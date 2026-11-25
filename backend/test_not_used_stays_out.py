# -*- coding: utf-8 -*-
"""A row a person takes out as a repeat stays out, even when its twin's booking code was read
a letter differently.

W48, 2026-11-24: four rows were taken out with 'ไม่ใช้งานนี้' because they repeated an approved
trip whose code had lost a letter at the line break ('…QTAV' read as '…QTA'). Taking a row out
also released the parked copies of its own code when no live row held that exact code, and the
row it had just parked was one of them. So each row went straight back into the queue as
passing, and 'approve all that pass' counted the four trips twice 52 seconds later."""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-notused-out-")
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
job = db.create_job("ก Win", "Trips", *W, category="2 W Saver")


def trip(name, **kw):
    base = dict(job_id=job, file_name=name, status="done", committed=0, check_status="pass",
                trip_date="2026-11-29", trip_time="12:48", base_fare=24, net_earnings=24,
                distance_km=1.75, pickup_text="จุดรับ ก", dropoff_text="จุดส่ง ข",
                service_type="Saver Bike")
    base.update(kw)
    with db.engine.begin() as c:
        return c.execute(insert(db.trips).values(**base)).inserted_primary_key[0]


counted = trip("a_1+2_฿24.jpg", booking_code="A-TESTCODE00QTA", committed=1)
repeat = trip("a_3+4_฿24.jpg", booking_code="A-TESTCODE00QTAV")

r = web.post(f"/api/trips/{repeat}/not-used").json()
check("กดไม่ใช้งานนี้: แถวถูกพักเป็นงานซ้ำ", r.get("status") == "duplicate", r)
t = db.get_trip(repeat)
check("❗ แถวที่เพิ่งพักไม่เด้งกลับเข้าคิวเอง", t["status"] == "duplicate", t["status"])
check("❗ ไม่มีโน้ต 'กลับเข้าคิว' ต่อท้าย", "กลับเข้าคิว" not in (t["note"] or ""), t["note"])
ids = [x["id"] for x in web.get("/api/review-queue").json()["rows"]]
check("แถวนั้นไม่อยู่ในคิวตรวจ", repeat not in ids, ids)
bulk = web.post("/api/review-queue/approve-passing").json()
check("❗ อนุมัติทุกแถวที่ตัวเลขผ่าน ไม่เอาแถวที่พักไว้ไปนับซ้ำ",
      db.get_trip(repeat)["committed"] == 0 and repeat not in bulk.get("ids", []), bulk)

plain = trip("b_5+6_฿80.jpg", booking_code="A-OTHERCODE0001", base_fare=80, net_earnings=80,
             distance_km=9.9, pickup_text="อื่น", dropoff_text="อื่น")
parked = trip("b_7+8_฿80.jpg", booking_code="A-OTHERCODE0001", base_fare=80, net_earnings=80,
              distance_km=9.9, pickup_text="อื่น", dropoff_text="อื่น", status="duplicate")
r = web.post(f"/api/trips/{plain}/not-used").json()
check("แถวที่ไม่ใช่งาน (ไม่มีคู่ที่นับแล้ว) ถูกพักเป็น voided ตามเดิม", r.get("status") == "voided", r)
check("สำเนาที่พักไว้ของรหัสเดียวกันกลับเข้าคิวแทน เพราะไม่เหลือแถวไหนนับรหัสนี้",
      db.get_trip(parked)["status"] == "done", db.get_trip(parked)["status"])

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
