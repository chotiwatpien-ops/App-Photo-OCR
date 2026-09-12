# -*- coding: utf-8 -*-
"""ค่าอ่านต่อสัปดาห์คิดจาก token จริง และรอบที่ผ่าน Batch API คิดครึ่งราคา (2026-09-12).

ราคาป้ายต่อรูปเป็นค่าเฉลี่ยของการวัดครั้งเดียว ของจริงอยู่ในแถว: ทุกแถวเก็บ model และ token ไว้
ตั้งแต่ต้นโปรเจกต์ เทสต์นี้ใช้ SQLite ชั่วคราวแทนฐานข้อมูลจริง
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-cost-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import config                                                   # noqa: E402
import cost_report                                              # noqa: E402
import db                                                       # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


def job(date_from, created_at):
    with db.engine.begin() as c:
        return c.execute(db.jobs.insert().values(
            driver_name="ทดสอบ", sheet="Trips", date_from=date_from, date_to=date_from,
            status="committed", created_at=created_at).returning(db.jobs.c.id)).scalar()


def trip(job_id, model, tin, tout, think=0):
    with db.engine.begin() as c:
        c.execute(db.trips.insert().values(job_id=job_id, file_name="a.jpg", status="done",
                                           model=model, tok_in=tin, tok_out=tout, tok_think=think))


check("'2026-08-31' อยู่สัปดาห์ W36", cost_report.iso_week("2026-08-31") == "2026-W36")
check("วันที่ว่างไม่ทำให้ล่ม", cost_report.iso_week(None) == "ไม่รู้สัปดาห์")

# ราคา gemini-3.7-flash = $0.75 เข้า / $3.75 ออก ต่อล้าน token, USD_THB = 35
_p = cost_report.price_thb("gemini-3.7-flash", 1_000_000, 1_000_000, 0)
check("คิดราคาเข้า+ออกถูกต้อง (0.75+3.75 = $4.50 → ฿157.5)", abs(_p - 4.5 * config.USD_THB) < 0.01)
check("thinking คิดเป็น output",
      abs(cost_report.price_thb("gemini-3.7-flash", 0, 0, 1_000_000) - 3.75 * config.USD_THB) < 0.01)
check("โมเดลที่ไม่มีราคา ไม่เดา", cost_report.price_thb("รุ่นที่ไม่รู้จัก", 1000, 1000, 0) is None)

_before = job("2026-08-10", "2026-08-12 09:00:00")     # ก่อน batch — ราคาเต็ม
_after = job("2026-08-31", "2026-09-01 09:00:00")      # หลัง batch — ครึ่งราคา
trip(_before, "gemini-3.7-flash", 1_000_000, 0)
trip(_after, "gemini-3.7-flash", 1_000_000, 0)
trip(_after, None, 0, 0)                                # ครึ่งล่างที่ยุบเข้าคู่ — ไม่มีการอ่าน

_rows = cost_report.load()
check("อ่านแถวพร้อมสัปดาห์ของงานได้", len(_rows) == 3)
_read = [r for r in _rows if r["model"] and (r["tok_in"] or r["tok_out"])]
check("แถวที่ไม่มี token ไม่ถูกนับเป็นการอ่าน", len(_read) == 2)

_full = cost_report.price_thb("gemini-3.7-flash", 1_000_000, 0, 0)
_paid = {}
for r in _read:
    batch = (r["created_at"] or "")[:10] >= cost_report.BATCH_FROM
    _paid[cost_report.iso_week(r["date_from"])] = _full * (cost_report.BATCH_SHARE if batch else 1.0)
check("สัปดาห์ก่อน batch จ่ายเต็ม", abs(_paid["2026-W33"] - _full) < 0.01)
check("สัปดาห์หลัง batch จ่ายครึ่งเดียว", abs(_paid["2026-W36"] - _full / 2) < 0.01)
check("batch เริ่มนับ 27 ส.ค. (คอมมิต b29eeea)", cost_report.BATCH_FROM == "2026-08-27")

check("รันทั้งสคริปต์แล้วไม่ error", cost_report.main([]) == 0)

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
