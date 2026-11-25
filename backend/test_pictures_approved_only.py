# -*- coding: utf-8 -*-
"""The customer's picture folder holds a picture for every trip in the file and nothing else.

A picture used to be made for every row that had been read, approved or not, so a row the queue
was still holding, or one taken out afterwards, put a picture beside the delivered ones (W46: two,
W47's close audit: one). Now a picture is made only for an approved row: in the same round when
the round approves it, from the bytes it already holds, and in the next round when a person
approves it in the web. A picture whose row leaves the file moves to _ไม่อยู่ในไฟล์ in an open
week and stays where it is in a closed one; nothing is deleted.

Runs the real round on LocalDrive and a throwaway SQLite, reading stubbed."""
import os
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-approvedpics-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import config                                                   # noqa: E402
import db                                                       # noqa: E402
import free_dup_seats                                           # noqa: E402
import ingest                                                   # noqa: E402
import pipeline                                                 # noqa: E402
import week_files                                               # noqa: E402
from drive_client import LocalDrive                             # noqa: E402
from PIL import Image                                           # noqa: E402
from sqlalchemy import select                                   # noqa: E402

assert "sqlite" in config.DATABASE_URL, config.DATABASE_URL
db.init_db()
free_dup_seats.STALE_DAYS = 10 ** 4       # the test week must stay open whatever today is
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


W = ("2026-11-16", "2026-11-22")
inbox = Path(WORK) / "Inbox"
rider_dir = inbox / "Week 16-22 Nov" / "2 W Saver" / "Admin Yo" / "01 สมชาย"
rider_dir.mkdir(parents=True)
for i in range(1, 6):
    Image.new("RGB", (720, 1560), (40 * i, 240 - 30 * i, 120 + 20 * i)).save(rider_dir / f"{i}.jpg", "JPEG")
exports = Path(WORK) / "Exports"
exports.mkdir()
saver = exports / "2026-W47" / "2 W Saver"

FAKE = {
    "1.jpg": {"kind": "full", "net_earnings": 100.0, "base_fare": 100.0, "booking_code": "A-ONE"},
    "2.jpg": {"kind": "full", "net_earnings": 200.0, "base_fare": 200.0, "booking_code": "A-TWO"},
    "3.jpg": {"kind": "full", "net_earnings": 300.0, "base_fare": 100.0, "booking_code": "A-THREE"},
    "4.jpg": {"kind": "full", "net_earnings": 400.0, "base_fare": 400.0, "booking_code": "A-FOUR"},
    "5.jpg": {"kind": "full", "net_earnings": 500.0, "base_fare": 500.0, "booking_code": "A-FIVE"},
}
order = sorted(FAKE)


def fake_extract(image_bytes, mime="image/jpeg", model=None, drop=()):
    d = dict(FAKE[order.pop(0)])
    d["_usage"] = {"model": "test", "tok_in": 1, "tok_out": 1, "tok_think": 0}
    return d


pipeline.extractor.extract_image = fake_extract
config.INGEST_BATCH = False
ingest.config.INGEST_BATCH = False


class CountingDrive(LocalDrive):
    downloads = 0

    def download(self, file_id):
        CountingDrive.downloads += 1
        return super().download(file_id)


drive = CountingDrive(inbox)


def round_():
    CountingDrive.downloads = 0
    errs = ingest.run(drive, str(inbox), str(exports))
    return errs, CountingDrive.downloads


def rows():
    t = db.trips.c
    with db.engine.begin() as c:
        return {r["file_name"]: dict(r) for r in c.execute(
            select(t.id, t.file_name, t.status, t.committed, t.customer_image)).mappings()}


def shown():
    return sorted(p.name for p in saver.iterdir() if p.is_file()) if saver.exists() else []


def held():
    d = saver / week_files.OUT_DIR
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


def everywhere():
    return sorted(p.name for p in exports.rglob("*.jpg"))


errs, downloads = round_()
r = rows()
approved = [n for n in FAKE if r[n]["committed"]]
check("รอบแรก: อนุมัติ 4 แถว · แถว 3.jpg รอคน", errs == 0 and sorted(approved) == ["1.jpg", "2.jpg", "4.jpg", "5.jpg"]
      and r["3.jpg"]["status"] == "done" and not r["3.jpg"]["committed"], (errs, approved))
check("❗ แถวที่รอคนไม่ได้รูปส่งลูกค้า (ไม่มีชื่อรูป ไม่มีไฟล์ที่ไหนเลย)",
      not r["3.jpg"]["customer_image"] and len(everywhere()) == 4, (r["3.jpg"]["customer_image"], everywhere()))
check("แถวที่อนุมัติได้รูปในรอบเดียวกัน ชื่อตรงกับแถว",
      shown() == sorted(r[n]["customer_image"] for n in approved), (shown(), [r[n]["customer_image"] for n in approved]))
check("❗ รูปของแถวที่อนุมัติในรอบนี้ทำจากไฟล์ที่โหลดมาแล้ว ไม่โหลดซ้ำ (5 สลิป = 5 ครั้ง)", downloads == 5, downloads)
check("ใบตรวจไม่นับแถวที่รอคนเป็นแถวไม่มีรูป", db.week_scorecard(*W)["no_picture"] == 0, db.week_scorecard(*W)["no_picture"])

check("คนกดอนุมัติแถวที่รอในหน้าเว็บ", db.approve_trip(r["3.jpg"]["id"]).get("ok"))
errs, downloads = round_()
r = rows()
check("❗ รอบถัดไปสร้างรูปให้แถวที่คนอนุมัติ", errs == 0 and r["3.jpg"]["customer_image"] in shown(),
      (errs, r["3.jpg"]["customer_image"], shown()))
check("โหลดเฉพาะสลิปของแถวนั้นใบเดียว", downloads == 1, downloads)
errs, downloads = round_()
check("รอบที่ไม่มีอะไรต้องทำ ไม่สร้าง ไม่โหลดอะไร", errs == 0 and downloads == 0 and len(everywhere()) == 5,
      (errs, downloads, everywhere()))

gone = r["2.jpg"]["customer_image"]
db.void_trips([r["2.jpg"]["id"]], "test: ไม่ใช่งาน")
errs, _ = round_()
check("❗ แถวที่ถูกเอาออกหลังอนุมัติ รูปย้ายออกไป _ไม่อยู่ในไฟล์ ในสัปดาห์ที่ยังเปิด",
      gone not in shown() and held() == [gone], (shown(), held()))
check("รูปที่แถวอนุมัติยังใช้อยู่ไม่ขยับ",
      shown() == sorted(r[n]["customer_image"] for n in ("1.jpg", "3.jpg", "4.jpg", "5.jpg")), shown())
check("ไม่มีรูปไหนถูกลบ", len(everywhere()) == 5, everywhere())

db.close_week(*W, by="test")
stay = r["4.jpg"]["customer_image"]
db.void_trips([r["4.jpg"]["id"]], "test: ไม่ใช่งาน")
errs, downloads = round_()
check("❗ สัปดาห์ที่ปิดแล้ว รูปของแถวที่ถูกเอาออกอยู่ที่เดิม", stay in shown() and held() == [gone], (shown(), held()))

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
