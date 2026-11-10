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
    {"id": 1, "trip_date": "2026-11-30", "trip_time": "14:05", "customer_image": None},
    {"id": 2, "trip_date": "2026-11-30", "trip_time": "08:30", "customer_image": None},
    {"id": 3, "trip_date": "2026-12-01", "trip_time": "09:00", "customer_image": None},
    {"id": 5, "trip_date": None, "trip_time": "10:00", "customer_image": None},
    {"id": 6, "trip_date": "2026-11-30", "trip_time": None, "customer_image": None},
]
got = order_id.assign(rows, ids["ตฤณ Win"], [])
check("ตรงตามตัวอย่างลูกค้า: 0001 + 301126 + 01", got[2] == "000130112601.jpg", got)
check("ลำดับนับตามเวลาในสลิปของวันนั้น", got[1] == "000130112602.jpg")
check("เที่ยวที่ไม่มีเวลาเรียงท้ายของวัน", got[6] == "000130112603.jpg")
check("วันใหม่เริ่มนับ 01 ใหม่", got[3] == "000101122601.jpg")
check("เที่ยวที่ไม่มีวันที่: ไม่ได้ชื่อ Order ID", 5 not in got)
check("อ่าน Order ID กลับจากชื่อรูปได้", order_id.of_picture("000130112601.jpg") == "000130112601")
check("ชื่อแบบเดิมไม่ใช่ Order ID", order_id.of_picture("WK46-ตฤณ Win1.jpg") is None)

kept = [dict(r, customer_image=got[r["id"]]) for r in rows if r["id"] in got]
late = {"id": 7, "trip_date": "2026-11-30", "trip_time": "07:00", "customer_image": None}
again = order_id.assign(kept + [late], "0001", list(got.values()))
check("ชื่อที่ให้ไปแล้วคงเดิม ไม่เลื่อนเลขเมื่อมีเที่ยวมาเพิ่ม",
      all(again[r["id"]] == got[r["id"]] for r in kept), again)
check("เที่ยวที่มาทีหลังได้เลขถัดไปของวันนั้น แม้เวลาจะเช้ากว่า", again[7] == "000130112604.jpg", again.get(7))
moved = dict(kept[0], trip_date="2026-12-02")
check("เที่ยวที่ถูกเลื่อนวัน (ยกงาน) ได้ชื่อใหม่ตามวันใหม่",
      order_id.assign([moved], "0001", [])[moved["id"]] == "000102122601.jpg")
check("เลขของไรเดอร์คนอื่นในสัปดาห์ไม่กันเลขของเรา",
      order_id.assign([late], "0001", ["000230112601.jpg"])[7] == "000130112601.jpg")

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
