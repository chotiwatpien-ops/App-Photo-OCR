# -*- coding: utf-8 -*-
"""In read-then-file mode a trip whose type the free OCR cannot tell still leaves the pool.

2W-Win มกรา = 105 held three long pictures in its pool for days (2026-09-21): 41 KB screenshots
whose 'Standard Bike' chip was too small to read, in an album named '2W' with no tier. The pool
needed the group to pick a rider — but with config.POOL_STAGE no rider is picked until the slip
has been read, so the trip can go to _พร้อมอ่าน and be filed by what the reader sees.
Runs on a small copy of the Phase2 sample (skipped if absent).
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-stage-unknown-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

SAMPLE = "Phase2/Test 7"
if not os.path.isdir(SAMPLE):
    print("ไม่มีตัวอย่าง Phase2/Test 7 — ข้าม")
    sys.exit(0)
try:
    import rapidocr_onnxruntime  # noqa: F401
except ImportError:
    print("ไม่มี rapidocr — ข้าม (pip install -r backend/requirements-pairing.txt)")
    sys.exit(0)

import config                                                   # noqa: E402
import db                                                       # noqa: E402
import pairing                                                  # noqa: E402
import pool                                                     # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


root = os.path.join(WORK, "Inbox")
week = os.path.join(root, "Week 14-20 Sep")
album = os.path.join(week, "Pool", "2W", "2W-Win มกรา = 105")     # wheels in the name, no tier
os.makedirs(album)
files = sorted(os.listdir(SAMPLE), key=lambda f: int(f.rsplit("_", 1)[1].split(".")[0]))[:6]
for f in files:
    shutil.copy2(os.path.join(SAMPLE, f), os.path.join(album, f))
db.init_db()

# the chip cannot be read — as on the 41 KB screenshots
pairing.vehicle_type = lambda _data: (None, None)


def jpgs(path):
    return sorted(f for f in os.listdir(path) if f.endswith(".jpg")) if os.path.isdir(path) else []


config.POOL_STAGE = False
rc1 = pool.main(["--local", root, "--move"])
check("โหมดเดิม: ไม่รู้ประเภท = ยังอยู่ในกอง (ไม่มีไรเดอร์ให้เลือก)",
      rc1 == 0 and len(jpgs(album)) == 6 and not jpgs(os.path.join(week, pool.HOLDING_DIR)))

config.POOL_STAGE = True
rc2 = pool.main(["--local", root, "--move"])
staged = jpgs(os.path.join(week, pool.HOLDING_DIR))
report = __import__("json").loads(db.recent_pool_runs(1, with_report=True)[0]["report"])
moved = [p for a in report["albums"] for p in a["pairs"] if p.get("dest")]
check("❗ โหมดพร้อมอ่าน: คู่ที่ไม่รู้ประเภทไปกองพัก _พร้อมอ่าน", rc2 == 0 and len(staged) >= 1
      and len(staged) == len(moved))
check("ต้นฉบับออกจากกองไป _ใช้แล้ว ไม่ได้ถูกลบ",
      len(jpgs(album)) == 6 - 2 * len(staged)
      and len([f for dp, _, fs in os.walk(os.path.join(week, "Pool", "_ใช้แล้ว")) for f in fs]) == 2 * len(staged))
check("รายงานบอกว่าให้สลิปบอกประเภทหลังอ่าน",
      all(p.get("target_from") == "ให้สลิปบอกหลังอ่าน" for p in moved))
check("ไม่มีโฟลเดอร์กลุ่มรถถูกสร้างเดาเอา", not any(c.lower().startswith(("2 w", "4 w")) for c in os.listdir(week)))

config.POOL_STAGE = False
shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
