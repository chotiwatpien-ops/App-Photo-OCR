# -*- coding: utf-8 -*-
"""Two things a round stopped doing the slow way (2026-09-09).

ONE HAND-OVER. Pictures used to go to the batch queue a rider at a time: run #141 created 125
batch jobs for 251 pictures and spent 21 minutes of the next round asking Google about each
one. One job carries up to 60 pictures, so the whole round now goes over in a few.

WALKING WHAT CHANGED — OFF since the day it shipped, and these tests say why it is off.
The rule below is correct in itself, and it rests on something untrue: that Drive stamps a
folder when a file enters it. A directory on disk does, which is why every check here passed;
Drive does not. On 2026-09-09 the pool moved 19 pictures into a rider folder at 01:08 and at
08:11 the folder's modifiedTime still read the previous evening, so the round skipped it and
saw none of them. The tests are kept because the bookkeeping they cover is right and would be
needed again by a version built on a signal Drive really gives — but the default is off, and
this file checks that too.
"""
import os
import shutil
import sys
import tempfile
from io import BytesIO

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-speed-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from PIL import Image                                           # noqa: E402

import batch_client                                             # noqa: E402
import config                                                   # noqa: E402
import db                                                       # noqa: E402
import ingest                                                   # noqa: E402
from drive_client import LocalDrive                             # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


def slip(seed, into):
    b = BytesIO()
    Image.new("RGB", (720, 1560), (10 + seed, 200, 120)).save(b, "JPEG")
    with open(into, "wb") as f:
        f.write(b.getvalue())


ROOT = os.path.join(WORK, "drive")
INBOX = os.path.join(ROOT, "Inbox")
EXPORTS = os.path.join(ROOT, "Exports")
RIDERS = ["01-ก Win", "02-ข Win", "03-ค Win"]
group = os.path.join(INBOX, "Week 31 Aug-6 Sep", "2 W Saver")
for i, r in enumerate(RIDERS):
    os.makedirs(os.path.join(group, r), exist_ok=True)
    for k in (1, 2):
        slip(i * 10 + k, os.path.join(group, r, f"{r[:2]}{k}.jpg"))
os.makedirs(EXPORTS, exist_ok=True)


class Drive(LocalDrive):
    """A local tree that counts what it was asked, and can refuse one download."""

    def __init__(self, root):
        super().__init__(root)
        self.listed, self.fail = [], set()

    def list_images(self, parent_id):
        self.listed.append(str(parent_id))
        return super().list_images(parent_id)

    def download(self, file_id):
        if os.path.basename(str(file_id)) in self.fail:
            raise RuntimeError("โหลดไม่ได้ (ทดสอบ)")
        return super().download(file_id)


submits = []


def fake_submit(items, model=None, display_name="ingest", workers=4):
    """Stand in for Gemini: one entry per chunk, exactly as the real client returns."""
    submits.append(list(items))
    out, n = [], 0
    for i in range(0, len(items), batch_client.MAX_CHUNK_ITEMS):
        chunk = items[i:i + batch_client.MAX_CHUNK_ITEMS]
        n += 1
        out.append({"name": f"batches/{display_name}-{len(submits)}-{n}",
                    "trips": [t for t, _d, _m in chunk], "model": "fake"})
    return out


batch_client.submit = fake_submit
batch_client.collect = lambda name: ("JOB_STATE_PENDING", {}, {})   # answers come later
config.INGEST_BATCH = True
config.STORE_DRIVE_IMAGES = False


def round_once(drive):
    del submits[:]
    drive.listed = []
    ingest.run(drive, INBOX, EXPORTS)
    return drive


# --- one hand-over for the whole round ---------------------------------------------------------
check("ค่าเริ่มต้นคือปิด — Drive ไม่ประทับเวลาโฟลเดอร์เมื่อมีไฟล์ถูกย้ายเข้า", config.WALK_CACHE is False)
config.WALK_CACHE = True      # the rest of this file tests the bookkeeping itself

d = Drive(ROOT)
round_once(d)
check("สามไรเดอร์ หกรูป → ส่ง batch ครั้งเดียว ไม่ใช่สามครั้ง", len(submits) == 1)
check("และครั้งนั้นมีรูปครบทั้งหก", len(submits[0]) == 6)
check("บันทึกไว้เป็น batch เดียว", len(db.open_batches()) == 1)
jobs_in_batch = {j for _t, j in db.batch_trip_jobs(db.open_batches()[0]["name"])}
check("batch เดียวข้ามหลาย job ได้ (เก็บผลรอบหน้าแยกกลับเข้า job เองอยู่แล้ว)", len(jobs_in_batch) == 3)

# --- the walk cache: read to the end once, then skipped ----------------------------------------
walked_1 = [p for p in d.listed if os.path.basename(p) in RIDERS]
check("รอบแรกเดินครบทุกโฟลเดอร์ไรเดอร์", len(walked_1) == 3)
check("รอบแรกยังไม่จำว่าโฟลเดอร์ไหนสะอาด (เพิ่งเจอรูปใหม่ในนั้น)", db.walk_cache_load() == {})

round_once(d)
walked_2 = [p for p in d.listed if os.path.basename(p) in RIDERS]
check("รอบสองเดินอีกครั้ง แล้วพบว่าไม่มีอะไรใหม่", len(walked_2) == 3)
check("จึงจำไว้ทั้งสามโฟลเดอร์", len(db.walk_cache_load()) == 3)

round_once(d)
walked_3 = [p for p in d.listed if os.path.basename(p) in RIDERS]
check("รอบสามข้ามทั้งสามโฟลเดอร์ ไม่ต้องถาม Drive", walked_3 == [])
check("และยังจำไว้เหมือนเดิม", len(db.walk_cache_load()) == 3)

# --- a folder Ops adds to is walked again, the others are not -----------------------------------
slip(99, os.path.join(group, RIDERS[1], "ข3.jpg"))
round_once(d)
walked_4 = [os.path.basename(p) for p in d.listed if os.path.basename(p) in RIDERS]
check("เพิ่มรูปในโฟลเดอร์เดียว → เดินเฉพาะโฟลเดอร์นั้น", walked_4 == [RIDERS[1]])
check("และรูปใหม่ถูกส่งเข้า batch", len(submits) == 1 and len(submits[0]) == 1)

# A folder that had new work is deliberately walked once more: only a round that looks and
# finds nothing left may call it read. That costs one Drive call per changed folder and is what
# keeps a picture whose download failed from being forgotten.
round_once(d)
check("รอบถัดมายังเดินโฟลเดอร์นั้นอีกครั้งเพื่อยืนยันว่าไม่เหลืออะไร",
      [os.path.basename(p) for p in d.listed if os.path.basename(p) in RIDERS] == [RIDERS[1]])
round_once(d)
check("แล้วจึงกลับไปข้ามทั้งหมดอีกครั้ง",
      [p for p in d.listed if os.path.basename(p) in RIDERS] == [])

# --- a picture that could not be downloaded keeps its folder dirty ------------------------------
slip(77, os.path.join(group, RIDERS[2], "ค9.jpg"))
d.fail = {"ค9.jpg"}
round_once(d)
check("โหลดรูปไม่สำเร็จ → โฟลเดอร์นั้นไม่ถูกจำว่าสะอาด",
      os.path.join(group, RIDERS[2]) not in db.walk_cache_load())
d.fail = set()
round_once(d)
walked_7 = [os.path.basename(p) for p in d.listed if os.path.basename(p) in RIDERS]
check("รอบถัดไปจึงกลับมาลองรูปนั้นใหม่", walked_7 == [RIDERS[2]])
check("และคราวนี้อ่านได้", len(submits) == 1 and len(submits[0]) == 1)

# --- the cache is off when somebody asks for a full walk ----------------------------------------
round_once(d)                                   # settle: everything clean again
config.WALK_CACHE = False
round_once(d)
check("ปิด WALK_CACHE แล้วเดินครบทุกโฟลเดอร์ตามเดิม",
      len([p for p in d.listed if os.path.basename(p) in RIDERS]) == 3)
config.WALK_CACHE = True

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
