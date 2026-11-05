# -*- coding: utf-8 -*-
"""prepare_week: makes Week/Pool/2W·4W and the three groups, reuses what Ops already made
(however spelled), and is safe to run twice."""
import io
import os
import sys
import tempfile
from contextlib import redirect_stdout

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-prep-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import ingest                                                   # noqa: E402
import prepare_week as pw                                       # noqa: E402
from drive_client import LocalDrive                             # noqa: E402

ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


inbox = os.path.join(WORK, "Inbox")
os.makedirs(inbox)
drive = LocalDrive(inbox)
quiet = lambda *a: None                                         # noqa: E731

check("ชื่อสัปดาห์เดือนเดียวกัน", pw.week_name("2026-11-09") == "Week 9-15 Nov")
check("ชื่อสัปดาห์ข้ามเดือน", pw.week_name("2026-11-30") == "Week 30 Nov-6 Dec")
check("ชื่อที่สร้างอ่านกลับเป็นสัปดาห์เดิม",
      ingest.week_label(ingest.parse_range(pw.week_name("2026-11-30"))[0].isoformat()) == "2026-W49")

r = pw.prepare(drive, inbox, "2026-11-09", log=quiet)
week = os.path.join(inbox, "Week 9-15 Nov")
check("สร้างโฟลเดอร์สัปดาห์", os.path.isdir(week))
check("สร้าง Pool/2W และ Pool/4W", all(os.path.isdir(os.path.join(week, "Pool", g)) for g in ("2W", "4W")))
check("สร้างสามกลุ่ม ไม่มี 4 W Saver",
      sorted(n for n in os.listdir(week) if n != "Pool") == ["2 W Saver", "2 W Standard", "4 W Standard"])
check("รอบแรกสร้างใหม่ 7 โฟลเดอร์", len(r["made"]) == 7, r["made"])

r2 = pw.prepare(drive, inbox, "2026-11-09", log=quiet)
check("รันซ้ำ: ไม่สร้างอะไรเพิ่ม", r2["made"] == [] and len(r2["kept"]) == 7, r2)

ops = os.path.join(inbox, "week 16 - 22 Nov")
os.makedirs(os.path.join(ops, "กอง", "2w"))
os.makedirs(os.path.join(ops, "2 w saver "))
r3 = pw.prepare(drive, inbox, "2026-11-16", log=quiet)
check("ใช้โฟลเดอร์ที่ Ops สร้างเองแม้สะกดต่าง ไม่สร้างสัปดาห์ซ้ำ",
      not os.path.isdir(os.path.join(inbox, "Week 16-22 Nov")) and r3["week"] == "week 16 - 22 Nov", r3["week"])
check("ใช้ 'กอง' และ '2w' ที่มีอยู่ สร้างเฉพาะที่ขาด",
      sorted(os.listdir(os.path.join(ops, "กอง"))) == ["2w", "4W"]
      and not os.path.isdir(os.path.join(ops, "Pool")), os.listdir(ops))
groups = sorted(n for n in os.listdir(ops) if n != "กอง")
check("กลุ่มที่ Ops สะกดตัวเล็กถือว่ามีแล้ว ไม่สร้างซ้ำ",
      len(groups) == 3 and sum(1 for n in groups if n.lower().strip() == "2 w saver") == 1, groups)

try:
    with redirect_stdout(io.StringIO()):
        pw.prepare(drive, inbox, "2026-11-10", log=quiet)
    check("ไม่ใช่วันจันทร์: ปฏิเสธ", False)
except ValueError:
    check("ไม่ใช่วันจันทร์: ปฏิเสธ", True)

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
