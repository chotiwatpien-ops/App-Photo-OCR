# -*- coding: utf-8 -*-
"""One delivered week, again, in the Phase 3 layout — as a file of its own.

Ops asked for W35 (24–30 Aug) in the layout the customer reads from W38 on (Fiat 2026-09-22:
a separate file; the delivered Rider Trips.xlsx is not touched, and no amount changes). The
passenger block lines are filled in first by reread_passenger.py, which keeps a row's own paid
and fare figures; this only writes the rows out.

The week is the week of the job, as in the weekly files — the rows the customer received as W35 —
approved and finished rows only.

    python week_phase3.py --from 2026-08-24 --to 2026-08-30                 # count, write nothing
    python week_phase3.py --from 2026-08-24 --to 2026-08-30 --xlsx w35.xlsx
    python week_phase3.py --from 2026-08-24 --to 2026-08-30 --to-drive      # next to the weekly files
"""
import argparse
import sys
from collections import Counter

from sqlalchemy import select

import db
import excel_writer
from ingest import week_label


def week_rows(d_from, d_to):
    t, j = db.trips.c, db.jobs.c
    with db.engine.begin() as c:
        return [dict(r) for r in c.execute(
            select(*db.TRIP_COLS, j.driver_name, j.category)
            .select_from(db.trips.join(db.jobs, j.id == t.job_id))
            .where(j.date_from == d_from, j.date_to == d_to, t.status == "done", t.committed == 1)
            .order_by(t.trip_date, j.driver_name, t.trip_time, t.id)).mappings().all()]


def file_name(d_from):
    return f"Rider Trips {week_label(d_from)} Phase 3.xlsx"


def main(argv=None):
    ap = argparse.ArgumentParser(description="ออกไฟล์ของสัปดาห์เดียวในรูปแบบ Phase 3 (ไฟล์แยก)")
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--xlsx", help="เขียนไฟล์ไว้ที่นี่")
    ap.add_argument("--to-drive", action="store_true", help="วางไฟล์ลง Drive ข้างไฟล์ประจำสัปดาห์")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    db.init_db()
    rows = week_rows(a.d_from, a.d_to)
    print(f"สัปดาห์ {a.d_from}..{a.d_to} ({week_label(a.d_from)}): {len(rows):,} แถว")
    print("  " + " · ".join(f"{k or '?'} {v:,}" for k, v in Counter(r.get("category") for r in rows).most_common()))
    lines = sum(1 for r in rows if any(r.get(k) for k in ("discount", "insurance_fee", "passenger_tolls")))
    print(f"  แถวที่มีบรรทัดส่วนลด/ประกัน/ทางด่วนแยกแล้ว {lines:,}")
    if not rows:
        return 1
    data = excel_writer.build_fare_lines_workbook(rows, every_week=True)
    name = file_name(a.d_from)
    if a.xlsx:
        open(a.xlsx, "wb").write(data)
        print(f"เขียนไฟล์แล้ว: {a.xlsx}")
    if a.to_drive:
        import config
        import roster
        fid = roster._drive().upload_xlsx(config.DRIVE_EXPORTS_FOLDER_ID, name, data)
        print(f"วางลง Drive แล้ว: {name} → https://drive.google.com/file/d/{fid}/view")
    if not (a.xlsx or a.to_drive):
        print(f"\n(นับอย่างเดียว — ใส่ --to-drive เพื่อวาง '{name}' ลง Drive)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
