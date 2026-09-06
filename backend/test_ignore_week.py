# -*- coding: utf-8 -*-
"""A sandbox week (config.IGNORE_WEEKS) must be invisible to a round — neither its pool nor its
rider folders — while staying reachable when someone names it outright."""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-ignore-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

SAMPLE = "Phase2/Test 7"
if not os.path.isdir(SAMPLE):
    print("ไม่มีตัวอย่าง Phase2/Test 7 — ข้าม")
    sys.exit(0)

import config                                                   # noqa: E402
import db                                                       # noqa: E402
import ingest                                                   # noqa: E402
import pool                                                     # noqa: E402
from drive_client import LocalDrive                             # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


check("ชื่อสัปดาห์ปกติไม่ถูกข้าม", not config.week_ignored("Week 7-13 Sep"))
check("ชื่อที่มีคำว่า Test ถูกข้าม", config.week_ignored("Week xx-xx SEP Test"))
check("ชื่อไทย 'ทดสอบ' ถูกข้าม", config.week_ignored("Week 1-7 Sep ทดสอบ"))

root = os.path.join(WORK, "Inbox")
files = sorted(os.listdir(SAMPLE), key=lambda f: int(f.rsplit("_", 1)[1].split(".")[0]))[:4]
for week, rider_photos in (("Week xx-xx SEP Test", True), ("Week 7-13 Sep", False)):
    alb = os.path.join(root, week, "Pool", "LINE_ALBUM_Dl-boy4 w")
    os.makedirs(alb)
    for f in files:
        shutil.copy2(os.path.join(SAMPLE, f), os.path.join(alb, f))
    rider = os.path.join(root, week, "4 W Standard", "01 ทดสอบ")
    os.makedirs(rider)
    if rider_photos:                       # photos sitting in the sandbox week's rider folder
        for f in files[:2]:
            shutil.copy2(os.path.join(SAMPLE, f), os.path.join(rider, f))

# โฟลเดอร์เก็บของที่เครื่องมือเราสร้างเอง ต้องข้ามเงียบ ๆ ไม่ใช่เตือนซ้ำทุกรอบ
os.makedirs(os.path.join(root, "Week 7-13 Sep", "_ทิ้ง-จับคู่ผิด"))
os.makedirs(os.path.join(root, "Week 7-13 Sep", "ชื่อมั่ว"))

drive = LocalDrive(root)
items, skipped = ingest.discover(drive, root)
weeks_seen = {i["date_from"] for i in items}
check(f"ingest ไม่อ่านรูปในสัปดาห์ทดสอบ (เจอ {len(items)} รูป, ต้อง 0)", not items)
check("ไม่มีคำเตือนเรื่องสัปดาห์ทดสอบ", not any("Test" in s for s in skipped))
check("โฟลเดอร์ขึ้นต้นด้วย _ ถูกข้ามเงียบ ๆ", not any("_ทิ้ง" in s for s in skipped))
check("โฟลเดอร์แปลกปลอมจริงยังเตือนอยู่", any("ชื่อมั่ว" in s for s in skipped))

albums = pool.scan_inbox(drive, root)
check(f"จัดกองอัตโนมัติข้ามสัปดาห์ทดสอบ (เจอ {len(albums)} อัลบั้ม, ต้อง 1 = ของสัปดาห์จริง)",
      len(albums) == 1 and albums[0]["week"] == "Week 7-13 Sep")

named = pool.scan_inbox(drive, root, "Week xx-xx SEP Test")
check("ระบุชื่อสัปดาห์ทดสอบเองยังเข้าถึงได้", len(named) == 1 and named[0]["week"] == "Week xx-xx SEP Test")

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
