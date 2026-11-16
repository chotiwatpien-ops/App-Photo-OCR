# -*- coding: utf-8 -*-
"""กองไม่ลงงานในสัปดาห์ที่ปิดแล้ว และไม่ลงเกินเป้าของกลุ่ม (เฟส 1, 2026-09-17).

สองกฎนี้แทนการ 'ยกทีหลัง' ซึ่ง W37 ต้องทำสี่รอบ ทุกครั้งที่ยกคือย้ายทั้งแถว รูปรวมร่าง รูปส่งลูกค้า
และชื่อรูป — ต้นเหตุที่ลูกค้าเปิดไฟล์แล้วหารูปตามชื่อไม่เจอ
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-room-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from sqlalchemy import insert                                    # noqa: E402

import config                                                    # noqa: E402
import db                                                        # noqa: E402
import pool                                                      # noqa: E402
from drive_client import LocalDrive                              # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


W37, W37_END = "2026-09-07", "2026-09-13"
check("อ่านวันแรกของสัปดาห์จากชื่อโฟลเดอร์ได้", pool.week_starts("Week 7-13 Sep") == W37)
check("ชื่อที่ไม่ใช่สัปดาห์ → None", pool.week_starts("Test 7") is None)

# --- กองข้ามสัปดาห์ที่ปิดแล้ว -------------------------------------------------------------------
ROOT = os.path.join(WORK, "inbox")
for wk in ("Week 31 Aug-6 Sep", "Week 7-13 Sep"):
    d = os.path.join(ROOT, wk, "Pool", "2W-Win อัลบั้ม")
    os.makedirs(d)
    open(os.path.join(d, "a.jpg"), "wb").write(bytes([0xFF, 0xD8]))
drive = LocalDrive(ROOT)

seen = pool.scan_inbox(drive, ROOT)
check("ไม่มีสัปดาห์ไหนปิด: เห็นกองทั้งสองสัปดาห์", sorted(a["week"] for a in seen) == ["Week 31 Aug-6 Sep", "Week 7-13 Sep"])
seen = pool.scan_inbox(drive, ROOT, closed={W37})
check("ปิด W37 แล้ว: กองของ W37 ไม่ถูกหยิบมาจัด", [a["week"] for a in seen] == ["Week 31 Aug-6 Sep"])

# --- ที่ว่างของสัปดาห์ตามเป้าลูกค้า (ยังไม่เผื่อ) ---------------------------------------------------
config.POOL_RESERVE_PCT, config.POOL_RESERVE_MIN = 0, 0
job = db.create_job("สมชาย Win", "Trips", W37, W37_END, category="2 W Standard")
target = config.WEEKLY_TARGET_PER_GROUP
with db.engine.begin() as c:
    for i in range(3):
        c.execute(insert(db.trips).values(job_id=job, file_name=f"d{i}.jpg", status="done",
                                          service_type="Standard Bike", committed=1))
    for i in range(2):     # ของที่ไม่ได้อยู่บนบิล ต้องไม่ทำให้กลุ่มดูเต็ม
        c.execute(insert(db.trips).values(job_id=job, file_name=f"x{i}.jpg", status="duplicate",
                                          service_type="Standard Bike", committed=1))
    c.execute(insert(db.trips).values(job_id=job, file_name="v.jpg", status="voided",
                                      service_type="Standard Bike", committed=1))

counts = db.week_group_counts(W37, W37_END)
check("นับเฉพาะงานที่อยู่บนบิล (ไม่นับซ้ำ/ยกเลิก)", counts == {"2 W Standard": 3})
room = pool.week_room("Week 7-13 Sep")
check("ที่ว่างของกลุ่มที่มีงานแล้ว = เป้า − ที่ลงไปแล้ว", room["2 W Standard"] == target - 3)
check("กลุ่มที่ยังไม่มีงานเลย ที่ว่าง = เป้าเต็ม",
      room["2 W Saver"] == target and room["4 W Standard"] == target)
check("สัปดาห์ที่อ่านชื่อไม่ออก → ไม่กั้นอะไร (None)", pool.week_room("Test 7") is None)

with db.engine.begin() as c:
    for i in range(target - 3):
        c.execute(insert(db.trips).values(job_id=job, file_name=f"f{i}.jpg", status="done",
                                          service_type="Standard Bike", committed=1))
room = pool.week_room("Week 7-13 Sep")
check("กลุ่มที่ครบเป้าแล้ว: ที่ว่างเป็น 0 — งานถัดไปต้องลงสัปดาห์หน้าตั้งแต่แรก",
      room["2 W Standard"] == 0 and room["2 W Saver"] == target)

# --- นับตาม Service Type บนสลิป ไม่ใช่ตามโฟลเดอร์ (W38, 2026-09-21) --------------------------------------
W38, W38_END = "2026-09-14", "2026-09-20"
saver = db.create_job("จิตร Win", "Trips", W38, W38_END, category="2 W Saver")
hold = db.create_job("(รออ่าน)", "Trips", W38, W38_END)
with db.engine.begin() as c:
    for i in range(5):
        c.execute(insert(db.trips).values(job_id=saver, file_name=f"s{i}.jpg", status="done",
                                          service_type="Saver Bike", committed=1))
    for i in range(3):     # สลิปบอก Standard Bike แต่ค้างอยู่ในโฟลเดอร์ Saver
        c.execute(insert(db.trips).values(job_id=saver, file_name=f"b{i}.jpg", status="done",
                                          service_type="Standard Bike", committed=1))
    c.execute(insert(db.trips).values(job_id=saver, file_name="u.jpg", status="done",
                                      service_type=None, committed=1))
    for i in range(4):     # อ่านแล้วรอลงที่ — ตัวลงที่หักที่ว่างเอง
        c.execute(insert(db.trips).values(job_id=hold, file_name=f"h{i}.jpg", status="done",
                                          service_type="Saver Bike", committed=0))
counts = db.week_group_counts(W38, W38_END)
check("❗ แถว Standard Bike ในโฟลเดอร์ Saver นับเข้า 2 W Standard ตามที่ลูกค้านับ",
      counts.get("2 W Standard") == 3 and counts.get("2 W Saver") == 6)
check("แถวที่ไม่รู้ประเภทนับตามโฟลเดอร์ของมัน · แถวในกองพักไม่ถูกนับ", sum(counts.values()) == 9)

room = pool.week_room("Week 14-20 Sep")
check("แถวที่อ่านแล้วรอลงที่หักที่ว่างของกลุ่มตาม Service Type", room["2 W Saver"] == target - 6 - 4)

# --- เผื่อเมื่อสัปดาห์ยังขาด (W46 Saver Bike 1,469, 2026-11-16) -----------------------------------------
config.POOL_RESERVE_PCT, config.POOL_RESERVE_MIN = 2, 2
room = pool.week_room("Week 7-13 Sep")
check("❗ กลุ่มที่ยังขาดได้เผื่อ 2% ของที่ขาด (1,470 → +30)", room["2 W Saver"] == target + 30)
check("กลุ่มที่ครบแล้วไม่เผื่อ: งานถัดไปไปสัปดาห์หน้า", room["2 W Standard"] == 0)
W39, W39_END = "2026-09-21", "2026-09-27"
s39 = db.create_job("ดาว Win", "Trips", W39, W39_END, category="2 W Saver")
h39 = db.create_job("(รออ่าน)", "Trips", W39, W39_END)
with db.engine.begin() as c:
    for i in range(target - 102):
        c.execute(insert(db.trips).values(job_id=s39, file_name=f"w{i}.jpg", status="done",
                                          service_type="Saver Bike", committed=1))
check("❗ ขาด 102: ส่ง 102 + เผื่อ 3", pool.week_room("Week 21-27 Sep")["2 W Saver"] == 105)
with db.engine.begin() as c:
    for i in range(101):
        c.execute(insert(db.trips).values(job_id=s39, file_name=f"n{i}.jpg", status="done",
                                          service_type="Saver Bike", committed=1))
    for i in range(3):
        c.execute(insert(db.trips).values(job_id=h39, file_name=f"e{i}.jpg", status="done",
                                          service_type="Saver Bike", committed=0))
check("❗ ซ้ำ 1 ทำให้ขาด 1 แต่มีงานเผื่อรออยู่ 3: ไม่ส่งเพิ่มจากกอง (ลงจากที่พักแทน)",
      pool.week_room("Week 21-27 Sep")["2 W Saver"] <= 0)
with db.engine.begin() as c:
    c.execute(insert(db.trips).values(job_id=s39, file_name="last.jpg", status="done",
                                      service_type="Saver Bike", committed=1))
check("ครบเป้าแล้วงานเผื่อที่เหลือไม่ดึงงานเพิ่ม", pool.week_room("Week 21-27 Sep")["2 W Saver"] == -3)

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
