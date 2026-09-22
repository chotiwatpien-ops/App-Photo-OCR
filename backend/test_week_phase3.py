# -*- coding: utf-8 -*-
"""A delivered week comes out again in the Phase 3 layout, as its own file (W35, 2026-09-22)."""
import io
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-wk3-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from openpyxl import load_workbook                              # noqa: E402
from sqlalchemy import insert, select                                   # noqa: E402

import db                                                       # noqa: E402
import excel_writer                                             # noqa: E402
import week_phase3 as wp                                        # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


W35 = ("2026-08-24", "2026-08-30")
j = db.create_job("สมชาย Win", "Trips", *W35, category="2 W Saver")
other = db.create_job("สมชาย Win", "Trips", "2026-08-31", "2026-09-06", category="2 W Saver")
with db.engine.begin() as c:
    base = dict(status="done", committed=1, service_type="Saver Bike", base_fare=30.0, net_earnings=30.0,
                passenger_paid=40.0, passenger_total=35.0, app_fee=1.0, discount=4.0)
    c.execute(insert(db.trips).values(job_id=j, file_name="a.jpg", trip_date="2026-08-25", **base))
    c.execute(insert(db.trips).values(job_id=j, file_name="b.jpg", trip_date="2026-08-24", **base))
    c.execute(insert(db.trips).values(job_id=j, file_name="dup.jpg", trip_date="2026-08-24",
                                      **{**base, "status": "duplicate"}))
    c.execute(insert(db.trips).values(job_id=j, file_name="wait.jpg", trip_date="2026-08-24",
                                      **{**base, "committed": 0}))
    c.execute(insert(db.trips).values(job_id=other, file_name="w36.jpg", trip_date="2026-08-31", **base))

rows = wp.week_rows(*W35)
check("เฉพาะแถวของสัปดาห์นั้นที่อนุมัติแล้ว (ไม่เอาซ้ำ ไม่เอาที่รอคน ไม่เอาสัปดาห์อื่น)",
      sorted(r["file_name"] for r in rows) == ["a.jpg", "b.jpg"])
check("ชื่อไฟล์บอกสัปดาห์และ Phase 3", wp.file_name(W35[0]) == "Rider Trips 2026-W35 Phase 3.xlsx")
out = os.path.join(WORK, "w35.xlsx")
check("รันได้ เขียนไฟล์ได้", wp.main(["--from", W35[0], "--to", W35[1], "--xlsx", out]) == 0)
ws = load_workbook(out).active
head = [c.value for c in ws[1]]
check("❗ หัวคอลัมน์เป็นแบบ Phase 3 แม้วันที่จะก่อน W38",
      head[:len(excel_writer.FARE_LINES_HEADERS)] == excel_writer.FARE_LINES_HEADERS
      and "Total Commission (THB)" in head)
check("สองแถว เรียงตามวันที่", ws.max_row == 3 and ws.cell(2, 1).value <= ws.cell(3, 1).value)
check("ส่วนลดอยู่คอลัมน์ของตัวเอง", ws.cell(2, head.index("Discount") + 1).value in (4, 4.0))

# --- the clean version: one row per booking code (W34, 2026-09-23) ------------------------------
W34 = ("2026-08-17", "2026-08-23")
j1 = db.create_job("จิตติ", "Trips", *W34, category="4 W Standard")
j2 = db.create_job("สมชาย", "Trips", *W34, category="4 W Standard")
with db.engine.begin() as c:
    ins = lambda **kw: c.execute(insert(db.trips).values(**{**base, "service_type": "Standard Car",
                                                             "trip_date": "2026-08-18", **kw})).inserted_primary_key[0]
    first = ins(job_id=j1, file_name="a1.jpg", booking_code="A-9IPKOL4WWENVAV", base_fare=111.0, customer_image="WK34-จิตติ1.jpg")
    again = ins(job_id=j2, file_name="b1.jpg", booking_code="a-9ipkol4wwenvav ", base_fare=111.0, customer_image="WK34-สมชาย1.jpg")
    odd1 = ins(job_id=j1, file_name="a2.jpg", booking_code="A-9IX6878WWP8QAV", base_fare=175.0)
    odd2 = ins(job_id=j2, file_name="b2.jpg", booking_code="A-9IX6878WWP8QAV", base_fare=184.0)
    alone = ins(job_id=j2, file_name="b3.jpg", booking_code=None, base_fare=50.0)
rows34 = wp.week_rows(*W34)
kept, dropped, held = wp.drop_repeats(rows34)
check("❗ รหัสเดียวกัน (ต่างตัวพิมพ์/ช่องว่าง) เก็บใบที่อ่านก่อน ตัดใบหลัง",
      [r["id"] for r, _k in dropped] == [again] and dropped[0][1]["id"] == first)
check("รหัสเดียวกันแต่ค่ารอบไม่ตรง ยังไม่ตัด ส่งให้คนดู",
      {odd1, odd2} <= {r["id"] for r in kept} and [sorted(r["id"] for r in g) for g in held] == [sorted([odd1, odd2])])
check("แถวที่ไม่มีรหัสอยู่ครบ", alone in {r["id"] for r in kept})
out34 = os.path.join(WORK, "w34c.xlsx")
check("ฉบับคลีนรันได้", wp.main(["--from", W34[0], "--to", W34[1], "--drop-repeats", "--xlsx", out34]) == 0)
wb34 = load_workbook(out34)
check("ชื่อไฟล์ฉบับคลีนแยกจากฉบับเต็ม", wp.file_name(W34[0], clean=True) == "Rider Trips 2026-W34 Phase 3 (คลีน).xlsx")
check("ฉบับคลีนมีแถวน้อยลงหนึ่งแถว และมีชีตรายการที่ตัดออกกับที่ยังไม่ตัด",
      wb34.active.max_row == 1 + len(rows34) - 1
      and wb34["ตัดออก-งานซ้ำ"].max_row == 2 and wb34["ยังไม่ตัด-ค่ารอบไม่ตรง"].max_row == 3)
with db.engine.begin() as c:
    check("ไม่แตะฐานข้อมูล", c.execute(select(db.trips.c.status).where(db.trips.c.id == again)).scalar() == "done")

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
