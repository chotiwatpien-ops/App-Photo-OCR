# -*- coding: utf-8 -*-
"""A top half read this round with no lower half yet waits one round, on the batch path too.

Batch is the default path. The collect held the top, and the review sweep later in the same
round approved it anyway (audit 2026-10-31), so a guessed base fare went into the workbook
before the lower half had a chance to arrive.
"""
import io
import os
import sys
import tempfile
from contextlib import redirect_stdout

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-lonetop-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
os.environ["POOL_IN_ROUND"] = "0"
sys.path.insert(0, "backend")

import batch_client                                             # noqa: E402
import config                                                   # noqa: E402
import db                                                       # noqa: E402
import ingest                                                   # noqa: E402
from drive_client import LocalDrive                             # noqa: E402
from PIL import Image                                           # noqa: E402

db.init_db()
config.POOL_IN_ROUND = False
config.INGEST_BATCH = ingest.config.INGEST_BATCH = True
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


root = os.path.join(WORK, "Inbox")
rider = os.path.join(root, "Week 17-23 Aug", "2 W Saver", "Admin Yo", "01 สมชาย")
os.makedirs(rider)
exports = os.path.join(WORK, "Exports")
os.makedirs(exports)
Image.new("RGB", (720, 1560), (10, 245, 90)).save(os.path.join(rider, "1.jpg"), "JPEG")

SUBMITTED, ANSWERS = [], {}


def fake_submit(items, model=None, display_name="x", workers=4):
    SUBMITTED.append([t for t, _d, _m in items])
    return [{"name": f"batches/b{len(SUBMITTED)}", "model": "test", "trips": SUBMITTED[-1]}]


def fake_collect(name):
    if name in ANSWERS:
        return "JOB_STATE_SUCCEEDED", ANSWERS[name], {}
    return "JOB_STATE_RUNNING", {}, {}


batch_client.submit, batch_client.collect = fake_submit, fake_collect


def round_():
    with redirect_stdout(io.StringIO()):
        ingest.run(LocalDrive(root), root, exports)


round_()
check("รอบแรกส่งรูปเข้า batch", len(SUBMITTED) == 1 and len(SUBMITTED[0]) == 1)
tid = SUBMITTED[0][0]
ANSWERS["batches/b1"] = {tid: {"kind": "top", "net_earnings": 100.0, "base_fare": 100.0,
                               "booking_code": "A-TOPHALF12345", "service_type": "Saver Bike",
                               "_usage": {}}}
round_()
t = db.get_trip(tid)
check("ครึ่งบนที่เพิ่งอ่านรอบนี้ ยังไม่มีครึ่งล่าง: รอหนึ่งรอบ ไม่อนุมัติในรอบเดียวกัน",
      t["status"] == "done" and not t["committed"], (t["status"], t["committed"]))
round_()
t = db.get_trip(tid)
check("รอบถัดไปไม่มีครึ่งล่างมา: อนุมัติตามปกติ", bool(t["committed"]), t["committed"])

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
