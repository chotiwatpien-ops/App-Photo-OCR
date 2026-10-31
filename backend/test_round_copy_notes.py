# -*- coding: utf-8 -*-
"""A round whose last job met a picture already read this week must still finish.

The round kept two lists under one name: the folder warnings it saves as the run's notes, and the
copies it skipped inside each job. The second overwrote the first, and the closing
"\\n".join(...) then met dicts: TypeError, the run stayed "running", and every scheduled round
after it waited behind that run.
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-copynotes-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import hashlib                                                  # noqa: E402
import config                                                   # noqa: E402
import db                                                       # noqa: E402
import ingest                                                   # noqa: E402
from drive_client import LocalDrive                             # noqa: E402

db.init_db()
config.INGEST_BATCH = False
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


inbox, exports = os.path.join(WORK, "Inbox"), os.path.join(WORK, "Exports")
rider_dir = os.path.join(inbox, "Week 24-30 Aug", "2 W Saver", "ทดสอบ")
os.makedirs(os.path.join(rider_dir, "ไม่ใช่วันที่"), exist_ok=True)
os.makedirs(exports, exist_ok=True)
picture = b"\xff\xd8\xff the same slip, uploaded again"
with open(os.path.join(rider_dir, "again.jpg"), "wb") as fh:
    fh.write(picture)

job = db.create_job("ทดสอบ", "Trips", "2026-08-24", "2026-08-30", category="2 W Saver")
db.create_trip(job, "first.jpg", None, "image/jpeg", image_hash=hashlib.sha1(picture).hexdigest())

drive = LocalDrive(inbox)
try:
    ingest.run(drive, inbox, exports, only="ทดสอบ")
    finished = True
except TypeError as e:
    print("   ", e)
    finished = False

last = db.list_ingest_runs(1)[0]
check("รอบที่เจอรูปซ้ำทั้งไฟล์ จบได้ ไม่ล้ม", finished)
check("รอบถูกปิดเป็นจบแล้ว ไม่ค้าง 'กำลังรัน'", last["finished_at"] is not None)
check("โน้ตของรอบยังเป็นคำเตือนเรื่องโฟลเดอร์", "ไม่ใช่วันที่" in (last["notes"] or ""))

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
