# -*- coding: utf-8 -*-
"""Rows filed under a week are dated inside it, spread across its days in driven order; the
slip's own day survives in the note (Fiat, 2026-09-10 evening).

A throwaway SQLite stands in for the database: a W37 job holding six rows carried from W36 and
one row really driven in W37.
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-redate-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from sqlalchemy import insert, select                            # noqa: E402

import db                                                        # noqa: E402
import redate_to_week as rd                                      # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


N_FROM, N_TO = "2026-09-07", "2026-09-13"
check("สัปดาห์มี 7 วัน จันทร์ถึงอาทิตย์", rd.week_days(N_FROM, N_TO) == [f"2026-09-{d:02d}" for d in range(7, 14)])

# --- the dealing rule on its own -------------------------------------------------------------------------
rows = [{"id": i, "trip_date": d, "trip_time": t} for i, (d, t) in enumerate(
    [("2026-09-06", "20:00"), ("2026-09-04", "09:00"), ("2026-09-05", "12:00"),
     ("2026-09-06", "08:00"), ("2026-09-04", "18:00"), ("2026-09-05", "23:00"), ("2026-09-06", "21:00")], 1)]
plan = rd.spread(rows, N_FROM, N_TO)
check("7 แถวลง 7 วัน วันละหนึ่ง", sorted(new for _r, new in plan) == rd.week_days(N_FROM, N_TO))
order = [r["id"] for r, _new in plan]
check("เรียงตามเวลาที่ขับจริง (วัน แล้วเวลา) ก่อนแจก", order == [2, 5, 3, 6, 4, 1, 7])
check("แถวที่ขับก่อนได้วันต้นสัปดาห์ แถวที่ขับหลังได้วันท้าย",
      plan[0][1] == "2026-09-07" and plan[-1][1] == "2026-09-13")
plan14 = rd.spread(rows + [dict(r, id=r["id"] + 10) for r in rows], N_FROM, N_TO)
from collections import Counter                                  # noqa: E402
check("14 แถวลงวันละ 2 เท่ากันทุกวัน", set(Counter(new for _r, new in plan14).values()) == {2})
plan3 = rd.spread(rows[:3], N_FROM, N_TO)
check("3 แถวก็ยังกระจายทั่วสัปดาห์ ไม่กองวันเดียว", len({new for _r, new in plan3}) == 3)

# --- against the database --------------------------------------------------------------------------------
j = db.create_job("สมชาย Win", "Trips", N_FROM, N_TO, category="2 W Saver")
j36 = db.create_job("สมชาย Win", "Trips", "2026-08-31", "2026-09-06", category="2 W Saver")
with db.engine.begin() as c:
    for i, (d, t) in enumerate([("2026-09-06", "20:00"), ("2026-09-04", "09:00"), ("2026-09-05", "12:00"),
                                ("2026-09-06", "08:00"), ("2026-09-04", "18:00"), ("2026-09-05", "23:00")], 1):
        c.execute(insert(db.trips).values(job_id=j, file_name=f"c{i}.jpg", status="done", committed=1,
                                          trip_date=d, trip_time=t, net_earnings=10 * i, note="ยกมา"))
    c.execute(insert(db.trips).values(job_id=j, file_name="real.jpg", status="done", committed=1,
                                      trip_date="2026-09-08", trip_time="10:00"))
    c.execute(insert(db.trips).values(job_id=j, file_name="void.jpg", status="voided", committed=0,
                                      trip_date="2026-09-01"))
    c.execute(insert(db.trips).values(job_id=j36, file_name="w36.jpg", status="done", committed=1,
                                      trip_date="2026-09-06"))
rows, jobs = rd.out_of_week_rows(N_FROM, N_TO)
check("เจอเฉพาะ 6 แถวที่วันที่อยู่นอกสัปดาห์ (ไม่นับแถวจริงของ W37, แถว voided, แถวของ W36)",
      sorted(r["file_name"] for r in rows) == [f"c{i}.jpg" for i in range(1, 7)])
n = rd.apply(rd.spread(rows, N_FROM, N_TO), N_FROM, N_TO, log=lambda *a: None)
check("ลงวันที่ใหม่ 6 แถว", n == 6)
with db.engine.begin() as c:
    got = {r["file_name"]: dict(r) for r in c.execute(
        select(db.trips.c.file_name, db.trips.c.trip_date, db.trips.c.trip_time, db.trips.c.note,
               db.trips.c.net_earnings)).mappings().all()}
check("ทุกแถวที่ยกมาอยู่ใน 7-13 ก.ย. แล้ว", all(N_FROM <= got[f"c{i}.jpg"]["trip_date"] <= N_TO for i in range(1, 7)))
check("6 แถวลง 6 วันติดกัน: แถวแรกที่ขับ (4 ก.ย. 09:00) ได้จันทร์ 7 · แถวสุดท้าย (6 ก.ย. 20:00) ได้เสาร์ 12",
      got["c2.jpg"]["trip_date"] == "2026-09-07" and got["c1.jpg"]["trip_date"] == "2026-09-12")
check("เวลา ยอดเงิน ไม่ถูกแตะ", got["c2.jpg"]["trip_time"] == "09:00" and got["c2.jpg"]["net_earnings"] == 20)
check("วันที่บนสลิปเก็บไว้ในโน้ต ต่อท้ายโน้ตเดิม",
      "วันที่บนสลิป 2026-09-04" in got["c2.jpg"]["note"] and got["c2.jpg"]["note"].endswith("| ยกมา"))
check("แถวจริงของ W37 และแถว W36 ไม่ถูกแตะ",
      got["real.jpg"]["trip_date"] == "2026-09-08" and got["w36.jpg"]["trip_date"] == "2026-09-06")
again, _ = rd.out_of_week_rows(N_FROM, N_TO)
check("รันซ้ำไม่มีอะไรต้องทำ", again == [])

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
