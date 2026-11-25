# -*- coding: utf-8 -*-
"""The week audit sorts a delivered week's faults onto their own lists, and changes nothing."""
import io
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-audit-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from openpyxl import load_workbook                              # noqa: E402
from sqlalchemy import insert, select                           # noqa: E402

import db                                                       # noqa: E402
import week_audit as wa                                         # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


W = ("2026-08-17", "2026-08-23")
a = db.create_job("พงศ์กฤษณ์", "Trips", *W, category="2 W Standard")
b = db.create_job("วิมลวรรณ", "Trips", *W, category="2 W Standard")
s = db.create_job("ณัฐพล", "Trips", *W, category="2 W Saver")
c = db.create_job("ณัฐพล", "Trips", *W, category="4 W Standard")
base = dict(status="done", committed=1, file_name="x.jpg", trip_date="2026-08-17", trip_time="12:00-17:59",
            service_type="Standard Bike", distance_km=15.7, pickup_text="A", dropoff_text="B",
            passenger_paid=140.0, passenger_total=130.0, app_fee=-1.0, discount=None, other_adj=-5.0)
with db.engine.begin() as x:
    ins = lambda **kw: x.execute(insert(db.trips).values(**{**base, **kw})).inserted_primary_key[0]
    ins(job_id=a, base_fare=118.0, net_earnings=118.0, booking_code="A-1", customer_image="WK34-พงศ์กฤษณ์1.jpg")
    ins(job_id=b, base_fare=118.0, net_earnings=118.0, booking_code="a-1 ", customer_image="WK34-วิมลวรรณ1.jpg")
    ins(job_id=a, base_fare=39.0, net_earnings=39.0, distance_km=5.29, booking_code=None, customer_image="WK34-พงศ์กฤษณ์2.jpg")
    ins(job_id=b, base_fare=39.0, net_earnings=39.0, distance_km=5.29, booking_code="A-2", customer_image="WK34-วิมลวรรณ2.jpg")
    ins(job_id=a, base_fare=26.0, net_earnings=26.0, distance_km=1.3, booking_code="A-3", customer_image="WK34-พงศ์กฤษณ์3.jpg")
    ins(job_id=b, base_fare=26.0, net_earnings=26.0, distance_km=1.3, booking_code="A-4", customer_image="WK34-วิมลวรรณ3.jpg")
    zero = ins(job_id=b, base_fare=0.0, net_earnings=5.0, turbo=5.0, distance_km=0, booking_code="A-5",
               customer_image="WK34-วิมลวรรณ4.jpg", passenger_paid=None)
    ins(job_id=s, base_fare=30.0, net_earnings=30.0, service_type="Saver Bike", distance_km=2.0, booking_code="A-6",
        customer_image="WK34-ณัฐพล1.jpg")
    ins(job_id=c, base_fare=90.0, net_earnings=99.0, service_type="Standard Car", distance_km=9.0, booking_code="A-7",
        customer_image="WK34-ณัฐพล1.jpg")
    ins(job_id=c, base_fare=50.0, net_earnings=50.0, service_type="Saver Bike", distance_km=4.0, booking_code="A-8",
        customer_image=None)

rows = wa.week_rows(*W)
out = wa.audit(rows, pictures={"2 W Standard": {"WK34-พงศ์กฤษณ์1.jpg", "WK34-เกิน.jpg"}})
check("❗ รหัสการจองเดียวกัน (ต่างตัวพิมพ์/ช่องว่าง) คือซ้ำ", len(out["งานซ้ำ-รหัสการจอง"]) == 1
      and len(out["งานซ้ำ-รหัสการจอง"][0]) == 2)
check("เหมือนทุกช่องแต่แถวหนึ่งไม่มีรหัส → ให้คนดู", len(out["เหมือนทุกช่อง-ไม่มีรหัสยืนยัน"]) == 1)
check("เหมือนทุกช่องแต่รหัสต่างกัน → งานจริงสองงาน แยกไว้", len(out["เหมือนทุกช่อง-แต่รหัสต่างกัน"]) == 1)
check("ค่ารอบ 0", [r["id"] for r in out["ค่ารอบเป็น0"]] == [zero])
check("คุณได้รับไม่ตรงค่ารอบ+โบนัส", len(out["คุณได้รับไม่ตรงค่ารอบ+โบนัส"]) == 1)
check("บล็อกผู้โดยสารไม่ลงตัว (130 ≠ 140 − 1 − 5)", len(out["บล็อกผู้โดยสารไม่ลงตัว"]) >= 1)
check("กลุ่มไม่ตรง Service Type", len(out["กลุ่มไม่ตรงServiceType"]) == 1)
check("ชื่อรูปเดียวกันคนละกลุ่ม แยกจากชื่อซ้ำในกลุ่มเดียวกัน",
      len(out["ชื่อรูปซ้ำข้ามกลุ่ม"]) == 2 and not out["ชื่อรูปซ้ำในกลุ่มเดียวกัน"])
check("ไม่มีรูปส่งลูกค้า", len(out["ไม่มีรูปส่งลูกค้า"]) == 1)
check("รูปหายจาก Drive และรูปที่ไม่มีแถว", out["รูปใน Drive ที่ไม่มีแถว"] == [("2 W Standard", "WK34-เกิน.jpg")]
      and len(out["รูปหายจาก Drive"]) == 8)
wb = load_workbook(io.BytesIO(wa.build_xlsx(rows, out, W[0])))
check("Excel มีชีตสรุปและชีตรายการ", wb.sheetnames[0] == "สรุป" and "งานซ้ำ-รหัสการจอง" in wb.sheetnames)
with db.engine.begin() as x:
    before = x.execute(select(db.trips)).mappings().all()
wa.main(["--from", W[0], "--to", W[1]])
with db.engine.begin() as x:
    after = x.execute(select(db.trips)).mappings().all()
check("อ่านอย่างเดียว ไม่แก้แถวใด", [dict(r) for r in before] == [dict(r) for r in after])

# --- an album the pool split between two weeks (W46/W47 Tae, 2026-11-16) ---------------------
N = ("2026-08-24", "2026-08-30")
n = db.create_job("ดาว Win", "Trips", *N, category="2 W Saver")
X = "2W Tae รวมงาน 9 16Nov"
with db.engine.begin() as x:
    ins = lambda **kw: x.execute(insert(db.trips).values(**{**base, **kw})).inserted_primary_key[0]
    here = ins(job_id=s, base_fare=44.0, net_earnings=44.0, booking_code="A-ALBUMSAME0001", source_album=X,
               service_type="Saver Bike", distance_km=3.0, customer_image="WK34-ณัฐพล2.jpg")
    there = ins(job_id=n, base_fare=44.0, net_earnings=44.0, booking_code="A-ALBUMSAME0001", source_album=X,
                service_type="Saver Bike", distance_km=3.0, trip_date="2026-08-24")
    ins(job_id=n, base_fare=55.0, net_earnings=55.0, booking_code="A-OTHERALBUM001", source_album="2W Win อื่น",
        service_type="Saver Bike", distance_km=3.0, trip_date="2026-08-24")
    ins(job_id=s, base_fare=55.0, net_earnings=55.0, booking_code="A-OTHERALBUM001", source_album=X,
        service_type="Saver Bike", distance_km=3.0, customer_image="WK34-ณัฐพล3.jpg")
    ins(job_id=n, base_fare=66.0, net_earnings=66.0, booking_code="A-PARKEDCOPY001", source_album=X,
        service_type="Saver Bike", distance_km=3.0, trip_date="2026-08-24", status="duplicate", committed=0)
    ins(job_id=s, base_fare=66.0, net_earnings=66.0, booking_code="A-PARKEDCOPY001", source_album=X,
        service_type="Saver Bike", distance_km=3.0, customer_image="WK34-ณัฐพล4.jpg")
split = wa.audit(wa.week_rows(*W))["งานซ้ำ-อัลบั้มเดียวกันข้ามสัปดาห์"]
check("❗ อัลบั้มเดียวกัน เลขจองเดียวกัน คนละสัปดาห์ นับทั้งสองสัปดาห์ → เจอ",
      [[r["id"] for r in g] for g in split] == [[here, there]])
check("เลขจองเดียวกันแต่คนละอัลบั้ม = งานของอีกสัปดาห์ตามกติกาลูกค้า ไม่นับเป็นซ้ำ · แถวที่พักไว้แล้วไม่นับ",
      len(split) == 1)
check("❗ อีกสัปดาห์ก็เห็นคู่เดียวกัน",
      [[r["id"] for r in g] for g in wa.audit(wa.week_rows(*N))["งานซ้ำ-อัลบั้มเดียวกันข้ามสัปดาห์"]] == [[there, here]])
import close_week                                               # noqa: E402
# Album names were reused across weeks (69 of 187 by 2026-11-17) and Porpla=309 held 7 such pairs
# in W37/W38: a re-sent album is work by the customer's rule, so a person decides; no block.
check("หมวดนี้ให้คนตัดสิน ไม่ขวางการปิดสัปดาห์", "งานซ้ำ-อัลบั้มเดียวกันข้ามสัปดาห์" not in close_week.BLOCKING)

# --- a delivered row whose two halves disagree on money (W47, 2026-11-23) --------------------
# Nine rows went out with one trip's top on the neighbour's bottom; the net-vs-base sheet above
# saw seven of them, because a top half balances by itself.
M = ("2026-11-16", "2026-11-22")
m = db.create_job("สมศรี", "Trips", *M, category="2 W Saver")
HALVES = "สองครึ่งเงินไม่ตรงกัน"
with db.engine.begin() as x:
    ins = lambda **kw: x.execute(insert(db.trips).values(**{                        # noqa: E731
        **base, "job_id": m, "service_type": "Saver Bike", "trip_date": "2026-11-17", "passenger_paid": None,
        "app_fee": None, "other_adj": None, **kw})).inserted_primary_key[0]
    odd = ins(file_name="2W-Win สมศรี = 12_31+32_฿105.jpg", net_earnings=105.0, base_fare=100.0, turbo=5.0,
              passenger_total=130.0, grab_commission=25.0, booking_code="A-BBBBBBBBBBBBBB", distance_km=1.1)
    ins(file_name="2W-Win สมศรี = 12_33+34_฿46.jpg", net_earnings=46.0, base_fare=46.0,
        passenger_total=182.0, grab_commission=137.0, booking_code="A-CCCCCCCCCCCCCC", distance_km=2.2)
    ins(file_name="S__40010001_0.jpg", net_earnings=105.0, base_fare=100.0, turbo=5.0,
        passenger_total=130.0, grab_commission=25.0, booking_code="A-DDDDDDDDDDDDDD", distance_km=3.3)
    merged = ins(file_name="S__40010002_0.jpg", note="รวม 2 รูป: S__40010002_0.jpg + S__40010003_0.jpg",
                 net_earnings=60.0, base_fare=60.0, passenger_total=90.0, grab_commission=20.0,
                 booking_code="A-EEEEEEEEEEEEEE", distance_km=4.4)
rows_m = wa.week_rows(*M)
out_m = wa.audit(rows_m)
check("❗ แถวที่อนุมัติแล้วซึ่งครึ่งล่างบอกรายได้จากรอบขับไม่เท่าค่ารอบ ขึ้นชีตของมันเอง ทั้งรูปที่กองต่อให้และแถวที่รวม 2 รูป",
      [r["id"] for r in out_m.get(HALVES, [])] == [odd, merged])
check("ชีตเดิม 'คุณได้รับไม่ตรงค่ารอบ+โบนัส' มองไม่เห็นแถวพวกนี้ เพราะครึ่งบนลงตัวในตัวเอง",
      out_m["คุณได้รับไม่ตรงค่ารอบ+โบนัส"] == [])
sheet = load_workbook(io.BytesIO(wa.build_xlsx(rows_m, out_m, M[0])))[HALVES] if HALVES in out_m else None
check("ชีตบอกเหตุด้วยตัวเลขของแถวนั้น", sheet is not None and "105" in str(sheet.cell(2, sheet.max_column).value)
      and "100" in str(sheet.cell(2, sheet.max_column).value))
check("ให้คนเปิดรูปดู ไม่ขวางการปิดสัปดาห์", HALVES not in close_week.BLOCKING)

# Pictures moved aside on purpose (_แทนที่แล้ว, _ซ้ำ, _ไม่อยู่ในไฟล์) are no stray in the customer folder
from drive_client import LocalDrive                             # noqa: E402
from ingest import week_label                                   # noqa: E402
exports = os.path.join(WORK, "exports")
wk_dir = os.path.join(exports, week_label(M[0]))
for folder, name in (("2 W Saver", "kept.jpg"), ("_แทนที่แล้ว", "old.jpg"), ("2 W Saver/_ไม่อยู่ในไฟล์", "out.jpg")):
    os.makedirs(os.path.join(wk_dir, folder), exist_ok=True)
    open(os.path.join(wk_dir, folder, name), "wb").write(b"x")
pics = wa.pictures_on_drive(LocalDrive(exports), exports, M[0])
print("   ได้:", pics)
check("❗ รูปในโฟลเดอร์ที่ขึ้นต้นด้วย _ ไม่ถูกนับเป็นรูปของกลุ่มงาน", pics == {"2 W Saver": {"kept.jpg"}})

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
