# -*- coding: utf-8 -*-
"""A group short of its target is topped up with copies of earlier weeks' rows — the earlier week
keeps everything, this week gets new rows that say the same thing, dated as driven (2026-09-10).

Local folders stand in for Drive and a throwaway SQLite for the database.
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-fill-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from sqlalchemy import insert, select                            # noqa: E402

import db                                                        # noqa: E402
import fill_from_past as fp                                      # noqa: E402
from drive_client import LocalDrive                              # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


ROOT = os.path.join(WORK, "drive")
OLD = os.path.join(ROOT, "Week 24-30 Aug", "2 W Standard", "03-สมชาย Win")
THIS = os.path.join(ROOT, "Week 31 Aug-6 Sep")
os.makedirs(OLD)
os.makedirs(os.path.join(THIS, "2 W Standard", "01-คนอื่น Win"))
drive = LocalDrive(ROOT)

j_old = db.create_job("สมชาย Win", "Trips", "2026-08-24", "2026-08-30", category="2 W Standard", drive_folder_id=OLD)
j_old_saver = db.create_job("สมชาย Win", "Trips", "2026-08-24", "2026-08-30", category="2 W Saver")
with db.engine.begin() as c:
    for n in range(1, 5):
        p = os.path.join(OLD, f"old{n}.jpg")
        open(p, "wb").write(b"\xff\xd8old%d" % n)
        c.execute(insert(db.trips).values(job_id=j_old, file_name=f"old{n}.jpg", status="done", committed=1,
                                          service_type="Standard Bike", trip_date=f"2026-08-2{n}", net_earnings=100 + n,
                                          base_fare=90 + n, source_url=p, customer_image=f"WK35-สมชาย Win{n}.jpg",
                                          image_hash="h%d" % n))
    # never drawn: a duplicate, a voided row, a Saver row, and a row from THIS week
    c.execute(insert(db.trips).values(job_id=j_old, file_name="dup.jpg", status="done", committed=1,
                                      service_type="Standard Bike", duplicate_of=1, source_url=os.path.join(OLD, "old1.jpg")))
    c.execute(insert(db.trips).values(job_id=j_old, file_name="void.jpg", status="voided", committed=0,
                                      service_type="Standard Bike", source_url=os.path.join(OLD, "old1.jpg")))
    c.execute(insert(db.trips).values(job_id=j_old_saver, file_name="sv.jpg", status="done", committed=1,
                                      service_type="Saver Bike", source_url=os.path.join(OLD, "old1.jpg")))
j_this = db.create_job("คนอื่น Win", "Trips", "2026-08-31", "2026-09-06", category="2 W Standard")
with db.engine.begin() as c:
    c.execute(insert(db.trips).values(job_id=j_this, file_name="this.jpg", status="done", committed=1,
                                      service_type="Standard Bike", source_url=os.path.join(OLD, "old1.jpg")))

# --- what may be drawn ---------------------------------------------------------------------------------
cands = fp.candidates("2026-08-31", "2 W Standard")
check("หยิบได้เฉพาะ 4 แถวจริงของสัปดาห์ก่อน (ไม่เอาซ้ำ/ยกเลิก/Saver/สัปดาห์นี้)", sorted(r[0]["file_name"] for r in cands.values())
      == ["old1.jpg", "old2.jpg", "old3.jpg", "old4.jpg"])
p1 = fp.draw(cands, 2, seed=7)
p2 = fp.draw(cands, 2, seed=7)
check("seed เดิม → หยิบชุดเดิม", [r[0]["id"] for r in p1] == [r[0]["id"] for r in p2])
check("หยิบไม่ซ้ำแถว", len({r[0]["id"] for r in p1}) == 2)
check("ขอเกินที่มี → ได้เท่าที่มี", len(fp.draw(cands, 10, seed=1)) == 4)

# --- copy them in ----------------------------------------------------------------------------------------
tgt = fp.Target(drive, THIS, "2 W Standard")
done = fp.apply(drive, tgt, "2026-08-31", "2026-09-06", "2 W Standard", p1, log=lambda *a: None)
check("คัดลอก 2 แถว ไม่มีที่โหลดไม่ได้", done["คัดลอกแถว"] == 2 and len(done) == 1)
this_dir = os.path.join(THIS, "2 W Standard")
check("เปิดโฟลเดอร์ไรเดอร์ในสัปดาห์นี้ด้วยเลขถัดไป (02)", sorted(os.listdir(this_dir)) == ["01-คนอื่น Win", "02-สมชาย Win"])
copied = sorted(os.listdir(os.path.join(this_dir, "02-สมชาย Win")))
check("รูป 2 ใบถูกคัดลอกมา", copied == sorted(r[0]["file_name"] for r in p1))
check("สัปดาห์เก่ายังมีรูปครบ 4 ใบ (คัดลอก ไม่ใช่ย้าย)", sorted(os.listdir(OLD)) == ["old1.jpg", "old2.jpg", "old3.jpg", "old4.jpg"])

j_new = db.find_job("สมชาย Win", "2026-08-31", "2026-09-06", category="2 W Standard")
check("มี job สัปดาห์นี้ของคนเดิม กลุ่มเดิม", bool(j_new))
with db.engine.begin() as c:
    new = [dict(r) for r in c.execute(select(*db.TRIP_COLS).where(db.trips.c.job_id == j_new)).mappings().all()]
    old = [dict(r) for r in c.execute(select(*db.TRIP_COLS).where(db.trips.c.job_id == j_old, db.trips.c.committed == 1,
                                                                  db.trips.c.duplicate_of.is_(None))).mappings().all()]
check("แถวใหม่ 2 แถวใต้ job สัปดาห์นี้", len(new) == 2)
src = {r[0]["id"]: r[0] for r in p1}
check("ตัวเลขถูกคัดลอกครบ (ยอด/ฐาน/วันที่)",
      all(any(n["net_earnings"] == s["net_earnings"] and n["base_fare"] == s["base_fare"] and n["trip_date"] == s["trip_date"]
              for s in src.values()) for n in new))
check("วันที่บนสลิปคงไว้ ไม่ใช่วันของสัปดาห์นี้", all(n["trip_date"].startswith("2026-08-2") for n in new))
check("customer_image ว่าง เพื่อให้สัปดาห์นี้ตั้งชื่อใหม่", all(n["customer_image"] is None for n in new))
check("source_url ชี้ไปสำเนาใหม่ ไม่ใช่ไฟล์เดิม", all(n["source_url"] != s["source_url"] for n in new for s in src.values()))
check("ไม่พก image_hash/duplicate_of/batch มา", all(n["image_hash"] is None and n["duplicate_of"] is None and n["batch_name"] is None for n in new))
check("โน้ตบอกสัปดาห์และแถวต้นทาง", all("เติมจากสัปดาห์ 2026-08-24..2026-08-30" in n["note"] and "สำเนาของแถว #" in n["note"] for n in new))
check("แถวสัปดาห์เก่ายังอยู่ครบ 4 ไม่ถูกแตะ", len(old) == 4 and all(o["customer_image"] for o in old))

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
