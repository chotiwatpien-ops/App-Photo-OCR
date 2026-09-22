# -*- coding: utf-8 -*-
"""Exact copies leave the pool with their originals, and the round compares against the whole week.

2W-Home Jabzaja sent its 48-picture album twice (2026-09-22). Round #328 skipped the second set as
exact copies but left it in the pool; round #329, the originals gone, paired the copies into 24
more trips, and only the round's per-rider hash check, which happened to still see the originals
in '(รออ่าน)', kept them from being read again. Runs on a small copy of the Phase2 sample.
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-copies-")
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

from sqlalchemy import insert                                   # noqa: E402

import config                                                   # noqa: E402
import db                                                       # noqa: E402
import pool                                                     # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


root = os.path.join(WORK, "Inbox")
week = os.path.join(root, "Week 14-20 Sep")
album = os.path.join(week, "Pool", "2W", "2W-Home Jabzaja")
os.makedirs(album)
files = sorted(os.listdir(SAMPLE), key=lambda f: int(f.rsplit("_", 1)[1].split(".")[0]))[:4]
for i, f in enumerate(files, 1):
    shutil.copy2(os.path.join(SAMPLE, f), os.path.join(album, f"L_{i}_0.jpg"))
    shutil.copy2(os.path.join(SAMPLE, f), os.path.join(album, f"L_{i + 48}_0.jpg"))   # the album, twice
db.init_db()


def jpgs(path):
    return sorted(f for f in os.listdir(path) if f.endswith(".jpg")) if os.path.isdir(path) else []


config.POOL_STAGE = True
rc = pool.main(["--local", root, "--move"])
used = os.path.join(week, "Pool", "_ใช้แล้ว", "2W-Home Jabzaja")
staged = jpgs(os.path.join(week, pool.HOLDING_DIR))
check("รอบแรก: จับคู่จากชุดแรก", rc == 0 and len(staged) >= 1)
check("❗ สำเนาทั้งชุดออกจากกองไป _ใช้แล้ว ไม่ถูกลบ",
      not [f for f in jpgs(album) if int(f.split("_")[1]) > 48]
      and {f"L_{i + 48}_0.jpg" for i in range(1, 5)} <= set(jpgs(used)))
before = len(staged)
pool.main(["--local", root, "--move"])
check("❗ รอบถัดไป: สำเนาไม่วนกลับมาเป็นคู่ใหม่",
      len(jpgs(os.path.join(week, pool.HOLDING_DIR))) == before)
rows = db.skipped_copies_for_week("2026-09-14")
check("จดลงรายงานรูปซ้ำ 4 ใบ ครั้งเดียว", len(rows) == 4)
check("บอกว่าเป็นสำเนาในอัลบั้มเดียวกัน และซ้ำกับใบไหน",
      all(r["kind"] == "สำเนาในอัลบั้มเดียวกัน" and r["same_as"].startswith("2W-Home Jabzaja/L_") for r in rows))

# --- the round's hash check covers the whole week, not one rider ----------------------------
j_rider = db.create_job("สมชาย Win", "Trips", "2026-09-14", "2026-09-20", category="2 W Standard")
db.create_job("(รออ่าน)", "Trips", "2026-09-14", "2026-09-20")
with db.engine.begin() as c:
    c.execute(insert(db.trips).values(job_id=j_rider, file_name="orig.jpg", status="done", image_hash="h1"))
check("❗ รูปที่อ่านแล้วในโฟลเดอร์ไรเดอร์ ถูกเห็นจากกองพักด้วย",
      db.seen_image_hashes_week("2026-09-14", "2026-09-20").get("h1") == "orig.jpg"
      and "h1" not in db.seen_image_hashes("(รออ่าน)", "2026-09-14", "2026-09-20"))
check("สัปดาห์อื่นไม่ปน", "h1" not in db.seen_image_hashes_week("2026-09-21", "2026-09-27"))

config.POOL_STAGE = False
shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
