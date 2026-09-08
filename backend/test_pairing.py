# -*- coding: utf-8 -*-
"""Pairing rules must hold without any OCR; the folder run is checked when sample data exists."""
import io
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
# --- 4W-Home Sirinapa, the two pairs the matcher threw away -------------------------------------
# Ops put them in a training folder after the album came back with four unpaired halves. Both are
# correct pairs and both were rejected, for two different reasons.

# S__126665022 (฿117) + S__126665021: base 73, ค่าทิป 40, อินเซนทีฟเทอร์โบ 4. The gap is 44, but
# the figure the slip prints three times is the tip alone; the turbo rides along with it. The
# extras ceiling (half the fare) blocks tier 1 at 44 > 36.5, and the tip rule used to look for
# the whole 44 and find it once.
siri117 = {"amount": 73.0, "numbers": [4, 19, 20, 3, 40, 44, 73, 92, 155],
           "seq": [73, 73, 40, 4, 44, 155, 20, 3, 40, 92, 92, 73, 19]}
check("ทิป 40 + เทอร์โบ 4 บนค่าโดยสาร 73 → จับกับ ฿117 ได้",
      pairing.matches({"amount": 117.0}, siri117))
check("และยังเป็นหลักฐานอ่อน ต้องชนะด้วยระยะห่างเหมือนเดิม",
      pairing.match_tier({"amount": 117.0}, siri117) == 3)

# S__126665204 (฿308) + S__126665203: the bottom is cut above the round-income card, so its only
# green figure is the extra-income total ฿15. Two cards below, the fee card prints
# 369 − 293 = 76, and 293 + 15 is 308.
siri308 = {"amount": 15.0, "numbers": [15, 20, 50, 76, 293, 369, 389],
           "seq": [15, 15, 50, 389, 20, 50, 50, 369, 369, 293, 76]}
check("เลขเขียวเป็นยอดรายได้เพิ่ม ไม่ใช่รายได้รอบขับ → ถอยไปใช้การ์ดค่าบริการ",
      pairing.matches({"amount": 308.0}, siri308))
check("และได้ tier 1 เพราะการ์ดยืนยันตัวเอง ไม่ใช่หลักฐานอ่อน",
      pairing.match_tier({"amount": 308.0}, siri308) == 1)

# Parichat W5(1-13) carries both trips in one album: ฿33 received on one, ฿53 on another (33 and
# a ฿20 tip). The ฿53 trip's bottom prints 33 inside its own fee card, so a fall-through that
# accepted the income alone paired the ฿33 top with the ฿53 trip's bottom at tier 0 — and the
# true partner, which needs the tip counted, lost to it. Only income PLUS the printed extras.
pari35 = {"amount": 20.0, "numbers": [1, 7, 20, 33, 40, 61],
          "seq": [20, 20, 61, 1, 20, 40, 40, 33, 7]}
check("รายได้รอบขับเฉยๆ ไม่ใช่คู่ — ต้องรวมทิปที่ครึ่งล่างพิมพ์ไว้ด้วย",
      not pairing.matches({"amount": 33.0}, pari35))
check("รอบขับ 33 + ทิป 20 = ฿53 คือคู่ที่ถูก", pairing.matches({"amount": 53.0}, pari35))
check("และคู่ที่ถูกได้ tier 1", pairing.match_tier({"amount": 53.0}, pari35) == 1)
check("ของ Sirinapa ก็ต้องไม่รับรายได้รอบขับเปล่าๆ เช่นกัน",
      not pairing.matches({"amount": 293.0}, siri308))

# the loosening must not open the door the old rules were holding shut
check("เลขเขียวที่ใช้ไม่ได้ ไม่ได้แปลว่าจับกับอะไรก็ได้",
      not pairing.matches({"amount": 999.0}, siri308))
check("ส่วนที่พ่วงมากับทิปต้องเล็ก ไม่ใช่ค่าโดยสารอีกก้อน",
      not pairing.matches({"amount": 262.0},
                          {"amount": 73.0, "numbers": [40, 73, 149],
                           "seq": [73, 73, 40, 40, 149, 40]}))
check("ทิปที่พิมพ์ครั้งเดียว ต่อให้มีของเล็กพ่วง ก็ยังไม่จับ",
      not pairing.matches({"amount": 117.0},
                          {"amount": 73.0, "numbers": [4, 40, 73],
                           "seq": [73, 73, 40, 4]}))

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


# --- แถบวันที่บนหัวสลิป (Ops 2026-09-06: ทีมกำหนดวันที่เอง วันที่บนรูปจึงขัดกับในไฟล์) --------

from PIL import Image as _Img                                   # noqa: E402
plain = _Img.new("RGB", (600, 1200), "white")
check("รูปเปล่าไม่มีอะไรให้ตัด", pairing.date_bar_cut(plain) is None)
# ครึ่งบนที่มีแถบสีแดง 120px อยู่ข้างบน — ตัดแล้วต้องไม่เหลือสีแดงในรูปที่ต่อเสร็จ
a, b = _Img.new("RGB", (400, 1000), "white"), _Img.new("RGB", (400, 1000), "white")
a.paste((255, 0, 0), (0, 0, 400, 120))
check("ไม่สั่งตัด แถบยังอยู่", pairing.stitch(a, b).getpixel((5, 5)) == (255, 0, 0))
cut = pairing.stitch(a, b, cut_top=120)
check("สั่งตัดแล้วแถบหายจากรูปที่ต่อเสร็จ", cut.getpixel((5, 5)) == (255, 255, 255))
check("ตัดเฉพาะครึ่งบน ครึ่งล่างไม่ถูกแตะ",
      cut.getpixel((400 + 16 + 5, 995)) == (255, 255, 255) and cut.height == 1000)

dates = "Phase2/For Train Model/Remove Date Train"
if os.path.isdir(dates) and os.environ.get("PAIRING_SAMPLE", "1") == "1":
    tops = bots = 0
    for f in sorted(os.listdir(dates)):
        im = _Img.open(os.path.join(dates, f)).convert("RGB")
        cut = pairing.date_bar_cut(im)
        if cut is None:
            bots += 1
        else:
            tops += 1
            if not 0.05 < cut / im.height < 0.15:
                print("   ✗ ตัดผิดตำแหน่ง", f, cut / im.height)
    check(f"ชุด Remove Date: เจอแถบ 15 ใบ (เจอ {tops})", tops == 15)
    check(f"ครึ่งล่างไม่ถูกตัดสักใบ (ไม่ตัด {bots})", bots == 15)


# ชุด Remove Date 2026-09-06: ครึ่งบน ฿161 ไปคว้าครึ่งล่าง ฿161 ที่ห่าง 15 ใบ (ยอดตรงเป๊ะ)
# แทนที่จะจับกับใบที่ติดกัน (฿153 + ส่วนเพิ่ม 8) — ทำให้คู่ที่ถูกต้องกำพร้าไปสองคู่
far = [("b1", {"role": "bottom", "amount": 161.0, "numbers": [8, 161]}),
       ("t1", {"role": "top", "amount": 169.0}),
       ("pad1", {"role": "long", "amount": None}), ("pad2", {"role": "long", "amount": None}),
       ("b2", {"role": "bottom", "amount": 153.0, "numbers": [8, 153]}),
       ("t2", {"role": "top", "amount": 161.0})]
pairs, left = pairing.pair_album(far)
got = sorted((t, b) for t, b, _ in pairs)
check("ยอดตรงเป๊ะแต่อยู่ไกล ต้องแพ้ใบที่ติดกัน", got == [("t1", "b1"), ("t2", "b2")])
check("ไม่เหลือครึ่งไหนกำพร้า", not left)
check("รายงานระยะห่างที่ถูกต้อง", all(d == 1 for _, _, d in pairs))


def _enc(im):
    b = io.BytesIO()
    im.save(b, "JPEG")
    return b.getvalue()



# OCR ปฏิเสธรูปทรงบางแบบแล้วโยน error — ถ้าไม่กัน ทั้งรอบตาย เพราะรูปเดียว
class _Boom:
    def __call__(self, *a, **k):
        raise RuntimeError("ResizeImgError")


_real_engine = pairing._engine
pairing._engine = lambda: _Boom()
try:
    im_ok = _Img.new("RGB", (576, 1280), "white")
    im_ok.paste((0, 200, 90), (40, 700, 120, 740))          # ก้อนสีเขียวขนาดตัวเลขใหญ่
    got = pairing.inspect(_enc(im_ok))
    check("OCR ล้มแล้วยังตรวจรูปต่อได้ ไม่พาทั้งรอบลงเหว", got["amount"] is None)
    check("อ่านแถบวันที่ไม่ได้ ก็ไม่เดาว่ามีแถบ", pairing.date_bar_cut(im_ok) is None)
finally:
    pairing._engine = _real_engine


# รูปที่ Ops ต่อมาให้แล้ว วางลงกอง — ต้องรู้ว่าเป็นเที่ยวสมบูรณ์ ไม่ใช่ครึ่งใบที่ต้องหาคู่
wide = pairing.inspect(_enc(_Img.new("RGB", (1759, 1280), "white")))
check("รูปที่กว้างกว่าสูง = ต่อมาแล้ว ย้ายทั้งใบ ไม่ต้องจับคู่", wide["role"] == "long")
# ของจริงจาก Ops: ต่อรูป 537px สองใบ ได้ 1074x1200 = 0.895 — ยังไม่กว้างกว่าสูง แต่ต่อมาแล้ว
joined = pairing.inspect(_enc(_Img.new("RGB", (1074, 1200), "white")))
check("ต่อจากรูปแคบ (0.895) ก็ต้องรู้ว่าต่อมาแล้ว", joined["role"] == "long")
check("เกณฑ์อยู่ระหว่างใบเดียว (0.725) กับที่ต่อแล้ว (0.895)",
      0.725 < pairing.JOINED_MIN < 0.895)
tall = pairing.inspect(_enc(_Img.new("RGB", (576, 2600), "white")))
check("สกรีนช็อตยาวยังเป็น long เหมือนเดิม", tall["role"] == "long")
one = pairing.inspect(_enc(_Img.new("RGB", (928, 1280), "white")))
check("จอเดียวที่กว้างที่สุดที่เคยเจอ (0.725) ยังไม่ถูกนับว่าต่อแล้ว", one["role"] != "long")

panupong = "Phase2/For Train Model/2W-Home Panupong for train"
if os.path.isdir(panupong) and os.environ.get("PAIRING_SAMPLE", "1") == "1":
    from PIL import Image as _I
    miss = [f for f in sorted(os.listdir(panupong))
            if (lambda s: not (s[0] / s[1] < 0.36 or s[0] / s[1] > pairing.JOINED_MIN))(
                _I.open(os.path.join(panupong, f)).size)]
    check(f"ชุดที่ Ops ต่อมาให้: รู้ว่าต่อแล้วทุกใบ (พลาด {len(miss)})", not miss)


# --- the chip: which word is allowed to decide the vehicle -----------------------------------
# 'Standard' is the tier, not the vehicle. It is printed on 'Standard Bike' as much as on
# 'Standard (JustGrab)', so letting it vote for a car turned every bike whose 'Bike' the OCR
# missed into a car — WK36-อาลิฟ, a bike rider, was filed under 4 W Standard on 2026-09-07.
for txt, want in [("standard bike", "2W"), ("saver bike", "2W"), ("bike premium", "2W"),
                  ("standard | car only", "4W"), ("standard (justgrab)", "4W"),
                  ("saver car", "4W"), ("premium", "4W"),
                  ("standard", None),            # the tier alone says nothing about the vehicle
                  ("saver", None), ("", None), ("ค่าโดยสาร 86", None)]:
    check(f"ชิป {txt!r} → ล้อ {want}", pairing.wheels_from_chip(txt) == want)

for txt, want in [("standard bike", "Standard"), ("saver bike", "Saver"),
                  ("standard (justgrab)", "Standard"), ("justgrab", "Standard"),
                  ("saver car", "Saver"), ("bike", None), ("", None)]:
    check(f"ชิป {txt!r} → ระดับ {want}", pairing.tier_from_chip(txt) == want)

check("ชื่ออัลบั้มยังได้พูดเมื่อชิปอ่านไม่ออก",
      pairing.category_folder(pairing.wheels_from_chip("standard") or "2W",
                              pairing.tier_from_chip("standard")) == "2 W Standard")

# --- the date bar above a trip ----------------------------------------------------------------
# Written against thirty light-theme pictures that all said '02:51 PM', it matched none of the
# 616 Ops actually sends: the month is Thai, the clock is 24-hour, and the app elides the minutes
# to fit the width ('24 ก.ค. 2026, 05:3...').
for txt, want in [("24 n.A. 2026, 05:3... 5.41km", True),          # Ploy145, as the OCR reads it
                  ("05 n.8.2026,02:51 PM 7.17 km", True),          # the light sample, still fine
                  ("17 n.A. 2026, 06:3... 2.42 km", True),
                  ("13:40 2.64km Total 5 unn", False),             # Ploy182: a time, but no date
                  ("2026", False),                                 # a year with nothing under it
                  ("2026 150 190", False),                         # figures that look like one
                  ("nnnesuLCyIBLs 150 B150", False),               # ordinary text off a slip
                  ("5.41km", False), ("", False)]:
    hit = bool(pairing.DATE_BAR.search(txt) and pairing.UNDER_BAR.search(txt))
    check(f"แถบวันที่ {txt[:28]!r} → {want}", hit == want)

# and finding the two lines has to work whichever way round the screen is
import numpy as _np                                               # noqa: E402
from PIL import Image as _Im                                      # noqa: E402


def _band(ink, paper):
    a = _np.full((60, 200, 3), paper, dtype="uint8")
    a[6:20, 10:190] = ink                                          # the date line
    a[34:48, 10:120] = ink                                         # the distance under it
    return _Im.fromarray(a)


def _runs(band):
    on = pairing.text_rows(band)
    out, start = [], None
    for y, v in enumerate(on):
        if v and start is None:
            start = y
        elif not v and start is not None:
            out.append((start, y - 1)); start = None
    if start is not None:
        out.append((start, len(on) - 1))
    return [r for r in out if r[1] - r[0] >= 8]


check("จอสว่าง: เจอสองบรรทัด", len(_runs(_band(20, 245))) == 2)
check("จอมืด: เจอสองบรรทัดเหมือนกัน", len(_runs(_band(240, 15))) == 2)
check("ตำแหน่งบรรทัดตรงกันทั้งสองธีม", _runs(_band(20, 245)) == _runs(_band(240, 15)))
check("จอเปล่าไม่มีบรรทัดไหนเลย", _runs(_Im.fromarray(_np.full((60, 200, 3), 15, "uint8"))) == [])

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
