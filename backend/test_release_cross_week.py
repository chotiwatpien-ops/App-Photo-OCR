# -*- coding: utf-8 -*-
"""ลูกค้า 2026-09-14: ซ้ำข้ามสัปดาห์ไม่นับเป็นซ้ำ — ปลดแถว W37 ที่ถูกพักไว้ด้วยกติกาเก่า ฐานข้อมูล SQLite ชั่วคราว"""
import io
import os
import sys
import tempfile
from contextlib import redirect_stdout

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-xweek-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import db                                                       # noqa: E402
import free_dup_seats                                           # noqa: E402
import release_cross_week as rel                                # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


W36, W37 = ("2026-08-31", "2026-09-06"), ("2026-09-07", "2026-09-13")


def trip(job, name, code=None, status="done", committed=0, base=50, when="10:00", **kw):
    with db.engine.begin() as c:
        return c.execute(db.trips.insert().values(
            job_id=job, file_name=name, status=status, committed=committed, booking_code=code,
            base_fare=base, net_earnings=base, trip_time=when, trip_date="2026-09-08",
            check_status="pass", **kw)).inserted_primary_key[0]


old_job = db.create_job("มารือ", "Trips", *W36)
old = trip(old_job, "w36.jpg", code="A" * 20, committed=1)
old_b = trip(old_job, "w36-b.jpg", code="B" * 20, committed=1)
old_short = trip(old_job, "w36-short.jpg", code="A-9SHORT", committed=1, base=80, when="09:15")

a = db.create_job("ฉลองรัฐ", "Trips", *W37)
b = db.create_job("จิรุต", "Trips", *W37)
same = trip(a, "w37-first.jpg", code="C" * 20, committed=1)
x_week = trip(a, "x-week.jpg", code="A" * 20, status="duplicate")               # ต้นฉบับ W36 → ปลด
x_twice = trip(b, "x-week-again.jpg", code="A" * 20, status="duplicate")        # เที่ยวเดียวกันอีกใบใน W37 → ยังซ้ำ
in_week = trip(b, "in-week.jpg", code="C" * 20, status="duplicate")             # ต้นฉบับ W37 → ยังซ้ำ
by_hash = trip(b, "same-bytes.jpg", code="D" * 20, status="duplicate", duplicate_of=old_b)  # ไฟล์เดิม ต้นฉบับ W36 → ปลด
short_ok = trip(b, "short.jpg", code="A-9SHORT", status="duplicate", base=80, when="09:15")  # code สั้น ยอด+เวลาตรง → ปลด
short_diff = trip(b, "short-diff.jpg", code="A-9SHORT", status="duplicate", base=99, when="18:00")  # code สั้น คนละทริป → ไม่มีต้นฉบับ
orphan = trip(b, "orphan.jpg", code="Z" * 20, status="duplicate")               # ไม่มีต้นฉบับเลย

p = rel.plan(*W37)
ids = lambda k: sorted(r["id"] for r in p[k])
check("ปลดเฉพาะแถวที่ต้นฉบับอยู่สัปดาห์อื่น", ids("release") == sorted([x_week, by_hash, short_ok]))
check("ต้นฉบับอยู่สัปดาห์เดียวกัน ยังเป็นซ้ำ", ids("same_week") == [in_week])
check("เที่ยวเดียวกันสองใบใน W37 ปลดแค่ใบแรก", ids("repeat_of_released") == [x_twice])
check("หาต้นฉบับไม่เจอ ไม่แตะ (รวม code สั้นที่ยอด/เวลาไม่ตรง)", ids("no_twin") == sorted([short_diff, orphan]))

buf = io.StringIO()
with redirect_stdout(buf):
    rc = rel.main(["--from", W37[0], "--to", W37[1]])
check("รายงานอย่างเดียวไม่แตะฐานข้อมูล",
      rc == 0 and db.get_trip(x_week)["status"] == "duplicate" and "ปลดได้" in buf.getvalue())

returned = []
free_dup_seats.return_picture = lambda tid, drive=None, log=print: returned.append(tid) or True
with redirect_stdout(io.StringIO()):
    res = rel.apply_plan(p["release"], drive=object())
check("ปลดแล้วกลับเป็นงาน", all(db.get_trip(t)["status"] == "done" for t in (x_week, by_hash, short_ok)))
check("ปลดแล้วอนุมัติเข้าไฟล์ตามปกติ", all(db.get_trip(t)["committed"] == 1 for t in (x_week, by_hash, short_ok))
      and res["approved"] >= 3)
check("บันทึกเหตุผลไว้ในแถว", "ลูกค้า 2026-09-14" in (db.get_trip(x_week)["note"] or ""))
check("เอารูปกลับเข้าโฟลเดอร์ไรเดอร์ทุกใบที่ปลด", sorted(returned) == sorted([x_week, by_hash, short_ok]))
check("แถวที่ยังเป็นซ้ำไม่ถูกแตะ",
      all(db.get_trip(t)["status"] == "duplicate" for t in (x_twice, in_week, short_diff, orphan)))
check("ต้นฉบับของสัปดาห์ก่อนยังอยู่ครบ", db.get_trip(old)["committed"] == 1)

db.close_week(W37[0], "test") if hasattr(db, "close_week") else None
with redirect_stdout(io.StringIO()):
    check("สัปดาห์ที่ปิดแล้ว ไม่ยอมปลด", rel.main(["--from", W37[0], "--to", W37[1], "--apply"]) == 1)

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
