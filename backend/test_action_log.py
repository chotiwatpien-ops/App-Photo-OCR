# -*- coding: utf-8 -*-
"""Support can see who changed what: the action log, the diag views, and the run archive.

Asked for on 2026-10-02 ("ต้องมี Log หรืออะไรให้ทางผมสามารถ MA หรือเช็คได้") once the customer is
to run the app alone. A change nobody can trace is a dispute nobody can settle."""
import io
import json
import os
import sys
import tempfile
import zipfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-actions-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from sqlalchemy import update                                   # noqa: E402

import archive_runs                                             # noqa: E402
import config                                                   # noqa: E402
import db                                                       # noqa: E402
import main                                                     # noqa: E402
from fastapi.testclient import TestClient                       # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


config.APP_PASSWORD = "secret-pass"
config.DIAG_KEY = "k-123"
web = TestClient(main.app)
XFF = {"X-Forwarded-For": "203.0.113.7, 10.0.0.1"}

# --- logging in ---------------------------------------------------------------------------------
r = web.post("/api/login", json={"password": "wrong"}, headers=XFF)
log = db.list_actions(5)
check("รหัสผิด → บันทึกว่ามีคนพยายาม login", log[0]["action"] == "auth.login" and log[0]["status"] == 401)
check("❗ ไม่เก็บรหัสผ่านไว้ใน log", "wrong" not in json.dumps(log, ensure_ascii=False))
check("IP มาจาก X-Forwarded-For ตัวแรก (Render อยู่หน้าเว็บ)", log[0]["ip"] == "203.0.113.7")
r = web.post("/api/trips/1/approve")
check("กดโดยไม่ login → ถูกปฏิเสธและถูกบันทึก", r.status_code == 401 and db.list_actions(1)[0]["status"] == 401)
web.post("/api/login", json={"password": "secret-pass"})

# --- changing a row -----------------------------------------------------------------------------
job = db.create_job("สมหมาย Taxi", "Trips", "2026-09-21", "2026-09-27", category="4 W Standard")
tid = db.create_trip(job, "a.jpg", b"x", "image/jpeg")
with db.engine.begin() as c:
    c.execute(update(db.trips).where(db.trips.c.id == tid).values(
        status="done", base_fare=80, net_earnings=80, trip_date="2026-09-22", booking_code="A-1"))
n_before = len(db.list_actions(1000))
web.get(f"/api/jobs/{job}")
check("การเปิดดู (GET) ไม่ถูกบันทึก", len(db.list_actions(1000)) == n_before)

web.patch(f"/api/trips/{tid}", json={"base_fare": 85, "net_earnings": 85})
a = db.list_actions(1)[0]
check("แก้ตัวเลข → trip.edit พร้อมเลขแถว", a["action"] == "trip.edit" and a["target"] == f"trip:{tid}")
check("❗ เก็บค่าก่อนและหลังแก้", a["detail"]["before"] == {"base_fare": 80, "net_earnings": 80}
      and a["detail"]["after"] == {"base_fare": 85, "net_earnings": 85})

tid2 = db.create_trip(job, "b.jpg", b"y", "image/jpeg")
with db.engine.begin() as c:
    c.execute(update(db.trips).where(db.trips.c.id == tid2).values(status="done", base_fare=60, booking_code="B-2"))
import trash_picture                                            # noqa: E402
trash_picture.move_to_trash = lambda trip_id: None
web.delete(f"/api/trips/{tid2}")
a = db.list_actions(1)[0]
check("❗ ลบแถว → เก็บค่าของแถวไว้ก่อนหาย", a["action"] == "trip.delete"
      and a["detail"]["row"]["booking_code"] == "B-2" and a["detail"]["row"]["base_fare"] == 60)

web.post(f"/api/trips/{tid}/approve")
check("อนุมัติ → trip.approve", db.list_actions(1)[0]["action"] == "trip.approve")
web.post("/api/weeks/2026-09-21/close?date_to=2026-09-27")
web.post("/api/weeks/2026-09-21/reopen")
acts = [x["action"] for x in db.list_actions(2)]
check("ล็อก/เปิดสัปดาห์ถูกบันทึก", acts == ["week.unlock", "week.lock"])
r = web.post("/api/jobs/999999/commit")
check("กดแล้วไม่สำเร็จก็ถูกบันทึกพร้อมสถานะ", db.list_actions(1)[0]["status"] == 404
      and db.list_actions(1)[0]["action"] == "job.approve")

# --- the support views --------------------------------------------------------------------------
web.post("/api/logout")
web.cookies.clear()
check("❗ ดู diag โดยไม่มี key และไม่ login → ไม่ได้", web.get("/api/diag/actions").status_code == 401)
K = {"X-Diag-Key": "k-123"}
r = web.get(f"/api/diag/actions?target=trip:{tid}", headers=K).json()["actions"]
check("ค้นตามแถว: เห็นประวัติของแถวนั้นครบ", [x["action"] for x in r] == ["trip.approve", "trip.edit"])
check("ค้นตามประเภท: trip. ได้ทุกอย่างของแถว",
      {x["action"] for x in web.get("/api/diag/actions?action=trip.", headers=K).json()["actions"]}
      == {"trip.edit", "trip.delete", "trip.approve"})
check("❗ ไม่มีทางลบหรือแก้ action log ผ่านเว็บ",
      not any(p.path.startswith("/api/diag/actions") and m != "GET"
              for p in main.app.routes for m in getattr(p, "methods", set()) or set()))

run = db.create_close_run("2026-09-21", "2026-09-27", "plan")
db.update_close_run(run, status="done", steps=[{"key": "carry", "title": "ยก", "status": "done",
                                                 "summary": "สรุป", "log": "log เต็ม"}])
lst = web.get("/api/diag/close-runs", headers=K).json()["runs"]
check("รายการรอบปิดไม่ส่ง log ทั้งก้อน", lst[0]["id"] == run and "log" not in lst[0]["steps"][0])
check("เปิดรอบเดียวได้ log เต็ม", web.get(f"/api/diag/close-runs/{run}", headers=K).json()["steps"][0]["log"] == "log เต็ม")

# --- the run archive ----------------------------------------------------------------------------
check("ตัดเวลาหน้าบรรทัดของ GitHub ออก", archive_runs.tail("2026-10-02T08:00:00.1234567Z สวัสดี\n") == "สวัสดี\n")
big = archive_runs.tail("ก" * 50_000)
check("log ยาวเก็บแค่ท้าย", len(big.encode("utf-8")) <= archive_runs.TAIL_BYTES + 100 and big.startswith("…(ตัดต้น log)"))
check("เวลา GitHub (UTC) แปลงเป็นเวลาไทย", archive_runs.bkk("2026-10-02T08:00:00Z") == "2026-10-02T15:00:00")

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("0_close.txt", "2026-10-02T08:00:00.1Z ปิดสัปดาห์แล้ว\n")
    z.writestr("close/3_Close the week.txt", "ซ้ำกับไฟล์บน")
ZIP = buf.getvalue()
RUNS = [{"id": 111, "name": "Close week", "event": "workflow_dispatch", "display_title": "Close week",
         "status": "completed", "conclusion": "failure", "run_started_at": "2026-10-02T08:00:00Z",
         "updated_at": "2026-10-02T08:10:00Z", "actor": {"login": "someone"}, "html_url": "https://x/111"}]
asked = []


def fake_get(url, token, raw=False):
    asked.append(url)
    return ZIP if raw else {"workflow_runs": RUNS}


archive_runs._get = fake_get
n1 = archive_runs.archive("me/repo", "t", days=3, log=lambda *_: None)
n2 = archive_runs.archive("me/repo", "t", days=3, log=lambda *_: None)
row = db.get_workflow_run(111)
check("เก็บรอบที่จบแล้วลงฐานข้อมูล", n1 == 1 and row["conclusion"] == "failure" and row["started_at"] == "2026-10-02T15:00:00")
check("❗ log เอาไฟล์ของ job (ไม่ซ้ำกับไฟล์ราย step)", row["log_tail"].count("ปิดสัปดาห์แล้ว") == 1 and "ซ้ำกับไฟล์บน" not in row["log_tail"])
check("เก็บซ้ำไม่ได้ รอบเดิมไม่ถูกดึง log อีก", n2 == 0 and sum("/logs" in u for u in asked) == 1)
check("ขอรายการจาก GitHub ด้วยช่วงเวลาที่ encode แล้ว", "created=%3E%3D" in asked[0])
with db.engine.begin() as c:
    c.execute(update(db.workflow_runs).where(db.workflow_runs.c.id == 111).values(started_at="2025-01-01T00:00:00"))
check("ของเก่ากว่า 400 วันถูกลบ", db.prune_workflow_runs() == 1 and db.get_workflow_run(111) is None)
db.archive_workflow_run({"id": 222, "workflow": "Weekly ingest", "conclusion": "failure",
                         "started_at": db._now(), "log_tail": "boom"})
check("diag เห็นรอบที่เก็บไว้", web.get("/api/diag/runs?workflow=ingest", headers=K).json()["runs"][0]["id"] == 222)
check("diag เปิด log ของรอบได้", web.get("/api/diag/runs/222", headers=K).json()["log_tail"] == "boom")

sup = web.get("/api/diag/support", headers=K).json()
check("หน้า support ได้ภาพรวมครบในครั้งเดียว",
      {"counts", "ingest", "issues", "batches", "close_runs", "failed_runs", "actions"} <= set(sup))
check("หน้า support เห็น workflow ที่ล้มใน 7 วัน", [x["id"] for x in sup["failed_runs"]] == [222])
check("หน้า support เห็นว่าใครทำอะไรล่าสุด", sup["actions"][0]["action"] in ("auth.logout", "job.approve"))

print("\nผ่านทั้งหมด" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
