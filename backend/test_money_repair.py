# -*- coding: utf-8 -*-
"""The two readings that left rows waiting on 2026-08-27, plus the cases that must NOT change."""
import sys

sys.path.insert(0, "backend")
sys.stdout.reconfigure(encoding="utf-8")
from pipeline import _repair_money                              # noqa: E402

ok = True


def case(label, data, expect_base, expect_turbo, expect_note):
    global ok
    d = dict(data)
    note = _repair_money(d)
    got = (d.get("base_fare"), d.get("turbo") or 0, bool(note))
    want = (expect_base, expect_turbo, expect_note)
    mark = "✅" if got == want else "✗"
    if got != want:
        ok = False
    print(f"  {mark} {label}: base={got[0]} turbo={got[1]} note={'มี' if got[2] else '-'}")
    if note:
        print(f"       {note}")


print("เคสจริงที่ค้างอยู่:")
# กฤษณชัย #8725 — ทั้งสองครึ่งไม่มีค่าโดยสารพื้นฐาน, net 104, turbo 5 (รูปยืนยัน base = 99)
case("ฐานหาย", {"net_earnings": 104.0, "base_fare": 0.0, "bonus": 0.0, "turbo": 5.0},
     99.0, 5.0, True)
# ตฤณ #8831 — ค่าทางด่วน 50 ที่จ่ายคืน ถูกอ่านเป็น turbo ด้วย
case("ค่าทางด่วนซ้ำ", {"net_earnings": 270.0, "base_fare": 270.0, "bonus": 0.0,
                        "turbo": 50.0, "tolls": 50.0}, 270.0, 0, True)

print("\nเคสที่ห้ามแตะ:")
case("ยอดลงตัวอยู่แล้ว", {"net_earnings": 105.0, "base_fare": 100.0, "bonus": 0.0, "turbo": 5.0},
     100.0, 5.0, False)
case("turbo จริงเท่ากับ tolls แต่ยอดไม่ลงตัวถ้าตัดออก",
     {"net_earnings": 320.0, "base_fare": 270.0, "bonus": 0.0, "turbo": 50.0, "tolls": 50.0},
     270.0, 50.0, False)
case("ไม่มี net ให้คำนวณ", {"net_earnings": None, "base_fare": 0.0, "bonus": 0.0, "turbo": 0.0},
     0.0, 0, False)
case("net ทั้งหมดเป็น bonus (ฐานจะกลายเป็น 0)",
     {"net_earnings": 40.0, "base_fare": None, "bonus": 40.0, "turbo": 0.0}, None, 0, False)

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
