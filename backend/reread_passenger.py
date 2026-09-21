# -*- coding: utf-8 -*-
"""Fill the passenger's fare block, line by line, for a week that was read before the reader knew
those lines — without touching the fare itself.

Sheet1 now shows every line between what the passenger paid and the ride fare (Ops 2026-09-21):
app fee, international fee, ส่วนลด, the travel-insurance fee, the passenger's ค่าทางด่วน, the tip.
A week read before that has two gaps. ส่วนลด and the insurance fee sat in one field, so a slip
that printed both kept one; and the passenger's ค่าทางด่วน was never read. Such rows cannot be
added up to their own fare from their own columns.

Two steps, cheapest first:

* split — a row that already adds up holds at most one of the two lines, and its sign says
  which: ส่วนลด is printed positive, the insurance fee negative. No reading needed.
* reread — a row that does not add up is read again with the passenger lines switched on. The
  new reading is taken only when it keeps the row's own ยอดที่ผู้โดยสารชำระ and
  รวมค่าโดยสาร exactly, and its lines add up between them. Anything else is listed for a person
  and left as it was: the fare is what the customer checks, and a second reading that disagrees
  with the first is not evidence that the first was wrong.

    python reread_passenger.py --week 2026-09-14                # report; reads up to --limit rows
    python reread_passenger.py --week 2026-09-14 --apply        # write
"""
import argparse
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

import db

TOL = 0.51


def _f(v):
    return float(v) if v is not None else 0.0


def gap(t) -> float | None:
    """How far the row's own passenger lines are from adding up to its fare; None if it has no
    paid line to start from (the old screen). intl_fee is stored as an absolute number."""
    if t.get("passenger_paid") is None or t.get("passenger_total") is None:
        return None
    got = (_f(t["passenger_paid"]) + _f(t.get("app_fee")) - abs(_f(t.get("intl_fee")))
           + _f(t.get("discount")) + _f(t.get("insurance_fee")) + _f(t.get("passenger_tolls"))
           + _f(t.get("other_adj")) - _f(t.get("tip")))
    return round(_f(t["passenger_total"]) - got, 2)


def split(t) -> dict | None:
    """The lumped line of a row that already adds up, moved to the field its sign names."""
    if t.get("discount") is not None or t.get("insurance_fee") is not None:
        return None
    o = t.get("other_adj")
    if not o:
        return None
    g = gap(t)
    if g is None or abs(g) >= TOL:
        return None
    return {"discount": o, "other_adj": None} if o > 0 else {"insurance_fee": o, "other_adj": None}


def decide(t, new) -> tuple[dict | None, str]:
    """(fields to write, why) for a fresh reading of row t. Never moves paid or the fare."""
    for k in ("passenger_paid", "passenger_total"):
        if new.get(k) is None:
            return None, f"อ่านใหม่ไม่เห็น {k}"
        if abs(_f(new[k]) - _f(t.get(k))) >= TOL:
            return None, f"{k} อ่านใหม่ได้ {new[k]:g} ≠ เดิม {_f(t.get(k)):g}"
    fields = {
        "app_fee": new.get("app_fee"),
        "intl_fee": abs(_f(new.get("intl_fee"))),
        "discount": new.get("discount"),
        "insurance_fee": new.get("insurance_fee"),
        "passenger_tolls": new.get("passenger_tolls"),
        "other_adj": new.get("other_adjustments"),
    }
    g = gap({**t, **fields})
    if g is None or abs(g) >= TOL:
        return None, f"อ่านใหม่แล้วยังขาด {g:g}"
    return fields, "ลงตัว"


def rows_of_week(week):
    """Main rows of the week (not the merged halves), with the Drive file that shows the
    passenger block — the bottom half when the trip was stitched from two pictures."""
    t, j = db.trips.c, db.jobs.c
    with db.engine.begin() as c:
        main = c.execute(
            select(*db.TRIP_COLS, j.driver_name)
            .select_from(db.trips.join(db.jobs, j.id == t.job_id))
            .where(j.date_from == week, t.status == "done", t.merged_into.is_(None))
            .order_by(t.id)).mappings().all()
        kids = dict(c.execute(
            select(t.merged_into, t.source_url)
            .select_from(db.trips.join(db.jobs, j.id == t.job_id))
            .where(j.date_from == week, t.merged_into.isnot(None))
            .order_by(t.id.desc())).all())
    out = []
    for r in main:
        r = dict(r)
        r["_picture"] = kids.get(r["id"]) or r.get("source_url")
        out.append(r)
    return out


def _file_id(url):
    m = re.search(r"/d/([^/?]+)", url or "")
    return m.group(1) if m else None


def _read(t, drive, model):
    import extractor
    fid = _file_id(t.get("_picture"))
    if not fid:
        return t, None, "ไม่มีรูปบน Drive ให้ตามไปอ่าน"
    try:
        data = extractor.extract_image(drive.download(fid), "image/jpeg", model=model, lines=True)
        return t, data, None
    except Exception as e:                                         # noqa: BLE001
        return t, None, f"อ่านไม่สำเร็จ: {str(e)[:120]}"


def run(week, apply=False, limit=None, model=None, workers=8, log=print):
    rows = rows_of_week(week)
    log(f"สัปดาห์ {week}: {len(rows):,} แถว")
    splits = [(t, s) for t in rows if (s := split(t))]
    todo = [t for t in rows if (g := gap(t)) is not None and abs(g) >= TOL]
    no_paid = sum(1 for t in rows if gap(t) is None)
    log(f"  ลงตัวอยู่แล้ว {len(rows) - len(todo) - no_paid:,} · แยกช่องรวมตามเครื่องหมายได้ {len(splits):,}")
    log(f"  ไม่ลงตัว ต้องอ่านใหม่ {len(todo):,} · ไม่มียอดชำระ (จอเก่า) ข้าม {no_paid:,}")

    if apply:
        for t, s in splits:
            db.update_trip(t["id"], s)
        log(f"  ✓ แยกช่องรวมแล้ว {len(splits):,} แถว")

    if limit is not None and limit < len(todo):
        # spread across the week, so a measurement is not forty trips of one rider
        step = len(todo) / max(limit, 1)
        todo = [todo[int(i * step)] for i in range(limit)]
    if not todo:
        return {"rows": len(rows), "split": len(splits), "reread": 0}

    import roster
    drive = roster._drive()
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda t: _read(t, drive, model), todo))

    took, why, tok = [], {}, {"tok_in": 0, "tok_out": 0, "tok_think": 0}
    for t, data, err in results:
        if data:
            for k in tok:
                tok[k] += (data.get("_usage") or {}).get(k, 0)
        fields, reason = (None, err) if err else decide(t, data)
        if fields:
            took.append((t, fields))
        else:
            # group by the kind of disagreement, not by its amount
            why.setdefault(re.sub(r"-?\d[\d.,]*", "…", reason), []).append((t, reason))
    log(f"\nอ่านใหม่ {len(todo):,} แถวใน {time.time() - t0:.0f} วิ · token เข้า {tok['tok_in']:,} ออก {tok['tok_out']:,} คิด {tok['tok_think']:,}")
    log(f"  ✓ ลงตัวและเก็บได้ {len(took):,} แถว")
    kinds = {}
    for _, f in took:
        for k in ("discount", "insurance_fee", "passenger_tolls", "other_adj"):
            if f.get(k):
                kinds[k] = kinds.get(k, 0) + 1
    if kinds:
        log("    พบบรรทัด: " + " · ".join(f"{k} {v}" for k, v in kinds.items()))
    left = sum(len(v) for v in why.values())
    log(f"  ✗ ไม่เก็บ ปล่อยไว้ให้คนดู {left:,} แถว")
    for reason, ts in sorted(why.items(), key=lambda kv: -len(kv[1])):
        log(f"    {len(ts):4}  {reason}")
        for t, detail in ts[:5]:
            log(f"          #{t['id']} {t.get('driver_name') or ''} {t.get('file_name') or ''} — {detail}")
    if apply:
        for t, f in took:
            db.update_trip(t["id"], f)
        log(f"\n✓ เขียนแล้ว {len(took):,} แถว")
    else:
        log("\n(รายงานอย่างเดียว — ยังไม่ได้เขียนอะไร · ใส่ --apply เพื่อเขียนจริง)")
    return {"rows": len(rows), "split": len(splits), "reread": len(todo), "took": len(took),
            "left": left, **tok}


def main(argv=None):
    ap = argparse.ArgumentParser(description="เติมบรรทัดค่าโดยสารฝั่งผู้โดยสารให้สัปดาห์ที่อ่านไปแล้ว")
    ap.add_argument("--week", required=True, help="วันแรกของสัปดาห์ เช่น 2026-09-14")
    ap.add_argument("--apply", action="store_true", help="เขียนจริง (ไม่ใส่ = รายงานอย่างเดียว)")
    ap.add_argument("--limit", type=int, default=None, help="อ่านใหม่ไม่เกินกี่แถว")
    ap.add_argument("--model", default=None)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    db.init_db()
    run(a.week, apply=a.apply, limit=a.limit, model=a.model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
