# -*- coding: utf-8 -*-
"""อ่านก่อน แล้วค่อยลงที่ครั้งเดียว (เฟส 2, 2026-09-17).

รูปที่จับคู่แล้วรออยู่ที่ <Week>/_พร้อมอ่าน/ ไม่มีเจ้าของ พออ่านเสร็จจึงรู้ว่าเป็นงานประเภทไหน แล้วค่อย
ลงโฟลเดอร์ไรเดอร์ทีเดียว — ไม่ต้อง rehome ไม่ต้องแก้ป้าย ไม่ต้องยกทีหลัง
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-file-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from sqlalchemy import insert, select                            # noqa: E402

import db                                                        # noqa: E402
import file_after_read as far                                    # noqa: E402
from drive_client import LocalDrive                              # noqa: E402

db.init_db()
ok = True
JPEG = bytes([0xFF, 0xD8])


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


W, WE = "2026-09-07", "2026-09-13"
ROOT = os.path.join(WORK, "drive")
WEEK = os.path.join(ROOT, "Week 7-13 Sep")
HOLD = os.path.join(WEEK, far.HOLDING_DIR)
os.makedirs(HOLD)
drive = LocalDrive(ROOT)
db.name_pool_load([("สมชาย", "2W", "Win"), ("สมหญิง", "2W", "Home"),
                   ("สมหมาย", "4W", "Taxi"), ("ดวงใจ", "4W", "Home")])

hold_job = db.create_job(far.HOLDING_RIDER, "Trips", W, WE, category=None, drive_folder_id=HOLD)


def staged(name, svc, day="2026-09-08", status="done"):
    open(os.path.join(HOLD, name), "wb").write(JPEG)
    with db.engine.begin() as c:
        tid = c.execute(insert(db.trips).values(job_id=hold_job, file_name=name, status=status,
                                                service_type=svc, trip_date=day, net_earnings=50,
                                                base_fare=50)).inserted_primary_key[0]
        c.execute(insert(db.ingested_files).values(drive_id=os.path.join(HOLD, name), name=name,
                                                   job_id=hold_job, trip_id=tid,
                                                   ingested_at="2026-09-17"))
    return tid


t_bike = staged("a.jpg", "Standard Bike")
t_saver = staged("b.jpg", "Saver Bike", day="2026-09-07")
t_car = staged("c.jpg", "Standard Car")
t_savercar = staged("d.jpg", "Saver Car")          # รถยนต์มีกลุ่มเดียว
t_unknown = staged("e.jpg", None)                  # อ่านประเภทไม่ออก
staged("f.jpg", "Standard Bike", status="pending")  # ยังไม่ได้อ่าน ต้องไม่ถูกหยิบ

rows = far.staged_rows(W, WE)
check("หยิบเฉพาะแถวที่อ่านแล้ว", sorted(r["file_name"] for r in rows) == ["a.jpg", "b.jpg", "c.jpg", "d.jpg", "e.jpg"])
check("เรียงตามวันที่ขับ", rows[0]["file_name"] == "b.jpg")

res = far.file_rows(drive, WEEK, W, WE, log=lambda *a: None)
check("ลงที่ได้ 4 แถว (ที่เหลืออ่านประเภทไม่ออก)", res["filed"] == 4 and res["left"] == 1)
check("แยกกลุ่มตามประเภทงานบนสลิป",
      res["by_group"] == {"2 W Standard": 1, "2 W Saver": 1, "4 W Standard": 2})

with db.engine.begin() as c:
    now = {r["file_name"]: dict(r) for r in c.execute(
        select(db.trips.c.file_name, db.trips.c.job_id, db.trips.c.note)).mappings().all()}
jobs = {j["id"]: j for js in db.jobs_by_week().values() for j in js}
check("รถยนต์ Saver ลงกลุ่มรถยนต์กลุ่มเดียวที่มี",
      jobs[now["d.jpg"]["job_id"]]["category"] == "4 W Standard")
check("มอเตอร์ไซค์ Saver ไม่ไปปนกับ Standard",
      jobs[now["b.jpg"]["job_id"]]["category"] == "2 W Saver"
      and jobs[now["a.jpg"]["job_id"]]["category"] == "2 W Standard")
check("แถวที่อ่านประเภทไม่ออก ยังอยู่ที่เดิม รอรอบหน้า", now["e.jpg"]["job_id"] == hold_job)
check("โน้ตบอกว่าลงที่เพราะอะไร", now["a.jpg"]["note"].startswith("ลงที่หลังอ่าน: Standard Bike → 2 W Standard"))

moved = {f for _root, _dirs, files in os.walk(WEEK) if far.HOLDING_DIR not in _root
         for f in files}
check("รูปถูกย้ายออกจากที่พักไปอยู่กับไรเดอร์", moved == {"a.jpg", "b.jpg", "c.jpg", "d.jpg"}
      and sorted(os.listdir(HOLD)) == ["e.jpg", "f.jpg"])   # e = อ่านประเภทไม่ออก · f = ยังไม่ได้อ่าน
check("ไรเดอร์ที่ได้งานเป็นชื่อจากลิสต์ Ops",
      all(jobs[now[f]["job_id"]]["driver_name"].split()[0] in ("สมชาย", "สมหญิง", "สมหมาย", "ดวงใจ")
          for f in ("a.jpg", "b.jpg", "c.jpg", "d.jpg")))

# --- กลุ่มที่ครบเป้าแล้ว ไม่รับงานเพิ่ม -----------------------------------------------------------
t_more = staged("g.jpg", "Standard Bike")
res2 = far.file_rows(drive, WEEK, W, WE, target=1, log=lambda *a: None)
check("กลุ่มที่ครบเป้าแล้ว: ไม่ลงที่ให้ รอสัปดาห์หน้า", res2["filed"] == 0 and res2["left"] >= 1)
with db.engine.begin() as c:
    still = c.execute(select(db.trips.c.job_id).where(db.trips.c.id == t_more)).scalar()
check("แถวนั้นยังรออยู่ที่เดิม ไม่ถูกย้ายไปไหน", still == hold_job)

# --- รันซ้ำไม่ทำอะไรซ้ำ ---------------------------------------------------------------------------
res3 = far.file_rows(drive, WEEK, W, WE, log=lambda *a: None)
check("รันซ้ำ: แถวที่ลงที่ไปแล้วไม่ถูกหยิบมาอีก", res3["filed"] == 1 and res3["by_group"] == {"2 W Standard": 1})

# --- รอบมองเห็นที่พักเป็นโฟลเดอร์ที่ต้องอ่าน ไม่ใช่ของบ้านเรือนที่ต้องข้าม ------------------------
import ingest                                                    # noqa: E402

os.makedirs(os.path.join(WEEK, "_ใช้แล้ว"), exist_ok=True)
open(os.path.join(HOLD, "h.jpg"), "wb").write(JPEG)
items, skipped = ingest.discover(drive, ROOT, closed=set())
hold_items = [i for i in items if i["rider"] == far.HOLDING_RIDER]
check("รอบหยิบรูปในที่พักมาอ่าน", {i["file"]["name"] for i in hold_items} >= {"e.jpg", "f.jpg", "h.jpg"})
check("รูปในที่พักยังไม่มีกลุ่มรถ (ตัดสินหลังอ่าน)", all(i["category"] is None for i in hold_items))
check("โฟลเดอร์บ้านเรือนอื่น ๆ ยังถูกข้ามเงียบ ๆ", not any("_ใช้แล้ว" in m for m in skipped))

# --- ห้องพักต้องไม่โผล่ให้คนเห็นว่าเป็นกลุ่มงานหรือคิวตรวจ (2026-09-17) ---------------------------
staged("q.jpg", "Standard Bike")            # อ่านแล้ว รอลงที่ ไม่ใช่ของที่คนต้องตรวจ
check("คิวตรวจไม่มีแถวของห้องพัก",
      all(r["file_name"] != "q.jpg" for r in db.review_queue()))
weeks = {w["week"]: w for w in db.weeks_overview()}
groups = [g["category"] for w in weeks.values() for g in w["groups"]]
check("แดชบอร์ดไม่ขึ้นกลุ่มของห้องพัก", "อัปโหลดมือ" not in groups and None not in groups)

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
