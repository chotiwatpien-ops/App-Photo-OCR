# -*- coding: utf-8 -*-
"""A quiet round must cost almost nothing, and must never mistake work for quiet.

Four rounds out of four lately found no new photos, yet each walked 600-odd Drive folders for
five minutes and rewrote a 13,000-row workbook that came out byte-identical. Two guards fix
that; both are only safe if they fail towards doing the work.
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-lean-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import db                                                       # noqa: E402
import ingest                                                   # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


class Probe:
    """A Drive that answers the one-call question, and counts how often it was asked."""

    def __init__(self, found, boom=False):
        self.found, self.boom, self.calls = found, boom, 0

    def images_modified_since(self, since, limit=100):
        self.calls += 1
        if self.boom:
            raise RuntimeError("drive is down")
        return self.found


NO_PROBE = object()          # a drive without the method at all (LocalDrive, older clients)

# --- ตัวจำสถานะเล็กๆ -------------------------------------------------------------------------
db.state_set("k", "v1")
check("จำค่าได้", db.state_get("k") == "v1")
db.state_set("k", "v2")
check("เขียนทับค่าเดิมได้ ไม่ซ้อน", db.state_get("k") == "v2")
check("คีย์ที่ไม่มี คืนค่าเริ่มต้น", db.state_get("ไม่มีคีย์นี้", "-") == "-")

# --- ลายนิ้วมือของ workbook ------------------------------------------------------------------
job = db.create_job("ทดสอบ", "Trips", "2026-08-24", "2026-08-30")
t1 = db.create_trip(job, "a.jpg", None, "image/jpeg")
db.update_trip(t1, {"status": "done", "trip_date": "2026-08-25", "net_earnings": 100,
                    "base_fare": 100, "booking_code": "A-9AAAA"})
db.approve_trip(t1)
first = db.committed_fingerprint()
check("ลายนิ้วมือคงที่ถ้าไม่มีอะไรเปลี่ยน", db.committed_fingerprint() == first)

db.update_trip(t1, {"net_earnings": 120})
after_edit = db.committed_fingerprint()
check("แก้ยอดเงินแล้วลายนิ้วมือเปลี่ยน", after_edit != first)

t2 = db.create_trip(job, "b.jpg", None, "image/jpeg")
db.update_trip(t2, {"status": "done", "trip_date": "2026-08-26", "net_earnings": 50,
                    "base_fare": 50, "booking_code": "A-9BBBB"})
db.approve_trip(t2)
check("อนุมัติแถวใหม่แล้วลายนิ้วมือเปลี่ยน", db.committed_fingerprint() != after_edit)

# แถวที่ยังไม่อนุมัติต้องไม่ขยับลายนิ้วมือ — workbook เขียนเฉพาะแถวที่อนุมัติแล้ว
before_waiting = db.committed_fingerprint()
t3 = db.create_trip(job, "c.jpg", None, "image/jpeg")
db.update_trip(t3, {"status": "done", "trip_date": "2026-08-27", "net_earnings": 70, "base_fare": 70})
check("แถวที่รอตรวจไม่ทำให้ต้องเขียน workbook ใหม่", db.committed_fingerprint() == before_waiting)

# --- ตัวถาม Drive ก่อนเดินโฟลเดอร์ ------------------------------------------------------------
db.state_set(ingest.PROBE_KEY, None)
check("ยังไม่เคยมีหมุดเวลา: ต้องเดินโฟลเดอร์", ingest.nothing_new(Probe([])) is False)

db.state_set(ingest.PROBE_KEY, "2026-09-01T00:00:00Z")
check("Drive บอกไม่มีรูปใหม่เลย: ข้ามได้", ingest.nothing_new(Probe([])) is True)

check("เจอรูปที่ยังไม่เคยอ่าน: ต้องเดินโฟลเดอร์",
      ingest.nothing_new(Probe([{"id": "ยังไม่เคยเห็น", "name": "x.jpg"}])) is False)

db.record_ingested("เคยอ่านแล้ว", "old.jpg", job, t1)
check("เจอแต่รูปที่อ่านไปแล้ว: ข้ามได้",
      ingest.nothing_new(Probe([{"id": "เคยอ่านแล้ว", "name": "old.jpg"}])) is True)
check("รูปเก่าปนรูปใหม่: ต้องเดินโฟลเดอร์",
      ingest.nothing_new(Probe([{"id": "เคยอ่านแล้ว", "name": "old.jpg"},
                                {"id": "ใหม่", "name": "new.jpg"}])) is False)

full = [{"id": f"i{i}", "name": f"{i}.jpg"} for i in range(ingest.PROBE_PAGE)]
check("ผลเต็มหน้า (มากเกินกว่าจะตัดสิน): ต้องเดินโฟลเดอร์", ingest.nothing_new(Probe(full)) is False)

check("Drive ล่ม: ต้องเดินโฟลเดอร์ ไม่ใช่ข้าม", ingest.nothing_new(Probe([], boom=True)) is False)
check("Drive ที่ไม่มีตัวถาม (LocalDrive): ต้องเดินโฟลเดอร์", ingest.nothing_new(NO_PROBE) is False)

import config                                                   # noqa: E402
config.DRIVE_PROBE = False
check("ปิดสวิตช์แล้วกลับไปเดินโฟลเดอร์เสมอ", ingest.nothing_new(Probe([])) is False)
config.DRIVE_PROBE = True

p = Probe([])
ingest.nothing_new(p)
check("ถาม Drive ครั้งเดียวต่อรอบ", p.calls == 1)

# --- หมุดเวลาต้องเผื่อเวลาถอยหลัง ------------------------------------------------------------
mark = "2026-09-04T12:00:00Z"
back = ingest._shift(mark, -ingest.PROBE_MARGIN)
check("หมุดเวลาถอยหลัง 15 นาที (กันรูปที่อัปโหลดระหว่างรอบกำลังเดิน)", back == "2026-09-04T11:45:00Z")

# --- รอบจริง: เงียบแล้วต้องไม่เดินโฟลเดอร์ และไม่เขียน workbook ซ้ำ ---------------------------
from drive_client import LocalDrive                             # noqa: E402

config.INGEST_BATCH = False
ingest.config.INGEST_BATCH = False
inbox, exports = os.path.join(WORK, "Inbox"), os.path.join(WORK, "Exports")
os.makedirs(os.path.join(inbox, "Week 24-30 Aug", "4 W Standard", "01 ทดสอบ"), exist_ok=True)
os.makedirs(exports, exist_ok=True)


class QuietDrive(LocalDrive):
    """Drive with nothing new in it — the four rounds out of four we keep seeing."""

    def images_modified_since(self, since, limit=100):
        return []


walked = []
real_discover = ingest.discover
ingest.discover = lambda *a, **k: (walked.append(1) or ([], []))

uploads = []
real_xlsx = LocalDrive.upload_xlsx
LocalDrive.upload_xlsx = lambda self, parent, name, data: (
    uploads.append(name) or real_xlsx(self, parent, name, data))
try:
    drive = QuietDrive(inbox)
    db.state_set(ingest.PROBE_KEY, None)
    ingest.run(drive, inbox, exports)                     # ยังไม่มีหมุดเวลา → ต้องเดิน
    check("รอบแรก (ยังไม่มีหมุดเวลา): เดินโฟลเดอร์", len(walked) == 1)
    check("รอบแรก: เขียน workbook", uploads == ["Rider Trips.xlsx"])
    check("รอบแรก: จดหมุดเวลาไว้ให้รอบหน้า", bool(db.state_get(ingest.PROBE_KEY)))

    ingest.run(drive, inbox, exports)                     # Drive บอกว่าไม่มีอะไรใหม่
    check("รอบสอง (เงียบ): ไม่เดินโฟลเดอร์เลย", len(walked) == 1)
    check("รอบสอง (เงียบ): ไม่เขียน workbook ซ้ำ", len(uploads) == 1)

    db.update_trip(t2, {"net_earnings": 999})             # มีคนแก้เงินในเว็บระหว่างรอบ
    ingest.run(drive, inbox, exports)
    check("แก้ในเว็บระหว่างรอบ: ยังเขียน workbook ขึ้น Drive ให้", len(uploads) == 2)
    check("แต่ยังไม่ต้องเดินโฟลเดอร์เพราะเรื่องนั้น", len(walked) == 1)
finally:
    ingest.discover = real_discover
    LocalDrive.upload_xlsx = real_xlsx

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
