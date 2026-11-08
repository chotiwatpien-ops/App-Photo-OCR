# -*- coding: utf-8 -*-
"""Driver ID from Ops' name list and the Order ID built from it (requirement 2026-11-08)."""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-ids-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import openpyxl                                                 # noqa: E402

import db                                                       # noqa: E402
import order_id                                                 # noqa: E402
import roster                                                   # noqa: E402

db.init_db()
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


# --- Ops' list with a Driver ID column ------------------------------------------------------
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "2 W (Win)"
ws.append(["ชื่อ", "Driver ID"])
ws.append(["ตฤณ", 1])                 # a number in Excel
ws.append(["สมชาย", "0002"])
ws.append(["มานี", None])             # no id
t = wb.create_sheet("4 W Taxi")
t.append(["ชื่อ", "Driver ID"])
t.append(["ตฤณ", "0003"])             # same name, another kind: another person
t.append(["ปิติ", "0002"])            # an id already given to สมชาย Win
path = os.path.join(WORK, "names.xlsx")
wb.save(path)

logged = []
roster.log = logged.append
roster.import_pool(path)
ids = db.driver_ids()
check("อ่านคอลัมน์ Driver ID และเติม 0 ให้ครบ 4 หลัก", ids.get("ตฤณ Win") == "0001", ids)
check("ชื่อเดียวกันคนละชนิดได้รหัสคนละตัว", ids.get("ตฤณ Taxi") == "0003")
check("ชื่อที่ไม่มีรหัสไม่อยู่ในตารางรหัส", "มานี Win" not in ids)
check("เตือนชื่อที่ไม่มีรหัส", any("มานี Win: ไม่มีรหัส" in m for m in logged), logged)
check("เตือนรหัสซ้ำสองคน", any("0002 ซ้ำกัน" in m for m in logged), logged)
check("รายชื่อที่ยังไม่มีคอลัมน์รหัส ไม่เตือนอะไร", roster.check_driver_ids([("ก", "2W", "Win", None)]) == [])
check("รหัสที่ไม่ใช่ตัวเลข 4 หลักถูกเตือน",
      any("ไม่ใช่ตัวเลข 4 หลัก" in m for m in roster.check_driver_ids([("ก", "2W", "Win", "12345")])))

# --- Order ID -------------------------------------------------------------------------------
rows = [
    {"id": 1, "driver_name": "ตฤณ Win", "trip_date": "2026-11-30", "trip_time": "14:05"},
    {"id": 2, "driver_name": "ตฤณ Win", "trip_date": "2026-11-30", "trip_time": "08:30"},
    {"id": 3, "driver_name": "ตฤณ Win", "trip_date": "2026-12-01", "trip_time": "09:00"},
    {"id": 4, "driver_name": "มานี Win", "trip_date": "2026-11-30", "trip_time": "10:00"},
    {"id": 5, "driver_name": "ตฤณ Win", "trip_date": None, "trip_time": "10:00"},
    {"id": 6, "driver_name": "ตฤณ Win", "trip_date": "2026-11-30", "trip_time": None},
]
got = order_id.order_ids(rows, ids)
check("ตรงตามตัวอย่างลูกค้า: 0001 + 301126 + 01", got[2] == "000130112601", got)
check("ลำดับนับตามเวลาในสลิปของวันนั้น", got[1] == "000130112602")
check("เที่ยวที่ไม่มีเวลาเรียงท้ายของวัน", got[6] == "000130112603")
check("วันใหม่เริ่มนับ 01 ใหม่", got[3] == "000101122601")
check("ไรเดอร์ที่ไม่มีรหัส: ไม่สร้าง Order ID", got[4] is None)
check("เที่ยวที่ไม่มีวันที่: ไม่สร้าง Order ID", got[5] is None)
check("ยาว 12 หลักทุกตัว", all(v is None or (len(v) == 12 and v.isdigit()) for v in got.values()))

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
