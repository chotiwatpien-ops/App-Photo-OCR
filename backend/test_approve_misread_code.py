# -*- coding: utf-8 -*-
"""A person's approve refuses a trip the week already counts under a code read a letter or two
differently.

The round holds such a row (db._hold_suspects), but the อนุมัติ button and 'approve all that pass'
compared booking codes letter for letter. W48 (2026-11-24): four trips whose code had lost a
letter at Grab's line break ('…QTAV' read as '…QTA') were approved a second time from the queue.
The same evidence settle-doubles acts on (same_trip CODE: codes at most two letters apart, same
base fare, same distance) now stops the approve, any rider, the same week."""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-approve-misread-")
os.environ["PHOTO_OCR_EXCEL_APPEND"] = "0"
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from fastapi.testclient import TestClient                       # noqa: E402
from sqlalchemy import insert                                   # noqa: E402

import config                                                   # noqa: E402
import db                                                       # noqa: E402
import main                                                     # noqa: E402

db.init_db()
config.APP_PASSWORD = ""
web = TestClient(main.app)
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


W = ("2026-11-23", "2026-11-29")
a = db.create_job("ก Win", "Trips", *W, category="2 W Saver")
b = db.create_job("ข Win", "Trips", *W, category="2 W Saver")
later = db.create_job("ก Win", "Trips", "2026-11-30", "2026-12-06", category="2 W Saver")


def trip(job, code, **kw):
    base = dict(job_id=job, file_name=f"{job}_{code}.jpg", booking_code=code, status="done",
                committed=0, check_status="pass", trip_date="2026-11-29", trip_time="12:48",
                base_fare=24, net_earnings=24, distance_km=1.75, service_type="Saver Bike")
    base.update(kw)
    with db.engine.begin() as c:
        return c.execute(insert(db.trips).values(**base)).inserted_primary_key[0]


def approve(tid):
    return web.post(f"/api/trips/{tid}/approve")


def counted(tid):
    return db.get_trip(tid)["committed"] == 1


trip(a, "A-AXWKPG3WX2QTA", committed=1)
lost_letter = trip(b, "A-AXWKPG3WX2QTAV")
r = approve(lost_letter)
check("❗ รหัสที่อ่านตกไป 1 ตัว ค่ารอบและระยะทางตรงกัน: ปุ่มอนุมัติไม่นับซ้ำ (ไรเดอร์คนละคนก็ตาม)",
      not counted(lost_letter), r.json())
check("ข้อความบอกว่าซ้ำกับรูปไหน และให้ทำอะไร", "A-AXWKPG3WX2QTA.jpg" in r.text and "ไม่ใช้งานนี้" in r.text, r.text)

trip(a, "A-9V2FVVWXX9UDAV", committed=1, base_fare=33, net_earnings=33, distance_km=4.06)
o_for_0 = trip(b, "A-9V2FVVWX9UDAV", base_fare=33, net_earnings=33, distance_km=4.06)
bulk = web.post("/api/review-queue/approve-passing").json()
check("❗ อนุมัติทุกแถวที่ตัวเลขผ่าน ก็ไม่นับซ้ำ และบอกว่าแถวไหนไม่ได้อนุมัติ",
      not counted(o_for_0) and any("A-9V2FVVWXX9UDAV" in f["error"] for f in bulk["failed"]), bulk)

other_fare = trip(b, "A-AXWKPG3WX2QTAW", base_fare=40, net_earnings=40)
check("รหัสใกล้กันแต่ค่ารอบต่างกัน: เป็นคนละเที่ยว อนุมัติได้", approve(other_fare).status_code == 200 and counted(other_fare))
other_km = trip(b, "A-AXWKPG3WX2QTAX", distance_km=9.9)
check("รหัสใกล้กันแต่ระยะทางต่างกัน: อนุมัติได้", approve(other_km).status_code == 200 and counted(other_km))
far_code = trip(b, "A-ZZZZZZZZZZZZZZ")
check("ค่ารอบและระยะทางตรงกันแต่รหัสต่างกันมาก (ลูกค้าเส้นทางประจำ): อนุมัติได้", approve(far_code).status_code == 200 and counted(far_code))
next_week = trip(later, "A-AXWKPG3WX2QTAV", trip_date="2026-12-01")
check("ข้ามสัปดาห์ไม่นับว่าซ้ำ (ลูกค้ากำหนด 2026-09-14)", approve(next_week).status_code == 200 and counted(next_week))
short = trip(b, "A-VRF00019", base_fare=55, net_earnings=55, distance_km=2.0)
trip(a, "A-VRF00020", base_fare=55, net_earnings=55, distance_km=2.0, committed=1)
check("รหัสสั้น (อ่านตัดหาย) ไม่เทียบแบบนี้", approve(short).status_code == 200 and counted(short))

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
