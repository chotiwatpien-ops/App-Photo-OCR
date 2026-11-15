# -*- coding: utf-8 -*-
"""A tipped trip pairs when its bottom shows only the tip, as long as both clocks read one minute.

W46 (2026-11-14) left three true pairs in the pool: the top printed its ride income (฿52 under
฿72), the bottom's green was the tip total (฿20) and its fee card took too small a cut to count,
so the first gate saw 52 against 20 and refused. The readings below are the reader's own for those
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


def top(amount, own, clock, theme="สว่าง"):
    return {"role": "top", "amount": amount, "alts": [], "theme": theme, "numbers": [], "seq": [],
            "own_income": own, "clock": clock, "width": 869, "height": 1883}


def bottom(seq, amount, clock, theme="สว่าง"):
    return {"role": "bottom", "amount": amount, "alts": [], "theme": theme,
            "numbers": sorted(set(seq)), "seq": list(seq), "clock": clock, "width": 869, "height": 1883}


DARK = "มืด"
ALBUM_A = [  # album order, as Ops uploaded it
    ("112345", top(72, [52], 1398, DARK)),
    ("112346", bottom([20, 20, 78, 1, 20, 57, 57, 52, 5], 20, 1398, DARK)),
    ("112427", top(79, [39], 657, DARK)),
    ("112428", bottom([40, 40, 90, 1, 10, 1, 40, 38, 38, 39, 1], 40, 657, DARK)),
    ("114817", bottom([100, 1, 99, 99, 96, 3, 111], None, 1363)),
    ("114818", top(25, [25], 1362)),
]
ALBUM_B = [("3903", top(85, [65], 1065)),
           ("3902", bottom([85, 65, 65, 20, 20, 102, 1, 2, 20, 79], 85, 1065))]
ALBUM_C = [("44702", top(23, [], None)), ("44703", bottom([28, 28, 29, 1, 28, 28, 28, 2], 28, None))]
a, b = dict(ALBUM_A), dict(ALBUM_B)

check("❗ ฿72 = 52 + ทิป 20, ยอดเขียวครึ่งล่างคือทิป, นาฬิกาตรงกัน → เป็นคู่",
      pairing.match_tier(a["112345"], a["112346"], neighbours=True, same_shot=True) is not None)
check("❗ ฿79 = 39 + ทิป 40 → เป็นคู่", pairing.match_tier(
    a["112427"], a["112428"], neighbours=True, same_shot=True) is not None)
check("❗ ฿85 = 65 + ทิป 20, ยอดเขียวครึ่งล่างคือยอดที่ได้รับสุทธิ → เป็นคู่",
      pairing.match_tier(b["3903"], b["3902"], neighbours=True, same_shot=True) is not None)
check("❗ รายได้ครึ่งบนไม่ตรงกับตัวเลขไหนบนครึ่งล่าง ด่านแรกยังปัดตก: ฿72 รายได้ 53 บนครึ่งล่างเดิม",
      pairing.match_tier(top(72, [53], 1398, DARK), a["112346"], neighbours=True, same_shot=True) is None)
check("รายได้ครึ่งบนไม่อยู่บนครึ่งล่างเลย ด่านแรกยังปัดตก: ฿25 รายได้ 25 บนการ์ดรายได้ 96",
      pairing.match_tier(a["114818"], a["114817"], neighbours=True, same_shot=True) is None)

found = {}
for album in (ALBUM_A, ALBUM_B, ALBUM_C):
    pairs, left = pairing.pair_album(album)
    found.update({t: bt for t, bt, _ in pairs})
check("❗ ทั้งอัลบั้ม: คู่ทิปของ W46 จับได้ครบ 3 คู่ ถูกคู่",
      found == {"112345": "112346", "112427": "112428", "3903": "3902"})
check("Saver ฿25 กับครึ่งล่างรายได้ 96 และสลิปเก่า ฿23/฿28 ยังค้าง ไม่ถูกจับมั่ว",
      not {"114818", "114817", "44702", "44703"} & (set(found) | set(found.values())))

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
