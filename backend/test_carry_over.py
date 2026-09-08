# -*- coding: utf-8 -*-
"""A week with no seat left does not hold the work back (Ops, 2026-09-08).

When the allocator says the week is full — every name drawn, every rider at 21 — the originals
of what could not be placed go to the same album under NEXT week's pool, untouched, where the
next round pairs them again and hands them to next week's riders. Nothing is deleted, nothing
is stitched early, and the week folder is matched by what its name means, so one Ops spelled
'Week 7-13 Sep' and one made here are the same week.
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-carry-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import pool                                                     # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


# --- naming next week the way Ops does ---------------------------------------------------------
for name, want in [("Week 31 Aug-6 Sep", ("Week 7-13 Sep", "2026-09-07", "2026-09-13")),
                   ("Week 7-13 Sep", ("Week 14-20 Sep", "2026-09-14", "2026-09-20")),
                   ("Week 24-30 Aug", ("Week 31 Aug-6 Sep", "2026-08-31", "2026-09-06")),
                   ("Week 28 Sep-4 Oct", ("Week 5-11 Oct", "2026-10-05", "2026-10-11")),
                   ("week  21-27 Sep", ("week 28 Sep-4 Oct", "2026-09-28", "2026-10-04"))]:
    check(f"{name!r} → {want[0]!r}", pool.next_week_name(name) == want)
for name in ["Week test", "sandbox", "", "Pool"]:
    check(f"{name!r} อ่านวันไม่ออก → ไม่เดา", pool.next_week_name(name) is None)


class FakeDrive:
    def __init__(self):
        self.tree, self.moved = {"inbox": {}}, []

    def ensure_folder(self, pid, name):
        fid = f"{pid}/{name}"
        self.tree.setdefault(pid, {})[name] = fid
        self.tree.setdefault(fid, {})
        return fid

    def list_folders(self, pid):
        return [{"id": v, "name": k} for k, v in self.tree.get(pid, {}).items()]

    def move_file(self, fid, new_parent):
        self.moved.append((fid, new_parent))


# --- where next week's copy of the album lives -------------------------------------------------
d = FakeDrive()
wk = d.ensure_folder("inbox", "Week 31 Aug-6 Sep")
dest = pool.next_week_pool(d, "inbox", "Week 31 Aug-6 Sep", "2W", "2W-Win Lukpla=155")
check("สร้าง Week หน้า/Pool/กลุ่ม/อัลบั้ม ให้ครบ",
      dest == "inbox/Week 7-13 Sep/Pool/2W/2W-Win Lukpla=155")
check("สัปดาห์นี้ไม่ถูกแตะ", d.tree[wk] == {})

d2 = FakeDrive()
d2.ensure_folder("inbox", "Week 31 Aug-6 Sep")
ops_wk = d2.ensure_folder("inbox", "Week  7 - 13 Sep")        # Ops' own spelling, already there
ops_pool = d2.ensure_folder(ops_wk, "กอง")
dest2 = pool.next_week_pool(d2, "inbox", "Week 31 Aug-6 Sep", "2W", "2W-Win Lukpla=155")
check("สัปดาห์หน้าที่ Ops สร้างไว้แล้ว (สะกดต่างกัน) ถูกใช้ ไม่สร้างซ้ำ",
      dest2 == f"{ops_pool}/2W/2W-Win Lukpla=155" and len(d2.tree["inbox"]) == 2)

d3 = FakeDrive()
check("สัปดาห์ทดลองไม่มีสัปดาห์หน้า",
      pool.next_week_pool(d3, "inbox", "Week test", "2W", "x") is None and d3.tree == {"inbox": {}})

d4 = FakeDrive()
check("อัลบั้มที่วางตรงในโฟลเดอร์กลุ่ม ก็ไปโฟลเดอร์กลุ่มของสัปดาห์หน้า",
      pool.next_week_pool(d4, "inbox", "Week 31 Aug-6 Sep", "2W", "2W") == "inbox/Week 7-13 Sep/Pool/2W")

# --- the carry-over inside apply_moves ---------------------------------------------------------
# A stand-in allocator that has no seat at all: every trip is an overflow. The real one is
# covered by test_distribute; this is about what apply_moves does with its answer.
class FullAllocator:
    new_styles = {}

    def __init__(self, *a, **k):
        pass

    def folder_for(self, cat, wheel, style=None):
        return None, "สัปดาห์นี้เต็มแล้วสำหรับ 2W (145 ชื่อ × 21 เที่ยว ไม่เหลือที่นั่ง)"

    def kind_counts(self, wheel):
        return {"Win": 0, "Home": 0}


d5 = FakeDrive()
wk5 = d5.ensure_folder("inbox", "Week 31 Aug-6 Sep")
pool5 = d5.ensure_folder(wk5, "Pool")
alb5 = d5.ensure_folder(d5.ensure_folder(pool5, "2W"), "2W-Win Lukpla=155")
albums = [{"week": "Week 31 Aug-6 Sep", "week_id": wk5, "inbox_id": "inbox", "pool_id": pool5,
           "group": "2W", "album": "2W-Win Lukpla=155", "folder_id": alb5, "images": []}]
report = {"albums": [{"week": "Week 31 Aug-6 Sep", "album": "2W-Win Lukpla=155",
                      "pairs": [{"top": "a_1.jpg", "bottom": "a_2.jpg", "top_id": "t1", "bottom_id": "b1",
                                 "amount": 53.0, "target": "2 W Saver", "style": "ครึ่ง/สว่าง", "distance": 1}],
                      "long": [{"file": "a_3.jpg", "id": "l1", "target": "2 W Standard", "style": "ยาว/มืด"},
                               {"file": "a_4.jpg", "id": "l2", "target": None}]}],
          "totals": {}, "errors": []}
lines = []
moved = pool.apply_moves(d5, albums, {}, report, log=lines.append,
                         allocators={wk5: FullAllocator()}, issues=[])
carried_to = "inbox/Week 7-13 Sep/Pool/2W/2W-Win Lukpla=155"
check("ไม่มีที่นั่ง → ย้ายต้นฉบับทั้งคู่และรูปยาวไปอัลบั้มเดียวกันของสัปดาห์หน้า",
      sorted(d5.moved) == [("b1", carried_to), ("l1", carried_to), ("t1", carried_to)])
check("ไม่ได้ต่อรูป ไม่ได้ย้ายเข้าโฟลเดอร์ไรเดอร์ (ย้ายแล้ว = 0)", moved == 0)
check("นับว่ายกไป 2 รายการ (1 คู่ + 1 ยาว)", report["totals"].get("n_carried") == 2)
p = report["albums"][0]["pairs"][0]
check("ในรายงานบอกว่ายกไปที่ไหน", p.get("carried") and "ยกไป Week 7-13 Sep" in p["moved"])
check("รูปที่ไม่รู้ประเภทรถยังอยู่ที่เดิม ไม่ถูกยก",
      "ยังอยู่ในกอง" in report["albums"][0]["long"][1]["moved"] and "l2" not in [m[0] for m in d5.moved])
check("บันทึกในล็อกว่ายกไปกี่รายการ", any("ยกไป Week 7-13 Sep" in ln for ln in lines))
txt = pool.render({**report, "totals": {**report["totals"], "n_images": 4, "n_duplicates": 0, "n_long": 2,
                                       "n_pairs": 1, "pair_rate": None, "n_leftover": 0, "n_moved": 0},
                   "duplicates": [], "albums": [{**report["albums"][0], "group": "2W", "n_images": 4,
                                                 "n_duplicates": 0, "leftovers": []}]})
check("รายงานข้อความนับยกไปสัปดาห์หน้า และไม่ติดธง ⚠ ให้งานที่ยกไปแล้ว",
      "ยกไปสัปดาห์หน้า 2" in txt and "✔ เต็มสัปดาห์นี้ → ยกไป Week 7-13 Sep" in txt
      and "⚠ เต็มสัปดาห์นี้" not in txt)

# a sandbox week's overflow stays put, with the reason on the line
d6 = FakeDrive()
wk6 = d6.ensure_folder("inbox", "Week test")
pool6 = d6.ensure_folder(wk6, "Pool")
albums6 = [{"week": "Week test", "week_id": wk6, "inbox_id": "inbox", "pool_id": pool6,
            "group": "2W", "album": "2W-x", "folder_id": "x", "images": []}]
report6 = {"albums": [{"week": "Week test", "album": "2W-x", "pairs": [],
                       "long": [{"file": "a.jpg", "id": "l9", "target": "2 W Saver"}]}],
           "totals": {}, "errors": []}
pool.apply_moves(d6, albums6, {}, report6, log=lambda *_: None, allocators={wk6: FullAllocator()}, issues=[])
check("สัปดาห์ที่ไม่มีสัปดาห์หน้า: งานค้างพร้อมเหตุผล ไม่หาย",
      not d6.moved and "เต็มแล้ว" in report6["albums"][0]["long"][0]["moved"]
      and "n_carried" not in report6["totals"])

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
