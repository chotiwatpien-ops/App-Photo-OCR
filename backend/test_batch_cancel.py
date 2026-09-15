# -*- coding: utf-8 -*-
"""Batch ที่ค้าง (2026-09-15): ยกเลิก เก็บคำตอบที่ได้แล้ว ปลดรูปที่เหลือไปอ่านสด — คิว Google ปลอม ฐานข้อมูล SQLite"""
import io
import os
import sys
import tempfile
from contextlib import redirect_stdout

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-bcancel-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import batch_client                                             # noqa: E402
import db                                                       # noqa: E402
import ingest                                                   # noqa: E402
import pipeline                                                 # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


job = db.create_job("ทดสอบ", "Trips", "2026-09-07", "2026-09-13", category="2 W Standard")
t_done, t1, t2, t3 = (db.create_trip(job, f"{n}.jpg", b"img", "image/jpeg") for n in ("done", "a", "b", "c"))
db.record_batch("batches/finished", "m", [t_done])
db.record_batch("batches/stuck", "m", [t1, t2, t3])

cancelled = []
STATE = {"batches/finished": "JOB_STATE_SUCCEEDED", "batches/stuck": "JOB_STATE_RUNNING"}
ANSWER = {"batches/finished": {t_done: {"x": 1}}, "batches/stuck": {}}


def fake_collect(name):
    st = STATE[name]
    if not st.endswith(("SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED")):
        return st, {}, {}
    return st, ANSWER[name], {}


def fake_cancel(name):
    cancelled.append(name)
    STATE[name] = "JOB_STATE_CANCELLED"
    ANSWER[name] = {t1: {"x": 1}}                    # Google had already answered one picture


applied = []


def fake_apply(tid, jid, data):
    applied.append(tid)
    db.update_trip(tid, {"status": "done", "check_status": "pass", "net_earnings": 50, "base_fare": 50,
                         "trip_date": "2026-09-08"})
    return "done"


batch_client.collect, batch_client.cancel = fake_collect, fake_cancel
pipeline.apply_extraction = fake_apply

# ---- a normal round: nothing is cancelled, the stuck batch keeps waiting ----
with redirect_stdout(io.StringIO()):
    got, errs, touched, issues = ingest.collect_batches(None)
check("รอบปกติ: batch ที่เสร็จแล้วถูกเก็บผล", t_done in applied and got == 1)
check("รอบปกติ: ไม่ยกเลิก batch ที่ยังรันอยู่", cancelled == [])
check("รอบปกติ: batch ที่ค้างยังเปิดรออยู่ รูปยังล็อก",
      [b["name"] for b in db.open_batches()] == ["batches/stuck"] and db.get_trip(t2)["batch_name"] == "batches/stuck")
check("รอบปกติ: รูปที่ batch ถืออยู่ไม่ถูกหยิบไปอ่านสด (กันจ่ายซ้ำ)",
      not {t1, t2, t3} & {t for t, _ in db.stuck_pending_trips()})

# ---- the cancel round ----
buf = io.StringIO()
with redirect_stdout(buf):
    got, errs, touched, issues = ingest.collect_batches(None, cancel_open=True)
log = buf.getvalue()
check("สั่งยกเลิก: ยกเลิกเฉพาะ batch ที่ยังไม่เสร็จ", cancelled == ["batches/stuck"])
check("สั่งยกเลิก: คำตอบที่ Google ทำเสร็จก่อนยกเลิกถูกเก็บมาใช้ (ไม่อ่านซ้ำ)", t1 in applied and got == 1)
check("สั่งยกเลิก: batch ถูกปิด ไม่ค้างในรายการรอ", db.open_batches() == [])
check("สั่งยกเลิก: รูปที่เหลือถูกปลดล็อก", db.get_trip(t2)["batch_name"] is None and db.get_trip(t3)["batch_name"] is None)
check("สั่งยกเลิก: รูปที่เหลือเข้าคิวอ่านสดของรอบนี้",
      {t2, t3} <= {t for t, _ in db.stuck_pending_trips()} and t1 not in {t for t, _ in db.stuck_pending_trips()})
check("สั่งยกเลิก: บอกใน log และเป็นรายการในหมวดปัญหาของรอบ",
      "ยกเลิก batch" in log and any(k.startswith("batch-cancel:") for k, _, _ in issues))


# ---- a cancel Google has not confirmed yet still releases the pictures ----
t4 = db.create_trip(job, "d.jpg", b"img", "image/jpeg")
db.record_batch("batches/slow", "m", [t4])
STATE["batches/slow"], ANSWER["batches/slow"] = "JOB_STATE_RUNNING", {}
batch_client.cancel = lambda name: cancelled.append(name)   # the state stays RUNNING for a while
with redirect_stdout(io.StringIO()):
    ingest.collect_batches(None, cancel_open=True)
check("ยกเลิกแล้วแต่ Google ยังไม่ยืนยัน: ปลดรูปไปอ่านสดเลย ไม่รอ",
      db.get_trip(t4)["batch_name"] is None and t4 in {t for t, _ in db.stuck_pending_trips()})


# ---- a cancel that fails leaves everything as it was ----
t5 = db.create_trip(job, "e.jpg", b"img", "image/jpeg")
db.record_batch("batches/stubborn", "m", [t5])
STATE["batches/stubborn"], ANSWER["batches/stubborn"] = "JOB_STATE_RUNNING", {}


def boom(name):
    raise RuntimeError("503")


batch_client.cancel = boom
with redirect_stdout(io.StringIO()):
    _g, errs5, _t, _i = ingest.collect_batches(None, cancel_open=True)
check("ยกเลิกไม่สำเร็จ: รูปยังล็อกกับ batch เดิม ไม่อ่านซ้ำ นับเป็น error",
      db.get_trip(t5)["batch_name"] == "batches/stubborn" and errs5 >= 1)

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
