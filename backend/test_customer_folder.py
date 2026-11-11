# -*- coding: utf-8 -*-
"""The customer's picture folder holds the pictures of the rows in the week's file, nothing else.

A picture is made when its slip is read, so a row still waiting for a person (W46: two repeats
in the review queue) had its picture beside the delivered ones. week_files.tidy moves such a
picture into _ไม่อยู่ในไฟล์ and brings it back once the row is approved (Fiat 2026-11-11)."""
import os
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-custfolder-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from sqlalchemy import insert, update                           # noqa: E402

import db                                                       # noqa: E402
import week_files                                               # noqa: E402
from drive_client import LocalDrive                             # noqa: E402

db.init_db()
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


W = ("2026-11-09", "2026-11-15")
job = db.create_job("สินธุ Win", "Trips", *W, category="2 W Saver")


def trip(name, committed):
    with db.engine.begin() as c:
        return c.execute(insert(db.trips).values(job_id=job, file_name=name, status="done", committed=committed,
                                                 trip_date="2026-11-11", customer_image=name)).inserted_primary_key[0]


a = trip("005111112620.jpg", 1)
b = trip("005111112619.jpg", 1)
waiting = trip("005111112621.jpg", 0)

root = Path(WORK) / "drive"
exports = root / "Exports"
saver = exports / "2026-W46" / "2 W Saver"
saver.mkdir(parents=True)
for n in ("005111112620.jpg", "005111112619.jpg", "005111112621.jpg"):
    (saver / n).write_bytes(b"jpg")
drive = LocalDrive(root)
here = lambda: sorted(p.name for p in saver.iterdir() if p.is_file())
held = lambda: sorted(p.name for p in (saver / week_files.OUT_DIR).iterdir()) if (saver / week_files.OUT_DIR).exists() else []

log = []
out, back = week_files.tidy(drive, str(exports), *W, log=log.append)
check("❗ รูปของแถวที่ยังรอคนตรวจ ย้ายออกจากโฟลเดอร์ลูกค้า", here() == ["005111112619.jpg", "005111112620.jpg"], here())
check("ย้ายไป _ไม่อยู่ในไฟล์ ไม่ได้ลบ", held() == ["005111112621.jpg"] and (out, back) == (1, 0), (held(), out, back))
check("ทำซ้ำได้: รอบถัดไปไม่ย้ายอะไรเพิ่ม", week_files.tidy(drive, str(exports), *W, log=log.append) == (0, 0))

with db.engine.begin() as c:
    c.execute(update(db.trips).where(db.trips.c.id == waiting).values(committed=1))
out, back = week_files.tidy(drive, str(exports), *W, log=log.append)
check("❗ อนุมัติแล้ว รูปย้ายกลับเข้าโฟลเดอร์ลูกค้าเอง", "005111112621.jpg" in here() and held() == [] and back == 1, (here(), held()))

with db.engine.begin() as c:
    c.execute(update(db.trips).where(db.trips.c.id == b).values(status="duplicate", committed=0))
week_files.tidy(drive, str(exports), *W, log=log.append)
check("แถวที่ถูกตัดว่าซ้ำทีหลัง รูปก็ย้ายออก", "005111112619.jpg" not in here() and held() == ["005111112619.jpg"])

other = exports / "2026-W46" / "2 W Standard"
other.mkdir()
for i in range(30):
    (other / f"x{i}.jpg").write_bytes(b"jpg")
log.clear()
week_files.tidy(drive, str(exports), *W, log=log.append)
check("❗ โฟลเดอร์ที่รูปส่วนใหญ่ไม่ตรงกับแถวเลย (ชื่อกลุ่มไม่ตรงกัน) ไม่ย้ายอะไร และเตือน",
      len(list(other.iterdir())) == 30 and any("ไม่ได้ย้าย" in m for m in log), log)

empty = ("2026-11-16", "2026-11-22")
db.create_job("สินธุ Win", "Trips", *empty, category="2 W Saver")
nxt = exports / "2026-W47" / "2 W Saver"
nxt.mkdir(parents=True)
(nxt / "a.jpg").write_bytes(b"jpg")
check("สัปดาห์ที่ยังไม่มีแถวอนุมัติ ไม่แตะโฟลเดอร์", week_files.tidy(drive, str(exports), *empty) == (0, 0)
      and (nxt / "a.jpg").exists())

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
