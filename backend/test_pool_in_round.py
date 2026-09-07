# -*- coding: utf-8 -*-
"""An ingest round must first pair and file what the Agent dropped into Week/Pool, then carry on
exactly as before. Same throwaway setup as test_no_blob_round: a local Inbox, reading stubbed."""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-round-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
os.environ["POOL_IN_ROUND"] = "1"
sys.path.insert(0, "backend")

SAMPLE = "Phase2/Test 7"
if not os.path.isdir(SAMPLE):
    print("ไม่มีตัวอย่าง Phase2/Test 7 — ข้าม")
    sys.exit(0)
try:
    import rapidocr_onnxruntime  # noqa: F401
except ImportError:
    print("ไม่มี rapidocr — ข้าม")
    sys.exit(0)

import config                                                   # noqa: E402
import db                                                       # noqa: E402
import ingest                                                   # noqa: E402
import pipeline                                                 # noqa: E402
from drive_client import LocalDrive                             # noqa: E402

assert config.POOL_IN_ROUND
db.init_db()

root = os.path.join(WORK, "Inbox")
week = os.path.join(root, "Week 17-23 Aug")
pool_album = os.path.join(week, "Pool", "4W-Taxi Dl-boy4 w")
os.makedirs(pool_album)
files = sorted(os.listdir(SAMPLE), key=lambda f: int(f.rsplit("_", 1)[1].split(".")[0]))[:8]   # 4 trips as halves
for f in files:
    shutil.copy2(os.path.join(SAMPLE, f), os.path.join(pool_album, f))
os.makedirs(os.path.join(week, "4 W Standard", "01 ทดสอบ"))                                # an empty rider folder
db.name_pool_load([("สมชาย", "4W", "Taxi"), ("สมหญิง", "4W", "Home")])   # ops' list, for the folders below
exports = os.path.join(WORK, "Exports")
os.makedirs(exports)

# the same round files the pool and then reads what it filed — stubbed, so no Gemini call goes out
read = []


def fake_extract(image_bytes, mime="image/jpeg", model=None, drop=()):
    read.append(len(image_bytes or b""))
    return {"kind": "full", "net_earnings": 100.0, "base_fare": 100.0,
            "booking_code": f"A-{len(read):03d}",
            "_usage": {"model": "test", "tok_in": 1, "tok_out": 1, "tok_think": 0}}


pipeline.extractor.extract_image = fake_extract
config.INGEST_BATCH = False
ingest.config.INGEST_BATCH = False

ok = True
errors = ingest.run(LocalDrive(root), root, exports)
print("1) รอบ ingest จบ · error", errors)
ok = ok and errors == 0

cat = os.path.join(week, "4 W Standard")
stitched = [os.path.join(r, f) for r, _, fs in os.walk(cat) for f in fs if f.endswith(".jpg")]
left = [f for f in os.listdir(pool_album) if f.endswith(".jpg")]
used = os.path.join(week, "Pool", "_ใช้แล้ว", "4W-Taxi Dl-boy4 w")
used_n = len(os.listdir(used)) if os.path.isdir(used) else 0
print(f"2) รอบเดียวกันจัดกองแล้ว: รูปต่อแล้วใน 4 W Standard {len(stitched)} · ต้นฉบับใน _ใช้แล้ว {used_n} · เหลือในกอง {len(left)}")
ok = ok and len(stitched) >= 3 and used_n == 2 * len(stitched) and len(left) == 8 - used_n

# and they land in a rider's folder — loose in the category folder is invisible to discover().
# It has to be the folder that was already there: a rider's 21 trips are theirs whatever tier the
# fares were, so somebody with room is filled before any new name is drawn. This used to draw a
# fresh 'สมชาย Taxi' and leave '01 ทดสอบ' empty, because a folder whose name did not end in the
# right driver kind was passed over — and there is no wrong kind any more.
riders = {os.path.basename(os.path.dirname(f)) for f in stitched}
print("2b) รูปเข้าโฟลเดอร์ไรเดอร์ที่มีอยู่แล้ว ไม่ลอยและไม่เปิดคนใหม่:",
      riders == {"01 ทดสอบ"}, sorted(riders))
ok = ok and riders == {"01 ทดสอบ"}

print(f"2c) รอบเดียวกันอ่านรูปที่เพิ่งจัดเข้าโฟลเดอร์: อ่านไป {len(read)} รูป")
ok = ok and len(read) == len(stitched)

runs = db.recent_pool_runs(1, with_report=True)
print("3) บันทึก pool run พร้อมเลขรอบ ingest:", bool(runs) and runs[0]["mode"] == "move"
      and "ingest_run_id" in __import__("json").loads(runs[0]["report"]))
ok = ok and bool(runs) and runs[0]["mode"] == "move"

# dry run must only report
before = sorted(os.listdir(pool_album))
ingest.run(LocalDrive(root), root, exports, dry_run=True)
print("4) dry run ไม่ย้ายอะไร:", sorted(os.listdir(pool_album)) == before)
ok = ok and sorted(os.listdir(pool_album)) == before

# switch off → the pool is left alone
config.POOL_IN_ROUND = False
ingest.config.POOL_IN_ROUND = False
shutil.copy2(os.path.join(SAMPLE, files[0]), os.path.join(pool_album, "extra_" + files[0]))
ingest.run(LocalDrive(root), root, exports)
print("5) ปิดสวิตช์แล้วกองไม่ถูกแตะ:", os.path.exists(os.path.join(pool_album, "extra_" + files[0])))
ok = ok and os.path.exists(os.path.join(pool_album, "extra_" + files[0]))

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
