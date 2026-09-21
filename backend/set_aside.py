# -*- coding: utf-8 -*-
"""Take one rider's trips out of a week and deliver them on their own, dated into another week.

Ops, 2026-09-21: 20 urgent "งานแก้" (fix-up) trips in 2 W Saver, taken from ONE rider, out of W38,
as a file of their own with a folder holding only their pictures; W38's count drops by them
(Ops fills W38 back up themselves), and the dates in the new file lie in 24–30 Aug.

What happens, per row:
  1. status becomes 'set_aside'. Every weekly file, count, scorecard and the review queue take
     'done' rows only, so the row leaves W38 everywhere at once — and, dated into August, it is
     never pulled into the closed first workbook either (build_workbook also takes 'done' only).
     Nothing is deleted: the row keeps its money, booking code and a note of where it came from.
  2. it moves to a job of its own under the new dates, same rider and group.
  3. the date: spread across the new week in the order the trips were driven
     (redate_to_week.spread); the slip's own day stays in the note.
  4. the delivered picture: a copy under a name of the new week (WK35-สรธร Home1.jpg …) goes into
     the batch folder, and the old one leaves the week's Export Pic for _แทนที่แล้ว, as a carry
     does. Drive cannot rename, so the copy is made from the bytes.
  5. the stitched original leaves the week's rider folder for the batch folder's _ต้นฉบับ, so
     the week's folders hold only the week's work.
Then the batch's own workbook, in the Phase 3 layout, is written into the same folder.

    python set_aside.py --rider "สรธร Home" --group "2 W Saver" --from 2026-09-14 --to 2026-09-20 \\
        --new-from 2026-08-24 --new-to 2026-08-30 --name "งานแก้ 2W Saver 24-30 Aug"     # report
    python set_aside.py ... --apply
"""
import argparse
import sys
from collections import Counter
from datetime import date

from sqlalchemy import select

import db
import excel_writer
import redate_to_week

STATUS = "set_aside"
EXPORT_ROOT = "Export Pic"
REPLACED_DIR = "_แทนที่แล้ว"
ORIGINALS_DIR = "_ต้นฉบับ"


def week_label(d_from):
    y, w, _ = date.fromisoformat(d_from).isocalendar()
    return f"{y}-W{w:02d}"


def picked_rows(rider, group, d_from, d_to):
    """[(row, job)] — the rider's finished, approved rows in that group and week, driven order."""
    jobs = {j["id"]: j for j in db.jobs_by_week().get((d_from, d_to), [])
            if (j.get("driver_name") or "").strip() == rider.strip()
            and (j.get("category") or "").strip() == group}
    if not jobs:
        return []
    t = db.trips.c
    with db.engine.begin() as c:
        rows = [dict(r) for r in c.execute(
            select(t.id, t.job_id, t.file_name, t.trip_date, t.trip_time, t.customer_image,
                   t.note, t.service_type, t.committed)
            .where(t.job_id.in_(list(jobs)), t.status == "done")).mappings().all()]
    rows.sort(key=lambda r: (r.get("trip_date") or "", r.get("trip_time") or "", r["id"]))
    return [(r, jobs[r["job_id"]]) for r in rows]


def new_names(plan, rider, new_from):
    """{row id: picture name} numbered in the new date order, under the new week's prefix."""
    wk = int(week_label(new_from).split("W")[1])
    return {r["id"]: f"WK{wk}-{rider}{i}.jpg" for i, (r, _new) in enumerate(plan, start=1)}


def batch_rows(job_id):
    """The batch's rows as the workbook wants them (driver name joined)."""
    t, j = db.trips.c, db.jobs.c
    with db.engine.begin() as c:
        return [dict(r) for r in c.execute(
            select(*db.TRIP_COLS, j.driver_name)
            .select_from(db.trips.join(db.jobs, j.id == t.job_id))
            .where(t.job_id == job_id, t.status == STATUS)
            .order_by(t.trip_date, t.trip_time, t.id)).mappings().all()]


def apply(drive, inbox_id, picked, rider, group, d_from, d_to, new_from, new_to, name, log=print):
    done = Counter()
    exp_root = next((f["id"] for f in drive.list_folders(inbox_id) if f["name"].strip() == EXPORT_ROOT), None)
    if exp_root is None:
        exp_root = drive.ensure_folder(inbox_id, EXPORT_ROOT)
    batch_dir = drive.ensure_folder(exp_root, name)
    originals = drive.ensure_folder(batch_dir, ORIGINALS_DIR)
    week_dir = next((f["id"] for f in drive.list_folders(exp_root) if f["name"] == week_label(d_from)), None)
    group_dir = (next((f["id"] for f in drive.list_folders(week_dir) if f["name"].strip() == group), None)
                 if week_dir else None)
    delivered = {i["name"]: i["id"] for i in drive.list_images(group_dir)} if group_dir else {}
    replaced = drive.ensure_folder(week_dir, REPLACED_DIR) if week_dir else None

    rows = [r for r, _j in picked]
    plan = redate_to_week.spread(rows, new_from, new_to)
    names = new_names(plan, rider, new_from)
    jid = db.create_job(rider, "Trips", new_from, new_to, category=group,
                        folder_name=f"{name}/{rider}", drive_folder_id=batch_dir)
    db.set_job_status(jid, "committed")
    log(f"  + job #{jid} {rider} · {group} · {new_from}..{new_to} ({name})")

    src_listing = {}
    for r, new_day in plan:
        job = next(j for rr, j in picked if rr["id"] == r["id"])
        # the stitched original, out of the week's rider folder
        src = job.get("drive_folder_id")
        if src and src not in src_listing:
            src_listing[src] = {i["name"]: i["id"] for i in drive.list_images(src)}
        pic = src_listing.get(src, {}).get(r["file_name"]) if src else None
        if pic:
            drive.move_file(pic, originals)
            done["ย้ายรูปรวมร่าง"] += 1
        else:
            done["หารูปรวมร่างไม่เจอ"] += 1
        # the delivered picture: a copy under the new week's name, the old one set aside
        new_pic = names[r["id"]]
        old_id = delivered.get(r.get("customer_image") or "")
        if old_id:
            drive.create_file(batch_dir, new_pic, drive.download(old_id), "image/jpeg")
            drive.move_file(old_id, replaced)
            done["รูปส่งลูกค้าชื่อใหม่"] += 1
        else:
            done["หารูปส่งลูกค้าเดิมไม่เจอ"] += 1
        note = (f"{name}: ดึงออกจากสัปดาห์ {d_from}..{d_to} (job #{job['id']}) · "
                f"วันที่บนสลิป {r.get('trip_date')} → ลงเป็น {new_day}")
        db.move_trips_to_job([r["id"]], jid)
        db.update_trip(r["id"], {"status": STATUS, "trip_date": new_day,
                                 "customer_image": new_pic if old_id else None,
                                 "note": f"{note} | {r['note']}" if r.get("note") else note})
        done["ย้ายแถว"] += 1

    data = excel_writer.build_fare_lines_workbook(batch_rows(jid), every_week=True)
    file_name = f"Rider Trips {name}.xlsx"
    if data:
        drive.upload_xlsx(batch_dir, file_name, data)
        done["เขียนไฟล์"] += 1
    log(f"  📄 {EXPORT_ROOT}/{name}/{file_name}")
    return done, jid


def main(argv=None):
    ap = argparse.ArgumentParser(description="ดึงงานของไรเดอร์คนหนึ่งออกจากสัปดาห์ ไปเป็นไฟล์และโฟลเดอร์รูปของตัวเอง")
    ap.add_argument("--rider", required=True)
    ap.add_argument("--group", required=True, help="เช่น 2 W Saver")
    ap.add_argument("--from", dest="d_from", required=True, help="สัปดาห์ที่ดึงออก: วันแรก")
    ap.add_argument("--to", dest="d_to", required=True, help="สัปดาห์ที่ดึงออก: วันสุดท้าย")
    ap.add_argument("--new-from", required=True, help="วันที่ในไฟล์ใหม่: วันแรก")
    ap.add_argument("--new-to", required=True, help="วันที่ในไฟล์ใหม่: วันสุดท้าย")
    ap.add_argument("--name", required=True, help="ชื่อชุดงาน = ชื่อโฟลเดอร์และไฟล์")
    ap.add_argument("--expect", type=int, default=None, help="จำนวนงานที่ต้องได้ ถ้าไม่ตรงจะไม่ทำ")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    db.init_db()
    picked = picked_rows(a.rider, a.group, a.d_from, a.d_to)
    print(f"{a.rider} · {a.group} · {a.d_from}..{a.d_to}: {len(picked)} งาน")
    for (svc, ok), n in Counter(((r.get("service_type") or "?"), bool(r.get("committed")))
                                for r, _j in picked).most_common():
        print(f"    {svc} {'อนุมัติแล้ว' if ok else 'ยังไม่อนุมัติ'}: {n}")
    if not picked:
        print("✗ ไม่พบงาน")
        return 1
    if a.expect is not None and len(picked) != a.expect:
        print(f"✗ ได้ {len(picked)} งาน ไม่ตรงกับที่สั่ง {a.expect} — ไม่ทำอะไร")
        return 1
    plan = redate_to_week.spread([r for r, _j in picked], a.new_from, a.new_to)
    names = new_names(plan, a.rider, a.new_from)
    print(f"\nลงวันที่ใหม่ {a.new_from}..{a.new_to} · ชื่อรูปใหม่:")
    for r, new in plan:
        print(f"    #{r['id']} {r.get('trip_date')} → {new}   {r.get('customer_image')} → {names[r['id']]}")
    if not a.apply:
        print("\n(รายงานอย่างเดียว — ใส่ --apply เพื่อทำจริง)")
        return 0
    import config
    import roster
    drive = roster._drive()
    done, jid = apply(drive, config.DRIVE_INBOX_FOLDER_ID, picked, a.rider, a.group, a.d_from, a.d_to,
                      a.new_from, a.new_to, a.name)
    print("\nทำแล้ว: " + " · ".join(f"{k} {v}" for k, v in done.most_common()))
    print("ขั้นต่อไป: ingest ติ๊ก xlsx_only — ไฟล์ Phase 3 ของสัปดาห์เดิมจะไม่มีงานชุดนี้แล้ว")
    return 0


if __name__ == "__main__":
    sys.exit(main())
