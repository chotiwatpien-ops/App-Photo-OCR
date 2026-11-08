# -*- coding: utf-8 -*-
"""The customer's zone table (requirement 2026-11-08): sub-districts before districts, Bangkok's
rest is Other, and only trips dated from ZONE_TABLE_FROM on use it, so delivered weeks keep the
zones they went out with."""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-zones-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import config                                                   # noqa: E402
import excel_writer as xw                                       # noqa: E402
import zone_table_build as ztb                                  # noqa: E402
import zones                                                    # noqa: E402

ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


tz = zones.table_zone
check("เขตในตาราง", tz("ดินแดง", "BKK") == "City Center")
check("ตัดคำว่า 'เขต' ออกก่อนเทียบ", tz("เขตบางรัก", "BKK") == "Inner City")
check("แขวงที่ลูกค้าระบุชนะเขตของมัน (ลุมพินีในปทุมวัน)",
      tz("ปทุมวัน", "BKK", "สวนลุมพินี แขวงลุมพินี เขตปทุมวัน") == "Inner City")
check("ปทุมวันที่ไม่ใช่ลุมพินีเป็น City Center", tz("ปทุมวัน", "BKK", "สยามพารากอน") == "City Center")
check("คลองตันเหนือ ไม่ถูกจับเป็นคลองตันผิดตัว", tz(None, "BKK", "ซอยเอกมัย แขวงคลองตันเหนือ") == "City Center")
check("ชื่อเมืองแบบสั้นที่ตัวอ่านให้มา (สมุทรปราการ)", tz("สมุทรปราการ", "SPK") == "Outer Ring")
check("ไม่มีเขต แต่ที่อยู่มีชื่อพื้นที่ (พัทยา)", tz(None, "CBI", "ถนนพัทยาสาย 2 ชลบุรี") == "Pattaya")
check("เขตในกรุงเทพฯ ที่ตารางไม่ได้ระบุ เป็น Other", tz("เขตที่ไม่มีในตาราง", "BKK") == "Other")
check("นอกกรุงเทพฯ ที่ไม่มีในตาราง เว้นว่าง (รอลูกค้าตอบ)", tz("เมืองเชียงใหม่", "CMI", "เชียงใหม่") == "")

check("ตัวอ่านให้ชื่อแขวงมาแทนเขต: แปลงเป็นเขตก่อน (เสนานิคม → จตุจักร)",
      tz("แขวงเสนานิคม", "BKK") == "Inner City", tz("แขวงเสนานิคม", "BKK"))
check("หัวหมาก → บางกะปิ", tz("หัวหมาก", "BKK") == tz("บางกะปิ", "BKK"))
check("ชื่อแขวงที่ซ้ำสองเขต (บางจาก) ไม่ถูกเดา", "บางจาก" not in zones.SUBDISTRICT_OF)
check("แปลงเฉพาะช่องเขต ไม่ไปค้นชื่อแขวงในข้อความที่อยู่",
      tz(None, "BKK", "ร้านกาแฟหน้าวัดอรุณ") == "Other")
table_names = {n for part in zones.load_table() for n, _z in part}
bkk_khet = set(zones.SUBDISTRICT_OF.values())
check("ไม่มีชื่อแขวงในไฟล์แปลงที่ซ้ำกับชื่อเขต หรือแขวงที่ลูกค้าระบุ",
      not (set(zones.SUBDISTRICT_OF) & (bkk_khet | table_names)),
      set(zones.SUBDISTRICT_OF) & (bkk_khet | table_names))
check("ทุกเขตปลายทางของไฟล์แปลงอยู่ในตารางโซน", bkk_khet <= table_names, bkk_khet - table_names)

config.ZONE_TABLE_FROM = None
t_new = {"trip_date": "2026-11-10", "pickup_district": "ดินแดง", "pickup_code": "BKK",
         "dropoff_district": "ลาดกระบัง", "dropoff_code": "BKK"}
check("ยังไม่เปิดสวิตช์: ใช้โซนเดิม", xw.trip_zones(t_new) == ("Downtown", "East-SVB"), xw.trip_zones(t_new))
config.ZONE_TABLE_FROM = "2026-11-09"
check("เปิดสวิตช์: เที่ยวตั้งแต่วันเริ่มใช้โซนใหม่ ทั้งจุดรับและจุดส่ง",
      xw.trip_zones(t_new) == ("City Center", "Outer Ring"), xw.trip_zones(t_new))
t_old = dict(t_new, trip_date="2026-09-30")
check("เที่ยวก่อนวันเริ่ม คงโซนเดิม (สัปดาห์ที่ส่งไปแล้วไม่เปลี่ยน)",
      xw.trip_zones(t_old) == ("Downtown", "East-SVB"), xw.trip_zones(t_old))
config.ZONE_TABLE_FROM = None

check("แยกชื่อหลายพื้นที่ในช่องเดียว และตัดวงเล็บ",
      ztb.names_of("บางเสาธง / บางบ่อ (หมายเหตุ)") == ["บางเสาธง", "บางบ่อ"])
check("เมืองX ได้ชื่อสั้น X ด้วย", ztb.names_of("เมืองนนทบุรี") == ["เมืองนนทบุรี", "นนทบุรี"])
H = "ลูกค้ายืนยัน (✓ หรือใส่โซนที่ถูก)"
built = ztb.build([
    {"พื้นที่": "ลุมพินี", "ระดับ": "แขวง", "โซนที่เสนอ": "Inner City", H: "City Center"},
    {"พื้นที่": "สาทร", "ระดับ": "เขต", "โซนที่เสนอ": "Inner City", H: "✓"},
    {"พื้นที่": "ไทรน้อย", "ระดับ": "อำเภอ", "โซนที่เสนอ": "? ต้องเลือก", H: ""},
    {"พื้นที่": "คำถาม 2", "ระดับ": "", "โซนที่เสนอ": "", H: "Green"},
])
check("คำตอบของลูกค้าชนะข้อเสนอ · ✓ ใช้ข้อเสนอ · '?' ข้าม · แถวคำถามไม่นับ",
      built == [("ลุมพินี", "แขวง", "City Center"), ("สาทร", "เขต", "Inner City")], built)

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
