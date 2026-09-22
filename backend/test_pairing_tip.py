# -*- coding: utf-8 -*-
"""A tipped trip whose bottom half shows the tip only inside the passenger's card still pairs.

2W-Home UploadJab (2026-09-22) left four true pairs in the pool: the rider's bottom half was cut
below the extra-income card, so the ฿20 tip was printed once, as '−20' under what the passenger
paid, and ฿58 = 38 + 20 matched no rule. The readings below are the reader's own for those
pictures (pairing.inspect), so no image or OCR is needed to run this.
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "backend")

import pairing                                                   # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


def top(amount, own=()):
    return {"role": "top", "amount": amount, "alts": [], "theme": "สว่าง", "numbers": [], "seq": [],
            "own_income": list(own), "clock": None, "width": 860, "height": 1904}


def bottom(seq, amount=None):
    return {"role": "bottom", "amount": amount, "alts": [], "theme": "สว่าง",
            "numbers": sorted(set(seq)), "seq": list(seq), "clock": None, "width": 860, "height": 1904}


ALBUM = [  # album order, as Ops uploaded it
    ("3187", top(58)), ("3188", bottom([67, 1, 1, 20, 45, 45, 38, 7])),
    ("3195", bottom([32, 1, 5, 2, 28, 28, 24, 4, 2])),
    ("3236", top(44)), ("3237", bottom([20, 555, 50, 1, 20, 29, 29, 24, 5, 2])),
    ("3344", top(28, [28])),
    ("3361", top(59)), ("3362", bottom([20, 20, 72, 1, 1, 5, 20, 45], amount=20)),
    ("3389", top(79)), ("3390", bottom([86, 1, 1, 41, 43, 43, 38, 5])),
    ("3399", bottom([159, 195, 1, 1, 193, 193, 159, 34])),
    ("3424", top(58, [58])), ("3513", top(28, [28])),
]
info = dict(ALBUM)

check("บล็อกผู้โดยสาร: 67 − 1 − 1 − 20 = 45 ถูกอ่านเป็นการ์ดเดียว",
      (67, [1, 1, 20], 45) in pairing._passenger_cards(info["3188"]["seq"]))
check("❗ ฿58 = รายได้ 38 + ทิป 20 ที่อยู่ในบล็อกผู้โดยสาร → เป็นคู่",
      pairing.match_tier(info["3187"], info["3188"], neighbours=True) is not None)
check("❗ ฿79 = 38 + ทิป 41 (ทิปเกินครึ่งของรายได้ก็ยังเป็นทิป)",
      pairing.match_tier(info["3389"], info["3390"], neighbours=True) is not None)
check("❗ ยอดเขียว ฿20 ที่เป็นทิป ไม่ใช่รายได้: ฿59 = 39 + 20 → เป็นคู่",
      pairing.match_tier(info["3361"], info["3362"], neighbours=True) is not None)
check("ค่าธรรมเนียม ฿1 ไม่ใช่ทิป: ฿39 บนการ์ดรายได้ 38 ไม่เป็นคู่ด้วยกฎทิป",
      pairing._tip_in_passenger_card([39], [(45, 38, 7)], info["3188"]["seq"]) is None)
check("ส่วนต่างที่ไม่ได้อยู่ในบล็อกผู้โดยสาร ไม่เป็นทิป: ฿60 บน 38",
      pairing._tip_in_passenger_card([60], [(45, 38, 7)], info["3188"]["seq"]) is None)
check("ทิปต้องอยู่ในการ์ดผู้โดยสารที่ยอดรวมตรงกับค่าโดยสารในการ์ดค่าบริการ",
      pairing._tip_in_passenger_card([58], [(50, 38, 12)], info["3188"]["seq"]) is None)
check("ยอดเขียวที่พิมพ์ไม่ถึง 3 ครั้ง ไม่ถูกตีเป็นทิป",
      pairing._green_is_tip([59], [20], [20, 72, 1, 1, 5, 20, 45]) is None)
check("รายได้ที่เหลือหลังหักทิปต้องต่ำกว่าค่าโดยสารของผู้โดยสาร: ฿80 บนทิป 20 ไม่เป็นคู่",
      pairing._green_is_tip([80], [20], info["3362"]["seq"]) is None)

pairs, left = pairing.pair_album(ALBUM)
check("❗ ทั้งอัลบั้ม: คู่ที่มีทิป 4 คู่จับได้ครบ ถูกคู่",
      sorted((t, b) for t, b, _ in pairs) == [("3187", "3188"), ("3236", "3237"),
                                              ("3361", "3362"), ("3389", "3390")])
check("ครึ่งที่ไม่มีคู่ในอัลบั้มยังค้างเหมือนเดิม ไม่ถูกจับมั่ว",
      sorted(left) == ["3195", "3344", "3399", "3424", "3513"])

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
