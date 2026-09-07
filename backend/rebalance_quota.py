# -*- coding: utf-8 -*-
"""Find riders carrying more than a week's worth of work, and say what it would take to fix.

A rider works 21 trips in a week. Four of them in 31 Aug-6 Sep are carrying 37 to 42, because
the allocator used to read one vehicle group at a time: 'this name is already working' was only
true of the group it had just looked at, so the same person could be drawn again in the other
group and handed a second, separate 21. The count that proves it is the tier split — มานิตย์ is
Saver 21 plus Standard 21, exactly two full folders.

The allocator now reads the whole week before it decides anything and counts the quota against
the person, so this cannot happen again. It does not undo what already happened, and the rows are
in the delivered file, which is why this reports and does not touch anything.

    python rebalance_quota.py --from 2026-08-31 --to 2026-09-06
"""
import argparse
import sys
from collections import defaultdict

import config
import db


def plan(rows, per_rider):
    """{rider: {"keep": [...], "release": [...]}} for whoever is over.

    Keep the same days, thinned. Taking simply the first 21 of the week is a rule anyone can
    check, which is why it was tried first — but on this data it left every one of the four
    working Monday to Thursday and then nothing at all, and a rider who stops dead three days
    before the week ends is a stranger sight than one who did 42. So the seats are handed out a
    day at a time, always to the day with the most trips still waiting: a rider who worked seven
    days still works seven days. Deterministic, and it does not depend on the order rows arrive
    in — which is what made the first rule checkable, and this one keeps."""
    by_rider = defaultdict(list)
    for t in rows:
        by_rider[t["driver_name"]].append(t)
    out = {}
    for who, ts in by_rider.items():
        if len(ts) <= per_rider:
            continue
        by_day = defaultdict(list)
        for t in sorted(ts, key=lambda t: t["id"]):
            by_day[str(t.get("trip_date") or "")].append(t)
        days = sorted(by_day)
        # Largest remainder. Each day keeps its share of the 21 in proportion to what it holds,
        # rounded down, and the seats left over go to the days that lost the most in the
        # rounding. A day that did more still keeps more, none of them empties, and the answer
        # is a named method rather than whatever a tie-break happened to do.
        total = len(ts)
        exact = {d: per_rider * len(by_day[d]) / total for d in days}
        seats = {d: int(exact[d]) for d in days}
        for d in sorted(days, key=lambda d: (-(exact[d] - seats[d]), d))[:per_rider - sum(seats.values())]:
            seats[d] += 1
        keep = [t for d in days for t in by_day[d][:seats[d]]]
        release = [t for d in days for t in by_day[d][seats[d]:]]
        out[who] = {"keep": keep, "release": release}
    return out


def room(rows, per_rider, over):
    """Seats left this week among everyone who is not over — where the released work could go."""
    n = defaultdict(int)
    for t in rows:
        n[t["driver_name"]] += 1
    return {w: per_rider - c for w, c in n.items() if c < per_rider and w not in over}


def days_line(ts):
    """'08-31:3 09-01:3 …' — a rider who worked every day has to go on working every day."""
    c = defaultdict(int)
    for t in ts:
        c[str(t.get("trip_date") or "?")] += 1
    return " ".join(f"{d[5:]}:{n}" for d, n in sorted(c.items()))


def tiers(ts):
    c = defaultdict(int)
    for t in ts:
        c[str(t.get("service_type") or "?")] += 1
    return " · ".join(f"{k} {v}" for k, v in sorted(c.items()))


def main(argv=None):
    ap = argparse.ArgumentParser(description="ใครทำเกินโควตาสัปดาห์ และต้องทำอะไรถึงจะแก้ได้ (รายงานอย่างเดียว)")
    ap.add_argument("--from", dest="d_from", required=True, help="วันเริ่มสัปดาห์ YYYY-MM-DD")
    ap.add_argument("--to", dest="d_to", required=True, help="วันจบสัปดาห์ YYYY-MM-DD")
    ap.add_argument("--per-rider", type=int, default=config.EXPECTED_TRIPS_PER_WEEK)
    ap.add_argument("--list", action="store_true", help="พิมพ์รายเที่ยวที่จะถูกเอาออก")
    a = ap.parse_args(argv)
    db.init_db()

    rows = db.query_trips(date_from=a.d_from, date_to=a.d_to)
    if not rows:
        print(f"ไม่มีแถวที่ลงไฟล์แล้วในช่วง {a.d_from}..{a.d_to}")
        return 0
    riders = {t["driver_name"] for t in rows}
    print(f"{a.d_from}..{a.d_to} · {len(rows)} เที่ยว · {len(riders)} ไรเดอร์ · โควตา {a.per_rider}/คน")

    over = plan(rows, a.per_rider)
    if not over:
        print("ไม่มีใครเกินโควตา ✔")
        return 0

    extra = sum(len(v["release"]) for v in over.values())
    print(f"\nเกินโควตา {len(over)} คน · เที่ยวส่วนเกินรวม {extra}")
    print(f"\n{'ไรเดอร์':<22}{'มี':>5}{'เก็บ':>6}{'เอาออก':>8}  แยกตามบริการ")
    for who, v in sorted(over.items(), key=lambda kv: -len(kv[1]["release"])):
        n = len(v["keep"]) + len(v["release"])
        print(f"{who[:22]:<22}{n:>5}{len(v['keep']):>6}{len(v['release']):>8}  "
              f"เก็บ [{tiers(v['keep'])}] · ออก [{tiers(v['release'])}]")
        print(f"{'':<22}      วันละ: " + days_line(v["keep"]))

    free = room(rows, a.per_rider, over)
    seats = sum(free.values())
    print(f"\nที่ว่างในสัปดาห์นี้ {seats} ที่ จากไรเดอร์ {len(free)} คนที่ยังไม่เต็ม")
    if seats < extra:
        need = -(-(extra - seats) // a.per_rider)      # ceil
        print(f"  ไม่พอ — ขาดอีก {extra - seats} ที่ ต้องเปิดไรเดอร์ใหม่อย่างน้อย {need} คน")
        try:
            pool = {k: [n for n, kd in db.name_pool_for(k[0]) if kd == k[1]]
                    for k in (("2W", "Win"), ("2W", "Home"), ("4W", "Taxi"), ("4W", "Home"))}
            used = {w.strip() for w in riders}
            spare = {k: len([n for n in v if f"{n} {k[1]}".strip() not in used])
                     for k, v in pool.items()}
            print("  ชื่อที่ยังไม่ถูกใช้ในสัปดาห์นี้: "
                  + " · ".join(f"{k[0]} {k[1]} {v}" for k, v in sorted(spare.items())))
        except Exception as e:                          # noqa: BLE001
            print(f"  (อ่านรายชื่อไม่ได้: {str(e)[:80]})")
    else:
        print(f"  พอ — ไม่ต้องเปิดชื่อใหม่")

    if a.list:
        print(f"\n{'ไรเดอร์':<22}{'วันที่':<12}{'บริการ':<16}{'ไฟล์'}")
        for who, v in sorted(over.items()):
            for t in v["release"]:
                print(f"{who[:22]:<22}{str(t.get('trip_date')):<12}"
                      f"{str(t.get('service_type'))[:16]:<16}{t.get('file_name')}")

    print("\n(รายงานอย่างเดียว — ยังไม่ได้แตะอะไรทั้งสิ้น)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
