# -*- coding: utf-8 -*-
"""เลขที่พลิกหัวกลับแล้วยังเป็นเลข และคู่ที่จับมาตอนอ่านผิด (2026-09-12)."""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-flip-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import check_flipped_amounts as chk                             # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


check("66 อาจเป็น 99", chk.flipped(66) == 99)
check("99 อาจเป็น 66", chk.flipped(99) == 66)
check("26 อาจเป็น 97 (เคสวิน 97419329)", chk.flipped(26) == 97)
check("69 อาจเป็น 69 กลับด้าน = 69 → ไม่นับ", chk.flipped(69) is None)   # '69' พลิกแล้วเท่าเดิม
check("88 พลิกแล้วเท่าเดิม ไม่ต้องสงสัย", chk.flipped(88) is None)
check("153 พลิกแล้วไม่เป็นเลข", chk.flipped(153) is None)
check("30 พลิกไม่ได้ (3 ไม่ใช่เลขที่หมุนแล้วอ่านออก)", chk.flipped(30) is None)
check("60 พลิกแล้วขึ้นต้นด้วยศูนย์ ไม่นับ", chk.flipped(60) is None)
check("ยอดทศนิยมไม่นับ", chk.flipped(66.5) is None)
check("ไม่มียอดก็ไม่ล่ม", chk.flipped(None) is None)

check("อ่านยอดจากชื่อไฟล์ที่ pool ต่อให้",
      chk.figure_in_name("2W-Win ป๋อง = 71_86659+86658_฿30.jpg") == 30)
check("รูปที่ไม่ได้ต่อ ไม่มียอดในชื่อ", chk.figure_in_name("S__97419329_0.jpg") is None)

_rows = [
    # จับคู่ตอนเห็น ฿66 แต่รูปที่ต่อแล้วอ่านได้ 99 → คู่นี้ต้องเปิดดู
    {"id": 1, "file_name": "2W-Win วิน = 150_97435676+97435677_฿66.jpg", "net_earnings": 99.0,
     "driver_name": "วิน", "status": "done", "check_status": "fail", "committed": 0,
     "customer_image": None},
    # เลขในชื่อพลิกได้ แต่ทั้งสองทางเห็นตรงกัน → ไม่ต้องดู
    {"id": 2, "file_name": "2W-Win ป๋อง = 71_1+2_฿66.jpg", "net_earnings": 66.0,
     "driver_name": "ป๋อง", "status": "done", "check_status": "pass", "committed": 1,
     "customer_image": "WK37-ป๋อง1.jpg"},
    # ฿153 ไม่เคยโดนพลิก
    {"id": 3, "file_name": "2W-Win ป๋อง = 71_3+4_฿153.jpg", "net_earnings": 150.0,
     "driver_name": "ป๋อง", "status": "done", "check_status": "fail", "committed": 0,
     "customer_image": None},
    # รูปเดี่ยว ไม่ได้มาจากการจับคู่
    {"id": 4, "file_name": "S__97419329_0.jpg", "net_earnings": 26.0, "driver_name": "วิน",
     "status": "done", "check_status": "pass", "committed": 1, "customer_image": "WK37-วิน9.jpg"},
]
_s, _w = chk.scan(_rows)
check("จับได้เฉพาะคู่ที่ยอดขัดกันและเลขพลิกได้", [r["id"] for r in _s] == [1])
check("บอกยอดจริงที่เป็นไปได้", _s[0]["maybe"] == 99)
check("คู่ที่ยอดตรงกันไปอยู่ในกลุ่มเฝ้าดู", [r["id"] for r in _w] == [2])

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
