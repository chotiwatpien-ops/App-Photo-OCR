# -*- coding: utf-8 -*-
"""The four ways one booking code was counted twice or lost, found by model-checking the duplicate
guard (.claude/skills/verify-duplicate-guard, 2026-10-31). Each is the shortest sequence it found.

    G1  two waiting copies approved together (อนุมัติทุกแถวที่ตัวเลขผ่าน; the round after a void)
    G2  the อนุมัติ button checked the same rider only
    G3  the close carried a code that next week already bills
    G4  voiding the live copy left its parked copy parked: billed nowhere
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-test-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")
import db                                                    # noqa: E402
from sqlalchemy import select                                # noqa: E402

db.init_db()
W, N = ("2026-10-05", "2026-10-11"), ("2026-10-12", "2026-10-18")
CODE, OTHER = "A-8KQ2WXYZ7T3M9", "A-5RD7HUVB2N4P6"
ok = True


def check(label, cond):
    global ok
    print(("✅ " if cond else "✗ ") + label)
    ok = ok and cond


def job(rider, week):
    return db.create_job(rider, "Trips", *week, category="2 W Saver")


def slip(jid, code, amount=62.0, week=W):
    """A full slip whose numbers balance, as a read leaves it (status done, waiting)."""
    tid = db.create_trip(jid, f"s{code[-4:]}-{jid}-{amount:g}.jpg", b"x", "image/jpeg")
    db.update_trip(tid, {"status": "done", "kind": "full", "booking_code": code, "net_earnings": amount,
                         "base_fare": amount, "check_status": "pass", "trip_date": week[0],
                         "trip_time": "10:00", "service_type": "Saver Bike"})
    return tid


def counted(code, week):
    t, j = db.trips.c, db.jobs.c
    with db.engine.begin() as c:
        return c.execute(select(t.id).select_from(db.trips.join(db.jobs, j.id == t.job_id))
                         .where(t.booking_code == code, t.status == "done", t.committed == 1,
                                j.date_from == week[0], j.date_to == week[1])).all().__len__()


def status(tid):
    with db.engine.begin() as c:
        return c.execute(select(db.trips.c.status, db.trips.c.committed).where(db.trips.c.id == tid)).first()


def reset():
    with db.engine.begin() as c:
        for t in reversed(db.meta.sorted_tables):
            c.execute(t.delete())


# G1 — approve-all: riders A and B each hold a waiting copy of one code
reset()
a, b = job("A", W), job("B", W)
slip(a, CODE)
slip(b, CODE)
import main                                                  # noqa: E402
main.approve_passing()
check("G1 อนุมัติทุกแถวที่ผ่าน: สำเนาสองใบในคิวพร้อมกัน นับครั้งเดียว", counted(CODE, W) == 1)

# G1 — the round after a void frees two copies in one job
reset()
a = job("A", W)
first = slip(a, CODE)
for _ in range(2):
    tid = slip(a, CODE)
    db.update_trip(tid, {"duplicate_of": first})
db.void_trips([first], "จับคู่ผิด")
db.auto_approve_job(a)
check("G1 รอบ ingest หลัง void: สำเนาที่ถูกปลดสองใบ นับครั้งเดียว", counted(CODE, W) == 1)

# G2 — the round approved rider B's copy; a person presses อนุมัติ on rider A's
reset()
a, b = job("A", W), job("B", W)
ra = slip(a, CODE)
slip(b, CODE)
db.auto_approve_job(b)
r = db.approve_trip(ra)
check("G2 ปุ่มอนุมัติ: รหัสที่ไรเดอร์อีกคนอนุมัติแล้วในสัปดาห์เดียวกัน ถูกกันไว้",
      "error" in r and counted(CODE, W) == 1)

# G3 — next week already bills OTHER; this week is over target with CODE and OTHER
reset()
a, an = job("A", W), job("A", N)
slip(a, CODE)
late = slip(a, OTHER)
db.update_trip(late, {"trip_date": W[1]})
nx = slip(an, OTHER, week=N)
for tid in (late, nx):
    db.approve_trip(tid)
db.auto_approve_job(a)
import carry_excess                                          # noqa: E402
excess, counts, _ = carry_excess.excess_rows(*W, target=1)
picked = [r["booking_code"] for r, _j in excess.get("2 W Saver", [])]
check("G3 ปิดสัปดาห์: ไม่ยกรหัสที่สัปดาห์หน้านับแล้ว แต่ยกแถวถัดไปแทน", picked == [CODE])

# G4 — the round approved one copy and parked the other; the approved one is voided
reset()
a = job("A", W)
keep = slip(a, CODE)
db.auto_approve_job(a)
copy_ = slip(a, CODE)
db.auto_approve_job(a)
check("   (ก่อน void: สำเนาถูกพักเป็นงานซ้ำ)", status(copy_)[0] == "duplicate")
db.void_trips([keep], "จับคู่ผิด")
check("G4 void ต้นฉบับ: สำเนาที่ถูกพักกลับเข้าคิว ไม่หายไปเฉยๆ", tuple(status(copy_)) == ("done", 0))

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
