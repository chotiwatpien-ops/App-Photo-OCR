# -*- coding: utf-8 -*-
"""Handing paired trips to riders (Ops, 2026-09-05, revised 2026-09-07).

The service comes off the slip and decides the vehicle group. Which sheet a rider's name is drawn
from used to come off the pool album, and no longer does: the customer asked for a 70/30 Win-heavy
mix and reads it off the workbook, where every driver name carries its kind — so the kind is
chosen per name drawn, to hit that target. An album now only has to say 2W or 4W.

A rider also sends one phone's screenshots, so their folder holds one kind of picture: all
pre-joined or all stitched here, all dark theme or all light. The caller says what 'one kind'
means; the allocator only keeps a folder to whatever it settled on first.
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
for album, want in [("2W-Home bike 150", "2W"), ("2W-Win", "2W"), ("4W-Taxi wk5", "4W"),
                    ("4W-Home", "4W"), ("2w home", "2W"), ("2W_Win_kanjana", "2W")]:
    check(f"อ่าน {album!r} → {want}", distribute.wheel_of(album) == want)

# these used to be turned away for not naming a driver kind; the kind no longer comes from here
for album, want in [("2W-saver wk5kanjana 109", "2W"), ("2W-STD WK5=45", "2W"),
                    ("4W-Win", "4W"), ("2W-Taxi", "2W")]:
    check(f"{album!r} บอกล้อได้ก็พอแล้ว → {want}", distribute.wheel_of(album) == want)

for album in ["kanjana 91", "", "LINE_ALBUM_x"]:
    check(f"{album!r} บอกล้อไม่ได้ → ไม่เดา", distribute.wheel_of(album) is None)


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
        n = self.images.get(pid, 0)
        return n if isinstance(n, list) else [None] * n

    def move_file(self, fid, new_parent):
        for pid, n in list(self.images.items()):
            if isinstance(n, list):
                self.images[pid] = [f for f in n if f["id"] != fid]
        self.images[new_parent] = self.images.get(new_parent, 0) + 1


# Ops keeps more Win names than Home ones on purpose; the sheet has to be able to supply the
# mix being asked for, or the allocator can only fall back and the target is unreachable.
POOL = {("2W", "Win"): [f"วิน{i}" for i in range(1, 21)],
        ("2W", "Home"): [f"บ้าน{i}" for i in range(1, 11)],
        ("4W", "Taxi"): ["ฉ"], ("4W", "Home"): ["ช"]}
SMALL = {("2W", "Win"): ["ก", "ข", "ค"], ("2W", "Home"): ["ง", "จ"],
         ("4W", "Taxi"): ["ฉ"], ("4W", "Home"): ["ช"]}

# --- a rider is filled to the quota before anyone new is drawn ---------------------------------
d = FakeDrive()
a = distribute.Allocator(d, "week", POOL, per_rider=3, seed=1)
first, _ = a.folder_for("2 W Saver", "2W")
same = [a.folder_for("2 W Saver", "2W")[0] for _ in range(2)]
check("สามใบแรกลงคนเดียวกันจนครบโควตา", same == [first, first])
fourth, _ = a.folder_for("2 W Saver", "2W")
check("ใบที่สี่เปิดคนใหม่", fourth != first)
check("สร้างโฟลเดอร์ไปสองอัน", a.made == 2)

# --- the mix the customer asked for ------------------------------------------------------------
d2 = FakeDrive()
a2 = distribute.Allocator(d2, "week", POOL, per_rider=1, seed=2)
for _ in range(20):
    a2.folder_for("2 W Saver", "2W")
c = a2.kind_counts("2W")
share = c["Win"] / sum(c.values())
check(f"สัดส่วน Win เข้าเป้า 70% ±10% (ได้ {share:.0%}: Win {c['Win']} Home {c['Home']})",
      abs(share - 0.70) <= 0.10)

# the target is followed all the way, not only once the week is big
d2b = FakeDrive()
a2b = distribute.Allocator(d2b, "week", POOL, per_rider=1, seed=22)
worst = 0.0
for n in range(1, 21):
    a2b.folder_for("2 W Saver", "2W")
    cc = a2b.kind_counts("2W")
    if n >= 4:                                    # a 70/30 split cannot exist below four riders
        worst = max(worst, abs(cc["Win"] / sum(cc.values()) - 0.70))
check(f"ไม่หลุดกรอบระหว่างทางด้วย (ห่างจากเป้ามากสุด {worst:.0%})", worst <= 0.10)

# --- 21 งานเป็นของคน ไม่ใช่ของโฟลเดอร์ ----------------------------------------------------------
# A fare's tier is the fare's, not the rider's, so someone who works both gets a folder in each
# group and one quota across the two — not two quotas, and not a second name.
d3 = FakeDrive()
a3 = distribute.Allocator(d3, "week", POOL, per_rider=4, seed=3)
s1 = [a3.folder_for("2 W Saver", "2W")[0] for _ in range(3)]
check("สามใบแรกลงคนเดียวใน Saver", len(set(s1)) == 1)
t1, _ = a3.folder_for("2 W Standard", "2W")
check("พองาน Standard เข้ามา คนเดิมได้โฟลเดอร์ที่สอง ไม่ใช่ชื่อใหม่",
      distribute.bare(t1.rsplit("/", 1)[1]) == distribute.bare(s1[0].rsplit("/", 1)[1])
      and t1 != s1[0])
check("ชื่อที่ถูกใช้ยังมีคนเดียว", len(a3.used) == 1)
t2, _ = a3.folder_for("2 W Standard", "2W")
check("ครบ 4 แล้วต้องเป็นคนใหม่",
      distribute.bare(t2.rsplit("/", 1)[1]) != distribute.bare(s1[0].rsplit("/", 1)[1]))
check("รวมสองโฟลเดอร์แล้วไม่เกินโควตา", a3.total[distribute.bare(s1[0].rsplit("/", 1)[1])] == 4)

d3b = FakeDrive()
a3b = distribute.Allocator(d3b, "week", SMALL, per_rider=1, seed=33)
names = set()
for group in ("2 W Saver", "2 W Standard"):
    for _ in range(3):
        fid, err = a3b.folder_for(group, "2W")
        if fid:
            names.add(distribute.bare(fid.rsplit("/", 1)[1]))
check("ชื่อไม่ซ้ำแม้ข้ามกลุ่ม เมื่อโควตาหมดแล้ว", len(names) == 5)
check("พอชื่อหมดก็บอกว่าหมด ไม่วนใช้ซ้ำ", a3b.folder_for("2 W Standard", "2W")[1] is not None)

# and the person keeps one look, whichever group the work lands in
d3c = FakeDrive()
a3c = distribute.Allocator(d3c, "week", POOL, per_rider=4, seed=34)
sv, _ = a3c.folder_for("2 W Saver", "2W", "ยาว/มืด")
st, _ = a3c.folder_for("2 W Standard", "2W", "ยาว/มืด")
check("คนเดิมข้ามกลุ่มได้ถ้ารูปแบบเดียวกัน",
      distribute.bare(st.rsplit("/", 1)[1]) == distribute.bare(sv.rsplit("/", 1)[1]))
other, _ = a3c.folder_for("2 W Standard", "2W", "ครึ่ง/สว่าง")
check("รูปคนละแบบไม่ไปหาคนเดิม แม้เค้าจะยังไม่เต็ม",
      distribute.bare(other.rsplit("/", 1)[1]) != distribute.bare(sv.rsplit("/", 1)[1]))
check("จดสไตล์ไว้ที่ชื่อคน ไม่ใช่ที่โฟลเดอร์",
      a3c.new_styles == {distribute.bare(sv.rsplit("/", 1)[1]): "ยาว/มืด",
                         distribute.bare(other.rsplit("/", 1)[1]): "ครึ่ง/สว่าง"})

# --- when the list runs out, say whether the seats are gone or held by the wrong people --------
# Run 15 moved 21 of 230 and said only 'the names are all used'. That reads as 'nobody has room',
# and it is also printed when there is plenty of room belonging to people whose pictures look
# nothing like these. Those are two different problems and need two different answers.
d4 = FakeDrive()
a4 = distribute.Allocator(d4, "week", SMALL, per_rider=2, seed=4)
for _ in range(9):                                     # 5 names × 2 seats, one seat left over
    a4.folder_for("2 W Saver", "2W", "ยาว/มืด")
_, err = a4.folder_for("2 W Saver", "2W", "ครึ่ง/สว่าง")
check("บอกว่าชื่อหมด", err and "รายชื่อของ 2W หมดแล้ว" in err)
check("บอกว่าที่ว่างเป็นของคนที่ส่งรูปคนละแบบ",
      err and "ยังมีที่ว่างอีก 1 เที่ยว แต่เป็นของคนที่ส่งรูปคนละแบบ" in err)

d5 = FakeDrive()
a5 = distribute.Allocator(d5, "week", SMALL, per_rider=2, seed=5)
for _ in range(10):
    a5.folder_for("2 W Saver", "2W", "ยาว/มืด")
_, err5 = a5.folder_for("2 W Saver", "2W", "ยาว/มืด")
check("ทุกคนเต็มจริง ๆ ก็บอกให้ไปขอชื่อเพิ่ม", err5 and "ต้องขอชื่อเพิ่มจาก Ops" in err5)
check("ตอนเต็มจริงต้องไม่พูดถึงที่ว่าง", err5 and "ที่ว่าง" not in err5)


def nm(fid):
    return distribute.bare(fid.rsplit("/", 1)[1])


# --- one rider, one kind of picture -------------------------------------------------------------
d6 = FakeDrive()
a6 = distribute.Allocator(d6, "week", POOL, per_rider=5, seed=6)
p1, _ = a6.folder_for("2 W Saver", "2W", "ยาว/มืด")
p2, _ = a6.folder_for("2 W Saver", "2W", "ยาว/มืด")
check("รูปแบบเดียวกันลงคนเดียวกัน", p1 == p2)
p3, _ = a6.folder_for("2 W Saver", "2W", "ยาว/สว่าง")
check("ธีมคนละแบบต้องคนละคน แม้คนแรกยังไม่เต็ม", p3 != p1)
p4, _ = a6.folder_for("2 W Saver", "2W", "ครึ่ง/มืด")
check("ยาวกับครึ่งก็ต้องคนละคน", p4 not in (p1, p3))
check("จำไว้ว่าใครส่งรูปแบบไหน",
      a6.new_styles == {nm(p1): "ยาว/มืด", nm(p3): "ยาว/สว่าง", nm(p4): "ครึ่ง/มืด"})
p5, _ = a6.folder_for("2 W Saver", "2W", "ยาว/สว่าง")
check("กลับมาแบบเดิมก็กลับไปหาคนเดิม", p5 == p3)

# what a previous round decided is honoured, and a rider from before the rule adopts one
d7 = FakeDrive()
cat7 = d7.ensure_folder("week", "2 W Saver")
old7 = d7.ensure_folder(cat7, "01-ก Win")
d7.images[old7] = 1
a7 = distribute.Allocator(d7, "week", POOL, per_rider=5, seed=7, styles={"ก Win": "ยาว/มืด"})
got, _ = a7.folder_for("2 W Saver", "2W", "ยาว/มืด")
check("ทำตามที่รอบก่อนตัดสินไว้", got == old7 and a7.made == 0)
other7, _ = a7.folder_for("2 W Saver", "2W", "ครึ่ง/สว่าง")
check("คนละแบบก็ไม่ไปลงทับ", other7 != old7)

d8 = FakeDrive()
cat8 = d8.ensure_folder("week", "2 W Saver")
legacy = d8.ensure_folder(cat8, "01-ก Win")
d8.images[legacy] = 1
a8 = distribute.Allocator(d8, "week", POOL, per_rider=5, seed=8)
g8, _ = a8.folder_for("2 W Saver", "2W", "ครึ่ง/สว่าง")
check("ไรเดอร์เก่าที่ยังไม่มีสไตล์ รับแบบแรกที่มาแล้วยึดไว้", g8 == legacy)
check("แล้วบันทึกไว้ให้รอบหน้า", a8.new_styles.get("ก Win") == "ครึ่ง/สว่าง")
check("จากนั้นแบบอื่นเข้าไม่ได้แล้ว", a8.folder_for("2 W Saver", "2W", "ยาว/มืด")[0] != legacy)

# a caller with nothing to say about style neither filters nor records
d9 = FakeDrive()
a9 = distribute.Allocator(d9, "week", POOL, per_rider=5, seed=9)
x1, _ = a9.folder_for("2 W Saver", "2W")
x2, _ = a9.folder_for("2 W Saver", "2W")
check("ไม่ได้บอกสไตล์มา ก็ไม่แยกและไม่จด", x1 == x2 and a9.new_styles == {})

# reading the whole week must not count the group it was asked about twice
d12 = FakeDrive()
cat12 = d12.ensure_folder("week", "2 W Saver")
d12.images[d12.ensure_folder(cat12, "01-ก Win")] = 3
a12 = distribute.Allocator(d12, "week", POOL, per_rider=5, seed=12)
a12.folder_for("2 W Saver", "2W")
check("อ่านสัปดาห์ทั้งหมดแล้วต้องไม่นับกลุ่มเดิมซ้ำ", a12.total["ก Win"] == 4)
check("และไม่มีไรเดอร์โผล่มาสองครั้ง", len(a12.groups["2 W Saver"]["riders"]) == 1)

# --- someone already on the books gets topped up before a new name is drawn --------------------
d10 = FakeDrive()
cat10 = d10.ensure_folder("week", "4 W Standard")
half = d10.ensure_folder(cat10, "01-ฉ Taxi")
d10.images[half] = 1
a10 = distribute.Allocator(d10, "week", POOL, per_rider=3, seed=10)
got10, _ = a10.folder_for("4 W Standard", "4W")
check("เติมคนที่ยังไม่เต็มก่อน ไม่เปิดคนใหม่", got10 == half and a10.made == 0)
check("ชื่อที่มีอยู่แล้วถูกจองไว้ ไม่ถูกหยิบซ้ำ", "ฉ Taxi" in a10.used)

# --- backfill: งานที่ลอยอยู่ในโฟลเดอร์ประเภทรถอยู่แล้ว ------------------------------------------
# The group folder is where the slip put it, and that already says which wheel — so a file whose
# name never mentioned a driver kind is no longer left behind.
d11 = FakeDrive()
cat11 = d11.ensure_folder("week", "2 W Saver")
d11.images[cat11] = [{"id": f"f{i}", "name": n} for i, n in enumerate(
    ["2W-Win kan_1+2_฿86.jpg", "2W-Win kan_3+4_฿90.jpg",
     "2W-Home bike_5+6_฿70.jpg", "LINE_ALBUM_x_7+8_฿60.jpg"])]
moved, stuck = distribute.backfill(d11, "week", ["2 W Saver"], POOL, per_rider=5, seed=11,
                                   dry_run=False, log=lambda *a: None)
check("ย้ายได้ทุกใบ ไม่ต้องพึ่งชื่อไฟล์", (moved, len(stuck)) == (4, 0))
check("ไม่มีอะไรลอยเหลือ", len(d11.images[cat11]) == 0)
check("สี่ใบลงคนเดียว (โควตา 5)", len(d11.tree["week/2 W Saver"]) == 1)

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
