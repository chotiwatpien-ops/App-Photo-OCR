# -*- coding: utf-8 -*-
"""Next week's rider folders, drawn from Ops' name list (2026-09-05).

Most of a week carries over from the week before and the rest rotates. The two things that must
never happen: one name standing for two riders in the same week, and a rotation being reported
that the pool could not actually deliver.
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-roster-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import db                                                       # noqa: E402
import roster                                                   # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


def pool(n, kind, start=1):
    return [(f"{kind}{i}", kind) for i in range(start, start + n)]


check("ป้ายต่อท้ายชื่อ", roster.label("ตฤณ", "Taxi") == "ตฤณ Taxi")
check("ตัดเลขนำหน้าและช่องว่างส่วนเกิน", roster.bare("01-ตฤณ Taxi ") == "ตฤณ Taxi")
check("รูปแบบ '01 - ชื่อ' ก็อ่านออก", roster.bare("01 - ตฤณ Win") == "ตฤณ Win")
check("รูปแบบ '01.ชื่อ' ก็อ่านออก", roster.bare("01.พิชิต Home") == "พิชิต Home")
check("ชื่อเปล่าไม่มีเลขนำ", roster.bare("กิตติพงศ์ Win") == "กิตติพงศ์ Win")

# --- พูลใหญ่พอ: หมุนได้ตามที่ขอ ---------------------------------------------------------------
pools = {"2W": pool(200, "Win"), "4W": pool(200, "Taxi")}
first, _ = roster.plan({"2 W Saver": [], "2 W Standard": [], "4 W Standard": []},
                       pools, per_group=10, keep=0.8, seed=1)
check("วีคแรก: ได้ครบทุกกลุ่ม", all(len(v) == 10 for v in first.values()))
allnames = [n for v in first.values() for n in v]
check("วีคแรก: ไม่มีชื่อซ้ำข้ามกลุ่ม", len(allnames) == len(set(allnames)))
check("2 W ดึงจากพูล 2W · 4 W ดึงจากพูล 4W",
      all(n.startswith("Win") for n in first["2 W Saver"])
      and all(n.startswith("Taxi") for n in first["4 W Standard"]))

second, notes = roster.plan(first, pools, per_group=10, keep=0.8, seed=2)
kept = set(second["2 W Saver"]) & set(first["2 W Saver"])
check("วีคสอง: เก็บชื่อเดิมไว้ 80%", len(kept) == 8)
check("วีคสอง: เปลี่ยนใหม่ 20%", len(set(second["2 W Saver"]) - set(first["2 W Saver"])) == 2)
allnames2 = [n for v in second.values() for n in v]
check("วีคสอง: ยังไม่มีชื่อซ้ำข้ามกลุ่ม", len(allnames2) == len(set(allnames2)))

# --- พูลตึง: หมุนได้เท่าที่มี และต้องบอกตามจริง ------------------------------------------------
# ของจริงฝั่ง 2 W คือ 145 ชื่อ ต่อ 140 ที่นั่ง — ขอ 20% ได้จริงแค่ 3.6%
tight = {"2W": pool(21, "Win"), "4W": pool(50, "Taxi")}
w1, _ = roster.plan({"2 W Saver": [], "2 W Standard": []}, tight, per_group=10, keep=0.8, seed=3)
w2, notes = roster.plan(w1, tight, per_group=10, keep=0.8, seed=4)
check("พูลตึง: ยังได้คนครบทุกกลุ่ม", all(len(v) == 10 for v in w2.values()))
# 21 ชื่อ 20 ที่นั่ง → มีคนพักแค่ 1 คน หมุนได้จริงทั้งวีคก็แค่ 1 ไม่ใช่ 20% ของทุกกลุ่ม
last = {n for v in w1.values() for n in v}
fresh = len({n for v in w2.values() for n in v} - last)
check("พูลตึง: หมุนได้เท่าที่มีคนพัก ไม่ยัดให้ครบ 20%", fresh <= 1)
check("พูลตึง: ชื่อที่หลุดกลุ่มหนึ่งไม่ถูกนับเป็นคนใหม่ในอีกกลุ่ม",
      len({n for v in w2.values() for n in v} & last) >= 19)
check("พูลตึง: รายงานบอกจำนวนที่หมุนได้จริง", "ใหม่" in notes["2 W Saver"])
both = [n for v in w2.values() for n in v]
check("พูลตึง: ยังไม่มีชื่อซ้ำข้ามกลุ่ม", len(both) == len(set(both)))

# --- พูลไม่พอจริงๆ: ต้องบอกว่าขาด ไม่ใช่เงียบ --------------------------------------------------
short, notes = roster.plan({"2 W Saver": [], "2 W Standard": []},
                           {"2W": pool(15, "Win"), "4W": []}, per_group=10, keep=0.8, seed=5)
check("พูลไม่พอ: กลุ่มหลังได้ไม่ครบ", len(short["2 W Standard"]) == 5)
check("พูลไม่พอ: เตือนว่าขาด", "ขาด" in notes["2 W Standard"])

# --- ชื่อเดียวกันคนละประเภท เป็นคนละคน ---------------------------------------------------------
mixed = {"2W": [("พิชิต", "Home"), ("ตฤณ", "Win")], "4W": [("พิชิต", "Home"), ("ตฤณ", "Taxi")]}
m, _ = roster.plan({"2 W Saver": [], "4 W Standard": []}, mixed, per_group=2, keep=0.8, seed=6)
check("ตฤณ Win กับ ตฤณ Taxi อยู่คนละกลุ่มได้ (คนละคน)",
      "ตฤณ Win" in m["2 W Saver"] and "ตฤณ Taxi" in m["4 W Standard"])
check("พิชิต Home ที่ชนกันสองพูล ถูกใช้ครั้งเดียวในวีค",
      sum(v.count("พิชิต Home") for v in m.values()) == 1)

# --- นำเข้ารายชื่อ ----------------------------------------------------------------------------
n = db.name_pool_load([("ก", "2W", "Win"), ("ข", "2W", "Home"), ("ค", "4W", "Taxi")])
check("เก็บรายชื่อลงฐานข้อมูลได้", n == 3)
check("ดึงตามล้อได้", db.name_pool_for("2W") == [("ก", "Win"), ("ข", "Home")])
db.name_pool_load([("ง", "4W", "Taxi")])
check("โหลดใหม่แทนที่ของเดิม ไม่ต่อท้าย", db.name_pool_for("2W") == [])

# --- สั่งสร้างซ้ำต้องไม่บวกทบ -----------------------------------------------------------------
class FakeDrive:
    """Drive จำลองแค่พอให้รู้ว่ามีโฟลเดอร์อะไรอยู่ — การสุ่มไม่ล็อก seed สั่งสองรอบจึงได้คนละชุด"""

    def __init__(self):
        self.tree = {"inbox": {}}

    def list_folders(self, pid):
        return [{"id": f"{pid}/{n}", "name": n} for n in self.tree.get(pid, {})]

    def ensure_folder(self, pid, name):
        fid = f"{pid}/{name}"
        self.tree.setdefault(pid, {})[name] = fid
        self.tree.setdefault(fid, {})
        return fid


fd = FakeDrive()
fd.ensure_folder("inbox", "Week 7-13 Sep")
p1, _ = roster.plan({"2 W Saver": []}, {"2W": pool(50, "Win")}, per_group=10, keep=0.8, seed=11)
roster.apply(fd, "inbox", "Week 7-13 Sep", p1, dry_run=False, per_group=10)
check("สร้างรอบแรกได้ครบ 10", len(fd.tree["inbox/Week 7-13 Sep/2 W Saver"]) == 10)
p2, _ = roster.plan({"2 W Saver": []}, {"2W": pool(50, "Win")}, per_group=10, keep=0.8, seed=99)
roster.apply(fd, "inbox", "Week 7-13 Sep", p2, dry_run=False, per_group=10)
check("สั่งซ้ำด้วยชุดสุ่มใหม่: ไม่บวกทบ ยังคง 10",
      len(fd.tree["inbox/Week 7-13 Sep/2 W Saver"]) == 10)

fd2 = FakeDrive()
fd2.ensure_folder("inbox", "W")
roster.apply(fd2, "inbox", "W", {"2 W Saver": p1["2 W Saver"][:4]}, dry_run=False, per_group=10)
roster.apply(fd2, "inbox", "W", p1, dry_run=False, per_group=10)
check("มีอยู่บางส่วน: เติมจนครบ 10 พอดี", len(fd2.tree["inbox/W/2 W Saver"]) == 10)

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
