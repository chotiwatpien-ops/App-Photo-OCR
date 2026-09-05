# -*- coding: utf-8 -*-
"""Handing paired trips to riders (Ops, 2026-09-05).

Three vehicle groups as before, but two kinds of driver inside each: a 2W fare is taken by a Win
rider or by someone on their own bike (Home), a 4W fare by a Taxi or a Home car. The service comes
off the slip, the driver kind off the pool album, and the two are read from different places on
purpose — an album of Home work splits across Saver and Standard.
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-dist-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import distribute                                                # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


# --- reading the album name -------------------------------------------------------------------
for album, want in [("2W-Home bike 150", ("2W", "Home")), ("2W-Win", ("2W", "Win")),
                    ("4W-Taxi wk5", ("4W", "Taxi")), ("4W-Home", ("4W", "Home")),
                    ("2w home", ("2W", "Home")), ("2W_Win_kanjana", ("2W", "Win"))]:
    check(f"อ่าน {album!r} → {want}", distribute.driver_kind(album) == want)

for album in ["2W-saver wk5kanjana 109", "2W-STD WK5=45", "kanjana 91", "",
              "4W-Win", "2W-Taxi"]:
    check(f"{album!r} บอกประเภทคนขับไม่ได้ → ไม่เดา", distribute.driver_kind(album) is None)


class FakeDrive:
    def __init__(self):
        self.tree, self.images = {"week": {}}, {}

    def ensure_folder(self, pid, name):
        fid = f"{pid}/{name}"
        self.tree.setdefault(pid, {})[name] = fid
        self.tree.setdefault(fid, {})
        self.images.setdefault(fid, 0)
        return fid

    def list_folders(self, pid):
        return [{"id": v, "name": k} for k, v in self.tree.get(pid, {}).items()]

    def list_images(self, pid):
        return [None] * self.images.get(pid, 0)


POOL = {("2W", "Win"): ["ก", "ข", "ค"], ("2W", "Home"): ["ง", "จ"],
        ("4W", "Taxi"): ["ฉ"], ("4W", "Home"): ["ช"]}

# --- a rider is filled to the quota before anyone new is drawn ---------------------------------
d = FakeDrive()
a = distribute.Allocator(d, "week", POOL, per_rider=3, seed=1)
first, _ = a.folder_for("2 W Saver", "2W", "Win")
same = [a.folder_for("2 W Saver", "2W", "Win")[0] for _ in range(2)]
check("สามใบแรกลงคนเดียวกันจนครบโควตา", same == [first, first])
fourth, _ = a.folder_for("2 W Saver", "2W", "Win")
check("ใบที่สี่เปิดคนใหม่", fourth != first)
check("สร้างโฟลเดอร์ไปสองอัน", a.made == 2)

# --- one name, one group, one week -------------------------------------------------------------
d2 = FakeDrive()
a2 = distribute.Allocator(d2, "week", POOL, per_rider=1, seed=2)
names = set()
for group in ("2 W Saver", "2 W Standard"):
    for _ in range(2):
        fid, err = a2.folder_for(group, "2W", "Win")
        if fid:
            names.add(distribute.bare(fid.rsplit("/", 1)[1]))
check("ชื่อไม่ซ้ำแม้ข้ามกลุ่มในสัปดาห์เดียวกัน", len(names) == 3)
check("พอชื่อหมดก็บอกว่าหมด ไม่วนใช้ซ้ำ",
      a2.folder_for("2 W Standard", "2W", "Win")[1] is not None)

# --- Home work lands in both 2W groups, drawn from the Home sheet only -------------------------
d3 = FakeDrive()
a3 = distribute.Allocator(d3, "week", POOL, per_rider=1, seed=3)
s, _ = a3.folder_for("2 W Saver", "2W", "Home")
t, _ = a3.folder_for("2 W Standard", "2W", "Home")
check("อัลบั้ม Home แตกไปได้ทั้งสองกลุ่ม", s and t and s != t)
check("ชื่อที่หยิบมาต้องมาจากชีต Home เท่านั้น",
      all(x.rsplit("/", 1)[1].endswith("Home") for x in (s, t)))

# --- someone already on the books gets topped up before a new name is drawn --------------------
d4 = FakeDrive()
cat = d4.ensure_folder("week", "4 W Standard")
half = d4.ensure_folder(cat, "01-ฉ Taxi")
d4.images[half] = 1                                   # already has one trip
a4 = distribute.Allocator(d4, "week", POOL, per_rider=3, seed=4)
got, _ = a4.folder_for("4 W Standard", "4W", "Taxi")
check("เติมคนที่ยังไม่เต็มก่อน ไม่เปิดคนใหม่", got == half and a4.made == 0)
check("ชื่อที่มีอยู่แล้วถูกจองไว้ ไม่ถูกหยิบซ้ำ", "ฉ Taxi" in a4.used)

# --- a name of the wrong kind is not topped up -------------------------------------------------
d5 = FakeDrive()
cat5 = d5.ensure_folder("week", "2 W Saver")
d5.images[d5.ensure_folder(cat5, "01-ง Home")] = 0    # empty, but Home
a5 = distribute.Allocator(d5, "week", POOL, per_rider=3, seed=5)
got5, _ = a5.folder_for("2 W Saver", "2W", "Win")
check("งาน Win ไม่ถูกยัดใส่โฟลเดอร์ของคน Home", got5.endswith("Win"))

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
