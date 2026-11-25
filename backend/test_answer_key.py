# -*- coding: utf-8 -*-
"""ชุดเฉลย (Fiat 2026-11-25). Almost every row is approved with nobody looking and nobody edits a
field, so nothing said how often the reader is right. A person now checks a random sample of
auto-approved rows against the slip picture; what the picture prints is stored beside the trip,
never on it, and the accuracy of each field is counted from that."""
import os
import re
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-key-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from sqlalchemy import inspect                                  # noqa: E402

import answer_key as key                                        # noqa: E402
import db                                                       # noqa: E402

db.init_db()
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and bool(cond)


def refused(field, value):
    try:
        key.FIELD[field].canon(value)
    except ValueError:
        return True
    return False


F = key.FIELD
check("ช่องที่ตรวจมี 8 ช่อง เรียงตามที่ตาเจอบนสลิป",
      [f.key for f in key.FIELDS] == ["trip_time", "booking_code", "distance_km", "service_type",
                                      "payment_method", "net_earnings", "base_fare", "turbo"])
check("ทุกช่องเป็นคอลัมน์ของ trips", all(f.key in db.trips.c for f in key.FIELDS))
check("เวลา เขียนแบบเดียวเสมอ", F["trip_time"].canon("8:38") == "08:38" and F["trip_time"].canon(" 08:38 ") == "08:38")
check("เวลาที่เป็นไปไม่ได้ ไม่รับ", refused("trip_time", "25:00") and refused("trip_time", "เช้า"))
check("รหัสการจอง ตัวใหญ่ ไม่มีช่องว่าง", F["booking_code"].canon(" a-te stke y000 1av ") == "A-TESTKEY0001AV")
check("ตัวเลข เขียนทศนิยม 2 ตำแหน่ง",
      [F["net_earnings"].canon(v) for v in (47, "47", "47.0", " 1,047.5 ")] == ["47.00", "47.00", "47.00", "1047.50"])
check("0 เป็นค่า ไม่ใช่ช่องว่าง", F["turbo"].canon(0) == "0.00" and F["turbo"].canon("0") == "0.00")
check("ตัวเลขที่ไม่ใช่ตัวเลข ไม่รับ", refused("base_fare", "แปดสิบ") and refused("base_fare", "nan"))
check("รถยนต์ทุกแบบคือ Standard Car",
      [F["service_type"].canon(v) for v in ("Saver Car", "Standard Taxi", "Saver Bike")]
      == ["Standard Car", "Standard Car", "Saver Bike"])
check("ประเภทบริการนอกรายการ ไม่รับ", refused("service_type", "Rocket"))
check("การจ่ายเงินนอกรายการ ไม่รับ", refused("payment_method", "Cash") and F["payment_method"].canon("QR PAY") == "QR PAY")
check("ค่าว่างและ UNKNOWN คือไม่มีค่า",
      [F[k].canon(v) for k, v in (("trip_time", None), ("booking_code", "  "), ("turbo", ""),
                                  ("payment_method", "UNKNOWN"), ("service_type", None))] == [None] * 5)
check("หน้าเว็บได้ป้าย ชนิด ตัวเลือก และคำแนะนำจากที่เดียว",
      F["service_type"].public() == {"key": "service_type", "label": "ประเภทบริการ", "kind": "choice",
                                     "hint": "ชิปใต้แผนที่ · รถยนต์ทุกแบบ = Standard Car",
                                     "options": ["Saver Bike", "Standard Bike", "Standard Car"]})


def fact(field, truth, trip=1):
    return key.KeyFact(trip, field, truth)


got = key.tally([
    (fact("booking_code", "A-TESTKEY0001AV"), "A-TESTKEY0001AV"),
    (fact("booking_code", "A-TESTKEY0002AV"), "A-TESTKEY0002"),
    (fact("booking_code", "A-TESTKEY0003AV"), None),
    (fact("booking_code", None), None),
    (fact("booking_code", None), "A-TESTKEY0004"),
    (fact("turbo", "0.00"), "0.00"),
])
code = got["booking_code"]
check("นับ ถูก ผิด และไม่มีในรูป แยกกัน",
      (code.right, code.wrong, code.absent_blank, code.absent_filled) == (1, 2, 1, 1), code)
check("❗ แถวว่างทั้งที่รูปมี นับเป็นผิด และบอกได้ว่า AI เว้นว่าง", code.missed == 1, code)
check("❗ ความแม่นยำ = ถูก ÷ (ถูก + ผิด) สิ่งที่ไม่มีในรูปไม่อยู่ในตัวหาร", abs(code.rate - 1 / 3) < 1e-9, code.rate)
check("ทุกช่องมีผลนับ แม้ยังไม่มีใครตรวจ", set(got) == set(F) and got["trip_time"] == key.Tally())
check("ช่องที่ยังไม่ได้ตรวจ ไม่มีความแม่นยำ", key.Tally().rate is None and key.Tally().interval() is None)

low, high = key.Tally(right=104, wrong=4).interval()
check("ช่วง 95% ของ 104 จาก 108 คือ 90.9–98.6", abs(low - 0.9086) < 0.001 and abs(high - 0.9855) < 0.001, (low, high))
low, high = key.Tally(right=120).interval()
check("❗ ถูก 120 จาก 120 ไม่ได้แปลว่า 100%: ปลายล่างราว 96.9%", abs(low - 0.969) < 0.001 and high > 0.9999, (low, high))
low, high = key.Tally(wrong=5).interval()
check("ผิดหมด ปลายล่างเป็น 0", low == 0.0 and 0.4 < high < 0.5, (low, high))
shown = key.Tally(right=3, wrong=1, missed=1, absent_filled=2).public()
check("ผลนับที่ส่งให้หน้าเว็บ มีครบทุกตัว",
      {k: shown[k] for k in ("right", "wrong", "missed", "absent_blank", "absent_filled", "rate")}
      == {"right": 3, "wrong": 1, "missed": 1, "absent_blank": 0, "absent_filled": 2, "rate": 0.75}
      and shown["low"] < 0.75 < shown["high"], shown)

ids = list(range(1, 2001))
order = sorted(ids, key=key.rank)
check("ลำดับการตรวจไม่ใช่ลำดับเลขแถว", order[:50] != ids[:50] and sorted(order) == ids)
check("ลำดับเดิมทุกครั้งที่ถาม", order == sorted(ids, key=key.rank))
late = sorted(ids + [5000, 5001], key=key.rank)
check("แถวที่มาทีหลัง ไม่เปลี่ยนลำดับของแถวเดิม", [i for i in late if i <= 2000] == order)
first = order[:200]
check("ใบแรก ๆ กระจายทั่วทั้งสัปดาห์ ไม่กองอยู่ช่วงเดียว",
      all(40 <= sum(lo < i <= lo + 500 for i in first) <= 60 for lo in (0, 500, 1000, 1500)),
      [sum(lo < i <= lo + 500 for i in first) for lo in (0, 500, 1000, 1500)])

tables = inspect(db.engine).get_table_names()
check("ตารางชุดเฉลยถูกสร้างพร้อมฐานข้อมูล", {"key_facts", "key_slips"} <= set(tables), tables)

SOURCE = Path("backend/answer_key.py").read_text(encoding="utf-8")
writes = re.findall(r"\b(insert|update|delete)\(\s*([\w.]+)", SOURCE)
check("❗ ชุดเฉลยไม่เขียนตาราง trips (เขียนได้แค่ key_facts กับ key_slips)",
      all(target in ("db.key_facts", "db.key_slips") for _, target in writes)
      and not re.search(r"\btext\(|update_trip|executescript", SOURCE), writes)
check("ชุดเฉลยเรียก db ได้เฉพาะตัวที่ไม่แก้แถวงาน",
      set(re.findall(r"\bdb\.(\w+)", SOURCE)) <= {"engine", "trips", "jobs", "key_facts", "key_slips",
                                                   "_now", "closed_weeks"},
      set(re.findall(r"\bdb\.(\w+)", SOURCE)))
others = [p for p in Path("backend").glob("*.py")
          if p.name != "answer_key.py" and not p.name.startswith("test_")]
defined = re.compile(r'^key_(facts|slips) = Table\(\s*"key_\1", meta,', re.M)
touch = []
for p in others:
    code_only = "\n".join(line for line in p.read_text(encoding="utf-8").splitlines()
                          if not line.lstrip().startswith("#"))
    if p.name == "db.py":
        code_only = defined.sub("", code_only)
    if re.search(r"key_facts|key_slips", code_only):
        touch.append(p.name)
check("❗ มีแต่ answer_key.py ที่อ่านเขียนตารางชุดเฉลย", touch == [] and len(others) > 20, touch)

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
