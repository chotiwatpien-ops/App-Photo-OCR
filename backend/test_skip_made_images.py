# -*- coding: utf-8 -*-
"""A second pass must not rebuild customer images that already exist.

Rounds with no new photos were spending up to two hours re-downloading slips from Drive to
re-make files that were already there. What must still hold: the names never shift, a trip
that has no picture yet is still made, and a forced rebuild remakes everything.
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-skip-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import db                                                       # noqa: E402
import pipeline                                                 # noqa: E402
from PIL import Image                                           # noqa: E402
from io import BytesIO                                          # noqa: E402

db.init_db()
ok = True


def slip(seed):
    buf = BytesIO()
    Image.new("RGB", (720, 1560), (10 * seed, 200, 120)).save(buf, "JPEG")
    return buf.getvalue()


job = db.create_job("สมชาย", "S", "2026-08-24", "2026-08-30", category="2 W Saver")
tids = []
for i in range(1, 5):
    tid = db.create_trip(job, f"{i}.jpg", slip(i), "image/jpeg")
    db.update_trip(tid, {"status": "done", "kind": "full", "net_earnings": 100.0 + i,
                         "base_fare": 100.0 + i, "check_status": "pass",
                         "trip_date": "2026-08-25"})
    tids.append(tid)

first = list(pipeline.customer_images(job, "สมชาย"))
print(f"1) รอบแรก สร้าง {len(first)} รูป: {[n for n, _ in first]}")
if len(first) != 4:
    ok = False

second = list(pipeline.customer_images(job, "สมชาย"))
print(f"2) รอบสอง (ไม่มีอะไรเปลี่ยน) สร้าง {len(second)} รูป — ต้องเป็น 0")
if second:
    ok = False
    print("   ✗ ยังสร้างซ้ำอยู่")

# A new trip lands in the MIDDLE of the order. Since 2026-09-09 a picture keeps the number it
# was delivered under, so the newcomer takes the number after the last one instead of pushing
# four files along — one file is made, not three.
tid5 = db.create_trip(job, "2b.jpg", slip(9), "image/jpeg")
db.update_trip(tid5, {"status": "done", "kind": "full", "net_earnings": 55.0, "base_fare": 55.0,
                      "check_status": "pass", "trip_date": "2026-08-25"})
third = list(pipeline.customer_images(job, "สมชาย"))
made = [n for n, _ in third]
print(f"3) มีทริปใหม่แทรกกลางลำดับ → สร้าง {len(third)} รูป: {made}")
print("   (ของเดิมทั้งสี่ใบไม่ถูกแตะ · ใบใหม่ได้เลขต่อท้าย)")
if len(third) != 1 or not made[0].endswith("สมชาย5.jpg"):
    ok = False
    print("   ✗ ควรสร้างใบเดียว และเป็นเลข 5 (ต่อท้าย ไม่แทรกกลาง)")

forced = list(pipeline.customer_images(job, "สมชาย", only_missing=False))
print(f"4) สั่งสร้างใหม่ทั้งหมด → {len(forced)} รูป — ต้องเป็น 5")
if len(forced) != 5:
    ok = False

names = [n for n, _ in forced]
print(f"5) ชื่อไฟล์หลังสร้างใหม่: {names}")
if len(set(names)) != len(names):
    ok = False
    print("   ✗ ชื่อซ้ำกัน")

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
