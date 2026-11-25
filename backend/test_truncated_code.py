# -*- coding: utf-8 -*-
"""A booking code the reader cut short is the same trip as the full code it starts.

Grab prints the code over two lines and the reader sometimes stops at the break: 'A-AWBF7H4W'
or 'A-AW6NO6QV...' (W46 held 24 such codes, W47 54). same_trip compared codes only when both were
12 letters or more, and db.trip_key needs the clock time for a short code, so a cut code next to
its full twin was nobody's repeat: the round, the approve button and settle-doubles all let it
through. A cut code now counts as the same trip when the full one starts with it, at the same
base fare and the same distance."""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-truncated-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from sqlalchemy import insert                                   # noqa: E402

import db                                                       # noqa: E402
import same_trip                                                # noqa: E402

db.init_db()
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


def row(code, fare=62, km=5.31, **kw):
    return {"id": kw.pop("id", None), "booking_code": code, "base_fare": fare, "distance_km": km, **kw}


FULL = "A-AWBF7H4WQPXRAV"
check("❗ รหัสที่อ่านขาดท้าย กับรหัสเต็มที่ขึ้นต้นเหมือนกัน ค่ารอบและระยะทางตรงกัน: เที่ยวเดียวกัน",
      same_trip.kind(row("A-AWBF7H4W"), row(FULL)) == same_trip.CODE)
check("มีจุดต่อท้าย ('...') ก็เหมือนกัน", same_trip.kind(row("A-AWBF7H4WQP..."), row(FULL)) == same_trip.CODE)
check("สลับฝั่งก็ได้ผลเดียวกัน", same_trip.kind(row(FULL), row("A-AWBF7H4W")) == same_trip.CODE)
check("ค่ารอบต่าง: ไม่ใช่", same_trip.kind(row("A-AWBF7H4W", fare=70), row(FULL)) is None)
check("ระยะทางต่าง: ไม่ใช่", same_trip.kind(row("A-AWBF7H4W", km=9.9), row(FULL)) is None)
check("ไม่มีระยะทางให้เทียบ: ไม่เดา", same_trip.kind(row("A-AWBF7H4W", km=None), row(FULL)) is None)
check("ขึ้นต้นไม่เหมือนกัน: ไม่ใช่", same_trip.kind(row("A-AWBF7H4X"), row(FULL)) is None)
check("รหัสสั้นเกินไป (เหลือไม่กี่ตัว): ไม่เทียบ", same_trip.kind(row("A-AWBF"), row(FULL)) is None)
check("รหัสสั้นสองตัว (เช่นรหัสทดสอบ A-VRF00019 กับ A-VRF00020): ไม่เทียบแบบนี้",
      same_trip.kind(row("A-VRF00019"), row("A-VRF0001")) is None)
check("รหัสเต็มสองตัวที่ใกล้กัน ยังเป็นกฎเดิม", same_trip.kind(row(FULL), row("A-AWBF7H4WQPXRA")) == same_trip.CODE)

W = ("2026-11-23", "2026-11-29")
a = db.create_job("ก Win", "Trips", *W, category="2 W Saver")
b = db.create_job("ข Win", "Trips", *W, category="2 W Saver")


def trip(job, code, **kw):
    base = dict(job_id=job, file_name=f"{job}_{code}.jpg", booking_code=code, status="done",
                committed=0, check_status="pass", trip_date="2026-11-25", trip_time="10:00",
                base_fare=62, net_earnings=62, distance_km=5.31, kind="full", service_type="Saver Bike")
    base.update(kw)
    with db.engine.begin() as c:
        return c.execute(insert(db.trips).values(**base)).inserted_primary_key[0]


trip(a, FULL, committed=1)
cut = trip(b, "A-AWBF7H4W", trip_time="10:01")
r = db.approve_trip(cut)
check("❗ ปุ่มอนุมัติไม่นับรหัสที่ขาดท้ายซ้ำกับรหัสเต็มที่อนุมัติแล้ว", "error" in r and not db.get_trip(cut)["committed"], r)
waiting = trip(b, "A-AWBF7H4WQP...", trip_time=None)
st = db.auto_approve_job(b)
t = db.get_trip(waiting)
check("❗ รอบอนุมัติอัตโนมัติก็กักไว้ให้คนดู", not t["committed"] and same_trip.SUSPECT in (t["note"] or ""), (st, t["note"]))

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
