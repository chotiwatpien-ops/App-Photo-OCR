# -*- coding: utf-8 -*-
"""รถยนต์มีสินค้าเดียว: แถวที่อ่านได้ว่า Saver Car ต้องกลายเป็น Standard Car (Ops 2026-09-16)"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-carlabel-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from sqlalchemy import insert, select                            # noqa: E402

import db                                                        # noqa: E402
import pipeline                                                  # noqa: E402
import relabel_car_service as rc                                 # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


# --- the reader: every car is the Standard car from here on ------------------------------------
ns = pipeline.normalize_service
check("ชิป Saver บนสลิปรถยนต์ → Standard Car", ns("Saver Car", "4 W Standard")[0] == "Standard Car")
check("ชิป Saver รถยนต์ แต่ job อยู่กลุ่มมอเตอร์ไซค์ → ยังเป็น Standard Car",
      ns("Saver Car", "2 W Saver")[0] == "Standard Car")
check("ไม่มีกลุ่มให้เทียบ ก็ยังเป็น Standard Car", ns("Saver Car", None)[0] == "Standard Car")
check("JustGrab (รถยนต์) → Standard Car", ns("Standard (JustGrab)", "4 W Standard")[0] == "Standard Car")
check("มอเตอร์ไซค์ไม่ถูกแตะ: Saver Bike ยังเป็น Saver Bike", ns("Saver Bike", "2 W Standard")[0] == "Saver Bike")
check("Standard Car ที่ถูกอยู่แล้ว ไม่มีโน้ตกวน", ns("Standard Car", "4 W Standard") == ("Standard Car", None))

# --- the rows read before the rule ---------------------------------------------------------------
D_FROM, D_TO = "2026-09-07", "2026-09-13"
j_car = db.create_job("สมหมาย Taxi", "Trips", D_FROM, D_TO, category="4 W Standard")
j_bike = db.create_job("สมชาย Win", "Trips", D_FROM, D_TO, category="2 W Saver")
with db.engine.begin() as c:
    for n, jid, svc, st in ((1, j_car, "Saver Car", "done"), (2, j_car, "Standard Car", "done"),
                            (3, j_car, "Saver Car", "duplicate"), (4, j_bike, "Saver Bike", "done"),
                            (5, j_car, "Saver Car", "done")):
        c.execute(insert(db.trips).values(job_id=jid, file_name=f"{n}.jpg", status=st,
                                          service_type=svc, trip_date="2026-09-09", committed=1,
                                          note=("เดิมมีโน้ต" if n == 1 else None)))

pairs = rc.rows_to_relabel(D_FROM, D_TO)
check("เลือกเฉพาะแถวรถยนต์ที่ยังไม่ใช่ Standard Car และต้องเป็นแถวที่ลงไฟล์แล้ว",
      sorted(r["file_name"] for r, _j in pairs) == ["1.jpg", "5.jpg"])

n = rc.apply(pairs)
with db.engine.begin() as c:
    now = {r["file_name"]: dict(r) for r in c.execute(
        select(db.trips.c.file_name, db.trips.c.service_type, db.trips.c.note)).mappings().all()}
check("เปลี่ยนแล้ว 2 แถว", n == 2)
check("Saver Car → Standard Car", now["1.jpg"]["service_type"] == "Standard Car"
      and now["5.jpg"]["service_type"] == "Standard Car")
check("มอเตอร์ไซค์กับแถวที่พักไว้ไม่ถูกแตะ",
      now["4.jpg"]["service_type"] == "Saver Bike" and now["3.jpg"]["service_type"] == "Saver Car")
check("โน้ตบอกว่าเดิมเขียนว่าอะไร และโน้ตเดิมยังอยู่",
      now["1.jpg"]["note"].startswith("ประเภทงาน Saver Car → Standard Car")
      and now["1.jpg"]["note"].endswith("เดิมมีโน้ต"))
check("รันซ้ำ ไม่มีอะไรให้เปลี่ยนแล้ว", rc.rows_to_relabel(D_FROM, D_TO) == [])

# --- EV และ Women driver นับเป็น Standard Car (เฟียส 2026-09-21) -------------------------------------
# W38 มี EV 6 แถวกับ Women driver 2 แถวที่ไม่มีกลุ่มไหนรับ ค้างในกองพัก _พร้อมอ่าน ทั้งสัปดาห์
check("ชิป EV → Standard Car", ns("EV", None)[0] == "Standard Car")
check("ชิป 'Standard | Women driver' → Standard Car", ns("Standard | Women driver", None)[0] == "Standard Car")
check("ชิป 'Standard Women driver' → Standard Car", ns("Standard Women driver", None)[0] == "Standard Car")
check("EV ในโฟลเดอร์รถยนต์ → Standard Car", ns("EV", "4 W Standard")[0] == "Standard Car")
check("❗ มอเตอร์ไซค์ที่มีคำ EV / Women ไม่ถูกเปลี่ยนเป็นรถยนต์",
      pipeline.car_is_standard("GrabBike EV") == "GrabBike EV"
      and pipeline.car_is_standard("Women Bike") == "Women Bike")
check("❗ คำที่มี ev อยู่ข้างในไม่นับ (Seven, Every)",
      pipeline.car_is_standard("Seven") == "Seven" and pipeline.car_is_standard("Every") == "Every")

D2_FROM, D2_TO = "2026-09-14", "2026-09-20"
j_hold = db.create_job("(รออ่าน)", "Trips", D2_FROM, D2_TO)
with db.engine.begin() as c:
    for n, svc in ((11, "EV"), (12, "Standard | Women driver"), (13, "Standard Women driver"),
                   (14, "Saver Bike"), (15, "Standard Car")):
        c.execute(insert(db.trips).values(job_id=j_hold, file_name=f"{n}.jpg", status="done",
                                          service_type=svc, trip_date="2026-09-15", committed=0))
pairs = rc.rows_to_relabel(D2_FROM, D2_TO)
check("W38: เลือก EV + Women driver ทั้ง 3 แถว (รวมแถวในกองพักที่ยังไม่อนุมัติ) ไม่แตะ Saver Bike",
      sorted(r["file_name"] for r, _j in pairs) == ["11.jpg", "12.jpg", "13.jpg"])
rc.apply(pairs)
with db.engine.begin() as c:
    now = {r["file_name"]: dict(r) for r in c.execute(
        select(db.trips.c.file_name, db.trips.c.service_type, db.trips.c.note)
        .where(db.trips.c.job_id == j_hold)).mappings().all()}
check("EV / Women driver กลายเป็น Standard Car",
      all(now[f]["service_type"] == "Standard Car" for f in ("11.jpg", "12.jpg", "13.jpg")))
check("โน้ตบอกว่าเดิมเป็น EV", now["11.jpg"]["note"].startswith("ประเภทงาน EV → Standard Car"))

import file_after_read as far                                     # noqa: E402
check("ตัวลงที่หลังอ่านรู้จัก EV แม้ยังไม่ได้เปลี่ยนป้าย: ไปกลุ่ม 4 W Standard",
      far.GROUP_OF.get(pipeline.car_is_standard("EV")) == "4 W Standard")

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
