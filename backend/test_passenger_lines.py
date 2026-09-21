# -*- coding: utf-8 -*-
"""Every line of the passenger's fare block gets its own field, and a week already read can be
filled in without moving a single fare.

Ops asked on 2026-09-21 for the whole block in Sheet1. Before this, ส่วนลด and the travel
insurance fee shared other_adjustments — a slip printing both kept one — and the passenger's
ค่าทางด่วน was never read, so 1 row in 8 of W38 could not add up to its own fare. The numbers
below are real W38 slips, opened and read by eye on 2026-09-21.
"""
import os
import sys
import tempfile
import types as pytypes

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-lines-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import config                                                     # noqa: E402
import db                                                         # noqa: E402
import extractor                                                  # noqa: E402
import pipeline                                                   # noqa: E402
import reread_passenger as rp                                     # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


# --- the switch ---------------------------------------------------------------------------
config.PASSENGER_LINES = False
off = extractor._schema_without(())
check("ปิดสวิตช์: schema เหมือนเดิมทุกอย่าง", off is extractor.SCHEMA)
check("ปิดสวิตช์: prompt เหมือนเดิมทุกตัวอักษร", extractor.prompt() == extractor.PROMPT)
check("ปิดสวิตช์: ไม่มีช่องใหม่", "discount" not in off.properties)

on = extractor._schema_without((), lines=True)
check("เปิดสวิตช์: มีช่อง discount · insurance_fee · passenger_tolls",
      all(k in on.properties for k in extractor.PASSENGER_LINE_FIELDS))
check("เปิดสวิตช์: other_adjustments เหลือแค่บรรทัดที่ไม่มีช่องของตัวเอง",
      "OTHER line" in on.properties["other_adjustments"].description)
check("เปิดสวิตช์: prompt บอกให้แยกทุกบรรทัดและเช็กยอดก่อนตอบ",
      "ประกันภัย" in extractor.prompt(lines=True) and "Check before answering" in extractor.prompt(lines=True))
check("เปิดสวิตช์แล้วยังตัดช่องที่ตั้งให้ตัดได้", "surge" not in extractor._schema_without(("surge",), lines=True).properties)
check("ช่องเดิมไม่หาย", all(k in on.properties for k in off.properties))
config.PASSENGER_LINES = True
check("ค่าตั้งใน config เปิดได้โดยไม่ต้องส่ง lines", "discount" in extractor._schema_without(()).properties)
config.PASSENGER_LINES = False

# --- the arithmetic, on real slips ------------------------------------------------------
ops = {"passenger_paid": 29, "app_fee": -1, "intl_fee": 1, "passenger_total": 27}
check("สลิปของ Ops: 29 − 1 − 1 = 27", rp.gap(ops) == 0)
promo = {"passenger_paid": 90, "app_fee": -20, "other_adj": 50, "passenger_total": 120}
check("#31153 โปรโมชัน: 90 − 20 + 50 = 120", rp.gap(promo) == 0)
tipped = {"passenger_paid": 206, "app_fee": -20, "other_adj": 10, "tip": 40, "passenger_total": 156}
check("#31962 มีทิป: ทิปถูกหักออกก่อนถึงค่ารอบ", rp.gap(tipped) == 0)
both = {"passenger_paid": 39, "app_fee": -1, "other_adj": 3, "passenger_total": 31}
check("#32256 ส่วนลด+ประกัน เก็บได้ตัวเดียว: ขาด 10", rp.gap(both) == -10)
tolls = {"passenger_paid": 458, "app_fee": -20, "intl_fee": 13, "passenger_total": 285}
check("#31974 ทางด่วน DMK ไม่เคยอ่าน: ขาด 140", rp.gap(tolls) == -140)
check("จอเก่าไม่มียอดชำระ: ไม่นับ (ไม่ใช่ศูนย์)", rp.gap({"passenger_total": 50}) is None)

# --- split: no reading, sign decides ------------------------------------------------------
check("ส่วนลดที่ลงตัวแล้ว → discount", rp.split(promo) == {"discount": 50, "other_adj": None})
insured = {"passenger_paid": 91, "app_fee": -1, "other_adj": -10, "passenger_total": 80}
check("#31663 ค่าประกัน → insurance_fee", rp.split(insured) == {"insurance_fee": -10, "other_adj": None})
check("❗ แถวที่ยังไม่ลงตัว ห้ามเดาจากเครื่องหมาย", rp.split(both) is None)
check("แถวที่แยกไว้แล้ว ไม่แยกซ้ำ", rp.split(dict(promo, discount=50)) is None)
check("แถวที่ไม่มีช่องรวม ไม่มีอะไรให้แยก", rp.split(ops) is None)

# --- decide: a fresh reading fills the lines, never moves the fare ------------------------
fields, why = rp.decide(both, {"passenger_paid": 39, "passenger_total": 31, "app_fee": -1,
                               "discount": 3, "insurance_fee": -10})
check("#32256 อ่านใหม่เห็นทั้งสองบรรทัด → เก็บ", fields is not None and why == "ลงตัว")
check("#32256 ช่องรวมเก่าถูกล้าง ไม่ให้นับซ้ำ", fields and fields["other_adj"] is None)
fields, _ = rp.decide(tolls, {"passenger_paid": 458, "passenger_total": 285, "app_fee": -20,
                              "intl_fee": 13, "passenger_tolls": -140})
check("#31974 อ่านใหม่เห็นทางด่วน −140 → เก็บ", fields and fields["passenger_tolls"] == -140)
check("ค่าธุรกรรมต่างประเทศเก็บเป็นบวกเหมือนเดิม (ฐานข้อมูล)", fields and fields["intl_fee"] == 13)
fields, why = rp.decide(tolls, {"passenger_paid": 458, "passenger_total": 258, "app_fee": -20,
                                "intl_fee": 13, "passenger_tolls": -167})
check("❗ อ่านใหม่ได้ค่ารอบต่างจากเดิม → ไม่เก็บ แม้บรรทัดจะลงตัว", fields is None and "passenger_total" in why)
fields, why = rp.decide(tolls, {"passenger_paid": 485, "passenger_total": 285, "app_fee": -20,
                                "intl_fee": 13, "passenger_tolls": -167})
check("❗ อ่านใหม่ได้ยอดชำระต่างจากเดิม → ไม่เก็บ", fields is None and "passenger_paid" in why)
fields, why = rp.decide(both, {"passenger_paid": 39, "passenger_total": 31, "app_fee": -1, "discount": 3})
check("อ่านใหม่แล้วยังไม่ลงตัว → ไม่เก็บ บอกว่าขาดเท่าไหร่", fields is None and "-10" in why)
fields, why = rp.decide(both, {"passenger_total": 31})
check("อ่านใหม่ไม่เห็นยอดชำระ → ไม่เก็บ", fields is None and "passenger_paid" in why)

# --- the pipeline stores what the reader saw ----------------------------------------------
db.init_db()
with db.engine.begin() as c:
    jid = c.execute(db.jobs.insert().values(
        driver_name="ทดสอบ", date_from="2026-09-14", date_to="2026-09-20", status="review",
        created_at="2026-09-21 00:00:00")).inserted_primary_key[0]
    tid = c.execute(db.trips.insert().values(
        job_id=jid, file_name="a.jpg", status="pending", trip_date="2026-09-15")).inserted_primary_key[0]
pipeline.apply_extraction(tid, jid, {
    "kind": "full", "net_earnings": 27, "base_fare": 27, "distance_km": 1.67,
    "service_type": "Standard Bike", "passenger_paid": 39, "passenger_total": 31, "app_fee": -1,
    "discount": 3, "insurance_fee": -10, "passenger_tolls": None, "other_adjustments": None})
row = next(t for t in db.get_job(jid)["trips"] if t["id"] == tid)
check("pipeline เก็บ discount / insurance_fee ลงแถว", row["discount"] == 3 and row["insurance_fee"] == -10)
check("ครึ่งล่างส่งบรรทัดใหม่ต่อให้ครึ่งบนตอนจับคู่",
      all(k in pipeline.BOTTOM_FIELDS for k in extractor.PASSENGER_LINE_FIELDS))
check("แก้มือในหน้าตรวจได้", all(k in db.TRIP_EDITABLE for k in extractor.PASSENGER_LINE_FIELDS))

# --- a whole week, end to end, with the reader stubbed --------------------------------------
with db.engine.begin() as c:
    c.execute(db.trips.delete())

    def put(**kw):
        v = dict(job_id=jid, status="done", committed=1, trip_date="2026-09-15",
                 source_url="https://drive.google.com/file/d/x/view")
        v.update(kw)
        return c.execute(db.trips.insert().values(**v)).inserted_primary_key[0]

    ids = {
        "promo": put(file_name="promo.jpg", **promo),
        "insured": put(file_name="ins.jpg", **insured),
        "both": put(file_name="both.jpg", **both),
        "tolls": put(file_name="tolls.jpg", **tolls),
        "stubborn": put(file_name="bad.jpg", passenger_paid=50, app_fee=-1, passenger_total=40),
        "old": put(file_name="old.jpg", passenger_total=60),
    }
    put(file_name="tolls_bottom.jpg", status="merged", merged_into=ids["tolls"],
              source_url="https://drive.google.com/file/d/BOTTOM/view")

readings = {
    ids["both"]: {"passenger_paid": 39, "passenger_total": 31, "app_fee": -1, "discount": 3, "insurance_fee": -10},
    ids["tolls"]: {"passenger_paid": 458, "passenger_total": 285, "app_fee": -20, "intl_fee": 13, "passenger_tolls": -140},
    ids["stubborn"]: {"passenger_paid": 50, "passenger_total": 40, "app_fee": -1},
}
seen = []


def fake_read(t, drive, model):
    seen.append((t["id"], t["_picture"]))
    d = dict(readings[t["id"]])
    d["_usage"] = {"tok_in": 100, "tok_out": 10, "tok_think": 0}
    return t, d, None


rp._read = fake_read
sys.modules["roster"] = pytypes.SimpleNamespace(_drive=lambda: None)
quiet = lambda *_a: None                                          # noqa: E731


def trip(k):
    return next(t for t in db.get_job(jid)["trips"] if t["id"] == ids[k])


res = rp.run("2026-09-14", apply=False, log=quiet)
check("รายงานอย่างเดียว: ไม่แตะอะไร", trip("promo")["discount"] is None and trip("both")["insurance_fee"] is None)
check("อ่านใหม่เฉพาะ 3 แถวที่ไม่ลงตัว (ไม่อ่านแถวที่ลงตัว ไม่อ่านจอเก่า)", res["reread"] == 3)
check("แถวที่ต่อจากสองรูป อ่านรูปครึ่งล่าง (บล็อกผู้โดยสารอยู่ที่นั่น)",
      dict(seen)[ids["tolls"]].endswith("/d/BOTTOM/view"))

res = rp.run("2026-09-14", apply=True, log=quiet)
check("เขียนจริง: ส่วนลดถูกแยกออกจากช่องรวม", trip("promo")["discount"] == 50 and trip("promo")["other_adj"] is None)
check("เขียนจริง: ค่าประกันถูกแยกออกจากช่องรวม", trip("insured")["insurance_fee"] == -10)
check("เขียนจริง: #32256 ได้ครบทั้งสองบรรทัด", trip("both")["discount"] == 3 and trip("both")["insurance_fee"] == -10)
check("เขียนจริง: #31974 ได้ค่าทางด่วน", trip("tolls")["passenger_tolls"] == -140)
check("❗ ค่ารอบกับยอดชำระไม่ขยับเลยสักแถว",
      trip("tolls")["passenger_total"] == 285 and trip("both")["passenger_total"] == 31
      and trip("both")["passenger_paid"] == 39)
check("แถวที่อ่านใหม่แล้วยังไม่ลงตัว ปล่อยไว้ตามเดิม", trip("stubborn")["app_fee"] == -1 and res["left"] == 1)
check("ทุกแถวที่เก็บไป ลงตัวแล้วจริง", all(rp.gap(trip(k)) == 0 for k in ("promo", "insured", "both", "tolls")))
res = rp.run("2026-09-14", apply=False, log=quiet)
check("รอบสอง: เหลือแค่แถวที่คนต้องดู", res["reread"] == 1 and res["split"] == 0)

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
