# -*- coding: utf-8 -*-
"""A whole trip in one tall screenshot is a whole trip, wherever a stray number is read.

W46 (2026-11-18): three whole slips sat in the pool as "halves waiting for a partner", because a
number in their address or map area was read as the fare and made them look like lower halves.
"""
import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "backend")

from PIL import Image, ImageDraw                                 # noqa: E402

import pairing                                                   # noqa: E402

ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


def tall_picture(at):
    """A 600x2200 screenshot with one green figure centred at this share of the height."""
    im = Image.new("RGB", (600, 2200), "white")
    y = int(2200 * at)
    draw = ImageDraw.Draw(im)
    for x in range(40, 240, 10):                                # strokes: a solid bar is not a figure
        draw.rectangle((x, y - 25, x + 4, y + 25), fill=(30, 170, 80))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


read_as_fare, read_numbers, read_clock = pairing._try_amount, pairing._all_numbers, pairing.read_clock
pairing._try_amount = lambda *_a: (96.0, [])
pairing._all_numbers = lambda _im: ([96], [96])
pairing.read_clock = lambda _im: None
role = lambda at: pairing.inspect(tall_picture(at))["role"]
check("❗ ยอดอยู่บนสุด 8% = ครึ่งล่างที่แคปยาว", role(0.08) == "bottom", role(0.08))
check("❗ เลขที่ 18% คือที่อยู่หรือแผนที่ของสลิปเต็ม", role(0.18) == "long", role(0.18))
check("❗ เลขที่ 23% คือแผนที่ของสลิปเต็ม", role(0.23) == "long", role(0.23))
check("ยอดกลางรูปคือสลิปเต็มตามเดิม", role(0.33) == "long", role(0.33))
check("❗ ขยับเวอร์ชันตัวอ่าน คำตอบเดิมใน cache จะไม่ถูกหยิบมาใช้", pairing.READER not in ("r12", "r13"))


def dark_screen(green_at=None, white_at=None):
    """An 870x1880 dark screen with a small green figure and/or a big white one."""
    im = Image.new("RGB", (870, 1880), (20, 20, 20))
    draw = ImageDraw.Draw(im)
    for at, tall, colour in ((green_at, 16, (30, 170, 80)), (white_at, 30, (247, 247, 247))):
        if at is not None:
            y = int(1880 * at)
            for x in range(60, 260, 12):
                draw.rectangle((x, y - tall, x + 5, y + tall), fill=colour)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


pairing._try_amount = lambda im, _m, y0, _y1: (44.0 if y0 < im.height * 0.3 else 91.0, [])
lower = pairing.inspect(dark_screen(green_at=0.09, white_at=0.55))
check("❗ จอมืด: ครึ่งล่างที่มียอดเขียวเล็ก ไม่ถูกอ่านจากเลขขาวในการ์ด",
      (lower["role"], lower["amount"]) == ("bottom", 44.0), lower)
white = pairing.inspect(dark_screen(white_at=0.75))
check("❗ จอมืดที่ยอดเป็นสีขาวล้วน ยังอ่านเป็นครึ่งบนตามเดิม", (white["role"], white["amount"]) == ("top", 91.0), white)
pairing._try_amount, pairing._all_numbers, pairing.read_clock = read_as_fare, read_numbers, read_clock

# Real pictures, on the machine that has them: test-images/ holds passengers' data and is not pushed.
samples = os.path.join(os.path.dirname(__file__), "..", "test-images", "samples")
whole = os.path.join(samples, "tall_whole")
if os.path.isdir(whole):
    for name in sorted(os.listdir(whole)):
        got = pairing.inspect(os.path.join(whole, name))["role"]
        check(f"สลิปเต็มจริง {name}", got == "long", got)
    bottom, top = (pairing.inspect(os.path.join(samples, "dark_pair", n)) for n in ("bottom.jpg", "top.jpg"))
    check("❗ คู่จริงธีมมืด: ครึ่งล่างยอด 44 กับครึ่งบนยอด 44",
          (bottom["role"], bottom["amount"], top["role"], top["amount"]) == ("bottom", 44.0, "top", 44.0), (bottom, top))
    check("❗ คู่จริงธีมมืดจับคู่กันได้", [(t, b) for t, b, _ in pairing.pair_album([("b", bottom), ("t", top)])[0]] == [("t", "b")])
else:
    print("ข้าม: ไม่มีรูปตัวอย่างในเครื่องนี้")

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
