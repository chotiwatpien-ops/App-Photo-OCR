# -*- coding: utf-8 -*-
"""A row's stitched picture ends up in the folder of the job that holds the row; a name found
in two places is never moved on a guess (2026-09-10).

Local folders stand in for Drive and a throwaway SQLite for the database. A rider was rehomed
from 2 W Standard to 2 W Saver; her pictures still sit in the Standard folder under the names
Ops uploaded, and the old job carries no drive_folder_id.
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-recon-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from sqlalchemy import insert                                    # noqa: E402

import db                                                        # noqa: E402
import reconcile_pictures as rp                                  # noqa: E402
from drive_client import LocalDrive                              # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


D_FROM, D_TO = "2026-08-31", "2026-09-06"
ROOT = os.path.join(WORK, "drive")
WEEK = os.path.join(ROOT, "Week 31 Aug-6 Sep")
std = os.path.join(WEEK, "2 W Standard", "07-มนันตรา Win")
saver = os.path.join(WEEK, "2 W Saver", "105-มนันตรา Win")
other = os.path.join(WEEK, "2 W Standard", "08-คนอื่น Win")
os.makedirs(std); os.makedirs(saver); os.makedirs(other)
os.makedirs(os.path.join(WEEK, "4 W Standard"))
for n in ("LINE_1.jpg", "LINE_2.jpg", "168711_168712.jpg", "dup_0+0.jpg"):
    open(os.path.join(std, n), "wb").write(b"\xff\xd8" + n.encode())
open(os.path.join(other, "dup_0+0.jpg"), "wb").write(b"\xff\xd8other")     # same name elsewhere
open(os.path.join(saver, "already.jpg"), "wb").write(b"\xff\xd8ok")

drive = LocalDrive(ROOT)
# the Saver job holds four rows whose pictures are still in the Standard folder; the old job has
# no folder id (older layout); one row's picture is nowhere; one row's name exists twice
j_saver = db.create_job("มนันตรา Win", "Trips", D_FROM, D_TO, category="2 W Saver", drive_folder_id=saver)
j_old = db.create_job("มนันตรา Win", "Trips", D_FROM, D_TO, category="2 W Standard", drive_folder_id=None)
j_nofolder = db.create_job("ใหม่ Home", "Trips", D_FROM, D_TO, category="4 W Standard", drive_folder_id=None)
with db.engine.begin() as c:
    for n in ("LINE_1.jpg", "LINE_2.jpg", "168711_168712.jpg", "dup_0+0.jpg", "already.jpg", "gone.jpg"):
        c.execute(insert(db.trips).values(job_id=j_saver, file_name=n, status="done", committed=1, service_type="Saver Bike"))
    c.execute(insert(db.trips).values(job_id=j_old, file_name="x.jpg", status="voided", committed=0))

wk = rp.Week(drive, WEEK)
check("ดัชนีอ่านครบทุกโฟลเดอร์ไรเดอร์", len(wk.folders) == 3 and sum(len(v) for v in wk.by_name.values()) == 6)
moves, ambiguous, missing, need_folder, _jobs = rp.plan(wk, D_FROM, D_TO)
check("ย้ายได้แน่นอน 3 ใบ (LINE_1, LINE_2, 168711)", sorted(r["file_name"] for r, *_ in moves) == ["168711_168712.jpg", "LINE_1.jpg", "LINE_2.jpg"])
check("ชื่อซ้ำสองที่ ไม่ย้าย", [r["file_name"] for r, _j, _h in ambiguous] == ["dup_0+0.jpg"])
check("หาไม่เจอ 1 ใบ", [r["file_name"] for r, _j in missing] == ["gone.jpg"])
check("ใบที่อยู่ถูกที่แล้วไม่ถูกแตะ", all(r["file_name"] != "already.jpg" for r, *_ in moves))
check("แถวที่ไม่ใช่ done ไม่ถูกนับ", all(r["file_name"] != "x.jpg" for r, *_ in moves + [(m[0],) for m in missing]))

done = rp.apply(wk, moves, _jobs, log=lambda *a: None)
check("ย้าย 3 ใบ", done["ย้ายรูป"] == 3)
check("ทั้งสามอยู่โฟลเดอร์ Saver แล้ว", sorted(os.listdir(saver)) == ["168711_168712.jpg", "LINE_1.jpg", "LINE_2.jpg", "already.jpg"])
check("โฟลเดอร์ Standard เหลือแค่ชื่อซ้ำที่ไม่กล้าย้าย", os.listdir(std) == ["dup_0+0.jpg"])
check("ไฟล์ชื่อซ้ำของคนอื่นไม่ถูกแตะ", os.listdir(other) == ["dup_0+0.jpg"])

# a job with no folder at all gets one when it has a picture to receive
open(os.path.join(std, "car.jpg"), "wb").write(b"\xff\xd8car")
with db.engine.begin() as c:
    c.execute(insert(db.trips).values(job_id=j_nofolder, file_name="car.jpg", status="done", committed=1, service_type="Standard Car"))
wk2 = rp.Week(drive, WEEK)
moves2, _a, _m, need2, jobs2 = rp.plan(wk2, D_FROM, D_TO)
check("job ที่ไม่มีโฟลเดอร์ถูกชี้ว่าต้องเปิด", need2 == {j_nofolder})
rp.apply(wk2, moves2, jobs2, log=lambda *a: None)
check("เปิดโฟลเดอร์ 01-ใหม่ Home ใน 4 W Standard แล้วย้ายรูปเข้าไป",
      os.listdir(os.path.join(WEEK, "4 W Standard", "01-ใหม่ Home")) == ["car.jpg"])

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
