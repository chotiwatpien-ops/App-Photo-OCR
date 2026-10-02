# -*- coding: utf-8 -*-
"""The close-week button: the checks that stop it, the steps in the order W36-W39 were closed,
the week locked only on a clean audit, and an ingest round that keeps out of the way.

Until 2026-10 a week was closed by pressing six GitHub workflows in an order only Fiat knew; a
customer running the app alone cannot. These tests hold the order and the stops."""
import os
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-close-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
os.environ["WEEKLY_TARGET_PER_GROUP"] = "3"
sys.path.insert(0, "backend")

from sqlalchemy import insert, update                           # noqa: E402

import close_week as cw                                         # noqa: E402
import config                                                   # noqa: E402
import db                                                       # noqa: E402
import file_after_read as far                                   # noqa: E402
import roster                                                   # noqa: E402
from drive_client import LocalDrive                             # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


W39 = ("2026-09-21", "2026-09-27")
root = Path(WORK) / "drive"
(root / "inbox" / "Week 21-27 Sep").mkdir(parents=True)
roster._drive = lambda: LocalDrive(root)          # report-only tools still open a Drive client

j = db.create_job("สมหมาย Taxi", "Trips", *W39, category="4 W Standard")
j_hold = db.create_job(far.HOLDING_RIDER, "Trips", *W39, folder_name="Week 21-27 Sep/_พร้อมอ่าน")
with db.engine.begin() as c:
    for i in range(3):
        c.execute(insert(db.trips).values(job_id=j, file_name=f"c{i}.jpg", status="done", committed=1,
                                          service_type="Standard Car", trip_date="2026-09-22", trip_time="10:0" + str(i),
                                          booking_code=f"A-{i}", customer_image=f"WK39-สมหมาย Taxi{i + 1}.jpg"))
    pend = c.execute(insert(db.trips).values(job_id=j, file_name="p.jpg", status="pending",
                                             committed=0)).inserted_primary_key[0]
    rev = c.execute(insert(db.trips).values(job_id=j, file_name="r.jpg", status="done", committed=0,
                                            service_type="Standard Car", trip_date="2026-09-23", trip_time="12:00")
                    ).inserted_primary_key[0]
    # read, waiting in _พร้อมอ่าน to be filed — not a person's to approve, must not block
    c.execute(insert(db.trips).values(job_id=j_hold, file_name="h.jpg", status="done", committed=0,
                                      service_type="Standard Car", trip_date="2026-09-24"))

AFTER = "2026-09-29"


def block(pre, key):
    return next(c for c in pre["checks"] if c["key"] == key)


# --- the checks ------------------------------------------------------------------------------
pre = cw.preflight(*W39, today=AFTER)
check("รูปที่ยังอ่านไม่เสร็จ → ปิดไม่ได้", not pre["ok"] and not block(pre, "pending")["ok"])
check("แถวในคิวตรวจ → ปิดไม่ได้ และบอกจำนวน", not block(pre, "review")["ok"] and "1 แถว" in block(pre, "review")["detail"])
with db.engine.begin() as c:
    c.execute(update(db.trips).where(db.trips.c.id == pend).values(status="done", committed=1, trip_date="2026-09-25", trip_time="11:00",
                                                                    service_type="Standard Car"))
    c.execute(update(db.trips).where(db.trips.c.id == rev).values(committed=1))
pre = cw.preflight(*W39, today=AFTER)
check("❗ แถวที่รอลงโฟลเดอร์ใน _พร้อมอ่าน ไม่นับเป็นคิวตรวจ", block(pre, "review")["ok"])
os.environ["WEEKLY_TARGET_PER_GROUP"] = "9"
config.WEEKLY_TARGET_PER_GROUP = 9
pre9 = cw.preflight(*W39, today=AFTER)
check("❗ แถวรอลงโฟลเดอร์ที่กลุ่มยังมีที่ว่าง → ปิดไม่ได้ (ปิดแล้วจะไม่มีใครลงให้)",
      not pre9["ok"] and not block(pre9, "staged")["ok"] and "1 แถว" in block(pre9, "staged")["detail"])
config.WEEKLY_TARGET_PER_GROUP = 3
os.environ["WEEKLY_TARGET_PER_GROUP"] = "3"
check("กลุ่มเต็มแล้ว แถวรอลงโฟลเดอร์ไม่ขวาง (ขั้นกองพักย้ายไปสัปดาห์หน้าให้)",
      block(cw.preflight(*W39, today=AFTER), "staged")["ok"])
check("อ่านครบ คิวว่าง → ปิดได้", pre["ok"])
check("สัปดาห์ยังไม่จบ = เตือน ไม่ห้าม",
      cw.preflight(*W39, today="2026-09-26")["ok"] and not block(cw.preflight(*W39, today="2026-09-26"), "ended")["ok"])
check("หน้าเว็บเห็นยอดตาม Service Type", pre["card"]["by_service"]["Standard Car"] == 5)
check("กลุ่มเกินเป้าบอกว่าเกินเท่าไหร่", pre["card"]["over"] == {"Standard Car": 2})

with db.engine.begin() as c:
    rid = c.execute(insert(db.ingest_runs).values(started_at=db._now())).inserted_primary_key[0]
check("ingest กำลังรัน → ปิดไม่ได้", not cw.preflight(*W39, today=AFTER)["ok"])
with db.engine.begin() as c:
    c.execute(update(db.ingest_runs).where(db.ingest_runs.c.id == rid).values(started_at="2026-01-01T00:00:00"))
check("รอบ ingest ที่ค้างเกิน 3 ชม. (ตายไปแล้ว) ไม่ขวาง", cw.preflight(*W39, today=AFTER)["ok"])

# --- plan: every step report-only -------------------------------------------------------------
run = db.create_close_run(*W39, "plan")
rc = cw.Runner(run, *W39, "plan").go()
r = db.get_close_run(run)
st = {s["key"]: s for s in r["steps"]}
check("แผนรันจบ", rc == 0 and r["status"] == "done")
check("แผนไม่สร้างรูป ไม่ติดป้าย", st["pictures"]["status"] == "skipped" and st["lock"]["status"] == "skipped")
check("ขั้นที่เหลือรันครบและมีสรุปให้อ่าน",
      all(st[k]["status"] == "done" and st[k]["summary"] for k in ("rehome", "carry", "carry_back", "staged", "phase3", "audit")))
check("❗ แผนยกรถยนต์ 2 คัน — แถวที่ค้าง _พร้อมอ่าน ไม่นับเป็นงานของกลุ่ม", "เกิน 2" in st["carry"]["summary"])
check("กองพักย้ายแถวค้างไปสัปดาห์หน้า", "ย้ายไปสัปดาห์หน้า 1" in st["staged"]["summary"])
check("แผนไม่ปิดสัปดาห์", not db.week_closed(W39[0]))
check("ผลแผนเก็บยอดก่อนและหลัง", r["result"]["before"]["by_service"]["Standard Car"] == 5 and "after" in r["result"])
check("แผนคาดยอดหลังปิด: กลุ่มที่เกินถูกยกลงเหลือเท่าเป้า",
      r["result"]["after"]["by_service"]["Standard Car"] == 3 and r["result"]["after"]["projected"])
check("แผนคาดว่ากลุ่มที่ไม่มีงานให้ดึงกลับยังขาด", r["result"]["after"]["under"].get("Saver Bike") == 3)
check("audit ในแผนบอกว่าตรวจจากสภาพก่อนย้าย", st["audit"]["summary"].startswith("ตรวจจากสภาพตอนนี้"))

# --- apply: order, lock on a clean audit, stop on failure -------------------------------------
calls = []


def stub(name, rv=0, text=""):
    def f(argv=None, *a, **k):
        calls.append((name, argv))
        print(text or f"{name} ok")
        return rv
    return f


class FakeDrive:
    def ensure_folder(self, *_a):
        return "audit-folder"

    def upload_xlsx(self, *_a):
        return "audit-file"


import carry_back, carry_excess, ingest, move_staged, rehome_by_service, week_audit, week_phase3  # noqa: E401,E402

saved = (rehome_by_service.main, carry_excess.main, carry_back.main, move_staged.main, week_phase3.main,
         ingest.export_only, week_audit.pictures_on_drive, week_audit.audit, week_audit.build_xlsx, roster._drive, cw.week_folder)
rehome_by_service.main = stub("rehome")
carry_excess.main = stub("carry")
carry_back.main = stub("carry_back")
move_staged.main = stub("staged")
ingest.export_only = lambda *a, **k: (calls.append(("pictures", k.get("weeks"))), (0, []))[1]
week_phase3.main = stub("phase3", text="วางลง Drive แล้ว: x → https://drive.google.com/file/d/FILE123/view")
week_audit.pictures_on_drive = lambda *a: {}
clean = {k: [] for k in cw.BLOCKING}
week_audit.audit = lambda rows, pics: dict(clean)
week_audit.build_xlsx = lambda *a: b"xlsx"
roster._drive = lambda: FakeDrive()
cw.week_folder = lambda *a: "Week 21-27 Sep"

run = db.create_close_run(*W39, "apply")
rc = cw.Runner(run, *W39, "apply").go()
r = db.get_close_run(run)
check("ปิดจริงรันจบ", rc == 0 and r["status"] == "done", )
check("❗ ลำดับเดียวกับที่ปิด W36–W39: ย้ายกลุ่ม → ยก → ดึงกลับ → กองพัก → รูป → ไฟล์",
      [n for n, _ in calls] == ["rehome", "carry", "carry_back", "staged", "pictures", "phase3"])
check("ทุกขั้นทำจริง (--apply)", all("--apply" in a for n, a in calls if n in ("rehome", "carry", "carry_back", "staged")))
check("ใช้ชื่อโฟลเดอร์สัปดาห์จาก Drive", all("Week 21-27 Sep" in a for n, a in calls if n in ("rehome", "carry", "carry_back")))
check("สร้างรูปใหม่แค่ 2 สัปดาห์ที่เกี่ยว", dict(calls)["pictures"] == {"2026-W39", "2026-W40"})
check("ไฟล์ Phase 3 วางลง Drive", "--to-drive" in dict(calls)["phase3"])
check("เก็บลิงก์ไฟล์ให้หน้าเว็บ", r["result"]["file"] == "https://drive.google.com/file/d/FILE123/view")
check("เก็บลิงก์รายงานตรวจให้หน้าเว็บ", r["result"]["audit_file"] == "https://drive.google.com/file/d/audit-file/view")
check("audit สะอาด → ติดป้ายปิดแล้ว", db.week_closed(W39[0]) and r["result"]["closed"])
check("ข้อความบอกว่าปิดแล้ว", r["message"].startswith("ปิดสัปดาห์แล้ว"))

pre = cw.preflight(*W39, today=AFTER)
check("ปิดแล้ว → ปิดซ้ำไม่ได้จนกว่าจะเปิดใหม่", not block(pre, "closed")["ok"])
db.reopen_week(W39[0])

calls.clear()
week_audit.audit = lambda rows, pics: {**clean, "รูปหายจาก Drive": [1, 2]}
run = db.create_close_run(*W39, "apply")
cw.Runner(run, *W39, "apply").go()
r = db.get_close_run(run)
lock = next(s for s in r["steps"] if s["key"] == "lock")
check("❗ audit เจอรูปหาย → ทำครบแต่ไม่ติดป้ายปิด", not db.week_closed(W39[0]) and lock["status"] == "skipped")
check("บอกเหตุผลที่ไม่ปิด", "รูปหายจาก Drive 2" in lock["summary"] and "ยังไม่ติดป้ายปิด" in r["message"])

calls.clear()
carry_excess.main = stub("carry", rv=1)
week_audit.audit = lambda rows, pics: dict(clean)
run = db.create_close_run(*W39, "apply")
rc = cw.Runner(run, *W39, "apply").go()
r = db.get_close_run(run)
st = {s["key"]: s["status"] for s in r["steps"]}
check("❗ ขั้นไหนล้ม หยุดตรงนั้น ไม่ทำขั้นถัดไป",
      rc == 1 and r["status"] == "failed" and [n for n, _ in calls] == ["rehome", "carry"])
check("หน้าเว็บเห็นว่าล้มขั้นไหน", st["carry"] == "failed" and st["carry_back"] == "skipped" and st["rehome"] == "done")
check("ล้มแล้วไม่ปิดสัปดาห์", not db.week_closed(W39[0]))

with db.engine.begin() as c:   # something new to read: the real close refuses before touching anything
    c.execute(insert(db.trips).values(job_id=j, file_name="late.jpg", status="pending", committed=0))
calls.clear()
run = db.create_close_run(*W39, "apply")
rc = cw.Runner(run, *W39, "apply").go()
r = db.get_close_run(run)
check("❗ เงื่อนไขไม่ผ่าน → ไม่ทำสักขั้น", rc == 1 and r["status"] == "blocked" and not calls)
check("บอกเหตุผลเป็นภาษาคน", "รูปที่ยังอ่านไม่เสร็จ" in r["message"])

(rehome_by_service.main, carry_excess.main, carry_back.main, move_staged.main, week_phase3.main,
 ingest.export_only, week_audit.pictures_on_drive, week_audit.audit, week_audit.build_xlsx, roster._drive, cw.week_folder) = saved

# --- ingest keeps out of the way --------------------------------------------------------------
live = db.create_close_run(*W39, "apply")
db.update_close_run(live, status="running")
sys.argv = ["ingest.py"]
try:
    ingest.main()
    skipped = False
except SystemExit as e:
    skipped = e.code == 0
check("❗ ingest ข้ามรอบระหว่างกำลังปิดสัปดาห์จริง", skipped)
db.update_close_run(live, status="done")
plan_run = db.create_close_run(*W39, "plan")
check("รอบดูแผนไม่กัน ingest", db.close_run_active()["mode"] == "plan")
db.update_close_run(plan_run, status="done")
with db.engine.begin() as c:
    c.execute(update(db.close_runs).where(db.close_runs.c.id == live)
              .values(status="running", created_at="2026-01-01T00:00:00"))
check("รอบปิดที่ค้างเกิน 3 ชม. (runner ตาย) ไม่นับว่ากำลังรัน", db.close_run_active() is None)
db.update_close_run(live, status="failed")

# --- the web endpoints ------------------------------------------------------------------------
import main                                                     # noqa: E402
from fastapi.testclient import TestClient                       # noqa: E402

config.APP_PASSWORD = ""
sent = []
main._dispatch = lambda wf, inputs=None: sent.append((wf, inputs)) or True
web = TestClient(main.app)
with db.engine.begin() as c:
    c.execute(update(db.trips).where(db.trips.c.file_name == "late.jpg")      # approving needs a date
              .values(status="done", committed=1, trip_date="2026-09-26", trip_time="18:00"))
page = web.get(f"/api/close-week?week={W39[0]}").json()
check("หน้าเว็บได้เงื่อนไขและยอดของสัปดาห์", page["week"] == W39[0] and "checks" in page["preflight"])
check("หน้าเว็บไม่ส่ง log ทั้งก้อน", all("log" not in s for r in page["runs"] for s in r["steps"]))
for r in page["runs"]:              # the test's earlier runs stand for history; none is fresh
    db.update_close_run(r["id"], finished_at="2026-01-01T00:00:00")
res = web.post(f"/api/close-week/{W39[0]}/apply")
check("❗ ปิดจริงโดยไม่มีแผนล่าสุด → ไม่ให้กด", res.status_code == 409 and "ดูแผน" in res.json()["detail"])
res = web.post(f"/api/close-week/{W39[0]}/plan")
check("กดดูแผน → สร้างรอบและสั่ง workflow พร้อมเลขรอบ",
      res.status_code == 200 and sent[-1][0] == "close-week.yml"
      and sent[-1][1] == {"week_from": "2026-09-21", "week_to": "2026-09-27", "mode": "plan",
                          "run_id": str(res.json()["id"])})
check("กดซ้ำระหว่างรอบยังไม่จบ → ไม่ให้กด", web.post(f"/api/close-week/{W39[0]}/plan").status_code == 409)
db.update_close_run(res.json()["id"], status="done", finished_at=db._now())
check("แผนเสร็จแล้ว → หน้าเว็บเปิดปุ่มปิดจริง", web.get(f"/api/close-week?week={W39[0]}").json()["plan_ok"])
res = web.post(f"/api/close-week/{W39[0]}/apply")
check("มีแผนล่าสุด → ปิดจริงได้", res.status_code == 200 and sent[-1][1]["mode"] == "apply")
check("ดูรอบเดียวได้พร้อม log", web.get(f"/api/close-week/runs/{res.json()['id']}").json()["mode"] == "apply")
files = web.get(f"/api/close-week?week={W39[0]}").json()["files"]
check("หน้าเว็บได้ลิงก์ไฟล์ Phase 3 และรายงานตรวจจากรอบปิดล่าสุด",
      files["phase3"].endswith("FILE123/view") and files["audit"].endswith("audit-file/view"))
x = web.get(f"/api/export/week?week={W39[0]}")
check("ดาวน์โหลดไฟล์ส่งลูกค้าของสัปดาห์ได้", x.status_code == 200 and "Phase%203" in x.headers["content-disposition"]
      and int(x.headers["x-row-count"]) > 0)
check("สัปดาห์ที่ยังไม่มีแถว → 404 พร้อมเหตุผล", web.get("/api/export/week?week=2020-01-06").status_code == 404)

print("\nผ่านทั้งหมด" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
