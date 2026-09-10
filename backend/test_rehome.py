# -*- coding: utf-8 -*-
"""A row whose service names another group is moved there — row, stitched picture, delivered
picture — and nothing else is touched (2026-09-10).

Local folders stand in for Drive and a throwaway SQLite for the database. One rider holds three
finished rows under 2 W Standard; the chip audit has written 'Saver Bike' onto two of them.
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-rehome-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from sqlalchemy import insert, select                            # noqa: E402

import db                                                        # noqa: E402
import rehome_by_service as rh                                   # noqa: E402
from drive_client import LocalDrive                              # noqa: E402
from ingest import week_label                                    # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


D_FROM, D_TO = "2026-08-31", "2026-09-06"
ROOT = os.path.join(WORK, "drive")
WEEK = os.path.join(ROOT, "Week 31 Aug-6 Sep")
EXPORT_WEEK = os.path.join(ROOT, "Export Pic", week_label(D_FROM))
rider_std = os.path.join(WEEK, "2 W Standard", "07-มนันตรา Win")
os.makedirs(rider_std)
os.makedirs(os.path.join(WEEK, "2 W Saver", "03-คนอื่น Home"))     # the Saver group already has one rider
os.makedirs(os.path.join(EXPORT_WEEK, "2 W Standard"))
for n in (1, 2, 3):
    open(os.path.join(rider_std, f"pair_{n}.jpg"), "wb").write(b"\xff\xd8pair%d" % n)
    open(os.path.join(EXPORT_WEEK, "2 W Standard", f"WK36-มนันตรา Win{n}.jpg"), "wb").write(b"\xff\xd8cust%d" % n)

drive = LocalDrive(ROOT)
job_std = db.create_job("มนันตรา Win", "Trips", D_FROM, D_TO, category="2 W Standard",
                        folder_name="2 W Standard/มนันตรา Win", drive_folder_id=rider_std)
with db.engine.begin() as c:
    for n, svc in ((1, "Standard Bike"), (2, "Saver Bike"), (3, "Saver Bike")):
        c.execute(insert(db.trips).values(job_id=job_std, file_name=f"pair_{n}.jpg", status="done",
                                          service_type=svc, customer_image=f"WK36-มนันตรา Win{n}.jpg",
                                          committed=1, note="ประเภทตามชิปบนสลิป" if n > 1 else None))

# --- what needs moving --------------------------------------------------------------------------
moves, _jobs = rh.rows_needing_move(D_FROM, D_TO)
check("เจอ 2 แถวที่ประเภทไม่ตรงกลุ่มของ job (ไม่ใช่ 3)", len(moves) == 2)
check("ทั้งสองต้องไป 2 W Saver", {w for _r, _j, w in moves} == {"2 W Saver"})

# --- move them ------------------------------------------------------------------------------------
mv = rh.Mover(drive, WEEK, EXPORT_WEEK, log=lambda *a: None)
done = rh.apply(drive, mv, D_FROM, D_TO, moves, log=lambda *a: None)
check("ย้ายแถว 2 · รูปรวมร่าง 2 · รูปลูกค้า 2",
      (done["ย้ายแถว"], done["ย้ายรูปรวมร่าง"], done["ย้ายรูปลูกค้า"]) == (2, 2, 2))
check("ไม่มีรูปไหนหาไม่เจอ", not any("ไม่เจอ" in k for k in done))

saver_dir = os.path.join(WEEK, "2 W Saver")
new_folders = sorted(os.listdir(saver_dir))
check("เปิดโฟลเดอร์ไรเดอร์ใหม่ใน 2 W Saver ด้วยเลขถัดไป (04)", new_folders == ["03-คนอื่น Home", "04-มนันตรา Win"])
check("รูปรวมร่าง 2 ใบย้ายมาแล้ว",
      sorted(os.listdir(os.path.join(saver_dir, "04-มนันตรา Win"))) == ["pair_2.jpg", "pair_3.jpg"])
check("โฟลเดอร์เดิมเหลือใบที่ถูกต้องใบเดียว", os.listdir(rider_std) == ["pair_1.jpg"])
check("รูปลูกค้าย้ายไป Export Pic/…/2 W Saver โดยชื่อเดิม",
      sorted(os.listdir(os.path.join(EXPORT_WEEK, "2 W Saver"))) == ["WK36-มนันตรา Win2.jpg", "WK36-มนันตรา Win3.jpg"])
check("Export Pic เดิมไม่มีสำเนาค้าง",
      os.listdir(os.path.join(EXPORT_WEEK, "2 W Standard")) == ["WK36-มนันตรา Win1.jpg"])

job_saver = db.find_job("มนันตรา Win", D_FROM, D_TO, category="2 W Saver")
check("มี job ใหม่ของคนเดิมในกลุ่ม 2 W Saver", bool(job_saver) and job_saver != job_std)
with db.engine.begin() as c:
    rows = c.execute(select(db.trips.c.file_name, db.trips.c.job_id, db.trips.c.note,
                            db.trips.c.service_type).order_by(db.trips.c.id)).mappings().all()
check("แถว 2 และ 3 ย้ายไป job ใหม่ · แถว 1 อยู่ที่เดิม",
      [r["job_id"] for r in rows] == [job_std, job_saver, job_saver])
check("ตัวเลขบนแถวไม่ถูกแตะ (service_type เดิม)", [r["service_type"] for r in rows]
      == ["Standard Bike", "Saver Bike", "Saver Bike"])
check("โน้ตบอกว่าย้ายมาจากไหน และเก็บโน้ตเดิมไว้",
      all(r["note"].startswith("ย้ายไป 2 W Saver") and "ประเภทตามชิปบนสลิป" in r["note"] for r in rows[1:]))
check("job ใหม่ชี้ไปโฟลเดอร์ไรเดอร์ใหม่",
      db.get_job_meta(job_saver)["drive_folder_id"] == os.path.join(saver_dir, "04-มนันตรา Win"))

# --- running again finds nothing to do --------------------------------------------------------------
again, _ = rh.rows_needing_move(D_FROM, D_TO)
check("รันซ้ำไม่มีอะไรต้องย้าย", again == [])

# --- a service with no group to go to is reported, never moved ---------------------------------------
with db.engine.begin() as c:
    c.execute(insert(db.trips).values(job_id=job_std, file_name="pair_9.jpg", status="done",
                                      service_type="Saver Car", customer_image="WK36-มนันตรา Win9.jpg", committed=1))
m9, _ = rh.rows_needing_move(D_FROM, D_TO)
check("Saver Car ถูกชี้ว่าต้องไป 4 W Saver ซึ่ง main() จะกันไว้ไม่ย้าย", [w for _r, _j, w in m9] == ["4 W Saver"])

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
