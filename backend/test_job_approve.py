# -*- coding: utf-8 -*-
"""The rider job screen's อนุมัติ button (POST /api/jobs/{id}/commit).

In the cloud app it approved every read row of the job, rows whose numbers do not add up included,
and with `force` it also stepped past the in-job repeat check. It was taken off the review queue
for that reason, yet it stayed one click away behind 'ดูทั้งหมด' and 'งานของไรเดอร์'. Now the
cloud app approves only what passed, through the same guarded path as the queue's bulk button,
and says what stayed and why. The local app still writes the whole job to its workbook."""
import os
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-jobapprove-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ["PHOTO_OCR_EXCEL_APPEND"] = "0"          # the cloud app
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import config                                                   # noqa: E402
import db                                                       # noqa: E402
import excel_writer                                             # noqa: E402
import main                                                     # noqa: E402
import pipeline                                                 # noqa: E402
from fastapi.testclient import TestClient                       # noqa: E402

db.init_db()
config.APP_PASSWORD = ""
web = TestClient(main.app)
W = ("2026-11-16", "2026-11-22")
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


def slip(jid, code, check_status="pass", net=62.0, base=62.0, date=W[0], **more):
    tid = db.create_trip(jid, f"{code}.jpg", b"x", "image/jpeg")
    db.update_trip(tid, {"status": "done", "kind": "full", "booking_code": code, "net_earnings": net,
                         "base_fare": base, "check_status": check_status, "trip_date": date,
                         "trip_time": "10:00", "service_type": "Saver Bike", **more})
    return tid


def approved(tid):
    return db.get_trip(tid)["committed"] == 1


# --- cloud: one passing row, one whose numbers fail ---------------------------------------------
j = db.create_job("ไรเดอร์ ก", "Trips", *W, category="2 W Saver")
good = slip(j, "A-PASS00001")
bad = slip(j, "A-FAIL00001", check_status="fail", net=93.0, base=78.0)
r = web.post(f"/api/jobs/{j}/commit")
body = r.json()
check("❗ ปุ่มอนุมัติทั้งงาน: แถวที่ตัวเลขผ่านถูกอนุมัติ", r.status_code == 200 and approved(good))
check("❗ แถวที่ตัวเลขไม่ลงตัวยังรออยู่ ไม่ถูกอนุมัติไปด้วย", not approved(bad))
check("บอกว่าอนุมัติกี่แถว เหลือกี่แถว เพราะอะไร",
      body.get("written") == 1 and body.get("left") == 1 and body.get("reasons") == {"fail": 1})
check("งานยังไม่ปิด เพราะยังมีแถวรอ", db.get_job(j)["status"] != "committed")

r = web.post(f"/api/jobs/{j}/commit?force=true")
check("❗ force ก็ข้ามไม่ได้: แถวที่ไม่ผ่านยังรออยู่", r.status_code == 200 and not approved(bad)
      and r.json().get("written") == 0 and r.json().get("left") == 1)

r = web.post(f"/api/trips/{bad}/approve")
check("คนยังอนุมัติทีละแถวได้ด้วยปุ่มของแถวนั้น", r.status_code == 200 and approved(bad))

# --- cloud: every reason a row stays is counted -------------------------------------------------
j2 = db.create_job("ไรเดอร์ ข", "Trips", *W, category="2 W Saver")
first = slip(j2, "A-PASS00002")
twin = slip(j2, "A-PASS00002", duplicate_of=first)
undated = slip(j2, "A-NODATE001", date=None)
unread = slip(j2, "A-NODATA001", check_status="no_data", net=None, base=None)
body = web.post(f"/api/jobs/{j2}/commit?force=true").json()
check("❗ รูปซ้ำในงานเดียวกันไม่ถูกอนุมัติ แม้ส่ง force", approved(first) and not approved(twin))
check("แถวไม่มีวันที่และแถวข้อมูลไม่ครบยังรออยู่", not approved(undated) and not approved(unread))
check("เหตุผลของแถวที่เหลือครบทุกแบบ",
      body.get("written") == 1 and body.get("left") == 3
      and body.get("reasons") == {"dup": 1, "nodate": 1, "no_data": 1})

# --- the waiting room is nobody's job to approve -------------------------------------------------
hold = db.create_job(db.HOLDING_RIDER, "Trips", *W)
staged = slip(hold, "A-STAGED001")
r = web.post(f"/api/jobs/{hold}/commit")
check("❗ งานกองพัก (รออ่าน) อนุมัติทั้งงานไม่ได้", r.status_code == 409 and not approved(staged))

# --- local: the whole job still goes to the workbook --------------------------------------------
config.EXCEL_APPEND = True
config.EXCEL_PATH = Path(WORK) / "Rider Trips.xlsx"
wrote = []
excel_writer.append_trips = lambda rider, rows: wrote.append([t["id"] for t in rows])
excel_writer.count_existing_rows = lambda *_a: 0
pipeline.customer_images = lambda *_a: []
j3 = db.create_job("ไรเดอร์ ค", "Trips", *W)
a = slip(j3, "A-LOCAL0001")
b = slip(j3, "A-LOCAL0002", check_status="fail", net=93.0, base=78.0)
r = web.post(f"/api/jobs/{j3}/commit")
check("เครื่องตัวเอง (บันทึกลง Excel): ยังบันทึกทั้งงานเหมือนเดิม",
      r.status_code == 200 and r.json()["written"] == 2 and wrote == [[a, b]]
      and approved(a) and approved(b) and db.get_job(j3)["status"] == "committed")
r = web.post(f"/api/jobs/{hold}/commit")
check("เครื่องตัวเอง: งานกองพักก็อนุมัติทั้งงานไม่ได้",
      r.status_code == 409 and not approved(staged) and len(wrote) == 1)

print("\nผ่านทั้งหมด" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
