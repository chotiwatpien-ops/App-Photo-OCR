# -*- coding: utf-8 -*-
"""Correct a figure the reader got wrong on a few named rows — only where the row still holds
the value a person saw when deciding the fix.

W34 #8725 (กฤษณชัย): the slip prints ค่าโดยสารพื้นฐาน 99 and คุณได้รับ ฿104 (99 + a ฿5 turbo), the
row says base 0 (Fiat 2026-09-23). A fix names the row, the field, what the row holds now and
what it should hold; a row that no longer holds the old value is left alone and reported, so a
fix written against yesterday's data cannot overwrite today's. The note says who changed what.

    python fix_rows.py --fix "8725 base_fare 0 99" --why "ค่ารอบอ่านพลาด: สลิปพิมพ์ 99"          # report
    python fix_rows.py --fix "8725 base_fare 0 99" --why "..." --apply
"""
import argparse
import sys

from sqlalchemy import select

import db


def parse(spec):
    """'8725 base_fare 0 99; 8726 turbo None 5' → [(8725, 'base_fare', 0.0, 99.0), ...]"""
    out = []
    for part in [p for p in spec.split(";") if p.strip()]:
        tid, field, old, new = part.split()
        num = lambda v: None if v.lower() in ("none", "null", "-") else float(v)
        out.append((int(tid), field, num(old), num(new)))
    return out


def same(cur, old):
    """An empty field and a 0 are the same thing to a person reading the file."""
    if not old:
        return not cur
    return cur is not None and abs(cur - old) < 0.005


def plan(fixes):
    """[(fix, current value, ok)]"""
    ids = [f[0] for f in fixes]
    with db.engine.begin() as c:
        rows = {r["id"]: dict(r) for r in c.execute(select(db.trips).where(db.trips.c.id.in_(ids))).mappings().all()}
    out = []
    for tid, field, old, new in fixes:
        if field not in db.TRIP_EDITABLE:
            out.append(((tid, field, old, new), None, f"แก้ช่อง {field} ไม่ได้"))
            continue
        r = rows.get(tid)
        if r is None:
            out.append(((tid, field, old, new), None, "ไม่พบแถว"))
            continue
        cur = r.get(field)
        out.append(((tid, field, old, new), cur, "ok" if same(cur, old) else f"ค่าในแถวตอนนี้คือ {cur} ไม่ใช่ {old}"))
    return out, rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="แก้ตัวเลขที่อ่านผิดในแถวที่ระบุ (เช็กค่าเดิมก่อนเขียน)")
    ap.add_argument("--fix", required=True, help="'id field ค่าเดิม ค่าใหม่' คั่นหลายรายการด้วย ;")
    ap.add_argument("--why", required=True, help="เหตุผล — ลงในโน้ตของแถว")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    db.init_db()
    fixes = parse(a.fix)
    result, rows = plan(fixes)
    for (tid, field, old, new), cur, why in result:
        print(f"  #{tid} {field}: {cur} → {new}  [{why}]")
    good = [(f, rows[f[0]]) for f, _cur, why in result if why == "ok"]
    if not a.apply:
        print(f"\n(รายงานอย่างเดียว — แก้ได้ {len(good)} จาก {len(result)} · ใส่ --apply เพื่อเขียนจริง)")
        return 0
    for (tid, field, old, new), r in good:
        note = f"แก้ {field} {old:g} → {new:g}: {a.why}" if old is not None else f"แก้ {field} ว่าง → {new:g}: {a.why}"
        db.update_trip(tid, {field: new, "note": f"{note} | {r['note']}" if r.get("note") else note})
    print(f"\n✓ แก้แล้ว {len(good)} แถว · ข้าม {len(result) - len(good)}")
    return 0 if len(good) == len(result) else 1


if __name__ == "__main__":
    sys.exit(main())
