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

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
