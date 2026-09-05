# -*- coding: utf-8 -*-
"""Two requirements from Ops on 2026-09-05.

1. Repeated work comes out. Until now only the same rider repeating a booking code inside the
   same week counted; the same slip handed in under two rider names flowed through, and over
   W33-W35 that was 1,521 rows (11.6%). Forward-only by Ops' decision — delivered weeks are
   left alone, so these tests are about what happens to work arriving from now on.
2. Sheet1's pick-up and drop-off show the place from the slip, not the zone (which said
   "Downtown" for 10,942 of 13,077 rows).
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-ops-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import config                                                   # noqa: E402
import db                                                       # noqa: E402
import excel_writer                                             # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


def trip(job, code, base=100, when="14:30", date="2026-09-01", name=None):
    t = db.create_trip(job, name or f"{code}.jpg", None, "image/jpeg")
    db.update_trip(t, {"status": "done", "trip_date": date, "trip_time": when,
                       "net_earnings": base, "base_fare": base, "booking_code": code,
                       "check_status": "pass"})
    return t


WEEK = ("2026-08-31", "2026-09-06")
OTHER = ("2026-09-07", "2026-09-13")

# --- 1. งานซ้ำ -------------------------------------------------------------------------------
a = db.create_job("สมชาย", "Trips", *WEEK)
t1 = trip(a, "A-9AAAAAAAAAAAAAV")
db.auto_approve_job(a)
check("ใบแรกอนุมัติผ่านปกติ", db.get_trip(t1)["committed"] == 1)

# คนละไรเดอร์ สัปดาห์เดียวกัน — เดิมปล่อยผ่าน ตอนนี้ต้องถูกตัด
b = db.create_job("สมหญิง", "Trips", *WEEK)
t2 = trip(b, "A-9AAAAAAAAAAAAAV")
db.auto_approve_job(b)
r2 = db.get_trip(t2)
check("คนละไรเดอร์ code เดียวกัน: ไม่อนุมัติ", r2["committed"] == 0)
check("คนละไรเดอร์ code เดียวกัน: ถูกทิ้งออกจากคิว", r2["status"] == "duplicate")
check("บอกไว้ว่าซ้ำกับใบไหน", "ซ้ำกับ" in (r2["note"] or ""))
check("ใบแรกยังอยู่ครบ (เก็บของคนแรก)", db.get_trip(t1)["committed"] == 1)

# คนเดียวกัน คนละสัปดาห์ — เดิม Ops อนุญาต ตอนนี้ต้องถูกตัด
c = db.create_job("สมชาย", "Trips", *OTHER)
t3 = trip(c, "A-9AAAAAAAAAAAAAV", date="2026-09-08")
db.auto_approve_job(c)
check("คนเดียวกัน คนละสัปดาห์: ไม่อนุมัติ", db.get_trip(t3)["committed"] == 0)

# code เดียวกันแต่ยอดไม่ตรง = คำถามจริง ต้องให้คนดู ไม่ใช่ทิ้งเงียบ
d = db.create_job("สมศรี", "Trips", *WEEK)
t4 = trip(d, "A-9AAAAAAAAAAAAAV", base=250)
db.auto_approve_job(d)
r4 = db.get_trip(t4)
check("code ซ้ำแต่ยอดต่างกัน: ไม่อนุมัติ", r4["committed"] == 0)
check("code ซ้ำแต่ยอดต่างกัน: ค้างในคิวให้คนตัดสิน ไม่ทิ้งเอง", r4["status"] == "done")

# code สั้น (ตกบรรทัด) เป็นแค่เบาะแส ต้องมียอด+เวลาตรงด้วยถึงจะนับว่าซ้ำ
e = db.create_job("วิชัย", "Trips", *WEEK)
t5 = trip(e, "A-9SHORT", base=80, when="09:15")
db.auto_approve_job(e)
check("code สั้นใบแรก: อนุมัติปกติ", db.get_trip(t5)["committed"] == 1)

f = db.create_job("วิภา", "Trips", *WEEK)
t6 = trip(f, "A-9SHORT", base=80, when="09:15")
t7 = trip(f, "A-9SHORT", base=145, when="18:40")      # code สั้นชนกัน แต่คนละทริปจริง
db.auto_approve_job(f)
check("code สั้น + ยอด/เวลาตรง: นับว่าซ้ำ", db.get_trip(t6)["committed"] == 0)
check("code สั้น + ยอด/เวลาต่าง: ไม่ตัดผิด อนุมัติได้", db.get_trip(t7)["committed"] == 1)

# ไม่มี code เลย — จับด้วยวิธีนี้ไม่ได้ ต้องไม่พังและต้องไม่บล็อกมั่ว
g = db.create_job("อนันต์", "Trips", *WEEK)
t8 = db.create_trip(g, "nocode.jpg", None, "image/jpeg")
db.update_trip(t8, {"status": "done", "trip_date": "2026-09-02", "net_earnings": 60,
                    "base_fare": 60, "check_status": "pass"})
db.auto_approve_job(g)
check("ไม่มี booking code: ยังอนุมัติได้ตามปกติ", db.get_trip(t8)["committed"] == 1)

check("ใบที่ถูกทิ้งโผล่ในบันทึกให้กู้คืนได้",
      any(x["id"] == t2 for x in db.discarded_duplicates()["rows"]))
db.restore_discarded(t2)
check("กู้กลับเข้าคิวได้", db.get_trip(t2)["status"] == "done")

# --- 2. สถานที่บน Sheet1 ---------------------------------------------------------------------
check("ไม่ได้ปิดการอ่านที่อยู่แล้ว", "pickup_text" not in config.EXTRACT_DROP_FIELDS)
check("มีที่อยู่: ใช้ที่อยู่", excel_writer.place("เอ็มสเฟียร์ ทางออกป้ายรถเมล์", "วัฒนา", "BKK")
      == "เอ็มสเฟียร์ ทางออกป้ายรถเมล์")
check("ไม่มีที่อยู่: ถอยไปใช้โซนเดิม ไม่ปล่อยว่าง",
      excel_writer.place(None, "ดอนเมือง", "BKK") == "North-DMK")
check("ที่อยู่เป็นช่องว่างล้วน: ถือว่าไม่มี", excel_writer.place("   ", "ดอนเมือง", "BKK") == "North-DMK")

check("Analysis ไม่มีคอลัมน์ที่อยู่แล้ว",
      "Pick-up Address" not in excel_writer.ANALYSIS_HEADERS
      and "Drop-off Address" not in excel_writer.ANALYSIS_HEADERS)
check("Analysis ยังเก็บโซนไว้", "Pick-up Zone" in excel_writer.ANALYSIS_HEADERS)
check("หัวตาราง Analysis กับความกว้างยังเท่ากัน",
      len(excel_writer.ANALYSIS_HEADERS) == len(excel_writer.ANALYSIS_WIDTHS))

# ไฟล์ของลูกค้าต้องไม่เปลี่ยนเลย — Sheet1 ยังเป็นโซนเหมือนเดิม
def row(date_, name="สมชาย", pu="เอ็มสเฟียร์ ทางออกป้ายรถเมล์", do="มหานคร สกายวอล์ค"):
    return {"driver_name": name, "trip_date": date_, "trip_time": "14:30",
            "service_type": "Standard Bike", "payment_method": "CASH", "base_fare": 100,
            "net_earnings": 100, "distance_km": 5.0, "passenger_total": 117,
            "pickup_text": pu, "dropoff_text": do, "pickup_district": "วัฒนา",
            "dropoff_district": "บางรัก", "booking_code": "A-9ZZZ",
            "customer_image": "WK36-สมชาย1.jpg"}


import io                                                       # noqa: E402
import openpyxl                                                 # noqa: E402
wb = openpyxl.load_workbook(io.BytesIO(excel_writer.build_workbook([row("2026-08-20")])))
ws = wb[excel_writer.SHEET]
check("Sheet1 ยังเป็นโซนเหมือนเดิม ไม่ถูกทับ", ws.cell(2, 6).value == "Downtown")
check("ไฟล์ลูกค้าไม่มีชีตสถานที่โผล่มา", excel_writer.LOCATION_SHEET not in wb.sheetnames)
check("ไฟล์ลูกค้ายังมี 3 ชีตเท่าเดิม", len(wb.sheetnames) == 3)
check("ความกว้าง F/G กลับเป็นของเดิม", excel_writer.COL_WIDTHS[5] == 12.5)

# Ops 2026-09-06: ตกลงว่าไม่ยุ่งไฟล์เก่าแล้ว — ตั้งแต่ W36 ต้องไม่โผล่ในไฟล์ลูกค้าอีกเลย
mixed = excel_writer.build_workbook([row("2026-08-20"), row("2026-09-07"),
                                     row("2026-09-14", name="สมหญิง")])
mw = openpyxl.load_workbook(io.BytesIO(mixed))[excel_writer.SHEET]
check("ไฟล์เก่าหยุดที่ W35: 3 แถวเข้าไปแค่แถวเดียว", mw.max_row == 2)
check("แถวที่เหลืออยู่คือของเก่าจริง", mw.cell(2, 2).value.strftime("%Y-%m-%d") == "2026-08-20")
check("ไม่มีทริปเก่าเลย: ไฟล์ลูกค้าว่าง ไม่ error",
      openpyxl.load_workbook(io.BytesIO(excel_writer.build_workbook(
          [row("2026-09-07")])))[excel_writer.SHEET].max_row == 1)

# --- ไฟล์ Phase 2 -----------------------------------------------------------------------------
check("ชื่อไฟล์มี Phase 2", "Phase 2" in excel_writer.LOCATION_FILE)
check("เริ่มที่ W36", excel_writer.LOCATION_FROM_WEEK == "2026-W36")
check("W35 ไม่เข้า", not excel_writer.in_location_scope("2026-08-30"))
check("W36 เข้า", excel_writer.in_location_scope("2026-08-31"))
check("ปีถัดไปยังเข้า (เทียบสัปดาห์ไม่ใช่เทียบเลข)", excel_writer.in_location_scope("2027-01-04"))

check("ไม่มีทริปในขอบเขต: ไม่สร้างไฟล์เปล่า",
      excel_writer.build_location_workbook([row("2026-08-20")]) is None)

data = excel_writer.build_location_workbook([row("2026-08-20"), row("2026-09-07"),
                                             row("2026-09-14", name="สมหญิง")])
lb = openpyxl.load_workbook(io.BytesIO(data))
lw = lb[excel_writer.LOCATION_SHEET]
check("Phase 2 มีชีตเดียว", len(lb.sheetnames) == 1)
check("Phase 2 เอาเฉพาะตั้งแต่ W36 (2 จาก 3 แถว)", lw.max_row == 3)
# Ops 2026-09-06: ขอคอลัมน์ชุดเดียวกับไฟล์ส่งงาน ไม่ใช่ตารางค้นสถานที่
check("Phase 2 ใช้คอลัมน์ชุดเดียวกับ Sheet1",
      [lw.cell(1, c).value for c in range(1, len(excel_writer.HEADERS) + 1)] == excel_writer.HEADERS)
check("Phase 2 ต้นทางเป็นสถานที่จริง", lw.cell(2, 6).value == "เอ็มสเฟียร์ ทางออกป้ายรถเมล์")
check("Phase 2 ปลายทางเป็นสถานที่จริง", lw.cell(2, 7).value == "มหานคร สกายวอล์ค")
check("Phase 2 มีตัวเงินครบเหมือนไฟล์ส่งงาน", lw.cell(2, 11).value == 100)
check("Phase 2 ยังคำนวณ Grab Service Fee ด้วยสูตรเดิม", lw.cell(2, 17).value == "=P2-J2")
check("Phase 2 โยงกลับไฟล์รูปได้", lw.cell(2, 18).value == "WK36-สมชาย1.jpg")
check("Phase 2 เรียงตามวันที่", lw.cell(3, 1).value == "สมหญิง")
check("ไม่มีที่อยู่: Phase 2 ถอยไปใช้โซน ไม่ปล่อยว่าง",
      openpyxl.load_workbook(io.BytesIO(excel_writer.build_location_workbook(
          [row("2026-09-07", pu=None, do=None)]))
      )[excel_writer.LOCATION_SHEET].cell(2, 6).value == "Downtown")

# --- เคลียร์บันทึกรูปซ้ำ (Ops: ของเก่า ignore ไป เริ่มนับใหม่) --------------------------------
before = db.discarded_duplicates()
n_before = len(before["rows"])
check("บันทึกรูปซ้ำมีของอยู่ก่อนเคลียร์", n_before > 0 and before["hidden"] == 0)

n = db.clear_discarded_log()
after = db.discarded_duplicates()
check("เคลียร์แล้วนับใหม่จากศูนย์", after["rows"] == [])
check("บอกจำนวนที่ซ่อนไว้", after["hidden"] == n_before and n == n_before)
check("ไม่ได้ลบ — ขอดูทั้งหมดยังเห็นครบ",
      len(db.discarded_duplicates(everything=True)["rows"]) == n_before)

# ของใหม่ที่ถูกทิ้งหลังเคลียร์ ต้องโผล่ขึ้นมาเอง
h = db.create_job("ธนา", "Trips", *WEEK)
t9 = trip(h, "A-9AAAAAAAAAAAAAV", name="after-clear.jpg")
db.auto_approve_job(h)
fresh = db.discarded_duplicates()
check("ของใหม่หลังเคลียร์ยังขึ้นตามปกติ", [r["id"] for r in fresh["rows"]] == [t9])
check("ของเก่ายังนับแยกไว้ ไม่หายไปเฉยๆ", fresh["hidden"] == n_before)

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
