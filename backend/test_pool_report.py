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
# '74232_0.jpg': the trailing number is a copy index, '0' on every file in the album. Run #138
# named every LukArm pair '..._0+0_฿X' and pairs of one fare in one folder wrote over each other.
check("เลขท้าย _0 เป็นดัชนีสำเนา ตัวตนคือเลขข้างหน้า", pool.half_tag("74232_0.jpg") == "74232")
check("แบบ S__ ก็เหมือนกัน", pool.half_tag("S__76906624_0.jpg") == "76906624")
check("สำเนา _1 ของไฟล์เดิมได้ป้ายเดียวกัน (มันคือรูปเดียวกัน)", pool.half_tag("120848_1.jpg") == "120848")
check("สองไฟล์ติดกันได้ป้ายต่างกัน", pool.half_tag("74232_0.jpg") != pool.half_tag("74233_0.jpg"))
check("LINE_ALBUM เลขเดี่ยวท้ายชื่อยังเป็นลำดับในอัลบั้ม ไม่ใช่ดัชนี",
      pool.half_tag("LINE_ALBUM_x_260907_5.jpg") == "5" and pool.half_tag("LINE_ALBUM_x_260907_6.jpg") == "6")
check("เลขสั้น ๆ หน้า _0 ไม่ถูกมองเป็นแบบนั้น", pool.half_tag("12_0.jpg") == "0")

# a stitched picture is created, never written over
import tempfile, os
from drive_client import LocalDrive
ld = LocalDrive(tempfile.mkdtemp(prefix="pocr-create-"))
a = ld.create_file(ld.root, "x_฿46.jpg", b"1", "image/jpeg")
b = ld.create_file(ld.root, "x_฿46.jpg", b"2", "image/jpeg")
check("ชื่อซ้ำในโฟลเดอร์เดียว → สองไฟล์ ไม่ทับ", a != b and open(a, "rb").read() == b"1" and open(b, "rb").read() == b"2")
check("การต่อรูปใช้ create_file ไม่ใช่ upload_file",
      "drive.create_file(p[\"dest\"]" in open("backend/pool.py", encoding="utf-8").read()
      and "drive.upload_file(p[\"dest\"]" not in open("backend/pool.py", encoding="utf-8").read())

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)

# --- a car needs no tier: the team runs one car group (Best = 57, 2026-09-09) ------------------
# LINE shrank Best's long pictures to 317px wide; the chip read as just '4W' and the album name
# says no tier either, so 57 trips were 'ไม่รู้ประเภทรถ' — for a group that does not exist.
tc = pool.target_category
check("รถยนต์ อ่านได้แค่ 4W → 4 W Standard", tc("4W", None, "4W-Taxi Best=57") == "4 W Standard")
check("รถยนต์ ชิปอ่านไม่ออกเลย แต่ชื่ออัลบั้มบอก 4W → 4 W Standard", tc(None, None, "4W-Taxi Best=57") == "4 W Standard")
check("Saver Car ยังไป 4 W Standard เหมือนเดิม", tc("4W", "Saver", "x") == "4 W Standard")
check("จักรยานยนต์ยังต้องรู้ระดับ: 2W เฉย ๆ → ไม่รู้", tc("2W", None, "2W-Win Tae=15") is None)
check("จักรยานยนต์ที่ชื่ออัลบั้มบอก std → 2 W Standard", tc("2W", None, "2W-STD WK5=45") == "2 W Standard")
check("ชิปชนะชื่ออัลบั้ม", tc("2W", "Saver", "2W-STD WK5=45") == "2 W Saver")
check("ไม่รู้อะไรเลย → ไม่เดา", tc(None, None, "LINE_ALBUM_x") is None)
