# -*- coding: utf-8 -*-
"""Closed weeks moved into Inbox/_Archive/ are neither read nor reported as a stray folder.

A top-level folder whose name starts with '_' is the tools' own, the same rule the round already
applies inside a week (_ใช้แล้ว, _รายงาน). Without it every round logged "'_Archive' ไม่ใช่สัปดาห์"."""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-archive-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import db                                                       # noqa: E402
import ingest                                                   # noqa: E402
from drive_client import LocalDrive                             # noqa: E402

db.init_db()
inbox = os.path.join(WORK, "Inbox")
for rel, name in (("_Archive/Week 7-13 Sep/2 W Saver/01 a", "old.jpg"),
                  ("Week 9-15 Nov/2 W Saver/01 b", "new.jpg")):
    os.makedirs(os.path.join(inbox, rel))
    open(os.path.join(inbox, rel, name), "wb").write(b"\xff\xd8")

items, warnings = ingest.discover(LocalDrive(inbox), inbox, closed=set())
names = [i["file"]["name"] for i in items]
ok = names == ["new.jpg"] and warnings == []
print(("✅" if names == ["new.jpg"] else "✗"), "อ่านเฉพาะสัปดาห์ปัจจุบัน ไม่อ่านใน _Archive", names)
print(("✅" if warnings == [] else "✗"), "ไม่มีคำเตือนเรื่องโฟลเดอร์ _Archive", warnings)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
