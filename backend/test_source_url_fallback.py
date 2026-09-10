# -*- coding: utf-8 -*-
"""A finished row whose bytes are gone and whose ingest record is missing still gets its
customer picture from the Drive link on the row itself (2026-09-10).

Four of W36's 4,411 rows sat in the Phase 2 file with no picture name: their blobs had been
cleared, nothing in ingested_files pointed at them, and customer_images() skipped them without
a word. The row's own source_url carries the same file id.
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-srcurl-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import db                                                       # noqa: E402
import pipeline                                                 # noqa: E402
from PIL import Image                                           # noqa: E402
from io import BytesIO                                          # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


def slip(seed):
    buf = BytesIO()
    Image.new("RGB", (720, 1560), (10 * seed, 200, 120)).save(buf, "JPEG")
    return buf.getvalue()


FID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456"
check("อ่าน id จากลิงก์ /file/d/…/view", pipeline._drive_file_id(f"https://drive.google.com/file/d/{FID}/view") == FID)
check("อ่าน id จากลิงก์ ?id=…", pipeline._drive_file_id(f"https://drive.google.com/open?id={FID}") == FID)
check("พาธในเครื่องไม่ใช่ลิงก์ Drive", pipeline._drive_file_id(r"C:\pics\a.jpg") is None and pipeline._drive_file_id(None) is None)

job = db.create_job("สมชาย", "S", "2026-08-31", "2026-09-06", category="2 W Standard")
tid = db.create_trip(job, "x.jpg", slip(1), "image/jpeg")
db.update_trip(tid, {"status": "done", "kind": "full", "net_earnings": 60.0, "base_fare": 60.0,
                     "check_status": "pass", "trip_date": "2026-09-01"})
from sqlalchemy import update                                   # noqa: E402


def strip(trip_id, url):
    """What approval and a move leave behind: no bytes, only the link."""
    with db.engine.begin() as c:
        c.execute(update(db.trips).where(db.trips.c.id == trip_id).values(image_blob=None, source_url=url))


strip(tid, f"https://drive.google.com/file/d/{FID}/view")
asked = []


def fetch(fid):
    asked.append(fid)
    return slip(2)


made = list(pipeline.customer_images(job, "สมชาย", fetch=fetch))
check("ไม่มี blob ไม่มี ingested_files → โหลดจากลิงก์บนแถวแล้วต่อรูปได้ 1 ใบ", len(made) == 1 and asked == [FID])
check("ตั้งชื่อรูปให้แถวแล้ว", db.trips_with_images(job)[0]["customer_image"] == made[0][0] == "WK36-สมชาย1.jpg")

# a row with neither bytes nor a Drive link is still skipped — but visibly, by the exporter
tid2 = db.create_trip(job, "y.jpg", slip(3), "image/jpeg")
db.update_trip(tid2, {"status": "done", "kind": "full", "net_earnings": 61.0, "base_fare": 61.0,
                      "check_status": "pass", "trip_date": "2026-09-02"})
strip(tid2, r"D:\old\y.jpg")
made2 = list(pipeline.customer_images(job, "สมชาย", fetch=fetch))
bare = [r for r in db.trips_with_images(job) if not r["customer_image"]]
check("แถวที่ไม่มีทั้ง blob และลิงก์ Drive ยังทำไม่ได้ และยังไม่มีชื่อรูป (ให้ export รายงาน)", made2 == [] and len(bare) == 1)

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
