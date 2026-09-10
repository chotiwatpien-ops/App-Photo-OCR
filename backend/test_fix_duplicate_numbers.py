# -*- coding: utf-8 -*-
"""Rows sharing a customer picture name give the name up, latest first, and the shared file is
parked rather than deleted (2026-09-11).

Local folders stand in for Drive and a throwaway SQLite for the database.
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-dupnum-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from sqlalchemy import insert, select                            # noqa: E402

import db                                                        # noqa: E402
import fix_duplicate_numbers as fx                               # noqa: E402
from drive_client import LocalDrive                              # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


D_FROM, D_TO = "2026-09-07", "2026-09-13"
ROOT = os.path.join(WORK, "drive")
EXP = os.path.join(ROOT, "Export Pic", "2026-W37")
sav = os.path.join(EXP, "2 W Saver")
std = os.path.join(EXP, "2 W Standard")
os.makedirs(sav)
os.makedirs(std)
drive = LocalDrive(ROOT)

j_sav = db.create_job("ฤทัย Win", "Trips", D_FROM, D_TO, category="2 W Saver")
j_std = db.create_job("ฤทัย Win", "Trips", D_FROM, D_TO, category="2 W Standard")
j_ok = db.create_job("คนอื่น Home", "Trips", D_FROM, D_TO, category="2 W Saver")
with db.engine.begin() as c:
    # the same name on two rows, in two jobs of one rider — the collision this clears
    c.execute(insert(db.trips).values(job_id=j_sav, file_name="a.jpg", status="done", committed=1,
                                      trip_date="2026-09-08", customer_image="WK37-ฤทัย Win1.jpg"))
    c.execute(insert(db.trips).values(job_id=j_std, file_name="b.jpg", status="done", committed=1,
                                      trip_date="2026-09-10", customer_image="WK37-ฤทัย Win1.jpg"))
    # a name of its own, and a voided row that must not be counted
    c.execute(insert(db.trips).values(job_id=j_sav, file_name="c.jpg", status="done", committed=1,
                                      trip_date="2026-09-09", customer_image="WK37-ฤทัย Win2.jpg"))
    c.execute(insert(db.trips).values(job_id=j_ok, file_name="d.jpg", status="voided", committed=0,
                                      trip_date="2026-09-08", customer_image="WK37-ฤทัย Win1.jpg"))
open(os.path.join(sav, "WK37-ฤทัย Win1.jpg"), "wb").write(b"\xff\xd8one")
open(os.path.join(sav, "WK37-ฤทัย Win2.jpg"), "wb").write(b"\xff\xd8two")

dups, jobs = fx.duplicates(D_FROM, D_TO)
check("เจอชื่อซ้ำชื่อเดียว", [n for n, _rs in dups] == ["WK37-ฤทัย Win1.jpg"])
check("แถว voided ไม่ถูกนับ", len(dups[0][1]) == 2)
check("เรียงตามวันที่ แถวแรกคือ 8 ก.ย.", [r["trip_date"] for r in dups[0][1]] == ["2026-09-08", "2026-09-10"])

done = fx.apply(drive, EXP, dups, jobs, log=lambda *a: None)
check("ล้างชื่อแถวเดียว (แถวที่มาทีหลัง)", done["ล้างชื่อรูป"] == 1)
with db.engine.begin() as c:
    rows = {r["file_name"]: dict(r) for r in c.execute(
        select(db.trips.c.file_name, db.trips.c.customer_image, db.trips.c.note)).mappings().all()}
check("แถวแรกยังถือชื่อเดิม", rows["a.jpg"]["customer_image"] == "WK37-ฤทัย Win1.jpg")
check("แถวหลังถูกล้างชื่อ", rows["b.jpg"]["customer_image"] is None)
check("โน้ตบอกว่าซ้ำกับแถวไหน", "ชื่อรูปซ้ำกับแถว #" in (rows["b.jpg"]["note"] or ""))
check("แถวที่ชื่อไม่ซ้ำไม่ถูกแตะ", rows["c.jpg"]["customer_image"] == "WK37-ฤทัย Win2.jpg")
check("ไฟล์ชื่อซ้ำถูกเก็บเข้า _แทนที่แล้ว ไม่ได้ลบ",
      os.listdir(os.path.join(EXP, "_แทนที่แล้ว")) == ["WK37-ฤทัย Win1.jpg"])
check("ไฟล์ของแถวที่ไม่ซ้ำยังอยู่ที่เดิม", os.listdir(sav) == ["WK37-ฤทัย Win2.jpg"])

again, _ = fx.duplicates(D_FROM, D_TO)
check("รันซ้ำไม่มีอะไรเหลือให้ทำ", again == [])

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
