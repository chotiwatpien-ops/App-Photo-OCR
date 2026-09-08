# -*- coding: utf-8 -*-
"""Putting back only the trips that were written over.

Until 2026-09-08 a joined picture from an album named '74232_0.jpg' was called
'<album>_0+0_฿46.jpg' whatever its halves were, and the upload wrote over a same-named file:
of three ฿46 trips handed to one rider, one picture survived. The reports say how many pairs
of each fare were moved; Drive says how many pictures of each fare exist; the difference is
what went missing, and every pair of that fare goes back — survivors too, because nobody can
say which of the three the survivor is.
"""
import json
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-collide-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import revert_album as rev                                      # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


class FakeDrive:
    def __init__(self):
        self.tree, self.images = {}, {}

    def ensure_folder(self, pid, name):
        fid = f"{pid}/{name}"
        self.tree.setdefault(pid, {})[name] = fid
        self.tree.setdefault(fid, {})
        self.images.setdefault(fid, [])
        return fid

    def list_folders(self, pid):
        return [{"id": v, "name": k} for k, v in self.tree.get(pid, {}).items()]

    def list_images(self, pid):
        return list(self.images.get(pid, []))


check("อ่านยอดจากชื่อรูปต่อ", rev.amount_of("2W-Win LukArm=117_0+0_฿46.jpg") == 46.0)
check("ยอดทศนิยมก็ได้", rev.amount_of("x_1+2_฿46.5.jpg") == 46.5)
check("ชื่อที่ไม่ใช่รูปต่อตอบ None", rev.amount_of("74232_0.jpg") is None)

ALB = "2W-Win LukArm=117"
d = FakeDrive()
d.tree["inbox"] = {}
wk = d.ensure_folder("inbox", "Week 31 Aug-6 Sep")
saver = d.ensure_folder(wk, "2 W Saver")
r1 = d.ensure_folder(saver, "98-อิทธพล Win")
r2 = d.ensure_folder(saver, "97-สาธิต Win")
dup = d.ensure_folder(d.ensure_folder(wk, "_ซ้ำ"), "ก Win")
# three ฿46 trips were moved; one picture of that name survived in อิทธพล's folder. Two ฿33
# trips were moved; both survive (one in the duplicate hold). ฿95: one moved, one present.
d.images[r1] = [{"id": "s46", "name": f"{ALB}_0+0_฿46.jpg"}, {"id": "s33a", "name": f"{ALB}_0+0_฿33.jpg"},
                {"id": "s95", "name": f"{ALB}_0+0_฿95.jpg"}, {"id": "other", "name": "2W-Win Rin=326_0+0_฿46.jpg"}]
d.images[dup] = [{"id": "s33b", "name": f"{ALB}_0+0_฿33.jpg"}]
originals = [{"id": f"o{n}", "name": f"{n}_0.jpg"} for n in range(74232, 74246)]
report = {"albums": [{"week": "Week 31 Aug-6 Sep", "album": ALB, "pairs": [
    {"top": "74232_0.jpg", "bottom": "74233_0.jpg", "amount": 46.0, "moved": f"2 W Saver/{ALB}_0+0_฿46.jpg"},
    {"top": "74234_0.jpg", "bottom": "74235_0.jpg", "amount": 46.0, "moved": f"2 W Saver/{ALB}_0+0_฿46.jpg"},
    {"top": "74236_0.jpg", "bottom": "74237_0.jpg", "amount": 46.0, "moved": f"2 W Saver/{ALB}_0+0_฿46.jpg"},
    {"top": "74238_0.jpg", "bottom": "74239_0.jpg", "amount": 33.0, "moved": f"2 W Saver/{ALB}_0+0_฿33.jpg"},
    {"top": "74240_0.jpg", "bottom": "74241_0.jpg", "amount": 33.0, "moved": f"2 W Saver/{ALB}_0+0_฿33.jpg"},
    {"top": "74242_0.jpg", "bottom": "74243_0.jpg", "amount": 95.0, "moved": f"2 W Saver/{ALB}_0+0_฿95.jpg"},
    {"top": "74244_0.jpg", "bottom": "74245_0.jpg", "amount": 22.0, "moved": "เต็มสัปดาห์นี้ → ยกไป Week 7-13 Sep", "carried": True},
    {"top": "74250_0.jpg", "bottom": "74251_0.jpg", "amount": 46.0, "moved": "ย้ายไม่สำเร็จ: boom"},
]}, {"week": "Week 31 Aug-6 Sep", "album": "2W-Win Rin=326", "pairs": [
    {"top": "80661_0.jpg", "bottom": "80662_0.jpg", "amount": 46.0, "moved": "2 W Saver/2W-Win Rin=326_0+0_฿46.jpg"}]}]}
runs = [{"id": 24, "report": json.dumps(report, ensure_ascii=False)}, {"id": 23, "report": None}]

reported = rev.pairs_reported(runs, "Week 31 Aug-6 Sep", ALB)
check("นับเฉพาะคู่ที่ย้ายจริง ไม่นับที่ยกไปสัปดาห์หน้าหรือย้ายไม่สำเร็จ", len(reported) == 6)
check("ไม่ปนอัลบั้มอื่นแม้ยอดเท่ากัน", all(t.startswith("7423") or t.startswith("7424") for t, _b, _a in reported))
check("รายงานที่ว่าง (None) ไม่ทำให้พัง", rev.pairs_reported([{"report": None}], "w", ALB) == [])

stitched = rev.stitched_in_week(d, wk, ALB)
present = [i for _f, i in stitched] + rev.stitched_in_holds(d, wk, ALB)
check("รูปที่พักไว้ใน _ซ้ำ นับว่ายังอยู่", "s33b" in [i["id"] for i in present])
lost = rev.collided(reported, present)
check("฿46 ย้าย 3 มี 1 → หาย 2 · ฿33 ครบ · ฿95 ครบ", lost == {46.0: 2})

back, hold, lost2, missing = rev.collided_plan(d, {"id": wk, "name": "Week 31 Aug-6 Sep"}, ALB,
                                               originals, stitched, runs)
check("คืนต้นฉบับของทุกคู่ ฿46 (3 คู่ = 6 ใบ) รวมคู่ที่รูปยังอยู่",
      sorted(i["name"] for i in back) == [f"{n}_0.jpg" for n in range(74232, 74238)])
check("เก็บรูป ฿46 ที่ยังอยู่ไปพัก ไม่แตะ ฿33/฿95 และไม่แตะอัลบั้มอื่น",
      [i["id"] for _f, i in hold] == ["s46"])
check("ไม่มีคู่ที่ขาดต้นฉบับ", missing == [])

# a pair whose originals are gone from _ใช้แล้ว is reported, not silently skipped
back2, hold2, _l, missing2 = rev.collided_plan(d, {"id": wk, "name": "Week 31 Aug-6 Sep"}, ALB,
                                               originals[:2], stitched, runs)
check("คู่ที่หาต้นฉบับไม่เจอถูกบอก ไม่ใช่เงียบ", len(missing2) == 2 and len(back2) == 2)

# nothing lost → nothing to do
d2 = FakeDrive(); d2.tree["inbox"] = {}
wk2 = d2.ensure_folder("inbox", "Week 31 Aug-6 Sep")
r = d2.ensure_folder(d2.ensure_folder(wk2, "2 W Saver"), "01-ก Win")
d2.images[r] = [{"id": "a", "name": f"{ALB}_74232+74233_฿46.jpg"}, {"id": "b", "name": f"{ALB}_74234+74235_฿46.jpg"},
                {"id": "c", "name": f"{ALB}_74236+74237_฿46.jpg"}, {"id": "e", "name": f"{ALB}_74238+74239_฿33.jpg"},
                {"id": "f", "name": f"{ALB}_74240+74241_฿33.jpg"}, {"id": "g", "name": f"{ALB}_74242+74243_฿95.jpg"}]
st2 = rev.stitched_in_week(d2, wk2, ALB)
b3, h3, l3, m3 = rev.collided_plan(d2, {"id": wk2, "name": "Week 31 Aug-6 Sep"}, ALB, originals, st2, runs)
check("ครบทุกคู่ → ไม่คืนอะไร ไม่พักอะไร", b3 == [] and h3 == [] and l3 == {})

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
