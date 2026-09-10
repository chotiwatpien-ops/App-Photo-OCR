# -*- coding: utf-8 -*-
"""Give every row in a week's jobs a date inside that week, spread evenly across its days.

A row carried into next week's file kept the day it was driven (2026-09-10, morning). Fiat
checked the file that evening and reversed it: a row in the W37 file dated 4 Sep says W36 to the
reader, so the carried rows must be dated across the week they are filed under — "วันที่ต้องไม่ใช่
WK ที่ Run". The day on the slip is kept in the row's note, so nothing is lost.

How the days are chosen: the out-of-week rows are put in the order they were driven (date, time,
id) and dealt across the week's days in that order, the first seventh of them on Monday, the
last seventh on Sunday. Order is kept, so two trips that were an hour apart are never on
opposite ends of the week; the time of day is kept as it was. Nothing else on the row changes,
no picture is touched, and rows already dated inside the week are left alone.

    python redate_to_week.py --from 2026-09-07 --to 2026-09-13          # report
    python redate_to_week.py --from 2026-09-07 --to 2026-09-13 --apply
Then ingest with xlsx_only, so both workbooks show the new dates.
"""
import argparse
import sys
from collections import Counter
from datetime import date, timedelta

from sqlalchemy import select

import db


def week_days(d_from, d_to):
    a, b = date.fromisoformat(d_from), date.fromisoformat(d_to)
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def spread(rows, d_from, d_to):
    """[(row, new date)] for rows in driven order, dealt evenly across the week's days."""
    days = week_days(d_from, d_to)
    ranked = sorted(rows, key=lambda r: (r.get("trip_date") or "", r.get("trip_time") or "", r["id"]))
    n = len(ranked)
    return [(r, days[i * len(days) // n]) for i, r in enumerate(ranked)]


def out_of_week_rows(d_from, d_to):
    """Finished rows in the week's jobs whose date lies outside the week, with the jobs."""
    jobs = {j["id"]: j for j in db.jobs_by_week().get((d_from, d_to), [])}
    if not jobs:
        return [], jobs
    t = db.trips.c
    with db.engine.begin() as c:
        rows = [dict(r) for r in c.execute(
            select(t.id, t.job_id, t.file_name, t.trip_date, t.trip_time, t.note)
            .where(t.job_id.in_(list(jobs)), t.status == "done")).mappings().all()]
    out = [r for r in rows if not r.get("trip_date") or not (d_from <= r["trip_date"] <= d_to)]
    return out, jobs


def apply(plan, d_from, d_to, log=print):
    """Write the new dates; the slip's own day goes into the note."""
    n = 0
    for r, new in plan:
        note = f"วันที่บนสลิป {r.get('trip_date')} → ลงเป็น {new} ให้อยู่ในสัปดาห์ {d_from}..{d_to} ที่แถวถูกยกมา"
        db.update_trip(r["id"], {"trip_date": new,
                                 "note": f"{note} | {r['note']}" if r.get("note") else note})
        n += 1
        if n % 100 == 0:
            log(f"    ลงวันที่ใหม่แล้ว {n}/{len(plan)} แถว")
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="กระจายวันที่ของแถวที่ถูกยกมาให้อยู่ในสัปดาห์ของไฟล์")
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    db.init_db()
    rows, jobs = out_of_week_rows(a.d_from, a.d_to)
    print(f"สัปดาห์ {a.d_from}..{a.d_to}: job {len(jobs)} · แถวที่วันที่อยู่นอกสัปดาห์ {len(rows)}")
    if not rows:
        print("ไม่มีอะไรต้องลงวันที่ใหม่")
        return 0
    by_group = Counter((jobs[r["job_id"]].get("category") or "").strip() for r in rows)
    print("  ต่อกลุ่ม: " + " · ".join(f"{g} {n}" for g, n in sorted(by_group.items())))
    was = Counter(r.get("trip_date") for r in rows)
    print("  วันที่เดิม: " + " · ".join(f"{d} {n}" for d, n in sorted(was.items())))
    plan = spread(rows, a.d_from, a.d_to)
    will = Counter(new for _r, new in plan)
    print("  จะลงเป็น: " + " · ".join(f"{d} {n}" for d, n in sorted(will.items())))
    if not a.apply:
        print("\n(รายงานอย่างเดียว — ใส่ --apply เพื่อลงวันที่จริง)")
        return 0
    n = apply(plan, a.d_from, a.d_to)
    print(f"\nลงวันที่ใหม่แล้ว {n} แถว · ขั้นต่อไป: ingest ติ๊ก xlsx_only ให้ Excel ทั้งสองไฟล์เขียนใหม่")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
