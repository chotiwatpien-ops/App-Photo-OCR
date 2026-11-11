# -*- coding: utf-8 -*-
"""Take a trip approved twice back to once, in a week that is still open.

W46 (Fiat 2026-11-11): one slip was screenshotted twice and its booking code read two ways at
the line break, so both rows were approved and ฿38 was in the customer's file twice. The round
now holds such a row for a person (db._hold_suspects); this settles the ones approved before.

Only same_trip's CODE evidence is settled here (codes a letter or two apart, same fare and
distance). For each such group the first approved row stays; every later one is parked as a
duplicate of it, its customer picture moves to <group>/_ซ้ำ in the week's Exports folder, and the
week's file is written again. Same-route groups are listed for a person and left alone. A closed
week is never touched.

    python settle_doubles.py --from 2026-11-09 --to 2026-11-15            # report
    python settle_doubles.py --from 2026-11-09 --to 2026-11-15 --apply
"""
import argparse
import sys

from sqlalchemy import update

import db
import same_trip
from week_phase3 import week_rows

PARKED_DIR = "_ซ้ำ"


def plan(rows):
    """[(row to park, the row it repeats)] and [[rows]] of same-route groups, from the week's
    approved rows."""
    park, route = [], []
    for k, g in same_trip.groups(rows):
        if k != same_trip.CODE:
            route.append(g)
            continue
        kept = [g[0]]
        for r in g[1:]:
            twin, kind = same_trip.find_twin(r, kept)
            if twin is not None and kind == same_trip.CODE:
                park.append((r, twin))
            else:
                kept.append(r)
    return park, route


def park(r, twin):
    msg = (f"ซ้ำกับ {twin.get('customer_image') or twin.get('file_name')} ที่อนุมัติแล้ว "
           f"({same_trip.REASON[same_trip.CODE]}) — พบหลังอนุมัติ ถอดออกจากไฟล์")
    with db.engine.begin() as c:
        c.execute(update(db.trips).where(db.trips.c.id == r["id"], db.trips.c.committed == 1)
                  .values(status="duplicate", committed=0, duplicate_of=twin["id"],
                          note=f"{msg} | {r['note']}" if r.get("note") else msg))


def move_picture(drive, week_dir, r):
    """Move the parked row's customer picture out of its group folder. False when not found."""
    group = next((f["id"] for f in drive.list_folders(week_dir)
                  if f["name"].strip() == (r.get("category") or "").strip()), None)
    if not group or not r.get("customer_image"):
        return False
    pic = next((f["id"] for f in drive.list_images(group) if f["name"] == r["customer_image"]), None)
    if not pic:
        return False
    drive.move_file(pic, drive.ensure_folder(group, PARKED_DIR))
    return True


def run(drive, exports_id, d_from, d_to, apply, log=print):
    from ingest import week_label
    if d_from in set(db.closed_weeks()):
        log(f"✗ {week_label(d_from)} ปิดแล้ว — ไม่แตะสัปดาห์ที่ส่งแล้ว")
        return 1
    rows = week_rows(d_from, d_to)
    todo, route = plan(rows)
    # the repo is public: rows are named by id and customer picture only
    log(f"{week_label(d_from)}: อนุมัติ {len(rows):,} แถว · นับซ้ำ (เลขจองอ่านเพี้ยน) {len(todo)} แถว · "
        f"เส้นทางเดียวกัน (ให้คนดู) {len(route)} ชุด")
    for r, twin in todo:
        log(f"  ถอด #{r['id']} {r.get('customer_image')} ฿{r.get('base_fare')} — ซ้ำกับ #{twin['id']} {twin.get('customer_image')}")
    for g in route:
        log("  ให้คนดู: " + " | ".join(f"#{r['id']} {r.get('customer_image')}" for r in g))
    if not apply or not todo:
        log("(รายงานอย่างเดียว — ติ๊ก apply เพื่อถอดจริง)" if todo else "ไม่มีอะไรต้องถอด ✔")
        return 0
    week_dir = next((f["id"] for f in drive.list_folders(exports_id) if f["name"] == week_label(d_from)), None)
    for r, twin in todo:
        park(r, twin)
        moved = week_dir is not None and move_picture(drive, week_dir, r)
        log(f"  ✓ #{r['id']} ถอดแล้ว" + ("" if moved else " · ไม่พบรูปในโฟลเดอร์ลูกค้า"))
    import week_files
    written, errors = week_files.write(drive, exports_id, weeks=[(d_from, d_to)], force=True, log=log)
    return 1 if errors else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="ถอดเที่ยวที่ถูกอนุมัติสองครั้ง (เลขจองอ่านเพี้ยน) ออกจากสัปดาห์ที่ยังเปิด")
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    db.init_db()
    import config
    import roster
    return run(roster._drive(), config.DRIVE_EXPORTS_FOLDER_ID, a.d_from, a.d_to, a.apply)


if __name__ == "__main__":
    sys.exit(main())
