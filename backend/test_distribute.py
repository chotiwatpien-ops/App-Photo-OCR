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

# --- the style rule is applied last, not dropped (Ops, 2026-09-08) -----------------------------
# Run 20:32 had 194 free seats on the 2W side and 117 trips it refused to place, because every
# free seat belonged to somebody whose pictures look different and the list had no name left.
# Ops relaxed the rule: such a person is still the LAST one offered a trip — after everyone who
# matches, after every unused name — but no longer nobody.
d4 = FakeDrive()
a4 = distribute.Allocator(d4, "week", SMALL, per_rider=2, seed=4)
for _ in range(9):                                     # 5 names × 2 seats, one seat left over
    a4.folder_for("2 W Saver", "2W", "ยาว/มืด")
last, err = a4.folder_for("2 W Saver", "2W", "ครึ่ง/สว่าง")
check("ชื่อหมดและไม่มีคนแบบเดียวกัน → ลงที่นั่งที่เหลือ ไม่ใช่ค้าง", last and not err)
check("ที่นั่งนั้นเป็นของคนที่ส่งรูปคนละแบบ และถูกจดไว้ว่าใคร",
      a4.mixed == {nm4: {"ครึ่ง/สว่าง"} for nm4 in [distribute.bare(last.rsplit("/", 1)[1])]})
check("สไตล์ที่จำไว้ของคนนั้นไม่เปลี่ยน",
      a4.styles[distribute.bare(last.rsplit("/", 1)[1])] == "ยาว/มืด")

d5 = FakeDrive()
a5 = distribute.Allocator(d5, "week", SMALL, per_rider=2, seed=5)
for _ in range(10):
    a5.folder_for("2 W Saver", "2W", "ยาว/มืด")
_, err5 = a5.folder_for("2 W Saver", "2W", "ยาว/มืด")
check("ทุกที่นั่งเต็มจริง ๆ ถึงจะบอกว่าเต็ม", err5 and "เต็มแล้ว" in err5 and "5 ชื่อ × 2 เที่ยว" in err5)
check("ตอนเต็มบอกทางออกทั้งสอง: สัปดาห์หน้า หรือขอชื่อ",
      err5 and "สัปดาห์หน้า" in err5 and "ขอชื่อเพิ่ม" in err5)
_, err5b = a5.folder_for("2 W Saver", "2W", "ครึ่ง/สว่าง")
check("เต็มก็คือเต็ม ไม่ว่ารูปแบบไหน", err5b and "เต็มแล้ว" in err5b)

# the order: someone who matches, then a fresh name, and only then someone who does not match
d4b = FakeDrive()
a4b = distribute.Allocator(d4b, "week", SMALL, per_rider=3, seed=41)
f1, _ = a4b.folder_for("2 W Saver", "2W", "ยาว/มืด")
f2, _ = a4b.folder_for("2 W Saver", "2W", "ครึ่ง/สว่าง")
check("ยังมีชื่อว่าง → รูปคนละแบบได้ชื่อใหม่ ไม่ปนกับคนแรก", f2 != f1 and not a4b.mixed)
f3, _ = a4b.folder_for("2 W Saver", "2W", "ยาว/มืด")
check("แบบเดียวกันกลับไปหาคนเดิมก่อนเปิดชื่อใหม่", f3 == f1 and a4b.made == 2)
while len(a4b.used) < 5:                               # draw every remaining name with ยาว/มืด
    a4b.folder_for("2 W Standard", "2W", "ยาว/มืด")
f4, e4 = a4b.folder_for("2 W Saver", "2W", "ครึ่ง/สว่าง")
check("ชื่อหมดแล้ว แบบเดิมของตัวเองมีที่ → ไปหาคนเดิม ไม่ปนใคร", f4 == f2 and not a4b.mixed)
f5, _ = a4b.folder_for("2 W Saver", "2W", "ครึ่ง/สว่าง")
f6, _ = a4b.folder_for("2 W Saver", "2W", "ครึ่ง/สว่าง")
check("คนเดิมเต็มแล้ว ชื่อหมดแล้ว → ตอนนี้จึงยอมปน และจดไว้",
      f5 == f2 and f6 != f2 and f6 is not None and len(a4b.mixed) == 1)

# and when it comes to that, the fullest person with room, so the mix touches the fewest folders
d4e = FakeDrive()
a4e = distribute.Allocator(d4e, "week", {("2W", "Win"): ["ก", "ข"], ("2W", "Home"): [],
                                          ("4W", "Taxi"): [], ("4W", "Home"): []},
                           per_rider=4, seed=44)
one, _ = a4e.folder_for("2 W Saver", "2W", "ยาว/มืด")
three = [a4e.folder_for("2 W Saver", "2W", "ยาว/สว่าง")[0] for _ in range(3)][0]
m1, _ = a4e.folder_for("2 W Saver", "2W", "ครึ่ง/สว่าง")
check("ปนกับคนที่แน่นที่สุดก่อน (3/4 ก่อน 1/4)", m1 == three)
m2, _ = a4e.folder_for("2 W Saver", "2W", "ครึ่ง/สว่าง")
check("คนนั้นเต็มแล้วค่อยไปคนถัดไป", m2 == one and len(a4e.mixed) == 2)

# the mix is also allowed across groups — the same person's second folder — and still last
d4c = FakeDrive()
a4c = distribute.Allocator(d4c, "week", {("2W", "Win"): ["ก"], ("2W", "Home"): [],
                                          ("4W", "Taxi"): [], ("4W", "Home"): []},
                           per_rider=3, seed=42)
a4c.folder_for("2 W Saver", "2W", "ยาว/มืด")
g, e = a4c.folder_for("2 W Standard", "2W", "ครึ่ง/สว่าง")
check("คนเดียวในรายชื่อ กลุ่มอื่น รูปคนละแบบ → ยังได้โฟลเดอร์ที่สอง ไม่ค้าง",
      g and not e and g.endswith("2 W Standard/01-ก Win") and a4c.mixed == {"ก Win": {"ครึ่ง/สว่าง"}})

# --- a quota for one wheel count only (Ops, 2026-09-08 23:50: 'it is only 2 W Saver that is short')
d4f = FakeDrive()
a4f = distribute.Allocator(d4f, "week", SMALL, per_rider=2, seed=45, quota={"2W": 3})
bike = [a4f.folder_for("2 W Saver", "2W")[0] for _ in range(3)]
check("2W ใช้โควตาของตัวเอง: สามใบแรกลงคนเดียว (โควตา 3)", len(set(bike)) == 1)
check("ใบที่สี่ค่อยเปิดคนใหม่", a4f.folder_for("2 W Saver", "2W")[0] != bike[0])
car = [a4f.folder_for("4 W Standard", "4W")[0] for _ in range(3)]
check("4W ยัง 2 ตามเดิม: ใบที่สามเป็นคนที่สอง", car[0] == car[1] != car[2])
for _ in range(20):
    a4f.folder_for("2 W Saver", "2W")
_, e4f = a4f.folder_for("2 W Saver", "2W")
check("ข้อความตอนเต็มบอกโควตาของล้อนั้น", e4f and "× 3 เที่ยว" in e4f)
check("ไม่ระบุโควตาต่อล้อ ก็ใช้ตัวเลขเดียวทุกล้อ",
      distribute.Allocator(FakeDrive(), "week", SMALL, per_rider=5)._quota("2 W Saver", "2W") == 5)

# and for ONE group: '2W "Saver"' — the extra seats are for Saver trips, a Standard fare for
# the same person still stops at the week's figure
d4g = FakeDrive()
a4g = distribute.Allocator(d4g, "week", {("2W", "Win"): ["ก"], ("2W", "Home"): [],
                                          ("4W", "Taxi"): [], ("4W", "Home"): []},
                           per_rider=2, seed=46, quota={"2 W Saver": 4})
a4g.folder_for("2 W Standard", "2W"); a4g.folder_for("2 W Standard", "2W")     # ก at 2 = the 21
_, e_std = a4g.folder_for("2 W Standard", "2W")
check("Standard ใบที่สามของคนเดียวกัน: เต็มตามโควตาปกติ", e_std is not None)
s3, _ = a4g.folder_for("2 W Saver", "2W")
s4, _ = a4g.folder_for("2 W Saver", "2W")
check("แต่งาน Saver ยังลงคนเดิมได้ถึง 4 (โฟลเดอร์ที่สองในกลุ่ม Saver)",
      s3 and s4 == s3 and s3.endswith("2 W Saver/01-ก Win") and a4g.total["ก Win"] == 4)
_, e_sv = a4g.folder_for("2 W Saver", "2W")
check("Saver ใบที่ห้า: เต็มที่ 4 และข้อความบอก × 4", e_sv and "× 4 เที่ยว" in e_sv)

# a caller with no style never trips the mixing record
d4d = FakeDrive()
a4d = distribute.Allocator(d4d, "week", SMALL, per_rider=2, seed=43)
for _ in range(10):
    a4d.folder_for("2 W Saver", "2W")
check("ไม่บอกสไตล์ = ไม่มีอะไรให้ปน", not a4d.mixed and not a4d.new_styles)


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

# A Drive id is not a name. Reading one out of the folder id worked only for folders this run
# had just made; topping up someone already working gave 'yW9Sxa_HhW7ED1QvyfZP', which came
# within one button of being written into the workbook as a driver.
d13 = FakeDrive()
cat13 = d13.ensure_folder("week", "2 W Saver")
existing = d13.ensure_folder(cat13, "07-สมชาย Win")
d13.tree[cat13]["07-สมชาย Win"] = "1yW9Sxa_HhW7ED1QvyfZP"      # a real Drive id, not a path
d13.tree["1yW9Sxa_HhW7ED1QvyfZP"] = {}
d13.images["1yW9Sxa_HhW7ED1QvyfZP"] = 2
a13 = distribute.Allocator(d13, "week", POOL, per_rider=21, seed=13)
got13, _ = a13.folder_for("2 W Saver", "2W")
check("เติมคนเดิมที่ id เป็นรหัส Drive จริง", got13 == "1yW9Sxa_HhW7ED1QvyfZP")
check("ถามชื่อจาก allocator ได้ชื่อคน ไม่ใช่รหัส", a13.rider_at(got13) == "สมชาย Win")
check("ตัดท้าย id เอาเองจะได้ขยะ (นี่คือบั๊กที่เจอ)",
      distribute.bare(got13.rsplit("/", 1)[-1]) == "yW9Sxa_HhW7ED1QvyfZP")
new13, _ = a13.folder_for("2 W Standard", "2W")
check("โฟลเดอร์ที่เพิ่งสร้างก็ถามชื่อได้เหมือนกัน", a13.rider_at(new13) == "สมชาย Win")
check("โฟลเดอร์ที่ไม่รู้จักตอบว่าไม่รู้ ไม่เดา", a13.rider_at("ไม่มีอยู่จริง") is None)

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

# --- a person drives one kind of vehicle; a spare seat is not a licence for the other wheel ---
# Run 131 opened '4 W Standard/13-ดวงพร Win' for the car album Rabbit=246: the Win rider had
# room left over from 2 W Saver, and the borrowing loop looked at every group of the week and
# never at the wheel.
d14 = FakeDrive()
a14 = distribute.Allocator(d14, "week", SMALL, per_rider=4, seed=14)
sv14, _ = a14.folder_for("2 W Saver", "2W")
car14, err14 = a14.folder_for("4 W Standard", "4W")
check("งานรถยนต์ไม่ไปยืมคนขี่วินที่ยังว่าง",
      car14 and distribute.bare(car14.rsplit("/", 1)[1]) != distribute.bare(sv14.rsplit("/", 1)[1]))
check("แต่ได้ชื่อจากรายชื่อ 4W ตามปกติ",
      car14 and distribute.bare(car14.rsplit("/", 1)[1]).split()[-1] in ("Taxi", "Home"))
bike14, _ = a14.folder_for("2 W Standard", "2W")
check("ส่วนงานวินยังยืมคนเดิมข้ามกลุ่ม Saver/Standard ได้เหมือนเดิม",
      distribute.bare(bike14.rsplit("/", 1)[1]) == distribute.bare(sv14.rsplit("/", 1)[1]))
# and the other way round — run 132 did this eight times over: every 2W name was used up, so
# the bike albums borrowed the car riders who still had room ('2 W Saver/125-ยอดยิ่ง Taxi')
d16 = FakeDrive()
a16 = distribute.Allocator(d16, "week", SMALL, per_rider=2, seed=16)
car16, _ = a16.folder_for("4 W Standard", "4W")
for _ in range(2 * 5):                       # 5 bike names × 2 trips: the 2W list is now empty
    a16.folder_for("2 W Saver", "2W")
bike16, err16 = a16.folder_for("2 W Standard", "2W")
check("ชื่อวินหมดแล้ว ก็ต้องบอกว่าหมด ไม่ไปยืมคนขับรถยนต์ที่ยังว่าง", bike16 is None and err16)
bike_folders16 = (list(d16.tree.get("week/2 W Saver", {})) + list(d16.tree.get("week/2 W Standard", {})))
check("คนขับรถยนต์ยังอยู่โฟลเดอร์เดิมของเขา",
      bike_folders16 and all(distribute.bare(n).split()[-1] != "Taxi" for n in bike_folders16))

# a folder already opened on the wrong side must not be topped up either, or emptying it with
# the cleanup only fills it again next round
d17 = FakeDrive()
d17.ensure_folder("week", "4 W Standard")
# the fuller folder is topped up first, so the wrong-side one is made the fuller of the two —
# a test where the right answer is also the fullest proves nothing
d17.images[d17.ensure_folder("week/4 W Standard", "13-ดวงพร Win")] = 2
d17.images[d17.ensure_folder("week/4 W Standard", "14-ฉ Taxi")] = 1
a17 = distribute.Allocator(d17, "week", SMALL, per_rider=4, seed=17)
got17, _ = a17.folder_for("4 W Standard", "4W")
check("โฟลเดอร์วินที่ค้างอยู่ในรถยนต์ไม่ถูกเติม", distribute.bare(got17.rsplit("/", 1)[1]) != "ดวงพร Win")
check("ไปลงคนขับรถยนต์ที่อยู่ในกลุ่มแทน", distribute.bare(got17.rsplit("/", 1)[1]) == "ฉ Taxi")
check("Home พิมพ์มือในกลุ่มตัวเองยังถูกเติมตามปกติ", not a17._misplaced("ตึก Home", "4W"))

# a rider folder typed by hand that is on no list: the kind on the folder decides
d15 = FakeDrive()
d15.ensure_folder("week", "2 W Saver")
d15.images[d15.ensure_folder("week/2 W Saver", "01-มือ Win")] = 1
d15.ensure_folder("week", "4 W Standard")
d15.images[d15.ensure_folder("week/4 W Standard", "01-มือ Taxi")] = 1
d15.images[d15.ensure_folder("week/4 W Standard", "02-ตึก Home")] = 1
a15 = distribute.Allocator(d15, "week", {}, per_rider=4, seed=15)
check("ชื่อนอกรายชื่อ ยืมได้เฉพาะล้อที่ท้ายชื่อบอก",
      a15._drives("มือ Win", "2W") and not a15._drives("มือ Win", "4W")
      and a15._drives("มือ Taxi", "4W") and not a15._drives("มือ Taxi", "2W"))
check("Home ใช้ทั้งสองล้อ ตัดสินไม่ได้ก็ไม่ยืมข้าม",
      not a15._drives("ตึก Home", "2W") and not a15._drives("ตึก Home", "4W"))

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
