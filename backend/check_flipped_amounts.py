# -*- coding: utf-8 -*-
"""คู่ที่อาจถูกจับมาตอนตัวอ่านพลิกเลขหัวกลับ — รายงานอย่างเดียว ไม่แก้อะไร (2026-09-12)

ตัวจับมุมของ RapidOCR เคยพลิกบรรทัด '฿ 99' หัวลงก่อนอ่าน เลยได้ 66 (และ '฿ 97' ได้ 26) ปิดไป
แล้วใน pairing.NO_FLIP ส่วนใหญ่ครึ่งบนที่อ่านผิดจะหาคู่ไม่เจอแล้วค้างในกอง ซึ่งไม่เสียหาย แต่ถ้า
บังเอิญมีครึ่งล่างของอีกงานที่ยอด ฿66 จริงๆ วางอยู่ใกล้กัน มันจับคู่กันไปแล้วได้

ตัวจับผิดคู่แบบนั้นคือชื่อไฟล์: ตอนจับคู่ pool เขียนยอดที่สองครึ่งตกลงกันไว้ในชื่อ
('ป๋อง = 71_86659+86658_฿30.jpg') ส่วน net_earnings มาจาก Gemini ที่อ่านรูปที่ต่อแล้วทีหลัง
สองค่านี้ต่างกันเมื่อไหร่ แปลว่าตอนจับคู่เห็นเลขคนละตัวกับที่อยู่บนรูปจริง — ถ้าเลขในชื่อเป็นเลข
ที่พลิกได้ (6↔9, 26 จาก 97) ก็เข้าข่ายเคสนี้เต็มๆ

    python check_flipped_amounts.py --from 2026-09-07 --to 2026-09-13
"""
import argparse
import re
import sys

from sqlalchemy import select

import db

ROTATE = {"0": "0", "1": "1", "6": "9", "8": "8", "9": "6"}
# ฿97 อ่านได้ 26: '7' พลิกแล้วตัวอ่านเห็นเป็น '2' ไม่ใช่การหมุนตรงตัวเหมือน 6/9 จึงระบุเอง
EXTRA = {26.0: 97.0, 62.0: 79.0}
NAME_FIGURE = re.compile(r"฿\s*(\d+(?:\.\d+)?)")


def flipped(amount):
    """ยอดนี้อาจเป็นยอดอื่นที่ถูกพลิกหัวกลับหรือไม่ → ยอดจริงที่เป็นไปได้ หรือ None

    '66' พลิกแล้วคือ '99' · '88' พลิกแล้วเท่าเดิม จึงไม่มีอะไรให้สงสัย · '153' พลิกแล้วไม่เป็นเลข
    ตัวเดามุมจึงไม่เคยพลิกมันตั้งแต่แรก"""
    if amount is None or float(amount) != int(amount) or amount <= 0:
        return None
    if float(amount) in EXTRA:
        return EXTRA[float(amount)]
    s = str(int(amount))
    if any(ch not in ROTATE for ch in s):
        return None
    other = "".join(ROTATE[ch] for ch in reversed(s))
    return None if other == s or other.startswith("0") else float(other)


def figure_in_name(file_name):
    """ยอดที่สองครึ่งตกลงกันตอนจับคู่ ที่ pool เขียนไว้ในชื่อไฟล์ — None ถ้าไม่ใช่รูปที่ต่อมา"""
    m = NAME_FIGURE.search(file_name or "")
    return float(m.group(1)) if m else None


def scan(rows):
    """(น่าสงสัย, เฝ้าดู) — น่าสงสัยคือยอดในชื่อไฟล์เป็นเลขที่พลิกได้ และไม่ตรงกับที่ Gemini อ่าน"""
    suspect, watch = [], []
    for r in rows:
        fig = figure_in_name(r["file_name"])
        if fig is None:
            continue                                  # ไม่ใช่คู่ที่ pool ต่อให้ ไม่เกี่ยวกับเคสนี้
        true_amount = flipped(fig)
        if true_amount is None:
            continue                                  # เลขนี้พลิกแล้วไม่เป็นเลข ไม่เคยโดน
        net = r["net_earnings"]
        (suspect if net is not None and abs(net - fig) > 0.01 else watch).append(
            {**r, "fig": fig, "maybe": true_amount})
    return suspect, watch


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    a = ap.parse_args(argv)

    db.init_db()
    t, j = db.trips.c, db.jobs.c
    with db.engine.begin() as c:
        rows = [dict(r) for r in c.execute(
            select(t.id, t.file_name, t.net_earnings, t.base_fare, t.booking_code, t.status,
                   t.check_status, t.committed, t.customer_image, t.note, t.source_url,
                   j.driver_name, j.category, j.date_from)
            .select_from(db.trips.join(db.jobs, j.id == t.job_id))
            .where(j.date_from >= a.d_from, j.date_from <= a.d_to)).mappings().all()]
    suspect, watch = scan(rows)
    print(f"สัปดาห์ {a.d_from} ถึง {a.d_to} · แถวทั้งหมด {len(rows):,} · "
          f"คู่ที่ยอดในชื่อไฟล์เป็นเลขพลิกได้ {len(suspect) + len(watch):,}")

    if not suspect:
        print("\n✅ ไม่มีคู่ไหนที่ยอดตอนจับคู่ขัดกับยอดที่อ่านได้ — ไม่พบคู่ที่จับผิดจากเลขกลับหัว")
    else:
        print(f"\n⚠ ต้องเปิดรูปดู {len(suspect)} รายการ — ยอดตอนจับคู่ไม่ตรงกับยอดที่ Gemini อ่าน\n")
        print(f"{'id':>6}  {'ไรเดอร์':<14}{'ตอนจับคู่':>10}{'อาจเป็น':>9}{'ที่อ่านได้':>11}  "
              f"{'สถานะ':<10}{'ตรวจ':<7}{'ส่งแล้ว':<8}ไฟล์")
        for r in sorted(suspect, key=lambda x: -(x["fig"] or 0)):
            print(f"{r['id']:>6}  {(r['driver_name'] or '')[:13]:<14}{r['fig']:>10,.0f}"
                  f"{r['maybe']:>9,.0f}{(r['net_earnings'] or 0):>11,.0f}  {r['status']:<10}"
                  f"{(r['check_status'] or '-'):<7}{('ใช่' if r['committed'] else 'ไม่'):<8}"
                  f"{(r['file_name'] or '')[:55]}")
        sent = [r for r in suspect if r["committed"]]
        print(f"\nในนั้นส่งลูกค้าไปแล้ว {len(sent)} รายการ")
        if sent:
            print("รูปที่ส่ง: " + ", ".join(str(r["customer_image"] or r["id"]) for r in sent[:20]))
    if watch:
        print(f"\nอีก {len(watch)} รายการยอดตรงกันทั้งสองทาง — ทั้งสองครึ่งเห็นเลขเดียวกัน ไม่ต้องดู")
    return 0


if __name__ == "__main__":
    sys.exit(main())
