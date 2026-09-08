# -*- coding: utf-8 -*-
"""Which tier a row says, against the folder its picture sits in.

The workbook's Service Type came from the job's group, and a job is one group for the whole
week. The pool step files each picture by the chip on its slip, Saver or Standard, so a rider
whose job was opened under 2 W Standard and whose pictures went to their 2 W Saver folder
came out 'Standard Bike' on every row — 37 riders, about 870 rows, on 2026-09-09. The folder
a picture sits in is what the slip said; this reads that back and, with --apply, writes it
onto the rows and the job. Nothing is deleted; every changed row gets a note saying why.

    python service_audit.py --from 2026-08-31 --to 2026-09-06
    python service_audit.py --from 2026-08-31 --to 2026-09-06 --apply
"""
import argparse
import re
import sys
from collections import Counter

import db

TIER_RE = re.compile(r"\b(saver|standard)\b", re.IGNORECASE)
WHEEL_RE = re.compile(r"\b([24])\s*W\b", re.IGNORECASE)
GROUP_RE = re.compile(r"^\s*[24]\s*W\s+(Saver|Standard)\s*$", re.IGNORECASE)   # a real vehicle group


def tier_of(text):
    m = TIER_RE.search(text or "")
    return m.group(1).capitalize() if m else None


def wheel_of_group(group):
    m = WHEEL_RE.search(group or "")
    return {"2": "Bike", "4": "Car"}[m.group(1)] if m else None


def verdict(service_type, group):
    """('ok'|'flip'|'unknown', corrected service or None) for one row against its folder's group."""
    folder_tier, wheel = tier_of(group), wheel_of_group(group)
    row_tier = tier_of(service_type)
    if not folder_tier or not wheel or not row_tier:
        return "unknown", None
    if folder_tier == row_tier:
        return "ok", None
    return "flip", f"{folder_tier} {wheel}"


def audit(drive, jobs, log=print):
    """[(job, group now, rows, flips)] — group is the folder's parent on Drive today."""
    names = {}
    out = []
    for j in jobs:
        fid = j.get("drive_folder_id")
        group = None
        if fid:
            try:
                meta = drive.file_meta(fid)
                parent = (meta.get("parents") or [None])[0]
                if parent:
                    if parent not in names:
                        names[parent] = drive.file_meta(parent).get("name")
                    group = (names[parent] or "").strip()
            except Exception as e:                                  # noqa: BLE001
                log(f"  ⚠ อ่านโฟลเดอร์ของ job #{j['id']} ไม่ได้: {str(e)[:80]}")
        rows = db.trips_of_job(j["id"])
        flips = [(r, verdict(r["service_type"], group)[1]) for r in rows
                 if verdict(r["service_type"], group)[0] == "flip"]
        out.append((j, group, rows, flips))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="ตรวจว่า Saver/Standard ในแถวตรงกับโฟลเดอร์ที่รูปอยู่หรือไม่")
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--apply", action="store_true", help="แก้ service_type ของแถวและกลุ่มของ job ให้ตรงโฟลเดอร์")
    a = ap.parse_args(argv)
    db.init_db()
    import roster
    drive = roster._drive()
    jobs = db.jobs_by_week().get((a.d_from, a.d_to), [])
    if not jobs:
        print(f"✗ ไม่มี job ของ {a.d_from}..{a.d_to}")
        return 1
    print(f"{a.d_from}..{a.d_to}: {len(jobs)} job")
    result = audit(drive, jobs)
    by_change = Counter()
    n_rows = n_flip = n_moved = 0
    for j, group, rows, flips in result:
        n_rows += len(rows)
        if group and group != (j.get("category") or ""):
            n_moved += 1
        if flips:
            n_flip += len(flips)
            for _r, new in flips:
                by_change[(_r["service_type"], new)] += 1
            print(f"  job #{j['id']} {j['driver_name']}: job จดกลุ่ม {j.get('category')!r} · "
                  f"โฟลเดอร์อยู่ {group!r} · แถว {len(rows)} · ต้องแก้ {len(flips)}")
    print(f"\nรวม: แถว {n_rows} · ประเภทไม่ตรงโฟลเดอร์ {n_flip} · job ที่โฟลเดอร์ย้ายกลุ่มไปแล้ว {n_moved}")
    for (old, new), n in by_change.most_common():
        print(f"    {old!r} → {new!r}: {n} แถว")
    if not a.apply:
        print("\n(รายงานอย่างเดียว — ใส่ --apply เพื่อแก้จริง)")
        return 0
    fixed = jobs_fixed = 0
    for j, group, rows, flips in result:
        for r, new in flips:
            note = f"ประเภทตามโฟลเดอร์ {group}: {new} (เดิม {r['service_type']} จากกลุ่มของ job)"
            db.update_trip(r["id"], {"service_type": new,
                                     "note": f"{note} | {r['note']}" if r.get("note") else note})
            fixed += 1
        if group and group != (j.get("category") or "") and GROUP_RE.match(group):
            db.set_job_category(j["id"], group)
            jobs_fixed += 1
    print(f"\nแก้แล้ว: แถว {fixed} · job {jobs_fixed} (ไฟล์ส่งลูกค้าต้องเขียนใหม่ด้วย ingest xlsx_only)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
