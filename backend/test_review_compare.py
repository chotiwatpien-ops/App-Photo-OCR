# -*- coding: utf-8 -*-
"""A suspected repeat in the review queue shows the duplicate report's side-by-side picture
(Fiat 2026-11-15). The web server cannot reach Drive, so the other picture used to read
"โหลดรูปไม่ได้" and W46 #43332 was decided without it."""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-compare-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from fastapi import HTTPException                               # noqa: E402
from sqlalchemy import insert, update                           # noqa: E402

import db                                                       # noqa: E402
import dup_examples                                             # noqa: E402
import duplicate_report                                         # noqa: E402
import main                                                     # noqa: E402

ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


db.init_db()
job = db.create_job("ธนภัทร Taxi", "Trips", "2026-11-09", "2026-11-15", category="4 W Standard")
with db.engine.begin() as c:
    twin = c.execute(insert(db.trips).values(job_id=job, file_name="1137_0.jpg", status="done",
                                             committed=1, net_earnings=90)).inserted_primary_key[0]
    mine = c.execute(insert(db.trips).values(job_id=job, file_name="1128_0.jpg", status="done",
                                             committed=0, net_earnings=90)).inserted_primary_key[0]


def case(tid):
    return {"id": tid, "ไรเดอร์ผู้ส่ง": "4W Ploy 636งาน 11Nov", "ไฟล์ที่ซ้ำ": "1128_0.jpg", "ยอด": 90.0,
            "ลิงก์รูป": "https://drive.google.com/file/d/mine-id/view", "twin_url": "https://drive.google.com/file/d/twin-id/view",
            "ซ้ำกับไฟล์": "1137_0.jpg", "ของไรเดอร์": "4W Ploy 636งาน 11Nov", "ประเภทการซ้ำ": duplicate_report.KIND_SUSPECT,
            "รหัสการจอง": "A-A2EXNJNWWROGOAV"}


found = dup_examples.entries([], [case(mine)], [], {})
check("แถวที่รอคนตัดสินรู้ id ของตัวเอง", [e.trip_id for e in found] == [mine])
check("แถวที่ตัดออกไปแล้วไม่มี id ให้คิวตรวจ",
      [e.trip_id for e in dup_examples.entries([case(mine)], [], [], {})] == [None])


class Drive:
    def __init__(self):
        self.asked = []

    def download(self, fid):
        self.asked.append(fid)
        return b"\xff\xd8 side-by-side " + fid.encode()


d = Drive()
duplicate_report.keep_for_review(d, found, {found[0].name: "compare-id"}, log=lambda *_a: None)
check("❗ รูปเปรียบเทียบของแถวที่รอตรวจเก็บลงฐานข้อมูล",
      main.trip_compare(mine).body == b"\xff\xd8 side-by-side compare-id")
duplicate_report.keep_for_review(d, found, {found[0].name: "compare-id"}, log=lambda *_a: None)
check("รอบถัดไปไม่โหลดซ้ำจาก Drive", d.asked == ["compare-id"])

with db.engine.begin() as c:
    c.execute(update(db.trips).where(db.trips.c.id == mine).values(committed=1))
try:
    main.trip_compare(mine)
    refused = None
except HTTPException as e:
    refused = e.status_code
check("❗ ตัดสินแล้ว (อนุมัติ) — ไม่แสดงรูปเปรียบเทียบอีก", refused == 404)
duplicate_report.keep_for_review(d, [], {}, log=lambda *_a: None)
check("❗ รอบถัดไปลบรูปของแถวที่ตัดสินแล้วออกจากฐานข้อมูล", db.review_picture_ids() == set())


class Broken:
    def download(self, fid):
        raise OSError("Drive down")


with db.engine.begin() as c:
    c.execute(update(db.trips).where(db.trips.c.id == mine).values(committed=0))
duplicate_report.keep_for_review(Broken(), found, {found[0].name: "compare-id"}, log=lambda *_a: None)
check("Drive ล่ม — รายงานยังไปต่อ คิวตรวจแค่ไม่มีรูปเปรียบเทียบ", db.review_picture_ids() == set())

fonts = dup_examples._fonts()
if fonts:
    from PIL import Image, ImageDraw
    reg, _bold = fonts
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    long = "อัลบั้ม 4W Ploy 636งาน 11Nov ชื่อยาวมากจนล้นไปใต้รูปฝั่งขวา"
    cut = dup_examples._fit(draw, long, reg(26), 300)
    check("❗ ชื่ออัลบั้มยาวถูกตัดให้อยู่ในคอลัมน์ของตัวเอง ไม่ทับรูปฝั่งขวา",
          cut.endswith("…") and draw.textlength(cut, font=reg(26)) <= 300, cut)
    check("ชื่อสั้นไม่ถูกตัด", dup_examples._fit(draw, "ส่งโดย Ploy", reg(26), 300) == "ส่งโดย Ploy")

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
