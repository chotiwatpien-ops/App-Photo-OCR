# -*- coding: utf-8 -*-
"""ใบตรวจท้ายรอบ: ยอดต่อประเภทงาน · รูปส่งลูกค้าขาด/ชื่อซ้ำ · ครึ่งบนกับครึ่งล่างไม่ตรงกัน (2026-09-17)

W37 ถูกอ่านทะลุเป้า 1,470 ไปสองครั้ง (1,502 แล้ว 1,482) และทั้งสองครั้งคนไปเจอเองทีหลังหลายชั่วโมง
กฎยอดเขียว (คุณได้รับ = ค่าโดยสาร + โบนัส + เทอร์โบ) จริงกับ 4,399 จาก 4,410 แถวของ W37
ที่เหลือสิบแถวเป็นคู่ที่จับผิดหรืออ่านเลขคลาด
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-card-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from sqlalchemy import insert                                    # noqa: E402

import db                                                        # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


W, WE = "2026-09-07", "2026-09-13"
job = db.create_job("สมชาย Win", "Trips", W, WE, category="2 W Standard")
car = db.create_job("สมหมาย Taxi", "Trips", W, WE, category="4 W Standard")


def add(jid, name, svc, status="done", pic=None, net=50, base=50, bonus=0, turbo=0, tolls=0):
    with db.engine.begin() as c:
        return c.execute(insert(db.trips).values(
            job_id=jid, file_name=name, status=status, service_type=svc, customer_image=pic,
            net_earnings=net, base_fare=base, bonus=bonus, turbo=turbo, tolls=tolls,
            committed=1)).inserted_primary_key[0]


add(job, "a.jpg", "Standard Bike", pic="WK37-สมชาย Win1.jpg")
add(job, "b.jpg", "Standard Bike", pic="WK37-สมชาย Win2.jpg", net=70, base=50, bonus=20)   # ตรงกฎ
add(job, "c.jpg", "Standard Bike", pic="WK37-สมชาย Win2.jpg")                              # ชื่อรูปซ้ำ
add(job, "d.jpg", "Standard Bike", pic=None)                                               # ไม่มีรูป
bad = add(job, "e.jpg", "Standard Bike", pic="WK37-สมชาย Win3.jpg", net=285, base=380)      # ครึ่งไม่ตรง
add(car, "f.jpg", "Standard Car", pic="WK37-สมหมาย Taxi1.jpg", net=250, base=160, tolls=90)  # จ่ายคืน
add(car, "g.jpg", "Standard Car", status="error", pic=None)
add(car, "h.jpg", "Standard Car", status="pending", pic=None)
add(car, "i.jpg", "Standard Car", status="duplicate", pic="WK37-สมหมาย Taxi2.jpg")

card = db.week_scorecard(W, WE, target=5)
check("นับเฉพาะแถวที่ลงไฟล์แล้วแยกตามประเภทงาน",
      card["by_service"] == {"Standard Bike": 5, "Standard Car": 1})
check("บอกกลุ่มที่ยังขาดเป้า", card["under"].get("Standard Car") == 4 and "Standard Bike" not in card["under"])
check("กลุ่มที่ครบเป้าพอดี ไม่ขึ้นทั้งขาดและเกิน",
      "Standard Bike" not in card["under"] and "Standard Bike" not in card["over"])
check("นับแถวที่ไม่มีรูปส่งลูกค้า", card["no_picture"] == 1)
check("นับแถวที่ใช้ชื่อรูปซ้ำกับแถวอื่น", card["shared_picture"] == 1)
check("นับแถว error กับ pending แยกกัน", (card["error"], card["pending"]) == (1, 1))
check("ครึ่งบน/ครึ่งล่างไม่ตรงกัน: จับได้เฉพาะแถวที่ผิดจริง",
      [i for i, _d in card["halves_disagree"]] == [bad])
check("ผลต่างบอกมาด้วย เพื่อดูว่าจับคู่ผิดหรืออ่านคลาด", card["halves_disagree"][0][1] == -95)
check("ค่าทางด่วนที่จ่ายคืน ไม่ถือว่าผิดกฎ",
      all(i != 0 for i, _d in card["halves_disagree"]) and len(card["halves_disagree"]) == 1)

card2 = db.week_scorecard(W, WE, target=1)
check("เป้าเล็กกว่าที่มี → ขึ้นเป็นกลุ่มที่เกินเป้า", card2["over"].get("Standard Bike") == 4)

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
