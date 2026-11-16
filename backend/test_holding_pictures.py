# -*- coding: utf-8 -*-
"""A row in the waiting room (_พร้อมอ่าน) gets no stored picture; once filed and still waiting for a
person, it does. W47 #522 downloaded and stored 94 pictures for rows approved minutes later (75 s).
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-hold-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from sqlalchemy import insert, select                            # noqa: E402

import db                                                        # noqa: E402
import ingest                                                    # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


class Drive:
    def __init__(self):
        self.asked = []

    def download(self, fid):
        self.asked.append(fid)
        return bytes([0xFF, 0xD8, 0x01])


W, WE = "2026-11-16", "2026-11-22"
hold = db.create_job(db.HOLDING_RIDER, "Trips", W, WE, category=None)
rider = db.create_job("สมหมาย Taxi", "Trips", W, WE, category="4 W Standard")


def row(job, name):
    with db.engine.begin() as c:
        tid = c.execute(insert(db.trips).values(job_id=job, file_name=name, status="done", committed=0,
                                                net_earnings=50, base_fare=50)).inserted_primary_key[0]
        c.execute(insert(db.ingested_files).values(drive_id=f"drv-{name}", name=name, job_id=job,
                                                   trip_id=tid, ingested_at="2026-11-16"))
    return tid


a, b = row(hold, "a.jpg"), row(hold, "b.jpg")
drive = Drive()
check("❗ แถวในที่พักไม่ต้องเก็บรูป", db.waiting_trip_ids(hold) == []
      and ingest.keep_images_for_waiting(hold, drive=drive) == 0 and drive.asked == [])
check("❗ รอบถัดไปก็ไม่ไปดึงรูปให้แถวในที่พัก (แถวรอคนที่ไม่มีรูป)", db.waiting_trips_without_image() == [])

db.move_trips_to_job([a], rider)
check("ลงที่แล้วยังรอคน: เก็บรูปให้", ingest.keep_images_for_waiting(rider, drive=drive) == 1
      and drive.asked == ["drv-a.jpg"])
with db.engine.begin() as c:
    blob = c.execute(select(db.trips.c.image_blob).where(db.trips.c.id == a)).scalar()
check("รูปอยู่ในแถวจริง", blob is not None)
check("แถวที่ยังอยู่ในที่พักยังไม่ถูกดึง", db.waiting_trips_without_image() == [])

c = row(rider, "c.jpg")
check("แถวรอคนในงานของไรเดอร์ที่ไม่มีรูป รอบถัดไปยังไปดึงให้เหมือนเดิม",
      db.waiting_trips_without_image() == [(c, rider)])

print("\nผ่านทั้งหมด ✅" if ok else "\nมีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
