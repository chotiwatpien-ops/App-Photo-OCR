# -*- coding: utf-8 -*-
"""กดลบแล้วรูปต้องไปอยู่ที่ <สัปดาห์>/_ทิ้ง-กดลบ/<ไรเดอร์>/ ไม่ใช่ค้างในโฟลเดอร์ไรเดอร์

รูปของแถวที่คนกดลบคือรูปที่ตัวอ่านอ่านผิด หรือสลิปที่ไม่ควรถูกจับคู่ — ของที่ควรเอากลับมาดู
และเอาไปเทรนต่อได้ ปล่อยไว้ที่เดิมแย่กว่าไม่มีอะไร เพราะรอบถัดไปนับว่าอ่านแล้วและ Ops นับว่าเป็นเที่ยว
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-trash-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import db                                                        # noqa: E402
import trash_picture as tp                                       # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


class FakeDrive:
    """พอสำหรับงานนี้: มีโฟลเดอร์สัปดาห์ใน Inbox กับย้ายไฟล์ได้"""

    def __init__(self, weeks=("Week 14-20 Sep",), blow_up=False):
        self.weeks = list(weeks)
        self.blow_up = blow_up
        self.moved = []
        self.made = []

    def list_folders(self, parent):
        return [{"id": f"wk:{n}", "name": n} for n in self.weeks]

    def ensure_folder(self, parent, name):
        self.made.append((parent, name))
        return f"{parent}/{name}"

    def move_file(self, fid, dest):
        if self.blow_up:
            raise RuntimeError("Drive ล่ม")
        self.moved.append((fid, dest))


TRIP = {"id": 7, "job_id": 3}
JOB = {"id": 3, "date_from": "2026-09-14", "date_to": "2026-09-20", "driver_name": "สาธิต Win"}


def patch(trip=TRIP, job=JOB, fid="drive-abc"):
    db.get_trip = lambda tid: dict(trip) if trip else None
    db.get_job = lambda jid: dict(job) if job else None
    db.drive_ids_for_trips = lambda ids: ({7: fid} if fid else {})


check("ชื่อโฟลเดอร์ทิ้งคือ _ทิ้ง-กดลบ", tp.TRASH_DIR == "_ทิ้ง-กดลบ")

patch()
d = FakeDrive()
r = tp.move_to_trash(7, drive=d)
check("ย้ายรูปสำเร็จ", r["moved"] is True)
check("ปลายทางคือ <สัปดาห์>/_ทิ้ง-กดลบ/<ไรเดอร์>/",
      d.moved == [("drive-abc", "wk:Week 14-20 Sep/_ทิ้ง-กดลบ/สาธิต Win")])
check("สร้างโฟลเดอร์ทิ้งใต้สัปดาห์ที่ถูกต้อง ไม่ใช่ที่อื่น",
      ("wk:Week 14-20 Sep", "_ทิ้ง-กดลบ") in d.made)
check("บอกที่อยู่ปลายทางกลับไปให้หน้าเว็บด้วย", "_ทิ้ง-กดลบ" in r["why"])

patch(fid=None)
d = FakeDrive()
r = tp.move_to_trash(7, drive=d)
check("แถวที่ไม่มีรูปบน Drive — ไม่ย้าย ไม่พัง", r["moved"] is False and not d.moved)

patch()
d = FakeDrive(weeks=("Week 7-13 Sep",))
r = tp.move_to_trash(7, drive=d)
check("ไม่เจอโฟลเดอร์สัปดาห์ของงานนี้ — ไม่ย้ายมั่วไปสัปดาห์อื่น",
      r["moved"] is False and not d.moved)

patch()
d = FakeDrive(blow_up=True)
r = tp.move_to_trash(7, drive=d, log=lambda *_a: None)
check("Drive ล่มตอนย้าย — คืน False เฉย ๆ ไม่โยน error ใส่คนที่เพิ่งกดลบ", r["moved"] is False)

patch(job={"id": 3, "driver_name": "สาธิต Win"})
d = FakeDrive()
r = tp.move_to_trash(7, drive=d)
check("งานที่ไม่มีช่วงวันที่ — ไม่ย้าย", r["moved"] is False and not d.moved)

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
