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


DAYS = ["2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03",
        "2026-09-04", "2026-09-05", "2026-09-06"]


def day_counts(ts):
    from collections import Counter
    return Counter(t["trip_date"] for t in ts)


def trip(i, who, day, svc="Saver Bike"):
    return {"id": i, "driver_name": who, "trip_date": day, "service_type": svc,
            "file_name": f"{i}.jpg"}


# มานิตย์ carries two full folders, six trips on each of seven days; ก has exactly the quota
rows = ([trip(i, "มานิตย์ Home", DAYS[i % 7]) for i in range(1, 43)]
        + [trip(100 + i, "ก Win", DAYS[0]) for i in range(21)]
        + [trip(200 + i, "ข Win", DAYS[0]) for i in range(15)])
p = rq.plan(rows, 21)
check("จับเฉพาะคนที่เกิน", set(p) == {"มานิตย์ Home"})
check("เก็บ 21 เอาออก 21", (len(p["มานิตย์ Home"]["keep"]), len(p["มานิตย์ Home"]["release"])) == (21, 21))
check("คนที่พอดี 21 ไม่ถูกแตะ", "ก Win" not in p)
check("คนที่ยังไม่เต็มก็ไม่ถูกแตะ", "ข Win" not in p)

# the whole point of the rule: a rider who worked every day still works every day
kept_days = day_counts(p["มานิตย์ Home"]["keep"])
check(f"วันทำงานครบเจ็ดวันเหมือนเดิม (ได้ {sorted(kept_days.values())})", len(kept_days) == 7)
check("และแบ่งเท่ากันวันละ 3", set(kept_days.values()) == {3})

# an uneven week keeps its shape: 4,5,5,6,6,6,6 = 38 thins to 21 without emptying any day
uneven = []
i = 0
for d, n in zip(DAYS, (4, 5, 5, 6, 6, 6, 6)):
    for _ in range(n):
        i += 1
        uneven.append(trip(i, "ภุชงค์ Home", d))
pu = rq.plan(uneven, 21)["ภุชงค์ Home"]
kd = day_counts(pu["keep"])
check(f"สัปดาห์ที่ไม่เท่ากันก็ไม่มีวันไหนกลายเป็นศูนย์ (ได้ {[kd[d] for d in DAYS]})",
      len(kd) == 7 and min(kd.values()) >= 1)
# proportional, so a day that did more keeps more — never the other way round
before = dict(zip(DAYS, (4, 5, 5, 6, 6, 6, 6)))
pairs = sorted((before[d], kd[d]) for d in DAYS)          # by how busy the day was
check("วันที่ทำมากกว่า ต้องไม่เหลือน้อยกว่า",
      all(a[1] <= b[1] for a, b in zip(pairs, pairs[1:])))
check("ปัดเศษแล้วต่างจากสัดส่วนจริงไม่เกินหนึ่ง",
      all(abs(kd[d] - 21 * before[d] / 38) < 1 for d in DAYS))
check("เก็บ 21 เอาออก 17", (len(pu["keep"]), len(pu["release"])) == (21, 17))

# and the old rule's failure is the thing this must never do again
first21 = sorted(uneven, key=lambda t: (t["trip_date"], t["id"]))[:21]
check("กฎเก่า 'เก็บ 21 ใบแรก' ทำให้บางวันเป็นศูนย์ — กฎใหม่ต้องไม่เป็นแบบนั้น",
      len(day_counts(first21)) < 7 and len(kd) == 7)

# the answer cannot depend on what order the rows arrived in
check("ผลเหมือนเดิมไม่ว่าแถวจะมาลำดับไหน",
      [t["id"] for t in rq.plan(list(reversed(rows)), 21)["มานิตย์ Home"]["keep"]]
      == [t["id"] for t in p["มานิตย์ Home"]["keep"]])

free = rq.room(rows, 21, p)
check("นับที่ว่างเฉพาะคนที่ยังไม่เต็ม", free == {"ข Win": 6})
check("คนที่เกินไม่ถูกนับเป็นที่ว่าง", "มานิตย์ Home" not in free)

# a rider exactly one over still gets handled, and the tier split is reported as it is
rows3 = [trip(i, "ค Home", DAYS[i % 7], "Standard Bike" if i % 2 else "Saver Bike")
         for i in range(1, 23)]
p3 = rq.plan(rows3, 21)
check("เกินแค่ใบเดียวก็ต้องเห็น", len(p3["ค Home"]["release"]) == 1)
check("รายงานแยกตามบริการได้", "Saver Bike" in rq.tiers(p3["ค Home"]["keep"]))

check("ไม่มีใครเกินก็ตอบว่าไม่มี", rq.plan([trip(1, "ง Win", DAYS[0])], 21) == {})

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
