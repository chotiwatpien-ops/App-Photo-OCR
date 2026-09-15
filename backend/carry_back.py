# -*- coding: utf-8 -*-
"""Bring carried rows back from next week when this week's group has fallen below its target.

carry_excess counts a group by the jobs it holds. The customer counts by the Service Type on each
row (Fiat, 2026-09-16: "นับตาม Service Type"), and the two part company whenever the chip audit
and the rehome run after the carry instead of before it: W37 was carried at 1,470 per group,
then 20 Standard Bike rows left 2 W Saver for 2 W Standard and 8 car rows the reader had called
bikes went back to 4 W Standard — so Saver Bike stood at 1,450 with 119 of its own rows sitting
in W38. This undoes that much of the carry and no more.

Which rows: only rows carry_excess moved out of THIS week (its note names the week they went to
and the job they came from), of the group asked for and still carrying that group's service —
the slip's earliest trips first, since carry took the latest. What moves, per row, is the carry
in reverse:
  1. the row, back to the job it left — else a job for the same rider in this week's group;
  2. the stitched picture, from next week's rider folder into that job's folder;
  3. the delivered picture, if next week's export already named it, into next week's
     Export Pic _แทนที่แล้ว, and customer_image cleared so this week's export names it again;
  4. the date, back to the day on the slip when that day is inside this week.
Nothing is deleted and no row is re-read.

    python carry_back.py --week "Week 7-13 Sep" --from 2026-09-07 --to 2026-09-13 --group "2 W Saver"
    python carry_back.py ... --apply
"""
import argparse
import re
import sys
from collections import Counter

from sqlalchemy import select

import db
from carry_excess import REPLACED_DIR, next_week, next_week_folder
from distribute import NUM_PREFIX, bare, folder_label

SERVICE_OF = {"2 W Saver": "Saver Bike", "2 W Standard": "Standard Bike", "4 W Standard": "Standard Car"}
FROM_JOB_RE = re.compile(r"เดิม job #(\d+)")
SLIP_DAY_RE = re.compile(r"วันที่บนสลิป (\d{4}-\d{2}-\d{2}) →")


def carried_note(n_from, n_to):
    """The words carry_excess writes on every row it moves — the only proof a row was carried."""
    return f"ยกไปสัปดาห์ {n_from}..{n_to} เพราะ"


def count_by_service(d_from, d_to):
    """{service: finished rows in the week}, whichever group's job they sit in."""
    jobs = [j["id"] for j in db.jobs_by_week().get((d_from, d_to), [])]
    if not jobs:
        return Counter()
    t = db.trips.c
    with db.engine.begin() as c:
        return Counter(r[0] for r in c.execute(
            select(t.service_type).where(t.job_id.in_(jobs), t.status == "done")).all())


def candidates(d_from, d_to, group):
    """[(row, next-week job)] carried out of this week in this group, earliest slip first."""
    n_from, n_to = next_week(d_from, d_to)
    jobs = {j["id"]: j for j in db.jobs_by_week().get((n_from, n_to), [])
            if (j.get("category") or "").strip() == group}
    if not jobs:
        return []
    t = db.trips.c
    with db.engine.begin() as c:
        rows = [dict(r) for r in c.execute(
            select(t.id, t.job_id, t.file_name, t.trip_date, t.trip_time, t.service_type,
                   t.customer_image, t.note)
            .where(t.job_id.in_(list(jobs)), t.status == "done")).mappings().all()]
    mark, want = carried_note(n_from, n_to), SERVICE_OF.get(group)
    out = [r for r in rows if mark in (r.get("note") or "")
           and (want is None or (r.get("service_type") or "").strip() == want)]

    def slip_day(r):
        m = SLIP_DAY_RE.search(r.get("note") or "")
        return m.group(1) if m else (r.get("trip_date") or "")

    out.sort(key=lambda r: (slip_day(r), r.get("trip_time") or "", r["id"]))
    return [(r, jobs[r["job_id"]]) for r in out]


def home_job(row, next_job, d_from, d_to, group):
    """The job the row left, when it is still this week's and this group's — else None."""
    m = FROM_JOB_RE.search(row.get("note") or "")
    j = db.get_job(int(m.group(1))) if m else None
    if j and (j["date_from"], j["date_to"]) == (d_from, d_to) and (j.get("category") or "").strip() == group \
            and j.get("driver_name") == next_job.get("driver_name"):
        return j
    return None


def restored_note(row, d_from, d_to, group, from_job):
    """The row's note with the carry and its re-dating taken off, and why it came back on top."""
    parts = [p for p in (row.get("note") or "").split(" | ")
             if not p.startswith(carried_note(*next_week(d_from, d_to))) and not p.startswith("วันที่บนสลิป ")]
    back = f"ดึงกลับจากสัปดาห์ {'..'.join(next_week(d_from, d_to))} เพราะ {group} นับตาม Service Type ขาดเป้า (จาก job #{from_job})"
    return " | ".join([back] + parts)


def apply(drive, this_week_id, next_exports_id, d_from, d_to, group, picked, log=print):
    done = Counter()
    listing = {}

    def find_in(folder_id, name):
        if folder_id not in listing:
            listing[folder_id] = {i["name"]: i["id"] for i in drive.list_images(folder_id)}
        return listing[folder_id].get(name)

    group_dir = None
    replaced = None
    for r, nj in picked:
        home = home_job(r, nj, d_from, d_to, group)
        if home is None:
            jid = db.find_job(nj["driver_name"], d_from, d_to, category=group, admin=nj.get("admin"))
            home = db.get_job(jid) if jid else None
        if home is None:
            group_dir = group_dir or drive.ensure_folder(this_week_id, group)
            taken = [int(re.sub(r"[^0-9]", "", m.group(0))) for f in drive.list_folders(group_dir)
                     for m in [NUM_PREFIX.match(f["name"])] if m and re.search(r"[0-9]", m.group(0))]
            fid = drive.ensure_folder(group_dir, folder_label(max(taken, default=0) + 1, bare(nj["driver_name"])))
            jid = db.create_job(nj["driver_name"], "Trips", d_from, d_to, category=group,
                                folder_name=f"{group}/{bare(nj['driver_name'])}", admin=nj.get("admin"),
                                drive_folder_id=fid)
            db.set_job_status(jid, "committed")
            home = db.get_job(jid)
            log(f"  + job #{jid} {nj['driver_name']} · {group} · {d_from}..{d_to}")
        src, dest = nj.get("drive_folder_id"), home.get("drive_folder_id")
        pic = find_in(src, r["file_name"]) if src else None
        if pic and dest:
            drive.move_file(pic, dest)
            done["ย้ายรูปรวมร่างกลับ"] += 1
        else:
            done["หารูปรวมร่างในสัปดาห์หน้าไม่เจอ"] += 1
        if r.get("customer_image") and next_exports_id:
            cdir = next((f["id"] for f in drive.list_folders(next_exports_id) if f["name"].strip() == group), None)
            cid = find_in(cdir, r["customer_image"]) if cdir else None
            if cid:
                replaced = replaced or drive.ensure_folder(next_exports_id, REPLACED_DIR)
                drive.move_file(cid, replaced)
                done["เก็บรูปลูกค้าสัปดาห์หน้าออก"] += 1
        db.move_trips_to_job([r["id"]], home["id"])
        m = SLIP_DAY_RE.search(r.get("note") or "")
        fields = {"customer_image": None, "note": restored_note(r, d_from, d_to, group, nj["id"])}
        if m and d_from <= m.group(1) <= d_to:
            fields["trip_date"] = m.group(1)
        db.update_trip(r["id"], fields)
        done["ดึงแถวกลับ"] += 1
    return done


def main(argv=None):
    ap = argparse.ArgumentParser(description="ดึงแถวที่เคยยกไปสัปดาห์หน้ากลับมา เมื่อกลุ่มนับตาม Service Type ขาดเป้า")
    ap.add_argument("--week", required=True, help="ชื่อโฟลเดอร์สัปดาห์นี้บน Drive")
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--group", action="append", default=[], help="กลุ่มที่จะดึงกลับ (ใส่ซ้ำได้) — ว่าง = ทุกกลุ่ม")
    ap.add_argument("--target", type=int, default=1470)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    db.init_db()

    have = count_by_service(a.d_from, a.d_to)
    n_from, n_to = next_week(a.d_from, a.d_to)
    print(f"{a.d_from}..{a.d_to} · เป้า {a.target} ต่อ Service Type · ดึงจาก {n_from}..{n_to}")
    plan = {}
    for group in (a.group or list(SERVICE_OF)):
        service = SERVICE_OF[group]
        need = a.target - have.get(service, 0)
        pool = candidates(a.d_from, a.d_to, group)
        if need <= 0:
            print(f"    {service:<14} มี {have.get(service, 0):>5}   ไม่ขาด")
            continue
        plan[group] = pool[:need]
        print(f"    {service:<14} มี {have.get(service, 0):>5}   ขาด {need} · แถวที่ยกไปแล้วดึงกลับได้ {len(pool)}"
              f" → ดึง {len(plan[group])}" + ("" if len(pool) >= need else f" (ยังขาดอีก {need - len(pool)})"))
    if not any(plan.values()):
        print("ไม่มีอะไรต้องดึงกลับ")
        return 0
    if not a.apply:
        print("\n(รายงานอย่างเดียว — ใส่ --apply เพื่อดึงกลับจริง)")
        return 0

    import config
    import roster
    from ingest import week_label
    drive = roster._drive()
    inbox = config.DRIVE_INBOX_FOLDER_ID
    this_week = next((f for f in drive.list_folders(inbox) if f["name"].strip() == a.week.strip()), None)
    if this_week is None:
        print(f"✗ ไม่พบโฟลเดอร์ {a.week!r} ใน Inbox")
        return 1
    exports = next((f for f in drive.list_folders(inbox) if f["name"].strip() == "Export Pic"), None)
    next_exports = (next((f["id"] for f in drive.list_folders(exports["id"]) if f["name"] == week_label(n_from)), None)
                    if exports else None)
    total = Counter()
    for group, picked in plan.items():
        if picked:
            total.update(apply(drive, this_week["id"], next_exports, a.d_from, a.d_to, group, picked))
    print("\nทำแล้ว: " + " · ".join(f"{k} {v}" for k, v in total.most_common()))
    print(f"ขั้นต่อไป: ingest exports_only ของ {week_label(a.d_from)} แล้ว {week_label(n_from)}"
          f" (ชื่อสัปดาห์หน้า: {next_week_folder(a.week, a.d_from, a.d_to)})")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
