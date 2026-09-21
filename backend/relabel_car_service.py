# -*- coding: utf-8 -*-
"""Rows already read as 'Saver Car', 'EV' or 'Women driver' become 'Standard Car' — the customer
buys one car product (pipeline.car_is_standard; EV and Women driver added by Fiat 2026-09-21).

The reader stopped writing 'Saver Car' on 2026-09-16 (pipeline.car_is_standard, Ops via Fiat:
"4W saver ให้ตีเข้า Standard"), but rows read before that keep what they were given: W37 held 20,
which the week's count read as a service of its own and the car group therefore looked 20 short
of 1,470 while the folder held 1,490.

Only the label changes. No picture moves, no row is re-read, and every row keeps a note saying
what it said before, so the change can always be told from a reading.

    python relabel_car_service.py --from 2026-09-07 --to 2026-09-13            # report
    python relabel_car_service.py --from 2026-09-07 --to 2026-09-13 --apply
Then carry_excess (the car group may now be over target) and ingest --xlsx-only.
"""
import argparse
import sys
from collections import Counter

from sqlalchemy import select

import db
from pipeline import car_is_standard

TARGET = "Standard Car"


def rows_to_relabel(d_from, d_to):
    """[(row, job)] — finished rows of the week whose service is a car but not the one we sell."""
    jobs = {j["id"]: j for j in db.jobs_by_week().get((d_from, d_to), [])}
    if not jobs:
        return []
    t = db.trips.c
    with db.engine.begin() as c:
        rows = [dict(r) for r in c.execute(
            select(t.id, t.job_id, t.file_name, t.service_type, t.note)
            .where(t.job_id.in_(list(jobs)), t.status == "done").order_by(t.id)).mappings().all()]
    return [(r, jobs[r["job_id"]]) for r in rows
            if car_is_standard(r.get("service_type")) == TARGET
            and (r.get("service_type") or "").strip() != TARGET]


def apply(pairs, log=print):
    for r, _j in pairs:
        was = (r.get("service_type") or "").strip()
        note = f"ประเภทงาน {was} → {TARGET} (รถยนต์นับเป็นสินค้าเดียว)"
        db.update_trip(r["id"], {"service_type": TARGET,
                                 "note": f"{note} | {r['note']}" if r.get("note") else note})
    return len(pairs)


def main(argv=None):
    ap = argparse.ArgumentParser(description="เปลี่ยนแถวรถยนต์ (Saver Car / EV / Women driver) ให้เป็น Standard Car")
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    db.init_db()
    pairs = rows_to_relabel(a.d_from, a.d_to)
    print(f"{a.d_from}..{a.d_to} · แถวรถยนต์ที่ต้องเปลี่ยนป้าย {len(pairs)}")
    if not pairs:
        print("ไม่มีอะไรต้องเปลี่ยน ✔")
        return 0
    for (svc, group), n in Counter(((r.get("service_type") or "").strip(), j.get("category"))
                                   for r, j in pairs).most_common():
        print(f"    {svc} ในกลุ่ม {group}: {n} แถว → {TARGET}")
    if not a.apply:
        print("\n(รายงานอย่างเดียว — ใส่ --apply เพื่อเปลี่ยนจริง)")
        return 0
    n = apply(pairs)
    print(f"\nเปลี่ยนแล้ว {n} แถว · ขั้นต่อไป: Carry excess (กลุ่มรถยนต์อาจเกินเป้าแล้ว) แล้ว ingest ติ๊ก xlsx_only")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
