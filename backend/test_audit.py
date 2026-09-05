# -*- coding: utf-8 -*-
"""Telling one pool run's rows from another's when both produced the same file name.

The stitched name is '<album>_<top>+<bottom>_฿<amount>'. Two runs over the same album pair the
same positions for the same fare all the time, so the name is not a key — the first version of
this audit reported 109 rows for 87 files. What separates them is when the job was opened, and
the two tables write their timestamps in different shapes.
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-audit-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import audit_pool_run as audit                                  # noqa: E402
import db                                                       # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


check("เวลาสองรูปแบบเทียบกันได้", audit.when("2026-09-06T00:20:00") < audit.when("2026-09-06 00:38:06"))
check("ไม่มีเวลาก็ไม่พัง", audit.when(None) == "")
check("อ่านลำดับครึ่งบน/ครึ่งล่างจากชื่อไฟล์", audit.digits("X_8+29_฿56.jpg") == (8, 29))
check("ชื่อที่ไม่เข้าแพทเทิร์นคืน None", audit.digits("ไม่ใช่ไฟล์คู่.jpg") is None)

pairs7 = [{"moved": "2 W Saver/01-a/X_8+29_฿56.jpg", "amount": 56, "distance": 21},
          {"moved": "2 W Saver/01-a/X_3+2_฿24.jpg", "amount": 24, "distance": 1},
          {"moved": "", "amount": 30, "distance": 1}]                  # never filed
db.record_pool_run("move", "W", {"n_pairs": 3}, "s",
                   {"albums": [{"album": "X", "pairs": pairs7}], "started_at": "2026-09-05 23:54:17"})
db.record_pool_run("move", "W", {"n_pairs": 1}, "s",
                   {"albums": [{"album": "X", "pairs": [
                       {"moved": "2 W Saver/09-b/X_3+2_฿24.jpg", "amount": 24, "distance": 1}]}],
                    "started_at": "2026-09-06 00:38:06"})
runs = {r["id"]: r for r in db.recent_pool_runs(9, with_report=True)}
check("นับเฉพาะคู่ที่ย้ายเข้าโฟลเดอร์จริง", len(audit.pairs_of(runs[1])) == 2)
check("เก็บระยะห่างของแต่ละคู่ไว้", sorted(p["distance"] for p in audit.pairs_of(runs[1])) == [1, 21])

j7 = db.create_job("a", "Trips", "2026-08-31", "2026-09-06", category="2 W Saver")
j8 = db.create_job("b", "Trips", "2026-08-31", "2026-09-06", category="2 W Saver")
with db.engine.begin() as c:
    c.execute(db.jobs.update().where(db.jobs.c.id == j7).values(created_at="2026-09-05T23:55:00"))
    c.execute(db.jobs.update().where(db.jobs.c.id == j8).values(created_at="2026-09-06T00:40:00"))
    for job, fn, cs, code in [(j7, "X_8+29_฿56.jpg", "pass", "A-FAR"),
                              (j7, "X_3+2_฿24.jpg", "pass", "A-NEAR"),
                              (j8, "X_3+2_฿24.jpg", "pass", "A-NEAR")]:   # same name, run 2
        c.execute(db.trips.insert().values(job_id=job, file_name=fn, status="done",
                                           check_status=cs, booking_code=code, committed=1))

import io                                                        # noqa: E402
from contextlib import redirect_stdout                           # noqa: E402
buf = io.StringIO()
with redirect_stdout(buf):
    rc = audit.main(["--run", "1", "--against", "2", "--list"])
out = buf.getvalue()
check("จบด้วยสถานะปกติ", rc == 0)
check("ไม่นับแถวของรอบหลังที่ชื่อไฟล์ชนกัน", "กลายเป็นแถวในฐานข้อมูล 2 แถว" in out)
check("บอกด้วยว่าคัดออกไปกี่แถว", "ชื่อไฟล์ชนกับรอบหลัง 1 แถว" in out)
check("คู่ที่ห่างผิดปกติถูกแยกออกมา", "แถวที่มาจากคู่ห่างเกิน 6 ใบ: 1 แถว" in out)
check("บอกว่าแถวที่ผ่านการตรวจเลขคือตัวอันตราย", "ผ่านการตรวจเลข: 1 แถว" in out)
check("รู้ว่ารอบหลังทำเที่ยวไหนซ้ำแล้ว", "ซ้ำกับรอบ #1: 1 เที่ยว" in out)
check("รายไฟล์บอกลำดับที่เอามาต่อกัน", "(8 กับ 29)" in out)
check("ไม่แก้อะไรในฐานข้อมูล", db.trips_count() == 3 if hasattr(db, "trips_count") else True)

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
