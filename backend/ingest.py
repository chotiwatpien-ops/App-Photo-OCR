# -*- coding: utf-8 -*-
"""Weekly ingest: Google Drive Inbox → Gemini → database → weekly Excel back to Drive.

Folder contract (under the Inbox folder):
    2026-W34/                      ISO week  -> trip dates default to that week's Monday
    └── กิตติพงศ์ สินประเสริฐ/      rider name
        ├── IMG_001.jpg
        └── 2026-08-04/            optional day sub-folder -> exact trip date
            └── IMG_002.jpg

Rows that pass every check are approved automatically; the rest wait in the web UI.
Safe to re-run: files are tracked by Drive file id, trips by booking code.

Usage:
    python ingest.py                      # Drive, env: GOOGLE_SERVICE_ACCOUNT_JSON, DRIVE_INBOX_FOLDER_ID, DRIVE_EXPORTS_FOLDER_ID
    python ingest.py --source local:PATH  # local folder tree with the same layout (testing)
    python ingest.py --dry-run            # list what would be processed
    python ingest.py --limit 20           # cap images this run
"""
import argparse
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import db
import excel_writer
import pipeline
from config import MAX_PARALLEL_EXTRACTIONS
from drive_client import DriveClient, LocalDrive

WEEK_RE = re.compile(r"(\d{4})-?W(\d{1,2})", re.IGNORECASE)
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def week_bounds(folder_name):
    m = WEEK_RE.search(folder_name)
    if not m:
        return None
    monday = date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    return monday, monday + timedelta(days=6)


def week_label(d_from: str) -> str:
    y, w, _ = date.fromisoformat(d_from).isocalendar()
    return f"{y}-W{w:02d}"


def clean_name(s):
    return re.sub(r"\s+", " ", s).strip()


def discover(drive, inbox_id):
    """Walk Inbox → weeks → riders (→ optional day folders) → images. Yields work items."""
    items, skipped = [], []
    for wk in drive.list_folders(inbox_id):
        bounds = week_bounds(wk["name"])
        if not bounds:
            skipped.append(f"โฟลเดอร์ '{wk['name']}' ไม่ใช่รูปแบบสัปดาห์ (เช่น 2026-W34) — ข้าม")
            continue
        monday, sunday = bounds
        for rider in drive.list_folders(wk["id"]):
            name = clean_name(rider["name"])
            if not name:
                continue
            for img in drive.list_images(rider["id"]):
                items.append({"file": img, "rider": name, "week": wk["name"],
                              "date_from": monday.isoformat(), "date_to": sunday.isoformat(),
                              "trip_date": None})  # spread over the week after pairing
            for day in drive.list_folders(rider["id"]):
                dm = DATE_RE.match(day["name"].strip())
                if not dm:
                    skipped.append(f"'{wk['name']}/{name}/{day['name']}' ไม่ใช่วันที่ YYYY-MM-DD — ข้าม")
                    continue
                for img in drive.list_images(day["id"]):
                    items.append({"file": img, "rider": name, "week": wk["name"],
                                  "date_from": monday.isoformat(), "date_to": sunday.isoformat(),
                                  "trip_date": day["name"].strip()})
    return items, skipped


def run(drive, inbox_id, exports_id, dry_run=False, limit=None):
    run_id = None if dry_run else db.start_ingest_run()
    t0 = time.time()
    items, skipped = discover(drive, inbox_id)
    seen = db.already_ingested(i["file"]["id"] for i in items)
    new = [i for i in items if i["file"]["id"] not in seen]
    log(f"พบรูป {len(items)} · ใหม่ {len(new)} · เคยอ่านแล้ว {len(items) - len(new)}")
    for s in skipped:
        log("⚠ " + s)
    if limit:
        new = new[:limit]
    if dry_run:
        for i in new[:50]:
            log(f"  would process {i['week']}/{i['rider']}/{i['file']['name']} → {i['trip_date'] or 'กระจายในสัปดาห์'}")
        return

    # group by rider+week → one job each (reused across runs so a week's photos stay together)
    groups = {}
    for i in new:
        groups.setdefault((i["rider"], i["date_from"], i["date_to"]), []).append(i)

    jobs_created = approved = flagged = errors = 0
    touched_weeks = set()
    for (rider, d_from, d_to), group in groups.items():
        job_id = db.find_job(rider, d_from, d_to)
        if job_id is None:
            job_id = db.create_job(rider, excel_writer.SHEET, d_from, d_to)
            jobs_created += 1
        db.set_job_status(job_id, "running")
        log(f"job #{job_id} {rider} {d_from}..{d_to}: {len(group)} รูป")

        trip_ids = []
        for i in group:
            f = i["file"]
            try:
                data = drive.download(f["id"])
            except Exception as e:  # noqa: BLE001
                log(f"  ✗ download {f['name']}: {e}")
                errors += 1
                continue
            tid = db.create_trip(job_id, f["name"], data, f["mime"], source_url=f.get("url"))
            if i["trip_date"]:
                db.update_trip(tid, {"trip_date": i["trip_date"]})
            db.record_ingested(f["id"], f["name"], job_id, tid)
            trip_ids.append(tid)

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_EXTRACTIONS) as ex:
            results = list(ex.map(lambda tid: pipeline.process_trip(tid, job_id), trip_ids))
        errors += results.count("error")
        pairs = pipeline.pair_fragments(job_id)
        if pairs:
            log(f"  ⧉ จับคู่รูปบน/ล่างได้ {pairs} งาน")
        dated = pipeline.spread_dates(job_id, d_from, d_to, only_missing=True)
        if dated:
            log(f"  📅 กระจาย {dated} งานลง จ–อา เท่าๆ กัน")

        # customer images: Exports/<week>/<rider>/<rider>1.jpg ... (before approval clears the blobs)
        try:
            rider_dir = drive.ensure_folder(drive.ensure_folder(exports_id, week_label(d_from)), rider)
            n_img = 0
            for name, data in pipeline.customer_images(job_id, rider):
                drive.upload_file(rider_dir, name, data, "image/jpeg")
                n_img += 1
            log(f"  🖼 รูปส่งลูกค้า {n_img} ไฟล์ → Exports/{week_label(d_from)}/{rider}/")
        except Exception as e:  # noqa: BLE001
            log(f"  ✗ customer images: {e}")
            errors += 1

        stats = db.auto_approve_job(job_id)
        approved += stats["approved"]
        flagged += stats["flagged"]
        touched_weeks.add((d_from, d_to))
        log(f"  ✓ อนุมัติอัตโนมัติ {stats['approved']} · รอคน {stats['flagged']} · error {results.count('error')}")

    # weekly workbooks back to Drive (all riders, approved rows only)
    for d_from, d_to in sorted(touched_weeks):
        rows = db.query_trips(date_from=d_from, date_to=d_to, committed_only=True)
        name = f"Rider Trips {week_label(d_from)}.xlsx"
        try:
            drive.upload_xlsx(exports_id, name, excel_writer.build_workbook(rows))
            log(f"📄 {name}: {len(rows)} แถว")
        except Exception as e:  # noqa: BLE001
            log(f"✗ upload {name}: {e}")
            errors += 1

    db.finish_ingest_run(run_id, files_new=len(new), files_skipped=len(items) - len(new),
                         jobs_created=jobs_created, auto_approved=approved, flagged=flagged,
                         errors=errors, notes="\n".join(skipped) or None)
    log(f"เสร็จใน {time.time() - t0:.0f}s — ใหม่ {len(new)} · อนุมัติอัตโนมัติ {approved} · รอคน {flagged} · error {errors}")
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="drive", help="'drive' or 'local:<path to Inbox-like folder>'")
    ap.add_argument("--exports", default=None, help="exports folder id (drive) or path (local)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    db.init_db()
    if a.source.startswith("local:"):
        root = a.source[6:]
        drive = LocalDrive(root)
        inbox, exports = root, a.exports or os.path.join(root, "..", "Exports")
    else:
        drive = DriveClient()
        inbox = os.environ["DRIVE_INBOX_FOLDER_ID"]
        exports = a.exports or os.environ["DRIVE_EXPORTS_FOLDER_ID"]
    errors = run(drive, inbox, exports, dry_run=a.dry_run, limit=a.limit)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
