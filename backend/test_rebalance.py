# -*- coding: utf-8 -*-
"""Who is over the weekly quota, which of their trips go, and is there anywhere to put them.

The four riders found in 31 Aug-6 Sep were each carrying two full folders' worth because the old
allocator counted the quota against the folder. Choosing which trips to release cannot be done by
hand — the rule has to be written down and repeatable, or nobody can check afterwards whose work
was taken away.
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-rebal-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import rebalance_quota as rq                                     # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


def trip(i, who, day, svc="Saver Bike"):
    return {"id": i, "driver_name": who, "trip_date": day, "service_type": svc,
            "file_name": f"{i}.jpg"}


# มานิตย์ carries two full folders; ก has exactly the quota; ข is short
rows = ([trip(i, "มานิตย์ Home", f"2026-09-0{1 + i % 6}") for i in range(1, 43)]
        + [trip(100 + i, "ก Win", "2026-09-01") for i in range(21)]
        + [trip(200 + i, "ข Win", "2026-09-01") for i in range(15)])
p = rq.plan(rows, 21)
check("จับเฉพาะคนที่เกิน", set(p) == {"มานิตย์ Home"})
check("เก็บ 21 เอาออก 21", (len(p["มานิตย์ Home"]["keep"]), len(p["มานิตย์ Home"]["release"])) == (21, 21))
check("คนที่พอดี 21 ไม่ถูกแตะ", "ก Win" not in p)
check("คนที่ยังไม่เต็มก็ไม่ถูกแตะ", "ข Win" not in p)

# the rule is 'the first trips of the week stay', and it has to hold whatever order they arrive in
shuffled = list(reversed(rows))
p2 = rq.plan(shuffled, 21)
kept = [t["id"] for t in p2["มานิตย์ Home"]["keep"]]
kept_again = [t["id"] for t in rq.plan(rows, 21)["มานิตย์ Home"]["keep"]]
check("ผลเหมือนเดิมไม่ว่าแถวจะมาลำดับไหน", kept == kept_again)
early = min(t["trip_date"] for t in p2["มานิตย์ Home"]["keep"])
late = max(t["trip_date"] for t in p2["มานิตย์ Home"]["release"])
check("ที่เก็บไว้คือของต้นสัปดาห์", early <= late)

free = rq.room(rows, 21, p)
check("นับที่ว่างเฉพาะคนที่ยังไม่เต็ม", free == {"ข Win": 6})
check("คนที่เกินไม่ถูกนับเป็นที่ว่าง", "มานิตย์ Home" not in free)

# a rider exactly one over still gets handled, and the tier split is reported as it is
rows3 = [trip(i, "ค Home", "2026-09-01", "Standard Bike" if i % 2 else "Saver Bike")
         for i in range(1, 23)]
p3 = rq.plan(rows3, 21)
check("เกินแค่ใบเดียวก็ต้องเห็น", len(p3["ค Home"]["release"]) == 1)
check("รายงานแยกตามบริการได้", "Saver Bike" in rq.tiers(p3["ค Home"]["keep"]))

check("ไม่มีใครเกินก็ตอบว่าไม่มี", rq.plan([trip(1, "ง Win", "2026-09-01")], 21) == {})

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
