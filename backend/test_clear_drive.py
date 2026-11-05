# -*- coding: utf-8 -*-
"""clear_drive picks only the system account's files, of the agreed kinds, in the named closed
weeks; an Exports week folder that is wholly the system's goes as one folder."""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-clear-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import clear_drive as cd                                        # noqa: E402
import drive_usage as du                                        # noqa: E402

ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


def f(i, mine, b=1):
    return {"id": i, "name": i, "folder": False, "bytes": b, "mine": mine}


inbox = [
    (("Week 7-13 Sep", "2 W Saver", "01 สมชาย"), f("pair", True, 5)),        # W37 stitched pair
    (("Week 7-13 Sep", "2 W Saver", "01 สมชาย"), f("ops-orig", False, 3)),   # Ops' upload: never
    (("Week 7-13 Sep", "Pool", "_ใช้แล้ว", "2W A"), f("used-mine", True)),
    (("Week 7-13 Sep", "Pool", "_ใช้แล้ว", "2W A"), f("used-ops", False)),
    (("Week 7-13 Sep", "_ซ้ำ"), f("dup", True)),
    (("Week 7-13 Sep", "_ทิ้ง-กดลบ"), f("person-deleted", True)),          # kept: training material
    (("Week 7-13 Sep", "_พร้อมอ่าน"), f("staged", True)),                  # kept: decision pending
    (("Week 7-13 Sep", "Pool", "_รายงาน"), f("report", True)),             # kept
    (("Week 28 Sep-4 Oct", "2 W Saver", "01 x"), f("w40-pair", True)),      # W40 not in weeks
]
exports = [
    (("2026-W37", "2 W Saver"), f("cust", True, 2)),
    (("2026-W37", "_แทนที่แล้ว"), f("replaced", True)),
    (("2026-W38", "2 W Saver"), f("cust38", True)),
    (("2026-W38", "2 W Saver"), f("someone-elses", False)),                 # folder not wholly ours
    ((), f("Rider Trips.xlsx", True)),
]
files, whole, picked = cd.plan(inbox, exports, {"2026-W37", "2026-W38"})
ids = {x[2] for x in files}
picked_ids = {e["id"] for *_r, e in picked}

check("รูปคู่ของบัญชีระบบในโฟลเดอร์ไรเดอร์ถูกเลือก", "pair" in ids)
check("ต้นฉบับของ Ops ไม่ถูกแตะ", "ops-orig" not in picked_ids and "used-ops" not in picked_ids)
check("_ใช้แล้ว ส่วนของบัญชีระบบ และ _ซ้ำ ถูกเลือก", {"used-mine", "dup"} <= ids)
check("_ทิ้ง-กดลบ _พร้อมอ่าน _รายงาน ไม่ถูกแตะ", not ({"person-deleted", "staged", "report"} & picked_ids))
check("สัปดาห์ที่ไม่ได้ระบุ (W40) ไม่ถูกแตะ", "w40-pair" not in picked_ids)
check("Excel ที่ราก Exports ไม่ถูกแตะ", "Rider Trips.xlsx" not in picked_ids)
check("Exports/2026-W37 เป็นของระบบทั้งหมด: ย้ายทั้งโฟลเดอร์ ไม่ไล่ทีละไฟล์",
      "2026-W37" in whole and not ({"cust", "replaced"} & ids), (whole, ids))
check("Exports/2026-W38 มีไฟล์ของคนอื่น: ไล่ทีละไฟล์ เฉพาะของระบบ",
      "2026-W38" not in whole and "cust38" in ids and "someone-elses" not in picked_ids)

text = cd.summary(picked, {"2026-W37", "2026-W38"}, applied=False)
check("รายงานบอกว่ายังไม่ได้ลบ", "ยังไม่ได้ลบ" in text)
check("รายงานไม่มีชื่อไรเดอร์", "สมชาย" not in text)
check("ชนิดที่เลือกใช้ชื่อเดียวกับรายงาน Drive usage", du.RIDER in cd.KINDS and du.CUSTOMER in cd.KINDS)

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
