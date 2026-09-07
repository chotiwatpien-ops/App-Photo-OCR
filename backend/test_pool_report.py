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

# The ratio line has to keep quiet when there is nothing to judge: run 17 warned that 4W was
# 0% Taxi out of two riders, which is not a mix being missed, it is two riders.
print("บรรทัดสัดส่วน:")


class _Alloc:
    def __init__(self, c):
        self._c = c

    def kind_counts(self, wheel):
        return self._c.get(wheel, {})


def _ratio(counts):
    lines = []
    pool.report_mix({"w": _Alloc(counts)}, log=lines.append)
    return chr(10).join(lines)


txt = _ratio({"2W": {"Win": 12, "Home": 51}, "4W": {"Taxi": 0, "Home": 2}})
check("ห่างจากเป้าจริง ๆ ต้องเตือน", "Win 19% (เป้า 70% ±10%) ⚠" in txt)
check("คนน้อยเกินไปต้องไม่เตือน", "Taxi 0%  (ยังน้อยเกินกว่าจะตัดสิน)" in txt)
check("และต้องไม่ติ๊กถูกให้ด้วย", "Taxi 0% ✔" not in txt)
check("เข้าเป้าแล้วติ๊กถูก", "Win 70% ✔" in _ratio({"2W": {"Win": 46, "Home": 20}}))
check("ล้อที่ไม่มีใครเลยไม่ต้องพิมพ์", "4W" not in _ratio({"2W": {"Win": 5, "Home": 2}}))

# Run 18 lost seven real pairs to AttributeError because LINE also sends files named as a bare
# UUID, and the name of a stitched picture was built by demanding a trailing number.
print("ชื่อครึ่งรูปในไฟล์ที่ต่อแล้ว:")
check("ไฟล์ที่ลงท้ายด้วยเลข ใช้เลขนั้น",
      pool.half_tag("LINE_ALBUM_2W-NUI=110 standard_260907_57.jpg") == "57")
check("เลขหลายหลักก็ได้", pool.half_tag("S__96387096.jpg") == "96387096")
uid = pool.half_tag("1e020647-6513-4cef-91a3-5287f133bf2f.jpg")
check(f"UUID ไม่ทำให้พัง (ได้ {uid!r})", bool(uid))
check("และต้องไม่ไปหยิบเลขท้าย UUID มามั่ว ๆ", uid != "" and not uid.isdigit())
check("UUID คนละใบต้องได้ชื่อคนละอัน",
      pool.half_tag("1e020647-6513-4cef.jpg") != pool.half_tag("4c7d0753-5957-4316.jpg"))
check("ชื่อว่างก็ยังตอบอะไรสักอย่าง", pool.half_tag("") == "x" and pool.half_tag(None) == "x")
check("ไม่มีนามสกุลก็อ่านได้", pool.half_tag("LINE_ALBUM_x_12") == "12")

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
