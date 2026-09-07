# -*- coding: utf-8 -*-
"""A pool run's report has to say why a picture stayed behind, not just when one moved.

Run #14 read 609 pre-joined pictures and moved 379. The other 230 printed a line with nothing
after the target folder, because render() only appended text when the move had produced a path —
a failed move leaves its reason in the same field, and the reason was thrown away. The answer
(the rider name list had run out) reached only the web panel. Needs no sample album."""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "backend")
import pool                                                     # noqa: E402

ok = True


def check(name, cond):
    global ok
    ok = ok and bool(cond)
    print(("  ✓ " if cond else "  ✗ ") + name)


def report(long_items=(), pairs=()):
    return {"totals": {"n_images": 2, "n_duplicates": 0, "n_long": len(long_items),
                       "n_pairs": len(pairs), "n_leftover": 0, "pair_rate": None},
            "duplicates": [], "errors": [],
            "albums": [{"week": "W", "group": "", "album": "A", "n_images": 2,
                        "n_duplicates": 0, "long": list(long_items), "pairs": list(pairs),
                        "leftovers": []}]}


# A reading cached before themes existed has to gain one without its OCR being redone. Without
# this, every picture already in the cache is filed as style 'ยาว/None' and the whole point of
# keeping a rider to one look is lost on exactly the pictures that are waiting.
import io as _io                                                # noqa: E402
import numpy as _np                                             # noqa: E402
from PIL import Image as _Image                                 # noqa: E402
import pairing                                                  # noqa: E402


def _png(level):
    b = _io.BytesIO()
    _Image.fromarray(_np.full((40, 20, 3), level, dtype="uint8")).save(b, "PNG")
    return b.getvalue()


print("ธีมของผลที่แคชไว้:")
old_reading = {"role": "top", "amount": 56}                     # no 'theme' — read before the rule
pairing.ensure_theme(old_reading, _png(30))
check("ผลเก่าที่ไม่มีธีม ได้ธีมมืด", old_reading.get("theme") == "มืด")
light = {"role": "top"}
pairing.ensure_theme(light, _png(240))
check("และรูปสว่างได้สว่าง", light.get("theme") == "สว่าง")
kept = {"role": "top", "theme": "มืด"}
pairing.ensure_theme(kept, _png(240))
check("ผลที่มีธีมอยู่แล้วไม่ถูกเขียนทับ", kept["theme"] == "มืด")
check("ค่า None ก็ถือว่ายังไม่มี ไม่ใช่คำตอบ",
      pairing.ensure_theme({"theme": None}, _png(30))["theme"] == "มืด")

txt = pool.render(report(long_items=[
    {"file": "ก.jpg", "target": "2 W Saver", "moved": "2 W Saver/01-x/ก.jpg"},
    {"file": "ข.jpg", "target": "2 W Saver", "moved": "รายชื่อ Home ของ 2W หมดแล้ว"},
    {"file": "ค.jpg", "target": "2 W Saver"}]))
print("รูปยาว:")
check("ย้ายสำเร็จขึ้น ✔", "ก.jpg  → 2 W Saver  ✔ ย้ายแล้ว" in txt)
check("ย้ายไม่ได้ต้องบอกเหตุผล", "⚠ รายชื่อ Home ของ 2W หมดแล้ว" in txt)
check("ยังไม่ได้ลองย้ายก็ไม่ต้องขึ้นอะไร", "ค.jpg  → 2 W Saver\n" in txt + "\n")

txt = pool.render(report(pairs=[
    {"top": "a.jpg", "bottom": "b.jpg", "amount": 56, "tier": "A", "distance": 1,
     "moved": "2 W Saver/01-x/a_b.jpg"},
    {"top": "c.jpg", "bottom": "d.jpg", "amount": 70, "tier": "A", "distance": 1,
     "moved": "รายชื่อ Home ของ 2W หมดแล้ว"}]))
print("คู่:")
check("ย้ายสำเร็จขึ้น ✔", "✔ 2 W Saver/01-x/a_b.jpg" in txt)
check("ย้ายไม่ได้ต้องบอกเหตุผล", "⚠ รายชื่อ Home ของ 2W หมดแล้ว" in txt)

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
