# -*- coding: utf-8 -*-
"""Why each 'น่าจะซ้ำ' row is still in the queue, and what its twin says.

The settled repeats park themselves: same booking code, twin already approved, same money —
nobody needs to look. What reaches a person is the pair that disagrees, and the queue shows the
flag without showing the disagreement, so the reviewer has to go and find the other row.

This puts the two side by side and marks every field that differs. Read-only: it decides nothing
and writes nothing. Which copy is right is a question about the pictures.

    python report_queue_dups.py
"""
import sys

from sqlalchemy import select

import db

t, j = db.trips.c, db.jobs.c
FIELDS = [("trip_date", "วันที่"), ("trip_time", "เวลา"), ("net_earnings", "รายได้"),
          ("base_fare", "ค่าโดยสารพื้นฐาน"), ("bonus", "โบนัส"), ("turbo", "เทอร์โบ"),
          ("tip", "ทิป"), ("passenger_paid", "ผู้โดยสารจ่าย"), ("passenger_total", "รวมผู้โดยสาร"),
          ("grab_commission", "ค่าบริการแกร็บ"), ("distance_km", "ระยะทาง")]


def fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    return str(v)


def load(where):
    cols = [t.id, t.job_id, j.driver_name, j.category, t.file_name, t.booking_code, t.status,
            t.committed, t.check_status, t.duplicate_of, t.note, t.kind]
    cols += [getattr(t, f) for f, _ in FIELDS]
    with db.engine.begin() as c:
        return [dict(r) for r in c.execute(
            select(*cols).select_from(db.trips.join(db.jobs, j.id == t.job_id))
            .where(where)).mappings().all()]


def main(argv=None):
    db.init_db()
    queue = db.review_queue()
    dups = [r for r in queue if r.get("duplicate_of") or r.get("seen_in_job")]
    print(f"รอตรวจทั้งหมด {len(queue)} รายการ · ในนั้น 'น่าจะซ้ำ' {len(dups)} รายการ")
    if not dups:
        return 0

    ids = [r["duplicate_of"] for r in dups if r.get("duplicate_of")]
    codes = [r["booking_code"] for r in dups if r.get("booking_code")]
    twins = {r["id"]: r for r in (load(t.id.in_(ids)) if ids else [])}
    by_code = {}
    for r in (load(t.booking_code.in_(codes)) if codes else []):
        by_code.setdefault(r["booking_code"], []).append(r)

    for n, r in enumerate(dups, 1):
        twin = twins.get(r.get("duplicate_of"))
        if twin is None:                       # flagged by booking code, not by duplicate_of
            others = [x for x in by_code.get(r["booking_code"], []) if x["id"] != r["id"]]
            twin = next((x for x in others if x["committed"]), others[0] if others else None)
        print(f"\n{'=' * 78}\n{n}. {r['file_name']}")
        where = f" · {r['category']}" if r.get("category") else ""
        print(f"   ไรเดอร์ {r.get('driver_name')}{where} · job #{r['job_id']} "
              f"· รหัส {r.get('booking_code')}")
        if r.get("note"):
            print(f"   โน้ต: {r['note'][:150]}")
        if twin is None:
            print("   ⚠ หาคู่แฝดไม่เจอ — รหัสการจองอาจถูกลบไปแล้ว")
            continue
        state = "อนุมัติแล้ว" if twin["committed"] else f"ยังไม่อนุมัติ ({twin['status']})"
        print(f"   คู่แฝด: {twin['file_name']} · job #{twin['job_id']} "
              f"· {twin.get('driver_name')} · {state}")
        diff = [(lab, r.get(f), twin.get(f)) for f, lab in FIELDS
                if fmt(r.get(f)) != fmt(twin.get(f))]
        same = len(FIELDS) - len(diff)
        if not diff:
            print(f"   ทุกช่องตรงกันหมด ({same} ช่อง) — เป็นสำเนาของเที่ยวเดียวกัน")
        else:
            print(f"   ตรงกัน {same} ช่อง · ต่างกัน {len(diff)} ช่อง:")
            print(f"      {'ช่อง':<20}{'แถวนี้':>14}{'คู่แฝด':>14}")
            for lab, a, b in diff:
                print(f"      {lab:<20}{fmt(a):>14}{fmt(b):>14}")
        if r.get("driver_name") != twin.get("driver_name"):
            print("   ⚠ คนละไรเดอร์ — รหัสการจองเดียวกันแต่คนละคน ต้องดูรูปก่อนตัดสิน")

    print(f"\n{'=' * 78}\n(รายงานอย่างเดียว — ไม่ได้แก้อะไร)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
