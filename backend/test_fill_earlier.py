# -*- coding: utf-8 -*-
"""An open week short in a group takes that group's work back from the later open weeks first.

W47 (2026-11-23): Standard Car stood at 368 of 1,470 while W48 had already filed 632 cars, because
the albums Ops dropped into W48's folder were filed into W48. Fiat: a later week gets work only
once the week before it is full, however long ago that week ended.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-fill-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from sqlalchemy import insert, select                             # noqa: E402

import config                                                     # noqa: E402
import db                                                         # noqa: E402
import file_after_read as far                                     # noqa: E402
import move_staged as ms                                          # noqa: E402
from drive_client import LocalDrive                               # noqa: E402

db.init_db()
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


def row(i, group, day="2026-11-24", staged=False):
    return {"id": i, "group": group, "trip_date": day, "trip_time": "", "staged": staged}


# --- the plan, on its own ----------------------------------------------------------------------
A, B, C = ("2026-11-09", "2026-11-15"), ("2026-11-16", "2026-11-22"), ("2026-11-23", "2026-11-29")
car, bike = "4 W Standard", "2 W Saver"
plan = ms.fill_plan([
    (B, {car: 1, bike: 3}, [], []),
    (C, {car: 3, bike: 1}, [row(1, car, staged=True)], [row(2, car), row(3, car), row(4, bike)]),
], target=3)
check("❗ สัปดาห์ก่อนขาดรถยนต์ 2: ดึงรถยนต์จากสัปดาห์หลัง 2 แถว", [r["id"] for r in plan[(B, C)]] == [1, 2],
      plan)
check("แถวที่ยังรอลงที่ถูกดึงก่อนแถวที่ลงแล้ว", plan[(B, C)][0]["id"] == 1)
check("❗ กลุ่มที่สัปดาห์ก่อนครบแล้วไม่ถูกดึง", all(r["group"] == car for r in plan[(B, C)]))

plan = ms.fill_plan([(B, {car: 3}, [], []), (C, {}, [], [row(2, car)])], target=3)
check("สัปดาห์ก่อนครบแล้ว: ไม่ขยับอะไร", plan == {}, plan)

plan = ms.fill_plan([(B, {car: 2}, [row(5, car, staged=True)], []), (C, {}, [], [row(2, car)])], target=3)
check("❗ แถวที่รอลงที่ในสัปดาห์ก่อนนับเป็นของสัปดาห์นั้นแล้ว ไม่ดึงเกิน", plan == {}, plan)

plan = ms.fill_plan([
    (A, {car: 2}, [], []),
    (B, {car: 3}, [], [row(6, car)]),
    (C, {car: 1}, [], [row(7, car)]),
], target=3)
check("❗ สามสัปดาห์: สัปดาห์แรกดึงจากสัปดาห์ถัดไป แล้วสัปดาห์นั้นเติมช่องที่เสียไปจากสัปดาห์หลังสุด",
      {k: [r["id"] for r in v] for k, v in plan.items()} == {(A, B): [6], (B, C): [7]}, plan)

# --- the real thing, on a Drive copy -----------------------------------------------------------
root = Path(WORK) / "drive"
inbox = root / "inbox"
w47, w48 = inbox / "Week 16-22 Nov", inbox / "Week 23-29 Nov"
for p in (w47 / "_พร้อมอ่าน", w48 / "_พร้อมอ่าน", w48 / "4 W Standard" / "สมหมาย Taxi",
          w48 / "2 W Saver" / "พัดชา Win"):
    p.mkdir(parents=True)
drive = LocalDrive(root)
config.DRIVE_EXPORTS_FOLDER_ID = str(inbox / "Export Pic")
exp48 = inbox / "Export Pic" / "2026-W48" / "4 W Standard"
exp48.mkdir(parents=True)

W47, W48 = B, C
TARGET = 3
j47_car = db.create_job("ชัย Taxi", "Trips", *W47, category=car)
j47_bike = db.create_job("ปลา Win", "Trips", *W47, category=bike)
db.create_job(far.HOLDING_RIDER, "Trips", *W47, drive_folder_id=str(w47 / "_พร้อมอ่าน"))
j48_hold = db.create_job(far.HOLDING_RIDER, "Trips", *W48, drive_folder_id=str(w48 / "_พร้อมอ่าน"))
j48_car = db.create_job("สมหมาย Taxi", "Trips", *W48, category=car,
                        drive_folder_id=str(w48 / "4 W Standard" / "สมหมาย Taxi"))
j48_bike = db.create_job("พัดชา Win", "Trips", *W48, category=bike,
                         drive_folder_id=str(w48 / "2 W Saver" / "พัดชา Win"))
ids = {}


def add(key, job, folder, svc, day, committed, customer=None):
    f = folder / f"{key}.jpg"
    f.write_bytes(key.encode())
    with db.engine.begin() as c:
        tid = c.execute(insert(db.trips).values(job_id=job, file_name=f.name, status="done", committed=committed,
                                                service_type=svc, trip_date=day,
                                                customer_image=customer)).inserted_primary_key[0]
        c.execute(insert(db.ingested_files).values(drive_id=str(f), name=f.name, job_id=job, trip_id=tid,
                                                   ingested_at="2026-11-23 00:00:00"))
    ids[key] = tid


with db.engine.begin() as c:
    c.execute(insert(db.trips).values(job_id=j47_car, file_name="old.jpg", status="done", committed=1,
                                      service_type="Standard Car", trip_date="2026-11-17"))
    for i in range(3):
        c.execute(insert(db.trips).values(job_id=j47_bike, file_name=f"b{i}.jpg", status="done", committed=1,
                                          service_type="Saver Bike", trip_date="2026-11-18"))
add("car_wait", j48_hold, w48 / "_พร้อมอ่าน", "Standard Car", "2026-11-25", 0)
add("car_filed1", j48_car, w48 / "4 W Standard" / "สมหมาย Taxi", "Standard Car", "2026-11-23", 1,
    customer="026323112601.jpg")
add("car_filed2", j48_car, w48 / "4 W Standard" / "สมหมาย Taxi", "Standard Car", "2026-11-24", 1)
add("bike_filed", j48_bike, w48 / "2 W Saver" / "พัดชา Win", "Saver Bike", "2026-11-24", 1)
(exp48 / "026323112601.jpg").write_bytes(b"c")

lines = []
changed = ms.fill_earlier(drive, str(inbox), [W48, W47], target=TARGET, log=lines.append)
with db.engine.begin() as c:
    got = {r["id"]: dict(r) for r in c.execute(select(db.trips)).mappings().all()}
hold47 = [j["id"] for j in db.jobs_by_week()[W47] if j["driver_name"] == far.HOLDING_RIDER][0]
check("❗ รถยนต์ W47 ขาด 2: แถวรอลงที่ + แถวที่ขับก่อนสุดของ W48 กลับมากองพัก W47",
      got[ids["car_wait"]]["job_id"] == hold47 and got[ids["car_filed1"]]["job_id"] == hold47,
      {k: got[ids[k]]["job_id"] for k in ids})
check("แถวรถยนต์ที่เกินที่ว่างอยู่ W48 ต่อ", got[ids["car_filed2"]]["job_id"] == j48_car)
check("❗ Saver ของ W47 ครบแล้ว: งาน Saver ของ W48 ไม่ถูกแตะ", got[ids["bike_filed"]]["job_id"] == j48_bike)
check("วันที่ของแถวที่ดึงกลับอยู่ใน W47",
      all(W47[0] <= got[ids[k]]["trip_date"] <= W47[1] for k in ("car_wait", "car_filed1")))
check("โน้ตบอกว่าทำไมแถวย้ายมา และวันที่บนสลิปเดิม",
      "ยังไม่ครบ" in got[ids["car_filed1"]]["note"] and "2026-11-23" in got[ids["car_filed1"]]["note"])
check("ชื่อรูปส่งลูกค้าของ W48 ถูกล้าง", got[ids["car_filed1"]]["customer_image"] is None)
check("❗ รูปส่งลูกค้าของ W48 ย้ายไป _แทนที่แล้ว ไม่ถูกลบ",
      not (exp48 / "026323112601.jpg").exists()
      and (inbox / "Export Pic" / "2026-W48" / "_แทนที่แล้ว" / "026323112601.jpg").exists())
check("รูปรวมร่างทั้งสองใบอยู่ในกองพัก W47",
      {"car_wait.jpg", "car_filed1.jpg"} <= {p.name for p in (w47 / "_พร้อมอ่าน").glob("*.jpg")})
check("ทั้งสองสัปดาห์ถูกบอกว่าเปลี่ยน (ไฟล์ลูกค้าเขียนใหม่)", changed == {W47, W48}, changed)
check("ตัวลงที่หลังอ่านของ W47 เห็นสองแถวนี้",
      {ids["car_wait"], ids["car_filed1"]} <= {r["id"] for r in far.staged_rows(*W47)})
check("ไม่มีแถวไหนถูกลบ", len(got) == 8, len(got))
check("log บอกว่าเติมสัปดาห์ไหน จากไหน", any("เติมสัปดาห์ 2026-11-16" in ln for ln in lines), lines)
check("❗ รันซ้ำ: W47 ไม่ขาดแล้ว ไม่ย้ายอะไรอีก", ms.fill_earlier(drive, str(inbox), [W47, W48], target=TARGET,
                                                             log=lambda *_: None) == set())
check("สัปดาห์เดียวที่เปิด: ไม่มีอะไรให้ดึง", ms.fill_earlier(drive, str(inbox), [W48], target=10,
                                                            log=lambda *_: None) == set())

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
