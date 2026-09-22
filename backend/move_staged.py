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
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import select

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


def waiting_room(drive, inbox_id, d_from, d_to):
    """(week folder, its _พร้อมอ่าน folder id, its '(รออ่าน)' job id) — folder and job made if absent."""
    import excel_writer
    import ingest
    week = next((f for f in drive.list_folders(inbox_id)
                 if f["name"].strip().lower().startswith("week")
                 and (rng := ingest.parse_range(f["name"])) and rng[0].isoformat() == d_from), None)
    if week is None:
        raise RuntimeError(f"ไม่พบโฟลเดอร์สัปดาห์ที่เริ่ม {d_from} ใน Inbox")
    hold = drive.ensure_folder(week["id"], far.HOLDING_DIR)
    jid = (db.find_job_by_folder(hold, d_from)
           or db.find_job(far.HOLDING_RIDER, d_from, d_to)
           or db.create_job(far.HOLDING_RIDER, excel_writer.SHEET, d_from, d_to,
                            folder_name=f"{week['name']}/{far.HOLDING_DIR}", drive_folder_id=hold))
    return week, hold, jid


def apply(drive, inbox_id, d_from, d_to, move, log=print):
    n_from, n_to = next_week(d_from, d_to)
    week, hold, jid = waiting_room(drive, inbox_id, n_from, n_to)
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



def rows_to_bring_back(d_from, d_to, ids):
    """([row with its job], [why not]) for the asked rows that sit in NEXT week's finished work."""
    n_from, n_to = next_week(d_from, d_to)
    t, j = db.trips.c, db.jobs.c
    with db.engine.begin() as c:
        found = {r["id"]: dict(r) for r in c.execute(
            select(t.id, t.job_id, t.status, t.file_name, t.service_type, t.trip_date, t.trip_time,
                   t.customer_image, t.note, j.date_from, j.date_to, j.category, j.driver_name)
            .select_from(db.trips.join(db.jobs, j.id == t.job_id))
            .where(t.id.in_(ids))).mappings().all()}
    ok, bad = [], []
    for i in ids:
        r = found.get(i)
        if r is None:
            bad.append(f"#{i} ไม่พบแถว")
        elif (r["date_from"], r["date_to"]) != (n_from, n_to):
            bad.append(f"#{i} ไม่ได้อยู่ในสัปดาห์ {n_from}..{n_to} (อยู่ {r['date_from']})")
        elif r["status"] != "done":
            bad.append(f"#{i} สถานะ {r['status']}")
        else:
            ok.append(r)
    return ok, bad


def bring_back(drive, inbox_id, d_from, d_to, rows, log=print):
    """Rows the pool sent on to next week while this week still had room come back to this week's
    _พร้อมอ่าน, to be filed by the next round like any read row.

    W38 Saver (2026-09-21): the pool counted room by folder, saw 1,470 where the customer counted
    1,466, and sent 4 of the 20 Ploy trips Ops had uploaded to fill W38 into W39's พัดชา Win. Per
    row: the stitched picture into this week's _พร้อมอ่าน, the picture next week already delivered
    into its Export Pic week's _แทนที่แล้ว (so its name is not left naming a trip that moved), the
    row to this week's '(รออ่าน)' job, its delivered name cleared, dated across this
    week."""
    import ingest
    from carry_excess import REPLACED_DIR
    n_from, _n_to = next_week(d_from, d_to)
    _week, hold, jid = waiting_room(drive, inbox_id, d_from, d_to)
    exports = next((f for f in drive.list_folders(inbox_id) if f["name"].strip() == "Export Pic"), None)
    next_exports = (next((f["id"] for f in drive.list_folders(exports["id"])
                          if f["name"] == ingest.week_label(n_from)), None) if exports else None)
    done, listing, replaced = Counter(), {}, None
    pics = db.drive_ids_for_trips([r["id"] for r in rows])
    for r in rows:
        pic = pics.get(r["id"])
        if pic:
            drive.move_file(pic, hold)
            done["ย้ายรูปรวมร่าง"] += 1
        else:
            done["ไม่พบรูปรวมร่างบน Drive"] += 1
        cdir = None
        if r.get("customer_image") and next_exports:
            if "_dirs" not in listing:
                listing["_dirs"] = {f["name"].strip(): f["id"] for f in drive.list_folders(next_exports)}
            cdir = listing["_dirs"].get((r.get("category") or "").strip())
        if cdir:
            if cdir not in listing:
                listing[cdir] = {i["name"]: i["id"] for i in drive.list_images(cdir)}
            cid = listing[cdir].get(r["customer_image"])
            if cid:
                replaced = replaced or drive.ensure_folder(next_exports, REPLACED_DIR)
                drive.move_file(cid, replaced)
                done["เก็บรูปลูกค้าสัปดาห์หน้าออก"] += 1
            else:
                done["ไม่พบรูปลูกค้าสัปดาห์หน้า"] += 1
    db.move_trips_to_job([r["id"] for r in rows], jid)
    for r, new in redate_to_week.spread(rows, d_from, d_to):
        note = (f"ดึงกลับจาก {r['driver_name']} {r['date_from']}..{r['date_to']} มา {d_from}..{d_to} "
                f"เพราะกองนับที่ว่างตามโฟลเดอร์ ยกไปทั้งที่ยังขาด · วันที่ {r.get('trip_date')} → {new}")
        db.update_trip(r["id"], {"trip_date": new, "customer_image": None,
                                 "note": f"{note} | {r['note']}" if r.get("note") else note})
        done["ดึงแถวกลับ"] += 1
    log(f"  → job #{jid} {far.HOLDING_RIDER} · {d_from}..{d_to}")
    return done, jid

def main(argv=None):
    ap = argparse.ArgumentParser(description="ย้ายแถวที่ค้างในกองพักเพราะกลุ่มเต็ม ไปกองพักสัปดาห์หน้า")
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--back", default="", help="เลขแถวของสัปดาห์หน้า คั่นด้วยจุลภาค — ดึงกลับมากองพักสัปดาห์นี้")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    db.init_db()
    if a.back.strip():
        ids = [int(x) for x in re.findall(r"[0-9]+", a.back)]
        rows, bad = rows_to_bring_back(a.d_from, a.d_to, ids)
        print(f"ดึงกลับมากองพัก {a.d_from}..{a.d_to}: ขอ {len(ids)} · ดึงได้ {len(rows)}")
        for r in rows:
            print(f"    #{r['id']} {r['driver_name']} · {r['category']} · {r['service_type']} · "
                  f"{r.get('trip_date')} · {r.get('customer_image')} · {r['file_name']}")
        for why in bad:
            print(f"    ✗ {why}")
        if bad or not rows:
            print("มีแถวที่ดึงไม่ได้ — ไม่ทำอะไร")
            return 1
        if not a.apply:
            print("\n(รายงานอย่างเดียว — ใส่ --apply เพื่อดึงกลับจริง)")
            return 0
        import config
        import roster
        done, _jid = bring_back(roster._drive(), config.DRIVE_INBOX_FOLDER_ID, a.d_from, a.d_to, rows)
        print("\nทำแล้ว: " + " · ".join(f"{k} {v}" for k, v in done.most_common()))
        print("รอบ ingest ถัดไปจะลงโฟลเดอร์ไรเดอร์ให้ (กลุ่มนับตาม Service Type มีที่ว่างแล้ว)")
        return 0
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
