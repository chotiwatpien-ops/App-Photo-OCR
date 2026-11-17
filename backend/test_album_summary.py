# -*- coding: utf-8 -*-
"""Each album counted top to bottom (Fiat 2026-11-11): every picture, exact copies, originals, the
most trips the pictures can give, trips paired so far, unpaired halves, repeats, rows deleted in
the review queue, real trips, trips in the customer's file and the gap to the count Ops wrote in
the album's name. Nothing is stored, so a leftover paired later changes the numbers by itself."""
import json
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-albsum-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from sqlalchemy import insert                                   # noqa: E402

import db                                                       # noqa: E402
import duplicate_report as dr                                   # noqa: E402

db.init_db()
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


W = ("2026-11-09", "2026-11-15")
A = "2W Karnjana 10 งาน"
job = db.create_job("สมชาย Win", "Trips", *W, category="2 W Saver")


def trip(name, **kw):
    with db.engine.begin() as c:
        return c.execute(insert(db.trips).values(job_id=job, file_name=name, source_album=A,
                                                 **dict(dict(status="done", committed=1), **kw))).inserted_primary_key[0]


first = [trip(f"{A}_{i}1+{i}2_฿30.jpg", booking_code=f"A-CODE{i}") for i in range(5)]   # five pairs, counted
trip(f"{A}_61+62_฿30.jpg", status="duplicate", committed=0,       # a repeat parked after reading
     booking_code="A-CODE0", duplicate_of=first[0])
trip(f"{A}_71+72_฿30.jpg", status="pending", committed=0)       # still out at the model
trip("long_shot.jpg", committed=1)                              # a long screenshot: one picture
db.log_action(action="trip.delete", target="trip:999",
              detail={"row": {"job_id": job, "file_name": f"{A}_91+92_฿23.jpg"}})
db.log_action(action="trip.delete", target="trip:998",
              detail={"row": {"job_id": 12345, "file_name": f"{A}_93+94_฿23.jpg"}})   # another week's job
pre = [{"ไรเดอร์ผู้ส่ง": A, "ของอัลบั้ม": A}] * 3                 # three exact copies
db.record_pool_run("move", "Week 9-15 Nov", {}, "", {"started_at": "2026-11-11 00:00:00", "albums": [
    {"week": "Week 9-15 Nov", "album": A, "leftovers": [{"file": "a"}, {"file": "b"}, {"file": "c"}]}]})

cases = lambda: dr.build(*dr.load(*W))[0]
row = next(r for r in dr.album_overview(*W, cases(), pre) if r[1] == A)
got = dict(zip(dr.ALBUM_COLS, row))
check("คอลัมน์ตรงกับหัวตาราง", len(row) == len(dr.ALBUM_COLS), (len(row), len(dr.ALBUM_COLS)))
check("❗ รูปทั้งหมด = ไฟล์ซ้ำ + รูปของทุกงาน (คู่ละ 2 · รูปยาว 1 · งานที่ลบด้วย) + รูปที่หาคู่ไม่ได้",
      got["รูปทั้งหมด"] == 3 + (5 + 1 + 1 + 1) * 2 + 1 + 3, got["รูปทั้งหมด"])
check("ต้นฉบับ = รูปทั้งหมด − ไฟล์ซ้ำ", got["ต้นฉบับ"] == got["รูปทั้งหมด"] - 3)
check("จับคู่ได้แล้ว = ทุกงานที่เคยจับได้ รวมงานที่ลบไปแล้ว", got["จับคู่ได้แล้ว"] == 9, got["จับคู่ได้แล้ว"])
check("❗ จับคู่ครบได้ = จับได้แล้ว + ครึ่งหนึ่งของรูปที่ค้าง", got["จับคู่ครบได้"] == 9 + 1, got["จับคู่ครบได้"])
check("❗ งานที่ลบในคิวตรวจนับจากบันทึก เฉพาะของสัปดาห์นี้", got["ลบในคิวตรวจ"] == 1, got["ลบในคิวตรวจ"])
check("❗ งานจริง = จับได้ − ซ้ำหลังอ่าน − ลบ", got["งานจริง"] == 9 - 1 - 1, got["งานจริง"])
check("ค้างในระบบ = งานจริง − นับในไฟล์ (ที่รออ่าน)", got["ลงงาน"] == 6 and got["ค้างในระบบ"] == 1, got)
check("❗ ยอดที่ Ops จดในชื่ออัลบั้ม และส่วนต่าง", got["ยอดที่ Ops จด"] == 10
      and got["ต่างจากยอด Ops"] == 10 - (10 - 1 - 1), got)

db.record_pool_run("move", "Week 9-15 Nov", {}, "", {"started_at": "2026-11-11 05:00:00", "albums": [
    {"week": "Week 9-15 Nov", "album": A, "leftovers": [{"file": "c"}]}]})
trip(f"{A}_101+102_฿30.jpg")                                    # a later run paired two leftovers
row = dict(zip(dr.ALBUM_COLS, next(r for r in dr.album_overview(*W, cases(), pre) if r[1] == A)))
check("❗ จับคู่รูปที่ค้างได้ทีหลัง ตัวเลขเปลี่ยนตามเอง (รูปทั้งหมดเท่าเดิม)",
      row["จับคู่ได้แล้ว"] == 10 and row["รูปทั้งหมด"] == got["รูปทั้งหมด"] and row["งานจริง"] == 8, row)

import dup_examples as dx                                        # noqa: E402
r = next(r for r in dr.album_overview(*W, cases(), pre) if r[1] == A)
labels = [x[0] for x in dx.summary_lines(r)]
check("การ์ดสรุปเรียงจากรูปทั้งหมดถึงยอดที่ Ops จด",
      labels[0] == "รูปทั้งหมดในอัลบั้ม" and "นับในไฟล์ลูกค้า" in labels and labels[-1].startswith("ยอดที่ Ops"), labels)

# --- one album the pool split between two weeks (2026-11-16: Loli 11 in W46, 94 in W47) ---
B = "4W Loli 6 งาน 16Nov"
W2 = ("2026-11-16", "2026-11-22")
job2 = db.create_job("ดาว Taxi", "Trips", *W2, category="4 W Standard")
with db.engine.begin() as c:
    for i in range(2):
        c.execute(insert(db.trips).values(job_id=job, file_name=f"{B}_{i}1+{i}2_฿50.jpg", source_album=B,
                                          status="done", committed=1))
    w47 = [c.execute(insert(db.trips).values(job_id=job2, file_name=f"{B}_{i}5+{i}6_฿50.jpg", source_album=B,
                                             booking_code=f"A-LOLI{i}", status="done", committed=1)
                     ).inserted_primary_key[0] for i in range(4)]
    c.execute(insert(db.trips).values(job_id=job2, file_name=f"{B}_99+98_฿50.jpg", source_album=B,
                                      booking_code="A-LOLI0", duplicate_of=w47[0],
                                      status="duplicate", committed=0))
r46 = dict(zip(dr.ALBUM_COLS, next(r for r in dr.album_overview(*W, cases(), pre) if r[1] == B)))
check("❗ อัลบั้มที่ถูกแบ่ง: บอกว่าอีกส่วนอยู่สัปดาห์ไหนกี่เที่ยว (แถวซ้ำไม่นับ)",
      r46["อีกส่วนอยู่สัปดาห์"] == "W47 4", r46["อีกส่วนอยู่สัปดาห์"])
check("❗ งานจริงทุกสัปดาห์ = ของสัปดาห์นี้ + อีกส่วน และเทียบ Ops จากยอดรวม (ไม่ขึ้นว่าขาด)",
      r46["งานจริงทุกสัปดาห์"] == 6 and r46["ต่างจากยอด Ops"] == 0, r46)
r47 = dict(zip(dr.ALBUM_COLS, next(r for r in dr.album_overview(*W2, dr.build(*dr.load(*W2))[0], [])
                                   if r[1] == B)))
check("อีกสัปดาห์เห็นส่วนของสัปดาห์แรกเช่นกัน", r47["อีกส่วนอยู่สัปดาห์"] == "W46 2"
      and r47["งานจริงทุกสัปดาห์"] == 6 and r47["ต่างจากยอด Ops"] == 0, r47)
check("อัลบั้มที่ไม่ถูกแบ่งไม่มีสองช่องนี้", got.get("อีกส่วนอยู่สัปดาห์") is None)
r = next(r for r in dr.album_overview(*W, cases(), pre) if r[1] == B)
check("การ์ดสรุปบอกยอดทุกสัปดาห์ของอัลบั้มที่ถูกแบ่ง",
      any(x[0] == "งานจริงของอัลบั้มนี้ทุกสัปดาห์" and x[1] == 6 for x in dx.summary_lines(r)))

for name, want in (("4W Loli 105 งาน 16Nov", 105), ("2W Tae รวมงาน 295 16Nov", 295),
                   ("4 W Ploy 357งาน 11Nov 2", 357), ("2W Parichart2  473 งาน", 473),
                   ("งาน 16Nov", None), ("2W Win มกรา", None), ("2W Karnjana 1,748 งาน", 1748)):
    check(f"เลขที่ Ops จด: {name!r} → {want}", dr.ops_count(name) == want, dr.ops_count(name))

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
