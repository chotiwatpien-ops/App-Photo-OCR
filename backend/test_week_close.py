# -*- coding: utf-8 -*-
"""ปิดสัปดาห์แล้วงานอัตโนมัติต้องไม่แตะสัปดาห์นั้นอีก (2026-09-13).

รอบ #210 เดินเข้าไปใน W36 ที่ส่งลูกค้าไปแล้ว และจะย้ายรูปซ้ำ 165 ใบออกจากโฟลเดอร์ไรเดอร์ เพดาน
กันไว้ทัน แต่คำตอบที่ถูกคือไม่ควรไปมองตั้งแต่แรก ปฏิทินบอกไม่ได้ว่าสัปดาห์ไหนจบ — งานของสัปดาห์
หนึ่งทำต่ออีกหลายวันหลังวันอาทิตย์ คนจึงเป็นคนกดปิด
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-wk-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import db                                                       # noqa: E402
import free_dup_seats as fds                                    # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


W36, W36_END = "2026-08-31", "2026-09-06"
W37, W37_END = "2026-09-07", "2026-09-13"

check("ยังไม่มีใครกดปิด ทุกสัปดาห์เปิดหมด",
      fds.week_is_open(W36, W36_END, today="2026-09-13")
      and fds.week_is_open(W37, W37_END, today="2026-09-13"))
check("ปิดสัปดาห์ได้", db.close_week(W36, W36_END, by="ทดสอบ"))
check("กดปิดซ้ำไม่พัง แค่บอกว่าปิดอยู่แล้ว", db.close_week(W36, W36_END) is False)
check("ถามตรง ๆ ว่าปิดยัง", db.week_closed(W36) and not db.week_closed(W37))
check("สัปดาห์ที่ปิดแล้ว = ไม่เปิด", not fds.week_is_open(W36, W36_END, today="2026-09-13"))
check("สัปดาห์ที่ยังไม่ปิด ไม่ถูกกระทบ", fds.week_is_open(W37, W37_END, today="2026-09-13"))
check("รายชื่อสัปดาห์ที่ปิดมีเวลาที่กดไว้ด้วย",
      W36 in db.closed_weeks() and db.closed_weeks()[W36]["closed_at"])

# ส่ง set เข้ามาเองได้ เพื่อไม่ต้องถามฐานข้อมูลซ้ำทุกสัปดาห์ในรอบเดียว
check("ส่งรายชื่อที่ปิดแล้วเข้ามาเองได้", not fds.week_is_open(W37, W37_END, closed={W37}))

# ตาข่ายกันพลาด: ไม่มีใครกดปิดเลย แต่สัปดาห์เก่ามาก ๆ ต้องไม่ถูกแตะตลอดกาล
check(f"สัปดาห์ที่จบไปเกิน {fds.STALE_DAYS} วัน ถือว่าจบ แม้ไม่มีใครกด",
      not fds.week_is_open("2026-07-06", "2026-07-12", closed=set(), today="2026-09-13"))
check("จบไปไม่นาน ยังเปิดอยู่ ถ้าไม่มีใครกดปิด",
      fds.week_is_open("2026-09-01", "2026-09-06", closed=set(), today="2026-09-13"))
check("ไม่รู้วันจบ และไม่มีใครกดปิด → ยังเปิด (ไม่เดา)",
      fds.week_is_open("2026-09-07", None, closed=set(), today="2026-09-13"))

check("เปิดสัปดาห์ใหม่ได้", db.reopen_week(W36) and fds.week_is_open(W36, W36_END, today="2026-09-13"))
check("เปิดสัปดาห์ที่ไม่ได้ปิดไว้ ไม่พัง", db.reopen_week("2026-01-01") is False)


# --- รอบ ingest ต้องไม่เดินเข้าไปอ่านรูปของสัปดาห์ที่ปิดแล้ว (W37, 2026-09-16) -------------------
# ปิด W37 ไว้ที่ 1,470 ต่อ Service Type แล้วรอบ #253/#254 อ่านรูปที่ pool วางไว้ในโฟลเดอร์ไรเดอร์
# ต่ออีก 24 เที่ยว ไฟล์ที่ลูกค้าถืออยู่จึงโตขึ้นเอง
import ingest                                                   # noqa: E402
from drive_client import LocalDrive                             # noqa: E402

ROOT = os.path.join(WORK, "inbox")
for wk, rider in (("Week 31 Aug-6 Sep", "01-สมชาย Win"), ("Week 7-13 Sep", "01-สมชาย Win")):
    d = os.path.join(ROOT, wk, "2 W Standard", rider)
    os.makedirs(d)
    open(os.path.join(d, "a.jpg"), "wb").write(bytes([0xFF, 0xD8]))
drive = LocalDrive(ROOT)

items, skipped = ingest.discover(drive, ROOT, closed=set())
check("ไม่มีสัปดาห์ไหนปิด: เห็นรูปทั้งสองสัปดาห์", len(items) == 2)

items, skipped = ingest.discover(drive, ROOT, closed={W37})
check("ปิด W37 แล้ว: ไม่หยิบรูปของ W37 มาอ่าน",
      [i["week_from"] if "week_from" in i else i.get("date_from") for i in items] == [W36])
check("บอกไว้ในรายการที่ข้าม ว่าข้ามเพราะปิดสัปดาห์",
      any("ปิดสัปดาห์แล้ว" in m and "Week 7-13 Sep" in m for m in skipped))

items, _ = ingest.discover(drive, ROOT, closed={W36, W37})
check("ปิดทั้งสองสัปดาห์: ไม่มีอะไรให้อ่าน", items == [])


# --- แถวที่อ่านไม่สำเร็จในสัปดาห์ที่ปิดแล้ว: ไม่อ่านซ้ำ และปิดรายการปัญหาให้ (2026-09-16) --------
# W37 ปิดที่ 1,470 ต่อกลุ่มทั้งที่ยังมี 12 แถวค้างเป็น error — รอบถัดไปจะอ่านใหม่แล้วเติมเข้าไฟล์
# ที่ลูกค้าถืออยู่ ส่วนการ์ดปัญหาบนแดชบอร์ดก็ค้างตลอดกาลเพราะไม่มีใครแก้ได้แล้ว
from sqlalchemy import insert, select                            # noqa: E402

j_open = db.create_job("สมชาย Win", "Trips", W37, W37_END, category="2 W Standard")
j_shut = db.create_job("สมหญิง Win", "Trips", W36, W36_END, category="2 W Standard")
ids = {}
with db.engine.begin() as c:
    for n, jid in ((1, j_open), (2, j_shut)):
        tid = c.execute(insert(db.trips).values(job_id=jid, file_name=f"e{n}.jpg",
                                                status="error")).inserted_primary_key[0]
        ids[f"e{n}.jpg"] = tid
        c.execute(insert(db.ingested_files).values(drive_id=f"drive-{n}", job_id=jid, trip_id=tid,
                                                   name=f"e{n}.jpg", ingested_at="2026-09-16"))
db.close_week(W36, W36_END, by="ทดสอบ")

check("อ่านใหม่เฉพาะแถวของสัปดาห์ที่ยังเปิด",
      [t for t, _j in db.retryable_error_trips()] == [ids["e1.jpg"]])
check("แถว error ของสัปดาห์ที่ปิดแล้วถูกชี้ให้ปิดรายการปัญหา",
      [t for t, _j in db.error_trips_in_closed_weeks()] == [ids["e2.jpg"]])
# แถวที่ค้าง pending ก็มาทางฐานข้อมูลเหมือนกัน ต้องกันด้วย
with db.engine.begin() as c:
    for n, jid in ((3, j_open), (4, j_shut)):
        tid = c.execute(insert(db.trips).values(job_id=jid, file_name=f"p{n}.jpg",
                                                status="pending")).inserted_primary_key[0]
        ids[f"p{n}.jpg"] = tid
        c.execute(insert(db.ingested_files).values(drive_id=f"drive-{n}", job_id=jid, trip_id=tid,
                                                   name=f"p{n}.jpg", ingested_at="2026-09-16"))
check("แถวค้าง pending: หยิบเฉพาะของสัปดาห์ที่ยังเปิด",
      [t for t, _j in db.stuck_pending_trips()] == [ids["p3.jpg"]])

db.reopen_week(W36)
check("เปิดสัปดาห์กลับ: แถว pending ของสัปดาห์นั้นกลับมาเข้าคิวอ่าน",
      sorted(t for t, _j in db.stuck_pending_trips()) == sorted([ids["p3.jpg"], ids["p4.jpg"]]))
check("เปิดสัปดาห์กลับ: กลับมาอ่านใหม่ได้ตามเดิม",
      sorted(t for t, _j in db.retryable_error_trips()) == sorted([ids["e1.jpg"], ids["e2.jpg"]])
      and db.error_trips_in_closed_weeks() == [])
db.close_week(W36, W36_END, by="ทดสอบ")

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
