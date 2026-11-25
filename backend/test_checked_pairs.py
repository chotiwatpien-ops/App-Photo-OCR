# -*- coding: utf-8 -*-
"""ดูแล้ว ไม่ซ้ำ (Fiat 2026-11-25). Approved trips with the same route, distance and fare show on
the งานซ้ำ page for a person to look at. W48's pair was a regular commute: two riders, two days,
two codes printed on the slips. Once a person says so, the pair stops showing; both trips stay
counted; a group that gains another trip is a new question and shows again."""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-checked-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from fastapi.testclient import TestClient                       # noqa: E402
from sqlalchemy import insert                                   # noqa: E402

import db                                                       # noqa: E402
import duplicate_report as dr                                   # noqa: E402
import main                                                     # noqa: E402

db.init_db()
web = TestClient(main.app)
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


W = ("2026-11-23", "2026-11-29")
ROUTE = dict(base_fare=30, distance_km=3.6, service_type="Saver Bike", status="done", check_status="pass",
             pickup_text="คลังสินค้า ซอย 4 บางพูด", dropoff_text="สถานีรถไฟฟ้า ปากเกร็ด")
j1 = db.create_job("ก Home", "Trips", *W, category="2 W Saver")
j2 = db.create_job("ข Win", "Trips", *W, category="2 W Saver")


def trip(job, code, committed=1, **kw):
    with db.engine.begin() as c:
        return c.execute(insert(db.trips).values(
            job_id=job, file_name=f"{code}.jpg", booking_code=code, committed=committed,
            **{**ROUTE, "trip_date": "2026-11-26", **kw})).inserted_primary_key[0]


a = trip(j1, "A-TESTROUTEAAAAV", trip_date="2026-11-28")
b = trip(j2, "A-9ZZXXYYWWVVUAV")
waiting = trip(j2, "A-7PLMNBVCXZQWAV", committed=0)


def week():
    _, twice, suspect = dr.counted_twice(*W)
    return twice, suspect


twice, suspect = week()
check("เส้นทาง ระยะ ยอดตรงกัน ขึ้นให้คนดู ไม่นับเป็นซ้ำ", twice == [] and suspect == [[a, b]], (twice, suspect))

main._dup_cache.clear()
shown = web.get(f"/api/duplicates/week?week={W[0]}").json()["suspect"]
check("หน้างานซ้ำได้รายละเอียดทั้งสองเที่ยว ไว้เทียบรูป",
      [[r["trip_id"] for r in g] for g in shown] == [[a, b]]
      and {r["code"] for r in shown[0]} == {"A-TESTROUTEAAAAV", "A-9ZZXXYYWWVVUAV"}, shown)

r = web.post("/api/duplicates/checked", json={"ids": [a]})
check("ชุดเดียวกดไม่ได้ ต้องมีอย่างน้อย 2 เที่ยว", r.status_code == 400, r.status_code)
r = web.post("/api/duplicates/checked", json={"ids": [a, waiting]})
check("เที่ยวที่ยังไม่อนุมัติ กดไม่ได้", r.status_code == 409, r.status_code)
check("กดไม่สำเร็จ ไม่บันทึกอะไร", db.checked_groups() == set(), db.checked_groups())

r = web.post("/api/duplicates/checked", json={"ids": [b, a]})
check("❗ กด ดูแล้ว ไม่ซ้ำ สำเร็จ", r.status_code == 200 and r.json()["ids"] == [a, b], r.text)
twice, suspect = week()
check("❗ ชุดที่ดูแล้วไม่ขึ้นอีก", suspect == [], suspect)
check("❗ ทั้งสองเที่ยวยังอนุมัติและนับอยู่", dr.counted_twice(*W)[0] == 2)
check("หน้างานซ้ำไม่แสดงชุดนี้แล้ว (ไม่ต้องรอแคช)",
      web.get(f"/api/duplicates/week?week={W[0]}").json()["suspect"] == [])
r = web.post("/api/duplicates/checked", json={"ids": [a, b]})
check("กดซ้ำได้ ไม่พัง", r.status_code == 200, r.text)

c = trip(j1, "A-5RTYUIOPLKJHAV")
twice, suspect = week()
check("❗ มีเที่ยวใหม่เส้นทางเดียวกันเข้ามา ชุดขึ้นใหม่ให้ดูทั้งชุด", suspect == [[a, b, c]], suspect)

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
