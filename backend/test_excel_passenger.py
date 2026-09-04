# -*- coding: utf-8 -*-
"""Column P must carry รวมค่าโดยสารของผู้โดยสาร — the customer sent Week 35 back over this.
The 21 rows Operation corrected by hand (docs/Rider Data Train.xlsx) are the reference."""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "backend")
import config                                                   # noqa: E402
import excel_writer                                             # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


check("ค่าเริ่มต้นคือ 'total' (รวมค่าโดยสารของผู้โดยสาร)", config.PASSENGER_FARE_SOURCE == "total")

# ชัชชัย WK35: ผู้โดยสารได้ส่วนลด จึงจ่ายน้อยกว่ายอดรวม — Ops แก้เป็น 80 ไม่ใช่ 60
discount = {"passenger_paid": 60, "passenger_total": 80, "net_earnings": 64, "base_fare": 64}
check("มีส่วนลด: ใช้ยอดรวม 80 ไม่ใช่ยอดที่ชำระ 60", excel_writer.passenger_fare(discount) == 80)

# ทริปปกติ: ผู้โดยสารจ่ายมากกว่ายอดรวมเพราะค่าธรรมเนียมแอป — Ops แก้เป็น 161 ไม่ใช่ 186
appfee = {"passenger_paid": 186, "passenger_total": 161, "net_earnings": 129, "base_fare": 129}
check("มีค่าธรรมเนียมแอป: ใช้ยอดรวม 161 ไม่ใช่ 186", excel_writer.passenger_fare(appfee) == 161)

# ครึ่งล่างอ่านได้แค่ยอดที่ชำระ: ประกอบยอดรวมกลับจากค่าธรรมเนียมที่อ่านได้
only_paid = {"passenger_paid": 186, "passenger_total": None, "app_fee": -20, "other_adj": -5,
             "net_earnings": 129, "base_fare": 129}
check("มีแต่ยอดที่ชำระ: ประกอบยอดรวมกลับได้ 161", excel_writer.passenger_fare(only_paid) == 161)

# ไม่มีตัวเลขผู้โดยสารเลย: ประมาณจากค่าโดยสารพื้นฐานตามประเภทรถ
est = {"passenger_paid": None, "passenger_total": None, "base_fare": 100, "service_type": "Standard Car"}
check("ไม่มีเลข: ประมาณจากพื้นฐาน 100 → 125 (รถยนต์)", excel_writer.passenger_fare(est) == 125)
check("ธงบอกว่าเป็นค่าประมาณ", excel_writer.passenger_fare_estimated(est))
check("แถวที่มีเลขจริงไม่ถูกตีเป็นค่าประมาณ", not excel_writer.passenger_fare_estimated(appfee))

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
