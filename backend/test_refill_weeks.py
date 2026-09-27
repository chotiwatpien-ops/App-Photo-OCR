# -*- coding: utf-8 -*-
"""Topping up a delivered week from Ops' folder: only the groups still short, only riders already
working, past 21 each, dates inside the week, picture numbers after the rider's last one — and
never a repeat of what the weeks already hold (W34/W35, 2026-09-23)."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-refill-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
os.environ["WEEKLY_TARGET_PER_GROUP"] = "3"
sys.path.insert(0, "backend")

from sqlalchemy import insert                                   # noqa: E402

import db                                                       # noqa: E402
import refill_weeks as rw                                       # noqa: E402
from drive_client import LocalDrive                             # noqa: E402
from file_after_read import HOLDING_RIDER                        # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


A, B = "2026-08-17", "2026-08-24"
root = Path(WORK) / "drive"
(root / "exports").mkdir(parents=True)
(root / "staged").mkdir()

# W34: Standard Bike has 2 of 3 (room 1), Saver is full (3 of 3). W35: Standard Bike 1 of 3.
somchai = db.create_job("สมชาย", "Trips", A, rw.week_end(A), category="2 W Standard")
dang = db.create_job("แดง", "Trips", A, rw.week_end(A), category="2 W Standard")
saver = db.create_job("น้อย", "Trips", A, rw.week_end(A), category="2 W Saver")
b_rider = db.create_job("ขาว", "Trips", B, rw.week_end(B), category="2 W Standard")
hold = db.create_job(HOLDING_RIDER, "Trips", A, rw.week_end(A))
with db.engine.begin() as c:
    def row(**kw):
        return c.execute(insert(db.trips).values(**{
            "status": "done", "committed": 1, "check_status": "pass", "trip_date": A,
            "file_name": "x.jpg", **kw})).inserted_primary_key[0]
    row(job_id=somchai, service_type="Standard Bike", booking_code="A-OLD1", base_fare=30,
        net_earnings=30, distance_km=3.0, customer_image="WK34-สมชาย1.jpg")
    row(job_id=somchai, service_type="Standard Bike", booking_code="A-OLD2", base_fare=31,
        net_earnings=31, distance_km=3.1, customer_image="WK34-สมชาย2.jpg")
    for i in range(3):
        row(job_id=saver, service_type="Saver Bike", booking_code=f"A-SV{i}", base_fare=20 + i,
            net_earnings=20 + i, distance_km=2.0 + i)
    row(job_id=b_rider, service_type="Standard Bike", booking_code="A-B1", base_fare=40,
        net_earnings=40, distance_km=4.0, trip_date=B, customer_image="WK35-ขาว1.jpg")

    def wait(name, **kw):
        pic = root / "staged" / name
        pic.write_bytes(b"jpeg:" + name.encode())
        return row(job_id=hold, committed=0, source_url=f"https://drive.google.com/file/d/{pic}/view",
                   note=f"{rw.MARK}: test/{name}", **kw)
    new1 = wait("n1.jpg", service_type="Standard Bike", booking_code="A-NEW1", base_fare=50,
                net_earnings=50, distance_km=5.0)
    new2 = wait("n2.jpg", service_type="Standard Bike", booking_code="A-NEW2", base_fare=51,
                net_earnings=51, distance_km=5.1)
    new3 = wait("n3.jpg", service_type="Standard Bike", booking_code="A-NEW3", base_fare=52,
                net_earnings=52, distance_km=5.2)
    new4 = wait("n4.jpg", service_type="Standard Bike", booking_code="A-NEW4", base_fare=53,
                net_earnings=53, distance_km=5.3)
    rep_code = wait("r1.jpg", service_type="Standard Bike", booking_code="A-0LD1", base_fare=30,
                    net_earnings=30, distance_km=3.0)                  # O read as 0 — same slip
    rep_print = wait("r2.jpg", service_type="Standard Bike", booking_code=None, base_fare=40,
                     net_earnings=40, distance_km=4.0)                 # W35's A-B1, old screen
    saver_new = wait("s1.jpg", service_type="Saver Bike", booking_code="A-SVNEW", base_fare=25,
                     net_earnings=25, distance_km=2.5)
    express = wait("e1.jpg", service_type="GrabExpress (Bike)", booking_code="A-EX1", base_fare=155,
                   net_earnings=155, distance_km=19.4)
    bad = wait("b1.jpg", service_type="Standard Bike", booking_code="A-BAD", base_fare=60,
               net_earnings=70, distance_km=6.0, check_status="fail")
    half = row(job_id=hold, committed=0, service_type="Standard Bike", booking_code=None, base_fare=46,
               net_earnings=46, distance_km=7.4, note=f"{rw.MARK}: สัญญา 6 Aug/03.jpg | จากตัวอ่าน")
    paired_page = wait("p1.jpg", service_type="Standard Bike", booking_code=None, base_fare=47,
                       net_earnings=47, distance_km=7.5)
    two_cars = row(job_id=hold, committed=0, service_type="Standard Car", booking_code="A-CAR1",
                   base_fare=174, net_earnings=174, distance_km=5.3,
                   note=f"{rw.MARK}: 4 W Standard/3 AUG (1).jpg+3 AUG (2).jpg")
    old_wait = row(job_id=hold, committed=0, service_type="Standard Bike", booking_code="A-PARKED",
                   base_fare=33, net_earnings=33, distance_km=3.3, note="พักไว้จากรอบก่อน")

planned = rw.plan([A, B])
by = {p[0]["id"]: p for p in planned}
check("อ่านเฉพาะแถวของการเติมงาน — แถวที่พักอยู่เดิมไม่แตะ", old_wait not in by and len(planned) == 12)
check("❗ ซ้ำรหัสการจอง (O/0) กับงานที่มีอยู่ → ไม่เติม", by[rep_code][1] is None and "ซ้ำ" in by[rep_code][4])
check("❗ สลิปไม่มีรหัส ยอด+ระยะตรงกับงานของอีกสัปดาห์ → ไม่เติม",
      by[rep_print][1] is None and "ซ้ำ" in by[rep_print][4])
check("❗ Saver ของ W34 เต็มแล้ว → ไม่เติม และไม่ย้ายไปสัปดาห์อื่นนอกจากที่สั่ง",
      by[saver_new][1] is None and "ครบเป้า" in by[saver_new][4])
check("GrabExpress ไม่ใช่งานรับคน → ไม่เติม", by[express][1] is None)
check("ตัวเลขไม่ลงตัว → รอคนดู ไม่เติม", by[bad][1] is None and "ไม่ลงตัว" in by[bad][4])
check("❗ จอเดียวจากหน้ารวมรูป (ไม่มี +) → ไม่เติม", by[half][1] is None and "จอเดียว" in by[half][4])
check("รูปจากอัลบั้มอื่นที่ไม่มี + (รูปทั้งใบ/ต่อแล้ว) ยังเติมได้ตามปกติ", rw.half_of_page(db.get_trip(paired_page)) is False)
check("❗ รูปทั้งใบ 4W สองรูปถูกจับเป็นคู่ → ไม่เติม", by[two_cars][1] is None and "สองเที่ยว" in by[two_cars][4])
check("ที่มาอ่านจากโน้ต", rw.source_of({"note": f"{rw.MARK}: มารุต 3 Aug/01.jpg+02.jpg | x"}) == ("มารุต 3 Aug", "01.jpg+02.jpg"))
wbytes = rw.plan_workbook(planned)
import io as _io, openpyxl as _ox
_wb = _ox.load_workbook(_io.BytesIO(wbytes))
check("ไฟล์แผน: ชีต สรุป/เติม/ไม่เติม และจำนวนแถวตรงกับแผน",
      _wb.sheetnames == ["สรุป", "เติม", "ไม่เติม"]
      and _wb["เติม"].max_row - 1 == sum(1 for p in planned if p[1])
      and _wb["ไม่เติม"].max_row - 1 == sum(1 for p in planned if not p[1]))
check("❗ W34 เติม Standard Bike ได้ 1 (ว่าง 1) ที่เหลือไป W35 จนเต็ม (ว่าง 2)",
      by[new1][1] == A and by[new2][1] == B and by[new3][1] == B and by[new4][1] is None)
check("❗ ได้ไรเดอร์ที่ทำงานสัปดาห์นี้อยู่แล้ว — job ว่าง (แดง) ไม่นับเป็นคนทำงาน",
      by[new1][3] == somchai)

rev = {p[0]["id"]: p for p in rw.plan([B, A])}
check("❗ สลับลำดับ (W35 ก่อน): ยังเห็นแถวที่รออยู่ในที่พักของ W34 และ W35 ได้ก่อน",
      len(rev) == len(planned) and rev[new1][1] == B and rev[new2][1] == B and rev[new3][1] == A)

drive = LocalDrive(root)
n = rw.apply(drive, str(root / "exports"), planned, log=lambda *_: None)
check("ลงงานจริง 3 เที่ยว", n == 3)
t1 = db.get_trip(new1)
check("❗ แถวย้ายเข้า job ของสมชาย อนุมัติแล้ว วันที่อยู่ใน W34",
      t1["job_id"] == somchai and t1["committed"] == 1 and A <= t1["trip_date"] <= rw.week_end(A))
check("❗ รูปต่อเลขเดิม: WK34-สมชาย3.jpg และอยู่ใน Exports/2026-W34/2 W Standard",
      t1["customer_image"] == "WK34-สมชาย3.jpg"
      and (root / "exports" / "2026-W34" / "2 W Standard" / "WK34-สมชาย3.jpg").exists())
t2, t3 = db.get_trip(new2), db.get_trip(new3)
check("❗ W35: ขาวได้เกิน 1 งาน เลขต่อกัน 2, 3 วันที่อยู่ใน W35",
      {t2["customer_image"], t3["customer_image"]} == {"WK35-ขาว2.jpg", "WK35-ขาว3.jpg"}
      and all(B <= t["trip_date"] <= rw.week_end(B) for t in (t2, t3))
      and t2["trip_date"] != t3["trip_date"])
check("แถวที่ไม่เติมยังอยู่ที่พัก ไม่นับ ไม่อนุมัติ",
      all(db.get_trip(x)["job_id"] == hold and db.get_trip(x)["committed"] == 0
          for x in (new4, rep_code, rep_print, saver_new, express, bad, half)))
check("❗ รันแผนซ้ำ: ไม่มีอะไรจะเติมเพิ่ม (กลุ่มเต็มแล้ว)", not [p for p in rw.plan([A, B]) if p[1]])
check("ชื่อโฟลเดอร์สัปดาห์", rw.weeks_folder_name("2026-08-17") == "Week 17-23 Aug"
      and rw.weeks_folder_name("2026-08-31") == "Week 31 Aug-6 Sep")

# a rider named "1": 'WK34-11.jpg' is their first trip, not trip 11 — numbers alone would reuse it
used = {"WK34-11.jpg", "WK34-12.jpg"}
check("❗ ไรเดอร์ชื่อเป็นตัวเลข: ชื่อรูปถัดไปไม่ชนชื่อที่มีอยู่", rw.next_name("1", "WK34", set(), used) == "WK34-13.jpg"
      and rw.next_name("1", "WK34", set(), used) == "WK34-14.jpg")

one = db.create_job("1", "Trips", A, rw.week_end(A), category="2 W Standard")
grp = root / "exports" / "2026-W34" / "2 W Standard"
(grp / "WK34-11.jpg").write_bytes(b"old delivered")
src = root / "staged" / "clash.jpg"
src.write_bytes(b"jpeg:clash")
with db.engine.begin() as c:
    old_row = c.execute(insert(db.trips).values(job_id=one, status="done", committed=1, check_status="pass",
                                                trip_date=A, file_name="o.jpg", service_type="Standard Bike",
                                                booking_code="A-ONE1", base_fare=39, net_earnings=39,
                                                distance_km=3.9, customer_image="WK34-11.jpg")).inserted_primary_key[0]
    clash = c.execute(insert(db.trips).values(job_id=one, status="done", committed=1, check_status="pass",
                                              trip_date=A, file_name="c.jpg", service_type="Standard Bike",
                                              booking_code="A-ONE2", base_fare=32, net_earnings=32,
                                              distance_km=3.2, customer_image="WK34-11.jpg",
                                              source_url=f"https://drive.google.com/file/d/{src}/view",
                                              note=f"{rw.MARK}: test/clash.jpg")).inserted_primary_key[0]
n = rw.renumber(drive, str(root / "exports"), [A], log=lambda *_: None)
check("❗ ซ่อมชื่อชน: เฉพาะแถวที่เติม ได้ชื่อใหม่ที่ว่าง แถวเดิมและรูปเดิมไม่ถูกแตะ",
      n == 1 and db.get_trip(clash)["customer_image"] == "WK34-12.jpg"
      and db.get_trip(old_row)["customer_image"] == "WK34-11.jpg"
      and (grp / "WK34-11.jpg").read_bytes() == b"old delivered"
      and (grp / "WK34-12.jpg").read_bytes() == b"jpeg:clash")
check("ซ่อมซ้ำ: ไม่มีอะไรต้องแก้แล้ว", rw.renumber(drive, str(root / "exports"), [A], log=lambda *_: None) == 0)

# --take-from: W39's Standard Bike finishes a short week (Ops 2026-09-27)
C, D = "2026-09-21", "2026-08-10"
muang = db.create_job("ม่วง", "Trips", D, rw.week_end(D), category="2 W Standard")
big = db.create_job("ใหญ่", "Trips", C, rw.week_end(C), category="2 W Standard")
mid = db.create_job("กลาง", "Trips", C, rw.week_end(C), category="2 W Standard")
cgrp = root / "exports" / "2026-W39" / "2 W Standard"
cgrp.mkdir(parents=True)
with db.engine.begin() as c:
    def crow(job, code, fare, day, pic, **kw):
        src = root / "staged" / f"c-{pic}"
        src.write_bytes(b"jpeg:" + pic.encode())
        (cgrp / pic).write_bytes(b"delivered " + pic.encode())
        return c.execute(insert(db.trips).values(
            job_id=job, status="done", committed=1, check_status="pass", trip_date=day,
            file_name=pic, service_type="Standard Bike", booking_code=code, base_fare=fare,
            net_earnings=fare, distance_km=fare / 10, customer_image=pic,
            source_url=f"https://drive.google.com/file/d/{src}/view", **kw)).inserted_primary_key[0]
    c.execute(insert(db.trips).values(job_id=muang, status="done", committed=1, check_status="pass",
                                      trip_date=D, file_name="m.jpg", service_type="Standard Bike",
                                      booking_code="D-M1", base_fare=70, net_earnings=70, distance_km=7.0,
                                      customer_image="WK33-ม่วง1.jpg"))
    b1 = crow(big, "C-B1", 71, "2026-09-21", "WK39-ใหญ่1.jpg")
    b2 = crow(big, "C-B2", 72, "2026-09-22", "WK39-ใหญ่2.jpg")
    b3 = crow(big, "C-B3", 73, "2026-09-23", "WK39-ใหญ่3.jpg")
    b_rep = crow(big, "D-M1", 70, "2026-09-24", "WK39-ใหญ่4.jpg")        # the same slip D already has
    dup1 = crow(big, "C-DUP", 75, "2026-09-25", "WK39-ใหญ่5.jpg")       # W39 holds this code twice
    dup2 = crow(mid, "C-DUP", 75, "2026-09-25", "WK39-กลาง1.jpg")
    m2 = crow(mid, "C-M2", 76, "2026-09-26", "WK39-กลาง2.jpg")

taken = rw.take_from(C, {"2 W Standard"})
check("❗ โยก: รหัสที่ W39 มีสองแถวไม่โยก", not {dup1, dup2} & {r["id"] for r in taken})
check("❗ โยก: เริ่มจากไรเดอร์ที่มีงานมากที่สุด เที่ยวล่าสุดก่อน",
      [r["id"] for r in taken][:2] == [b_rep, b3] and taken[0]["from_week"] == C
      and taken[0]["note"].startswith("โยกจาก 2026-W39: ใหญ่/WK39-ใหญ่4.jpg"))
tp = rw.plan([D], taken)
tby = {p[0]["id"]: p for p in tp}
check("❗ โยก: แถวที่ซ้ำกับสัปดาห์ที่เติมไม่ลง และบอกว่าซ้ำ", tby[b_rep][1] is None and "ซ้ำ" in tby[b_rep][4])
check("❗ โยก: เติมเท่าที่ว่าง (2) แถวที่เหลืออยู่ W39 ตามเดิม ไม่อยู่ในรายการ",
      sum(1 for p in tp if p[1]) == 2 and tby[b3][1] == D and len(tp) == 3)
n = rw.apply(drive, str(root / "exports"), tp, log=lambda *_: None)
t = db.get_trip(b3)
check("❗ โยก: แถวไปอยู่กับม่วง วันที่ใน W33 ชื่อรูปใหม่ต่อเลขของม่วง",
      n == 2 and t["job_id"] == muang and D <= t["trip_date"] <= rw.week_end(D)
      and t["customer_image"] in {"WK33-ม่วง2.jpg", "WK33-ม่วง3.jpg"}
      and (root / "exports" / "2026-W33" / "2 W Standard" / t["customer_image"]).read_bytes() == "jpeg:WK39-ใหญ่3.jpg".encode())
check("❗ โยก: รูปที่ส่ง W39 ไปแล้วย้ายออกไป _โยกไปงานแก้ ไม่ค้างในกลุ่ม",
      not (cgrp / "WK39-ใหญ่3.jpg").exists()
      and (root / "exports" / "2026-W39" / rw.TAKEN_DIR / "WK39-ใหญ่3.jpg").exists()
      and (cgrp / "WK39-ใหญ่1.jpg").exists() and (cgrp / "WK39-ใหญ่4.jpg").exists())
check("โยก: โน้ตบอกที่มา", db.get_trip(b3)["note"].startswith("โยกจาก 2026-W39: ใหญ่/WK39-ใหญ่3.jpg"))
check("โยก: แถวที่ไม่ได้โยกยังอยู่ W39", all(db.get_trip(x)["job_id"] in (big, mid) for x in (b1, b_rep, dup1, dup2)))
rep = rw.repeats_between(C, [D])
check("❗ นับงานซ้ำข้ามสัปดาห์: เจอแถวที่รหัสตรงกับ W33 แถวเดียว และบอกว่าซ้ำกับสัปดาห์ไหน",
      [x[0]["id"] for x in rep] == [b_rep] and rep[0][1]["_week"] == "2026-W33" and rep[0][2] == "รหัสการจอง")
wbr = _ox.load_workbook(_io.BytesIO(rw.repeats_report(C, rep, 5, log=lambda *_: None)))
check("รายงานงานซ้ำ: ชีตสรุป/รายเที่ยว", wbr.sheetnames == ["สรุป", "รายเที่ยว"] and wbr["รายเที่ยว"].max_row == 2)

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
