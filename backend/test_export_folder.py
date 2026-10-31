# -*- coding: utf-8 -*-
"""Every step finds the week's customer pictures where the pictures step wrote them.

The pictures step and the week audit use DRIVE_EXPORTS_FOLDER_ID. Rehome, carry, carry-back,
move-staged, fix-duplicate-numbers and set-aside looked for a folder named 'Export Pic' inside
the Inbox. With any other exports folder (the README tells a new customer to make 'Exports'),
rehome moved the row but left its picture in the old group, and the audit then blocked the lock
on every press (audit 2026-10-31). They now all go through ingest.export_week_folder.
"""
import os
import sys
import tempfile
from contextlib import redirect_stdout
import io

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-exportdir-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from sqlalchemy import insert                                    # noqa: E402

import config                                                    # noqa: E402
import db                                                        # noqa: E402
import ingest                                                    # noqa: E402
import rehome_by_service as rh                                   # noqa: E402
import roster                                                    # noqa: E402
from drive_client import LocalDrive                              # noqa: E402

db.init_db()
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


D_FROM, D_TO = "2026-08-31", "2026-09-06"
ROOT = os.path.join(WORK, "drive")
INBOX = os.path.join(ROOT, "Inbox")
EXPORTS = os.path.join(ROOT, "Exports")                          # beside the Inbox, not in it
WEEK = os.path.join(INBOX, "Week 31 Aug-6 Sep")
EXPORT_WEEK = os.path.join(EXPORTS, ingest.week_label(D_FROM))
rider = os.path.join(WEEK, "2 W Standard", "07-มนันตรา Win")
os.makedirs(rider)
os.makedirs(os.path.join(EXPORT_WEEK, "2 W Standard"))
open(os.path.join(rider, "pair_1.jpg"), "wb").write(b"\xff\xd8pair")
open(os.path.join(EXPORT_WEEK, "2 W Standard", "WK36-มนันตรา Win1.jpg"), "wb").write(b"\xff\xd8cust")

drive = LocalDrive(ROOT)
config.DRIVE_INBOX_FOLDER_ID, config.DRIVE_EXPORTS_FOLDER_ID = INBOX, EXPORTS
roster._drive = lambda: drive

check("หาโฟลเดอร์รูปของสัปดาห์จาก DRIVE_EXPORTS_FOLDER_ID", ingest.export_week_folder(drive, D_FROM) == EXPORT_WEEK)
check("สัปดาห์ที่ยังไม่มีรูป: ไม่มีโฟลเดอร์", ingest.export_week_folder(drive, "2026-09-07") is None)

job = db.create_job("มนันตรา Win", "Trips", D_FROM, D_TO, category="2 W Standard",
                    folder_name="2 W Standard/มนันตรา Win", drive_folder_id=rider)
with db.engine.begin() as c:
    c.execute(insert(db.trips).values(job_id=job, file_name="pair_1.jpg", status="done",
                                      service_type="Saver Bike", customer_image="WK36-มนันตรา Win1.jpg",
                                      committed=1))

with redirect_stdout(io.StringIO()):
    rh.main(["--from", D_FROM, "--to", D_TO, "--week", "Week 31 Aug-6 Sep", "--apply"])
moved = os.path.join(EXPORT_WEEK, "2 W Saver")
check("รูปส่งลูกค้าย้ายตามแถวไปกลุ่มใหม่ในโฟลเดอร์ Exports",
      os.path.isdir(moved) and os.listdir(moved) == ["WK36-มนันตรา Win1.jpg"],
      os.listdir(EXPORT_WEEK))
check("ไม่มีรูปค้างในกลุ่มเดิม", os.listdir(os.path.join(EXPORT_WEEK, "2 W Standard")) == [])

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
