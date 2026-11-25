# -*- coding: utf-8 -*-
"""ชุดเฉลย (Fiat 2026-11-25). Almost every row is approved with nobody looking and nobody edits a
field, so nothing said how often the reader is right. A person now checks a random sample of
auto-approved rows against the slip picture; what the picture prints is stored beside the trip,
never on it, and the accuracy of each field is counted from that."""
import os
import re
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-key-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from fastapi.testclient import TestClient                       # noqa: E402
from sqlalchemy import func, insert, inspect, select, update    # noqa: E402

import answer_key as key                                        # noqa: E402
import db                                                       # noqa: E402
import main                                                     # noqa: E402

db.init_db()
web = TestClient(main.app)
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and bool(cond)


def refused(field, value):
    try:
        key.FIELD[field].canon(value)
    except ValueError:
        return True
    return False


F = key.FIELD
check("ช่องที่ตรวจมี 8 ช่อง เรียงตามที่ตาเจอบนสลิป",
      [f.key for f in key.FIELDS] == ["trip_time", "booking_code", "distance_km", "service_type",
                                      "payment_method", "net_earnings", "base_fare", "turbo"])
check("ทุกช่องเป็นคอลัมน์ของ trips", all(f.key in db.trips.c for f in key.FIELDS))
check("เวลา เขียนแบบเดียวเสมอ", F["trip_time"].canon("8:38") == "08:38" and F["trip_time"].canon(" 08:38 ") == "08:38")
check("เวลาที่เป็นไปไม่ได้ ไม่รับ", refused("trip_time", "25:00") and refused("trip_time", "เช้า"))
check("รหัสการจอง ตัวใหญ่ ไม่มีช่องว่าง", F["booking_code"].canon(" a-te stke y000 1av ") == "A-TESTKEY0001AV")
check("ตัวเลข เขียนทศนิยม 2 ตำแหน่ง",
      [F["net_earnings"].canon(v) for v in (47, "47", "47.0", " 1,047.5 ")] == ["47.00", "47.00", "47.00", "1047.50"])
check("0 เป็นค่า ไม่ใช่ช่องว่าง", F["turbo"].canon(0) == "0.00" and F["turbo"].canon("0") == "0.00")
check("ตัวเลขที่ไม่ใช่ตัวเลข ไม่รับ", refused("base_fare", "แปดสิบ") and refused("base_fare", "nan"))
check("รถยนต์ทุกแบบคือ Standard Car",
      [F["service_type"].canon(v) for v in ("Saver Car", "Standard Taxi", "Saver Bike")]
      == ["Standard Car", "Standard Car", "Saver Bike"])
check("ประเภทบริการนอกรายการ ไม่รับ", refused("service_type", "Rocket"))
check("การจ่ายเงินนอกรายการ ไม่รับ", refused("payment_method", "Cash") and F["payment_method"].canon("QR PAY") == "QR PAY")
check("ค่าว่างและ UNKNOWN คือไม่มีค่า",
      [F[k].canon(v) for k, v in (("trip_time", None), ("booking_code", "  "), ("turbo", ""),
                                  ("payment_method", "UNKNOWN"), ("service_type", None))] == [None] * 5)
check("หน้าเว็บได้ป้าย ชนิด ตัวเลือก และคำแนะนำจากที่เดียว",
      F["service_type"].public() == {"key": "service_type", "label": "ประเภทบริการ", "kind": "choice",
                                     "hint": "ชิปใต้แผนที่ · รถยนต์ทุกแบบ = Standard Car",
                                     "options": ["Saver Bike", "Standard Bike", "Standard Car"]})


def fact(field, truth, trip=1):
    return key.KeyFact(trip, field, truth)


got = key.tally([
    (fact("booking_code", "A-TESTKEY0001AV"), "A-TESTKEY0001AV"),
    (fact("booking_code", "A-TESTKEY0002AV"), "A-TESTKEY0002"),
    (fact("booking_code", "A-TESTKEY0003AV"), None),
    (fact("booking_code", None), None),
    (fact("booking_code", None), "A-TESTKEY0004"),
    (fact("turbo", "0.00"), "0.00"),
])
code = got["booking_code"]
check("นับ ถูก ผิด และไม่มีในรูป แยกกัน",
      (code.right, code.wrong, code.absent_blank, code.absent_filled) == (1, 2, 1, 1), code)
check("❗ แถวว่างทั้งที่รูปมี นับเป็นผิด และบอกได้ว่า AI เว้นว่าง", code.missed == 1, code)
check("❗ ความแม่นยำ = ถูก ÷ (ถูก + ผิด) สิ่งที่ไม่มีในรูปไม่อยู่ในตัวหาร", abs(code.rate - 1 / 3) < 1e-9, code.rate)
check("ทุกช่องมีผลนับ แม้ยังไม่มีใครตรวจ", set(got) == set(F) and got["trip_time"] == key.Tally())
check("ช่องที่ยังไม่ได้ตรวจ ไม่มีความแม่นยำ", key.Tally().rate is None and key.Tally().interval() is None)

low, high = key.Tally(right=104, wrong=4).interval()
check("ช่วง 95% ของ 104 จาก 108 คือ 90.9–98.6", abs(low - 0.9086) < 0.001 and abs(high - 0.9855) < 0.001, (low, high))
low, high = key.Tally(right=120).interval()
check("❗ ถูก 120 จาก 120 ไม่ได้แปลว่า 100%: ปลายล่างราว 96.9%", abs(low - 0.969) < 0.001 and high == 1.0, (low, high))
low, high = key.Tally(wrong=5).interval()
check("ผิดหมด ปลายล่างเป็น 0", low == 0.0 and 0.4 < high < 0.5, (low, high))
shown = key.Tally(right=3, wrong=1, missed=1, absent_filled=2).public()
check("ผลนับที่ส่งให้หน้าเว็บ มีครบทุกตัว",
      {k: shown[k] for k in ("right", "wrong", "missed", "absent_blank", "absent_filled", "rate")}
      == {"right": 3, "wrong": 1, "missed": 1, "absent_blank": 0, "absent_filled": 2, "rate": 0.75}
      and shown["low"] < 0.75 < shown["high"], shown)

ids = list(range(1, 2001))
order = sorted(ids, key=key.rank)
check("ลำดับการตรวจไม่ใช่ลำดับเลขแถว", order[:50] != ids[:50] and sorted(order) == ids)
check("ลำดับเดิมทุกครั้งที่ถาม", order == sorted(ids, key=key.rank))
late = sorted(ids + [5000, 5001], key=key.rank)
check("แถวที่มาทีหลัง ไม่เปลี่ยนลำดับของแถวเดิม", [i for i in late if i <= 2000] == order)
first = order[:200]
check("ใบแรก ๆ กระจายทั่วทั้งสัปดาห์ ไม่กองอยู่ช่วงเดียว",
      all(40 <= sum(lo < i <= lo + 500 for i in first) <= 60 for lo in (0, 500, 1000, 1500)),
      [sum(lo < i <= lo + 500 for i in first) for lo in (0, 500, 1000, 1500)])

tables = inspect(db.engine).get_table_names()
check("ตารางชุดเฉลยถูกสร้างพร้อมฐานข้อมูล", {"key_facts", "key_slips"} <= set(tables), tables)

SOURCE = Path("backend/answer_key.py").read_text(encoding="utf-8")
writes = re.findall(r"\b(insert|update|delete)\(\s*([\w.]+)", SOURCE)
check("❗ ชุดเฉลยไม่เขียนตาราง trips (เขียนได้แค่ key_facts กับ key_slips)",
      all(target in ("db.key_facts", "db.key_slips") for _, target in writes)
      and not re.search(r"\btext\(|update_trip|executescript", SOURCE), writes)
check("ชุดเฉลยเรียก db ได้เฉพาะตัวที่ไม่แก้แถวงาน",
      set(re.findall(r"\bdb\.(\w+)", SOURCE)) <= {"engine", "trips", "jobs", "key_facts", "key_slips",
                                                   "_now", "closed_weeks"},
      set(re.findall(r"\bdb\.(\w+)", SOURCE)))
others = [p for p in Path("backend").glob("*.py")
          if p.name != "answer_key.py" and not p.name.startswith("test_")]
defined = re.compile(r'^key_(facts|slips) = Table\(\s*"key_\1", meta,', re.M)
touch = []
for p in others:
    code_only = "\n".join(line for line in p.read_text(encoding="utf-8").splitlines()
                          if not line.lstrip().startswith("#"))
    if p.name == "db.py":
        code_only = defined.sub("", code_only)
    if re.search(r"key_facts|key_slips", code_only):
        touch.append(p.name)
check("❗ มีแต่ answer_key.py ที่อ่านเขียนตารางชุดเฉลย", touch == [] and len(others) > 20, touch)

r = web.get("/api/answer-key/report")
check("ยังไม่มีงานสักสัปดาห์ หน้ารายงานยังเปิดได้",
      r.status_code == 200 and r.json()["weeks"] == [] and r.json()["total"]["slips"] == 0
      and r.json()["progress"] == {"eligible": 0, "checked": 0, "no_picture": 0}, r.text)

W47, W48 = ("2026-11-16", "2026-11-22"), ("2026-11-23", "2026-11-29")
home = db.create_job("ก Home", "Trips", *W47, category="2 W Saver")
win = db.create_job("ข Win", "Trips", *W48, category="2 W Standard")
made = [0]


def trip(job, **kw):
    made[0] += 1
    n = made[0]
    row = dict(job_id=job, file_name=f"slip{n}.jpg", status="done", committed=1, auto_approved=1,
               check_status="pass", trip_date="2026-11-18", trip_time="08:38",
               booking_code=f"A-TESTKEY{n:04d}AV", distance_km=10.79, service_type="Saver Bike",
               payment_method="CASH", net_earnings=87.0, base_fare=82.0, turbo=5.0, bonus=0.0,
               model="reader-a", prompt_version="aaaaaaaaaa", image_blob=b"\x00slip\xff", image_mime="image/jpeg",
               source_url=f"https://drive.google.com/file/d/FILE{n:04d}/view")
    row.update(kw)
    with db.engine.begin() as c:
        return c.execute(insert(db.trips).values(**row)).inserted_primary_key[0]


def all_trips():
    with db.engine.begin() as c:
        return {r[0]: tuple(r) for r in c.execute(select(db.trips))}


def stored():
    """(facts, slips answered, slips handed out) straight from the key's two tables."""
    with db.engine.begin() as c:
        return (c.execute(select(func.count()).select_from(db.key_facts)).scalar(),
                c.execute(select(func.count()).select_from(db.key_slips)
                          .where(db.key_slips.c.outcome.isnot(None))).scalar(),
                c.execute(select(func.count()).select_from(db.key_slips)).scalar())


def facts_of(trip_id):
    with db.engine.begin() as c:
        return {r.field: (r.truth, r.row_value) for r in c.execute(
            select(db.key_facts).where(db.key_facts.c.trip_id == trip_id))}


def held_back(trip_id, minutes):
    """The claim on this slip was made `minutes` ago."""
    from datetime import datetime, timedelta
    then = (datetime.fromisoformat(db._now()) - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    with db.engine.begin() as c:
        c.execute(update(db.key_slips).where(db.key_slips.c.trip_id == trip_id).values(claimed_at=then))


SEEN = {}        # every slip the key handed out, by trip id


def ask(checker, answer=None, week=W47[0]):
    body = {"week": week, "checker": checker}
    if answer is not None:
        body["answer"] = answer
    r = web.post("/api/answer-key/check", json=body)
    if r.status_code == 200 and r.json()["slip"]:
        SEEN[r.json()["slip"]["trip_id"]] = r.json()["slip"]
    return r


def confirm(slip, absent=(), seconds=12, **changed):
    """The answer the page sends: what was shown, except the fields the person changed."""
    facts = {k: v for k, v in {**slip["shown"], **changed}.items() if k not in absent}
    return {"trip_id": slip["trip_id"], "facts": facts, "absent": list(absent), "seconds": seconds}


eligible = [trip(home) for _ in range(12)]
two_part = eligible[3]
by_person = trip(home, auto_approved=0)
waiting = trip(home, committed=0, auto_approved=0)
unread = trip(home, status="error", committed=0, auto_approved=0)
lower_half = trip(home, status="merged", committed=0, auto_approved=0, merged_into=two_part,
                  source_url="https://drive.google.com/open?id=LOWER-half_01")
next_week = [trip(win, trip_date="2026-11-25") for _ in range(3)]
order = sorted(eligible, key=key.rank)
before = all_trips()

r = ask("phone-a")
first = r.json()["slip"]
check("เริ่มตรวจ ได้ใบแรกตามลำดับสุ่ม ไม่ใช่เลขแถวแรก",
      r.status_code == 200 and first["trip_id"] == order[0] and order != eligible, (r.text, order[0]))
check("บอกความคืบหน้าของสัปดาห์: งานอนุมัติอัตโนมัติ 12 ใบ ยังไม่ได้ตรวจ",
      r.json()["progress"] == {"eligible": 12, "checked": 0, "no_picture": 0}, r.json()["progress"])
n = eligible.index(order[0]) + 1
check("ใบที่ได้ บอกค่าที่แถวมีอยู่ทุกช่อง เขียนแบบเดียวกับชุดเฉลย",
      first["shown"] == {"trip_time": "08:38", "booking_code": f"A-TESTKEY{n:04d}AV", "distance_km": "10.79",
                         "service_type": "Saver Bike", "payment_method": "CASH", "net_earnings": "87.00",
                         "base_fare": "82.00", "turbo": "5.00"}, first["shown"])
check("ใบที่ได้ บอกรูปบน Drive และรูปสำรองจากเซิร์ฟเวอร์",
      first["pictures"] == [{"drive_id": f"FILE{n:04d}", "fallback": f"/api/trips/{order[0]}/image?part=1",
                             "open": f"https://drive.google.com/file/d/FILE{n:04d}/view"}], first["pictures"])
check("❗ ถามซ้ำ (ปิดจอแล้วกลับมา) ได้ใบเดิม", ask("phone-a").json()["slip"] == first)
second = ask("phone-b").json()["slip"]
check("❗ อีกเครื่องตรวจพร้อมกัน ได้คนละใบ", second["trip_id"] == order[1], second["trip_id"])

whole = confirm(first)
short = {**whole, "facts": {k: v for k, v in whole["facts"].items() if k != "turbo"}}
twice = {**whole, "absent": ["turbo"]}
extra = {**whole, "facts": {**whole["facts"], "tip": "5"}}
for name, bad, word in (
        ("ขาดไป 1 ช่อง", short, "ไม่ครบ"), ("ช่องเดียวอยู่ทั้งสองฝั่ง", twice, "ไม่ครบ"),
        ("มีช่องที่ไม่รู้จัก", extra, "ไม่ครบ"), ("ไม่มีคำตอบเลย", {"trip_id": first["trip_id"]}, "ไม่ครบ"),
        ("ค่าว่าง", confirm(first, booking_code="  "), "รหัสการจอง"),
        ("เวลาที่เป็นไปไม่ได้", confirm(first, trip_time="31:99"), "เวลาบนแถบสถานะ"),
        ("ตัวเลือกนอกรายการ", confirm(first, payment_method="Cash"), "การจ่ายเงิน"),
        ("ตัวเลขที่ไม่ใช่ตัวเลข", confirm(first, turbo="ห้า"), "Turbo")):
    r = ask("phone-a", bad)
    check(f"คำตอบไม่สมบูรณ์ ({name}) ไม่รับ และบอกเหตุผล", r.status_code == 400 and word in r.json()["detail"], r.text)
check("❗ คำตอบที่ไม่รับ ไม่ถูกบันทึกแม้แต่ช่องเดียว และใบยังอยู่กับคนเดิม",
      stored() == (0, 0, 2) and ask("phone-a").json()["slip"] == first, stored())

r = ask("phone-a", confirm({"trip_id": order[6], "shown": first["shown"]}))
check("❗ ตอบใบที่ระบบไม่ได้สุ่มให้ ไม่รับ", r.status_code == 409 and "ไม่ได้อยู่ในชุด" in r.json()["detail"], r.text)
r = ask("phone-a", confirm({"trip_id": by_person, "shown": first["shown"]}))
check("ตอบแถวที่คนอนุมัติเอง ไม่รับ", r.status_code == 409 and stored() == (0, 0, 2), (r.status_code, stored()))
check("สัปดาห์ที่ไม่มีงาน ตอบ 404", ask("phone-a", week="2020-01-06").status_code == 404
      and ask("phone-a", confirm(first), week="").status_code == 404 and stored() == (0, 0, 2))
check("ไม่บอกว่าเครื่องไหนตรวจ ไม่รับ", ask("").status_code == 400)

r = ask("phone-a", whole)
third = r.json()["slip"]
check("❗ กด ตรงทุกช่อง แล้วได้ใบถัดไปที่ยังไม่มีใครถือ",
      r.status_code == 200 and third["trip_id"] == order[2]
      and r.json()["progress"] == {"eligible": 12, "checked": 1, "no_picture": 0}, r.text)
check("เก็บความจริงและค่าที่แถวมีตอนตรวจ ช่องละแถว",
      facts_of(order[0]) == {k: (v, v) for k, v in first["shown"].items()}, facts_of(order[0]))
r = ask("phone-a", whole)
check("❗ ส่งคำตอบเดิมซ้ำ (เน็ตหลุดแล้วส่งใหม่) ไม่มีอะไรเปลี่ยน และได้ใบถัดไปใบเดิม",
      r.json()["slip"] == third and r.json()["progress"]["checked"] == 1 and stored() == (8, 1, 3), (r.text, stored()))

held_back(order[1], 19)
fourth = ask("phone-c").json()["slip"]
check("ใบที่ถือมา 19 นาที ยังเป็นของคนเดิม", fourth["trip_id"] == order[3], fourth["trip_id"])
held_back(order[1], 21)
check("❗ ถือเกิน 20 นาที ใบกลับเข้ากอง คนถัดไปที่ถามได้ไป", ask("phone-d").json()["slip"]["trip_id"] == order[1])
check("คนเดิมกลับมา ได้ใบอื่น", ask("phone-b").json()["slip"]["trip_id"] == order[4])
check("❗ ใบที่สุ่มให้ไปแล้วเป็นช่วงต้นของลำดับสุ่มเสมอ ไม่มีใบถูกข้าม", set(SEEN) == set(order[:5]), sorted(SEEN))

r = ask("phone-a", {"trip_id": third["trip_id"], "no_picture": True})
check("❗ ดูรูปไม่ได้ ถูกนับไว้ ไม่นับเป็นตรวจแล้ว",
      r.json()["progress"] == {"eligible": 12, "checked": 1, "no_picture": 1}, r.json()["progress"])
check("ดูรูปไม่ได้ ไม่เก็บความจริงของช่องใด", facts_of(third["trip_id"]) == {})

db.close_week(*W47)
slip = r.json()["slip"]
while slip:
    r = ask("phone-a", confirm(slip))
    slip = r.json()["slip"]
check("❗ สัปดาห์ที่ปิดแล้ว ตรวจต่อได้ โดยไม่มีใบดูรูปไม่ได้กลับมาให้ตรวจซ้ำ",
      r.status_code == 200 and r.json()["progress"] == {"eligible": 12, "checked": 8, "no_picture": 1}, r.text)
check("ใบที่เหลือมีคนอื่นถืออยู่ คนนี้จึงไม่มีใบให้ตรวจ", r.json()["slip"] is None)
for mine, who in ((order[1], "phone-d"), (order[3], "phone-c"), (order[4], "phone-b")):
    got = ask(who).json()["slip"]
    r = ask(who, confirm(got))
    check(f"{who} ยังถือใบของตัวเอง และตอบได้", got["trip_id"] == mine and r.json()["slip"] is None, r.text)
check("❗ ตรวจครบ: ทุกใบที่อนุมัติอัตโนมัติถูกสุ่มให้ แถวอื่นไม่เคยถูกสุ่ม",
      set(SEEN) == set(eligible) and r.json()["progress"] == {"eligible": 12, "checked": 11, "no_picture": 1},
      (sorted(SEEN), r.json()["progress"]))
pictures = SEEN[two_part]["pictures"]
check("เที่ยวที่ต่อจากรูป 2 ใบ ได้รูปครบทั้งสองใบ",
      len(pictures) == 2 and pictures[1]["drive_id"] == "LOWER-half_01"
      and pictures[1]["fallback"] == f"/api/trips/{two_part}/image?part=2"
      and all(len(s["pictures"]) == 1 for i, s in SEEN.items() if i != two_part), pictures)
r = web.patch(f"/api/trips/{order[0]}", json={"turbo": 1})
check("แถวที่อนุมัติแล้วยังแก้ไม่ได้เหมือนเดิม", r.status_code == 409, r.status_code)

order48 = sorted(next_week, key=key.rank)
got = ask("phone-a", week=W48[0]).json()["slip"]
late = min(range(5000, 9000), key=key.rank)
trip(win, id=late, trip_date="2026-11-28")
r = ask("phone-a", confirm(got), week=W48[0])
check("❗ แถวที่เข้ามาทีหลัง ได้ที่ของตัวเองในลำดับ ไม่ถูกทิ้งไว้ท้ายแถว",
      got["trip_id"] == order48[0] and r.json()["slip"]["trip_id"] == late
      and key.rank(late) < key.rank(order48[1]), (got["trip_id"], r.json()["slip"]))
check("อีกสัปดาห์นับความคืบหน้าของตัวเอง",
      r.json()["progress"] == {"eligible": 4, "checked": 1, "no_picture": 0}, r.json()["progress"])

now = all_trips()
check("❗ ตรวจไปทั้งสัปดาห์ แถวงานทุกแถวเหมือนเดิมทุกไบต์", {i: now[i] for i in before} == before
      and len(before) == 19 and before[order[0]][db.trips.c.keys().index("image_blob")] == b"\x00slip\xff")

log = db.list_actions(action="answer.check", limit=500)
one = next(a for a in log if a["target"] == f"trip:{order[0]}" and a["status"] == 200)
check("บันทึกการกระทำเก็บคำตอบทุกครั้งที่ส่ง พร้อมความจริงที่ตอบ",
      one["detail"]["facts"] == first["shown"] and one["detail"]["absent"] == []
      and one["detail"]["checker"] == "phone-a" and one["detail"]["seconds"] == 12
      and sum(a["target"] == f"trip:{order[0]}" and a["status"] == 200 for a in log) == 2, one)
gone = next(a for a in log if a["target"] == f"trip:{third['trip_id']}")
check("บันทึกการกระทำบอกว่าใบไหนดูรูปไม่ได้", gone["detail"].get("no_picture") is True, gone)


def report(week=""):
    r = web.get(f"/api/answer-key/report?week={week}")
    return r.json() if r.status_code == 200 else r.status_code


def counts(rep, field):
    return tuple(rep["fields"][field][k] for k in ("right", "wrong", "missed", "absent_blank", "absent_filled"))


done47 = report(W47[0])
check("รายงานบอกสัปดาห์ ว่าปิดแล้วหรือยัง และตรวจไปถึงไหน",
      (done47["week"], done47["label"], done47["closed"]) == (W47[0], "2026-W47", True)
      and done47["progress"] == {"eligible": 12, "checked": 11, "no_picture": 1}, done47["progress"])
check("ยืนยันตรงทุกช่อง 11 ใบ = ถูกทุกช่อง 11 ใบ ใบที่ดูรูปไม่ได้ไม่อยู่ในผลนับ",
      (done47["total"]["slips"], done47["total"]["all_right"]) == (11, 11)
      and all(counts(done47["total"], f.key) == (11, 0, 0, 0, 0) for f in key.FIELDS), done47["total"])
check("❗ ถูกหมด 11 ใบ บอกได้แค่ว่าไม่ต่ำกว่าราว 74%",
      all(v["rate"] == 1.0 and abs(v["low"] - 0.741) < 0.002 for v in done47["total"]["fields"].values()),
      done47["total"]["fields"]["turbo"])
check("❗ รายการช่องของหน้าเว็บมาจากรายการเดียวกับที่ใช้นับ",
      done47["fields"] == [f.public() for f in key.FIELDS] and list(done47["total"]["fields"]) == list(key.FIELD))
check("ไม่มีช่องไหนผิด รายการใบที่อ่านผิดว่าง", done47["misses"] == [])

W46 = ("2026-11-09", "2026-11-15")
old = db.create_job("ค Taxi", "Trips", *W46, category="4 W Standard")
plain = trip(old)
cut_tail = trip(old, booking_code="A-TESTKEY9002")
no_clock = trip(old, trip_time=None, prompt_version="bbbbbbbbbb")
folded = trip(old, trip_time=None, booking_code="A-TESTKEY9004", prompt_version=None)
dark = trip(old, prompt_version=None)
before = all_trips()
answers = {
    plain: lambda s: confirm(s, seconds=10),
    cut_tail: lambda s: confirm(s, seconds=20, booking_code="a-testkey 9002av"),
    no_clock: lambda s: confirm(s, seconds=30, trip_time="8:05"),
    folded: lambda s: confirm(s, absent=("trip_time", "booking_code"), seconds=700, turbo="0"),
    dark: lambda s: {"trip_id": s["trip_id"], "no_picture": True},
}
slip = ask("phone-a", week=W46[0]).json()["slip"]
while slip:
    if slip["trip_id"] == no_clock:
        blank = ask("phone-a", confirm(slip), week=W46[0])
    slip = ask("phone-a", answers[slip["trip_id"]](slip), week=W46[0]).json()["slip"]
check("❗ ช่องที่แถวว่าง กดยืนยันว่าตรงไม่ได้ ต้องพิมพ์ค่าที่เห็นหรือบอกว่าไม่มีในรูป",
      blank.status_code == 400 and "เวลาบนแถบสถานะ" in blank.json()["detail"], blank.text)

got = report(W46[0])
total = got["total"]
check("ตรวจ 4 ใบ ดูรูปไม่ได้ 1 ใบ ถูกทุกช่อง 1 ใบ",
      got["progress"] == {"eligible": 5, "checked": 4, "no_picture": 1}
      and (total["slips"], total["all_right"]) == (4, 1), (got["progress"], total["slips"], total["all_right"]))
check("❗ แถวว่างทั้งที่รูปมีเวลา = ผิด และนับว่า AI เว้นว่าง · ไม่มีแถบสถานะและแถวว่าง = ไม่อยู่ในตัวหาร",
      counts(total, "trip_time") == (2, 1, 1, 1, 0) and abs(total["fields"]["trip_time"]["rate"] - 2 / 3) < 1e-9,
      total["fields"]["trip_time"])
check("❗ รหัสขาดท้าย = ผิด · รหัสถูกจอตัดแต่แถวมีค่า = ไม่มีในรูป แถวมีค่า ไม่ลากความแม่นยำลง",
      counts(total, "booking_code") == (2, 1, 0, 0, 1) and abs(total["fields"]["booking_code"]["rate"] - 2 / 3) < 1e-9,
      total["fields"]["booking_code"])
check("การ์ดกางแต่ไม่มีบรรทัด Turbo ความจริงคือ 0: แถวที่ใส่ 5 นับเป็นผิด",
      counts(total, "turbo") == (3, 1, 0, 0, 0) and total["fields"]["turbo"]["rate"] == 0.75, total["fields"]["turbo"])
check("ช่องที่เหลือถูกครบ 4 ใบ",
      all(counts(total, f) == (4, 0, 0, 0, 0)
          for f in ("distance_km", "service_type", "payment_method", "net_earnings", "base_fare")))
check("ช่วงที่น่าจะเป็นคร่อมค่าความแม่นยำ",
      all(v["low"] <= v["rate"] <= v["high"] for v in total["fields"].values()))
check("เวลาต่อใบเป็นค่ากลาง และใบที่ค้างนานนับไม่เกิน 10 นาที", total["seconds_per_slip"] == 25, total["seconds_per_slip"])
readers = [(g["model"], g["prompt_version"], g["slips"]) for g in got["by_reader"]]
check("❗ แยกตามตัวอ่าน: prompt สองรุ่น และแถวที่ไม่ได้บันทึกรุ่นเป็นกลุ่มของตัวเอง",
      readers == [("reader-a", "aaaaaaaaaa", 2), ("reader-a", None, 1), ("reader-a", "bbbbbbbbbb", 1)], readers)
check("ผลนับของแต่ละตัวอ่านเป็นของใบที่ตัวอ่านนั้นอ่าน",
      counts(got["by_reader"][0], "booking_code") == (1, 1, 0, 0, 0)
      and counts(got["by_reader"][1], "turbo") == (0, 1, 0, 0, 0)
      and counts(got["by_reader"][1], "booking_code") == (0, 0, 0, 0, 1)
      and counts(got["by_reader"][2], "trip_time") == (0, 1, 1, 0, 0), got["by_reader"])
misses = {(m["trip_id"], m["field"], m["row"], m["truth"]) for m in got["misses"]}
check("❗ รายการช่องที่อ่านผิด บอกค่าบนแถวและค่าบนรูป ช่องที่ไม่มีในรูปไม่อยู่ในรายการ",
      misses == {(cut_tail, "booking_code", "A-TESTKEY9002", "A-TESTKEY9002AV"),
                 (no_clock, "trip_time", None, "08:05"), (folded, "turbo", "5.00", "0.00")}
      and len(got["misses"]) == 3, got["misses"])
check("แต่ละรายการมีลิงก์เปิดรูปบน Drive",
      all(re.fullmatch(r"https://drive\.google\.com/file/d/FILE\d{4}/view", m["open"]) for m in got["misses"]))

check("❗ ตรงทุกช่อง แก้ค่า ไม่มีในรูป ดูรูปไม่ได้: แถวงานทุกแถวเหมือนเดิมทุกไบต์", all_trips() == before and len(before) == 25)

with db.engine.begin() as c:
    c.execute(update(db.trips).where(db.trips.c.id == cut_tail)
              .values(model="reader-b", prompt_version="cccccccccc", booking_code="A-TESTKEY9002AV"))
check("❗ แถวถูกอ่านใหม่หลังตรวจ: รายงานยังเป็นของตัวอ่านและค่าที่คนเห็นตอนตรวจ", report(W46[0]) == got)

r = ask("phone-a", confirm(SEEN[no_clock], absent=("trip_time",), seconds=5), week=W46[0])
again = report(W46[0])
check("ย้อนไปแก้คำตอบของใบก่อน: รายงานใช้คำตอบล่าสุด ไม่นับใบซ้ำ",
      r.json()["slip"] is None and counts(again["total"], "trip_time") == (2, 0, 0, 2, 0)
      and again["total"]["slips"] == 4 and len(again["misses"]) == 2, again["total"]["fields"]["trip_time"])
sent = [a["detail"]["facts"].get("trip_time")
        for a in db.list_actions(action="answer.check", target=f"trip:{no_clock}")]
check("❗ คำตอบที่ถูกแทนยังอยู่ในบันทึกการกระทำ", sent == [None, "08:05"], sent)

with db.engine.begin() as c:
    c.execute(insert(db.key_facts).values(trip_id=plain, field="retired_field", truth="1.00", row_value="2.00",
                                          checked_at=db._now()))
check("ช่องที่เลิกตรวจแล้วยังเก็บอยู่ แต่ไม่อยู่ในรายงาน", report(W46[0]) == again)

every = report("all")
check("ทุกสัปดาห์รวมกัน",
      (every["week"], every["label"], every["closed"]) == ("all", "ทุกสัปดาห์", False)
      and every["progress"] == {"eligible": 21, "checked": 16, "no_picture": 2}
      and every["total"]["slips"] == 16 and every["total"]["all_right"] == 14, (every["progress"], every["total"]["slips"]))
newest = report()
check("ไม่ระบุสัปดาห์ ได้สัปดาห์ล่าสุด พร้อมรายการสัปดาห์ให้เลือก",
      newest["week"] == W48[0] and newest["total"]["slips"] == 1
      and newest["weeks"] == [{"date_from": W48[0], "label": "2026-W48", "closed": False},
                              {"date_from": W47[0], "label": "2026-W47", "closed": True},
                              {"date_from": W46[0], "label": "2026-W46", "closed": False}], newest["weeks"])
check("สัปดาห์ที่ไม่มีงาน ตอบ 404", report("2020-01-06") == 404)
size = stored()
report(W46[0])
report("all")
now = all_trips()
check("❗ เปิดรายงานไม่เขียนอะไร และแถวงานที่ชุดเฉลยไม่ได้แตะยังเหมือนเดิมทุกไบต์",
      stored() == size and all(now[i] == before[i] for i in before if i != cut_tail))

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
