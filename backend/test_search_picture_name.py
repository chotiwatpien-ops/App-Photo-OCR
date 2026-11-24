# -*- coding: utf-8 -*-
"""The data tab's search box finds a trip by the name of the picture the customer was sent.

The customer and Ops refer to a trip by that name (it is the Order ID), and the search looked at
the booking code, the source file and the two addresses only."""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-search-")
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


job = db.create_job("ก Win", "Trips", "2026-11-16", "2026-11-22")
with db.engine.begin() as c:
    def row(n, picture):
        return c.execute(insert(db.trips).values(
            job_id=job, file_name=f"album_{n}+{n + 1}_฿50.jpg", status="done", committed=1,
            trip_date="2026-11-17", base_fare=50, net_earnings=50, check_status="pass",
            booking_code=f"A-CODE-{n:011d}", customer_image=picture)).inserted_primary_key[0]
    wanted = row(1, "000111112601.jpg")
    row(3, "000211112602.jpg")

config.APP_PASSWORD = ""
web = TestClient(main.app)


def found(q):
    return [r["id"] for r in web.get("/api/trips", params={"q": q}).json()["rows"]]


check("ค้นด้วยชื่อรูปส่งลูกค้าเต็มชื่อ เจอแถวนั้นแถวเดียว", found("000111112601.jpg") == [wanted], found("000111112601.jpg"))
check("ค้นด้วย Order ID ไม่มี .jpg ก็เจอ", found("000111112601") == [wanted], found("000111112601"))
check("ค้นด้วยเลขจองยังเจอเหมือนเดิม", found("A-CODE-00000000001") == [wanted], found("A-CODE-00000000001"))
check("คำที่ไม่มีในแถวไหนเลย ไม่เจออะไร", found("999999999999") == [])

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
