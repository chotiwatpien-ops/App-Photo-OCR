# -*- coding: utf-8 -*-
"""Rows whose money was wrong yet passed the check and went to the customer (audit 2026-10-31).

Each case was reproduced on the code before this fix:
1. pair_fragments' third pass took bonus/turbo/tolls from a lower half whose own fare disagreed
   with the top: slip ฿35, Phase 3 Net ฿85.
2. No base fare + a bonus that already holds the tip: the tip was added again and the base
   was then derived to balance, so the row passed with the tip twice.
3. A net misread by up to 20% of base became "hidden turbo" and passed on its own say-so.
4. Ride Fare derived from what the passenger paid ignored the tip, the intl fee and the
   discount/insurance/toll lines: 196 for a 156 trip.
5. A lone lower half took the model's guessed car/bike over the rider's group.
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-money-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import config                                                   # noqa: E402
import db                                                       # noqa: E402
import excel_writer                                             # noqa: E402
import ingest                                                   # noqa: E402
import pipeline                                                 # noqa: E402

db.init_db()
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


def read(job, name, **data):
    tid = db.create_trip(job, name, None, "image/jpeg")
    pipeline.apply_extraction(tid, job, {"kind": "full", **data})
    return db.get_trip(tid)


# --- 1. third pairing pass ------------------------------------------------------------------
job = db.create_job("สมชาย", "Trips", "2026-08-24", "2026-08-30", category="2 W Saver")
top = read(job, "1.jpg", kind="top", net_earnings=35, base_fare=35, booking_code="A-THIRDPASS0001",
           service_type="Saver Bike")
bot = read(job, "2.jpg", kind="bottom", net_earnings=120, base_fare=120, tolls=50,
           passenger_total=150)
pipeline.pair_fragments(job)
t = db.get_trip(top["id"])
check("รอบ 3 ยังรวมสองครึ่งเป็นแถวเดียว (กฎทีม: ส่งติดกันเสมอ)", t["kind"] == "full")
check("รอบ 3 ไม่เอาค่าทางด่วนจากครึ่งล่างที่ยอดขัดกัน", not t["tolls"], t["tolls"])
check("ครึ่งล่างที่ยอดขัดกับครึ่งบน ต้องรอคนดู ไม่ผ่านเอง", t["check_status"] != "pass", t["check_status"])

job3 = db.create_job("สมหญิง", "Trips", "2026-08-24", "2026-08-30", category="2 W Saver")
top = read(job3, "1.jpg", kind="top", net_earnings=35, base_fare=35, booking_code="A-THIRDPASS0002",
           service_type="Saver Bike")
read(job3, "2.jpg", kind="bottom", passenger_total=40, passenger_paid=41, app_fee=-1)
pipeline.pair_fragments(job3)
t = db.get_trip(top["id"])
check("ครึ่งล่างที่ไม่มียอดของคนขับ: รวมได้และผ่านตามเดิม",
      t["kind"] == "full" and t["passenger_total"] == 40 and t["check_status"] == "pass", t["check_status"])

# --- 2. tip counted twice -------------------------------------------------------------------
job2 = db.create_job("สมศักดิ์", "Trips", "2026-08-24", "2026-08-30", category="4 W Standard")
t = read(job2, "tip.jpg", net_earnings=100, base_fare=None, bonus=20, tip=20)
check("ไม่มีค่าโดยสารพื้นฐาน + โบนัสอาจรวมทิปแล้ว: ไม่ผ่านเอง", t["check_status"] != "pass",
      (t["base_fare"], t["bonus"], t["check_status"]))
check("ไม่คิดค่าโดยสารพื้นฐานจากโบนัสที่นับทิปซ้ำ (60)", t["base_fare"] != 60, t["base_fare"])
t = read(job2, "tip2.jpg", net_earnings=100, base_fare=None, bonus=5, tip=20)
check("โบนัสน้อยกว่าทิป (รวมทิปไม่ได้): ยังคิดค่าโดยสารพื้นฐานให้ได้",
      t["base_fare"] == 75 and t["check_status"] == "pass", (t["base_fare"], t["check_status"]))
t = read(job2, "nobase.jpg", net_earnings=90, base_fare=None, bonus=10)
check("ไม่มีทิป: คิดค่าโดยสารพื้นฐานจาก net−bonus ได้ตามเดิม", t["base_fare"] == 80 and t["check_status"] == "pass")

# --- 3. hidden turbo needs a second witness -------------------------------------------------
t = read(job2, "misread.jpg", net_earnings=57, base_fare=48)
check("เติม turbo จากส่วนต่าง (ยอดลงตัวบนชีต)", t["turbo"] == 9, t["turbo"])
check("ส่วนต่างที่ไม่มีพยานที่สอง ต้องรอคนดู", t["check_status"] != "pass", t["check_status"])
t = read(job2, "witness-left.jpg", net_earnings=57, base_fare=48, net_earnings_left_panel=57)
check("จอซ้ายพิมพ์ net เท่ากัน: เติมแล้วผ่านเองได้", t["turbo"] == 9 and t["check_status"] == "pass", t["check_status"])
t = read(job2, "witness-fare.jpg", net_earnings=57, base_fare=48, passenger_total=71, grab_commission=14)
check("ค่าโดยสาร − ส่วนแบ่ง Grab = net: เติมแล้วผ่านเองได้", t["turbo"] == 9 and t["check_status"] == "pass",
      t["check_status"])

tid = db.create_trip(job2, "old.jpg", None, "image/jpeg")
db.update_trip(tid, {"status": "done", "check_status": "fail", "net_earnings": 57, "base_fare": 48,
                     "bonus": 0, "turbo": 0, "kind": "full"})
ingest.fix_hidden_turbo()
t = db.get_trip(tid)
check("รอบเก็บตก: เติม turbo ให้แถวที่รออยู่", t["turbo"] == 9, t["turbo"])
check("รอบเก็บตก: แถวที่ไม่มีพยานที่สองยังรอคน ไม่กลายเป็นผ่าน", t["check_status"] != "pass", t["check_status"])

# --- 4. Ride Fare from what the passenger paid ---------------------------------------------
config.PASSENGER_FARE_SOURCE = "total"
fare = excel_writer.passenger_fare({"passenger_paid": 206, "app_fee": -20, "other_adj": 10, "tip": 40,
                                    "base_fare": 130, "service_type": "Standard Car"})
check("ยอดที่ชำระ 206 แอป −20 อื่น +10 ทิป 40 → ค่าโดยสาร 156", fare == 156, fare)
fare = excel_writer.passenger_fare({"passenger_paid": 458, "app_fee": -20, "intl_fee": 13,
                                    "passenger_tolls": -140, "base_fare": 230})
check("ยอดที่ชำระ 458 แอป −20 ต่างประเทศ 13 ทางด่วน −140 → 285", fare == 285, fare)
fare = excel_writer.passenger_fare({"passenger_paid": 60, "discount": 20, "insurance_fee": -5})
check("ส่วนลด +20 ประกัน −5 → 75", fare == 75, fare)
config.PASSENGER_FARE_SOURCE = "paid"
paid = excel_writer.passenger_fare({"passenger_total": 156, "app_fee": -20, "other_adj": 10, "tip": 40})
check("โหมดยอดที่ชำระ: กลับทางได้ 206", paid == 206, paid)
config.PASSENGER_FARE_SOURCE = "total"

# --- 5. a lone lower half takes the rider's group -------------------------------------------
t = read(job, "3.jpg", kind="bottom", net_earnings=44, base_fare=44, service_type="Standard Car")
check("ครึ่งล่างลำพังในกลุ่ม 2 W Saver ได้ Saver Bike ไม่ใช่รถที่โมเดลเดา",
      t["service_type"] == "Saver Bike", t["service_type"])

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
