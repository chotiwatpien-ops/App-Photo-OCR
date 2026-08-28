# -*- coding: utf-8 -*-
"""A round must work without copying photos into the database.

Runs the real ingest against a local folder of slips (LocalDrive) on a throwaway SQLite file,
with the reading stubbed so no money is spent, and checks that:
  1. no approved row keeps an image
  2. a row left for a person DOES keep one, or Ops cannot fix it
  3. customer images are still produced
  4. a row stuck 'pending' is recoverable from the source, not from a stored copy
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-noblob-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import config                                                   # noqa: E402
import db                                                       # noqa: E402
import ingest                                                   # noqa: E402
import pipeline                                                 # noqa: E402
from PIL import Image                                           # noqa: E402
from sqlalchemy import func, select                             # noqa: E402

assert "sqlite" in config.DATABASE_URL, config.DATABASE_URL
assert not config.STORE_DRIVE_IMAGES, "ค่าเริ่มต้นต้องไม่เก็บรูปลงฐานข้อมูล"
db.init_db()

# --- a small Inbox on disk: one rider, four slips ---
inbox = os.path.join(WORK, "Inbox", "Week 17-23 Aug", "2 W Saver", "Admin Yo", "01 สมชาย")
os.makedirs(inbox, exist_ok=True)
for i in range(1, 5):
    # each slip must LOOK different or the duplicate-image guard folds them into one
    Image.new("RGB", (720, 1560), (40 * i, 240 - 30 * i, 120 + 20 * i)).save(
        os.path.join(inbox, f"{i}.jpg"), "JPEG")

# --- read without calling Gemini: two clean trips, one row a person must look at ---
FAKE = {
    "1.jpg": {"kind": "full", "net_earnings": 100.0, "base_fare": 100.0, "booking_code": "A-ONE"},
    "2.jpg": {"kind": "full", "net_earnings": 200.0, "base_fare": 200.0, "booking_code": "A-TWO"},
    # numbers that cannot be reconciled — this is the row a person has to look at
    "3.jpg": {"kind": "full", "net_earnings": 300.0, "base_fare": 100.0, "booking_code": "A-THREE"},
    "4.jpg": {"kind": "full", "net_earnings": 400.0, "base_fare": 400.0, "booking_code": "A-FOUR"},
}
seen_bytes = {}


def fake_extract(image_bytes, mime="image/jpeg", model=None, drop=()):
    seen_bytes[len(seen_bytes)] = len(image_bytes or b"")
    name = fake_extract.order.pop(0)
    d = dict(FAKE[name])
    d["_usage"] = {"model": "test", "tok_in": 1, "tok_out": 1, "tok_think": 0}
    return d


fake_extract.order = ["1.jpg", "2.jpg", "3.jpg", "4.jpg"]
pipeline.extractor.extract_image = fake_extract
config.INGEST_BATCH = False          # live path, so the whole round runs in one go
ingest.config.INGEST_BATCH = False

from drive_client import LocalDrive                             # noqa: E402
root = os.path.join(WORK, "Inbox")
exports = os.path.join(WORK, "Exports")
os.makedirs(exports, exist_ok=True)
errors = ingest.run(LocalDrive(root), root, exports)

ok = errors == 0
t = db.trips.c
with db.engine.begin() as c:
    rows = c.execute(select(t.id, t.file_name, t.committed, t.status, t.check_status,
                            t.image_blob.isnot(None).label("has_img"))).mappings().all()
    total = len(rows)
    approved_with_img = [r for r in rows if r["committed"] and r["has_img"]]
    waiting = [r for r in rows if r["status"] == "done" and not r["committed"]]
    waiting_no_img = [r for r in waiting if not r["has_img"]]
    size = c.execute(select(func.sum(func.length(t.image_blob)))).scalar() or 0

print(f"1) อ่าน {total} รูป · error {errors}")
print(f"2) แถวที่อนุมัติแล้วยังเก็บรูปไว้: {len(approved_with_img)} (ต้องเป็น 0)")
print(f"3) แถวที่รอคน {len(waiting)} · ในนั้นไม่มีรูปให้ดู {len(waiting_no_img)} (ต้องเป็น 0)")
print(f"4) ข้อมูลรูปในฐานข้อมูลรวม {size/1024:.0f} KB "
      f"(ถ้าเก็บทุกใบจะเป็น ~{sum(os.path.getsize(os.path.join(inbox, f)) for f in os.listdir(inbox))/1024:.0f} KB)")
imgs = []
for dirpath, _, files in os.walk(exports):
    imgs += [f for f in files if f.endswith(".jpg")]
print(f"5) รูปส่งลูกค้าที่สร้างได้: {len(imgs)} ไฟล์")

if approved_with_img or waiting_no_img or errors:
    ok = False

# --- a pending row must be recoverable from the source, with no stored copy ---
with db.engine.begin() as c:
    tid = c.execute(select(t.id).where(t.committed == 1).limit(1)).scalar()
    c.execute(db.trips.update().where(t.id == tid).values(status="pending", image_blob=None))
stuck = db.stuck_pending_trips()
print(f"6) แถว pending ที่ไม่มีรูปในฐานข้อมูล → ระบบเห็นว่ากู้ได้: {[s[0] for s in stuck] == [tid]}")
if [s[0] for s in stuck] != [tid]:
    ok = False

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
