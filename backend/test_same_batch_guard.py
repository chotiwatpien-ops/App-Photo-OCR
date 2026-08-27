# -*- coding: utf-8 -*-
"""The exact shape that double-counted on 2026-08-27: a weak model reads the upper half as a
whole screenshot, so the pair never merges and both halves arrive for approval in one batch."""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-test-")
sys.path.insert(0, "backend")
import db                                                    # noqa: E402
from sqlalchemy import select                                # noqa: E402

db.init_db()


def add(job, name, kind, net, base, code=None, check="pass"):
    tid = db.create_trip(job, name, b"x", "image/jpeg")
    db.update_trip(tid, {"status": "done", "kind": kind, "net_earnings": net, "base_fare": base,
                         "booking_code": code, "check_status": check, "trip_date": "2026-08-10"})
    return tid


def state(ids):
    with db.engine.begin() as c:
        return {r["id"]: (r["committed"], r["duplicate_of"])
                for r in c.execute(select(db.trips.c.id, db.trips.c.committed,
                                          db.trips.c.duplicate_of)
                                   .where(db.trips.c.id.in_(ids))).mappings().all()}


ok = True

# 1. the failure: bottom (no code) + "full" upper half, same money, same round
job = db.create_job("ทดสอบ", "S", "2026-08-10", "2026-08-16")
bottom = add(job, "S__100.jpg", "bottom", 374.0, 374.0)
upper = add(job, "S__101.jpg", "full", 374.0, 374.0, code="A-9LSI4PDGXC6XAV")
st = db.auto_approve_job(job)
s = state([bottom, upper])
print(f"1) คู่ครึ่งบน/ล่างในรอบเดียวกัน → อนุมัติ {st['approved']} แถว")
print(f"   ครึ่งล่าง committed={s[bottom][0]} duplicate_of={s[bottom][1]} | ครึ่งบน committed={s[upper][0]}")
if not (st["approved"] == 1 and s[bottom][0] == 0 and s[bottom][1] == upper and s[upper][0] == 1):
    ok = False
    print("   ✗ ควรอนุมัติแค่แถวที่มีโค้ด และผูกครึ่งล่างเป็นซ้ำ")

# 2. two genuine trips that happen to earn the same amount must BOTH pass
job2 = db.create_job("ทดสอบสอง", "S", "2026-08-10", "2026-08-16")
a = add(job2, "a.jpg", "full", 200.0, 200.0, code="A-AAA")
b = add(job2, "b.jpg", "full", 200.0, 200.0, code="A-BBB")
st2 = db.auto_approve_job(job2)
s2 = state([a, b])
print(f"\n2) สองทริปจริงที่ยอดบังเอิญเท่ากัน → อนุมัติ {st2['approved']} แถว "
      f"(committed {s2[a][0]}/{s2[b][0]})")
if not (st2["approved"] == 2 and s2[a][0] == 1 and s2[b][0] == 1):
    ok = False
    print("   ✗ ทั้งคู่ควรผ่าน — ยอดเท่ากันไม่ใช่หลักฐานว่าซ้ำเมื่อทั้งคู่มีโค้ด")

# 3. a real lower half with no twin (upper half missing) still passes
job3 = db.create_job("ทดสอบสาม", "S", "2026-08-10", "2026-08-16")
lone = add(job3, "lone.jpg", "bottom", 155.0, 155.0)
st3 = db.auto_approve_job(job3)
print(f"\n3) ครึ่งล่างที่ไม่มีคู่เลย → อนุมัติ {st3['approved']} แถว "
      f"(committed {state([lone])[lone][0]})")
if st3["approved"] != 1:
    ok = False
    print("   ✗ ครึ่งล่างที่ไม่มีคู่ควรผ่านตามเดิม")

# 4. next round: the parked half is auto-discarded now that its twin is committed
n = db.discard_settled_duplicates(job)
with db.engine.begin() as c:
    st_bottom = c.execute(select(db.trips.c.status).where(db.trips.c.id == bottom)).scalar()
print(f"\n4) รอบถัดไป → ทิ้งอัตโนมัติ {n} แถว (สถานะครึ่งล่าง = {st_bottom})")
if not (n == 1 and st_bottom == "duplicate"):
    ok = False
    print("   ✗ ควรถูกทิ้งเข้าบันทึกเอง")

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
