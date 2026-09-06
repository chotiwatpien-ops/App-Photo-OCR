# -*- coding: utf-8 -*-
"""Telling one pool run's rows from another's when both produced the same file name.

The stitched name is '<album>_<top>+<bottom>_฿<amount>'. Two runs over the same album pair the
same positions for the same fare all the time, so the name is not a key — the first version of
this audit reported 109 rows for 87 files. What separates them is when the job was opened, and
the two tables write their timestamps in different shapes.
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-audit-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import audit_pool_run as audit                                  # noqa: E402
import db                                                       # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


check("เวลาสองรูปแบบเทียบกันได้", audit.when("2026-09-06T00:20:00") < audit.when("2026-09-06 00:38:06"))
check("ไม่มีเวลาก็ไม่พัง", audit.when(None) == "")
check("อ่านลำดับครึ่งบน/ครึ่งล่างจากชื่อไฟล์", audit.digits("X_8+29_฿56.jpg") == (8, 29))
check("ชื่อที่ไม่เข้าแพทเทิร์นคืน None", audit.digits("ไม่ใช่ไฟล์คู่.jpg") is None)

pairs7 = [{"moved": "2 W Saver/01-a/X_8+29_฿56.jpg", "amount": 56, "distance": 21},
          {"moved": "2 W Saver/01-a/X_3+2_฿24.jpg", "amount": 24, "distance": 1},
          {"moved": "", "amount": 30, "distance": 1}]                  # never filed
db.record_pool_run("move", "W", {"n_pairs": 3}, "s",
                   {"albums": [{"album": "X", "pairs": pairs7}], "started_at": "2026-09-05 23:54:17"})
db.record_pool_run("move", "W", {"n_pairs": 1}, "s",
                   {"albums": [{"album": "X", "pairs": [
                       {"moved": "2 W Saver/09-b/X_3+2_฿24.jpg", "amount": 24, "distance": 1}]}],
                    "started_at": "2026-09-06 00:38:06"})
runs = {r["id"]: r for r in db.recent_pool_runs(9, with_report=True)}
check("นับเฉพาะคู่ที่ย้ายเข้าโฟลเดอร์จริง", len(audit.pairs_of(runs[1])) == 2)
check("เก็บระยะห่างของแต่ละคู่ไว้", sorted(p["distance"] for p in audit.pairs_of(runs[1])) == [1, 21])

j7 = db.create_job("a", "Trips", "2026-08-31", "2026-09-06", category="2 W Saver")
j8 = db.create_job("b", "Trips", "2026-08-31", "2026-09-06", category="2 W Saver")
with db.engine.begin() as c:
    c.execute(db.jobs.update().where(db.jobs.c.id == j7).values(created_at="2026-09-05T23:55:00"))
    c.execute(db.jobs.update().where(db.jobs.c.id == j8).values(created_at="2026-09-06T00:40:00"))
    for job, fn, cs, code in [(j7, "X_8+29_฿56.jpg", "pass", "A-FAR"),
                              (j7, "X_3+2_฿24.jpg", "pass", "A-NEAR"),
                              (j8, "X_3+2_฿24.jpg", "pass", "A-NEAR")]:   # same name, run 2
        c.execute(db.trips.insert().values(job_id=job, file_name=fn, status="done",
                                           check_status=cs, booking_code=code, committed=1))

import io                                                        # noqa: E402
from contextlib import redirect_stdout                           # noqa: E402
buf = io.StringIO()
with redirect_stdout(buf):
    rc = audit.main(["--run", "1", "--against", "2", "--list"])
out = buf.getvalue()
check("จบด้วยสถานะปกติ", rc == 0)
check("ไม่นับแถวของรอบหลังที่ชื่อไฟล์ชนกัน", "กลายเป็นแถวในฐานข้อมูล 2 แถว" in out)
check("บอกด้วยว่าคัดออกไปกี่แถว", "ชื่อไฟล์ชนกับรอบหลัง 1 แถว" in out)
check("คู่ที่ห่างผิดปกติถูกแยกออกมา", "แถวที่มาจากคู่ห่างเกิน 6 ใบ: 1 แถว" in out)
check("บอกว่าแถวที่ผ่านการตรวจเลขคือตัวอันตราย", "ผ่านการตรวจเลข: 1 แถว" in out)
check("รู้ว่ารอบหลังทำเที่ยวไหนซ้ำแล้ว", "ซ้ำกับรอบ #1: 1 เที่ยว" in out)
check("รายไฟล์บอกลำดับที่เอามาต่อกัน", "(8 กับ 29)" in out)
check("ไม่แก้อะไรในฐานข้อมูล", db.trips_count() == 3 if hasattr(db, "trips_count") else True)

# --- เอาแถวจากคู่ผิดออก (ไม่ลบ) --------------------------------------------------------------
import void_pool_pairs as void                                  # noqa: E402
from sqlalchemy import select as _sel                           # noqa: E402

r = audit.resolve(1)
check("resolve เห็นแถวของรอบนี้ 2 แถว", len(r["rows"]) == 2)
check("แยกแถวที่มาจากคู่ห่างผิดปกติได้ 1 แถว", len(r["far_rows"]) == 1)
check("ติดระยะห่างมากับแถวด้วย", r["far_rows"][0]["distance"] == 21)
check("อ่าน id ของไฟล์บน Drive จากลิงก์",
      void.drive_id("https://drive.google.com/file/d/1AbC_dEf/view?usp=sharing") == "1AbC_dEf")

buf2 = io.StringIO()
with redirect_stdout(buf2):
    rc2 = void.main(["--run", "1"])
check("รายงานอย่างเดียวไม่แตะฐานข้อมูล", rc2 == 0 and "ยังไม่ได้แตะอะไร" in buf2.getvalue())

far_id = r["far_rows"][0]["id"]
with db.engine.begin() as c:
    was = c.execute(_sel(db.trips.c.status, db.trips.c.committed)
                    .where(db.trips.c.id == far_id)).mappings().one()
check("ก่อนสั่งจริง แถวยังเป็น done และยังลงไฟล์อยู่", (was["status"], was["committed"]) == ("done", 1))

with redirect_stdout(io.StringIO()):
    void.main(["--run", "1", "--apply", "--keep-images"])
with db.engine.begin() as c:
    now = c.execute(_sel(db.trips.c.status, db.trips.c.committed, db.trips.c.note)
                    .where(db.trips.c.id == far_id)).mappings().one()
    kept = c.execute(_sel(db.trips.c.status)
                     .where(db.trips.c.file_name == "X_3+2_฿24.jpg",
                            db.trips.c.job_id == j7)).mappings().one()
check("แถวคู่ผิดถูกพักแล้ว ออกจากไฟล์ส่งงาน", (now["status"], now["committed"]) == ("voided", 0))
check("บันทึกเหตุผลไว้ในโน้ต", "คู่ผิดจาก pool run #1" in (now["note"] or ""))
check("ไม่ไปแตะแถวที่จับคู่ติดกัน", kept["status"] == "done")
check("แถวที่พักไว้หลุดจากไฟล์ส่งงานจริง",
      all(t["file_name"] != "X_8+29_฿56.jpg" for t in db.query_trips(committed_only=True)))
check("กู้คืนได้", db.restore_voided(far_id))
with db.engine.begin() as c:
    back = c.execute(_sel(db.trips.c.status).where(db.trips.c.id == far_id)).mappings().one()
check("กู้แล้วกลับเข้าคิวตรวจ", back["status"] == "done")


# --- คิวตรวจ: 'น่าจะซ้ำ' ต่างจากคู่แฝดตรงไหน --------------------------------------------------
import report_queue_dups as qd                                  # noqa: E402

jq = db.create_job("ค", "Trips", "2026-08-31", "2026-09-06", category="2 W Saver")
base = dict(status="done", check_status="pass", booking_code="A-TWIN",
            trip_date="2026-09-02", net_earnings=30.0, base_fare=30.0)
with db.engine.begin() as c:
    keep = c.execute(db.trips.insert().values(job_id=jq, file_name="เก่า.jpg", committed=1,
                                              **base)).inserted_primary_key[0]
    c.execute(db.trips.insert().values(job_id=jq, file_name="ใหม่.jpg", committed=0,
                                       duplicate_of=keep,
                                       **dict(base, net_earnings=45.0)))
buf3 = io.StringIO()
with redirect_stdout(buf3):
    rc3 = qd.main()
q = buf3.getvalue()
check("รายงานคู่แฝดจบปกติ", rc3 == 0)
check("บอกว่าคู่แฝดอนุมัติไปแล้ว", "อนุมัติแล้ว" in q)
check("ชี้ช่องที่ต่างกันให้เห็น", "รายได้" in q and "45" in q and "30" in q)
check("ไม่ฟ้องช่องที่ตรงกัน", "ตรงกัน 10 ช่อง · ต่างกัน 1 ช่อง" in q)
check("ยังไม่แตะฐานข้อมูล",
      db.review_queue() and all(t["status"] == "done" for t in db.review_queue()))


# --- สุขภาพของสัปดาห์: อ่านครบยัง · นับซ้ำมั้ย · ตกหล่นมั้ย ------------------------------------
jh = db.create_job("ง", "Trips", "2026-09-07", "2026-09-13", category="2 W Saver")
LONG_A, LONG_B = "A-" + "X" * 16, "A-" + "Y" * 16
with db.engine.begin() as c:
    for fn, st, com, code, bat in [("ซ้ำ1.jpg", "done", 1, LONG_A, None),
                                   ("ซ้ำ2.jpg", "done", 1, LONG_A, None),      # นับเงินสองรอบ
                                   ("ตก1.jpg", "duplicate", 0, LONG_B, None),
                                   ("ตก2.jpg", "voided", 0, LONG_B, None),     # ไม่เหลือตัวไหนเลย
                                   ("รอ.jpg", "pending", 0, None, "batch-1")]:
        c.execute(db.trips.insert().values(job_id=jh, file_name=fn, status=st, committed=com,
                                           booking_code=code, batch_name=bat))
# เรียกผ่าน main() ไม่ใช่เรียก health() ตรง ๆ — รอบแรกฟังก์ชันถูกเขียนไว้แต่ไม่มีใครเรียก
# แล้วเทสที่เรียกเองก็ผ่าน ทั้งที่รายงานจริงไม่เคยพิมพ์มันออกมาเลย
db.record_pool_run("move", "W2", {"n_pairs": 1}, "s",
                   {"albums": [{"album": "Z", "pairs": [
                       {"moved": "2 W Saver/01-a/ซ้ำ1.jpg", "amount": 10, "distance": 1}]}],
                    "started_at": "2026-09-08 01:00:00"})
buf4 = io.StringIO()
with redirect_stdout(buf4):
    audit.main(["--run", 
                str(max(r["id"] for r in db.recent_pool_runs(9)))])
h = buf4.getvalue()
check("รายงานพิมพ์ส่วนสุขภาพของสัปดาห์ออกมาจริง", "สุขภาพของสัปดาห์" in h)
check("บอกว่ายังรอผลจาก batch อยู่", "ยังรอผลจาก batch: 1 รูป" in h)
check("เตือนว่าตัวเลขข้างล่างยังเชื่อไม่ได้", "ยังเชื่อไม่ได้" in h)
check("จับเที่ยวที่ลงไฟล์ซ้ำสองรอบ", "ลงไฟล์ส่งงานซ้ำสองรอบ: 1" in h)
check("จับเที่ยวที่ตกหล่นไม่เหลือแถวไหนเลย", "ไม่มีตัวไหนลงไฟล์: 1" in h)
check("ไม่ก้าวก่ายสัปดาห์อื่น", "A-TWIN" not in h)


# --- พักแถวหนึ่ง แล้วแถวที่เคยชนกับมันต้องได้ไปต่อ --------------------------------------------
# ของจริง 2026-09-06: พักคู่ผิดของรอบ 7 แล้ว 3 แถวของรอบ 8 ที่จับถูก ค้างในคิวเพราะยังชี้มาหาศพ
jr = db.create_job("จ", "Trips", "2026-09-14", "2026-09-20", category="2 W Saver")
with db.engine.begin() as c:
    wrong = c.execute(db.trips.insert().values(
        job_id=jr, file_name="ผิด_4+12.jpg", status="done", committed=1,
        check_status="pass", booking_code="A-REL")).inserted_primary_key[0]
    right = c.execute(db.trips.insert().values(
        job_id=jr, file_name="ถูก_10+9.jpg", status="done", committed=0,
        check_status="pass", booking_code="A-REL",
        duplicate_of=wrong)).inserted_primary_key[0]
check("ก่อนพัก: แถวที่ถูกยังติดธงซ้ำ",
      any(t["id"] == right and t["duplicate_of"] for t in db.review_queue()))
db.void_trips([wrong], "ทิ้ง: คู่ผิด")
after_q = {t["id"]: t for t in db.review_queue()}
check("พักแล้ว แถวที่ถูกหลุดธงซ้ำ ไม่ค้างในคิวเพราะศพ",
      right in after_q and not after_q[right]["duplicate_of"])
check("บันทึกไว้ว่าปลดธงเพราะอะไร", "ปลดธงซ้ำ" in (after_q[right]["note"] or ""))
check("แถวที่พักไม่โผล่ในคิว", wrong not in after_q)

# ซ่อมของที่พักไปก่อนมีกลไกนี้
with db.engine.begin() as c:
    c.execute(db.trips.update().where(db.trips.c.id == right).values(duplicate_of=wrong))
check("ซ่อมย้อนหลังได้", db.release_dup_flags_pointing_at_voided() >= 1)
check("ซ่อมแล้วธงหาย",
      not {t["id"]: t for t in db.review_queue()}[right]["duplicate_of"])


# --- ตรวจไฟล์ที่ย้ายเข้าโฟลเดอร์ไรเดอร์ไปแล้ว จากชื่อไฟล์อย่างเดียว --------------------------
# Backfill ย้าย 150 ใบจากรอบเก่าเข้าโฟลเดอร์ไรเดอร์ รอบถัดไปจะอ่านทันที — ต้องดักได้ก่อนถูกอ่าน
class FakeDrive:
    def __init__(self):
        self.tree = {"inbox": {"Week X": "wk"}, "wk": {"2 W Saver": "cat", "_ทิ้ง": "hold",
                                                        "Pool": "pool"},
                     "cat": {"01-a": "r1"}, "pool": {}, "hold": {}, "r1": {}}
        self.imgs = {"r1": [{"id": "f1", "name": "A_3+2_฿24.jpg"},
                            {"id": "f2", "name": "A_8+29_฿56.jpg"},
                            {"id": "f3", "name": "ไม่ใช่คู่.jpg"}], "hold": []}
        self.moved = []

    def list_folders(self, pid):
        return [{"id": v, "name": k} for k, v in self.tree.get(pid, {}).items()]

    def list_images(self, pid):
        return self.imgs.get(pid, [])

    def ensure_folder(self, pid, name):
        return self.tree.setdefault(pid, {}).setdefault(name, f"{pid}/{name}")

    def move_file(self, fid, parent):
        self.moved.append((fid, parent))


import roster                                                    # noqa: E402
fake = FakeDrive()
roster._drive = lambda: fake
import config                                                    # noqa: E402
config.DRIVE_INBOX_FOLDER_ID = "inbox"

buf5 = io.StringIO()
with redirect_stdout(buf5):
    rc5 = void.main(["--scan-week", "Week X", "--min-distance", "7"])
sc = buf5.getvalue()
check("นับเฉพาะไฟล์ที่ชื่อบอกคู่ได้", "รูปที่ต่อแล้วในโฟลเดอร์ไรเดอร์ 2 ใบ" in sc)
check("ชี้ใบที่ห่างผิดปกติ", "ห่าง  21" in sc and "A_8+29" in sc)
check("รายงานอย่างเดียวไม่ย้ายอะไร", rc5 == 0 and not fake.moved)

with redirect_stdout(io.StringIO()):
    void.main(["--scan-week", "Week X", "--min-distance", "7", "--apply"])
check("สั่งจริงแล้วย้ายเฉพาะใบที่ห่าง", [m[0] for m in fake.moved] == ["f2"])

fake.moved.clear()
with redirect_stdout(io.StringIO()):
    void.main(["--scan-week", "Week X", "--min-distance", "40", "--apply"])
check("ตั้งเกณฑ์กว้างขึ้น ก็ไม่มีอะไรต้องย้าย", not fake.moved)


print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
