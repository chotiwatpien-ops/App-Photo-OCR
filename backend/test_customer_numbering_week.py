# -*- coding: utf-8 -*-
"""A rider's customer pictures are numbered against the WEEK, not against one job (2026-09-11).

rehome and carry give one rider two and three jobs inside a week, and each job numbered from 1:
'WK36-สมชาย1.jpg' belonged to two rows. 513 names in W36's file were shared, 211 of them turning
up in a single day. A throwaway SQLite stands in for the database.
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-num-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from io import BytesIO                                          # noqa: E402

from PIL import Image                                           # noqa: E402

import db                                                       # noqa: E402
import pipeline                                                 # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


def slip(seed):
    buf = BytesIO()
    Image.new("RGB", (720, 1560), (10 * seed, 200, 120)).save(buf, "JPEG")
    return buf.getvalue()


D_FROM, D_TO = "2026-08-31", "2026-09-06"


def add(job, n, seed, date="2026-09-01"):
    tid = db.create_trip(job, f"{n}.jpg", slip(seed), "image/jpeg")
    db.update_trip(tid, {"status": "done", "kind": "full", "net_earnings": 10.0 + seed,
                         "base_fare": 10.0 + seed, "check_status": "pass", "trip_date": date})
    return tid


# สมชาย drives both tiers this week, so the rehome gave him a job in each group
std = db.create_job("สมชาย", "Trips", D_FROM, D_TO, category="2 W Standard")
sav = db.create_job("สมชาย", "Trips", D_FROM, D_TO, category="2 W Saver")
for i in (1, 2, 3):
    add(std, f"s{i}", i)
for i in (1, 2):
    add(sav, f"v{i}", 10 + i)

first = [n for n, _ in pipeline.customer_images(std, "สมชาย")]
check("job แรกได้ 1-3", first == ["WK36-สมชาย1.jpg", "WK36-สมชาย2.jpg", "WK36-สมชาย3.jpg"])
second = [n for n, _ in pipeline.customer_images(sav, "สมชาย")]
check("job ที่สองของคนเดียวกันในวีคเดียวกัน นับต่อเป็น 4-5 ไม่ใช่เริ่ม 1 ใหม่",
      second == ["WK36-สมชาย4.jpg", "WK36-สมชาย5.jpg"])
check("ไม่มีชื่อไหนซ้ำกันเลย", len(set(first) | set(second)) == 5)

# a third job, the shape carry_excess makes — and a row added to the FIRST job afterwards
third = db.create_job("สมชาย", "Trips", D_FROM, D_TO, category="4 W Standard")
add(third, "c1", 21)
check("job ที่สามได้ 6", [n for n, _ in pipeline.customer_images(third, "สมชาย")] == ["WK36-สมชาย6.jpg"])
add(std, "s4", 4)
made = [n for n, _ in pipeline.customer_images(std, "สมชาย")]
check("แถวใหม่ที่มาทีหลังใน job แรก ได้ 7 (ไม่ไปทับ 4-6 ของ job อื่น)", made == ["WK36-สมชาย7.jpg"])

# what was already delivered keeps its number, and a settled job makes nothing again
check("รันซ้ำไม่สร้างรูปเพิ่ม", list(pipeline.customer_images(sav, "สมชาย")) == [])
rows = {r["file_name"]: r["customer_image"] for r in db.trips_with_images(std)}
check("ชื่อที่ส่งไปแล้วไม่ถูกเรียงใหม่", rows["s1.jpg"] == "WK36-สมชาย1.jpg" and rows["s4.jpg"] == "WK36-สมชาย7.jpg")

# another rider is numbered on their own, and another week starts at 1 again
other = db.create_job("สมหญิง", "Trips", D_FROM, D_TO, category="2 W Saver")
add(other, "o1", 31)
check("ไรเดอร์คนอื่นในวีคเดียวกันเริ่มที่ 1",
      [n for n, _ in pipeline.customer_images(other, "สมหญิง")] == ["WK36-สมหญิง1.jpg"])
nxt = db.create_job("สมชาย", "Trips", "2026-09-07", "2026-09-13", category="2 W Saver")
add(nxt, "n1", 41, date="2026-09-08")
check("คนเดิมในวีคถัดไปเริ่มที่ 1 ใหม่",
      [n for n, _ in pipeline.customer_images(nxt, "สมชาย")] == ["WK37-สมชาย1.jpg"])

# the admin suffix (two riders sharing a name) still numbers apart
dupname = db.create_job("สมชาย", "Trips", D_FROM, D_TO, category="2 W Saver", admin="Yo")
add(dupname, "d1", 51)
check("ชื่อพ้องที่ต่อท้ายด้วยแอดมิน นับแยกของตัวเอง",
      [n for n, _ in pipeline.customer_images(dupname, "สมชาย-Yo")] == ["WK36-สมชาย-Yo1.jpg"])

names = [n for n in db.customer_images_in_week(D_FROM, D_TO)]
check("db.customer_images_in_week เห็นทุก job ของสัปดาห์", len(names) == 9 and len(set(names)) == 9)
check("ไม่เห็นของสัปดาห์อื่น", "WK37-สมชาย1.jpg" not in names)

# a voided trip gives its number back, even when the trip that takes it is in another job
voided = [r for r in db.trips_with_images(std) if r["file_name"] == "s2.jpg"][0]
db.update_trip(voided["id"], {"status": "voided"})
check("แถวที่ยกเลิกไม่ถูกนับว่าใช้เลขแล้ว", "WK36-สมชาย2.jpg" not in db.customer_images_in_week(D_FROM, D_TO))
add(sav, "v3", 61)
check("เลข 2 ที่ว่างถูกนำกลับมาใช้ (ทับไฟล์เก่าบน Drive ไม่เหลือรูที่ลูกค้าเห็น)",
      [n for n, _ in pipeline.customer_images(sav, "สมชาย")] == ["WK36-สมชาย2.jpg"])

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
