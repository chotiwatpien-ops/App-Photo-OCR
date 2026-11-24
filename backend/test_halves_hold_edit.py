# -*- coding: utf-8 -*-
"""A stitched pair held because its halves disagree stays held while a person edits it, and the
review queue is told why.

The reading holds such a row (pipeline.halves_conflict). The edit endpoint judged an edited row
with the reader's arithmetic alone, which a mis-paired top passes by itself, so retyping any money
field turned the row back to 'pass' and 'approve all that pass' took it. And the queue had only
the status to go on, so it called the row 'ข้อมูลไม่ครบ'."""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-halves-edit-")
os.environ["PHOTO_OCR_EXCEL_APPEND"] = "0"
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import config                                                   # noqa: E402
import db                                                       # noqa: E402
import main                                                     # noqa: E402
from fastapi.testclient import TestClient                       # noqa: E402

db.init_db()
config.APP_PASSWORD = ""
web = TestClient(main.app)
W = ("2026-11-16", "2026-11-22")
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


def slip(jid, name, code, **money):
    tid = db.create_trip(jid, name, b"x", "image/jpeg")
    db.update_trip(tid, {"status": "done", "kind": "full", "booking_code": code, "trip_date": W[0],
                         "trip_time": "10:00", "service_type": "Saver Bike", **money})
    return tid


job = db.create_job("ก Win", "Trips", *W)
# the W47 shape: this trip's top (105 = 100 + 5) on the neighbouring trip's bottom (130 − 25 = 105)
OTHER_TRIP = dict(net_earnings=105, base_fare=100, turbo=5, passenger_total=130, grab_commission=25)
held = slip(job, "album_11+12_฿105.jpg", "A-HELD-000000000001", check_status="no_data", **OTHER_TRIP)
whole = slip(job, "album_13.jpg", "A-WHOLE-00000000002", check_status="fail", **OTHER_TRIP)


def queue_row(tid):
    return next(r for r in web.get("/api/review-queue").json()["rows"] if r["id"] == tid)


why = queue_row(held).get("halves_conflict") or ""
check("❗ คิวตรวจได้เหตุของแถวที่สองครึ่งไม่ตรงกัน เป็นตัวเลขของแถวเอง", "105" in why and "100" in why, why)
check("สลิปเต็มใบไม่มีเหตุนี้", not queue_row(whole).get("halves_conflict"))

r = web.patch(f"/api/trips/{held}", json={"turbo": 5}).json()
check("❗ แก้ช่องเงินของแถวที่สองครึ่งไม่ตรงกัน: แถวไม่กลับไปเป็น 'ผ่าน'", r["check_status"] != "pass", r["check_status"])
check("แถวที่แก้แล้วยังบอกเหตุ", bool(r.get("halves_conflict")), r.get("halves_conflict"))
bulk = web.post("/api/review-queue/approve-passing").json()
check("❗ ปุ่มอนุมัติทุกแถวที่ตัวเลขผ่าน ไม่เอาแถวนี้ไป", db.get_trip(held)["committed"] == 0, bulk)

r = web.patch(f"/api/trips/{held}", json={"passenger_total": 125}).json()
check("คนแก้ค่าโดยสารตามรูปจนสองครึ่งตรงกัน (125 − 25 = 100): ผ่าน", r["check_status"] == "pass", r["check_status"])
check("และไม่มีเหตุค้างอยู่", not r.get("halves_conflict"), r.get("halves_conflict"))

r = web.patch(f"/api/trips/{whole}", json={"turbo": 5}).json()
check("❗ สลิปเต็มใบตัวเลขชุดเดียวกัน แก้แล้วผ่านตามเดิม", r["check_status"] == "pass", r["check_status"])

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
