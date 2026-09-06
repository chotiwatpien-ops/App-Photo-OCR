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
# A tip is the passenger's money, not Grab's, so it has no ceiling: Home bike riders were handed
# ฿40-50 on fares of ฿25-52 and the pairs were thrown away by the rule above, which exists to
# stop a passenger figure posing as a bonus. What tells them apart is how often the slip prints
# the figure — a tip three times (ค่าทิป, its section total, and again as a deduction in the
# passenger card), a passenger fare once.
tip = {"amount": 32.0, "numbers": [1, 32, 50, 83], "seq": [32, 32, 50, 50, 83, 1, 50, 32, 32, 32]}
check("ทิป ฿50 บนค่าโดยสาร ฿32 → จับกับครึ่งบน ฿82 ได้", pairing.matches({"amount": 82.0}, tip))
check("ทิปเป็นหลักฐานอ่อน ต้องชนะด้วยระยะห่าง", pairing.match_tier({"amount": 82.0}, tip) == 3)
check("เลขที่พิมพ์ครั้งเดียวไม่ใช่ทิป: 149+199 ยังห้ามจับ",
      not pairing.matches({"amount": 348.0},
                          {"amount": 149.0, "numbers": [7, 9, 50, 149, 199],
                           "seq": [149, 149, 7, 7, 50, 199, 149, 50]}))
check("ช่องว่างที่ตรงกับตัวเลขในการ์ดค่าธรรมเนียม ไม่นับเป็นทิป",
      not pairing.matches({"amount": 500.0},
                          {"amount": 426.0, "numbers": [21, 25, 54, 74, 426, 500],
                           "seq": [426, 426, 74, 74, 500, 426, 74]}))
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

# A trip where Grab took nothing ('ค่าบริการที่แกร็บได้รับ ฿0', Saver, short hop) prints no fee
# card worth the name — and the passenger card hands over a false one of exactly the right shape:
# 29 (รวมรายได้จากรอบขับ) − 28 (ยอดที่ผู้โดยสารชำระ) = 1 (ค่าธรรมเนียมการใช้แอป). Production
# 2026-09-06 threw away a pair over it, so a card that cannot agree must stay silent, not refuse.
b29 = {"amount": None, "numbers": [1, 2, 28, 29], "seq": [29, 29, 28, 1, 2, 29, 29, 29]}
check("แกร็บไม่หักค่าบริการ: การ์ดปลอม 29−28=1 ต้องไม่บล็อกคู่ ฿29", pairing.matches({"amount": 29.0}, b29))
check("และยังเป็นหลักฐานอ่อน ต้องชนะด้วยระยะห่าง", pairing.match_tier({"amount": 29.0}, b29) == 2)
check("ยอดที่ไม่มีในใบก็ยังไม่จับ", not pairing.matches({"amount": 55.0}, b29))
check("การ์ดจริงที่อ่านได้ยังปฏิเสธได้เหมือนเดิม", not pairing.matches({"amount": 348.0}, b149))

# '฿78' kerned tight leaves no gap for the leading-glyph check, so 878 stands as the fare. The
# second reading is offered alongside it, never in place of it — the partner decides.
check("อ่านสำรองจาก ฿ ที่ติดตัวเลข: 878 มีสำรอง 78 → จับกับครึ่งล่าง ฿78 ได้",
      pairing.matches({"amount": 878.0, "alts": [78.0]},
                      {"amount": 78.0, "numbers": [1, 2, 78, 80, 81], "seq": []}))
check("ค่าหลักยังใช้ได้ตามปกติ",
      pairing.matches({"amount": 878.0, "alts": [78.0]},
                      {"amount": 878.0, "numbers": [878], "seq": []}))
check("สำรองไม่ได้แปลว่าจับได้ทุกอย่าง",
      not pairing.matches({"amount": 878.0, "alts": [78.0]},
                          {"amount": 55.0, "numbers": [55], "seq": []}))


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

# The Saver slips of 2026-09-05, which took one album from 87% to 100% and cost three readings
# to get there. Each of these seven trips failed a different way:
#   · the map's pick-up pin and 'เส้นทางที่แนะนำ' legend line up into a band wider than it is
#     tall — printed text, as far as the block test can tell — and TALLER than the ฿ figure
#     below. Taking the tallest block read the map, and because the map sits above the 40% line
#     both halves of every trip were filed as bottoms with nothing to pair against.
#   · '฿43' comes back as 'B43'; the rule that removes a ฿ misread as a digit took the 4 with it.
#   · '฿72' came back as 372 on a page whose largest number is 72, and that misreading, being
#     the strongest kind of evidence, was allowed to block a pair its own page could confirm.
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
              sorted(i["amount"] for i in tops.values()) == [30.0, 33.0, 35.0, 38.0, 43.0, 43.0, 72.0])
        check("฿43 ไม่ถูกตัดเหลือ ฿3 (OCR อ่าน 'B43' มาถูกแล้ว)",
              [seen[n]["amount"] for n in (125, 126, 127, 128)] == [43.0] * 4)
        pairs, left = pairing.pair_album(sorted(seen.items()))
        check("อัลบั้มนี้จับคู่ได้ครบทั้ง 7 คู่", len(pairs) == 7 and left == [])
        check("ทุกคู่เป็นรูปที่อยู่ติดกัน ไม่ใช่จับข้ามอัลบั้ม",
              all(d == 1 for _, _, d in pairs))
    except ImportError as e:
        print("(ข้ามการทดสอบแผนที่เขียว: ไม่มี rapidocr —", e, ")")

# Standard slips, where Grab's cut is real. Every sample above is Saver, whose commission is
# near zero — the 'ค่าบริการที่แกร็บได้รับ' card is all but empty there, so nothing was holding
# the fee-card branch of match_tier to a real screenshot. Trip 37+38 is the one that matters:
# its lower half has no readable green figure at all, and only the card (184 − 150 = 34) says
# which top it belongs to.
std = "Phase2/Standard fee card"
if os.path.isdir(std) and os.environ.get("PAIRING_SAMPLE", "1") == "1":
    try:
        seen = {n: pairing.inspect(os.path.join(std, f))
                for f in sorted(os.listdir(std)) if f.endswith(".jpg")
                for n in [int(f.rsplit("_", 1)[1].split(".")[0])]}
        cards = {n: pairing._fee_card(i.get("seq") or []) for n, i in seen.items()}
        check("Standard: การ์ดค่าธรรมเนียมอ่านออก (ค่าโดยสาร − รายได้ = ส่วนที่แกร็บหัก)",
              [cards[n][-1] for n in (29, 37, 69)] == [(40.0, 33.0, 7.0), (184.0, 150.0, 34.0),
                                                       (25.0, 21.0, 4.0)])
        check("ครึ่งล่างที่อ่านเลขสีเขียวไม่ออก ยังจับคู่ได้ด้วยการ์ด",
              seen[37]["amount"] is None
              and pairing.match_tier(seen[38], seen[37]) is not None)
        pairs, left = pairing.pair_album(sorted(seen.items()))
        check("Standard: จับคู่ได้ครบทั้ง 3 คู่", len(pairs) == 3 and left == [])
        check("Standard: ยอดถูกทุกคู่",
              sorted(seen[t]["amount"] for t, _, _ in pairs) == [21.0, 33.0, 150.0])
    except ImportError as e:
        print("(ข้ามการทดสอบ Standard: ไม่มี rapidocr —", e, ")")

# ผลของ inspect() ถูก cache ด้วยไบต์ของรูป ซึ่งถูกจนกว่าตัวอ่านเองจะเปลี่ยน — รอบ 2026-09-06
# แก้ '฿78 อ่านเป็น 878' ไปแล้ว แต่รอบถัดมายังได้ 878 เพราะไบต์เดิมยังแฮชได้ค่าเดิม
check("กุญแจ cache ผูกกับเวอร์ชันตัวอ่านด้วย", pairing.cache_key("a" * 32).startswith(pairing.READER))
check("กุญแจยาวไม่เกินช่องในตาราง (40 ตัว)", len(pairing.cache_key("a" * 32)) <= 40)
check("รูปคนละใบยังได้กุญแจคนละอัน", pairing.cache_key("a" * 32) != pairing.cache_key("b" * 32))


b78 = {"amount": 78.0, "numbers": [1, 2, 78, 80, 81], "seq": []}
check("จับคู่ด้วยค่าสำรองแล้วต้องรายงานยอดที่คู่เห็นด้วย ไม่ใช่ค่าที่อ่านผิด",
      pairing.agreed_amount({"amount": 878.0, "alts": [78.0]}, b78) == 78.0)
check("ถ้าค่าหลักตรงอยู่แล้วก็ใช้ค่าหลัก",
      pairing.agreed_amount({"amount": 78.0, "alts": [12.0]}, b78) == 78.0)
check("ไม่มีอันไหนตรงเลย ก็คืนค่าหลักตามเดิม",
      pairing.agreed_amount({"amount": 500.0, "alts": []}, b78) == 500.0)


# เพดานความหนาแน่นของหมึก: ตัวเลขจริงที่หนาที่สุดใน 878 รูปของสัปดาห์หนึ่งวัดได้ 0.600 พอดี
# ('฿86' — เลข 8 กับ 6 เส้นเต็มกว่า 7 กับ 1) แล้วถูกทิ้งเพราะเส้นอยู่ที่ 0.6 พอดีเป๊ะ
check("เพดานหมึกต้องอยู่เหนือตัวเลขที่หนาที่สุดที่วัดได้", pairing.MAX_FILL > 0.60)
check("แต่ยังต่ำกว่าแถบทึบ", pairing.MAX_FILL < 0.9)


print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
