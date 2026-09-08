# -*- coding: utf-8 -*-
"""A picture whose verdict is already known is not downloaded again (2026-09-09).

The pool keeps each reading under the md5 of the bytes, which is right — the same picture read
twice must not be read twice. But finding the md5 meant downloading the picture, so run #141
pulled 404 pictures down to discover it needed to look at 88 of them. The md5 is now remembered
under the Drive file id as well; bytes are fetched for a fresh reading, for a service chip, and
for joining a pair, and for nothing else.
"""
import os
import shutil
import sys
import tempfile
from io import BytesIO

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-lazy-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from PIL import Image                                           # noqa: E402

import db                                                       # noqa: E402
import pool                                                     # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


# --- the id -> md5 memory ----------------------------------------------------------------------
db.pool_md5_save({"1AbC": "d" * 32, "2XyZ": "e" * 32})
got = db.pool_md5_load(["1AbC", "2XyZ", "ไม่เคยเห็น"])
check("จำ md5 ไว้ใต้ id ของไฟล์บน Drive ได้", got == {"1AbC": "d" * 32, "2XyZ": "e" * 32})
check("id ที่ไม่เคยเห็นไม่ตอบอะไรมั่ว", "ไม่เคยเห็น" not in got)
db.pool_md5_save({})
check("บันทึกของว่างไม่พัง", db.pool_md5_load([]) == {})


# --- bytes that arrive only when asked for ------------------------------------------------------
class Counter:
    def __init__(self, blobs, boom=()):
        self.blobs, self.boom, self.asked = blobs, set(boom), []

    def __call__(self, key):
        self.asked.append(key)
        if key in self.boom:
            raise RuntimeError("โหลดไม่ได้ (ทดสอบ)")
        return self.blobs[key]


c = Counter({"a": b"AAA", "b": b"BBB", "c": b"CCC"})
errs = []
im = pool.Images({"a": b"AAA"}, fetch_one=c, workers=4, errors=errs)
check("รูปที่โหลดมาแล้วไม่ถูกขอซ้ำ", im["a"] == b"AAA" and c.asked == [])
check("รูปที่ยังไม่มี ถูกขอตอนที่ต้องใช้", im["b"] == b"BBB" and c.asked == ["b"])
check("ขอครั้งเดียว ครั้งต่อไปใช้ของเดิม", im["b"] == b"BBB" and c.asked == ["b"])
im.prefetch(["c", "a", "b"])
check("prefetch ขอเฉพาะที่ยังไม่มี", c.asked == ["b", "c"])
check("get ของที่ไม่มีจริงๆ ตอบ None ไม่ระเบิด", pool.Images({}, fetch_one=None).get("z") is None)

bad = pool.Images({}, fetch_one=Counter({}, boom=["z"]), errors=errs)
check("โหลดไม่ได้ → get ตอบ None และบันทึกเป็นปัญหา", bad.get("z") is None and any("z" in e for e in errs))


# --- a whole pool, twice ------------------------------------------------------------------------
def slip(path, colour):
    img = Image.new("RGB", (720, 1560), colour)
    img.save(path, "JPEG")


ROOT = os.path.join(WORK, "drive")
alb = os.path.join(ROOT, "Week 17-23 Aug", "Pool", "2W", "2W-Win ทดสอบ")
os.makedirs(alb, exist_ok=True)
for i in range(1, 5):
    slip(os.path.join(alb, f"{i}.jpg"), (20 + i * 5, 180, 100))

from drive_client import LocalDrive                             # noqa: E402


class Drive(LocalDrive):
    def __init__(self, root):
        super().__init__(root)
        self.downloads = []

    def download(self, file_id):
        self.downloads.append(str(file_id))
        return super().download(file_id)


d = Drive(ROOT)
albums = pool.scan_inbox(d, ROOT)
r1 = pool.run_pool(d, albums, move=False, preview=False, use_db=True)
n1 = len(d.downloads)
check("รอบแรกโหลดรูปทั้งหมด", n1 == 4)

d.downloads = []
r2 = pool.run_pool(d, pool.scan_inbox(d, ROOT), move=False, preview=False, use_db=True)
check("รอบสองไม่โหลดอะไรเลย", d.downloads == [])
check("แต่ผลออกมาเหมือนเดิม",
      (r2["totals"]["n_pairs"], r2["totals"]["n_long"], r2["totals"]["n_leftover"])
      == (r1["totals"]["n_pairs"], r1["totals"]["n_long"], r1["totals"]["n_leftover"]))
check("และไม่ได้อ่าน OCR ใหม่", r2.get("ocr_cached") == r2["totals"]["n_images"] - r2["totals"]["n_duplicates"])

slip(os.path.join(alb, "5.jpg"), (240, 60, 60))
d.downloads = []
pool.run_pool(d, pool.scan_inbox(d, ROOT), move=False, preview=False, use_db=True)
check("เพิ่มรูปใหม่หนึ่งใบ → โหลดใบเดียว", [os.path.basename(x) for x in d.downloads] == ["5.jpg"])

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
