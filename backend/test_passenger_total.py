# -*- coding: utf-8 -*-
"""passenger_total must always be the passenger's FARE, never the receipt total.

The pre-2026 trip screen prints two cards; the second one ('ค่าธรรมเนียมของผู้โดยสาร') adds the
app fee, tip, tolls and international fee on top of the fare. Reading its Total as the fare
overstated 43 rows in W33-W35 by up to ฿235. Every case below is a real slip from that audit
or a real new-screen row that must NOT be touched.
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "backend")
import extractor                                                  # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


def fare(d):
    return extractor.fix_passenger_total(dict(d)).get("passenger_total")


# --- หน้าจอเก่า: ต้องแก้ ------------------------------------------------------------------
# WK33-สรธร4: การ์ดค่าบริการบอก 327/245/82 แต่ใบเสร็จรวม 417 (บวกค่าแอป 20 + ทางด่วน 70)
sorathorn4 = {"base_fare": 245, "grab_commission": 82, "passenger_total": 417,
              "passenger_paid": None, "app_fee": 20, "tolls": 70, "tip": 0, "intl_fee": 0}
check("สรธร4: 417 → 327 (การ์ดค่าบริการเป็นตัวตัดสิน)", fare(sorathorn4) == 327)

# เคสเดียวกันแต่ไม่มีค่าบริการที่แกร็บได้รับให้เทียบ — ยังประกอบกลับได้จากค่าโดยสารพื้นฐาน
no_cut = dict(sorathorn4, grab_commission=None)
check("สรธร4 ไม่มีค่าบริการแกร็บ: ยังได้ 327", fare(no_cut) == 327)

# WK33-สมปอง13: ใบเสร็จ 115 = ค่าโดยสาร 72 + ค่าแอป 20 + ทิป 20 + ต่างประเทศ 3
sompong13 = {"base_fare": 54, "grab_commission": 18, "passenger_total": 115,
             "passenger_paid": 72, "app_fee": 20, "tolls": 0, "tip": 20, "intl_fee": 3}
check("สมปอง13: 115 → 72", fare(sompong13) == 72)
check("สมปอง13: บอกไว้ใน confidence_note",
      "72" in (extractor.fix_passenger_total(dict(sompong13)).get("confidence_note") or ""))

# ยอดที่ชำระอ่านได้ แต่ไม่มีค่าบริการแกร็บ — ยังจับได้จากส่วนต่างที่ลงตัวพอดี
paid_only = dict(sompong13, grab_commission=None)
check("มีแต่ยอดที่ชำระ: 115 → 72", fare(paid_only) == 72)

# WK33-สรธร7: ใบเสร็จ 860, ค่าโดยสารจริง 625 (ค่าแอป 20 + ทิป 60 + ทางด่วน 155)
sorathorn7 = {"base_fare": 469, "grab_commission": 156, "passenger_total": 860,
              "passenger_paid": 625, "app_fee": 20, "tolls": 155, "tip": 60, "intl_fee": 0}
check("สรธร7: 860 → 625", fare(sorathorn7) == 625)

# --- หน้าจอใหม่: ห้ามแตะ ------------------------------------------------------------------
# WK33-ประพันธ์1: 262 − 20 + 79 = 321 — ค่าธรรมเนียมแอปเป็นลบ อยู่ในยอดรวมอยู่แล้ว
prapan1 = {"base_fare": 241, "grab_commission": 80, "passenger_total": 321,
           "passenger_paid": 262, "app_fee": -20, "other_adjustments": 79,
           "tolls": 0, "tip": 0, "intl_fee": 0}
check("ประพันธ์1 (จอใหม่ มีส่วนลด): คงไว้ที่ 321", fare(prapan1) == 321)

# Saver Bike จอใหม่: 48 − 1 = 47, ค่าบริการแกร็บ 2
saver = {"base_fare": 45, "grab_commission": 2, "passenger_total": 47, "passenger_paid": 48,
         "app_fee": -1, "tolls": 0, "tip": 0, "intl_fee": 0}
check("Saver Bike จอใหม่: คงไว้ที่ 47", fare(saver) == 47)

# ทิปบนจอใหม่อยู่ในรายได้คนขับ ไม่ได้บวกในยอดผู้โดยสาร — ห้ามหักออก
new_tip = {"base_fare": 100, "grab_commission": 17, "passenger_total": 117, "passenger_paid": 118,
           "app_fee": -1, "tolls": 0, "tip": 30, "intl_fee": 0}
check("จอใหม่ที่คนขับได้ทิป: คงไว้ที่ 117", fare(new_tip) == 117)

# ทางด่วนบนจอใหม่ก็เป็นเงินคืนคนขับ ไม่ใช่ส่วนหนึ่งของค่าโดยสาร
new_tolls = {"base_fare": 200, "grab_commission": 50, "passenger_total": 250, "passenger_paid": 270,
             "app_fee": -20, "tolls": 70, "tip": 0, "intl_fee": 0}
check("จอใหม่ที่มีทางด่วน: คงไว้ที่ 250", fare(new_tolls) == 250)

# ค่าธุรกรรมต่างประเทศบนจอใหม่อยู่ในยอดค่าโดยสารอยู่แล้ว — เคยโดนหักผิดไป 65 แถว
# (WK33-ทำนอง16: base 111 · ยอดรวม 146 · ตปท 4 — อัตราค่าบริการ 32% ยังปกติ)
intl_new = {"base_fare": 111, "grab_commission": None, "passenger_total": 146,
            "passenger_paid": 142, "app_fee": -20, "tolls": 0, "tip": 0, "intl_fee": 4}
check("ทำนอง16 (จอใหม่ มีค่าต่างประเทศ): คงไว้ที่ 146", fare(intl_new) == 146)

# แบบเดียวกันแต่ค่าธรรมเนียมแอปอ่านมาเป็นบวก (Saver Bike เครื่องหมายหาย) — ก็ยังห้ามหัก
intl_sign = {"base_fare": 97, "grab_commission": None, "passenger_total": 118,
             "passenger_paid": 115, "app_fee": 1, "tolls": 0, "tip": 0, "intl_fee": 3}
check("ธีรศักดิ์14 (เครื่องหมายค่าแอปหาย): คงไว้ที่ 118", fare(intl_sign) == 118)

check("อัตราเกิน 35% ถือว่าผิดปกติ", extractor.implausible(146, 100))
check("อัตรา 30% ยังปกติ", not extractor.implausible(130, 100))

# --- ไม่ชัวร์ = ไม่แตะ --------------------------------------------------------------------
# ตัวเลขขัดกันโดยอธิบายไม่ได้ (ส่วนต่าง 60 ไม่เท่ากับส่วนเสริม 20) — ปล่อยให้คนตรวจ
unexplained = {"base_fare": 100, "grab_commission": 20, "passenger_total": 180,
               "passenger_paid": None, "app_fee": 20, "tolls": 0, "tip": 0, "intl_fee": 0}
check("ขัดกันแบบอธิบายไม่ได้: ไม่แก้", fare(unexplained) == 180)

check("ไม่มียอดผู้โดยสารเลย: ไม่แก้", fare({"base_fare": 100, "passenger_total": None}) is None)

# อัตราค่าบริการยังสมเหตุสมผลอยู่ — ไม่ใช่หน้าจอเก่า ห้ามหักส่วนเสริมทิ้ง
plausible = {"base_fare": 100, "grab_commission": None, "passenger_total": 125,
             "passenger_paid": None, "app_fee": 20, "tolls": 0, "tip": 0, "intl_fee": 0}
check("ค่าบริการ 25% ปกติดี: ไม่แก้", fare(plausible) == 125)

check("ส่วนเสริมของใบเสร็จ = ค่าแอป(บวก)+ทิป+ทางด่วน+ต่างประเทศ",
      extractor.receipt_extras(sompong13) == 43)
check("ค่าแอปติดลบ (จอใหม่) ไม่นับเป็นส่วนเสริม", extractor.receipt_extras(prapan1) == 0)

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
