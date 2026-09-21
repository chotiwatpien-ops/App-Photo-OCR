# -*- coding: utf-8 -*-
"""Move the read rows a week has no room for out of its _พร้อมอ่าน and into next week's.

A pair is read in <Week>/_พร้อมอ่าน/ and filed into a rider's folder afterwards
(file_after_read.py) — but only while its group is under target. When the group is full the row
stays in the waiting room for good: never filed, never approved, never pictured. W38 held 15
Standard Car rows like that for a week, and the round's scorecard read them as the car group over
target and as 19 rows without a delivered picture (Fiat asked about it on 2026-09-21).

What happens:
  * per group, the earliest-driven rows stay, as many as the week still has room for — the next
    round files them where they belong;
  * the rest move to next week's waiting room: the row to its '(รออ่าน)' job (made if absent),
    the picture into <next week>/_พร้อมอ่าน/, the date spread across next week in driven order
    with the slip's own day kept in the note (Fiat 2026-09-10: a week's file carries its own
    dates). The next round of that week files them as if they had arrived there.
Rows whose service no group takes are left alone and reported. Nothing is deleted, nothing re-read.

    python move_staged.py --week "Week 14-20 Sep" --from 2026-09-14 --to 2026-09-20          # report
    python move_staged.py ... --apply
"""
import argparse
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta

import db
import file_after_read as far
import redate_to_week
from pipeline import car_is_standard


def next_week(d_from, d_to):
    a, b = (date.fromisoformat(d) + timedelta(days=7) for d in (d_from, d_to))
    return a.isoformat(), b.isoformat()


def plan(d_from, d_to, target=None):
    """(keep, move, room, unknown): rows that stay, [(row, group)] that go, room per group before
    anything moves, and the count of rows no group takes."""
    rows = far.staged_rows(d_from, d_to)            # oldest first
    room = far.room_left(d_from, d_to, target)
    by_group, unknown = defaultdict(list), Counter()
    for r in rows:
        svc = car_is_standard((r.get("service_type") or "").strip())
        g = far.GROUP_OF.get(svc)
        if g:
            by_group[g].append(r)
        else:
            unknown[svc or "?"] += 1
    keep, move = [], []
    for g, rs in by_group.items():
        n = max(room.get(g, 0), 0)
        keep += [(r, g) for r in rs[:n]]
        move += [(r, g) for r in rs[n:]]
    return keep, move, room, unknown


def apply(drive, inbox_id, d_from, d_to, move, log=print):
    import excel_writer
    import ingest
    n_from, n_to = next_week(d_from, d_to)
    week = next((f for f in drive.list_folders(inbox_id)
                 if f["name"].strip().lower().startswith("week")
                 and (rng := ingest.parse_range(f["name"])) and rng[0].isoformat() == n_from), None)
    if week is None:
        raise RuntimeError(f"ไม่พบโฟลเดอร์สัปดาห์ที่เริ่ม {n_from} ใน Inbox")
    hold = drive.ensure_folder(week["id"], far.HOLDING_DIR)
    jid = (db.find_job_by_folder(hold, n_from)
           or db.find_job(far.HOLDING_RIDER, n_from, n_to)
           or db.create_job(far.HOLDING_RIDER, excel_writer.SHEET, n_from, n_to,
                            folder_name=f"{week['name']}/{far.HOLDING_DIR}", drive_folder_id=hold))
    done = Counter()
    rows = [r for r, _g in move]
    pics = db.drive_ids_for_trips([r["id"] for r in rows])
    for r in rows:
        pic = pics.get(r["id"])
        if pic:
            try:
                drive.move_file(pic, hold)
                done["ย้ายรูป"] += 1
            except Exception as e:                                # noqa: BLE001
                done[f"ย้ายรูปไม่สำเร็จ: {str(e)[:40]}"] += 1
        else:
            done["ไม่พบรูปบน Drive"] += 1
    db.move_trips_to_job([r["id"] for r in rows], jid)
    for r, new in redate_to_week.spread(rows, n_from, n_to):
        note = (f"ย้ายจากกองพัก {d_from}..{d_to} ไป {n_from}..{n_to} เพราะกลุ่มเต็ม · "
                f"วันที่บนสลิป {r.get('trip_date')} → ลงเป็น {new}")
        db.update_trip(r["id"], {"trip_date": new, "note": f"{note} | {r['note']}" if r.get("note") else note})
        done["ย้ายแถว"] += 1
    log(f"  → job #{jid} {far.HOLDING_RIDER} · {n_from}..{n_to} ({week['name']}/{far.HOLDING_DIR})")
    return done, jid


def main(argv=None):
    ap = argparse.ArgumentParser(description="ย้ายแถวที่ค้างในกองพักเพราะกลุ่มเต็ม ไปกองพักสัปดาห์หน้า")
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    db.init_db()
    keep, move, room, unknown = plan(a.d_from, a.d_to)
    print(f"กองพัก {a.d_from}..{a.d_to}: {len(keep) + len(move) + sum(unknown.values())} แถว")
    for g in sorted({g for _r, g in keep + move}):
        k = sum(1 for _r, gg in keep if gg == g)
        m = sum(1 for _r, gg in move if gg == g)
        print(f"    {g:<14} ที่ว่าง {max(room.get(g, 0), 0):>4} · อยู่ต่อ {k} · ย้ายไปสัปดาห์หน้า {m}")
    for svc, n in unknown.items():
        print(f"    {svc}: {n} แถว — ไม่มีกลุ่มรับ ปล่อยไว้")
    for r, g in move:
        print(f"      #{r['id']} {g} {r.get('trip_date')} {r.get('file_name')}")
    if not move:
        print("ไม่มีอะไรต้องย้าย")
        return 0
    if not a.apply:
        print("\n(รายงานอย่างเดียว — ใส่ --apply เพื่อย้ายจริง)")
        return 0
    import config
    import roster
    done, _jid = apply(roster._drive(), config.DRIVE_INBOX_FOLDER_ID, a.d_from, a.d_to, move)
    print("\nทำแล้ว: " + " · ".join(f"{k} {v}" for k, v in done.most_common()))
    print("รอบ ingest ถัดไปจะลงโฟลเดอร์ไรเดอร์ของทั้งสองสัปดาห์ให้เอง")
    return 0


if __name__ == "__main__":
    sys.exit(main())
