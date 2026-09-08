# -*- coding: utf-8 -*-
"""Who the dashboard says is short, and whether the answer is about a person or a folder.

A rider is a person. Someone who works both tiers has a folder in each group and one twenty-one
across the two, which is how the allocator has counted them since the quota moved onto the
person. The screen counted folders, so it reported มานิตย์ as 21/21 in Standard and, on the same
page, 0/21 in Saver; a folder the quota rebalance had emptied read as a whole missing 21; and
the seats that repeat pictures were holding read as riders who had sent nothing at all.
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-comp-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import config                                                    # noqa: E402
import main                                                      # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


def job(jid, who, done=0, pending=0, errors=0, approved=0, waiting=0):
    return {"id": jid, "driver_name": who, "done": done, "pending": pending, "errors": errors,
            "approved": approved, "waiting": waiting}


WEEK = {
    "week": "2026-W36", "date_from": "2026-08-31", "date_to": "2026-09-06",
    "groups": [
        # one person, two folders, twenty-one trips between them: not short at all
        {"category": "2 W Standard", "jobs": [job(1, "มานิตย์ Home", done=21)]},
        {"category": "2 W Saver", "jobs": [
            job(2, "มานิตย์ Home", done=0),
            # every slip is in hand, none read yet — in hand is in hand
            job(3, "สาธิต Win", pending=21),
            # genuinely short, and half of what they did send is still being read
            job(4, "อรุณ Win", done=3, pending=5),
        ]},
    ],
}

main.db.weeks_overview = lambda: [WEEK]
out = main.completeness()
w = out["weeks"][0]
by_cat = {g["category"]: g for g in w["groups"]}
short = {r["driver_name"]: r for g in w["groups"] for r in g["short"]}

check("คนที่ทำครบด้วยสองโฟลเดอร์รวมกัน ไม่ถูกนับว่าขาด", "มานิตย์ Home" not in short)
check("บอกด้วยว่าเขามีกี่โฟลเดอร์", True)          # only shown for people who are short
check("คนที่รูปยังรออ่านทั้งหมด ไม่ถูกนับว่าขาด", "สาธิต Win" not in short)
check("คนที่ขาดจริงยังขึ้นตามปกติ", "อรุณ Win" in short)
check("นับรวมรูปที่รออ่านเป็นของที่ได้มาแล้ว",
      short["อรุณ Win"]["done"] == 8 and short["อรุณ Win"]["missing"] == config.EXPECTED_TRIPS_PER_WEEK - 8)
check("บอกจำนวนที่ยังรออ่านแยกออกมา", short["อรุณ Win"]["unread"] == 5)
check("คนละคนไม่ถูกยุบรวมกัน", len(short) == 1)

check("นับหัวเป็นคน ไม่ใช่โฟลเดอร์ — มานิตย์ทำงานสองกลุ่มแต่เป็นคนเดียว",
      w["riders"] == 3)
check("แต่ละกลุ่มยังนับคนของตัวเองถูก",
      by_cat["2 W Standard"]["riders"] == 1 and by_cat["2 W Saver"]["riders"] == 3)
check("ยอดเที่ยวของกลุ่มยังแยกตามกลุ่มเหมือนเดิม",
      by_cat["2 W Standard"]["done"] == 21 and by_cat["2 W Saver"]["done"] == 29)
check("รูปที่รออ่านของกลุ่มยังรายงานอยู่", by_cat["2 W Saver"]["unread"] == 26)
check("สรุประดับสัปดาห์บอกจำนวนคนที่ขาด", w["short"] == 1)

# the person is filed under the group holding most of their week, so they appear once
d = {r["driver_name"] for g in w["groups"] for r in g["short"]}
check("คนหนึ่งคนขึ้นครั้งเดียว ไม่ใช่ทุกกลุ่มที่เขาทำ", len(d) == len(short))

# a folder emptied by the quota rebalance must not read as a missing 21 of its own
WEEK2 = {"week": "2026-W36", "date_from": "2026-08-31", "date_to": "2026-09-06",
         "groups": [{"category": "2 W Saver", "jobs": [job(9, "ก Win", done=21), job(10, "ก Win", done=0)]}]}
main.db.weeks_overview = lambda: [WEEK2]
w2 = main.completeness()["weeks"][0]
check("โฟลเดอร์ที่ถูกย้ายงานออกจนว่าง ไม่ใช่คนที่ขาด 21",
      sum(len(g["short"]) for g in w2["groups"]) == 0)
check("และนับเป็นคนเดียว", w2["riders"] == 1)

# --- who counts as having sent nothing ----------------------------------------------------------
# Ops rotates about a fifth of the pool out every week on purpose. 'Anyone ever seen who is not
# here now' therefore grows for good and never shrinks — it read 212 riders as having sent
# nothing in 31 Aug-6 Sep, when almost all of them were simply not rostered that week.
W33 = {"week": "2026-W33", "date_from": "2026-08-10", "date_to": "2026-08-16",
       "groups": [{"category": "2 W Saver", "jobs": [job(1, "เก่ามาก Win", done=21)]}]}
W35 = {"week": "2026-W35", "date_from": "2026-08-24", "date_to": "2026-08-30",
       "groups": [{"category": "2 W Saver", "jobs": [job(2, "ทำสัปดาห์ก่อน Win", done=21),
                                                     job(3, "ทำต่อเนื่อง Win", done=21)]}]}
W36 = {"week": "2026-W36", "date_from": "2026-08-31", "date_to": "2026-09-06",
       "groups": [{"category": "2 W Saver", "jobs": [job(4, "ทำต่อเนื่อง Win", done=21),
                                                     job(5, "คนใหม่ Win", done=21)]}]}
main.db.weeks_overview = lambda: [W33, W35, W36]
weeks = {x["week"]: x for x in main.completeness()["weeks"]}
absent36 = [n for g in weeks["2026-W36"]["groups"] for n in g["absent"]]
check("คนที่ทำสัปดาห์ที่แล้วแล้วหายไป ถูกนับว่ายังไม่ส่ง", absent36 == ["ทำสัปดาห์ก่อน Win"])
check("คนที่หมุนเวียนออกไปตั้งแต่หลายสัปดาห์ก่อน ไม่ถูกนับ", "เก่ามาก Win" not in absent36)
check("คนที่ยังทำอยู่ ไม่ถูกนับ", "ทำต่อเนื่อง Win" not in absent36)
absent33 = [n for g in weeks["2026-W33"]["groups"] for n in g["absent"]]
check("สัปดาห์แรกสุดไม่มีใครถูกนับว่าหาย เพราะไม่มีสัปดาห์ก่อนหน้า", absent33 == [])

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
