# -*- coding: utf-8 -*-
"""The accounting report counts every picture an Admin placed in the week, half and full apart,
and every trip as usable (here, sent on to next week, still waiting) or not, with the reason."""
import io
import json
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-acct-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from openpyxl import load_workbook                              # noqa: E402
from sqlalchemy import insert                                   # noqa: E402

import accounting                                               # noqa: E402
import db                                                       # noqa: E402

db.init_db()
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


W46, W47 = ("2026-11-09", "2026-11-15"), ("2026-11-16", "2026-11-22")
A, B, OLD = "2W Karnjana 10 งาน", "4W Ploy 5งาน 11Nov", "2W Win เก่า"
ja = db.create_job("สมชาย Win", "Trips", *W46, category="2 W Saver")
jb = db.create_job("ดาว Taxi", "Trips", *W46, category="4 W Standard")
jn = db.create_job("สมชาย Win", "Trips", *W47, category="2 W Saver")
jold = db.create_job("เก่า Win", "Trips", "2026-11-02", "2026-11-08", category="2 W Saver")


def trip(job, name, album, **kw):
    with db.engine.begin() as c:
        return c.execute(insert(db.trips).values(job_id=job, file_name=name, source_album=album,
                                                 **{**dict(status="done", committed=1), **kw})).inserted_primary_key[0]


# A: 4 pairs filed here (2 Saver, 1 Standard Bike, 1 Standard Car), a parked repeat, an unreadable
# pair, one pair waiting for a person, two pairs the pool sent on to W47, one deleted in the queue
pair = lambda i: f"{A}_{2000 + 2 * i}+{2001 + 2 * i}_฿30.jpg"      # tags as the pool names them
for i, svc in enumerate(("Saver Bike", "Saver Bike", "Standard Bike", "Saver Car")):
    trip(ja, pair(i), A, service_type=svc)
trip(ja, pair(5), A, status="duplicate", committed=0, booking_code="A-X")
trip(ja, pair(6), A, status="error", committed=0)
trip(ja, pair(7), A, committed=0)
trip(jn, pair(8), A, service_type="Saver Bike")
trip(jn, pair(9), A, service_type="Saver Bike")
db.log_action(action="trip.delete", target="trip:900", status=200,
              detail={"row": {"job_id": ja, "file_name": pair(10)}})
db.log_action(action="trip.delete", target="trip:901", status=200,      # W47's own delete: not here
              detail={"row": {"job_id": jn, "file_name": "lone_w47.jpg"}})
# B: long screenshots, one deleted (its album only known from its job), and copies of a long one
for i in range(3):
    trip(jb, f"S__77{i}_0.jpg", B, service_type="Standard Car")
db.log_action(action="trip.delete", target="trip:902", status=200,
              detail={"row": {"job_id": jb, "file_name": "S__779_0.jpg"}})
db.record_skipped_copies([
    {"ref": "c1", "week_from": W46[0], "album": B, "file_name": "S__770_1.jpg", "drive_id": "d1",
     "same_as": f"{B}/S__770_0.jpg", "kind": "สำเนาในอัลบั้มเดียวกัน"},
    {"ref": "c2", "week_from": W46[0], "album": A, "file_name": "2000_1.jpg", "drive_id": "d2",
     "same_as": f"{A}/2000_0.jpg", "kind": "สำเนาในอัลบั้มเดียวกัน"},
    {"ref": "c3", "week_from": W46[0], "album": A, "file_name": "zz_1.jpg", "drive_id": "d3",
     "same_as": f"{A}/zz_0.jpg", "kind": "สำเนาในอัลบั้มเดียวกัน"}])
db.record_pool_run("move", "Week 9-15 Nov", {}, "", {"started_at": "2026-11-12 00:00:00", "albums": [
    {"week": "Week 9-15 Nov", "album": A, "leftovers": [{"file": "a_0.jpg"}, {"file": "b_0.jpg"}, {"file": "c_0.jpg"}]}]})
db.record_pool_run("move", "Week 9-15 Nov", {}, "", {"started_at": "2026-11-13 00:00:00", "albums": [
    {"week": "Week 9-15 Nov", "album": A, "leftovers": [{"file": "c_0.jpg"}]}]})
# an album that first came in the week before: that week's report holds it
trip(jold, f"{OLD}_1+2_฿30.jpg", OLD)
trip(ja, f"{OLD}_3+4_฿30.jpg", OLD, service_type="Saver Bike")

d = accounting.build(*W46)
a = next(x for x in d["albums"] if x["album"] == A)
b = next(x for x in d["albums"] if x["album"] == B)
check("❗ อัลบั้มที่วางครั้งแรกสัปดาห์ก่อน ไม่ถูกนับซ้ำในรายงานนี้", all(x["album"] != OLD for x in d["albums"]),
      [x["album"] for x in d["albums"]])
check("ชื่อ Admin อ่านจากชื่ออัลบั้ม", (a["admin"], b["admin"]) == ("Karnjana", "Ploy"))
check("❗ งานที่ใช้ได้ = ลงไฟล์นี้ 4 + ไปลง W47 2 + ยังรอ 1",
      (a["usable"], a["used_here"], a["used_later"], a["waiting"]) == (7, 4, 2, 1), a)
check("ลงไฟล์แยกตาม Service Type (Saver Car นับเป็น Standard Car)",
      (a["Saver Bike"], a["Standard Bike"], a["Standard Car"]) == (2, 1, 1), a)
check("❗ งานที่ใช้ไม่ได้แยกเหตุผล: ซ้ำ 1 · อ่านไม่ได้ 1 · ลบในคิวตรวจ 1",
      (a["unusable"], a["ซ้ำ (เลขจองซ้ำ)"], a["อ่านไม่ได้"], a[accounting.DELETED]) == (3, 1, 1, 1), a)
check("❗ รูปครึ่ง = 2 ต่อคู่ (10 คู่ รวมที่ถูกลบ) + สำเนาของรูปครึ่ง 1 + รูปที่หาคู่ไม่ได้ (รอบล่าสุด) 1",
      (a["half"], a["full"]) == (10 * 2 + 1 + 1, 0), a)
check("สำเนาที่หาต้นฉบับไม่เจอ นับเป็นรูปไม่ทราบชนิด", a["unknown"] == 1 and a[accounting.COPY] == 2, a)
check("❗ รูปที่ส่งมา = เต็ม + ครึ่ง + ไม่ทราบ", a["pictures"] == a["full"] + a["half"] + a["unknown"] == 23, a)
check("❗ รูปเต็ม: แคปยาว 3 + ที่ถูกลบ 1 (อัลบั้มรู้จาก job) + สำเนาของรูปยาว 1",
      (b["full"], b["half"], b[accounting.DELETED], b[accounting.COPY]) == (5, 0, 1, 1), b)
k = next(x for x in d["admins"] if x["admin"] == "Karnjana")
check("สรุปต่อ Admin รวมจากทุกอัลบั้มของคนนั้น", k["pictures"] == a["pictures"] and k["albums"] == 1)
whys = {(i["album"], i["why"]) for i in d["items"]}
check("รายการที่ใช้ไม่ได้มีครบทุกเหตุผล พร้อมลิงก์ของรูปซ้ำเป๊ะ",
      {(A, "ซ้ำ (เลขจองซ้ำ)"), (A, "อ่านไม่ได้"), (A, accounting.DELETED), (A, accounting.COPY),
       (A, accounting.UNPAIRED), (B, accounting.DELETED), (B, accounting.COPY)} <= whys
      and any(i["link"] == "https://drive.google.com/file/d/d1/view" for i in d["items"]))
check("งานที่ถูกลบใน W47 เองไม่มาอยู่ในรายงาน W46", not any(i["file"] == "lone_w47.jpg" for i in d["items"]))

wb = load_workbook(io.BytesIO(accounting.build_xlsx(d)))
check("Excel มีชีตสรุปต่อ Admin · รายอัลบั้ม · รายการที่ใช้ไม่ได้ · อ่านก่อน",
      wb.sheetnames == ["สรุปต่อ Admin", "รายอัลบั้ม", "รายการที่ใช้ไม่ได้", "อ่านก่อน"], wb.sheetnames)
last = [c.value for c in list(wb["สรุปต่อ Admin"].iter_rows())[-1]]
check("แถวรวมท้ายชีตสรุป", last[0] == "รวม" and last[2] == sum(x["pictures"] for x in d["admins"]), last)

for name, want in (("2W Parichart2  473 งาน", "Parichart"), ("4 W Ploy 357งาน 11Nov 2", "Ploy"),
                   ("2W Tae รวมงาน 295 16Nov", "Tae"), ("2W-Win Karnjana = 140", "Karnjana"),
                   ("2W-Home สแตน = 39", "สแตน"), ("4W Loli 105 งาน 16Nov", "Loli")):
    check(f"Admin ของ {name!r} = {want}", accounting.admin_of(name) == want, accounting.admin_of(name))

import main                                                     # noqa: E402
from fastapi.testclient import TestClient                       # noqa: E402
import config                                                   # noqa: E402

config.APP_PASSWORD = ""
main.DUP_TAB_FROM = "2026-01-01"
res = TestClient(main.app).get(f"/api/accounting.xlsx?week={W46[0]}")
check("ดาวน์โหลดจากหน้าเว็บได้ ไม่ต้องใช้ Drive", res.status_code == 200 and res.content[:2] == b"PK"
      and "%E0%B8%9A%E0%B8%B1%E0%B8%8D%E0%B8%8A%E0%B8%B5" in res.headers.get("content-disposition", ""),
      (res.status_code, res.headers.get("content-disposition")))

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
