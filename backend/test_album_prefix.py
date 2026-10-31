# -*- coding: utf-8 -*-
"""revert --delete-rows finds an album's rows by the start of the picture name. In SQL LIKE an
underscore matches any one character, so album 'a_b' also found rows of album 'axb' and the revert
would have deleted another album's work."""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-album-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import db                                                       # noqa: E402

db.init_db()
job = db.create_job("ทดสอบ", "Trips", "2026-08-24", "2026-08-30")
mine = db.create_trip(job, "Lot_16_0+1.jpg", None, "image/jpeg")
other = db.create_trip(job, "LotX16_0+1.jpg", None, "image/jpeg")
percent = db.create_trip(job, "Lot%16_0+1.jpg", None, "image/jpeg")

got = {r["id"] for r in db.trips_from_album("Lot_16_")}
ok = got == {mine}
print(("✅" if ok else "✗"), "อัลบั้ม Lot_16 เจอแค่แถวของตัวเอง", sorted(got), "ควรเป็น", [mine])
got = {r["id"] for r in db.trips_from_album("Lot%16_")}
ok2 = got == {percent}
print(("✅" if ok2 else "✗"), "เครื่องหมาย % ในชื่ออัลบั้มไม่กลายเป็นตัวแทนทุกตัวอักษร", sorted(got))
sys.exit(0 if ok and ok2 else 1)
