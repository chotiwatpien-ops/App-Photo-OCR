# -*- coding: utf-8 -*-
"""Put back the rows parked as repeats of a trip counted in ANOTHER week.

The customer ruled on 2026-09-14 that a slip counted in an earlier week is work again in a later
one; only a repeat inside the week it is delivered in is a duplicate. The guard follows the new
rule from now on (db._approved_twin), but W37 already held 306 rows (฿16,159) parked under the old
one — their pictures moved out to Week/_ซ้ำ/ by the round's tidying, their seats given away.

For each parked row of the week:
  * its twin is in the same week          → stays a duplicate (nothing changed for it)
  * its twin is only in other weeks       → released: back to 'done', picture back into the
                                            rider folder, then the job's normal auto-approval
  * two released rows are the same trip   → only the first comes back; inside one week the rest
                                            are still repeats of it
  * no twin can be found at all           → left alone and listed

Closed weeks are refused — delivered work is not reopened (fix forward). Report-only unless
--apply.

    python release_cross_week.py --from 2026-09-07 --to 2026-09-13
    python release_cross_week.py --from 2026-09-07 --to 2026-09-13 --apply
"""
import argparse
import sys
from collections import Counter, defaultdict

from sqlalchemy import select, update

import db

NOTE = "ปลดซ้ำ: ต้นฉบับอยู่สัปดาห์อื่น — ลูกค้า 2026-09-14 ให้นับเป็นงาน"


def _amount(r):
    return r["net_earnings"] if r["net_earnings"] is not None else r["base_fare"]


def plan(d_from, d_to):
    """{'release': [row], 'same_week': [row], 'repeat_of_released': [row], 'no_twin': [row]}"""
    t, j = db.trips.c, db.jobs.c
    cols = [t.id, t.job_id, t.file_name, t.status, t.booking_code, t.duplicate_of, t.image_hash,
            t.net_earnings, t.base_fare, t.trip_time, j.driver_name, j.category, j.date_from, j.date_to]
    src = db.trips.join(db.jobs, j.id == t.job_id)
    with db.engine.begin() as c:
        parked = [dict(r) for r in c.execute(
            select(*cols).select_from(src)
            .where(j.date_from == d_from, j.date_to == d_to, t.status == "duplicate")
            .order_by(t.id)).mappings().all()]
        ids = [r["duplicate_of"] for r in parked if r["duplicate_of"]]
        by_id = {r["id"]: dict(r) for r in c.execute(
            select(*cols).select_from(src).where(t.id.in_(ids))).mappings().all()} if ids else {}
        codes = sorted({r["booking_code"] for r in parked if r["booking_code"]})
        committed = [dict(r) for r in c.execute(
            select(*cols).select_from(src)
            .where(t.committed == 1, t.booking_code.in_(codes))).mappings().all()] if codes else []
    by_code = defaultdict(list)
    for r in committed:
        by_code[r["booking_code"]].append(r)

    def agrees(row, twin):
        # a short code may be cut off — it names a trip only with the fare and clock time (db.DUP_FULL_CODE)
        if len(row["booking_code"]) >= db.DUP_FULL_CODE:
            return True
        return twin["base_fare"] == row["base_fare"] and twin["trip_time"] == row["trip_time"]

    out = {"release": [], "same_week": [], "repeat_of_released": [], "no_twin": []}
    for r in parked:
        week = (r["date_from"], r["date_to"])
        twins = []
        if r["duplicate_of"] and r["duplicate_of"] in by_id:
            twins.append(by_id[r["duplicate_of"]])
        if r["booking_code"]:
            twins += [x for x in by_code.get(r["booking_code"], []) if x["id"] != r["id"] and agrees(r, x)]
        if not twins:
            out["no_twin"].append(r)
        elif any((x["date_from"], x["date_to"]) == week for x in twins):
            out["same_week"].append(r)
        else:
            r["twin_week"] = min(x["date_from"] for x in twins)
            out["release"].append(r)

    # two released rows that are one trip: inside the week the later one is still a repeat
    seen_code, seen_hash, keep = set(), set(), []
    for r in out["release"]:
        code = r["booking_code"] if r["booking_code"] and len(r["booking_code"]) >= db.DUP_FULL_CODE else None
        if (code and code in seen_code) or (r["image_hash"] and r["image_hash"] in seen_hash):
            out["repeat_of_released"].append(r)
            continue
        seen_code.add(code) if code else None
        seen_hash.add(r["image_hash"]) if r["image_hash"] else None
        keep.append(r)
    out["release"] = keep
    return out


def apply_plan(rows, drive=None, log=print):
    """Release the rows, bring their pictures back, approve what passes. → dict of counts."""
    import free_dup_seats
    ids = [r["id"] for r in rows]
    if not ids:
        return {"released": 0, "pictures": 0, "approved": 0, "flagged": 0}
    from sqlalchemy import func
    with db.engine.begin() as c:
        n = c.execute(update(db.trips)
                      .where(db.trips.c.id.in_(ids), db.trips.c.status == "duplicate")
                      .values(status="done", duplicate_of=None,
                              note=func.coalesce(db.trips.c.note + " | ", "") + NOTE)).rowcount or 0
    pictures = sum(1 for tid in ids if free_dup_seats.return_picture(tid, drive=drive, log=log))
    approved = flagged = 0
    for job_id in sorted({r["job_id"] for r in rows}):
        res = db.auto_approve_job(job_id)
        approved += res.get("approved", 0)
        flagged += res.get("flagged", 0)
    return {"released": n, "pictures": pictures, "approved": approved, "flagged": flagged}


def main(argv=None):
    ap = argparse.ArgumentParser(description="ปลดแถวที่ถูกพักเพราะซ้ำกับงานของสัปดาห์อื่น (รายงานอย่างเดียวถ้าไม่ใส่ --apply)")
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    db.init_db()

    if db.week_closed(a.d_from):
        print(f"✗ สัปดาห์ {a.d_from} ปิดแล้ว — ไม่เปิดงานที่ส่งลูกค้าไปแล้ว")
        return 1
    p = plan(a.d_from, a.d_to)
    rel = p["release"]
    print(f"สัปดาห์ {a.d_from}..{a.d_to} · แถวที่ถูกพักเป็นซ้ำ "
          f"{sum(len(v) for v in p.values())}")
    print(f"  ปลดได้ (ต้นฉบับอยู่สัปดาห์อื่นเท่านั้น): {len(rel)} แถว · ฿{sum(_amount(r) or 0 for r in rel):,.0f}")
    print(f"  ยังเป็นซ้ำ (ต้นฉบับอยู่สัปดาห์เดียวกัน): {len(p['same_week'])}")
    print(f"  ยังเป็นซ้ำ (เที่ยวเดียวกับแถวที่ปลดแล้ว): {len(p['repeat_of_released'])}")
    print(f"  หาต้นฉบับไม่เจอ — ไม่แตะ: {len(p['no_twin'])}")
    if rel:
        print("\n  แยกกลุ่ม:", dict(Counter(r["category"] for r in rel)))
        print("  ต้นฉบับอยู่สัปดาห์:", dict(sorted(Counter(r["twin_week"] for r in rel).items())))
        print("  ไรเดอร์ที่ได้คืนมากสุด:", Counter(r["driver_name"] for r in rel).most_common(10))
    for r in p["no_twin"][:10]:
        print(f"    ไม่เจอต้นฉบับ #{r['id']} {r['driver_name']} {r['file_name']}")
    if not a.apply:
        print("\n(รายงานอย่างเดียว — ยังไม่ได้แตะอะไร · ติ๊กทำจริงเพื่อปลด)")
        return 0
    import roster
    res = apply_plan(rel, drive=roster._drive())
    print(f"\nปลดแล้ว {res['released']} แถว · รูปกลับเข้าโฟลเดอร์ไรเดอร์ {res['pictures']} ใบ"
          f" · อนุมัติเข้าไฟล์ {res['approved']} · ค้างให้คนดู {res['flagged']}")
    print("ต่อไป: รัน ingest แบบ exports_only ใส่ exports_week ของสัปดาห์นี้ เพื่อเขียน Excel และรูปส่งลูกค้า")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
