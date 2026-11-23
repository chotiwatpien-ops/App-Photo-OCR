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

fill_earlier runs the other way inside every ingest round: an open week short in a group takes
that group's work back from the later open weeks first, waiting or already filed, however long
ago the week ended (Fiat 2026-11-23). Only closing the week ends that.

    python move_staged.py --week "Week 14-20 Sep" --from 2026-09-14 --to 2026-09-20          # report
    python move_staged.py ... --apply
"""
import argparse
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from sqlalchemy import select

import config
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


def bring_back(drive, inbox_id, d_from, d_to, rows, log=print,
               why="เพราะกองนับที่ว่างตามโฟลเดอร์ ยกไปทั้งที่ยังขาด"):
    """Rows a later week holds come back to this week's _พร้อมอ่าน, to be filed by the next
    round like any read row.

    W38 Saver (2026-09-21): the pool counted room by folder, saw 1,470 where the customer counted
    1,466, and sent 4 of the 20 Ploy trips Ops had uploaded to fill W38 into W39's พัดชา Win. Per
    row: the stitched picture into this week's _พร้อมอ่าน, the picture its own week already
    delivered into that Export Pic week's _แทนที่แล้ว (so its name is not left naming a trip that
    moved), the row to this week's '(รออ่าน)' job, its delivered name cleared, dated across this
    week."""
    import ingest
    from carry_excess import REPLACED_DIR
    _week, hold, jid = waiting_room(drive, inbox_id, d_from, d_to)
    done, exports, dirs, listing, replaced = Counter(), {}, {}, {}, {}
    pics = db.drive_ids_for_trips([r["id"] for r in rows])
    moves = []
    for r in rows:
        pic = pics.get(r["id"])
        if pic:
            moves.append((pic, hold, "ย้ายรูปรวมร่าง"))
        else:
            done["ไม่พบรูปรวมร่างบน Drive"] += 1
        if not r.get("customer_image"):
            continue
        wk = r["date_from"]
        if wk not in exports:
            exports[wk] = ingest.export_week_folder(drive, wk)
        if not exports[wk]:
            continue
        if wk not in dirs:
            dirs[wk] = {f["name"].strip(): f["id"] for f in drive.list_folders(exports[wk])}
        cdir = dirs[wk].get((r.get("category") or "").strip())
        if not cdir:
            continue
        if cdir not in listing:
            listing[cdir] = {i["name"]: i["id"] for i in drive.list_images(cdir)}
        cid = listing[cdir].get(r["customer_image"])
        if cid:
            if wk not in replaced:
                replaced[wk] = drive.ensure_folder(exports[wk], REPLACED_DIR)
            moves.append((cid, replaced[wk], "เก็บรูปลูกค้าของสัปดาห์เดิมออก"))
        else:
            done["ไม่พบรูปลูกค้าของสัปดาห์เดิม"] += 1

    def move(m):
        drive.move_file(m[0], m[1])
        return m[2]
    with ThreadPoolExecutor(max_workers=max(1, config.DRIVE_PARALLEL)) as ex:
        done.update(ex.map(move, moves))
    db.move_trips_to_job([r["id"] for r in rows], jid)
    fields = {}
    for r, new in redate_to_week.spread(rows, d_from, d_to):
        note = (f"ดึงกลับจาก {r['driver_name']} {r['date_from']}..{r['date_to']} มา {d_from}..{d_to} "
                f"{why} · วันที่ {r.get('trip_date')} → {new}")
        fields[r["id"]] = {"trip_date": new, "customer_image": None,
                           "note": f"{note} | {r['note']}" if r.get("note") else note}
    db.set_trip_fields(fields)
    done["ดึงแถวกลับ"] += len(fields)
    log(f"  → job #{jid} {far.HOLDING_RIDER} · {d_from}..{d_to}")
    return done, jid


GROUPS = ("2 W Saver", "2 W Standard", "4 W Standard")


def week_rows(d_from, d_to):
    """(staged, filed): the week's finished rows an earlier week may take, each with its group and
    oldest-driven first. Staged rows wait in _พร้อมอ่าน; filed rows are approved into a rider's
    job. Rows in the review queue, and rows no group takes, are not offered."""
    t, j = db.trips.c, db.jobs.c
    with db.engine.begin() as c:
        rows = [dict(r) for r in c.execute(
            select(t.id, t.committed, t.file_name, t.service_type, t.trip_date, t.trip_time,
                   t.customer_image, t.note, j.date_from, j.date_to, j.category, j.driver_name)
            .select_from(db.trips.join(db.jobs, j.id == t.job_id))
            .where(j.date_from == d_from, j.date_to == d_to, t.status == "done")).mappings().all()]
    staged, filed = [], []
    for r in rows:
        r["group"] = far.GROUP_OF.get(car_is_standard((r.get("service_type") or "").strip()))
        if not r["group"]:
            continue
        if r["driver_name"] == far.HOLDING_RIDER:
            staged.append(r)
        elif r["committed"] == 1:
            filed.append(r)

    def driven(r):
        return r.get("trip_date") or "", r.get("trip_time") or "", r["id"]
    return sorted(staged, key=driven), sorted(filed, key=driven)


def fill_plan(weeks, target):
    """{(earlier week, later week): [row]} so that no open week is short in a group while a later
    open week holds work of that group (Fiat 2026-11-23: "งานใน WK ก่อนหน้าต้องครบก่อน").

    weeks: [(range, have, staged, filed)] of the open weeks, oldest first, with have from
    db.week_group_counts and staged/filed from week_rows. A week's room is the target less what
    it has filed and what waits in its _พร้อมอ่าน. It takes from the next later week first, rows
    still waiting before rows already filed, earliest driven first; a row it takes leaves room in
    the week it came from, which that week then fills from the weeks after it."""
    room = {rng: {g: target - have.get(g, 0) - sum(r["group"] == g for r in staged) for g in GROUPS}
            for rng, have, staged, _filed in weeks}
    plan, taken = defaultdict(list), set()
    for i, (into, *_rest) in enumerate(weeks):
        for g in GROUPS:
            for came, _have, staged, filed in weeks[i + 1:]:
                for r in staged + filed:
                    if room[into][g] <= 0:
                        break
                    if r["group"] == g and r["id"] not in taken:
                        taken.add(r["id"])
                        plan[(into, came)].append(r)
                        room[into][g] -= 1
                        room[came][g] += 1
    return dict(plan)


def fill_earlier(drive, inbox_id, open_weeks, target=None, log=print):
    """Move the work later open weeks hold into the earlier open weeks still short of it. Returns
    the weeks whose rows changed. The rows land in the earlier week's _พร้อมอ่าน, so the round's
    filing that follows gives them a rider there."""
    target = config.WEEKLY_TARGET_PER_GROUP if target is None else target
    weeks = [(rng, db.week_group_counts(*rng), *week_rows(*rng)) for rng in sorted(open_weeks)]
    plan = fill_plan(weeks, target)
    for (into, came), rows in plan.items():
        log(f"⤺ เติมสัปดาห์ {into[0]} ให้ครบก่อน: ดึง "
            + " · ".join(f"{g} {n}" for g, n in sorted(Counter(r["group"] for r in rows).items()))
            + f" จากสัปดาห์ {came[0]}")
        done, _jid = bring_back(drive, inbox_id, *into, rows, log=log,
                                why=f"เพราะสัปดาห์ {into[0]} ยังไม่ครบ ต้องเติมสัปดาห์ก่อนให้เต็มก่อน")
        log("    " + " · ".join(f"{k} {v}" for k, v in done.most_common()))
    return {w for pair in plan for w in pair}

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
