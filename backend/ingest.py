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
import collections
import hashlib
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import batch_client
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
    """Never let a log line kill a round. The web app collects batches through this same code,
    and a uvicorn console on Windows is cp874 — one emoji there raised UnicodeEncodeError and
    took the whole collection down with it."""
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(enc, "replace").decode(enc, "replace"), flush=True)
    except Exception:  # noqa: BLE001 - logging must never be the thing that fails
        pass


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
                      "folder_name": folder_name, "folder_id": folder["id"],
                      "date_from": d_from, "date_to": d_to, "trip_date": None})
    for day in drive.list_folders(folder["id"]):
        dm = DATE_RE.match(day["name"].strip())
        if not dm:
            skipped.append(f"'{folder_name}/{day['name']}' ไม่ใช่วันที่ YYYY-MM-DD — ข้าม")
            continue
        for img in drive.list_images(day["id"]):
            items.append({"file": img, "rider": name, "week": week_label_, "category": category, "admin": admin,
                          "folder_name": folder_name, "folder_id": folder["id"],
                          "date_from": d_from, "date_to": d_to,
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


def keep_images_for_waiting(job_id, among=None, memory=None, drive=None) -> int:
    """Store the picture of every row this job left for a person, and nothing else.

    Photos are no longer copied into the database as a matter of course, but a row in the
    review queue is useless without one — Ops has to look at the slip to fix the number. Those
    are the ~2% worth keeping. The bytes come from this round's memory when they are still in
    hand, and from Drive when the reading happened in an earlier round via a batch."""
    ids = db.waiting_trip_ids(job_id, among=among)
    if not ids:
        return 0
    memory = memory or {}
    kept = 0
    missing = [t for t in ids if t not in memory]
    fetched = {}
    if missing and drive is not None:
        drive_ids = db.drive_ids_for_trips(missing)

        def one(tid):
            try:
                return tid, drive.download(drive_ids[tid]), "image/jpeg"
            except Exception:  # noqa: BLE001 - a missing picture must not fail the round
                return tid, None, None

        with ThreadPoolExecutor(max_workers=DRIVE_PARALLEL) as ex:
            for tid, data, mime in ex.map(one, [t for t in missing if t in drive_ids]):
                if data:
                    fetched[tid] = (data, mime)
    for tid in ids:
        got = memory.get(tid) or fetched.get(tid)
        if got:
            db.set_trip_image(tid, got[0], got[1])
            kept += 1
    return kept


def collect_batches(drive, exports_id=None):
    """Pick up whatever the batch queue has finished since the last round.

    drive=None collects without touching Drive — that is the web app's "เก็บผลตอนนี้" button,
    which can put the readings in front of Ops even when GitHub is not running rounds at all.

    Everything downstream of the reading — pairing, dates, customer images, auto-approve — runs
    here, because until the answers arrive there is nothing to pair or approve. A batch that
    failed or expired hands its images back as ordinary pending rows, which the next round
    reads the live way, so a bad batch costs time and not data."""
    open_jobs = db.open_batches()
    if not open_jobs:
        return 0, 0, set(), []
    done_trips = errors = 0
    issues, touched_jobs, waiting = [], set(), 0
    fresh_by_job = collections.defaultdict(list)   # read THIS round — a lone top waits one more
    for b in open_jobs:
        try:
            state, data, errs = batch_client.collect(b["name"])
        except Exception as e:  # noqa: BLE001
            log(f"  ✗ อ่านสถานะ batch {b['name'][-12:]} ไม่ได้: {str(e)[:120]}")
            errors += 1
            continue
        if not state.endswith(("SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED")):
            db.touch_batch(b["name"], state)
            waiting += b["n_trips"] or 0
            continue
        pairs = dict(db.batch_trip_jobs(b["name"]))
        for tid, jid in pairs.items():
            if tid in data:
                if pipeline.apply_extraction(tid, jid, data[tid]) == "done":
                    done_trips += 1
                else:
                    errors += 1
                fresh_by_job[jid].append(tid)
                touched_jobs.add(jid)
            elif tid in errs:
                pipeline.mark_trip_error(tid, jid, errs[tid])
                errors += 1
                issues.append((f"batch:{tid}", "process", f"batch อ่านรูป #{tid} ไม่สำเร็จ: {errs[tid]}"))
                touched_jobs.add(jid)
        left = [t for t in pairs if t not in data and t not in errs]
        note = None
        if left:
            # no answer for these — hand them back for the ordinary path to read next round
            note = f"ไม่ได้คำตอบ {len(left)} รูป — จะอ่านแบบปกติในรอบถัดไป"
            log(f"  ⚠ batch {b['name'][-12:]}: {note}")
        db.close_batch(b["name"], state, note)
        log(f"  📥 เก็บผล batch {b['name'][-12:]} ({state.replace('JOB_STATE_', '')}): "
            f"อ่านสำเร็จ {len(data)} · พลาด {len(errs)}")
    if waiting:
        log(f"  ⏳ ยังรอผล batch อีก {waiting} รูป — รอบถัดไปมาเก็บ")
    if touched_jobs:
        for jid, d1, d2 in db.jobs_dates(touched_jobs):
            # each job stands alone: one that throws used to abandon every job after it in this
            # loop, leaving their rows read but undated and unapproved — 420 rows on 2026-08-30
            try:
                pairs_n = pipeline.pair_fragments(jid)
                if d1 and d2:
                    pipeline.spread_dates(jid, d1, d2, only_missing=True)
                else:
                    log(f"  ⚠ job #{jid}: ไม่รู้ช่วงสัปดาห์ ข้ามการกระจายวันที่")
                st = db.auto_approve_job(jid, fresh_ids=fresh_by_job.get(jid, []))
                kept = keep_images_for_waiting(jid, drive=drive)
                log(f"  ✓ job #{jid}: จับคู่ {pairs_n} · อนุมัติอัตโนมัติ {st['approved']} · "
                    f"รอคน {st['flagged']}" + (f" · เก็บรูปให้แถวที่รอคน {kept}" if kept else ""))
            except Exception as e:  # noqa: BLE001
                errors += 1
                log(f"  ✗ job #{jid}: จัดการหลังอ่านไม่สำเร็จ — {str(e)[:150]}")
                issues.append((f"collect:{jid}", "process",
                               f"job #{jid}: เก็บผลแล้วแต่จับคู่/ลงวันที่/อนุมัติไม่สำเร็จ: {str(e)[:200]}"))
        if drive is None:
            # collected from the web app, which has no Drive credentials — the numbers are in,
            # but the customer images are not, and nothing would remember that. The issue log is
            # exactly the list a round retries, so leaving a note there is what brings them back.
            log("  ℹ เก็บผลจากหน้าเว็บ: รูปส่งลูกค้า/Excel บน Drive จะอัพเดตในรอบถัดไป")
            for jid in touched_jobs:
                issues.append((f"images:{jid}", "images",
                               f"job #{jid}: เก็บผลจากหน้าเว็บแล้ว ยังไม่ได้สร้างรูปส่งลูกค้า "
                               f"— รอบถัดไปจะสร้างให้"))
        else:
            errs2, failed = export_only(drive, exports_id, only_job_ids=touched_jobs, with_xlsx=False)
            errors += errs2
            for jid in failed:
                issues.append((f"images:{jid}", "images", f"อัพโหลดรูปส่งลูกค้า job #{jid} ไม่สำเร็จ"))
    return done_trips, errors, touched_jobs, issues


def export_only(drive, exports_id, only_job_ids=None, with_xlsx=True):
    """Regenerate Excel + customer images for jobs already in the database (no reading).
    only_job_ids limits the sweep; returns (error_count, failed_job_ids)."""
    errors = 0
    failed = []
    for (d_from, d_to), js in sorted(db.jobs_by_week().items()):
        wk = week_label(d_from)
        for j in js:
            if only_job_ids is not None and j["id"] not in only_job_ids:
                continue
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
                failed.append(j["id"])
    if with_xlsx:
        rows = db.query_trips(committed_only=True)
        try:
            fid = drive.upload_xlsx(exports_id, "Rider Trips.xlsx", excel_writer.build_workbook(rows))
            for (d_from, _), _js in db.jobs_by_week().items():
                db.record_drive_file(week_label(d_from), "xlsx", fid, "Rider Trips.xlsx")
            log(f"📄 Rider Trips.xlsx: {len(rows)} แถวรวมทุกสัปดาห์")
        except Exception as e:  # noqa: BLE001
            log(f"✗ upload xlsx: {e}")
            errors += 1
    return errors, failed


def cleanup(drive, exports_id, delete_job_ids=None, dedupe=False, delete_trip_ids=None) -> int:
    """User-ordered data cleanup: drop whole jobs (duplicate manual uploads) and/or remove
    approved rows that repeat a booking code for the same rider. Rewrites the workbook after."""
    if delete_job_ids:
        for r in db.delete_jobs(delete_job_ids):
            if r["found"]:
                log(f"🗑 ลบ job #{r['job_id']} {r['driver_name']} ({r['date_from']}) — {r['trips']} แถว")
            else:
                log(f"   (ไม่พบ job #{r['job_id']})")
    if delete_trip_ids:
        gone = db.delete_trips(delete_trip_ids)
        baht = sum(r.get("net", 0) for r in gone if r["found"])
        for r in gone:
            if r["found"]:
                log(f"🗑 ลบแถว #{r['id']} {r['driver_name']} {r['file_name']} "
                    f"(job #{r['job_id']}, ฿{r['net']:g}" +
                    (f", ครึ่งที่รวมไว้ {r['halves']} รูป)" if r["halves"] else ")"))
            else:
                log(f"   (ไม่พบแถว #{r['id']})")
        log(f"🧹 ลบแถวที่สั่งไว้ {sum(1 for r in gone if r['found'])} แถว (฿{baht:,.0f})")
    if dedupe:
        removed = db.dedupe_approved_trips()
        baht = sum(r["net"] for r in removed)
        for r in removed[:60]:
            log(f"🗑 ซ้ำ: {r['driver_name']} {r['file_name']} (job #{r['job_id']}, "
                f"code {r['code']}, ฿{r['net']:g})")
        if len(removed) > 60:
            log(f"   ... และอีก {len(removed) - 60} แถว")
        log(f"🧹 ลบแถวที่อนุมัติซ้ำของไรเดอร์คนเดียวกัน {len(removed)} แถว (฿{baht:,.0f})")
    rows = db.query_trips(committed_only=True)
    try:
        drive.upload_xlsx(exports_id, "Rider Trips.xlsx", excel_writer.build_workbook(rows))
        log(f"📄 อัพเดต Rider Trips.xlsx: เหลือ {len(rows)} แถว")
    except Exception as e:  # noqa: BLE001
        log(f"✗ upload xlsx: {e}")
        return 1
    return 0


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
            refill = "เติม Turbo" in (r["note"] or "")  # our own inference — replaceable
            if (r["turbo"] or 0) != 0 and not refill:
                continue
            gap = round(net - base - (r["bonus"] or 0), 2)
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
    cap = limit or config.MAX_NEW_PER_ROUND
    if cap and len(new) > cap:
        log(f"📦 รอบนี้รับ {cap} รูปก่อน (เหลือ {len(new) - cap} ใบให้รอบถัดไป — "
            f"กันไม่ให้รูปที่รอ batch กินพื้นที่ฐานข้อมูลเกินโควตา)")
        new = new[:cap]
    if run_id is not None:
        db.update_ingest_run_progress(run_id, files_total=len(new))
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

    jobs_created = approved = flagged = errors = submitted = 0
    processed_images = 0
    touched_weeks = set()

    if config.INGEST_BATCH or db.open_batches():
        got, errs, jobs_touched, batch_issues = collect_batches(drive, exports_id)
        errors += errs
        issues.extend(batch_issues)
        if got or jobs_touched:
            log(f"📥 เก็บผล batch รอบก่อน: อ่านได้ {got} รูป · {len(jobs_touched)} job")
            touched_weeks.update((d1, d2) for _j, d1, d2 in db.jobs_dates(jobs_touched))

    n_norm = db.normalize_booking_codes()
    if n_norm:
        log(f"🧹 ตัดช่องว่างใน booking code เดิม {n_norm} แถว (กันระบบจับซ้ำพลาด)")

    # a cancelled run leaves damage in two shapes: rows stuck in 'pending' (reprocess them
    # from the stored blobs — no re-download, no double billing), and jobs stuck in
    # 'running' whose pair/spread/approve steps never happened. Fix both before new work.
    stuck = db.stuck_pending_trips()
    if stuck:
        log(f"♻ เก็บตก {len(stuck)} แถวที่ค้างจากรอบก่อนซึ่งถูกตัดกลางทาง")
        stuck_ids = db.drive_ids_for_trips([t for t, _ in stuck])

        def _redo(x):
            tid, jid = x
            img = None
            if tid in stuck_ids:
                try:
                    img = (drive.download(stuck_ids[tid]), "image/jpeg")
                except Exception:  # noqa: BLE001 - fall back to a stored copy if there is one
                    img = None
            return pipeline.process_trip(tid, jid, img)

        with ThreadPoolExecutor(max_workers=INGEST_PARALLEL) as ex:
            res = list(ex.map(_redo, stuck))
        errors += res.count("error")
    redo_jobs = {j for _, j in stuck} | set(db.stale_running_jobs()) | set(db.jobs_missing_dates())
    if redo_jobs:
        for jid, d1, d2 in db.jobs_dates(redo_jobs):
            try:
                pipeline.pair_fragments(jid)
                if d1 and d2:
                    pipeline.spread_dates(jid, d1, d2, only_missing=True)
                st = db.auto_approve_job(jid)
                approved += st["approved"]
                flagged += st["flagged"]
                touched_weeks.add((d1, d2))
                log(f"  ♻ job #{jid}: จับคู่/อนุมัติย้อนหลัง — อนุมัติ {st['approved']} · รอคน {st['flagged']}")
            except Exception as e:  # noqa: BLE001
                errors += 1
                log(f"  ✗ job #{jid}: กู้ย้อนหลังไม่สำเร็จ — {type(e).__name__}: {str(e)[:150]}")
                issues.append((f"redo:{jid}", "process", f"job #{jid}: กู้ย้อนหลังไม่สำเร็จ: {str(e)[:200]}"))

    # the hidden-turbo backfill now runs EVERY round (no more manual checkbox needed) —
    # rows that slipped through under older, stricter conditions heal themselves here
    fix_hidden_turbo()

    # team rule 2026-08-25: rows once held for a photo-vs-folder vehicle conflict now log
    # per the photo — convert any old-style flagged rows before the approval sweep below
    n_money = pipeline.repair_money_reads()
    if n_money:
        log(f"🔧 ซ่อมตัวเลขที่อ่านพลาด {n_money} แถว (ฐานหาย / ค่าทางด่วนถูกนับเป็น Turbo)")
    n_svc = pipeline.repair_service_conflicts()
    if n_svc:
        log(f"🔁 บันทึกตามรูปให้ {n_svc} แถวที่เคยติดธงประเภทรถขัดกับโฟลเดอร์")

    # rule changes apply retroactively: re-run the (idempotent) auto-approve over every job
    # still in review, so rows that meet the CURRENT criteria stop waiting on a person
    swept_fail = 0
    for jid, d1, d2 in db.jobs_dates(db.review_job_ids()):
        # every job on its own: this loop runs near the end of a round, so one exception here
        # used to lose the dates, the approvals AND the issue sync for every job behind it —
        # 354 rows sat undated for three days because of exactly that
        try:
            if d1 and d2:
                pipeline.spread_dates(jid, d1, d2, only_missing=True)  # a failed collect left them bare
            st = db.auto_approve_job(jid)
            if st["approved"] or st.get("discarded"):
                approved += st["approved"]
                touched_weeks.add((d1, d2))
                bits = []
                if st["approved"]:
                    bits.append(f"อนุมัติเพิ่ม {st['approved']} แถว")
                if st.get("discarded"):
                    bits.append(f"ทิ้งรูปซ้ำที่นับไปแล้ว {st['discarded']} แถว")
                log(f"  ✚ job #{jid}: เกณฑ์ล่าสุด{' · '.join(bits)}")
        except Exception as e:  # noqa: BLE001
            swept_fail += 1
            errors += 1
            log(f"  ✗ job #{jid}: กวาดย้อนหลังไม่สำเร็จ — {type(e).__name__}: {str(e)[:150]}")
            issues.append((f"sweep:{jid}", "process",
                           f"job #{jid}: กวาดย้อนหลัง (ลงวันที่/อนุมัติ) ไม่สำเร็จ: {str(e)[:200]}"))
    if swept_fail:
        log(f"⚠ กวาดย้อนหลังพลาด {swept_fail} job — job อื่นไม่ได้รับผลกระทบ")

    broken = db.retryable_error_trips()
    if broken:
        log(f"♻ อ่านใหม่ {len(broken)} แถวที่รอบก่อนอ่านไม่สำเร็จ (Gemini ตอบ error ชั่วคราว)")
        ids = db.drive_ids_for_trips([t for t, _ in broken])

        def _reread(x):
            tid, jid = x
            img = None
            if tid in ids:
                try:
                    img = (drive.download(ids[tid]), "image/jpeg")
                except Exception:  # noqa: BLE001
                    return "error"
            return pipeline.process_trip(tid, jid, img)

        with ThreadPoolExecutor(max_workers=INGEST_PARALLEL) as ex:
            res = list(ex.map(_reread, broken))
        fixed = res.count("done")
        log(f"   อ่านสำเร็จ {fixed}/{len(broken)} แถว")
        for (tid, _), r in zip(broken, res):
            if r == "done":
                db.resolve_issue(f"batch:{tid}")
        errors += res.count("error")
        # redo_jobs was already consumed above, so these jobs are finished off here
        for jid, d1, d2 in db.jobs_dates({j for _t, j in broken}):
            try:
                pipeline.pair_fragments(jid)
                if d1 and d2:
                    pipeline.spread_dates(jid, d1, d2, only_missing=True)
                st = db.auto_approve_job(jid)
                if st["approved"]:
                    approved += st["approved"]
                    touched_weeks.add((d1, d2))
            except Exception as e:  # noqa: BLE001
                log(f"  ✗ job #{jid}: หลังอ่านซ้ำแล้วจัดการต่อไม่สำเร็จ — {str(e)[:120]}")

    orphan = db.waiting_trips_without_image()
    if orphan:
        by_job = collections.defaultdict(list)
        for tid, jid in orphan:
            by_job[jid].append(tid)
        got = sum(keep_images_for_waiting(jid, among=tids, drive=drive)
                  for jid, tids in by_job.items())
        log(f"🖼 ดึงรูปให้แถวที่รอคนตรวจ {got}/{len(orphan)} แถว (เก็บผลจากหน้าเว็บไม่มีสิทธิ์แตะ Drive)")

    # customer-image uploads that failed earlier (network blips) — the issue log promises the
    # next round retries them, so it does; still-failing jobs stay on the issue list
    retry_jobs = set(db.open_image_issue_jobs())
    if retry_jobs:
        log(f"🖼 ลองอัพโหลดรูปส่งลูกค้าซ้ำ {len(retry_jobs)} job ที่ค้างจากรอบก่อน")
        errs, still_failed = export_only(drive, exports_id, only_job_ids=retry_jobs, with_xlsx=False)
        errors += errs
        for jid in still_failed:
            issues.append((f"images:{jid}", "images", f"อัพโหลดรูปส่งลูกค้า job #{jid} ยังไม่สำเร็จ (ลองซ้ำแล้ว)"))
    for (rider, d_from, d_to), group in groups.items():
        meta = by_key[(rider, d_from, d_to)]
        folder_id = meta.get("folder_id")
        job_id = (db.find_job_by_folder(folder_id, d_from)
                  or db.find_job(rider, d_from, d_to, meta.get("category"), meta.get("admin")))
        if job_id is None:
            job_id = db.create_job(rider, excel_writer.SHEET, d_from, d_to,
                                   category=meta.get("category"), folder_name=meta.get("folder_name"),
                                   admin=meta.get("admin"), drive_folder_id=folder_id)
            jobs_created += 1
        else:
            moved = db.attach_folder(job_id, folder_id, rider, meta.get("folder_name"))
            if moved.get("renamed"):
                old_name, new_name = moved["renamed"]
                log(f"  ✎ โฟลเดอร์ถูกเปลี่ยนชื่อที่ต้นทาง: '{old_name}' → '{new_name}' "
                    f"— job #{job_id} ใช้ชื่อใหม่แล้ว (Excel/รูปส่งลูกค้าจะตามให้เอง)")
        db.set_job_status(job_id, "running")
        if re.fullmatch(r"\d+", rider or ""):
            # the folder is a bare number — Ops made it and never typed the name. The money is
            # real so it still gets read, but a rider called "01" ends up in Sheet1 and in the
            # customer image names, and renaming the folder later starts a SECOND job.
            msg = (f"โฟลเดอร์ '{meta.get('folder_name')}' ไม่มีชื่อไรเดอร์ (เป็นเลข '{rider}') — "
                   f"แก้ชื่อโฟลเดอร์บน Drive ให้มีชื่อคนก่อนรอบหน้า ไม่งั้นชื่อนี้จะไปโผล่ใน Excel")
            log(f"  ⚠ {msg}")
            issues.append((f"noname:{job_id}", "folder", msg))
        kk = (d_from, d_to, meta.get("category"), rider)
        dup_here = name_count.get(kk, 0) > 1 or db.name_shared_in_group(rider, d_from, d_to, meta.get("category"), job_id)
        display_names[job_id] = f"{rider}-{meta.get('admin')}" if (dup_here and meta.get("admin")) else rider
        log(f"job #{job_id} {rider} {d_from}..{d_to}: {len(group)} รูป")

        images = {}          # trip_id -> (bytes, mime) for this job, this round only

        def _dl(i):
            try:
                return i, drive.download(i["file"]["id"]), None
            except Exception as e:  # noqa: BLE001
                return i, None, e
        with ThreadPoolExecutor(max_workers=DRIVE_PARALLEL) as ex:
            downloads = list(ex.map(_dl, group))
        trip_ids = []
        seen_hashes = db.seen_image_hashes(rider, d_from, d_to)
        n_same = 0
        for i, data, err in downloads:
            f = i["file"]
            if err is not None:
                log(f"  ✗ download {f['name']}: {err}")
                issues.append((f"download:{f['id']}", "download", f"{rider}: โหลดรูป {f['name']} ไม่สำเร็จ ({err})"))
                errors += 1
                continue
            digest = hashlib.sha1(data).hexdigest()
            if digest in seen_hashes:
                # the very same picture already read for this rider this week (re-upload under a
                # new Drive id, or the same shot dropped in two folders) — record it as ingested
                # so it never comes back, but do not pay to read it again
                db.record_ingested(f["id"], f["name"], job_id, None)
                n_same += 1
                continue
            seen_hashes[digest] = f["name"]
            # the photo stays on Drive; only its bytes travel through this round in memory
            tid = db.create_trip(job_id, f["name"],
                                 data if config.STORE_DRIVE_IMAGES else None,
                                 f["mime"], source_url=f.get("url"), image_hash=digest)
            images[tid] = (data, f["mime"])
            if i["trip_date"]:
                db.update_trip(tid, {"trip_date": i["trip_date"]})
            db.record_ingested(f["id"], f["name"], job_id, tid)
            trip_ids.append(tid)

        if n_same:
            log(f"  ⏭ ข้ามรูปที่เนื้อหาซ้ำกับที่อ่านไปแล้ว {n_same} ใบ (ไม่เสียค่าอ่านซ้ำ)")

        if config.INGEST_BATCH and trip_ids:
            # hand the pile over and move on — the next round collects the answers and does the
            # pairing, images and approvals for this job
            try:
                items = [(tid, *images[tid]) for tid in trip_ids if tid in images]
                for b in batch_client.submit(items, display_name=f"job{job_id}",
                                             workers=DRIVE_PARALLEL):
                    db.record_batch(b["name"], b["model"], b["trips"], run_id)
                    submitted += len(b["trips"])
                log(f"  📤 ส่งเข้า batch {len(trip_ids)} รูป (ครึ่งราคา · ผลมารอบหน้า)")
            except Exception as e:  # noqa: BLE001
                log(f"  ✗ ส่ง batch ไม่สำเร็จ: {str(e)[:150]} — อ่านแบบปกติแทน")
                issues.append((f"batch:{job_id}", "process", f"ส่ง batch ของ {rider} ไม่สำเร็จ: {str(e)[:200]}"))
                with ThreadPoolExecutor(max_workers=INGEST_PARALLEL) as ex:
                    ex.map(lambda tid: pipeline.process_trip(tid, job_id, images.get(tid)), trip_ids)
            processed_images += len(group)
            db.update_ingest_run_progress(run_id, files_new=processed_images,
                                          auto_approved=approved, flagged=flagged)
            continue

        with ThreadPoolExecutor(max_workers=INGEST_PARALLEL) as ex:
            results = list(ex.map(lambda tid: pipeline.process_trip(tid, job_id, images.get(tid)),
                                  trip_ids))
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
            imgs = list(pipeline.customer_images(job_id, display, fetch=drive.download,
                                                 cache=images))
            with ThreadPoolExecutor(max_workers=DRIVE_PARALLEL) as ex:
                list(ex.map(lambda nd: drive.upload_file(cat_dir, nd[0], nd[1], "image/jpeg"), imgs))
            log(f"  🖼 รูปส่งลูกค้า {len(imgs)} ไฟล์ → Exports/{wk}/{meta.get('category') or 'อัปโหลดมือ'}/ (ชื่อ {display}N.jpg)")
        except Exception as e:  # noqa: BLE001
            log(f"  ✗ customer images: {e}")
            issues.append((f"images:{job_id}", "images", f"อัพโหลดรูปส่งลูกค้าของ {rider} ไม่สำเร็จ: {e}"))
            errors += 1

        stats = db.auto_approve_job(job_id, fresh_ids=trip_ids)
        keep_images_for_waiting(job_id, among=trip_ids, memory=images)
        approved += stats["approved"]
        flagged += stats["flagged"]
        touched_weeks.add((d_from, d_to))
        processed_images += len(group)
        db.update_ingest_run_progress(run_id, files_new=processed_images,
                                      auto_approved=approved, flagged=flagged)
        dup_note = f" · ทิ้งซ้ำอัตโนมัติ {stats['discarded']}" if stats.get("discarded") else ""
        log(f"  ✓ อนุมัติอัตโนมัติ {stats['approved']} · รอคน {stats['flagged']}{dup_note} · error {results.count('error')}")

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
    sub = f" · ส่งเข้า batch {submitted} (ผลมารอบหน้า)" if submitted else ""
    log(f"เสร็จใน {time.time() - t0:.0f}s — ใหม่ {len(new)} · อนุมัติอัตโนมัติ {approved} · "
        f"รอคน {flagged}{sub} · error {errors}")
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="drive", help="'drive' or 'local:<path to Inbox-like folder>'")
    ap.add_argument("--exports", default=None, help="exports folder id (drive) or path (local)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--exports-only", action="store_true", help="regenerate Excel + customer images for existing jobs")
    ap.add_argument("--exports-jobs", metavar="IDS",
                    help="regenerate customer images for these job ids only (comma-separated)")
    ap.add_argument("--fix-hidden-turbo", action="store_true",
                    help="DB-only maintenance: fill small net-base gaps (collapsed sections) into Turbo")
    ap.add_argument("--delete-jobs", metavar="IDS", help="comma-separated job ids to delete")
    ap.add_argument("--dedupe-approved", action="store_true",
                    help="delete approved rows repeating a booking code for the same rider")
    ap.add_argument("--delete-trips", metavar="IDS",
                    help="comma-separated trip ids to delete (team-verified repeats), then rewrite the xlsx")
    ap.add_argument("--redo-model", metavar="SUBSTR",
                    help="delete trips read by a model matching SUBSTR, then re-read them this run")
    ap.add_argument("--min-gap", type=float, metavar="HOURS",
                    help="do nothing if a round finished less than this many hours ago "
                         "(scheduled runs only — a person pressing the button always runs)")
    ap.add_argument("--only", help="comma-separated substrings of rider folder paths to process, e.g. '01 อภิชาติ,01 ปัญญา'")
    a = ap.parse_args()

    db.init_db()
    if a.min_gap:
        # GitHub fires roughly one scheduled run in three, and late. The answer is to let it try
        # every hour and have the round decide: if one finished recently there is nothing to do,
        # and saying so costs seconds instead of the minutes a real round takes.
        last = db.latest_ingest_run()
        if last and last.get("finished_at"):
            from datetime import datetime
            age = (datetime.now(db._TZ_BKK).replace(tzinfo=None)
                   - datetime.fromisoformat(last["finished_at"])).total_seconds() / 3600
            if age < a.min_gap:
                log(f"⏭ รอบล่าสุดเพิ่งจบไป {age:.1f} ชม. (เกณฑ์ {a.min_gap} ชม.) — ยังไม่ถึงเวลา ข้ามรอบนี้")
                sys.exit(0)
        elif last and not last.get("finished_at"):
            log("⏭ มีรอบกำลังรันอยู่ — ข้ามรอบนี้")
            sys.exit(0)
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
    if a.delete_jobs or a.dedupe_approved or a.delete_trips:
        ids = [int(x) for x in (a.delete_jobs or "").replace(" ", "").split(",") if x]
        tids = [int(x) for x in (a.delete_trips or "").replace(" ", "").split(",") if x]
        sys.exit(cleanup(drive, exports, delete_job_ids=ids, dedupe=a.dedupe_approved,
                         delete_trip_ids=tids))
    if a.exports_jobs:
        only = {int(x) for x in a.exports_jobs.replace(" ", "").split(",") if x}
        log(f"🖼 สร้างรูปส่งลูกค้าใหม่เฉพาะ job {sorted(only)}")
        errors, failed = export_only(drive, exports, only_job_ids=only)
        for jid in only - set(failed):
            db.resolve_issue(f"images:{jid}")
        sys.exit(1 if errors else 0)
    if a.exports_only:
        errors, _ = export_only(drive, exports)
    else:
        errors = run(drive, inbox, exports, dry_run=a.dry_run, limit=a.limit, only=a.only)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
