# -*- coding: utf-8 -*-
"""Ops renames a mis-named rider folder at the source. The next round must land on the SAME
job under the new name — not open a second one and leave the week split in two."""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-rename-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")
import db                                                      # noqa: E402

db.init_db()
ok = True
FOLDER = "1AbCdEfGhIjK"          # the Drive folder id — stable across renames
WEEK = ("2026-08-17", "2026-08-23")

# round 1: the folder is called "01" and nobody has typed a name yet
job = db.create_job("01", "S", *WEEK, category="2 W Saver", folder_name="2 W Saver/Admin Yo/01",
                    admin="Yo", drive_folder_id=FOLDER)
db.create_trip(job, "227202.jpg", b"x", "image/jpeg")
print(f"1) รอบแรก: job #{job} ชื่อ '{db.get_job_meta(job)['driver_name']}'")

# round 2: Ops renamed the folder to "01 สมชาย"
found = db.find_job_by_folder(FOLDER, WEEK[0])
moved = db.attach_folder(found, FOLDER, "01 สมชาย", "2 W Saver/Admin Yo/01 สมชาย")
name = db.get_job_meta(job)["driver_name"]
print(f"2) หลังต้นทางแก้ชื่อ: เจอ job เดิม #{found} · เปลี่ยนชื่อ {moved.get('renamed')} · ตอนนี้ '{name}'")
if not (found == job and name == "01 สมชาย" and moved.get("renamed") == ("01", "01 สมชาย")):
    ok = False
    print("   ✗ ควรเจอ job เดิมและเปลี่ยนชื่อตามโฟลเดอร์")

# and the name-only lookup must NOT have opened a second job
by_name = db.find_job("01 สมชาย", *WEEK, category="2 W Saver", admin="Yo")
print(f"3) ค้นด้วยชื่อใหม่ได้ job #{by_name} (ต้องเป็น #{job} ตัวเดิม)")
if by_name != job:
    ok = False
    print("   ✗ ชื่อใหม่ควรชี้มาที่ job เดิม")

# a different folder with the same rider name in the same week stays its own job
other = db.create_job("01 สมชาย", "S", *WEEK, category="4 W Standard",
                      folder_name="4 W Standard/Admin Pla/01 สมชาย", admin="Pla",
                      drive_folder_id="ZZZotherfolder")
print(f"4) โฟลเดอร์อื่น (คนละกลุ่มรถ) → job #{other} แยกกันอยู่: {other != job}")
if other == job:
    ok = False

# an old job created before folder ids existed still gets adopted, not duplicated
legacy = db.create_job("มานะ", "S", *WEEK, category="2 W Saver", admin="Yo")
db.attach_folder(legacy, "LEGACYFOLDER", "มานะ", "2 W Saver/Admin Yo/มานะ")
print(f"5) job เก่าที่ยังไม่มี folder id → ผูก id ให้แล้ว: "
      f"{db.find_job_by_folder('LEGACYFOLDER', WEEK[0]) == legacy}")
if db.find_job_by_folder("LEGACYFOLDER", WEEK[0]) != legacy:
    ok = False

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
