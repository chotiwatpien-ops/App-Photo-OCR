# -*- coding: utf-8 -*-
"""The overview tab: progress by Service Type, what to do next, when the next reading round is."""
import os
import sys
import tempfile
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-overview-")
os.environ.pop("DATABASE_URL", None)
os.environ["WEEKLY_TARGET_PER_GROUP"] = "5"
sys.path.insert(0, "backend")

from sqlalchemy import insert                                   # noqa: E402

import config                                                   # noqa: E402
import db                                                       # noqa: E402
import overview                                                 # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


W = ("2026-09-28", "2026-10-04")
saver = db.create_job("ธีรพล Win", "Trips", *W, category="2 W Saver")
std = db.create_job("กิตติ Win", "Trips", *W, category="2 W Standard")
car = db.create_job("สมหมาย Taxi", "Trips", *W, category="4 W Standard")
hold = db.create_job(db.HOLDING_RIDER, "Trips", *W)


def add(job, **kw):
    with db.engine.begin() as c:
        c.execute(insert(db.trips).values(job_id=job, file_name="x.jpg", **kw))


for _ in range(5):
    add(saver, status="done", committed=1, service_type="Saver Bike", trip_date="2026-09-29", check_status="pass")
add(saver, status="done", committed=1, service_type="Standard Bike", trip_date="2026-09-29")     # chip says Standard
add(std, status="done", committed=0, service_type="Standard Bike", trip_date="2026-09-30", check_status="fail")
add(std, status="done", committed=0, service_type="Standard Bike", trip_date=None, check_status="pass")
add(std, status="pending", committed=0)                                                          # by its folder
add(car, status="done", committed=0, service_type="Standard | Women driver", trip_date="2026-09-30", check_status="pass")
add(car, status="duplicate", committed=0, service_type="Standard Car")
add(hold, status="done", committed=0, service_type="Standard Car", trip_date="2026-10-01")       # waiting to be filed
add(hold, status="pending", committed=0)                                                         # in the pool, no group yet
add(car, status="error", committed=0)

ov = overview.build(*W, now=datetime(2026, 10, 2, 14, 0))
g = {x["service"]: x for x in ov["groups"]}
check("นับตาม Service Type ไม่ใช่โฟลเดอร์: ชิป Standard ในโฟลเดอร์ Saver ไปอยู่ Standard Bike",
      g["Saver Bike"]["filed"] == 5 and g["Standard Bike"]["filed"] == 1)
check("แถวรอตรวจนับเป็น 'รอตรวจ'", g["Standard Bike"]["review"] == 2)
check("รูปที่ยังไม่อ่านนับตามกลุ่มของโฟลเดอร์", g["Standard Bike"]["reading"] == 1)
check("'Standard | Women driver' เป็นรถยนต์", g["Standard Car"]["review"] == 1)
check("❗ แถวที่อ่านแล้วรอลงโฟลเดอร์นับเป็น 'รออ่าน' ไม่ใช่รอตรวจ", g["Standard Car"]["reading"] == 1)
check("❗ แถวซ้ำไม่ถูกนับ", g["Standard Car"]["have"] == 2)
check("ขาดเท่าไหร่ต่อ Service Type", g["Standard Bike"]["short"] == 1 and g["Standard Car"]["short"] == 3 and g["Saver Bike"]["short"] == 0)
check("รูปในกองที่ยังไม่รู้กลุ่มนับรวมในรออ่านทั้งหมด", ov["reading"]["total"] == 3)
check("รูปอ่านไม่สำเร็จนับแยก", ov["errors"] == 1)

r = ov["review"]
check("เหตุผลในคิว: ตัวเลข 1 · ไม่มีวันที่ 1 · ผ่านรอกด 1", (r["money"], r["date"], r["ready"], r["total"]) == (1, 1, 1, 3))
kinds = [t["kind"] for t in ov["todos"]]
check("❗ สิ่งที่ต้องทำเรียง: ตรวจคิว → ขอรูปเพิ่ม → รอผลอ่าน → รูปอ่านไม่ได้", kinds == ["review", "short", "reading", "errors"])
check("ข้อความขอรูปบอกจำนวนต่อ Service Type", "Standard Bike 1" in ov["todos"][1]["title"] and "Standard Car 3" in ov["todos"][1]["title"])
check("ไรเดอร์ที่ยังรับได้: เฉพาะกลุ่มที่ขาด", {x["name"] for x in ov["riders"]} == {"กิตติ Win", "สมหมาย Taxi"})
check("รับได้อีก = 21 − ที่มี (แถวซ้ำไม่นับ)",
      {x["name"]: x["room"] for x in ov["riders"]} == {"กิตติ Win": 18, "สมหมาย Taxi": 19})

n = overview.next_round
check("รอบถัดไปตามตาราง (xx:23 ชั่วโมงที่หาร 3 เหลือ 1)", n(datetime(2026, 10, 2, 14, 0)) == datetime(2026, 10, 2, 16, 23))
check("รอบที่เพิ่งจบไม่ถึง 2.5 ชม. ทำให้รอบถัดไปถูกข้าม",
      n(datetime(2026, 10, 2, 14, 0), datetime(2026, 10, 2, 14, 30)) == datetime(2026, 10, 2, 19, 23))

with db.engine.begin() as c:
    c.execute(db.trips.delete())
empty = overview.build(*W, now=datetime(2026, 10, 2, 14, 0))
check("สัปดาห์ว่างก็มีสิ่งที่ต้องทำ (ขอรูปทุกกลุ่ม) ไม่พัง", empty["todos"][0]["kind"] == "short")

import main                                                     # noqa: E402
from fastapi.testclient import TestClient                       # noqa: E402

config.APP_PASSWORD = ""
res = TestClient(main.app).get(f"/api/overview?week={W[0]}")
check("endpoint ตอบได้", res.status_code == 200 and res.json()["week"] == W[0] and len(res.json()["groups"]) == 3)

print("\nผ่านทั้งหมด" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
