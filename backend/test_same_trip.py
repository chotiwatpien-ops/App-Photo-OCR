# -*- coding: utf-8 -*-
"""One rule for "is this the same trip?" (db.trip_key), everywhere it is asked.

A code of 15+ characters names one trip. A shorter one may have been cut off by the reader, so
it is the same trip only when the fare and clock time match too. The ingest round applied that;
the อนุมัติ button, the whole-job approve, the review queue, the same-job check and the week
audit matched on the code alone. Two real trips with one short code were both approved by the
round, then the audit called them a duplicate and the week could never be locked (audit
2026-10-31).
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-sametrip-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import db                                                       # noqa: E402
import week_audit                                               # noqa: E402

db.init_db()
WEEK = ("2026-09-21", "2026-09-27")
NEXT = ("2026-09-28", "2026-10-04")
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


def trip(job, name, code, base, time, approve=False):
    tid = db.create_trip(job, name, None, "image/jpeg")
    db.update_trip(tid, {"status": "done", "check_status": "pass", "booking_code": code,
                         "base_fare": base, "net_earnings": base, "trip_time": time,
                         "trip_date": "2026-09-22", "kind": "full"})
    if approve:
        db.approve_trip(tid)
    return tid


a = db.create_job("สมชาย", "Trips", *WEEK, category="2 W Saver")
b = db.create_job("สมหญิง", "Trips", *WEEK, category="2 W Saver")
t1 = trip(a, "1.jpg", "A-SHORT1", 50, "10:00", approve=True)
t2 = trip(b, "2.jpg", "A-SHORT1", 80, "18:00")

check("ปุ่มอนุมัติ: โค้ดสั้นเดียวกันแต่ยอดและเวลาต่างกัน เป็นอีกเที่ยว อนุมัติได้",
      db.approve_trip(t2).get("ok") is True)
rows = [db.get_trip(t1), db.get_trip(t2)]
check("ตรวจสัปดาห์: สองเที่ยวจริงไม่ถูกนับเป็นงานซ้ำ (ไม่บล็อกการล็อก)",
      week_audit.audit(rows)["งานซ้ำ-รหัสการจอง"] == [])

t3 = trip(b, "3.jpg", "A-SHORT1", 80, "18:00")
check("ปุ่มอนุมัติ: โค้ดสั้น ยอดและเวลาตรงกัน ยังเป็นงานซ้ำ ไม่ให้อนุมัติ",
      "error" in db.approve_trip(t3))
q = {r["id"]: r for r in db.review_queue()}
check("คิวตรวจ: ใบที่ซ้ำจริงบอกว่าอนุมัติไปแล้วใน job ไหน", q[t3]["seen_in_job"] == b, q[t3]["seen_in_job"])

t4 = trip(b, "4.jpg", "A-SHORT1", 65, "13:00")
q = {r["id"]: r for r in db.review_queue()}
check("คิวตรวจ: เที่ยวจริงที่โค้ดสั้นชนกัน ไม่ถูกขึ้นป้ายว่าอนุมัติไปแล้ว", q[t4]["seen_in_job"] is None,
      q[t4]["seen_in_job"])
check("เช็กใน job เดียวกัน: เที่ยวจริงที่โค้ดสั้นชนกันไม่ใช่รูปซ้ำ",
      db.find_job_duplicate(b, "A-SHORT1", t4, base_fare=65, trip_time="13:00") is None)
check("เช็กใน job เดียวกัน: ยอดและเวลาตรงกันยังจับได้",
      (db.find_job_duplicate(b, "A-SHORT1", t4, base_fare=80, trip_time="18:00") or {}).get("id") == t2)

c = db.create_job("สมศรี", "Trips", *NEXT, category="2 W Saver")
t5 = trip(c, "5.jpg", "A-LONGCODE123456", 50, "10:00")
trip(a, "6.jpg", "A-LONGCODE123456", 99, "20:00", approve=True)
q = {r["id"]: r for r in db.review_queue()}
check("คิวตรวจ: ซ้ำกับสัปดาห์อื่นไม่ขึ้นป้ายว่าอนุมัติไปแล้ว (ข้ามสัปดาห์เป็นงาน)",
      q[t5]["seen_in_job"] is None, q[t5]["seen_in_job"])
t7 = trip(b, "7.jpg", "A-LONGCODE123456", 12, "07:00")
check("โค้ดเต็ม: ยอดต่างก็ยังเป็นเที่ยวเดียวกัน", "error" in db.approve_trip(t7))
check("กุญแจเดียว: โค้ดเต็มไม่สนยอด/เวลา โค้ดสั้นต้องตรงทั้งสาม",
      db.trip_key({"booking_code": "A-LONGCODE123456", "base_fare": 1}) == ("A-LONGCODE123456",)
      and db.trip_key({"booking_code": "A-S", "base_fare": 1, "trip_time": "x"}) == ("A-S", 1, "x")
      and db.trip_key({"booking_code": " "}) is None)

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
