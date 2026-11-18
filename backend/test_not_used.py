# -*- coding: utf-8 -*-
"""Nothing is deleted any more (Fiat 2026-11-18, for visibility): a person takes a waiting row out
of the work, the row stays, the reports can count it and it can come back."""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-notused-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from fastapi.testclient import TestClient                       # noqa: E402
from sqlalchemy import insert                                   # noqa: E402

import config                                                   # noqa: E402
import db                                                       # noqa: E402
import main                                                     # noqa: E402

db.init_db()
config.APP_PASSWORD = ""
web = TestClient(main.app)
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


W = ("2026-11-09", "2026-11-15")
job = db.create_job("สมชาย Win", "Trips", *W, category="2 W Saver")
other_week = db.create_job("สมชาย Win", "Trips", "2026-11-16", "2026-11-22", category="2 W Saver")


def trip(name, jid=job, **kw):
    with db.engine.begin() as c:
        return c.execute(insert(db.trips).values(
            job_id=jid, file_name=name, **{**dict(status="done", committed=0), **kw})).inserted_primary_key[0]


def out(tid):
    return web.post(f"/api/trips/{tid}/not-used")


def status(tid):
    return db.get_trip(tid)["status"]


def in_panel(tid, everything=False):
    return any(r["id"] == tid for r in db.discarded_duplicates(everything=everything)["rows"])


counted = trip("a.jpg", booking_code="A-TESTAAA000001", base_fare=40, committed=1)
same = trip("b.jpg", booking_code="A-TESTAAA000001", base_fare=40)
near = trip("c.jpg", booking_code="A-TESTAAA000091", base_fare=40)
other_fare = trip("d.jpg", booking_code="A-TESTAAA000092", base_fare=99)
plain = trip("e.jpg", booking_code="A-TESTBBB000001", base_fare=50, note="เดิม")
unread = trip("f.jpg", status="error")
reading = trip("g.jpg", status="pending")
elsewhere = trip("h.jpg", booking_code="A-TESTCCC000001", base_fare=60)
trip("i.jpg", other_week, booking_code="A-TESTCCC000001", base_fare=60, committed=1)

check("❗ ไม่มีทางลบแถวผ่านเว็บแล้ว", web.delete(f"/api/trips/{plain}").status_code == 405)
check("❗ เลขจองตรงกับงานที่นับแล้ว → ซ้ำ แถวยังอยู่", out(same).json()["status"] == "duplicate"
      and "ซ้ำกับ a.jpg" in db.get_trip(same)["note"])
check("❗ เลขจองเพี้ยนแต่ค่ารอบตรง → ซ้ำ", out(near).json()["status"] == "duplicate")
check("เลขจองใกล้กันแต่ค่ารอบต่าง → ไม่นับว่าซ้ำ", out(other_fare).json()["status"] == "voided")
check("❗ ไม่ตรงกับงานไหน → ยกเลิก และโน้ตเดิมยังอยู่", out(plain).json()["status"] == "voided"
      and db.get_trip(plain)["note"] == f"{db.NOT_USED}: ไม่ใช่งาน | เดิม", db.get_trip(plain)["note"])
check("แถวที่อ่านไม่ได้เอาออกได้", out(unread).json()["status"] == "voided")
check("❗ เลขจองซ้ำกับสัปดาห์อื่นไม่ถือว่าซ้ำ (ลูกค้า 2026-09-14)", out(elsewhere).json()["status"] == "voided")

check("❗ งานที่อนุมัติแล้วเอาออกไม่ได้", out(counted).status_code == 409 and status(counted) == "done")
check("❗ แถวที่ยังอ่านไม่เสร็จเอาออกไม่ได้", out(reading).status_code == 409 and status(reading) == "pending")
check("เอาออกซ้ำไม่ได้", out(plain).status_code == 409)
check("แถวที่ไม่มีอยู่ → 404", out(999999).status_code == 404)

check("❗ เห็นในงานที่ไม่ได้ใช้ ทั้งซ้ำและยกเลิก", in_panel(same) and in_panel(plain))
db.void_trips([trip("j.jpg")], "ทิ้ง: คู่ผิด")
check("แถวที่ระบบยกเลิกเพราะจับคู่ผิดไม่ปนเข้ามา",
      not any(r["file_name"] == "j.jpg" for r in db.discarded_duplicates(everything=True)["rows"]))
db.clear_discarded_log()
check("❗ กดซ่อนรายการเก่าแล้ว งานที่คนกดไม่ใช้ยังเห็น", in_panel(plain) and in_panel(same))

res = web.post(f"/api/trips/{plain}/restore")
got = db.get_trip(plain)
check("❗ เอากลับเข้าคิวได้", res.status_code == 200 and got["status"] == "done" and not got["committed"]
      and db.KEPT in got["note"], (res.status_code, got["status"], got["note"]))
check("ยังเอากลับไม่ได้ถ้าเลขจองนับไปแล้วในสัปดาห์นี้", web.post(f"/api/trips/{same}/restore").status_code == 409
      and status(same) == "duplicate")

first = trip("k.jpg", booking_code="A-TESTDDD000001", base_fare=70)
second = trip("l.jpg", booking_code="A-TESTDDD000001", base_fare=70, duplicate_of=first)
check("❗ ซ้ำกับแถวที่ยังรอตรวจ → ซ้ำ", out(second).json()["status"] == "duplicate")
check("❗ แถวคู่ถูกไม่ใช้ตาม → แถวที่พักไว้กลับเข้าคิว งานไม่หาย",
      out(first).json()["status"] == "voided" and status(second) == "done")
top = trip("m.jpg", booking_code="A-TESTEEE000001", base_fare=80)
copy = trip("n.jpg", booking_code="A-TESTEEE000001", base_fare=80, duplicate_of=top)
out(top)
check("แถวที่ชี้มาหาแถวนี้ถูกปลดธงซ้ำ", db.get_trip(copy)["duplicate_of"] is None)

with open(".github/workflows/ingest.yml", encoding="utf-8") as f:
    workflow = f.read()
check("❗ workflow อ่านรูปไม่มีช่องสั่งลบแล้ว",
      not any(w in workflow for w in ("delete_jobs", "delete_trips", "redo_model", "--delete-", "--redo-model")))
check("❗ ไม่มีคำสั่งลบทั้ง job หรือลบตามโมเดลในฐานข้อมูล",
      not hasattr(db, "delete_jobs") and not hasattr(db, "delete_model_trips"))

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
