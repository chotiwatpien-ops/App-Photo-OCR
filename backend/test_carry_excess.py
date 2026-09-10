# -*- coding: utf-8 -*-
"""Rows above a group's target go to next week, latest trip first, dates untouched (2026-09-10).

Local folders stand in for Drive and a throwaway SQLite for the database. 2 W Saver holds five
finished rows against a target of three; 2 W Standard holds two and is left alone.
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-carry-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from sqlalchemy import insert, select                            # noqa: E402

import carry_excess as ce                                        # noqa: E402
import db                                                        # noqa: E402
from drive_client import LocalDrive                              # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


D_FROM, D_TO = "2026-08-31", "2026-09-06"
N_FROM, N_TO = "2026-09-07", "2026-09-13"
check("ชื่อโฟลเดอร์สัปดาห์หน้าสะกดแบบ Ops: เดือนเดียวเขียนครั้งเดียว",
      ce.next_week_folder("Week 31 Aug-6 Sep", "2026-08-31", "2026-09-06") == "Week 7-13 Sep")
check("ข้ามเดือนเขียนสองครั้ง",
      ce.next_week_folder("Week 21-27 Sep", "2026-09-21", "2026-09-27") == "Week 28 Sep-4 Oct")
check("ไม่พึ่ง pool (runner ของ Carry ไม่มี OCR)", "from pool" not in open("backend/carry_excess.py", encoding="utf-8").read())
check("สัปดาห์ถัดไปคำนวณจากวันที่", ce.next_week(D_FROM, D_TO) == (N_FROM, N_TO))

ROOT = os.path.join(WORK, "drive")
THIS, NEXT = "Week 31 Aug-6 Sep", "Week 7-13 Sep"
saver_rider = os.path.join(ROOT, THIS, "2 W Saver", "05-สมชาย Win")
std_rider = os.path.join(ROOT, THIS, "2 W Standard", "02-สมชาย Win")
exp = os.path.join(ROOT, "Export Pic", "2026-W36")
os.makedirs(saver_rider); os.makedirs(std_rider)
os.makedirs(os.path.join(ROOT, NEXT, "2 W Saver", "01-คนอื่น Home"))   # next week already has a rider
os.makedirs(os.path.join(exp, "2 W Saver")); os.makedirs(os.path.join(exp, "2 W Standard"))

drive = LocalDrive(ROOT)
j_saver = db.create_job("สมชาย Win", "Trips", D_FROM, D_TO, category="2 W Saver", drive_folder_id=saver_rider)
j_std = db.create_job("สมชาย Win", "Trips", D_FROM, D_TO, category="2 W Standard", drive_folder_id=std_rider)
with db.engine.begin() as c:
    for n, d, tm in ((1, "2026-09-01", "08:00"), (2, "2026-09-06", "09:00"), (3, "2026-09-03", "10:00"),
                     (4, "2026-09-06", "07:00"), (5, "2026-09-05", "22:00")):
        open(os.path.join(saver_rider, f"s{n}.jpg"), "wb").write(b"\xff\xd8s%d" % n)
        open(os.path.join(exp, "2 W Saver", f"WK36-สมชาย Win{n}.jpg"), "wb").write(b"\xff\xd8c%d" % n)
        c.execute(insert(db.trips).values(job_id=j_saver, file_name=f"s{n}.jpg", status="done",
                                          service_type="Saver Bike", trip_date=d, trip_time=tm,
                                          customer_image=f"WK36-สมชาย Win{n}.jpg", committed=1, net_earnings=10 * n))
    for n in (1, 2):
        open(os.path.join(std_rider, f"t{n}.jpg"), "wb").write(b"\xff\xd8t%d" % n)
        c.execute(insert(db.trips).values(job_id=j_std, file_name=f"t{n}.jpg", status="done",
                                          service_type="Standard Bike", trip_date="2026-09-06", committed=1))

# --- which rows are excess ----------------------------------------------------------------------------
excess, counts, _ = ce.excess_rows(D_FROM, D_TO, target=3)
check("นับได้ Saver 5 · Standard 2", (counts["2 W Saver"], counts["2 W Standard"]) == (5, 2))
check("เกินเฉพาะ Saver 2 แถว · Standard ไม่แตะ", list(excess) == ["2 W Saver"] and len(excess["2 W Saver"]) == 2)
picked = [r["file_name"] for r, _j in excess["2 W Saver"]]
check("เลือกวันล่าสุดก่อน: 6 ก.ย. 09:00 แล้ว 6 ก.ย. 07:00 (ไม่ใช่ 5 ก.ย.)", picked == ["s2.jpg", "s4.jpg"])

# --- carry them ------------------------------------------------------------------------------------------
wk = ce.Weeks(drive, ROOT, THIS, NEXT, exp)
done = ce.apply(drive, wk, D_FROM, D_TO, excess, log=lambda *a: None)
check("ย้ายแถว 2 · รูปรวมร่าง 2 · เก็บรูปลูกค้าเดิม 2",
      (done["ย้ายแถว"], done["ย้ายรูปรวมร่าง"], done["เก็บรูปลูกค้าเดิมออก"]) == (2, 2, 2))
nxt_dir = os.path.join(ROOT, NEXT, "2 W Saver")
check("เปิดโฟลเดอร์ไรเดอร์ในสัปดาห์หน้าด้วยเลขถัดไป (02)", sorted(os.listdir(nxt_dir)) == ["01-คนอื่น Home", "02-สมชาย Win"])
check("รูปรวมร่าง 2 ใบอยู่สัปดาห์หน้า", sorted(os.listdir(os.path.join(nxt_dir, "02-สมชาย Win"))) == ["s2.jpg", "s4.jpg"])
check("โฟลเดอร์สัปดาห์นี้เหลือ 3 ใบ", sorted(os.listdir(saver_rider)) == ["s1.jpg", "s3.jpg", "s5.jpg"])
check("รูปลูกค้าของแถวที่ยกถูกเก็บเข้า _แทนที่แล้ว ไม่ได้ลบ",
      sorted(os.listdir(os.path.join(exp, "_แทนที่แล้ว"))) == ["WK36-สมชาย Win2.jpg", "WK36-สมชาย Win4.jpg"])
check("Export Pic สัปดาห์นี้เหลือ 3 ใบ", len(os.listdir(os.path.join(exp, "2 W Saver"))) == 3)

j_next = db.find_job("สมชาย Win", N_FROM, N_TO, category="2 W Saver")
check("มี job สัปดาห์หน้าของคนเดิม กลุ่มเดิม", bool(j_next))
with db.engine.begin() as c:
    rows = {r["file_name"]: dict(r) for r in c.execute(
        select(db.trips.c.file_name, db.trips.c.job_id, db.trips.c.trip_date, db.trips.c.customer_image,
               db.trips.c.note, db.trips.c.net_earnings)).mappings().all()}
check("แถวที่ยกอยู่ job สัปดาห์หน้า", rows["s2.jpg"]["job_id"] == j_next and rows["s4.jpg"]["job_id"] == j_next)
check("แถวที่เหลืออยู่ที่เดิม", all(rows[f]["job_id"] == j_saver for f in ("s1.jpg", "s3.jpg", "s5.jpg")))
check("วันที่บนสลิปไม่ถูกเปลี่ยน", rows["s2.jpg"]["trip_date"] == "2026-09-06")
check("ตัวเลขไม่ถูกแตะ", rows["s2.jpg"]["net_earnings"] == 20)
check("customer_image ถูกล้าง เพื่อให้สัปดาห์หน้าตั้งชื่อใหม่", rows["s2.jpg"]["customer_image"] is None
      and rows["s1.jpg"]["customer_image"] == "WK36-สมชาย Win1.jpg")
check("โน้ตบอกว่ายกไปทำไมและวันที่คงไว้",
      "ยกไปสัปดาห์ 2026-09-07..2026-09-13" in rows["s2.jpg"]["note"] and "คงไว้" in rows["s2.jpg"]["note"])

# --- now the group is at target: nothing more to carry ---------------------------------------------------
again, counts2, _ = ce.excess_rows(D_FROM, D_TO, target=3)
check("รันซ้ำ: Saver เหลือ 3 พอดี ไม่มีอะไรต้องยก", counts2["2 W Saver"] == 3 and again == {})

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
