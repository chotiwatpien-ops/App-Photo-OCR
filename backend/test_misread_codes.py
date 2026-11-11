# -*- coding: utf-8 -*-
"""One trip under two readings of its booking code (W46, Fiat 2026-11-11).

A slip was screenshotted twice; the reader got its code two ways where Grab wraps it onto a
second line (…TGWTFAV and …TGWWWTFAV), both rows were approved and ฿38 went to the customer
twice. The round now holds such a row for a person instead of approving it, never parks it on
its own, the duplicates tab and the week audit call it counted twice, and settle_doubles takes
an already approved double back to one row."""
import io
import os
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-misread-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import openpyxl                                                 # noqa: E402
from sqlalchemy import insert, select                           # noqa: E402

import config                                                   # noqa: E402
import db                                                       # noqa: E402
import duplicate_report as dr                                   # noqa: E402
import same_trip                                                # noqa: E402
import settle_doubles                                           # noqa: E402
import week_audit                                               # noqa: E402
from drive_client import LocalDrive                             # noqa: E402
from week_phase3 import week_rows                               # noqa: E402

db.init_db()
config.ORDER_ID_FROM = "2026-11-09"
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


SLIP = dict(base_fare=38, net_earnings=38, distance_km=5.23, trip_time="06:07", service_type="Saver Bike",
            pickup_text="โรงแรมยูเนี่ยน ทางเข้าล็อบบี้ Bangkok", dropoff_text="ซอยราชปรารภ 3 ถนนราชปรารภ")
A, B = "A-AWRFU6TGWTFAV", "A-AWRFU6TGWWWTFAV"

check("เลขจองต่างกัน 2 ตัว ค่ารอบและระยะตรง = เที่ยวเดียวกัน (code)",
      same_trip.kind(dict(SLIP, booking_code=A), dict(SLIP, booking_code=B)) == same_trip.CODE)
check("เลขจองต่างกันชัดเจน แต่เส้นทาง ระยะ ยอดตรง = ให้คนดู (route)",
      same_trip.kind(dict(SLIP, booking_code=A), dict(SLIP, booking_code="A-9XQ27RMNBVCXAV")) == same_trip.ROUTE)
check("เลขจองสั้น (เช่น A-VRF00019 กับ A-VRF00020) ไม่นับว่าอ่านเพี้ยน แม้ยอดและระยะตรง",
      same_trip.kind(dict(SLIP, booking_code="A-VRF00019", trip_time="10:19"),
                     dict(SLIP, booking_code="A-VRF00020", trip_time="10:20")) is None)
check("ค่ารอบต่างกัน ไม่ใช่เที่ยวเดียวกัน",
      same_trip.kind(dict(SLIP, booking_code=A), dict(SLIP, booking_code=B, base_fare=40)) is None)
check("เลขจองใกล้กันแต่ระยะต่างกัน และคนละเส้นทาง ไม่ใช่เที่ยวเดียวกัน",
      same_trip.kind(dict(SLIP, booking_code=A), dict(SLIP, booking_code=B, distance_km=7.1, pickup_text="x")) is None)
check("เวลาในสลิปต่างกัน ไม่นับว่าเส้นทางเดียวกัน",
      same_trip.kind(dict(SLIP, booking_code="A-1"), dict(SLIP, booking_code="A-2", trip_time="18:40")) is None)

W = ("2026-11-09", "2026-11-15")
j1 = db.create_job("ศักดิ์ชัย Home", "Trips", *W, category="2 W Saver")
j2 = db.create_job("ธนกร Win", "Trips", *W, category="2 W Saver")


def trip(job, code, **kw):
    with db.engine.begin() as c:
        return c.execute(insert(db.trips).values(
            job_id=job, file_name=f"{job}-{code}.jpg", status="done", committed=0, check_status="pass",
            trip_date="2026-11-13", booking_code=code, **dict(SLIP, **kw))).inserted_primary_key[0]


def row(tid):
    with db.engine.begin() as c:
        return dict(c.execute(select(db.trips).where(db.trips.c.id == tid)).mappings().first())


first = trip(j1, A)
second = trip(j1, B)
st = db.auto_approve_job(j1)
check("❗ สองรูปของเที่ยวเดียวในรอบเดียวกัน: อนุมัติใบแรก ใบที่สองรอคน",
      row(first)["committed"] == 1 and row(second)["committed"] == 0 and st["approved"] == 1, st)
check("ใบที่รอชี้ไปที่ใบแรก และโน้ตบอกเหตุผล",
      row(second)["duplicate_of"] == first and same_trip.SUSPECT in (row(second)["note"] or ""))
db.discard_settled_duplicates(j1)
check("❗ รอบถัดไปไม่ตัดใบนี้ทิ้งเอง (ยอดตรงกันก็ไม่ตัด) — ให้คนตัดสิน", row(second)["status"] == "done")

later = trip(j2, "A-AWRFU6TGWWTFAV")
db.auto_approve_job(j2)
check("❗ ใบที่มาทีหลังในงานของไรเดอร์อีกคน ก็ถูกกันไว้เหมือนกัน",
      row(later)["committed"] == 0 and row(later)["duplicate_of"] == first)

commute = trip(j2, "A-9XQ27RMNBVCXAV")
db.auto_approve_job(j2)
check("เส้นทางเดียวกันแต่เลขจองต่างชัด ก็รอคนดู ไม่อนุมัติเอง", row(commute)["committed"] == 0)
r = db.approve_trip(commute)
check("❗ คนดูแล้วว่าไม่ซ้ำ กดอนุมัติได้", "error" not in r and row(commute)["committed"] == 1, r)

nocode = trip(j2, None)
db.auto_approve_job(j2)
check("❗ สลิปที่ไม่มีเลขจอง แต่เส้นทาง ระยะ ยอดตรงกับเที่ยวที่อนุมัติแล้ว ก็รอคนดู",
      row(nocode)["committed"] == 0 and row(nocode)["duplicate_of"] in (first, commute))
with db.engine.begin() as c:
    c.execute(db.trips.delete().where(db.trips.c.id == nocode))

n, twice, suspect = dr.counted_twice(*W)
check("ผลตรวจหน้างานซ้ำ: ไม่มีอะไรนับสองครั้ง (ใบซ้ำถูกกันไว้ก่อนอนุมัติ)", twice == [] and n == 2, (n, twice))
check("ผลตรวจหน้างานซ้ำ: เส้นทางเดียวกันขึ้นเป็นคำเตือน", suspect == [[first, commute]], suspect)

with db.engine.begin() as c:   # what W46 did before this change: both approved
    c.execute(db.trips.update().where(db.trips.c.id == second).values(committed=1, duplicate_of=None, note=None,
                                                                       customer_image="010613112618.jpg"))
    c.execute(db.trips.update().where(db.trips.c.id == first).values(customer_image="010613112616.jpg"))
    c.execute(db.trips.update().where(db.trips.c.id == commute).values(customer_image="010913112601.jpg"))
n, twice, suspect = dr.counted_twice(*W)
check("❗ ผลตรวจหน้างานซ้ำจับคู่ที่อนุมัติไปแล้วทั้งสองใบได้", twice == [[first, second]], twice)
check("❗ เที่ยวเส้นทางประจำไม่ถูกนับเป็นซ้ำ เป็นแค่คำเตือน", commute not in sum(twice, []) and suspect, suspect)
out = week_audit.audit(week_rows(*W))
check("❗ รายงานตรวจสัปดาห์: ชีทเลขจองอ่านเพี้ยน (บล็อกการปิดสัปดาห์)",
      [[r["id"] for r in g] for g in out["งานซ้ำ-เลขจองอ่านเพี้ยน"]] == [[first, second]],
      out["งานซ้ำ-เลขจองอ่านเพี้ยน"])
import close_week                                               # noqa: E402
check("ชีทนี้อยู่ในรายการที่บล็อกการปิดสัปดาห์", "งานซ้ำ-เลขจองอ่านเพี้ยน" in close_week.BLOCKING)

root = Path(WORK) / "drive"
exports = root / "Exports"
saver = exports / "2026-W46" / "2 W Saver"
saver.mkdir(parents=True)
for name in ("010613112616.jpg", "010613112618.jpg", "010913112601.jpg"):
    (saver / name).write_bytes(b"jpg")
drive = LocalDrive(root)
log = []
settle_doubles.run(drive, str(exports), *W, apply=False, log=log.append)
check("รายงานอย่างเดียว: ไม่แตะอะไร", row(second)["committed"] == 1 and (saver / "010613112618.jpg").exists())
check("รายงานบอกแถวที่จะถอดด้วยเลขแถวและชื่อรูป ไม่มีเลขจองในบันทึก",
      any("010613112618.jpg" in m for m in log) and not any(A in m or B in m for m in log), log)
settle_doubles.run(drive, str(exports), *W, apply=True, log=log.append)
check("❗ ถอดใบที่สอง: เป็น duplicate ของใบแรก ไม่อยู่ในไฟล์",
      row(second)["status"] == "duplicate" and row(second)["committed"] == 0 and row(second)["duplicate_of"] == first)
check("ใบแรกและเที่ยวเส้นทางประจำยังอยู่", row(first)["committed"] == 1 and row(commute)["committed"] == 1)
check("❗ รูปลูกค้าของใบที่ถอดย้ายไป _ซ้ำ ไม่ได้ลบ",
      not (saver / "010613112618.jpg").exists() and (saver / "_ซ้ำ" / "010613112618.jpg").exists())
book = openpyxl.load_workbook(io.BytesIO((exports / "2026-W46" / "Rider Trips 2026-W46 Phase 3.xlsx").read_bytes()))
ws = book[book.sheetnames[0]]
head = [c.value for c in ws[1]]
images = [r[head.index("Image")] for r in ws.iter_rows(min_row=2, values_only=True) if r[0]]
check("❗ ไฟล์ของสัปดาห์เขียนใหม่ เหลือเที่ยวละแถว", sorted(images) == ["010613112616.jpg", "010913112601.jpg"], images)
db.close_week(*W, by="test")
log.clear()
check("สัปดาห์ที่ปิดแล้ว ไม่แตะ", settle_doubles.run(drive, str(exports), *W, apply=True, log=log.append) == 1, log)

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
