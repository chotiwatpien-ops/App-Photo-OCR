# -*- coding: utf-8 -*-
"""Pairing rules must hold without any OCR; the folder run is checked when sample data exists."""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "backend")
import pairing                                                  # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


top = {"role": "top", "amount": 104.0}
check("ยอดตรงกับบรรทัดเขียวของครึ่งล่าง", pairing.matches(top, {"amount": 104.0, "numbers": []}))
check("ยอดอยู่ในตัวเลขของครึ่งล่าง", pairing.matches(top, {"amount": None, "numbers": [20, 104, 125]}))
check("ยอด = พื้นฐาน + รายได้เพิ่ม (4W)", pairing.matches(top, {"amount": 99.0, "numbers": [5, 20, 99, 125, 145]}))
check("ยอด = พื้นฐาน + โบนัส + ทิป", pairing.matches({"amount": 116.0}, {"numbers": [100, 10, 6, 20]}))
check("ยอดไม่ตรง → ไม่จับ", not pairing.matches(top, {"amount": 99.0, "numbers": [20, 99, 125]}))
check("ค่าโดยสารผู้โดยสารไม่ใช่รายได้เพิ่ม: 149+199 ≠ คู่ของ ฿348",
      not pairing.matches({"amount": 348.0}, {"amount": 149.0, "numbers": [7, 9, 50, 149, 199]}))
check("รายได้เพิ่มเล็ก ๆ ยังบวกได้: 149+7 = ฿156", pairing.matches({"amount": 156.0}, {"amount": 149.0, "numbers": [7, 9, 50, 149, 199]}))
# bottoms the user caught being paired wrongly (Test 9, 2026-09-03) — the fee card at the foot
# of every bottom half (passenger fare, income, Grab's cut) must decide the income
b426 = {"amount": 426.0, "numbers": [21, 25, 54, 142, 426, 568], "seq": [426, 426, 21, 21, 25, 568, 426, 142]}
check("การ์ดค่าบริการอ่านได้ → ฿75 ห้ามจับกับครึ่งล่างรายได้ 426 (เคย 21+54)", not pairing.matches({"amount": 75.0}, b426))
check("การ์ดค่าบริการอ่านได้ → ฿447 = 426 + เทอร์โบ 21 ยังจับได้", pairing.match_tier({"amount": 447.0}, b426) == 1)
b240 = {"amount": 240.0, "numbers": [12, 60, 240, 300], "seq": [240, 240, 12, 12, 300, 240, 60]}
check("฿76 ห้ามจับกับครึ่งล่างรายได้ 240", not pairing.matches({"amount": 76.0}, b240))
b71 = {"amount": 71.0, "numbers": [24, 71, 94], "seq": [71, 71, 94, 71, 24]}
check("฿189 ห้ามจับกับครึ่งล่างรายได้ 71 (เคย 71+94+24) · ค่าแกร็บปัดเศษ 94−71=23≈24", not pairing.matches({"amount": 189.0}, b71))
b94 = {"amount": 94.0, "numbers": [31, 94, 125], "seq": [94, 94, 125, 94, 31]}
check("฿125 ห้ามจับกับครึ่งล่างรายได้ 94 แม้ 125 คือค่าโดยสารผู้โดยสารในใบ", not pairing.matches({"amount": 125.0}, b94))
check("฿94 จับกับครึ่งล่างรายได้ 94 ได้", pairing.match_tier({"amount": 94.0}, b94) == 0)
b149 = {"amount": None, "numbers": [7, 9, 50, 149, 199], "seq": [149, 149, 7, 7, 50, 199, 149, 50]}
check("การ์ด 199/149/50 ยืนยันยอด 149 แม้ไม่มีบรรทัดเขียว", pairing.match_tier({"amount": 149.0}, b149) == 0)
check("149 + เทอร์โบ 7 = ฿156 ยังจับได้", pairing.match_tier({"amount": 156.0}, b149) == 1)
check("฿348 ห้ามจับกับครึ่งล่าง 149 (เคย 149+199)", not pairing.matches({"amount": 348.0}, b149))
b206 = {"amount": None, "numbers": [2, 5, 20, 69, 90, 206, 274, 391], "seq": [90, 391, 20, 2, 5, 90, 274, 274, 206, 69]}
check("Test 8: ฿413 ห้ามจับกับครึ่งล่างรายได้ 206 (เคย 391+20+2)", not pairing.matches({"amount": 413.0}, b206))
check("Test 8: ฿206 จับได้จากการ์ด 274/206/69", pairing.match_tier({"amount": 206.0}, b206) == 0)
b248 = {"amount": 248.0, "numbers": [20, 83, 248, 331, 351], "seq": [248, 248, 351, 20, 331, 331, 248, 83]}
check("Test 8: ฿252 ห้ามจับกับครึ่งล่างรายได้ 248 (เคย 248 + '4' จาก 4G บนแถบสถานะ)", not pairing.matches({"amount": 252.0}, b248))
check("Test 8: ฿248 จับได้ตรง ๆ", pairing.match_tier({"amount": 248.0}, b248) == 0)
b252 = {"amount": 252.0, "numbers": [20, 45, 50, 63, 252, 315, 330], "seq": [252, 45, 330, 20, 50, 45, 315, 315, 252, 63]}
check("Test 8: ฿117 ห้ามจับกับครึ่งล่างรายได้ 252 (เคย 63+50+4)", not pairing.matches({"amount": 117.0}, b252))
check("Test 8: ฿252 จับได้จากการ์ด 315/252/63", pairing.match_tier({"amount": 252.0}, b252) == 0)
b221 = {"amount": None, "numbers": [20, 50, 55, 221, 276, 346], "seq": [50, 346, 20, 50, 276, 276, 221, 55]}
check("Test 8: ฿229 ห้ามจับกับครึ่งล่างรายได้ 221 (เคย 221+4 / 55+50+...)", not pairing.matches({"amount": 229.0}, b221))
check("Test 8: ฿221 จับได้จากการ์ด 276/221/55", pairing.match_tier({"amount": 221.0}, b221) == 0)
check("ยอดจิ๋วคือการอ่านพลาด: MIN_AMOUNT ≥ 10 (GitHub run 2026-09-03 ต่อ ฿4/฿6/฿8 ผิด 10 คู่)", pairing.MIN_AMOUNT >= 10)
check("ครึ่งบนอ่านยอดไม่ได้ → ไม่จับ", not pairing.matches({"amount": None}, {"amount": 104.0, "numbers": [104]}))

items = [("1", {"role": "top", "amount": 30.0}), ("2", {"role": "bottom", "amount": 30.0, "numbers": [30]}),
         ("3", {"role": "top", "amount": 37.0}), ("4", {"role": "bottom", "amount": 37.0, "numbers": [37]}),
         ("5", {"role": "top", "amount": 37.0}), ("6", {"role": "bottom", "amount": 37.0, "numbers": [37]}),
         ("7", {"role": "long", "amount": None}),
         ("8", {"role": "top", "amount": 50.0}), ("9", {"role": "bottom", "amount": 60.0, "numbers": [60]})]
pairs, left = pairing.pair_album(items)
check("จับคู่ที่อยู่ติดกัน 1+2, 3+4, 5+6", sorted((t, b) for t, b, _ in pairs) == [("1", "2"), ("3", "4"), ("5", "6")])
check("รูปยาวไม่ถูกจับคู่ · ยอดไม่ตรงเหลือค้าง", sorted(left) == ["8", "9"])

tie = [("1", {"role": "bottom", "amount": 37.0, "numbers": [37]}), ("2", {"role": "top", "amount": 37.0}),
       ("3", {"role": "bottom", "amount": 37.0, "numbers": [37]})]
pairs, left = pairing.pair_album(tie)
check("ยอดชนกันและห่างเท่ากัน → ไม่เดา ปล่อยค้าง", pairs == [] and len(left) == 3)

sample = "Phase2/Test 7"
if os.path.isdir(sample) and os.environ.get("PAIRING_SAMPLE", "1") == "1":
    try:
        pairs, left, longs, info = pairing.run_folder(sample, out=None)
        check("ตัวอย่างจริง Test 7 จับคู่ได้ ≥ 85%", 2 * len(pairs) >= 0.85 * (len(info) - len(longs)))
    except ImportError as e:
        print("(ข้ามการทดสอบกับรูปจริง: ไม่มี rapidocr —", e, ")")

# The Saver slips of 2026-09-05: a paler map whose pick-up pin and 'เส้นทางที่แนะนำ' legend line
# up into a band wider than it is tall — printed text, as far as the block test can tell — and
# TALLER than the ฿ figure below it. Choosing the tallest block read the map (฿3352 off one, no
# number at all off the next) and, since the map sits above the 40% line, filed both halves of
# every trip as a bottom. 24 of 26 leftovers in that album were this, all of them matchable.
maps = "Phase2/Saver map green"
if os.path.isdir(maps) and os.environ.get("PAIRING_SAMPLE", "1") == "1":
    try:
        seen = {n: pairing.inspect(os.path.join(maps, f))
                for f in sorted(os.listdir(maps)) if f.endswith(".jpg")
                for n in [int(f.rsplit("_", 1)[1].split(".")[0])]}
        tops = {n: i for n, i in seen.items() if n % 2 == 0}
        check("ครึ่งบนที่มีแผนที่ ยังถูกอ่านว่าเป็นครึ่งบน",
              all(i["role"] == "top" for i in tops.values()))
        check("ยอดมาจากตัวเลขจริง ไม่ใช่สีเขียวบนแผนที่",
              sorted(i["amount"] for i in tops.values()) == [30.0, 33.0, 35.0, 38.0])
        pairs, left = pairing.pair_album(sorted(seen.items()))
        check("อัลบั้มนี้จับคู่ได้ครบทั้ง 4 คู่", len(pairs) == 4 and left == [])
    except ImportError as e:
        print("(ข้ามการทดสอบแผนที่เขียว: ไม่มี rapidocr —", e, ")")

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
