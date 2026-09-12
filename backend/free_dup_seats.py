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


def wheel_of(category):
    """'2 W Saver' -> '2W'. Which list the freed seats come back to — the trips with nowhere to
    go are all on the 2W side, so a total that mixes the two answers the wrong question."""
    import rebalance_quota as rq
    return rq.wheel_of_category(category)


def seats_freed(plan):
    """How much room the move actually gives back, counted the way the allocator counts.

    Room is quota minus pictures in the folder, floored at zero. The first shape of this summed
    'quota minus live trips', which is unused capacity and not the same thing: it went negative
    for the riders whose pictures had already been moved elsewhere by the quota rebalance, and
    those negatives quietly ate the real gains of everybody else."""
    q = config.EXPECTED_TRIPS_PER_WEEK
    total = 0
    for p in plan:
        before = max(0, q - p["on_drive"])
        after = max(0, q - (p["on_drive"] - len(p["files"])))
        total += after - before
    return total


# กันชนของรอบอัตโนมัติ: เก็บกวาดได้มากสุดกี่ใบต่อรอบก่อนจะขอให้คนมาดูก่อน
# 2026-09-12 กวาดมือครั้งแรกของ W37 ได้ 475 ใบ — ตัวเลขนั้นถูกต้องแต่ไม่มีใครคาดมาก่อน ถ้าวันหนึ่ง
# ตัวจับซ้ำพลาดแล้วพักแถวดี ๆ ไว้ รอบอัตโนมัติต้องไม่กวาดโฟลเดอร์ไรเดอร์เกลี้ยงโดยไม่มีใครเห็น
SWEEP_CAP = 150


def week_is_open(d_to, today=None) -> bool:
    """สัปดาห์นี้ยังทำอยู่หรือปิดไปแล้ว — วันสุดท้ายของสัปดาห์ผ่านไปแล้ว = ปิด

    รอบอัตโนมัติเก็บกวาดเฉพาะสัปดาห์ที่ยังทำอยู่ ของที่ส่งลูกค้าไปแล้วไม่ต้องไปขยับ: ที่นั่งของ
    สัปดาห์ที่ปิดแล้วไม่มีใครใช้ต่อ และการย้ายไฟล์ทีหลังทำให้สิ่งที่ลูกค้าเปิดดูไปแล้วเปลี่ยน
    (2026-09-13 รอบ #210 เจอรูปซ้ำ 165 ใบของ W36 ซึ่งส่งไปแล้ว) สั่งเองยังกวาดสัปดาห์ไหนก็ได้"""
    from datetime import date
    return str(d_to or "") >= (today or date.today().isoformat())


def sweep(drive, jobs, d_from, d_to, apply=False, cap=SWEEP_CAP, log=print):
    """เอารูปของแถวที่ตายแล้วออกจากโฟลเดอร์ไรเดอร์ · คืนสรุปเป็น dict

    ใช้ได้ทั้งจากคำสั่งมือ (main ข้างล่าง) และจากท้ายรอบ ingest ผลลัพธ์เหมือนกันทุกอย่าง
    ยกเว้นรอบอัตโนมัติมีเพดาน: เกิน cap เมื่อไหร่จะรายงานแล้วไม่ย้าย"""
    dead_by_job = dead_trips(jobs)
    out = {"jobs": len(jobs), "with_dead": len(dead_by_job), "files": 0, "seats": 0,
           "moved": 0, "failed": 0, "over_cap": False, "plan": []}
    if not dead_by_job:
        return out
    plan = plan_for(drive, jobs, dead_by_job)
    broken = [p for p in plan if p.get("error")]
    plan = [p for p in plan if p.get("files")]
    out["plan"] = plan
    for p in broken:
        log(f"  ⚠ อ่านโฟลเดอร์ {p['job'].get('folder_name')} ไม่ได้: {p['error']}")
    if not plan:
        return out
    out["files"] = sum(len(p["files"]) for p in plan)
    out["seats"] = seats_freed(plan)
    if not apply:
        return out
    if cap and out["files"] > cap:
        out["over_cap"] = True
        log(f"  ⚠ รูปซ้ำ {out['files']} ใบ เกินเพดาน {cap} ใบต่อรอบ — ไม่ย้ายอะไรทั้งสิ้น "
            f"ให้คนดูก่อนแล้วสั่ง free_dup_seats.py --apply เอง")
        return out

    import rebalance_quota as rq
    wk = rq.week_folder(drive, config.DRIVE_INBOX_FOLDER_ID, d_from, d_to)
    if wk is None:
        log(f"  ✗ ไม่พบโฟลเดอร์สัปดาห์ที่ครอบ {d_from}..{d_to} ใน Inbox — ไม่ได้ย้ายอะไร")
        return out
    hold_root = drive.ensure_folder(wk["id"], HOLD_DIR)
    for p in plan:
        dest = drive.ensure_folder(hold_root, str(p["job"]["driver_name"]))
        for img in p["files"]:
            try:
                drive.move_file(img["id"], dest)
                out["moved"] += 1
            except Exception as e:                              # noqa: BLE001
                out["failed"] += 1
                log(f"  ⚠ ย้ายไม่สำเร็จ {img['name']}: {str(e)[:70]}")
    out["week_name"] = wk["name"]
    return out


def return_picture(trip_id, drive=None, log=print) -> bool:
    """เอารูปกลับเข้าโฟลเดอร์ไรเดอร์ เมื่อแถวที่เคยถูกพักถูกกู้คืน

    ถ้าไม่ทำ แถวจะกลับเข้าคิวโดยไม่มีรูปให้ส่งลูกค้า และที่นั่งจะไม่ถูกนับคืน — รูรั่วนี้ไม่สำคัญ
    ตอนที่ยังกวาดด้วยมือ (คนกดกู้คืนก่อนกวาด) แต่พอกวาดทุกรอบอัตโนมัติแล้วมันเกิดได้ทุกวัน
    ย้ายด้วย id ของไฟล์ ซึ่งไม่เปลี่ยนตอนย้ายโฟลเดอร์ พัง = คืน False ไม่ใช่โยน error ทิ้ง
    เพราะแถวถูกกู้คืนไปแล้ว"""
    try:
        trip = db.get_trip(trip_id)
        if not trip:
            return False
        job = db.get_job(trip["job_id"]) or {}
        dest = job.get("drive_folder_id")
        fid = db.drive_ids_for_trips([trip_id]).get(trip_id)
        if not dest or not fid:
            return False
        if drive is None:
            import roster
            drive = roster._drive()
        drive.move_file(fid, dest)
        return True
    except Exception as e:                                      # noqa: BLE001
        log(f"⚠ กู้คืนแถว {trip_id} แล้ว แต่ย้ายรูปกลับเข้าโฟลเดอร์ไม่สำเร็จ: {str(e)[:80]}")
        return False


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
            # หนึ่งครั้งต่อโฟลเดอร์ ไม่ใช่สองครั้ง — เดิมถามรายการเดิมซ้ำเพื่อนับจำนวนรูป ซึ่งเป็น
            # ครึ่งหนึ่งของ 12 นาทีที่รอบกวาด W37 ใช้ไป และตอนนี้มันรันท้ายทุกรอบ
            on_drive = drive.list_images(fid)
        except Exception as e:                                  # noqa: BLE001
            plan.append({"job": j, "error": str(e)[:70], "files": []})
            continue
        here = [im for im in on_drive if im["id"] in ids]
        if here:
            plan.append({"job": j, "files": here, "live": live_count(j["id"]),
                         "on_drive": len(on_drive)})
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
    # สั่งเองไม่มีเพดาน — คนสั่งคือคนที่ดูรายงานมาแล้ว เพดานมีไว้กันรอบอัตโนมัติเท่านั้น
    res = sweep(drive, jobs, a.d_from, a.d_to, apply=a.apply, cap=None)
    print(f"{a.d_from}..{a.d_to} · {res['jobs']} job · job ที่มีแถวซ้ำ/ถูกพัก {res['with_dead']}")
    if not res["with_dead"]:
        print("ไม่มีอะไรต้องคืน ✔")
        return 0

    plan = res["plan"]
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
    print(f"\nรูปที่จะเอาออก {files} ใบ จาก {len(plan)} โฟลเดอร์"
          f" · ที่นั่งที่ได้คืน {seats_freed(plan)} เที่ยว")
    by_wheel = defaultdict(list)
    for p in plan:
        by_wheel[wheel_of(p["job"].get("category")) or "?"].append(p)
    for wheel, ps in sorted(by_wheel.items()):
        print(f"    {wheel}: คืน {seats_freed(ps)} เที่ยว จาก {len(ps)} โฟลเดอร์")
    if not a.apply:
        print("\n(รายงานอย่างเดียว — ยังไม่ได้แตะอะไร · ใส่ --apply เพื่อทำจริง)")
        return 0

    if not res["moved"] and not res["failed"]:
        print("\n✗ ไม่ได้ย้ายอะไรเลย — ดูบรรทัดเตือนข้างบน")
        return 1
    print(f"\nย้ายรูปซ้ำไปพักที่ {res.get('week_name', '')}/{HOLD_DIR}/ {res['moved']} ใบ "
          f"(ไม่ได้ลบ · ไม่ได้แตะแถวใดเลย)"
          + (f" · ย้ายไม่สำเร็จ {res['failed']}" if res["failed"] else ""))
    print("ที่นั่งคืนแล้ว — รอบจัดกองรอบหน้าจะเห็นคนพวกนี้ว่างและลงงานที่ค้างอยู่ได้")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
