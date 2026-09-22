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
      [r["id"] for r, _k, _w in dropped] == [again] and dropped[0][1]["id"] == first)
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

# --- the same trip twice under one rider, no code to say so (W34 วรวิทย์) ------------------------
def row(i, f, base=None, net=None, paid=None, tot=None, code=None, t="21:40", rider="วรวิทย์"):
    return {"id": i, "file_name": f, "base_fare": base, "net_earnings": net, "passenger_paid": paid,
            "passenger_total": tot, "booking_code": code, "trip_time": t, "driver_name": rider,
            "category": "4 W Standard"}


V = [row(1, "5.jpg", 99, 104, t="21:34"),                       # album top
     row(2, "7.jpg", None, None, 120, 122, t="21:35"),           # album bottom, counted on its own
     row(3, "วรวิทย์ 2.jpg", 99, 104, 120, 122, "A-9NI2HPR", "21:34"),   # the second upload, joined
     row(4, "22.jpg", 247, 259, t="21:46"),                      # a top whose joined copy was set aside
     row(5, "24.jpg", 0, None, 450, 305, t="21:47"),             # ...and its bottom, two pictures on
     row(6, "25.jpg", 289, 303, t="21:47"),                      # the next top — must not take 24.jpg
     row(7, "34.jpg", 74, 78, code="A-9O3NIXK...", t="21:51"),   # cut-short code, O for 0
     row(8, "วรวิทย์ 12.jpg", 74, 78, 113, 93, "A-903NIXK", "21:51"),
     row(9, "31.jpg", t="21:49"), row(10, "30.jpg", 337, 337, 407, 337, t="21:49"),
     row(11, "S__1.jpg", 26, 26, t="09:10", rider="ปลา"),        # two ฿26 Saver trips of one rider,
     row(12, "S__9.jpg", 26, 26, 30, 26, "A-1", "15:30", rider="ปลา")]   # hours apart: two trips
kept, dropped, held = wp.drop_repeats(V)
ids = {r["id"] for r in kept}
check("❗ ครึ่งบน + ครึ่งล่าง + รูปที่อัปซ้ำของงานเดียวกัน เหลือแถวเดียว (เก็บแถวที่ข้อมูลครบสุด)",
      {1, 2, 3} & ids == {3})
check("ครึ่งล่างที่ไม่มีค่ารอบ ไปรวมกับครึ่งบนที่อยู่ก่อนหน้า ไม่ใช่ครึ่งบนถัดไป",
      {4, 6} <= ids and 5 not in ids and next(k["id"] for r, k, _w in dropped if r["id"] == 5) == 4)
check("รหัสที่ถูกตัด '...' และ O/0 ยังเป็นรหัสเดียวกัน", len({7, 8} & ids) == 1)
check("แถวว่างทุกช่องไปรวมกับรูปข้างกัน", 9 not in ids and 10 in ids)
check("❗ งาน ฿26 สองงานของคนเดียวกันที่เวลาห่างกัน ไม่ถูกรวม", {11, 12} <= ids)
check("ทุกแถวที่ตัดมีเหตุผล", all(w for _r, _k, w in dropped))
# the first W34 run joined these — the '-00' and '_0' every such name ends in looked like one number
M = [row(21, "MyImage-1787829394-00.jpg", 28, 28, 40, 30, t="12:31", rider="พงศ์กฤษณ์"),
     row(22, "MyImage-1787829600-00.jpg", 28, 28, t="12:34", rider="พงศ์กฤษณ์"),
     row(23, "48743_0_48744_0.jpg", 26, 26, 30, 26, t="20:01", rider="สนธยา"),
     row(24, "48757_0_48758_0.jpg", 26, 26, t="20:02", rider="สนธยา"),
     row(25, "Screenshot 2026-08-28 124028.png", 25, 25, 30, 25, t="12:40", rider="อนุรักษ์"),
     row(26, "Screenshot 2026-08-28 124219.png", 25, 25, t="12:42", rider="อนุรักษ์")]
kept, dropped, _ = wp.drop_repeats(M)
check("❗ ชื่อแบบ MyImage-…-00 / …_0_…_0 / Screenshot ในอัปเดียวกัน ค่ารอบเท่ากัน ไม่ถูกรวม", not dropped)

# --- fix_rows: a figure is changed only where the row still holds what a person saw --------------
import fix_rows                                                 # noqa: E402
with db.engine.begin() as c:
    fx = c.execute(insert(db.trips).values(job_id=j1, file_name="k.jpg", status="done", committed=1,
                                           base_fare=0.0, net_earnings=104.0, turbo=5.0)).inserted_primary_key[0]
check("fix_rows: รายงานอย่างเดียวไม่เขียน",
      fix_rows.main(["--fix", f"{fx} base_fare 0 99", "--why", "สลิปพิมพ์ 99"]) == 0
      and db.get_trip(fx)["base_fare"] == 0)
check("fix_rows: ค่าเดิมตรง → แก้ และลงโน้ต",
      fix_rows.main(["--fix", f"{fx} base_fare 0 99", "--why", "สลิปพิมพ์ 99", "--apply"]) == 0
      and db.get_trip(fx)["base_fare"] == 99 and "สลิปพิมพ์ 99" in db.get_trip(fx)["note"])
check("fix_rows: ค่าในแถวเปลี่ยนไปแล้ว → ไม่ทับ",
      fix_rows.main(["--fix", f"{fx} base_fare 0 50", "--why", "x", "--apply"]) == 1
      and db.get_trip(fx)["base_fare"] == 99)

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
