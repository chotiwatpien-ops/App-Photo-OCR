# -*- coding: utf-8 -*-
"""A delivered week's repeats go into the database as duplicates, its picture folder matches the
rows left, and all of it can be undone (W34/W35 re-delivery, 2026-09-23)."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-clean-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from sqlalchemy import insert                                   # noqa: E402

import apply_clean as ac                                        # noqa: E402
import db                                                       # noqa: E402
from drive_client import LocalDrive                             # noqa: E402
from week_phase3 import week_rows                               # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


W = ("2026-08-17", "2026-08-23")
a = db.create_job("จิตติ", "Trips", *W, category="4 W Standard")
b = db.create_job("สมชาย", "Trips", *W, category="4 W Standard")
root = Path(WORK) / "drive"
exp = root / "exports" / "2026-W34" / "4 W Standard"
exp.mkdir(parents=True)
with db.engine.begin() as c:
    ins = lambda **kw: c.execute(insert(db.trips).values(**{"status": "done", "committed": 1,
                                                            "service_type": "Standard Car",
                                                            "trip_date": "2026-08-18", **kw})).inserted_primary_key[0]
    first = ins(job_id=a, file_name="a.jpg", booking_code="A-1", base_fare=111.0, customer_image="WK34-จิตติ1.jpg",
                passenger_paid=150.0, note="เดิม")
    again = ins(job_id=b, file_name="b.jpg", booking_code="A-1", base_fare=111.0, customer_image="WK34-สมชาย1.jpg")
    other = ins(job_id=b, file_name="c.jpg", booking_code="A-2", base_fare=80.0, customer_image="WK34-สมชาย2.jpg",
                note="โน้ตเก่า")
for n in ("WK34-จิตติ1.jpg", "WK34-สมชาย1.jpg", "WK34-สมชาย2.jpg", "WK34-ไม่มีแถว.jpg"):
    (exp / n).write_bytes(b"x")

rows, kept, dropped, held = ac.plan(*W)
check("แผน: ตัด 1 แถว เก็บ 2", len(dropped) == 1 and dropped[0][0]["id"] == again and len(kept) == 2)
check("รายงานอย่างเดียวไม่เขียน", ac.main(["--from", W[0], "--to", W[1]]) == 0 and len(week_rows(*W)) == 3)
ac.write(dropped, W[0])
t = db.get_trip(again)
check("❗ แถวที่ตัด → duplicate ชี้ไปแถวที่เก็บ และออกจากไฟล์ (committed 0)",
      t["status"] == "duplicate" and t["duplicate_of"] == first and t["committed"] == 0)
check("โน้ตบอกเหตุผลและแถวที่นับแทน", t["note"].startswith(f"{ac.MARK} 2026-W34") and f"#{first}" in t["note"])
check("❗ หน้าที่อ่านจากฐานข้อมูลเห็นแค่ 2 แถวแล้ว", len(week_rows(*W)) == 2)
done = ac.tidy_pictures(LocalDrive(root), str(root / "exports"), W[0], week_rows(*W), log=lambda *_: None)
check("❗ รูปของแถวที่ตัด และรูปที่ไม่มีแถว ย้ายไป _แทนที่แล้ว ไม่ถูกลบ",
      sorted(p.name for p in exp.glob("*.jpg")) == ["WK34-จิตติ1.jpg", "WK34-สมชาย2.jpg"]
      and sorted(p.name for p in (root / "exports" / "2026-W34" / "_แทนที่แล้ว").glob("*.jpg"))
      == ["WK34-สมชาย1.jpg", "WK34-ไม่มีแถว.jpg"])
check("ทุกแถวที่เหลือมีรูป", done["แถวที่หารูปไม่เจอ"] == 0 and done["แถวที่รูปอยู่ครบ"] == 2)
check("รันซ้ำ: ไม่มีอะไรต้องตัดแล้ว", not ac.plan(*W)[2])
check("❗ undo คืนแถวกลับ", ac.undo(*W) == 1 and db.get_trip(again)["status"] == "done"
      and db.get_trip(again)["committed"] == 1 and db.get_trip(again)["duplicate_of"] is None
      and len(week_rows(*W)) == 3)
check("undo ไม่แตะโน้ตของแถวอื่น", db.get_trip(other)["note"] == "โน้ตเก่า" and db.get_trip(first)["note"] == "เดิม")

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
