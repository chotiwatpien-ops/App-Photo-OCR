# -*- coding: utf-8 -*-
"""A customer picture keeps the number it was delivered under (Ops, 2026-09-09).

Numbering used to be recomputed from the date order on every round, so one trip added to a
rider who was already finished pushed every later trip up one — and the round rebuilt and
re-uploaded all twenty-one files. Run #141 spent forty minutes doing that for about sixty
riders. Now an existing name is kept and new work takes the numbers after it; the trade is
that the numbers no longer run strictly in date order, which is why the old behaviour is one
setting away.
"""
import io
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-num-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from PIL import Image                                           # noqa: E402

import config                                                   # noqa: E402
import db                                                       # noqa: E402
import pipeline                                                 # noqa: E402
import stitch                                                   # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


db.init_db()


def jpeg(colour=(200, 200, 200)):
    b = io.BytesIO()
    Image.new("RGB", (60, 120), colour).save(b, "JPEG")
    return b.getvalue()


def make_job(rows):
    """rows = [(file_name, trip_date)] -> job id, every row 'done' with a blob."""
    jid = db.create_job("ก", "Trips", "2026-08-31", "2026-09-06", category="2 W Saver")
    for fn, d in rows:
        tid = db.create_trip(jid, fn, jpeg(), "image/jpeg")
        db.update_trip(tid, {"status": "done", "trip_date": d})
    return jid


WK = "WK36"

# --- a first delivery numbers by date, exactly as before ---------------------------------------
j1 = make_job([("a.jpg", "2026-09-01"), ("b.jpg", "2026-09-03"), ("c.jpg", "2026-09-05")])
first = [n for n, _ in pipeline.customer_images(j1, "ก")]
check("รอบแรก: เรียงตามวันที่ 1-2-3",
      first == [stitch.customer_name("ก", i, WK) for i in (1, 2, 3)])

# nothing changed: nothing is remade
check("กดซ้ำโดยไม่มีอะไรเปลี่ยน → ไม่สร้างอะไรเลย", list(pipeline.customer_images(j1, "ก")) == [])

# --- a trip added in the MIDDLE of the week takes the next free number, not the middle one -----
tid = db.create_trip(j1, "b2.jpg", jpeg(), "image/jpeg")
db.update_trip(tid, {"status": "done", "trip_date": "2026-09-02"})
added = list(pipeline.customer_images(j1, "ก"))
check("งานที่แทรกกลางสัปดาห์: สร้างแค่ใบเดียว", len(added) == 1)
check("และได้เลขต่อท้าย (4) ไม่ใช่เลข 2", added[0][0] == stitch.customer_name("ก", 4, WK))
names = {r["file_name"]: r["customer_image"] for r in db.trips_with_images(j1)}
check("ของเดิมสามใบไม่ถูกเปลี่ยนชื่อ",
      [names["a.jpg"], names["b.jpg"], names["c.jpg"]]
      == [stitch.customer_name("ก", i, WK) for i in (1, 2, 3)])

# --- the old behaviour is one setting away -----------------------------------------------------
config.CUSTOMER_IMAGE_NUMBERING = "bydate"
j2 = make_job([("a.jpg", "2026-09-01"), ("c.jpg", "2026-09-05")])
list(pipeline.customer_images(j2, "ข"))
t2 = db.create_trip(j2, "b.jpg", jpeg(), "image/jpeg")
db.update_trip(t2, {"status": "done", "trip_date": "2026-09-03"})
again = [n for n, _ in pipeline.customer_images(j2, "ข")]
check("โหมด bydate: แทรกกลางแล้วเรียงใหม่ทั้งชุด (พฤติกรรมเดิม)",
      sorted(again) == sorted(stitch.customer_name("ข", i, WK) for i in (2, 3)))
config.CUSTOMER_IMAGE_NUMBERING = "append"

# --- a rider renamed must not keep a file name that says somebody else -------------------------
j3 = make_job([("a.jpg", "2026-09-01")])
list(pipeline.customer_images(j3, "ค"))
renamed = [n for n, _ in pipeline.customer_images(j3, "ค-แอดมินบี")]
check("เปลี่ยนชื่อที่แสดง → ตั้งชื่อใหม่ ไม่ยึดชื่อเดิมของคนอื่น",
      renamed == [stitch.customer_name("ค-แอดมินบี", 1, WK)])
check("ชื่อของคนอื่นไม่ถูกนับเป็นเลขที่ใช้แล้ว", pipeline._number_in("WK36-คนอื่น7.jpg", "ค", WK) is None)
check("ชื่อของตัวเองอ่านเลขได้", pipeline._number_in(stitch.customer_name("ค", 7, WK), "ค", WK) == 7)
check("ชื่อที่ไม่ใช่รูปส่งลูกค้าเลย → None", pipeline._number_in("S__12345.jpg", "ค", WK) is None)
check("ไม่มีชื่อ → None", pipeline._number_in(None, "ค", WK) is None)

# --- a forced rebuild remakes the same files under the same names ------------------------------
j4 = make_job([("a.jpg", "2026-09-01"), ("b.jpg", "2026-09-02")])
before = [n for n, _ in pipeline.customer_images(j4, "ง")]
forced = [n for n, _ in pipeline.customer_images(j4, "ง", only_missing=False)]
check("สั่งสร้างใหม่ทั้งหมด: ได้ไฟล์เดิม ชื่อเดิม", forced == before and len(forced) == 2)

# --- a number freed by a voided trip is used again, so the customer gets no gap ----------------
# The voided trip's picture is still sitting on Drive under that name; uploading the new one
# over it is what takes it away. A gap would leave the stale file there for good.
j5 = make_job([("a.jpg", "2026-09-01"), ("b.jpg", "2026-09-02"), ("c.jpg", "2026-09-03")])
list(pipeline.customer_images(j5, "จ"))
mid = [r for r in db.trips_with_images(j5) if r["file_name"] == "b.jpg"][0]
db.update_trip(mid["id"], {"status": "voided"})
t5 = db.create_trip(j5, "d.jpg", jpeg(), "image/jpeg")
db.update_trip(t5, {"status": "done", "trip_date": "2026-09-04"})
after = [n for n, _ in pipeline.customer_images(j5, "จ")]
check("ทริปที่ถูกยกเลิกคืนเลขให้ใบใหม่ (ทับไฟล์เก่าบน Drive ไม่เหลือรูที่ลูกค้าเห็น)",
      after == [stitch.customer_name("จ", 2, WK)])
check("และใบที่เหลือยังชื่อเดิม",
      [r["customer_image"] for r in sorted(db.trips_with_images(j5), key=lambda r: r["file_name"])
       if r["file_name"] in ("a.jpg", "c.jpg")]
      == [stitch.customer_name("จ", 1, WK), stitch.customer_name("จ", 3, WK)])

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
