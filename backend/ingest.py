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
import config
from config import DRIVE_PARALLEL, INGEST_PARALLEL
from drive_client import DriveClient, LocalDrive

WEEK_RE = re.compile(r"(\d{4})-?W(\d{1,2})", re.IGNORECASE)
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
# team layout: "01 สายยนต์ 3-9 Aug", "01ธัญณิชา 3-9 Aug", "02 ชื่อ 28 Jul-3 Aug"
RIDER_RANGE_RE = re.compile(
    r"^\s*(?:\d{1,3}\s*)?(?P<name>.+?)\s+(?P<d1>\d{1,2})\s*(?P<m1>[A-Za-z]{3,9})?\s*[-–]\s*(?P<d2>\d{1,2})\s*(?P<m2>[A-Za-z]{3,9})\s*(?P<y>\d{4})?\s*$")
# production layout: week folders "Week 10-16 Aug", "Week 31 Aug-6 Sep"
RANGE_RE = re.compile(
    r"(?P<d1>\d{1,2})\s*(?P<m1>[A-Za-z]{3,9})?\s*[-–]\s*(?P<d2>\d{1,2})\s*(?P<m2>[A-Za-z]{3,9})\s*(?P<y>\d{4})?\s*$")
ADMIN_RE = re.compile(r"^\s*admin\b\s*(?P<name>.*)$", re.IGNORECASE)
NUM_PREFIX_RE = re.compile(r"^\s*\d{1,3}\s*[-. ]\s*")
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
CATEGORIES = {"4 w standard", "4 w saver", "2 w standard", "2 w saver"}


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
    s = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", s or "")  # zero-width chars from LINE copy-paste
    return re.sub(r"\s+", " ", s).strip()


def rider_display_name(folder_name):
    """'07-นภสิทธิ์ ' -> 'นภสิทธิ์'; 'พลอย' -> 'พลอย'."""
    return clean_name(NUM_PREFIX_RE.sub("", clean_name(folder_name)))


def parse_range(text, default_year=None):
    """'10-16 Aug' / '31 Aug-6 Sep' / '3-9 Aug 2026' -> (date_from, date_to) or None."""
    m = RANGE_RE.search(text or "")
    if not m:
        return None
    m2 = MONTHS.get((m.group("m2") or "")[:3].lower())
    m1 = MONTHS.get((m.group("m1") or "")[:3].lower(), m2)
    if not m2:
        return None
    y = int(m.group("y") or default_year or date.today().year)
    try:
        d1, d2 = date(y, m1, int(m.group("d1"))), date(y, m2, int(m.group("d2")))
    except ValueError:
        return None
    if d2 < d1:
        d2 = d2.replace(year=y + 1)
    return d1, d2


def parse_rider_folder(name, default_year=None):
    """'01 สายยนต์ 3-9 Aug' -> ('สายยนต์', date(2026,8,3), date(2026,8,9)) or None."""
    m = RIDER_RANGE_RE.match(name)
    if not m:
        return None
    m2 = MONTHS.get((m.group("m2") or "")[:3].lower())
    m1 = MONTHS.get((m.group("m1") or "")[:3].lower(), m2)
    if not m2:
        return None
    y = int(m.group("y") or default_year or date.today().year)
    try:
        d1, d2 = date(y, m1, int(m.group("d1"))), date(y, m2, int(m.group("d2")))
    except ValueError:
        return None
    if d2 < d1:
        d1 = d1.replace(year=y - 1)
    return clean_name(m.group("name")), d1, d2


def _rider_items(drive, folder, name, week_label_, d_from, d_to, category, skipped, folder_name, admin=None):
    items = []
    for img in drive.list_images(folder["id"]):
        items.append({"file": img, "rider": name, "week": week_label_, "category": category, "admin": admin,
                      "folder_name": folder_name, "date_from": d_from, "date_to": d_to, "trip_date": None})
    for day in drive.list_folders(folder["id"]):
        dm = DATE_RE.match(day["name"].strip())
        if not dm:
            skipped.append(f"'{folder_name}/{day['name']}' ไม่ใช่วันที่ YYYY-MM-DD — ข้าม")
            continue
        for img in drive.list_images(day["id"]):
            items.append({"file": img, "rider": name, "week": week_label_, "category": category, "admin": admin,
                          "folder_name": folder_name, "date_from": d_from, "date_to": d_to,
                          "trip_date": day["name"].strip()})
    return items


def _discover_category(drive, cat_folder, category, d_from, d_to, wk_name, skipped, items):
    """Children of a category folder are either Admin folders (production) or rider folders."""
    for child in drive.list_folders(cat_folder["id"]):
        adm = ADMIN_RE.match(clean_name(child["name"]))
        if adm:
            admin = adm.group("name").strip() or child["name"].strip()
            for rider in drive.list_folders(child["id"]):
                name = rider_display_name(rider["name"])
                if not name:
                    continue
                items += _rider_items(drive, rider, name, wk_name, d_from, d_to, category, skipped,
                                      f"{category}/{clean_name(child['name'])}/{clean_name(rider['name'])}", admin=admin)
            continue
        # rider folder directly under the category (older layout, may carry its own date range)
        parsed = parse_rider_folder(child["name"])
        if parsed:
            name, r1, r2 = parsed
            items += _rider_items(drive, child, name, week_label(r1.isoformat()), r1.isoformat(), r2.isoformat(),
                                  category, skipped, f"{category}/{clean_name(child['name'])}")
        elif d_from:
            name = rider_display_name(child["name"])
            items += _rider_items(drive, child, name, wk_name, d_from, d_to, category, skipped,
                                  f"{category}/{clean_name(child['name'])}")
        else:
            skipped.append(f"'{category}/{child['name']}' อ่านชื่อ/ช่วงวันที่ไม่ออก — ข้าม")


def discover(drive, inbox_id):
    """Walk the Inbox. Two layouts are understood:
      A) Inbox/<YYYY-Www>/<rider>/[YYYY-MM-DD/]*.jpg
      B) Inbox/<4 W Standard|4 W Saver|2 W Standard|2 W Saver>/<NN name D-D Mon>/*.jpg   (the team's)
    Returns (items, skipped-warnings)."""
    import config as _cfg
    items, skipped = [], []
    for top in drive.list_folders(inbox_id):
        if top["id"] == (_cfg.DRIVE_EXPORTS_FOLDER_ID or ""):
            continue  # the Exports folder lives inside the Inbox — never read our own outputs
        top_name = clean_name(top["name"])
        rng = parse_range(top_name) if top_name.lower().startswith("week") else None
        if rng:  # production: Week D-D Mon / <category> / <Admin X> / <rider>
            d1, d2 = rng
            wk = week_label(d1.isoformat())
            for cat in drive.list_folders(top["id"]):
                if clean_name(cat["name"]).lower() in CATEGORIES:
                    _discover_category(drive, cat, clean_name(cat["name"]), d1.isoformat(), d2.isoformat(), wk, skipped, items)
                else:
                    skipped.append(f"'{top['name']}/{cat['name']}' ไม่ใช่กลุ่มรถ (4 W Standard ...) — ข้าม")
            continue
        bounds = week_bounds(top["name"])
        if bounds:  # layout A
            monday, sunday = bounds
            for rider in drive.list_folders(top["id"]):
                parsed = parse_rider_folder(rider["name"])
                name = parsed[0] if parsed else clean_name(rider["name"])
                items += _rider_items(drive, rider, name, top["name"], monday.isoformat(), sunday.isoformat(),
                                      None, skipped, f"{top['name']}/{rider['name']}")
            continue
        if clean_name(top["name"]).lower() in CATEGORIES:  # layout B (test folder)
            _discover_category(drive, top, clean_name(top["name"]), None, None, None, skipped, items)
            continue
        skipped.append(f"โฟลเดอร์ '{top['name']}' ไม่ใช่สัปดาห์ (2026-W34) หรือกลุ่มรถ (4 W Standard ...) — ข้าม")
    return items, skipped


def export_only(drive, exports_id):
    """Regenerate Excel + customer images for every job already in the database (no reading)."""
    errors = 0
    for (d_from, d_to), js in sorted(db.jobs_by_week().items()):
        wk = week_label(d_from)
        for j in js:
            try:
                week_dir = drive.ensure_folder(exports_id, wk)
                db.record_drive_file(wk, "week_folder", week_dir)
                cat_dir = drive.ensure_folder(week_dir, j.get("category") or "อัปโหลดมือ")
                db.record_drive_file(wk, "rider_folder", cat_dir, j.get("category"), ref=j["id"])
                dup = sum(1 for x in js if x["driver_name"] == j["driver_name"] and x.get("category") == j.get("category")) > 1
                display = f"{j['driver_name']}-{j.get('admin')}" if (dup and j.get("admin")) else j["driver_name"]
                imgs = list(pipeline.customer_images(j["id"], display, fetch=drive.download))
                with ThreadPoolExecutor(max_workers=DRIVE_PARALLEL) as ex:
                    list(ex.map(lambda nd: drive.upload_file(cat_dir, nd[0], nd[1], "image/jpeg"), imgs))
                log(f"🖼 {display}: {len(imgs)} รูป → Exports/{wk}/{j.get('category') or 'อัปโหลดมือ'}/")
            except Exception as e:  # noqa: BLE001
                log(f"✗ images {j['driver_name']}: {e}")
                errors += 1
    rows = db.query_trips(committed_only=True)
    try:
        fid = drive.upload_xlsx(exports_id, "Rider Trips.xlsx", excel_writer.build_workbook(rows))
        for (d_from, _), _js in db.jobs_by_week().items():
            db.record_drive_file(week_label(d_from), "xlsx", fid, "Rider Trips.xlsx")
        log(f"📄 Rider Trips.xlsx: {len(rows)} แถวรวมทุกสัปดาห์")
    except Exception as e:  # noqa: BLE001
        log(f"✗ upload xlsx: {e}")
        errors += 1
    return errors


def fix_hidden_turbo() -> int:
    """Maintenance pass (no Drive, no Gemini): waiting rows that fail the check with a small
    positive net−base gap and bonus/turbo both 0 are the 'collapsed-accordion' family — the
    ~5% surge hidden in a folded section. Fill the gap into Turbo with an audit note; the row
    still waits for a person to approve."""
    from sqlalchemy import select, update
    note_txt = "เติม Turbo จากส่วนต่าง net−base (รูปพับหัวข้อรายได้เพิ่มเติม — เลขไม่โชว์ในรูป)"
    fixed = 0
    with db.engine.begin() as c:
        t = db.trips.c
        rows = c.execute(select(t.id, t.file_name, t.net_earnings, t.base_fare, t.bonus,
                                t.turbo, t.note)
                         .where(t.status == "done", t.committed == 0,
                                t.check_status == "fail")).mappings().all()
        for r in rows:
            net, base = r["net_earnings"], r["base_fare"]
            if net is None or base is None or base <= 0:
                continue
            if (r["bonus"] or 0) != 0 or (r["turbo"] or 0) != 0:
                continue
            gap = round(net - base, 2)
            if not (0 < gap <= round(0.20 * base, 2)):  # same 20%-of-base cap as the pipeline
                continue
            note = f"{note_txt} | {r['note']}" if r["note"] else note_txt
            c.execute(update(db.trips).where(t.id == r["id"])
                      .values(turbo=gap, check_status="pass", note=note))
            log(f"  ✓ #{r['id']} {r['file_name']}: turbo 0→{gap}")
            fixed += 1
    log(f"เติม Turbo จากส่วนต่างให้ {fixed} แถว — รอคนกดอนุมัติในคิวตรวจ")
    return 0


def run(drive, inbox_id, exports_id, dry_run=False, limit=None, only=None):
    run_id = None if dry_run else db.start_ingest_run()
    t0 = time.time()
    issues = []  # (key, kind, message) — synced to ingest_issues at the end (auto-resolve)
    items, skipped = discover(drive, inbox_id)
    issues += [(f"folder:{s}", "folder", s) for s in skipped]
    if only:
        keys = [k.strip() for k in only.split(",") if k.strip()]
        items = [i for i in items if any(k in (i.get("folder_name") or i["rider"]) for k in keys)]
        log(f"--only {keys}: เหลือ {len(items)} รูป")
    seen = db.already_ingested(i["file"]["id"] for i in items)
    new = [i for i in items if i["file"]["id"] not in seen]
    log(f"พบรูป {len(items)} · ใหม่ {len(new)} · เคยอ่านแล้ว {len(items) - len(new)}")
    for s in skipped:
        log("⚠ " + s)
    if limit:
        new = new[:limit]
    if dry_run:
        for i in new[:50]:
            log(f"  would process [{i.get('category') or '-'}] {i['rider']} {i['date_from']}..{i['date_to']} / {i['file']['name']}")
        return

    # group by rider+week → one job each (reused across runs so a week's photos stay together)
    groups = {}
    for i in new:
        groups.setdefault((i["rider"], i["date_from"], i["date_to"]), []).append(i)
    by_key = {k: v[0] for k, v in groups.items()}  # category / folder_name for the group
    # riders sharing a display name inside the same week+vehicle group get an -Admin suffix
    name_count = {}
    for (rider, d_from, d_to), v in groups.items():
        kk = (d_from, d_to, v[0].get("category"), rider)
        name_count[kk] = name_count.get(kk, 0) + 1
    display_names = {}

    jobs_created = approved = flagged = errors = 0
    touched_weeks = set()

    n_norm = db.normalize_booking_codes()
    if n_norm:
        log(f"🧹 ตัดช่องว่างใน booking code เดิม {n_norm} แถว (กันระบบจับซ้ำพลาด)")

    # a cancelled run leaves damage in two shapes: rows stuck in 'pending' (reprocess them
    # from the stored blobs — no re-download, no double billing), and jobs stuck in
    # 'running' whose pair/spread/approve steps never happened. Fix both before new work.
    stuck = db.stuck_pending_trips()
    if stuck:
        log(f"♻ เก็บตก {len(stuck)} แถวที่ค้างจากรอบก่อนซึ่งถูกตัดกลางทาง")
        with ThreadPoolExecutor(max_workers=INGEST_PARALLEL) as ex:
            res = list(ex.map(lambda x: pipeline.process_trip(x[0], x[1]), stuck))
        errors += res.count("error")
    redo_jobs = {j for _, j in stuck} | set(db.stale_running_jobs())
    if redo_jobs:
        for jid, d1, d2 in db.jobs_dates(redo_jobs):
            pipeline.pair_fragments(jid)
            pipeline.spread_dates(jid, d1, d2, only_missing=True)
            st = db.auto_approve_job(jid)
            approved += st["approved"]
            flagged += st["flagged"]
            touched_weeks.add((d1, d2))
            log(f"  ♻ job #{jid}: จับคู่/อนุมัติย้อนหลัง — อนุมัติ {st['approved']} · รอคน {st['flagged']}")
    for (rider, d_from, d_to), group in groups.items():
        meta = by_key[(rider, d_from, d_to)]
        job_id = db.find_job(rider, d_from, d_to)
        if job_id is None:
            job_id = db.create_job(rider, excel_writer.SHEET, d_from, d_to,
                                   category=meta.get("category"), folder_name=meta.get("folder_name"),
                                   admin=meta.get("admin"))
            jobs_created += 1
        db.set_job_status(job_id, "running")
        kk = (d_from, d_to, meta.get("category"), rider)
        dup_here = name_count.get(kk, 0) > 1 or db.name_shared_in_group(rider, d_from, d_to, meta.get("category"), job_id)
        display_names[job_id] = f"{rider}-{meta.get('admin')}" if (dup_here and meta.get("admin")) else rider
        log(f"job #{job_id} {rider} {d_from}..{d_to}: {len(group)} รูป")

        def _dl(i):
            try:
                return i, drive.download(i["file"]["id"]), None
            except Exception as e:  # noqa: BLE001
                return i, None, e
        with ThreadPoolExecutor(max_workers=DRIVE_PARALLEL) as ex:
            downloads = list(ex.map(_dl, group))
        trip_ids = []
        for i, data, err in downloads:
            f = i["file"]
            if err is not None:
                log(f"  ✗ download {f['name']}: {err}")
                issues.append((f"download:{f['id']}", "download", f"{rider}: โหลดรูป {f['name']} ไม่สำเร็จ ({err})"))
                errors += 1
                continue
            tid = db.create_trip(job_id, f["name"], data, f["mime"], source_url=f.get("url"))
            if i["trip_date"]:
                db.update_trip(tid, {"trip_date": i["trip_date"]})
            db.record_ingested(f["id"], f["name"], job_id, tid)
            trip_ids.append(tid)

        with ThreadPoolExecutor(max_workers=INGEST_PARALLEL) as ex:
            results = list(ex.map(lambda tid: pipeline.process_trip(tid, job_id), trip_ids))
        errors += results.count("error")
        for tid, res in zip(trip_ids, results):
            if res == "error":
                issues.append((f"process:{tid}", "process",
                               f"{rider} (job #{job_id}): อ่านรูป #{tid} ไม่สำเร็จ"))
        pairs = pipeline.pair_fragments(job_id)
        if pairs:
            log(f"  ⧉ จับคู่รูปบน/ล่างได้ {pairs} งาน")
        dated = pipeline.spread_dates(job_id, d_from, d_to, only_missing=True)
        if dated:
            log(f"  📅 กระจาย {dated} งานลง จ–อา เท่าๆ กัน")

        # customer images: Exports/<week>/<vehicle type>/ — all riders' images in one folder,
        # named '<rider><n>.jpg' ('<rider>-<admin><n>.jpg' when two riders share a name in the group)
        try:
            wk = week_label(d_from)
            week_dir = drive.ensure_folder(exports_id, wk)
            db.record_drive_file(wk, "week_folder", week_dir)
            cat_dir = drive.ensure_folder(week_dir, meta.get("category") or "อัปโหลดมือ")
            db.record_drive_file(wk, "rider_folder", cat_dir, meta.get("category"), ref=job_id)
            display = display_names.get(job_id, rider)
            imgs = list(pipeline.customer_images(job_id, display, fetch=drive.download))
            with ThreadPoolExecutor(max_workers=DRIVE_PARALLEL) as ex:
                list(ex.map(lambda nd: drive.upload_file(cat_dir, nd[0], nd[1], "image/jpeg"), imgs))
            log(f"  🖼 รูปส่งลูกค้า {len(imgs)} ไฟล์ → Exports/{wk}/{meta.get('category') or 'อัปโหลดมือ'}/ (ชื่อ {display}N.jpg)")
        except Exception as e:  # noqa: BLE001
            log(f"  ✗ customer images: {e}")
            issues.append((f"images:{job_id}", "images", f"อัพโหลดรูปส่งลูกค้าของ {rider} ไม่สำเร็จ: {e}"))
            errors += 1

        stats = db.auto_approve_job(job_id)
        approved += stats["approved"]
        flagged += stats["flagged"]
        touched_weeks.add((d_from, d_to))
        log(f"  ✓ อนุมัติอัตโนมัติ {stats['approved']} · รอคน {stats['flagged']} · error {results.count('error')}")

    # ONE continuous workbook for the whole project (all weeks appended). Regenerated EVERY
    # run — not just when new photos arrived — so edits/approvals made in the web app between
    # runs always reach the Drive copy too.
    rows = db.query_trips(committed_only=True)
    if rows:
        name = "Rider Trips.xlsx"
        try:
            fid = drive.upload_xlsx(exports_id, name, excel_writer.build_workbook(rows))
            for (d_from, _), _js in db.jobs_by_week().items():
                db.record_drive_file(week_label(d_from), "xlsx", fid, name)
            log(f"📄 {name}: {len(rows)} แถวรวมทุกสัปดาห์")
        except Exception as e:  # noqa: BLE001
            log(f"✗ upload {name}: {e}")
            issues.append(("xlsx", "xlsx", f"อัพโหลด {name} ขึ้น Drive ไม่สำเร็จ: {e}"))
            errors += 1

    db.sync_ingest_issues(run_id, issues)
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
    ap.add_argument("--exports-only", action="store_true", help="regenerate Excel + customer images for existing jobs")
    ap.add_argument("--fix-hidden-turbo", action="store_true",
                    help="DB-only maintenance: fill small net-base gaps (collapsed sections) into Turbo")
    ap.add_argument("--redo-model", metavar="SUBSTR",
                    help="delete trips read by a model matching SUBSTR, then re-read them this run")
    ap.add_argument("--only", help="comma-separated substrings of rider folder paths to process, e.g. '01 อภิชาติ,01 ปัญญา'")
    a = ap.parse_args()

    db.init_db()
    if a.fix_hidden_turbo:
        sys.exit(fix_hidden_turbo())
    if a.redo_model:
        st = db.delete_model_trips(a.redo_model)
        log(f"🔁 redo '{a.redo_model}': ลบ {st['trips']} แถว · {st['files']} ไฟล์บันทึก · "
            f"{st['jobs']} job ว่าง — จะอ่านซ้ำด้วยโมเดลปัจจุบันในรอบนี้เลย")
    if a.source.startswith("local:"):
        root = a.source[6:]
        drive = LocalDrive(root)
        inbox, exports = root, a.exports or os.path.join(root, "..", "Exports")
    else:
        if not (config.GOOGLE_SERVICE_ACCOUNT or config.DRIVE_OAUTH_TOKEN):
            sys.exit("ไม่พบ credentials: วาง drive_token.json (จาก drive_auth.py) หรือ service_account.json ไว้ในโฟลเดอร์โปรเจกต์")
        if not (config.DRIVE_INBOX_FOLDER_ID and (a.exports or config.DRIVE_EXPORTS_FOLDER_ID)):
            sys.exit("ไม่พบ folder id: ใส่ drive_inbox_folder_id / drive_exports_folder_id ใน photo_ocr_config.json")
        drive = DriveClient(config.GOOGLE_SERVICE_ACCOUNT, config.DRIVE_OAUTH_TOKEN)
        log(f"Drive auth: {drive.mode}" + ("" if drive.mode == "oauth" else "  (service account = อ่านได้ เขียนไม่ได้ — รัน drive_auth.py เพื่อเขียนกลับ)"))
        inbox = config.DRIVE_INBOX_FOLDER_ID
        exports = a.exports or config.DRIVE_EXPORTS_FOLDER_ID
    if a.exports_only:
        errors = export_only(drive, exports)
    else:
        errors = run(drive, inbox, exports, dry_run=a.dry_run, limit=a.limit, only=a.only)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
