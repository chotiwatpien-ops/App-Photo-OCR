# -*- coding: utf-8 -*-
"""Who is over the weekly quota, which of their trips go, and is there anywhere to put them.

The four riders found in 31 Aug-6 Sep were each carrying two full folders' worth because the old
allocator counted the quota against the folder. Choosing which trips to release cannot be done by
hand — the rule has to be written down and repeatable, or nobody can check afterwards whose work
was taken away.
"""
import io
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

# --- handing the released trips to somebody else ----------------------------------------------
import distribute                                                # noqa: E402
import numpy as _np                                              # noqa: E402
from PIL import Image as _Image                                  # noqa: E402


def _png(level):
    b = io.BytesIO()
    _Image.fromarray(_np.full((40, 20, 3), level, dtype="uint8")).save(b, "PNG")
    return b.getvalue()


print("สไตล์รูปอ่านจากชื่อไฟล์กับความสว่าง:")
check("รูปที่เราต่อเอง = ครึ่ง", rq.style_of("2W-Home_188+187_฿32.jpg", _png(240)) == "ครึ่ง/สว่าง")
check("รูปที่ Ops รวมมา = ยาว", rq.style_of("47825_47826.jpg", _png(240)) == "ยาว/สว่าง")
check("ธีมมืดอ่านออก", rq.style_of("47825_47826.jpg", _png(30)) == "ยาว/มืด")
check("ชื่อที่มีเลขแต่ไม่ใช่รูปแบบของเรา ก็ยังเป็นยาว",
      rq.style_of("LINE_ALBUM_x_260828_85.jpg", _png(240)) == "ยาว/สว่าง")


class FakeDrive:
    def __init__(self):
        self.tree, self.images = {"week": {}}, {}

    def ensure_folder(self, pid, name):
        fid = f"{pid}/{name}"
        self.tree.setdefault(pid, {})[name] = fid
        self.tree.setdefault(fid, {})
        self.images.setdefault(fid, 0)
        return fid

    def list_folders(self, pid):
        return [{"id": v, "name": k} for k, v in self.tree.get(pid, {}).items()]

    def list_images(self, pid):
        n = self.images.get(pid, 0)
        return n if isinstance(n, list) else [None] * n

    def move_file(self, fid, new_parent):
        for pid, n in list(self.images.items()):
            if isinstance(n, list):
                self.images[pid] = [f for f in n if f["id"] != fid]
        self.images[new_parent] = self.images.get(new_parent, 0) + 1


POOL = {("2W", "Win"): [f"วิน{i}" for i in range(1, 21)],
        ("2W", "Home"): [f"บ้าน{i}" for i in range(1, 11)],
        ("4W", "Taxi"): ["ท"], ("4W", "Home"): ["ห"]}

print("เลือกเจ้าของใหม่:")
d = FakeDrive()
alloc = distribute.Allocator(d, "week", POOL, per_rider=21, seed=1)
fid, cat, err = rq.find_new_home(alloc, {"service_type": "Saver Bike", "style": "ยาว/มืด"})
check("Saver Bike ไปกลุ่ม 2 W Saver", cat == "2 W Saver" and not err)
fid2, cat2, _ = rq.find_new_home(alloc, {"service_type": "Standard Bike", "style": "ยาว/มืด"})
check("Standard Bike ไปกลุ่ม 2 W Standard", cat2 == "2 W Standard")
check("คนเดิมรับข้ามกลุ่มได้ เพราะสไตล์เดียวกัน",
      distribute.bare(fid2.rsplit("/", 1)[1]) == distribute.bare(fid.rsplit("/", 1)[1]))
fid3, _, _ = rq.find_new_home(alloc, {"service_type": "Saver Bike", "style": "ครึ่ง/สว่าง"})
check("สไตล์ต่างต้องคนละคน",
      distribute.bare(fid3.rsplit("/", 1)[1]) != distribute.bare(fid.rsplit("/", 1)[1]))
_, _, err4 = rq.find_new_home(alloc, {"service_type": "ค่าโดยสาร 86", "style": "ยาว/มืด"})
check("อ่านประเภทบริการไม่ออกก็ไม่เดา", err4 and "อ่านประเภทบริการไม่ออก" in err4)

print("รูปส่งลูกค้าชุดเก่า:")
e = FakeDrive()
e.tree["exports"] = {}
wkd = e.ensure_folder("exports", "2026-W36")
cat_d = e.ensure_folder(wkd, "2 W Saver")
hold = e.ensure_folder(wkd, "_แทนที่แล้ว")
e.images[cat_d] = [{"id": "a", "name": "มานิตย์ Home7.jpg"},
                   {"id": "b", "name": "มานิตย์ Home21.jpg"},
                   {"id": "c", "name": "คนอื่น Win3.jpg"}]
e.images[hold] = [{"id": "z", "name": "มานิตย์ Home1.jpg"}]
found = rq.stale_export_images(e, "exports", "2026-W36", {"มานิตย์ Home"})
check("เจอเฉพาะรูปของคนที่ถูกแตะ", sorted(i["id"] for _, i in found) == ["a", "b"])
check("ไม่ไปยุ่งโฟลเดอร์ที่พักไว้แล้ว", "z" not in [i["id"] for _, i in found])
check("สัปดาห์อื่นไม่ถูกแตะ", rq.stale_export_images(e, "exports", "2026-W35", {"มานิตย์ Home"}) == [])

print("โหมดรายงานต้องเขียนอะไรไม่ได้เลย:")
real = FakeDrive()
cat_real = real.ensure_folder("week", "2 W Saver")
real.images[cat_real] = 3
dry = rq.DryDrive(real)
check("โฟลเดอร์ที่มีอยู่แล้ว คืนของจริง", dry.ensure_folder("week", "2 W Saver") == cat_real)
before = dict(real.tree)
newf = dry.ensure_folder(cat_real, "01-วิน1 Win")
check("โฟลเดอร์ใหม่ไม่ถูกสร้างบน Drive", real.tree == before)
check("แต่ยังได้ id ไว้ใช้ต่อ", newf and newf.endswith("01-วิน1 Win"))
check("โฟลเดอร์ที่ยังไม่มีจริง อ่านแล้วว่าง", dry.list_images(newf) == [] and dry.list_folders(newf) == [])
check("ของจริงยังอ่านได้ตามปกติ", len(dry.list_images(cat_real)) == 3)
for op, args in (("move_file", ("a", "b")), ("upload_file", ("a", "b", b"", "image/jpeg"))):
    try:
        getattr(dry, op)(*args)
        check(f"{op} ต้องถูกปฏิเสธ", False)
    except AssertionError:
        check(f"{op} ต้องถูกปฏิเสธ", True)

# and the allocator really does try to open folders — which is why the guard has to exist
d9 = FakeDrive()
a9 = distribute.Allocator(rq.DryDrive(d9), "week", POOL, per_rider=21, seed=9)
a9.folder_for("2 W Saver", "2W", "ยาว/มืด")
check("จ่ายงานผ่านโหมดรายงานแล้ว Drive ยังสะอาด", d9.tree == {"week": {}})

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
