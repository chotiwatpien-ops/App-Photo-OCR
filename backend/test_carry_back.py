# -*- coding: utf-8 -*-
"""Carried rows come back when the group, counted by Service Type, falls short (2026-09-16).

Local folders stand in for Drive and a throwaway SQLite for the database. 2 W Saver holds five
Saver Bike rows against a target of three; two are carried. Then one of the three left turns out
to be a Standard Bike trip and is rehomed away, so Saver Bike stands at two and one carried row
has to come back — the one with the earliest slip, to the job it left, with its picture and date.
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-carryback-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from sqlalchemy import insert, select                            # noqa: E402

import carry_back as cb                                          # noqa: E402
import carry_excess as ce                                        # noqa: E402
import db                                                        # noqa: E402
from drive_client import LocalDrive                              # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


D_FROM, D_TO = "2026-09-07", "2026-09-13"
N_FROM, N_TO = "2026-09-14", "2026-09-20"
ROOT = os.path.join(WORK, "drive")
THIS, NEXT = "Week 7-13 Sep", "Week 14-20 Sep"
saver_rider = os.path.join(ROOT, THIS, "2 W Saver", "05-สมชาย Win")
exp37 = os.path.join(ROOT, "Export Pic", "2026-W37")
exp38 = os.path.join(ROOT, "Export Pic", "2026-W38")
os.makedirs(saver_rider)
os.makedirs(os.path.join(exp37, "2 W Saver")); os.makedirs(os.path.join(exp38, "2 W Saver"))
drive = LocalDrive(ROOT)

j_saver = db.create_job("สมชาย Win", "Trips", D_FROM, D_TO, category="2 W Saver", drive_folder_id=saver_rider)
with db.engine.begin() as c:
    for n, d, tm in ((1, "2026-09-08", "08:00"), (2, "2026-09-13", "09:00"), (3, "2026-09-10", "10:00"),
                     (4, "2026-09-13", "07:00"), (5, "2026-09-12", "22:00")):
        open(os.path.join(saver_rider, f"s{n}.jpg"), "wb").write(b"\xff\xd8s%d" % n)
        open(os.path.join(exp37, "2 W Saver", f"WK37-สมชาย Win{n}.jpg"), "wb").write(b"\xff\xd8c%d" % n)
        c.execute(insert(db.trips).values(job_id=j_saver, file_name=f"s{n}.jpg", status="done",
                                          service_type="Saver Bike", trip_date=d, trip_time=tm,
                                          customer_image=f"WK37-สมชาย Win{n}.jpg", committed=1, net_earnings=10 * n))

# --- carry two (s2, s4 — both 13 Sep) ----------------------------------------------------------
excess, _counts, _ = ce.excess_rows(D_FROM, D_TO, target=3)
ce.apply(drive, ce.Weeks(drive, ROOT, THIS, NEXT, exp37), D_FROM, D_TO, excess, log=lambda *a: None)
j_next = db.find_job("สมชาย Win", N_FROM, N_TO, category="2 W Saver")
next_rider = os.path.join(ROOT, NEXT, "2 W Saver", "01-สมชาย Win")
check("เตรียม: ยกไปสัปดาห์หน้า 2 แถว", sorted(os.listdir(next_rider)) == ["s2.jpg", "s4.jpg"])

# next week's export has already named the carried rows, and next week has a row of its own
with db.engine.begin() as c:
    for fn, ci in (("s2.jpg", "WK38-สมชาย Win2.jpg"), ("s4.jpg", "WK38-สมชาย Win1.jpg")):
        c.execute(db.trips.update().where(db.trips.c.file_name == fn).values(customer_image=ci))
        open(os.path.join(exp38, "2 W Saver", ci), "wb").write(b"\xff\xd8x")
    open(os.path.join(next_rider, "own.jpg"), "wb").write(b"\xff\xd8o")
    c.execute(insert(db.trips).values(job_id=j_next, file_name="own.jpg", status="done", service_type="Saver Bike",
                                      trip_date="2026-09-14", trip_time="06:00", committed=1))

# --- the audit finds s3 is a Standard Bike trip; the count by service drops to two -------------
with db.engine.begin() as c:
    c.execute(db.trips.update().where(db.trips.c.file_name == "s3.jpg").values(service_type="Standard Bike"))
check("นับตาม Service Type: Saver Bike เหลือ 2 · Standard Bike 1",
      (cb.count_by_service(D_FROM, D_TO)["Saver Bike"], cb.count_by_service(D_FROM, D_TO)["Standard Bike"]) == (2, 1))

pool = cb.candidates(D_FROM, D_TO, "2 W Saver")
check("ดึงกลับได้เฉพาะแถวที่ยกไปจากสัปดาห์นี้ (แถวของสัปดาห์หน้าเองไม่นับ)",
      sorted(r["file_name"] for r, _j in pool) == ["s2.jpg", "s4.jpg"])
check("เรียงตามวันบนสลิปแล้วเวลา: 13 ก.ย. 07:00 ก่อน 09:00", [r["file_name"] for r, _j in pool] == ["s4.jpg", "s2.jpg"])

with db.engine.begin() as c:
    c.execute(db.trips.update().where(db.trips.c.file_name == "s2.jpg").values(service_type="Standard Bike"))
check("แถวที่ยกไปแต่ Service Type ไม่ใช่ของกลุ่มแล้ว ไม่ถูกดึงกลับ",
      [r["file_name"] for r, _j in cb.candidates(D_FROM, D_TO, "2 W Saver")] == ["s4.jpg"])
with db.engine.begin() as c:
    c.execute(db.trips.update().where(db.trips.c.file_name == "s2.jpg").values(service_type="Saver Bike"))

# --- bring one back ------------------------------------------------------------------------------
picked = cb.candidates(D_FROM, D_TO, "2 W Saver")[:1]
done = cb.apply(drive, os.path.join(ROOT, THIS), exp38, D_FROM, D_TO, "2 W Saver", picked, log=lambda *a: None)
check("ดึงกลับ 1 แถว · รูปรวมร่าง 1 · รูปลูกค้าสัปดาห์หน้า 1",
      (done["ดึงแถวกลับ"], done["ย้ายรูปรวมร่างกลับ"], done["เก็บรูปลูกค้าสัปดาห์หน้าออก"]) == (1, 1, 1))
check("รูปรวมร่างกลับเข้าโฟลเดอร์เดิมของสัปดาห์นี้", "s4.jpg" in os.listdir(saver_rider)
      and sorted(os.listdir(next_rider)) == ["own.jpg", "s2.jpg"])
check("รูปลูกค้าที่สัปดาห์หน้าตั้งชื่อไว้ถูกเก็บเข้า _แทนที่แล้ว ไม่ได้ลบ",
      os.listdir(os.path.join(exp38, "_แทนที่แล้ว")) == ["WK38-สมชาย Win1.jpg"])

with db.engine.begin() as c:
    rows = {r["file_name"]: dict(r) for r in c.execute(
        select(db.trips.c.file_name, db.trips.c.job_id, db.trips.c.trip_date, db.trips.c.customer_image,
               db.trips.c.note, db.trips.c.net_earnings)).mappings().all()}
check("แถวกลับเข้า job เดิมที่ยกออกไป (ไม่เปิด job ใหม่)", rows["s4.jpg"]["job_id"] == j_saver
      and len(db.jobs_by_week()[(D_FROM, D_TO)]) == 1)
check("วันที่กลับเป็นวันบนสลิป", rows["s4.jpg"]["trip_date"] == "2026-09-13")
check("customer_image ถูกล้าง ให้สัปดาห์นี้ตั้งชื่อใหม่", rows["s4.jpg"]["customer_image"] is None)
check("โน้ตบอกว่าดึงกลับเพราะอะไร และไม่เหลือโน้ตการยกกับวันที่ที่ลงใหม่",
      rows["s4.jpg"]["note"].startswith("ดึงกลับจากสัปดาห์ 2026-09-14..2026-09-20 เพราะ 2 W Saver")
      and "ยกไปสัปดาห์" not in rows["s4.jpg"]["note"] and "วันที่บนสลิป" not in rows["s4.jpg"]["note"])
check("ตัวเลขไม่ถูกแตะ", rows["s4.jpg"]["net_earnings"] == 40)
check("แถวที่ไม่ถูกดึงยังอยู่สัปดาห์หน้า", rows["s2.jpg"]["job_id"] == j_next and rows["own.jpg"]["job_id"] == j_next)
check("Saver Bike กลับมาเป็น 3 ตามเป้า", cb.count_by_service(D_FROM, D_TO)["Saver Bike"] == 3)

# --- the job it left is gone: a job for the same rider is made in this week's group -------------
with db.engine.begin() as c:
    c.execute(db.trips.update().where(db.trips.c.file_name == "s2.jpg")
              .values(note="ยกไปสัปดาห์ 2026-09-14..2026-09-20 เพราะ 2 W Saver เกินเป้า (เดิม job #99999)"))
done = cb.apply(drive, os.path.join(ROOT, THIS), exp38, D_FROM, D_TO, "2 W Saver",
                cb.candidates(D_FROM, D_TO, "2 W Saver")[:1], log=lambda *a: None)
with db.engine.begin() as c:
    back = c.execute(select(db.trips.c.job_id).where(db.trips.c.file_name == "s2.jpg")).scalar()
check("job เดิมไม่มีแล้ว: กลับเข้า job ของคนเดิมในกลุ่มเดิมของสัปดาห์นี้", back == j_saver)

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
