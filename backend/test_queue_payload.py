# -*- coding: utf-8 -*-
"""What the review queue page is given: each row's week (filters, one-tap dates), the trip a held
repeat repeats (its picture goes beside it), and a count for the tab badge that does not build
the whole queue."""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-queue-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from sqlalchemy import insert                                   # noqa: E402

import config                                                   # noqa: E402
import db                                                       # noqa: E402
import main                                                     # noqa: E402
from fastapi.testclient import TestClient                       # noqa: E402

db.init_db()
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


W = ("2026-11-09", "2026-11-15")
a = db.create_job("ก Win", "Trips", *W)
b = db.create_job("ข Win", "Trips", *W)
with db.engine.begin() as c:
    def row(job, **kw):
        base = dict(job_id=job, file_name=f"{job}-{len(kw)}-{kw.get('booking_code')}.jpg", status="done",
                    committed=0, trip_date="2026-11-10", base_fare=50, net_earnings=50, check_status="pass")
        base.update(kw)
        return c.execute(insert(db.trips).values(**base)).inserted_primary_key[0]
    approved = row(a, committed=1, booking_code="A-LONGCODE-0000001")
    repeat = row(b, booking_code="A-LONGCODE-0000001")
    plain = row(b, booking_code="A-OTHER-00000000002", trip_date=None)

config.APP_PASSWORD = ""
web = TestClient(main.app)
rows = {r["id"]: r for r in web.get("/api/review-queue").json()["rows"]}
check("แต่ละแถวมีสัปดาห์ของมัน", rows[plain]["wk_from"] == W[0], rows[plain].get("wk_from"))
check("แถวที่ซ้ำกับเที่ยวที่อนุมัติแล้ว บอก id ของเที่ยวนั้น (เอารูปมาวางข้างกัน)",
      rows[repeat]["seen_trip"] == approved, rows[repeat].get("seen_trip"))
check("แถวที่ไม่ซ้ำไม่มีคู่", rows[plain]["seen_trip"] is None)
check("ป้ายนับคิวตรงกับจำนวนแถว ไม่ต้องโหลดทั้งคิว",
      web.get("/api/review-queue/count").json()["count"] == len(rows) == 2)
r = web.patch(f"/api/trips/{plain}", json={"trip_date": "2026-11-11"})
check("แก้วันที่จากคิวได้", r.status_code == 200 and r.json()["trip_date"] == "2026-11-11", r.text[:200])

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
