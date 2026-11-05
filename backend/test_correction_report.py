# -*- coding: utf-8 -*-
"""correction_report: queue history from action_log becomes per-field error counts and, per
hold reason, how often a person approved the row unchanged. No names or codes are printed."""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-corr-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import correction_report as cr                                  # noqa: E402
import db                                                       # noqa: E402
import pipeline                                                 # noqa: E402

db.init_db()
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


job = db.create_job("สมชาย ใจดี", "Trips", "2026-11-09", "2026-11-15", category="2 W Saver")


def trip(**f):
    tid = db.create_trip(job, "x.jpg", None, "image/jpeg")
    db.update_trip(tid, {"status": "done", "trip_date": "2026-11-10", "booking_code": "A-SECRETCODE99",
                         "pickup_text": "ซอยลับ 9", **f})
    return tid


turbo_ok = trip(check_status="no_data", note=f"เติม Turbo 3 | {pipeline.UNWITNESSED_TURBO}")
turbo_fixed = trip(check_status="no_data", note=f"เติม Turbo 6 | {pipeline.UNWITNESSED_TURBO}")
tip_row = trip(check_status="no_data", note=pipeline.tip_unsure_note(20, 20))
glyph = trip(check_status="fail")
gone = trip(check_status="fail")
bulk = trip(check_status="pass")

log = lambda action, target=None, **d: db.log_action(action=action, target=target, status=200, detail=d)  # noqa: E731
log("trip.approve", f"trip:{turbo_ok}")
log("trip.edit", f"trip:{turbo_fixed}", before={"net_earnings": 57}, after={"net_earnings": 51})
log("trip.edit", f"trip:{turbo_fixed}", before={"turbo": 6}, after={"turbo": 0})
log("trip.approve", f"trip:{turbo_fixed}")
log("trip.edit", f"trip:{tip_row}", before={"bonus": 40, "base_fare": None}, after={"bonus": 20, "base_fare": 80})
log("trip.approve", f"trip:{tip_row}")
log("trip.edit", f"trip:{glyph}", before={"net_earnings": 847, "note": "a"}, after={"net_earnings": 47, "note": "b"})
log("trip.edit", f"trip:{glyph}", before={"service_type": "Standard Bike"}, after={"service_type": "Saver Bike"})
log("trip.approve", f"trip:{glyph}")
log("trip.delete", f"trip:{gone}", row={"file_name": "x.jpg", "booking_code": "A-SECRETCODE99"})
db.delete_trip(gone)
log("queue.approve_passing", trip_ids=[bulk], approved=1)
db.log_action(action="trip.approve", target=f"trip:{bulk + 99}", status=400)      # refused: not counted

touched, rows = cr.load("2026-01-01", "2099-12-31")
check("นับแถวที่คนแตะ 6 แถว (ไม่นับคำสั่งที่ถูกปฏิเสธ)", len(touched) == 6, sorted(touched))
check("อนุมัติโดยไม่แก้", cr.outcome(touched[turbo_ok]) == "อนุมัติโดยไม่แก้")
check("แก้แล้วอนุมัติ", cr.outcome(touched[turbo_fixed]) == "แก้แล้วอนุมัติ")
check("ลบทิ้ง", cr.outcome(touched[gone]) == "ลบทิ้ง")
check("กดอนุมัติทุกแถวที่ผ่าน นับเป็นอนุมัติ", cr.outcome(touched[bulk]) == "อนุมัติโดยไม่แก้")

check("เหตุที่มารอ: turbo ไม่มีพยาน", cr.hold_reason(rows[turbo_ok]) == "turbo ที่เติมเอง ไม่มีตัวเลขยืนยัน")
check("เหตุที่มารอ: ทิป", cr.hold_reason(rows[tip_row]) == "ไม่รู้ว่าโบนัสรวมทิปแล้วหรือยัง")
check("เหตุที่มารอ: แถวที่ลบไปแล้ว", cr.hold_reason(rows.get(gone)) == "แถวถูกลบไปแล้ว")

check("฿ อ่านเป็นเลขนำหน้า (847 → 47)", cr.money_error(847, 47) == "฿ ถูกอ่านเป็นเลขนำหน้า")
check("ว่าง แล้วคนกรอก", cr.money_error(None, 80) == "ว่าง แล้วคนกรอกให้")
check("ต่างมาก (57 → 51 เกิน 10%)", cr.money_error(57, 51) == "ต่างมาก")
check("ต่างเล็กน้อย (100 → 95)", cr.money_error(100, 95) == "ต่างเล็กน้อย (ไม่เกิน 10%)")
check("ค่าเท่าเดิมไม่นับเป็นความผิด", cr.money_error(50, 50.0) is None)

text = cr.report(touched, rows, "2026-11-09", "2026-11-15")
check("ตาราง: turbo ไม่มีพยาน 2 แถว อนุมัติไม่แก้ 1 (50%)",
      "| turbo ที่เติมเอง ไม่มีตัวเลขยืนยัน | 2 | 1 (50%) | 1 (50%) | 0 (0%) |" in text)
check("ช่อง net_earnings ถูกแก้ 2 ครั้ง", "| net_earnings | 2 |" in text)
check("ประเภทรถที่คนเปลี่ยน", "| Standard Bike | Saver Bike | 1 |" in text)
check("ไม่นับช่อง note", "| note |" not in text)
check("ไม่มีชื่อไรเดอร์ booking code หรือที่อยู่ในรายงาน",
      not any(x in text for x in ("สมชาย", "SECRETCODE", "ซอยลับ")))
check("ช่วงที่ไม่มีอะไร: บอกตรงๆ", "ไม่มีการแก้" in cr.report({}, {}, "2026-01-01", "2026-01-07"))

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
