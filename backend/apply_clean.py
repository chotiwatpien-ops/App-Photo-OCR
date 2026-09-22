# -*- coding: utf-8 -*-
"""Make a delivered week's rows what the clean copy says: every repeat set aside as a duplicate,
and the week's customer pictures exactly the rows that are left.

W34 and W35 go to the customer again, "as true and as clean as it can be", and the dashboard has
to say the same (Fiat 2026-09-23). The clean copy (week_phase3.py --drop-repeats) only filtered a
file; the dashboard, the week's scorecard, Rider Trips.xlsx and the duplicate report all read the
database. So each row the clean copy leaves out becomes status 'duplicate', pointing at the row
that stands for its trip, with the reason in its note, and leaves the delivered file (committed 0)
— as a voided row does. Nothing is deleted: `--undo` puts every row this script set aside back.

Pictures: each set-aside row's delivered picture, and any picture in the week's Exports folder no
row names, moves to that week's _แทนที่แล้ว. Afterwards every row has its picture and every picture
its row.

    python apply_clean.py --from 2026-08-17 --to 2026-08-23 --keep 11109,11115           # report
    python apply_clean.py --from 2026-08-17 --to 2026-08-23 --keep ... --apply
    python apply_clean.py --from 2026-08-17 --to 2026-08-23 --undo --apply
"""
import argparse
import sys
from collections import Counter

from sqlalchemy import select, update

import db
from ingest import week_label
from week_phase3 import drop_repeats, week_rows

MARK = "คลีนสัปดาห์"          # every note this script writes starts with it — the undo finds them by it
REPLACED_DIR = "_แทนที่แล้ว"


def plan(d_from, d_to, keep=()):
    rows = week_rows(d_from, d_to)
    kept, dropped, held = drop_repeats(rows, keep)
    return rows, kept, dropped, held


def write(dropped, d_from):
    stamp = f"{MARK} {week_label(d_from)}"
    with db.engine.begin() as c:
        for r, k, why in dropped:
            note = f"{stamp}: {why} — งานนี้นับที่ #{k['id']} ({k.get('driver_name')})"
            c.execute(update(db.trips).where(db.trips.c.id == r["id"], db.trips.c.status == "done")
                      .values(status="duplicate", duplicate_of=k["id"], committed=0,
                              note=f"{note} | {r['note']}" if r.get("note") else note))
    return len(dropped)


def undo(d_from, d_to):
    """Every row this script set aside in the week, back to done and delivered."""
    t, j = db.trips.c, db.jobs.c
    stamp = f"{MARK} {week_label(d_from)}"
    with db.engine.begin() as c:
        rows = c.execute(select(t.id, t.note).select_from(db.trips.join(db.jobs, j.id == t.job_id))
                         .where(j.date_from == d_from, j.date_to == d_to, t.status == "duplicate",
                                t.note.like(f"{stamp}%"))).all()
        for tid, note in rows:
            rest = note.split(" | ", 1)[1] if " | " in note else None
            c.execute(update(db.trips).where(db.trips.c.id == tid)
                      .values(status="done", duplicate_of=None, committed=1, note=rest))
    return len(rows)


def tidy_pictures(drive, exports_id, d_from, kept, log=print):
    """Move every picture of the week no kept row names into the week's _แทนที่แล้ว."""
    wk = next((f for f in drive.list_folders(exports_id) if f["name"] == week_label(d_from)), None)
    if wk is None:
        log(f"  ไม่พบโฟลเดอร์ {week_label(d_from)} ใน Exports")
        return Counter()
    named = {((r.get("category") or "").strip(), r.get("customer_image")) for r in kept if r.get("customer_image")}
    done, replaced = Counter(), None
    have = set()
    for g in drive.list_folders(wk["id"]):
        if g["name"].strip() == REPLACED_DIR:
            continue
        for img in drive.list_images(g["id"]):
            key = (g["name"].strip(), img["name"])
            if key in named:
                have.add(key)
                continue
            replaced = replaced or drive.ensure_folder(wk["id"], REPLACED_DIR)
            drive.move_file(img["id"], replaced)
            done["ย้ายรูปที่ไม่มีแถว"] += 1
    done["แถวที่รูปอยู่ครบ"] = len(have)
    done["แถวที่หารูปไม่เจอ"] = len(named - have)
    return done


def main(argv=None):
    ap = argparse.ArgumentParser(description="เขียนผลคลีนของสัปดาห์ลงฐานข้อมูล และจัดโฟลเดอร์รูปให้ตรง")
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--keep", default="", help="id ที่คนเปิดรูปแล้วเลือกเก็บ ในรหัสที่ค่ารอบไม่ตรงกัน")
    ap.add_argument("--undo", action="store_true", help="คืนทุกแถวที่สคริปต์นี้เคยพักไว้ในสัปดาห์นี้")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    db.init_db()
    if a.undo:
        if not a.apply:
            print("(รายงานอย่างเดียว — ใส่ --apply เพื่อคืนจริง)")
            return 0
        print(f"คืนแล้ว {undo(a.d_from, a.d_to):,} แถว")
        return 0
    keep = {int(x) for x in a.keep.replace(" ", "").split(",") if x}
    rows, kept, dropped, held = plan(a.d_from, a.d_to, keep)
    print(f"{week_label(a.d_from)} ({a.d_from}..{a.d_to}): {len(rows):,} แถว → เหลือ {len(kept):,} · พักเป็นงานซ้ำ {len(dropped):,}"
          f" (ค่ารอบ ฿{sum(r.get('base_fare') or 0 for r, _k, _w in dropped):,.0f})")
    for why, n in Counter(w for _r, _k, w in dropped).most_common():
        print(f"    {n:>4}  {why}")
    print("  เหลือตาม Service Type: " + " · ".join(f"{k or '?'} {v:,}" for k, v in
                                                   Counter(r.get("service_type") for r in kept).most_common()))
    if held:
        print(f"  ยังตัดสินไม่ได้ (รหัสเดียวกัน ค่ารอบต่างกัน) {len(held)} รหัส — ไม่แตะ:")
        for g in held:
            print("    " + " | ".join(f"#{r['id']} {r.get('driver_name')} ฿{r.get('base_fare')}" for r in g))
    if not a.apply:
        print("\n(รายงานอย่างเดียว — ใส่ --apply เพื่อเขียนลงฐานข้อมูลและจัดรูป)")
        return 0
    print(f"\n✓ พักเป็นงานซ้ำแล้ว {write(dropped, a.d_from):,} แถว")
    import config
    import roster
    done = tidy_pictures(roster._drive(), config.DRIVE_EXPORTS_FOLDER_ID, a.d_from, kept)
    print("  รูป: " + " · ".join(f"{k} {v:,}" for k, v in done.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
