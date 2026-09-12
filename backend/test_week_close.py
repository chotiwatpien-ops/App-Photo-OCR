# -*- coding: utf-8 -*-
"""ปิดสัปดาห์แล้วงานอัตโนมัติต้องไม่แตะสัปดาห์นั้นอีก (2026-09-13).

รอบ #210 เดินเข้าไปใน W36 ที่ส่งลูกค้าไปแล้ว และจะย้ายรูปซ้ำ 165 ใบออกจากโฟลเดอร์ไรเดอร์ เพดาน
กันไว้ทัน แต่คำตอบที่ถูกคือไม่ควรไปมองตั้งแต่แรก ปฏิทินบอกไม่ได้ว่าสัปดาห์ไหนจบ — งานของสัปดาห์
หนึ่งทำต่ออีกหลายวันหลังวันอาทิตย์ คนจึงเป็นคนกดปิด
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-wk-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import db                                                       # noqa: E402
import free_dup_seats as fds                                    # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


W36, W36_END = "2026-08-31", "2026-09-06"
W37, W37_END = "2026-09-07", "2026-09-13"

check("ยังไม่มีใครกดปิด ทุกสัปดาห์เปิดหมด",
      fds.week_is_open(W36, W36_END, today="2026-09-13")
      and fds.week_is_open(W37, W37_END, today="2026-09-13"))
check("ปิดสัปดาห์ได้", db.close_week(W36, W36_END, by="ทดสอบ"))
check("กดปิดซ้ำไม่พัง แค่บอกว่าปิดอยู่แล้ว", db.close_week(W36, W36_END) is False)
check("ถามตรง ๆ ว่าปิดยัง", db.week_closed(W36) and not db.week_closed(W37))
check("สัปดาห์ที่ปิดแล้ว = ไม่เปิด", not fds.week_is_open(W36, W36_END, today="2026-09-13"))
check("สัปดาห์ที่ยังไม่ปิด ไม่ถูกกระทบ", fds.week_is_open(W37, W37_END, today="2026-09-13"))
check("รายชื่อสัปดาห์ที่ปิดมีเวลาที่กดไว้ด้วย",
      W36 in db.closed_weeks() and db.closed_weeks()[W36]["closed_at"])

# ส่ง set เข้ามาเองได้ เพื่อไม่ต้องถามฐานข้อมูลซ้ำทุกสัปดาห์ในรอบเดียว
check("ส่งรายชื่อที่ปิดแล้วเข้ามาเองได้", not fds.week_is_open(W37, W37_END, closed={W37}))

# ตาข่ายกันพลาด: ไม่มีใครกดปิดเลย แต่สัปดาห์เก่ามาก ๆ ต้องไม่ถูกแตะตลอดกาล
check(f"สัปดาห์ที่จบไปเกิน {fds.STALE_DAYS} วัน ถือว่าจบ แม้ไม่มีใครกด",
      not fds.week_is_open("2026-07-06", "2026-07-12", closed=set(), today="2026-09-13"))
check("จบไปไม่นาน ยังเปิดอยู่ ถ้าไม่มีใครกดปิด",
      fds.week_is_open("2026-09-01", "2026-09-06", closed=set(), today="2026-09-13"))
check("ไม่รู้วันจบ และไม่มีใครกดปิด → ยังเปิด (ไม่เดา)",
      fds.week_is_open("2026-09-07", None, closed=set(), today="2026-09-13"))

check("เปิดสัปดาห์ใหม่ได้", db.reopen_week(W36) and fds.week_is_open(W36, W36_END, today="2026-09-13"))
check("เปิดสัปดาห์ที่ไม่ได้ปิดไว้ ไม่พัง", db.reopen_week("2026-01-01") is False)

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
