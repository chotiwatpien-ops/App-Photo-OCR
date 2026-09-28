# -*- coding: utf-8 -*-
"""The old Grab screen's fee card, turned into the new screen's signs: Total becomes what the
passenger paid, the app fee turns negative, and nothing is kept unless it adds up to the row's own
ride fare (W34/W35 Passenger Fare left empty on 1,216 rows, Ops 2026-09-28)."""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-oldfees-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import reread_old_fees as ro                                   # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


# ฉลวย W34: fare 195, app fee 20, international 6, Total 221; Grab's cut 44 on base 151
row = {"passenger_total": 195, "passenger_paid": None, "tip": 0}
card = {"screen": "old", "fare": 195, "total": 221, "app_fee": 20, "intl_fee": 6}
f, why = ro.decide(row, card)
check("❗ จอเก่า: Total 221 → Passenger Fare · ค่าแอปกลายเป็น −20 (แบบจอใหม่) · ค่าธุรกรรม 6",
      why == "ลงตัว" and f["passenger_paid"] == 221 and f["app_fee"] == -20 and f["intl_fee"] == 6)
check("Total Commission ตามสูตรเดิม (Grab Service − ค่าแอป) = 44 − (−20) = 64", 44 - f["app_fee"] == 64)

# motorbike: fare 46, app 1, discount -3, international 1, Total 45
f, why = ro.decide({"passenger_total": 46, "tip": 0},
                   {"screen": "old", "fare": 46, "total": 45, "app_fee": 1, "discount": -3, "intl_fee": 1})
check("❗ ส่วนลดที่จอเก่าพิมพ์ −3 → เก็บเป็น +3 แบบจอใหม่ และลงตัว",
      why == "ลงตัว" and f["discount"] == 3 and f["app_fee"] == -1 and f["passenger_paid"] == 45)

# new screen that was left empty: paid 78, app −20, insurance −10 → fare 48
f, why = ro.decide({"passenger_total": 48, "tip": 0},
                   {"screen": "new", "fare": 48, "total": 78, "app_fee": -20, "insurance_fee": -10})
check("จอใหม่ที่ช่องจ่ายว่าง: เก็บตามที่พิมพ์", why == "ลงตัว" and f["app_fee"] == -20 and f["insurance_fee"] == -10)

f, why = ro.decide({"passenger_total": 195, "tip": 0}, {"screen": "old", "fare": 195, "total": 231, "app_fee": 20, "intl_fee": 6})
check("❗ บวกลบไม่ลงตัว → ไม่เก็บ", f is None and "ไม่ลงตัว" in why)
f, why = ro.decide({"passenger_total": 195, "tip": 0}, {"screen": "old", "fare": 187, "total": 213, "app_fee": 20, "intl_fee": 6})
check("❗ ค่าโดยสารบนสลิปไม่ตรง Ride Fare เดิม (คนละเที่ยว/อ่านผิด) → ไม่เก็บ", f is None and "≠" in why)
f, why = ro.decide({"passenger_total": None, "base_fare": 151, "tip": 0},
                   {"screen": "old", "fare": 195, "total": 221, "app_fee": 20, "intl_fee": 6, "grab_fare": 195, "grab_ride": 151, "grab_cut": 44})
check("❗ แถวที่ไม่มีค่าโดยสาร (ไฟล์ประมาณเอา): ได้ค่าจริงเมื่อการ์ด Grab ผูกกับค่ารอบ",
      why == "ลงตัว" and f["passenger_total"] == 195 and f["passenger_paid"] == 221)
f, why = ro.decide({"passenger_total": None, "base_fare": 120, "tip": 0},
                   {"screen": "old", "fare": 195, "total": 221, "app_fee": 20, "intl_fee": 6, "grab_fare": 195, "grab_ride": 151, "grab_cut": 44})
check("❗ การ์ด Grab ไม่ตรงค่ารอบของแถว (รูปคนละเที่ยว) → ไม่เก็บ", f is None and "ผูก" in why)
f, why = ro.decide({"passenger_total": 50, "base_fare": 40, "tip": 0},
                   {"screen": "old", "fare": 49, "total": 51, "app_fee": 1, "intl_fee": 1, "grab_fare": 49, "grab_ride": 40, "grab_cut": 9})
check("ต่าง ฿1 และการ์ดผูกกับค่ารอบ → ใช้ค่าตามสลิป", why == "ลงตัว" and f["passenger_total"] == 49)
f, why = ro.decide({"passenger_total": 100, "tip": 0}, {"screen": "old", "fare": 100, "total": 140, "app_fee": 20, "tip": 20})
check("❗ บล็อกมีค่าทิปที่แถวไม่มี → ไม่เก็บ (ไม่แตะทิป/คุณได้รับ)", f is None and "ทิป" in why)
f, why = ro.decide({"passenger_total": 100, "tip": 20}, {"screen": "old", "fare": 100, "total": 140, "app_fee": 20, "tip": 20})
check("บล็อกมีค่าทิปตรงกับแถว → ลงตัว", why == "ลงตัว" and f["passenger_paid"] == 140)
f, why = ro.decide({"passenger_total": 100, "tip": 0}, {"screen": "none"})
check("ไม่เห็นบล็อก → ไม่เก็บ", f is None)

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
