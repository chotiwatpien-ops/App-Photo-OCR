# -*- coding: utf-8 -*-
"""คู่ที่คนเปิดดูแล้วยืนยัน (2026-09-14): ตัวอ่านทิ้งไว้เพราะส่งครึ่งล่างก่อน / นาฬิกาอ่านผิด /
ยอดครึ่งบน = รายได้ + เงินเพิ่ม — สั่งจับตามรายชื่อได้ แต่ต้องไม่ไปแตะคู่ที่ตัวอ่านจับไว้แล้ว"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "backend")

import pairing                                                  # noqa: E402
import pool                                                     # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


f = pool.parse_forced("2W-Win Panupong|91757_0.jpg|91756_0.jpg|51 ; 4W-Taxi นฤมล = 359|a.jpg|b.jpg|฿1,367;"
                      "ขาดช่อง|x.jpg|12;ยอดไม่ใช่ตัวเลข|x.jpg|y.jpg|abc")
check("อ่านรายชื่อคู่ได้ (ชื่ออัลบั้มมีช่องว่าง/เครื่องหมาย =)",
      f == {"2W-Win Panupong": [("91757_0.jpg", "91756_0.jpg", 51.0)],
            "4W-Taxi นฤมล = 359": [("a.jpg", "b.jpg", 1367.0)]})
check("ว่าง = ไม่มีคู่สั่งเอง", pool.parse_forced("") == {} and pool.parse_forced(None) == {})

# ตัวอ่านจริงถูกแทนด้วยผลที่รู้อยู่แล้ว — ทดสอบเฉพาะการตัดสินใจของ analyse
INFO = {
    # ตัวเลขที่ตัวอ่านเก็บได้จากครึ่งล่างไม่พอให้จับเอง (ของจริงก็ค้างแบบนี้)
    "91756_0.jpg": {"role": "bottom", "amount": None, "numbers": [5, 36], "seq": [], "clock": 885},
    "91757_0.jpg": {"role": "top", "amount": 51.0, "clock": 885},
    "1.jpg": {"role": "top", "amount": 40.0, "clock": 600},
    "2.jpg": {"role": "bottom", "amount": 40.0, "numbers": [40], "seq": [], "clock": 600},
}
for v in INFO.values():
    v.update(theme="สว่าง", width=858, height=1907)
pairing.inspect = lambda src: dict(INFO[src.decode()])
pairing.vehicle_type = lambda src: ("2W", "Standard")

albums = [{"week": "Week 7-13 Sep", "group": "2W", "album": "2W-Win Panupong", "pool_id": "p",
           "images": [{"id": n, "name": n} for n in INFO]}]
data = {n: n.encode() for n in INFO}
forced = {"2W-Win Panupong": [("91757_0.jpg", "91756_0.jpg", 51.0),     # ค้างอยู่ทั้งคู่ → จับ
                              ("1.jpg", "91756_0.jpg", 99.0),           # 1.jpg ตัวอ่านจับไปแล้ว → ไม่แตะ
                              ("ไม่มีไฟล์นี้.jpg", "2.jpg", 10.0)]}
rep = pool.analyse(albums, data, 1, cache={}, forced=forced)
a = rep["albums"][0]
pairs = {(p["top"], p["bottom"]): p for p in a["pairs"]}
check("คู่ที่ตัวอ่านจับได้เองยังอยู่เหมือนเดิม", ("1.jpg", "2.jpg") in pairs and not pairs[("1.jpg", "2.jpg")].get("by_hand"))
check("คู่ที่สั่งเองถูกจับ ใช้ยอดที่คนยืนยัน", pairs.get(("91757_0.jpg", "91756_0.jpg"), {}).get("amount") == 51.0
      and pairs[("91757_0.jpg", "91756_0.jpg")].get("by_hand"))
check("ไม่มีครึ่งไหนค้างแล้ว", a["leftovers"] == [])
check("สั่งจับใบที่ตัวอ่านจับไปแล้ว → ไม่แตะ และบอกในปัญหา",
      len(a["pairs"]) == 2 and sum("สั่งจับคู่เอง" in e for e in rep["errors"]) == 2)
check("รายงานบอกว่าคู่ไหนสั่งเอง", "[สั่งจับคู่เอง]" in pool.render({**rep, "totals": {**rep["totals"]}}))
check("ไม่สั่งอะไร = ผลเหมือนเดิมทุกอย่าง",
      len(pool.analyse(albums, data, 1, cache={})["albums"][0]["pairs"]) == 1)

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
