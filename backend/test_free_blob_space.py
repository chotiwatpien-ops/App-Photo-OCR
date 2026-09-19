# -*- coding: utf-8 -*-
"""ปล่อยรูปของแถวที่จบแล้ว โดยไม่แตะรูปที่ยังมีคนต้องใช้

รูปในฐานข้อมูลมีไว้อย่างเดียว: ให้คนเปิดดูสลิปก่อนตัดสินใจ พอตัดสินใจเสร็จก็ไม่ต้องใช้แล้ว
สิ่งที่เทสต์นี้กันคือความผิดพลาดที่แพงที่สุดสองแบบ — ล้างรูปของแถวที่ยังรอคนตรวจอยู่ (คนจะแก้เลข
ไม่ได้เพราะไม่มีสลิปให้ดู) และล้างรูปของแถวที่ตามรอยกลับไป Drive ไม่ได้ (รูปจะหายจริง)
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-blob-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import db                                                        # noqa: E402
import free_blob_space as fbs                                    # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


db.init_db()
PIC = bytes([0xFF, 0xD8]) + b"x" * 1000          # 1,002 ไบต์ พอให้ชั่งน้ำหนักได้
URL = "https://drive.google.com/file/d/abc123/view"


def seed():
    with db.engine.begin() as c:
        c.execute(db.trips.delete())
        c.execute(db.jobs.delete())
        jid = c.execute(db.jobs.insert().values(
            driver_name="ทดสอบ", date_from="2026-09-14", date_to="2026-09-20",
            status="review", created_at="2026-09-19 00:00:00")).inserted_primary_key[0]

        def put(**kw):
            v = dict(job_id=jid, image_blob=PIC, image_mime="image/jpeg", source_url=URL,
                     committed=0)
            v.update(kw)
            return c.execute(db.trips.insert().values(**v)).inserted_primary_key[0]

        ids = {
            "dup": put(status="duplicate", file_name="dup.jpg"),
            "void": put(status="voided", file_name="void.jpg"),
            "err": put(status="error", file_name="err.jpg"),
            "approved": put(status="done", committed=1, file_name="approved.jpg"),
            "queue": put(status="done", committed=0, file_name="queue.jpg"),
            "reading": put(status="pending", file_name="reading.jpg"),
            "no_url": put(status="duplicate", source_url=None, file_name="nourl.jpg"),
        }
        ids["kid_of_dup"] = put(status="merged", merged_into=ids["dup"], file_name="dup2.jpg")
        ids["kid_of_queue"] = put(status="merged", merged_into=ids["queue"], file_name="queue2.jpg")
    return ids


def blob(tid):
    from sqlalchemy import select
    with db.engine.begin() as c:
        return c.execute(select(db.trips.c.image_blob).where(db.trips.c.id == tid)).scalar()


ids = seed()
s = fbs.survey()
check("ชั่งน้ำหนักรูปที่ค้างอยู่ได้ (9 แถว)", s["total_rows"] == 9)
check("บอกได้ว่าล้างได้กี่แถว — 4 แถวที่จบแล้วและตามรอยกลับ Drive ได้",
      s["free_rows"] == 4)
check("แยกแถวที่ไม่มี source_url ออกมาเตือนไว้ ไม่เอาไปรวมกับที่ล้างได้",
      s["stuck_rows"] == 1 and s["free_rows"] + s["stuck_rows"] < s["total_rows"])

fbs.run(apply=False, log=lambda *_a: None)
check("รายงานอย่างเดียว ไม่แตะอะไรสักแถว", all(blob(i) is not None for i in ids.values()))

fbs.run(apply=True, log=lambda *_a: None)
check("ล้างรูปซ้ำ", blob(ids["dup"]) is None)
check("ล้างแถวที่ void", blob(ids["void"]) is None)
check("ล้างแถวที่อ่านไม่สำเร็จ", blob(ids["err"]) is None)
check("ล้างแถวที่อนุมัติแล้ว (ปกติว่างอยู่แล้ว แต่กันไว้)", blob(ids["approved"]) is None)
check("ครึ่งล่างที่พับกับแถวที่ล้าง ถูกล้างตามไปด้วย", blob(ids["kid_of_dup"]) is None)

check("❗ แถวที่ยังรอคนตรวจ ห้ามถูกล้าง", blob(ids["queue"]) == PIC)
check("❗ ครึ่งล่างของแถวที่รอคนตรวจ ห้ามถูกล้าง", blob(ids["kid_of_queue"]) == PIC)
check("❗ แถวที่ยังอ่านไม่เสร็จ ห้ามถูกล้าง", blob(ids["reading"]) == PIC)
check("❗ แถวที่ไม่มี source_url ห้ามถูกล้าง เพราะรูปจะหายจริง", blob(ids["no_url"]) == PIC)

after = fbs.survey()
check("รอบสองไม่มีอะไรเหลือให้ล้าง", after["free_rows"] == 0)
check("แถวไม่ได้หายไปไหน ยังอยู่ครบ 9 แถว",
      db.engine.connect().execute(__import__("sqlalchemy").select(
          __import__("sqlalchemy").func.count()).select_from(db.trips)).scalar() == 9)

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
