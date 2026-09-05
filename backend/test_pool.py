# -*- coding: utf-8 -*-
"""A pool run must report pairs and duplicates, write previews only under _รายงาน, and leave every
album file exactly where it was. Runs on a small copy of the Phase2 sample (skipped if absent)."""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-pool-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

SAMPLE = "Phase2/Test 7"
if not os.path.isdir(SAMPLE):
    print("ไม่มีตัวอย่าง Phase2/Test 7 — ข้าม")
    sys.exit(0)
try:
    import rapidocr_onnxruntime  # noqa: F401
except ImportError:
    print("ไม่มี rapidocr — ข้าม (pip install -r backend/requirements-pairing.txt)")
    sys.exit(0)

import db                                                       # noqa: E402
import pool                                                     # noqa: E402

# --- a pool on disk: one week, one group, one album of 12 halves + 1 exact duplicate ---
root = os.path.join(WORK, "Inbox")
album = os.path.join(root, "Week 17-23 Aug", "Pool", "4W", "4W-Taxi Dl-boy4 w")
os.makedirs(os.path.join(root, "Week 17-23 Aug", "2 W Saver", "Admin Yo"))   # the usual rider side, empty
os.makedirs(album)
files = sorted(os.listdir(SAMPLE), key=lambda f: int(f.rsplit("_", 1)[1].split(".")[0]))[:12]
for f in files:
    shutil.copy2(os.path.join(SAMPLE, f), os.path.join(album, f))
shutil.copy2(os.path.join(SAMPLE, files[0]), os.path.join(album, "4W-Taxi Dl-boy4 w_260902_99.jpg"))
# two more halves dropped loose into Pool/ itself (no album folder) — must count as their own album
pool_dir = os.path.join(root, "Week 17-23 Aug", "Pool")
loose = sorted(os.listdir(SAMPLE), key=lambda f: int(f.rsplit("_", 1)[1].split(".")[0]))[12:14]
for f in loose:
    shutil.copy2(os.path.join(SAMPLE, f), os.path.join(pool_dir, f))
before = sorted(os.listdir(album))

db.init_db()
db.name_pool_load([(f"คนขับ{i}", "4W", "Taxi") for i in range(1, 6)]
                  + [(f"วิน{i}", "2W", "Win") for i in range(1, 6)])
rc = pool.main(["--local", root])
ok = rc == 0
print("1) รันจบ:", rc == 0)

after = sorted(os.listdir(album))
print("2) ไฟล์ในอัลบั้มไม่ถูกย้าย/ลบ/เพิ่ม:", before == after)
ok = ok and before == after

runs = db.recent_pool_runs(1, with_report=True)
r = runs[0] if runs else {}
print(f"3) บันทึกลงฐานข้อมูล: pairs={r.get('n_pairs')} dup={r.get('n_duplicates')} leftover={r.get('n_leftover')}")
ok = ok and (r.get("n_pairs") or 0) >= 4 and r.get("n_duplicates") == 1
rep_json = __import__("json").loads(r["report"])
names = [a["album"] for a in rep_json["albums"]]
print("3b) รูปที่วางตรง ๆ ใน Pool ถูกนับเป็นอัลบั้ม '(กองรวม)':", "(กองรวม)" in names, "· รูปรวม", r.get("n_images"))
ok = ok and "(กองรวม)" in names and r.get("n_images") == 15
if not ((r.get("n_pairs") or 0) >= 4 and r.get("n_duplicates") == 1):
    print("   ✗ ควรได้อย่างน้อย 4 คู่ และรูปซ้ำ 1")

rep = os.path.join(root, "Week 17-23 Aug", "Pool", "_รายงาน")
previews = []
for dp, _, fs in os.walk(rep):
    previews += [f for f in fs if f.endswith(".jpg")]
txts = [f for f in os.listdir(rep) if f.endswith(".txt")] if os.path.isdir(rep) else []
print(f"4) รูปที่ต่อแล้วใน _รายงาน: {len(previews)} · รายงาน txt: {len(txts)}")
ok = ok and len(previews) == r.get("n_pairs") and len(txts) == 1

# a second run must see _รายงาน as not-an-album and report the same numbers
rc2 = pool.main(["--local", root, "--no-preview"])
r2 = db.recent_pool_runs(1, with_report=True)[0]
cached = __import__("json").loads(r2["report"]).get("ocr_cached")
print(f"5) รันซ้ำได้ผลเท่าเดิม: {r2['n_pairs'] == r['n_pairs'] and r2['n_images'] == r['n_images']} · ใช้ผล OCR เดิม {cached} รูป (ต้อง 14)")
ok = ok and rc2 == 0 and r2["n_pairs"] == r["n_pairs"] and r2["n_images"] == r["n_images"] and cached == 14

# the old ingest must walk past the pool: no items from it, no warning about it
import ingest                                                   # noqa: E402
from drive_client import LocalDrive                             # noqa: E402
items, skipped = ingest.discover(LocalDrive(root), root)
pool_warn = [s for s in skipped if "Pool" in s or "pool" in s]
print(f"6) ingest เดิมมองข้ามกอง: รูปที่จะอ่าน {len(items)} (ต้อง 0) · คำเตือนเรื่อง Pool {len(pool_warn)} (ต้อง 0)")
ok = ok and not items and not pool_warn

# --- move mode on the same pool: stitched pairs land in Week/<category>/, originals go to
# Pool/_ใช้แล้ว/<album>/, leftovers stay, a second run finds nothing more to do
n_pairs_before = r["n_pairs"]
rc3 = pool.main(["--local", root, "--move"])
r3 = db.recent_pool_runs(1, with_report=True)[0]
week_dir = os.path.join(root, "Week 17-23 Aug")
cats = [c for c in os.listdir(week_dir) if c.lower().startswith(("2 w", "4 w"))]
print("7a) ไม่มีโฟลเดอร์ 4 W Saver (ทริป Saver Car ไป 4 W Standard):", "4 W Saver" not in cats)
ok = ok and "4 W Saver" not in cats
stitched = [f for c in cats
            for dp, _, fs in os.walk(os.path.join(week_dir, c)) for f in fs if f.endswith(".jpg")]
used = os.path.join(pool_dir, "_ใช้แล้ว")
used_files = [f for dp, _, fs in os.walk(used) for f in fs] if os.path.isdir(used) else []
album_left = [f for f in os.listdir(album) if f.endswith(".jpg")]
print(f"7) ย้ายจริง: rc={rc3} mode={r3['mode']} · รูปต่อแล้วในโฟลเดอร์ประเภทรถ {len(stitched)} ({cats}) · "
      f"ต้นฉบับใน _ใช้แล้ว {len(used_files)} · เหลือในอัลบั้ม {len(album_left)}")
n_moved = __import__("json").loads(r3["report"])["totals"].get("n_moved")
ok = ok and rc3 == 0 and r3["mode"] == "move" and len(stitched) == n_moved
ok = ok and len(stitched) >= 4 and len(used_files) == 2 * len([f for f in stitched if "+" in f]) \
     and len(album_left) == 13 - 2 * len([f for f in stitched if "Dl-boy4" in f])
# rider folders, not loose files in the category folder — ingest only ever walks folders
homes = sorted({os.path.basename(dp) for c in cats
                for dp, _, fs in os.walk(os.path.join(week_dir, c))
                if any(f.endswith(".jpg") for f in fs)})
print(f"7b) ไฟล์ที่ต่อแล้วอยู่ในโฟลเดอร์ไรเดอร์ {homes} (ไม่ใช่ไฟล์ลอยในโฟลเดอร์ประเภทรถ)")
ok = ok and homes and all(d.endswith((" Taxi", " Win", " Home")) for d in homes)

# the loose pile in Pool/ has no album name to say what kind of driver it belongs to, so it is
# left alone every run — a wrong sheet would spread wrong names across the week
rc4 = pool.main(["--local", root, "--move"])
r4 = db.recent_pool_runs(1)[0]
print(f"8) ย้ายซ้ำ: คู่ใหม่ {r4['n_pairs']} (เหลือแต่กองลอยที่ไม่รู้ประเภทคนขับ)")
ok = ok and rc4 == 0 and r4["n_pairs"] == 1
loose_left = [f for f in os.listdir(pool_dir) if f.endswith(".jpg")]
print(f"9) กองลอยยังอยู่ที่เดิม {len(loose_left)} ใบ (ต้อง 2)")
ok = ok and len(loose_left) == 2

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
