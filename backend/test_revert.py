# -*- coding: utf-8 -*-
"""Finding what one album produced, so it can be put back.

The joined pictures carry their album in their own name, which is the only thing left connecting
them once they have been scattered across riders and vehicle groups. Everything here is about
finding exactly those and nothing else — a sweep that catches a neighbouring album would take
away work that is perfectly good.
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-revert-")
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

    def move_file(self, fid, new_parent):
        for pid, imgs in list(self.images.items()):
            keep = [i for i in imgs if i["id"] != fid]
            if len(keep) != len(imgs):
                moved = [i for i in imgs if i["id"] == fid]
                self.images[pid] = keep
                self.images.setdefault(new_parent, []).extend(moved)


d = FakeDrive()
d.tree["inbox"] = {}
wk = d.ensure_folder("inbox", "Week 31 Aug-6 Sep")
other_wk = d.ensure_folder("inbox", "Week 24-30 Aug")
pool = d.ensure_folder(wk, "Pool")
saver = d.ensure_folder(wk, "2 W Saver")
std = d.ensure_folder(wk, "2 W Standard")
r1 = d.ensure_folder(saver, "01-ก Win")
r2 = d.ensure_folder(std, "02-ข Win")
held = d.ensure_folder(wk, "_ดึงกลับ")            # a holding folder from an earlier revert

d.images[r1] = [{"id": "a", "name": "2W-Win Ploy145_146+225_฿45.jpg"},
                {"id": "b", "name": "2W-Win Ploy145_109+108_฿26.jpg"},
                {"id": "c", "name": "2W-Win Ploy182_96362549+96362550_฿43.jpg"},
                {"id": "d", "name": "2W-Win NuiSaver=65_10+9_฿21.jpg"}]
d.images[r2] = [{"id": "e", "name": "2W-Win Ploy145_200+236_฿26.jpg"},
                {"id": "f", "name": "168106_168107.jpg"}]        # a pre-joined long picture
d.images[held] = [{"id": "z", "name": "2W-Win Ploy145_1+2_฿30.jpg"}]

got = rev.stitched_in_week(d, wk, "2W-Win Ploy145")
check("เจอรูปของอัลบั้มนี้ครบทุกโฟลเดอร์ไรเดอร์",
      sorted(i["id"] for _f, i in got) == ["a", "b", "e"])
check("บอกด้วยว่าอยู่โฟลเดอร์ไหน",
      sorted({f for f, _i in got}) == ["2 W Saver/01-ก Win", "2 W Standard/02-ข Win"])
check("ไม่ไปแตะอัลบั้มอื่น", "c" not in [i["id"] for _f, i in got]
      and "d" not in [i["id"] for _f, i in got])
check("ไม่ไปแตะรูปยาวที่ไม่ได้เกิดจากการต่อ", "f" not in [i["id"] for _f, i in got])
check("ไม่ไปรื้อของที่เคยคืนไปแล้ว", "z" not in [i["id"] for _f, i in got])
check("ไม่เดินเข้าโฟลเดอร์กอง", all(f.split("/")[0] != "Pool" for f, _i in got))

# a name that merely starts the same must not be swept up with it
d.images[r1].append({"id": "g", "name": "2W-Win Ploy1450_9+8_฿20.jpg"})
again = [i["id"] for _f, i in rev.stitched_in_week(d, wk, "2W-Win Ploy145")]
check("ชื่ออัลบั้มที่ขึ้นต้นเหมือนกันต้องไม่ถูกกวาดไปด้วย", "g" not in again)
check("แต่ของอัลบั้มนั้นเองยังครบเหมือนเดิม", sorted(again) == ["a", "b", "e"])
check("และหาอัลบั้มที่ชื่อยาวกว่าได้ตามปกติ",
      [i["id"] for _f, i in rev.stitched_in_week(d, wk, "2W-Win Ploy1450")] == ["g"])

check("อัลบั้มที่ไม่มีอะไรเลย ตอบว่าว่าง", rev.stitched_in_week(d, wk, "ไม่มีอยู่จริง") == [])
check("หาสัปดาห์เจอ", rev.week_folder(d, "inbox", "Week 31 Aug-6 Sep") == {"id": wk, "name": "Week 31 Aug-6 Sep"})
check("สัปดาห์ที่ไม่มีตอบ None", rev.week_folder(d, "inbox", "Week 1-7 Jan") is None)
check("หาโฟลเดอร์กองเจอ", rev.pool_folder(d, wk)["id"] == pool)
check("สัปดาห์ที่ไม่มีกองตอบ None", rev.pool_folder(d, other_wk) is None)

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
