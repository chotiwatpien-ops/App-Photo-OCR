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
# Render installs requirements.txt only: no numpy, so nothing the web app runs may reach the OCR
# stack (2026-11-17: W46's report failed there on its exact copies; the tests had numpy)
sys.modules["numpy"] = None

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
check("ชื่อ Admin อ่านจากชื่ออัลบั้ม", (a["admin"], b["admin"]) == ("Kanchana", "Ploy"))
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
k = next(x for x in d["admins"] if x["admin"] == "Kanchana")
check("สรุปต่อ Admin รวมจากทุกอัลบั้มของคนนั้น", k["pictures"] == a["pictures"] and k["albums"] == 1)
whys = {(i["album"], i["why"]) for i in d["items"]}
check("รายการที่ใช้ไม่ได้มีครบทุกเหตุผล พร้อมลิงก์ของรูปซ้ำเป๊ะ",
      {(A, "ซ้ำ (เลขจองซ้ำ)"), (A, "อ่านไม่ได้"), (A, accounting.DELETED), (A, accounting.COPY),
       (A, accounting.WAITING_PAIR), (B, accounting.DELETED), (B, accounting.COPY)} <= whys
      and any(i["link"] == "https://drive.google.com/file/d/d1/view" for i in d["items"]))
check("งานที่ถูกลบใน W47 เองไม่มาอยู่ในรายงาน W46", not any(i["file"] == "lone_w47.jpg" for i in d["items"]))

wb = load_workbook(io.BytesIO(accounting.build_xlsx(d)))
check("Excel เปิดด้วยหน้าสรุป ตามด้วยชีตรายละเอียด",
      wb.sheetnames == ["สรุป", "สรุปต่อ Admin", "รายอัลบั้ม", "รายการที่ใช้ไม่ได้", "อ่านก่อน"], wb.sheetnames)
last = [c.value for c in list(wb["สรุปต่อ Admin"].iter_rows())[-1]]
check("แถวรวมท้ายชีตสรุปต่อ Admin", last[0] == "รวม" and last[2] == sum(x["pictures"] for x in d["admins"]), last)

# --- the first sheet: pictures → trips → read → final, with the reasons -------------------------
check("❗ เทียบงาน = Final 6 + ซ้ำ 2 (สำเนา 1 + เลขจอง 1) + อื่นๆ 2 (ลบเดิม 1 + อ่านไม่ได้ 1) + ค้าง 2",
      (a["jobs"], a["final"], a["dup"], a[accounting.DELETED], a["other"], a["pending"]) == (12, 6, 2, 1, 2, 2), a)
check("อ่านได้ = Final + รอคนตรวจ + เลขจองซ้ำ + ลบ (อ่านไม่ได้ไม่นับ)", a["read"] == 6 + 1 + 1 + 1, a)
check("❗ ค้างแยกเหตุผล: รอคนตรวจ 1 · รูปครึ่งรอคู่ 1 รูป",
      (a[accounting.REVIEW], a[accounting.READING], a[accounting.FILING], a[accounting.UNPAIRED]) == (1, 0, 0, 1), a)
check("ยอด Ops เทียบกับเทียบงาน", (a["ops"], a["ops_gap"], b["ops"], b["jobs"], b["ops_gap"]) == (10, -2, 5, 5, 0), (a, b))
check("❗ แถวรวมต้องบวกกลับได้", d["total"]["jobs"] == d["total"]["final"] + d["total"]["dup"]
      + d["total"]["other"] + d["total"]["pending"], d["total"])
check("หน้าสรุปไม่มีคอลัมน์ลบแล้ว", "ลบ" not in list(wb["สรุป"].iter_rows(values_only=True))[1])
check("งานของอัลบั้มสัปดาห์ก่อนที่ลงไฟล์สัปดาห์นี้ แยกบอก ไม่นับซ้ำ", d["from_earlier"] == {OLD: 1}, d["from_earlier"])
s = list(wb["สรุป"].iter_rows(values_only=True))
names = [r[0] for r in s]
check("❗ หน้าสรุปของสัปดาห์ที่ยังไม่ปิดขึ้นว่ายอดชั่วคราว", "ยอดชั่วคราว" in s[0][0], s[0][0])
check("แถว Admin มีอัลบั้มอยู่ใต้ และปิดท้ายด้วยแถวรวม", names.index("Kanchana") + 1 == names.index(A)
      and "รวมทุก Admin" in names, names)
check("แถวอัลบั้มพับเก็บได้", wb["สรุป"].row_dimensions[names.index(A) + 1].outlineLevel == 1)
check("หน้าสรุปบอกงานจากอัลบั้มสัปดาห์ก่อน", any(str(n).startswith("งานจากอัลบั้มของสัปดาห์ก่อน") for n in names), names)
check("ชื่อไฟล์บอกว่ายังเป็นยอดชั่วคราว", accounting.file_name(d) == "บัญชี 2026-W46 (ชั่วคราว).xlsx")

W48 = ("2026-11-23", "2026-11-29")
j48 = db.create_job("ฟ้า Win", "Trips", *W48, category="2 W Saver")
hold = db.create_job(db.HOLDING_RIDER, "Trips", *W48)
MAIN, PART, EMPTY = "2W Karnjana 1748 งาน", "2W Karnjana ทดสอบ", "2W ใหม่ 3 งาน"
trip(j48, f"{MAIN}_3000+3001_฿30.jpg", MAIN, service_type="Saver Bike")
trip(j48, f"{PART}_3002+3003_฿30.jpg", PART, service_type="Standard Bike")
trip(hold, f"{MAIN}_3004+3005_฿30.jpg", MAIN, committed=0)
trip(hold, f"{MAIN}_3006+3007_฿30.jpg", MAIN, status="pending", committed=0)
db.record_pool_run("move", "Week 23-29 Nov", {}, "", {"started_at": "2026-11-24 00:00:00", "albums": [
    {"week": "Week 23-29 Nov", "album": EMPTY, "leftovers": [{"file": "p_0.jpg"}, {"file": "q_0.jpg"}, {"file": "r_0.jpg"}]},
    {"week": "Week 23-29 Nov", "album": A, "leftovers": [{"file": "old_0.jpg"}]}]})
d48 = accounting.build(*W48)
by = {x["album"]: x for x in d48["albums"]}
check("❗ อัลบั้มทดสอบรวมเข้าชุด 1748 เป็นแถวเดียว", PART not in by and by[MAIN]["final"] == 2, sorted(by))
check("❗ แยกงานค้าง: รออ่าน 1 · รอลงไฟล์ 1",
      (by[MAIN][accounting.READING], by[MAIN][accounting.FILING], by[MAIN]["pending"]) == (1, 1, 2), by[MAIN])
check("❗ อัลบั้มที่ยังไม่มีงานเข้าระบบก็ขึ้นในรายงาน โดยนับรูปครึ่งที่รอคู่",
      EMPTY in by and (by[EMPTY]["half"], by[EMPTY]["pending"], by[EMPTY]["final"]) == (3, 2, 0), sorted(by))
check("อัลบั้มที่เริ่มสัปดาห์ก่อนไม่โผล่ซ้ำจากรูปที่ค้างในกอง", A not in by, sorted(by))

db.close_week(*W46)
closed = accounting.build(*W46)
top = list(load_workbook(io.BytesIO(accounting.build_xlsx(closed)))["สรุป"].iter_rows(values_only=True))[0][0]
check("❗ สัปดาห์ที่ปิดแล้วไม่ขึ้นยอดชั่วคราว", closed["closed"] and "ปิดสัปดาห์แล้ว" in top and "ชั่วคราว" not in top, top)
check("ชื่อไฟล์สัปดาห์ที่ปิดแล้ว", accounting.file_name(closed) == "บัญชี 2026-W46.xlsx")
check("สัปดาห์ที่ปิดแล้วเรียกรูปค้างว่าหาคู่ไม่ได้",
      any(i["why"] == accounting.UNPAIRED for i in closed["items"]))

for name, want in (("2W Parichart2  473 งาน", "Parichat"), ("2W Parichat 71งาน 23Nov", "Parichat"), ("4 W Ploy 357งาน 11Nov 2", "Ploy"),
                   ("2W Tae รวมงาน 295 16Nov", "Tae"), ("2W-Win Karnjana = 140", "Kanchana"), ("2W-Win Kachana=260", "Kanchana"),
                   ("2W-Home สแตน = 39", "สแตน"), ("4W Loli 105 งาน 16Nov", "Loli")):
    check(f"Admin ของ {name!r} = {want}", accounting.admin_of(name) == want, accounting.admin_of(name))

# --- a row a person deleted: a repeat of a counted trip, and whose album it was --------------------
W41, W42 = ("2026-10-05", "2026-10-11"), ("2026-10-12", "2026-10-18")
TAE, KAN = "2W Tae 9 งาน 5Oct", "2W Kanchana 8 งาน 12Oct"
j41 = db.create_job("ต้น Win", "Trips", *W41, category="2 W Saver")
j42 = db.create_job("ต้น Win", "Trips", *W42, category="2 W Saver")
trip(j41, "S__501_0.jpg", TAE, service_type="Saver Bike", booking_code="A-TESTAAA000001", base_fare=40)
trip(j42, "S__502_0.jpg", TAE, service_type="Saver Bike", booking_code="A-TESTAAA000002", base_fare=50)
for i in range(3):                                              # most of this job is another album
    trip(j42, f"{KAN}_{10 + 2 * i}+{11 + 2 * i}_฿30.jpg", KAN, service_type="Saver Bike",
         booking_code=f"A-TESTKKK00000{i + 1}", base_fare=30 + i)
for target, name, code, fare in (
        (910, "S__503_0.jpg", "A-TESTAAA000002", 50),            # Tae's: same code as its trip here
        (911, f"{KAN}_90+91_฿30.jpg", "A-TESTKKK000001", 30),    # same code
        (912, "S__504_0.jpg", "A-TESTKKK000092", 31),            # one letter off, same fare
        (913, "S__505_0.jpg", "A-TESTAAA000001", 40),            # that code is only in the week before
        (914, "S__506_0.jpg", "A-TESTKKK000093", 99)):           # one letter off, another fare
    db.log_action(action="trip.delete", target=f"trip:{target}", status=200,
                  detail={"row": {"job_id": j42, "file_name": name, "booking_code": code, "base_fare": fare}})
d41, d42 = accounting.build(*W41), accounting.build(*W42)
tae = next(x for x in d41["albums"] if x["album"] == TAE)
kan = next(x for x in d42["albums"] if x["album"] == KAN)
check("❗ แถวที่ไม่รู้อัลบั้ม ตามงานที่มันซ้ำ ไม่ใช่อัลบั้มส่วนใหญ่ของ job",
      (tae[accounting.DELETED_REPEAT], tae["dup"], tae["full"], tae["jobs"], tae["final"]) == (1, 1, 3, 3, 2), tae)
check("❗ คนกดลบงานที่ซ้ำ นับเป็นซ้ำ (เลขจองตรง และเพี้ยนแต่ค่ารอบตรง)",
      (kan[accounting.DELETED_REPEAT], kan["dup"]) == (2, 2), kan)
check("❗ ลบแล้วไม่ตรงกับงานในสัปดาห์เดียวกัน ยังเป็นลบ (ข้ามสัปดาห์ · ค่ารอบต่าง)", kan[accounting.DELETED] == 2, kan)
check("❗ เทียบงานบวกกลับได้ และไม่นับแถวของอัลบั้มอื่น",
      (kan["jobs"], kan["read"], kan["full"], kan["half"]) == (7, 7, 3, 8), kan)
check("อัลบั้มสัปดาห์ก่อนไม่โผล่ในรายงานนี้", all(x["album"] != TAE for x in d42["albums"]))
check("รายการบอกว่าซ้ำกับงานไหน", any(i["why"] == accounting.DELETED_REPEAT and i["file"] == "S__503_0.jpg"
                                       and i["note"] == "ซ้ำกับ S__502_0.jpg" for i in d41["items"]), d41["items"])

import main                                                     # noqa: E402
from fastapi.testclient import TestClient                       # noqa: E402
import config                                                   # noqa: E402

config.APP_PASSWORD = ""
main.DUP_TAB_FROM = "2026-01-01"
res = TestClient(main.app).get(f"/api/accounting.xlsx?week={W46[0]}")
check("ดาวน์โหลดจากหน้าเว็บได้ ไม่ต้องใช้ Drive", res.status_code == 200 and res.content[:2] == b"PK"
      and "%E0%B8%9A%E0%B8%B1%E0%B8%8D%E0%B8%8A%E0%B8%B5" in res.headers.get("content-disposition", ""),
      (res.status_code, res.headers.get("content-disposition")))

client = TestClient(main.app)
main._dup_cache.clear()
rep = client.get(f"/api/accounting/albums?week={W42[0]}").json()
kanchana = next(g for g in rep["admins"] if g["admin"] == "Kanchana")["albums"][0]
check("❗ รายงานหน้าเว็บ: อัลบั้มอยู่ใต้ Admin ส่งมา 7 = ได้งาน 3 + ซ้ำ 2 + ใช้ไม่ได้ 2",
      (kanchana["album"], kanchana["sent"], kanchana["final"], kanchana["dup"], kanchana["other"], kanchana["pending"])
      == (KAN, 7, 3, 2, 2, 0), kanchana)
check("❗ บอกจำนวนรูปในอัลบั้ม แยกรูปเต็มกับรูปครึ่ง",
      (kanchana["pictures"], kanchana["full"], kanchana["half"], kanchana["unknown"]) == (11, 3, 8, 0), kanchana)
check("❗ ทุกอัลบั้มบวกกลับเป็นยอดส่งมา และแถวรวมตรงกับผลรวม",
      all(x["sent"] == x["final"] + x["dup"] + x["other"] + x["pending"] for g in rep["admins"] for x in g["albums"])
      and rep["total"]["sent"] == sum(x["sent"] for g in rep["admins"] for x in g["albums"]), rep)
check("บอกว่าสัปดาห์ปิดแล้วหรือยัง", client.get(f"/api/accounting/albums?week={W46[0]}").json()["closed"] is True
      and rep["closed"] is False)
real_build, calls = accounting.build, []
accounting.build = lambda *w: calls.append(w) or real_build(*w)
client.get(f"/api/accounting/albums?week={W42[0]}")
check("❗ เปิดแท็บซ้ำไม่คำนวณใหม่", calls == [], calls)
main._dup_cache.clear()
client.get(f"/api/accounting/albums?week={W42[0]}")
check("ล้าง cache แล้วคำนวณใหม่", calls == [W42], calls)
accounting.build = real_build
check("สัปดาห์ที่ไม่มีอยู่ → 404", client.get("/api/accounting/albums?week=2020-01-06").status_code == 404)

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
