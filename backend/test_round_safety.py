# -*- coding: utf-8 -*-
"""The weekly loop must not stop or lose work silently.

- A scheduled round is due on time, sooner when Gemini answers are waiting, and never blocked
  for good by a round that died without stamping its row.
- A round that crashes stamps its row.
- A picture's row and the record that it was taken are written together or not at all.
- A week folder without a year keeps its year across New Year."""
import os
import sys
import tempfile
from datetime import date, datetime

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-round-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import db                                                       # noqa: E402
import ingest                                                   # noqa: E402
import round_gate                                               # noqa: E402

db.init_db()
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


NOW = datetime(2026, 11, 10, 14, 0)
d = lambda last, batch=None: round_gate.decide(NOW, last, batch, min_gap=2.5, collect_min=45, stale=6)[0]  # noqa: E731
check("ไม่เคยมีรอบ: รันได้", d(None))
check("มีรอบกำลังรัน (เริ่มมา 1 ชม.): ไม่รัน", not d({"started_at": "2026-11-10T13:00:00"}))
check("รอบค้างเกิน 6 ชม.: ถือว่าล่ม รันได้", d({"started_at": "2026-11-10T07:30:00"}))
check("รอบล่าสุดจบไป 1 ชม. ไม่มี batch: ยังไม่รัน", not d({"finished_at": "2026-11-10T13:00:00"}))
check("รอบล่าสุดจบไป 3 ชม.: รัน", d({"finished_at": "2026-11-10T11:00:00"}))
check("มีผลอ่านรอเก็บ 50 นาที และรอบก่อนจบไป 1 ชม.: รันเลย ไม่ต้องรอ 2.5 ชม.",
      d({"finished_at": "2026-11-10T13:00:00"}, {"created_at": "2026-11-10T13:10:00"}))
check("batch เพิ่งส่ง 20 นาที: ยังไม่รัน",
      not d({"finished_at": "2026-11-10T13:00:00"}, {"created_at": "2026-11-10T13:40:00"}))
check("batch รอนานแล้ว แต่รอบก่อนเพิ่งจบ 10 นาที: ยังไม่รัน (ไม่ถามถี่เกิน)",
      not d({"finished_at": "2026-11-10T13:50:00"}, {"created_at": "2026-11-10T12:00:00"}))

# a round that crashes stamps its own row, and the exception still surfaces
real_run = ingest._run


def boom(*a, **k):
    raise RuntimeError("Drive หลุด")


ingest._run = boom
try:
    ingest.run(None, None, None)
    raised = False
except RuntimeError:
    raised = True
ingest._run = real_run
last = db.latest_ingest_run()
check("รอบที่ล้มยังโยน error ออกไป (GitHub เห็นว่าล้ม)", raised)
check("รอบที่ล้มถูกปิดแถวพร้อม error", bool(last["finished_at"]) and last["errors"] == 1
      and "Drive หลุด" in (last["notes"] or ""), last)
later = datetime.fromisoformat(last["finished_at"]).replace(hour=23, minute=59)
check("รอบที่ล้มไม่ขวางรอบถัดไปตามตาราง", "กำลังรัน" not in round_gate.decide(later, last, None, min_gap=0)[1])

# the row and its record go in together
job = db.create_job("ทดสอบ Win", "Trips", "2026-11-09", "2026-11-15")
tid = db.create_ingested_trip(job, "drive-1", "a.jpg", None, "image/jpeg", image_hash="h1",
                              trip_date="2026-11-10")
with db.engine.begin() as c:
    rec = c.execute(db.select(db.ingested_files).where(db.ingested_files.c.drive_id == "drive-1")).mappings().first()
    row = c.execute(db.select(db.trips).where(db.trips.c.id == tid)).mappings().first()
check("แถวกับบันทึกการรับรูปเขียนคู่กัน", rec and rec["trip_id"] == tid and row["trip_date"] == "2026-11-10")
try:
    db.create_ingested_trip(job, "drive-1", "a-again.jpg", None, "image/jpeg", image_hash="h2")
    failed = False
except Exception:  # noqa: BLE001
    failed = True
with db.engine.begin() as c:
    n = c.execute(db.select(db.func.count()).select_from(db.trips)
                  .where(db.trips.c.file_name == "a-again.jpg")).scalar()
check("ถ้าบันทึกการรับรูปเขียนไม่ได้ ก็ไม่มีแถวค้างครึ่งทาง", failed and n == 0, (failed, n))

# a week folder without a year, read on either side of New Year
real_today = ingest._today
ingest._today = lambda: date(2027, 1, 2)
check("2 ม.ค. 2027: 'Week 21-27 Dec' ยังเป็นปี 2026",
      ingest.parse_range("Week 21-27 Dec") == (date(2026, 12, 21), date(2026, 12, 27)),
      ingest.parse_range("Week 21-27 Dec"))
check("2 ม.ค. 2027: 'Week 28 Dec-3 Jan' คร่อมปีถูก",
      ingest.parse_range("Week 28 Dec-3 Jan") == (date(2026, 12, 28), date(2027, 1, 3)))
check("2 ม.ค. 2027: 'Week 4-10 Jan' เป็นปี 2027", ingest.parse_range("Week 4-10 Jan")[0] == date(2027, 1, 4))
check("โฟลเดอร์ไรเดอร์แบบเก่าก็ได้ปีที่ใกล้ที่สุด",
      ingest.parse_rider_folder("01 ทดสอบ 21-27 Dec")[1] == date(2026, 12, 21))
ingest._today = lambda: date(2026, 12, 30)
check("30 ธ.ค. 2026: 'Week 4-10 Jan' เป็นปี 2027", ingest.parse_range("Week 4-10 Jan")[0] == date(2027, 1, 4))
check("ชื่อที่ระบุปีเองใช้ปีนั้น", ingest.parse_range("Week 3-9 Aug 2026")[0] == date(2026, 8, 3))
ingest._today = real_today

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
