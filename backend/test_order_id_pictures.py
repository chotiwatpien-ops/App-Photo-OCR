# -*- coding: utf-8 -*-
"""From W46 the customer picture is named by its Order ID (Fiat 2026-11-10), the file carries
Driver ID and Order ID after the name, and a picture made under its old name is moved out of the
customer's folder when it is renamed. Earlier weeks keep the names they were delivered with."""
import io
import os
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-orderpic-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import openpyxl                                                 # noqa: E402
from PIL import Image                                           # noqa: E402
from sqlalchemy import insert                                   # noqa: E402

import config                                                   # noqa: E402
import db                                                       # noqa: E402
import excel_writer as xw                                       # noqa: E402
import ingest                                                   # noqa: E402
from drive_client import LocalDrive                             # noqa: E402

db.init_db()
config.ORDER_ID_FROM = "2026-11-09"
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


def jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (40, 80), "white").save(buf, "JPEG")
    return buf.getvalue()


db.name_pool_load([("สถาพร", "2W", "Win", "0056"), ("มานี", "2W", "Home", None)])
W46, W45 = ("2026-11-09", "2026-11-15"), ("2026-11-02", "2026-11-08")
job = db.create_job("สถาพร Win", "Trips", *W46, category="2 W Standard")
noid = db.create_job("มานี Home", "Trips", *W46, category="2 W Standard")
old = db.create_job("สถาพร Win", "Trips", *W45, category="2 W Standard")


def trip(j, day, at, name=None):
    with db.engine.begin() as c:
        return c.execute(insert(db.trips).values(
            job_id=j, file_name=f"{j}-{day}-{at}.jpg", status="done", committed=1, trip_date=day,
            trip_time=at, image_blob=jpeg(), customer_image=name, service_type="Standard Bike",
            base_fare=50, net_earnings=50)).inserted_primary_key[0]


a = trip(job, "2026-11-09", "18:10", name="WK46-สถาพร Win1.jpg")     # made before the switch
b = trip(job, "2026-11-09", "09:05")
c = trip(job, "2026-11-10", "20:00")
m = trip(noid, "2026-11-09", "10:00")
o = trip(old, "2026-11-03", "10:00")

root = Path(WORK) / "drive"
folder = str(root / "Exports" / "2026-W46" / "2 W Standard")
Path(folder).mkdir(parents=True)
(Path(folder) / "WK46-สถาพร Win1.jpg").write_bytes(jpeg())
drive = LocalDrive(root)

n = ingest.make_customer_images(drive, folder, job, "สถาพร Win", only_missing=True)
names = {r["id"]: r["customer_image"] for r in db.trips_with_images(job)}
check("ทุกเที่ยวของ W46 ได้ชื่อรูปเป็น Order ID", n == 3 and names[b] == "005609112601.jpg"
      and names[a] == "005609112602.jpg" and names[c] == "005610112601.jpg", names)
here = sorted(p.name for p in Path(folder).iterdir() if p.is_file())
check("โฟลเดอร์ลูกค้ามีแต่รูปชื่อ Order ID", here == ["005609112601.jpg", "005609112602.jpg", "005610112601.jpg"], here)
check("รูปชื่อเดิมถูกย้ายไป _ชื่อเดิม ไม่ได้ลบ",
      (Path(folder) / ingest.RENAMED_DIR / "WK46-สถาพร Win1.jpg").exists())

d = trip(job, "2026-11-09", "07:00")
ingest.make_customer_images(drive, folder, job, "สถาพร Win", only_missing=True)
again = {r["id"]: r["customer_image"] for r in db.trips_with_images(job)}
check("เที่ยวที่มาทีหลังได้เลขถัดไป ชื่อเดิมไม่เปลี่ยน",
      again[d] == "005609112603.jpg" and all(again[k] == names[k] for k in names), again)

ingest.make_customer_images(drive, folder, noid, "มานี Home", only_missing=True)
check("ไรเดอร์ที่ไม่มี Driver ID ใช้ชื่อแบบเดิม",
      db.trips_with_images(noid)[0]["customer_image"] == "WK46-มานี Home1.jpg")
odir = str(root / "Exports" / "2026-W45" / "2 W Standard")
ingest.make_customer_images(drive, odir, old, "สถาพร Win", only_missing=True)
check("สัปดาห์ก่อน W46 ใช้ชื่อแบบเดิม", db.trips_with_images(old)[0]["customer_image"] == "WK45-สถาพร Win1.jpg")

rows = db.query_trips(committed_only=True)
book = openpyxl.load_workbook(io.BytesIO(xw.build_fare_lines_workbook(rows, every_week=True)))
ws = book[book.sheetnames[0]]
head = [x.value for x in ws[1]]
got = {r[head.index("Image")]: (r[head.index("Driver ID")], r[head.index("Order ID")])
       for r in ws.iter_rows(min_row=2, values_only=True)}
check("ไฟล์: Driver ID และ Order ID ต่อจากชื่อไรเดอร์", head[:3] == ["Driver Name", "Driver ID", "Order ID"], head[:4])
check("ไฟล์: Order ID ตรงกับชื่อรูปของแถวเดียวกัน", got.get("005609112601.jpg") == ("0056", "005609112601"), got)
check("ไฟล์: ไรเดอร์ไม่มีรหัส เว้นว่างทั้งสองช่อง", got.get("WK46-มานี Home1.jpg") == (None, None))
check("ไฟล์: แถวก่อน W46 เว้นว่าง (ไม่ย้อนไปแก้สัปดาห์ที่ส่งแล้ว)", got.get("WK45-สถาพร Win1.jpg") == (None, None))

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
