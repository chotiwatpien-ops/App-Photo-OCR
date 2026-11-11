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

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
