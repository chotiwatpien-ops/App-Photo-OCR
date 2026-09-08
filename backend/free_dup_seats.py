# -*- coding: utf-8 -*-
"""Take the pictures that turned out to be repeats out of the rider folders, so the seats come back.

A rider's week is twenty-one trips, and the allocator decides who is full by counting the pictures
in their folder on Drive — not the rows in the database. The two stopped agreeing in run #131.
Ops sent the Parichat album twice, once split into three and once whole, and only the 80 files
that were byte-for-byte identical were caught as repeats. The rest were saved again by the phone,
so they paired, moved into rider folders, cost a Gemini call each, and were only then recognised
as trips already counted and parked as status='duplicate'.

What is left behind is a folder holding twenty-one pictures that produced almost no work:

    สัมมา Win     21 pictures   0 trips
    สาธิต Win     21 pictures   0 trips
    ไตรรัตน์ Win  21 pictures   1 trip

The allocator reads twenty-one and calls the person full, so ~175 seats across the 2W list are
held by pictures of trips that were already delivered under somebody else's name. That is why
run #132 said 'รายชื่อของ 2W หมดแล้ว' while the dashboard showed the same riders at 1/21, and
why 217 trips — 45 in the wrong-wheel cleanup and 172 still in the pool — have nowhere to go.

Nothing is deleted and no row is touched. The pictures move to Week/_ซ้ำ/, the rows keep their
status, their note and their restore button, and the seat is free for the next round to use.

    python free_dup_seats.py --from 2026-08-31 --to 2026-09-06
"""
import argparse
import sys
from collections import defaultdict

import config
import db

HOLD_DIR = "_ซ้ำ"

# A row in one of these states is on nobody's bill: 'duplicate' is a repeat of a trip already
# approved for the same money, 'voided' is a stitch of two different trips that never happened.
# Both keep their picture, and the picture is what the allocator counts.
DEAD = ("duplicate", "voided")


def dead_trips(jobs):
    """{job_id: [trip, ...]} — rows that cost a seat and earn nothing."""
    out = {}
    for j in jobs:
        full = db.get_job(j["id"]) or {"trips": []}
        dead = [t for t in full["trips"] if str(t.get("status")) in DEAD]
        if dead:
            out[j["id"]] = dead
    return out


def live_count(job_id):
    """Trips of this job that are actually worth a seat."""
    full = db.get_job(job_id) or {"trips": []}
    return sum(1 for t in full["trips"] if str(t.get("status")) not in DEAD)


def plan_for(drive, jobs, dead_by_job):
    """[{job, folder, on_drive, live, files}] — what would leave each rider folder.

    Only files still sitting in the rider's own folder count. A picture already moved on by a
    revert or an earlier sweep is somebody else's business, and a folder that cannot be read is
    reported rather than guessed at."""
    plan = []
    for j in jobs:
        dead = dead_by_job.get(j["id"])
        fid = j.get("drive_folder_id")
        if not dead or not fid:
            continue
        want = db.drive_ids_for_trips([t["id"] for t in dead])
        ids = {v for v in want.values() if v}
        try:
            here = [im for im in drive.list_images(fid) if im["id"] in ids]
        except Exception as e:                                  # noqa: BLE001
            plan.append({"job": j, "error": str(e)[:70], "files": []})
            continue
        if here:
            plan.append({"job": j, "files": here, "live": live_count(j["id"]),
                         "on_drive": len(drive.list_images(fid))})
    return plan


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="เอารูปที่เป็นของซ้ำออกจากโฟลเดอร์ไรเดอร์ เพื่อคืนที่นั่งให้รอบถัดไป (รายงานอย่างเดียวถ้าไม่ใส่ --apply)")
    ap.add_argument("--from", dest="d_from", required=True, help="วันเริ่มสัปดาห์ YYYY-MM-DD")
    ap.add_argument("--to", dest="d_to", required=True, help="วันจบสัปดาห์ YYYY-MM-DD")
    ap.add_argument("--apply", action="store_true", help="ย้ายไฟล์จริงบน Drive")
    a = ap.parse_args(argv)
    db.init_db()

    import roster
    drive = roster._drive()
    jobs = [j for (f, t), js in db.jobs_by_week().items()
            if f == a.d_from and t == a.d_to for j in js]
    dead_by_job = dead_trips(jobs)
    print(f"{a.d_from}..{a.d_to} · {len(jobs)} job · job ที่มีแถวซ้ำ/ถูกพัก {len(dead_by_job)}")
    if not dead_by_job:
        print("ไม่มีอะไรต้องคืน ✔")
        return 0

    plan = plan_for(drive, jobs, dead_by_job)
    broken = [p for p in plan if p.get("error")]
    plan = [p for p in plan if p.get("files")]
    if not plan:
        print("แถวซ้ำมีอยู่ แต่รูปไม่ได้อยู่ในโฟลเดอร์ไรเดอร์แล้ว — ไม่มีที่นั่งให้คืน")
        return 0

    print(f"\n{'ไรเดอร์':<24}{'กลุ่ม':<14}{'รูปในโฟลเดอร์':>14}{'เที่ยวจริง':>11}{'จะเอาออก':>10}{'เหลือ':>7}")
    for p in sorted(plan, key=lambda p: -len(p["files"])):
        j = p["job"]
        print(f"{str(j['driver_name'])[:24]:<24}{str(j.get('category'))[:14]:<14}"
              f"{p['on_drive']:>14}{p['live']:>11}{len(p['files']):>10}"
              f"{p['on_drive'] - len(p['files']):>7}")
    files = sum(len(p["files"]) for p in plan)
    # A seat is a place in somebody's twenty-one, so what comes back is capped by the quota:
    # a folder holding twenty-five dead pictures still only ever held twenty-one seats.
    seats = sum(min(config.EXPECTED_TRIPS_PER_WEEK, p["on_drive"]) - p["live"] for p in plan)
    print(f"\nรูปที่จะเอาออก {files} ใบ จาก {len(plan)} โฟลเดอร์ · ที่นั่งที่ได้คืนประมาณ {max(0, seats)} เที่ยว")
    for p in broken:
        print(f"  ⚠ อ่านโฟลเดอร์ {p['job'].get('folder_name')} ไม่ได้: {p['error']}")

    if not a.apply:
        print("\n(รายงานอย่างเดียว — ยังไม่ได้แตะอะไร · ใส่ --apply เพื่อทำจริง)")
        return 0

    wk = None
    import rebalance_quota as rq
    wk = rq.week_folder(drive, config.DRIVE_INBOX_FOLDER_ID, a.d_from, a.d_to)
    if wk is None:
        print(f"✗ ไม่พบโฟลเดอร์สัปดาห์ที่ครอบ {a.d_from}..{a.d_to} ใน Inbox")
        return 1
    hold_root = drive.ensure_folder(wk["id"], HOLD_DIR)
    moved, failed = 0, 0
    by_folder = defaultdict(int)
    for p in plan:
        j = p["job"]
        dest = drive.ensure_folder(hold_root, str(j["driver_name"]))
        for img in p["files"]:
            try:
                drive.move_file(img["id"], dest)
                moved += 1
                by_folder[j["driver_name"]] += 1
            except Exception as e:                              # noqa: BLE001
                failed += 1
                print(f"  ⚠ ย้ายไม่สำเร็จ {img['name']}: {str(e)[:70]}")
    print(f"\nย้ายรูปซ้ำไปพักที่ {wk['name']}/{HOLD_DIR}/ {moved} ใบ (ไม่ได้ลบ · ไม่ได้แตะแถวใดเลย)"
          + (f" · ย้ายไม่สำเร็จ {failed}" if failed else ""))
    print("ที่นั่งคืนแล้ว — รอบจัดกองรอบหน้าจะเห็นคนพวกนี้ว่างและลงงานที่ค้างอยู่ได้")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
