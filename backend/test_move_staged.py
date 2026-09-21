# -*- coding: utf-8 -*-
"""Rows read into a full week's _พร้อมอ่าน move to next week's, and the scorecard says what they are.

W38 held 15 Standard Car rows in its waiting room for a week: the car group was full, so they were
never filed, never approved, never pictured — and the round reported them as the car group over
target and as rows with no delivered picture, pointing people at an upload fault (2026-09-21).
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-staged-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from sqlalchemy import insert, select                             # noqa: E402

import db                                                         # noqa: E402
import file_after_read as far                                     # noqa: E402
import move_staged as ms                                          # noqa: E402
from drive_client import LocalDrive                               # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


root = Path(WORK) / "drive"
inbox = root / "inbox"
hold38 = inbox / "Week 14-20 Sep" / "_พร้อมอ่าน"
hold38.mkdir(parents=True)
(inbox / "Week 21-27 Sep" / "4 W Standard").mkdir(parents=True)
drive = LocalDrive(root)

W38, W39 = ("2026-09-14", "2026-09-20"), ("2026-09-21", "2026-09-27")
TARGET = 3
j_car = db.create_job("สมหมาย Taxi", "Trips", *W38, category="4 W Standard")
j_hold = db.create_job(far.HOLDING_RIDER, "Trips", *W38, folder_name="Week 14-20 Sep/_พร้อมอ่าน",
                       drive_folder_id=str(hold38))
ids = {}
with db.engine.begin() as c:
    for i in range(2):   # the car group already holds 2 of its 3
        c.execute(insert(db.trips).values(job_id=j_car, file_name=f"c{i}.jpg", status="done",
                                          committed=1, service_type="Standard Car",
                                          trip_date="2026-09-15", customer_image=f"WK38-สมหมาย Taxi{i + 1}.jpg"))
    staged = (("car_early", "Standard Car", "2026-09-14"), ("car_mid", "Standard Car", "2026-09-17"),
              ("car_late", "Standard Car", "2026-09-19"), ("ev_late", "EV", "2026-09-20"),
              ("saver", "Saver Bike", "2026-09-16"), ("odd", "Scooter Delivery", "2026-09-18"))
    for key, svc, day in staged:
        f = hold38 / f"{key}.jpg"
        f.write_bytes(key.encode())
        tid = c.execute(insert(db.trips).values(job_id=j_hold, file_name=f.name, status="done",
                                                committed=0, service_type=svc, trip_date=day,
                                                note=("เดิมมีโน้ต" if key == "car_late" else None))
                        ).inserted_primary_key[0]
        ids[key] = tid
        c.execute(insert(db.ingested_files).values(drive_id=str(f), name=f.name, job_id=j_hold,
                                                   trip_id=tid, ingested_at="2026-09-21 00:00:00"))

# --- the scorecard ---------------------------------------------------------------------------
card = db.week_scorecard(*W38, target=TARGET)
check("❗ แถวในกองพักไม่ถูกนับว่ากลุ่มรถยนต์เกินเป้า", "Standard Car" not in card["over"])
check("❗ แถวในกองพักไม่ถูกนับว่าไม่มีรูปส่งลูกค้า", card["no_picture"] == 0)
check("แถวในกองพักถูกนับแยกตามประเภทงาน",
      card["staged"] == {"Standard Car": 3, "EV": 1, "Saver Bike": 1, "Scooter Delivery": 1})
check("ยอดที่ลงโฟลเดอร์แล้วยังนับเหมือนเดิม", card["by_service"] == {"Standard Car": 2})

# --- the plan --------------------------------------------------------------------------------
keep, move, room, unknown = ms.plan(*W38, target=TARGET)
check("รถยนต์มีที่ว่าง 1: เก็บคันที่ขับก่อนสุดไว้ในสัปดาห์นี้",
      [r["id"] for r, g in keep if g == "4 W Standard"] == [ids["car_early"]])
check("ที่เหลือ 3 คัน (รวม EV ที่นับเป็นรถยนต์) ย้ายไปสัปดาห์หน้า",
      sorted(r["id"] for r, _g in move) == sorted([ids["car_mid"], ids["car_late"], ids["ev_late"]]))
check("Saver ยังมีที่ว่าง: อยู่ต่อ ไม่ย้าย", any(r["id"] == ids["saver"] for r, _g in keep))
check("ประเภทงานที่ไม่มีกลุ่มรับ: ปล่อยไว้ รายงานแยก", unknown == {"Scooter Delivery": 1})

# --- moving ----------------------------------------------------------------------------------
done, jid = ms.apply(drive, str(inbox), *W38, move, log=lambda *_: None)
with db.engine.begin() as c:
    rows = {r["id"]: dict(r) for r in c.execute(select(db.trips)).mappings().all()}
job = db.get_job(jid)
check("แถวไปอยู่กองพักของสัปดาห์หน้า", job["driver_name"] == far.HOLDING_RIDER
      and (job["date_from"], job["date_to"]) == W39)
check("ย้ายครบ 3 แถว", all(rows[ids[k]]["job_id"] == jid for k in ("car_mid", "car_late", "ev_late")))
check("วันที่อยู่ในสัปดาห์หน้า", all(W39[0] <= rows[ids[k]]["trip_date"] <= W39[1]
                                   for k in ("car_mid", "car_late", "ev_late")))
check("โน้ตเก็บวันที่บนสลิปไว้ และโน้ตเดิมยังอยู่",
      "วันที่บนสลิป 2026-09-19" in rows[ids["car_late"]]["note"]
      and rows[ids["car_late"]]["note"].endswith("เดิมมีโน้ต"))
check("ยังไม่อนุมัติ (รอบหน้าลงที่ให้)", all(rows[ids[k]]["committed"] == 0 for k in ("car_mid", "car_late", "ev_late")))
hold39 = inbox / "Week 21-27 Sep" / "_พร้อมอ่าน"
check("รูปย้ายไปกองพักของสัปดาห์หน้า", sorted(p.name for p in hold39.glob("*.jpg"))
      == ["car_late.jpg", "car_mid.jpg", "ev_late.jpg"])
check("รูปของแถวที่อยู่ต่อยังอยู่ที่เดิม", sorted(p.name for p in hold38.glob("*.jpg"))
      == ["car_early.jpg", "odd.jpg", "saver.jpg"])
check("ไม่มีแถวไหนถูกลบ", len(rows) == 8)
check("ตัวลงที่หลังอ่านของสัปดาห์หน้าเห็น 3 แถวนี้", len(far.staged_rows(*W39)) == 3)
check("รันซ้ำ: ไม่มีอะไรต้องย้ายแล้ว", ms.plan(*W38, target=TARGET)[1] == [])
check("กองพักสัปดาห์หน้ามีอยู่แล้ว: ใช้ job เดิม ไม่เปิดซ้ำ",
      ms.apply(drive, str(inbox), *W38, [], log=lambda *_: None)[1] == jid)

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
