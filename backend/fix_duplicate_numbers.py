# -*- coding: utf-8 -*-
"""Give a fresh number to every row whose customer picture name is shared with another row.

Numbering was per job until 2026-09-11, so a rider split across two jobs of one week — which is
what rehome and carry do — had two rows called 'WK36-สมชาย1.jpg'. The fix stops new collisions;
this clears the ones already made. Only the LATER row of each name moves, so the first row keeps
the name Ops and the customer already have.

What it does per row: clears customer_image so the next export names it afresh against the week,
and moves the file that stands under the shared name out of the group folder into _แทนที่แล้ว —
never deleting it, because two rows shared that name and only one of them still owns it.

    python fix_duplicate_numbers.py --from 2026-09-07 --to 2026-09-13          # report
    python fix_duplicate_numbers.py --from 2026-09-07 --to 2026-09-13 --apply
Then ingest with exports_only for that week: the cleared rows get new pictures and new names.
"""
import argparse
import sys
from collections import Counter, defaultdict

from sqlalchemy import select

import db

REPLACED_DIR = "_แทนที่แล้ว"


def duplicates(d_from, d_to):
    """[(name, [rows sharing it, earliest first])] for the week's shared picture names."""
    jobs = {j["id"]: j for j in db.jobs_by_week().get((d_from, d_to), [])}
    if not jobs:
        return [], jobs
    t = db.trips.c
    with db.engine.begin() as c:
        rows = [dict(r) for r in c.execute(
            select(t.id, t.job_id, t.file_name, t.trip_date, t.trip_time, t.customer_image, t.note)
            .where(t.job_id.in_(list(jobs)), t.status == "done",
                   t.customer_image.isnot(None))).mappings().all()]
    per = defaultdict(list)
    for r in rows:
        per[r["customer_image"]].append(r)
    out = []
    for name, rs in sorted(per.items()):
        if len(rs) < 2:
            continue
        rs.sort(key=lambda r: (r.get("trip_date") or "", r.get("trip_time") or "", r["id"]))
        out.append((name, rs))
    return out, jobs


def apply(drive, exports_week_id, dups, jobs, log=print):
    """Clear the later rows' names, and park the shared file. Returns a tally."""
    done = Counter()
    hold = None
    group_dirs = {}
    if exports_week_id:
        for f in drive.list_folders(exports_week_id):
            if f["name"] == REPLACED_DIR:
                hold = f["id"]
            else:
                group_dirs[f["name"]] = f["id"]
        if hold is None:
            hold = drive.ensure_folder(exports_week_id, REPLACED_DIR)
    for name, rs in dups:
        keep, movers = rs[0], rs[1:]
        for r in movers:
            note = (f"ชื่อรูปซ้ำกับแถว #{keep['id']} ({name}) — ล้างชื่อให้ตั้งใหม่ "
                    f"(เลขรูปเคยนับแยกตาม job)")
            db.update_trip(r["id"], {"customer_image": None,
                                     "note": f"{note} | {r['note']}" if r.get("note") else note})
            done["ล้างชื่อรูป"] += 1
        if hold and group_dirs:
            cat = (jobs[keep["job_id"]].get("category") or "").strip()
            fid = group_dirs.get(cat)
            hits = [i for i in drive.list_images(fid) if i["name"] == name] if fid else []
            # one file for two rows: which row owns it cannot be told apart, so it is parked
            for i in hits:
                drive.move_file(i["id"], hold)
                done["เก็บไฟล์ชื่อซ้ำเข้า _แทนที่แล้ว"] += 1
            if not hits:
                done["หาไฟล์ชื่อซ้ำในโฟลเดอร์กลุ่มไม่เจอ"] += 1
        if done["ล้างชื่อรูป"] % 100 == 0 and done["ล้างชื่อรูป"]:
            log(f"    ล้างแล้ว {done['ล้างชื่อรูป']} แถว")
    return done


def main(argv=None):
    ap = argparse.ArgumentParser(description="ล้างชื่อรูปที่ซ้ำกัน ให้รอบ export ตั้งชื่อใหม่")
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    db.init_db()
    dups, jobs = duplicates(a.d_from, a.d_to)
    rows = sum(len(rs) for _n, rs in dups)
    print(f"สัปดาห์ {a.d_from}..{a.d_to}: job {len(jobs)} · ชื่อรูปที่ซ้ำ {len(dups)} ชื่อ · แถวที่เกี่ยว {rows}")
    if not dups:
        print("ไม่มีชื่อซ้ำ")
        return 0
    print("  จะล้างชื่อของแถวที่มาทีหลัง " + str(rows - len(dups)) + " แถว (แถวแรกของแต่ละชื่อคงไว้)")
    for name, rs in dups[:20]:
        who = " · ".join(f"#{r['id']} {r.get('trip_date')}" for r in rs)
        print(f"    {name}: {who}")
    if len(dups) > 20:
        print(f"    … อีก {len(dups) - 20} ชื่อ")
    if not a.apply:
        print("\n(รายงานอย่างเดียว — ใส่ --apply เพื่อล้างจริง)")
        return 0
    import config
    import roster
    from ingest import week_label
    drive = roster._drive()
    exports = next((f for f in drive.list_folders(config.DRIVE_INBOX_FOLDER_ID)
                    if f["name"].strip() == "Export Pic"), None)
    ex_week = (next((f["id"] for f in drive.list_folders(exports["id"])
                     if f["name"] == week_label(a.d_from)), None) if exports else None)
    if ex_week is None:
        print("⚠ ไม่พบโฟลเดอร์ Export Pic ของสัปดาห์นี้ — จะล้างชื่อในฐานข้อมูลอย่างเดียว")
    done = apply(drive, ex_week, dups, jobs)
    print("\nทำแล้ว: " + " · ".join(f"{k} {v}" for k, v in done.most_common()))
    print("ขั้นต่อไป: ingest ติ๊ก exports_only — แถวที่ล้างชื่อจะได้รูปและชื่อใหม่ที่ไม่ซ้ำ")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
