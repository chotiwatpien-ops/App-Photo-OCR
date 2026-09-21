# -*- coding: utf-8 -*-
"""File a trip once, after the reading, where the slip itself says it belongs.

The pool used to choose the vehicle group, the rider and the delivered picture's name while the
only thing it knew was the album's name and what the free OCR could make of the chip. Everything
the AI reads afterwards can disagree with that guess, and then the row, the stitched picture, the
delivered picture and its NAME all have to move: W37 moved ~325 rows that way in one week, and a
delivered file ended up naming receipts that no longer existed.

So a paired picture now waits in <Week>/_พร้อมอ่าน/ with no owner. It is read from there, and only
then — knowing the service on the slip, the day it was driven and what the week still owes the
customer — does it go into a rider's folder, once.

    group   the Service Type on the row (a car is the Standard car)
    rider   whoever still has room this week, same as before (distribute.Allocator)
    week    this one while its group is under target; otherwise the work stays put and is
            reported, because the pool is what decides to send new work to next week
"""
import sys
from collections import Counter

from sqlalchemy import select

import config
import db
import distribute
from pipeline import car_is_standard

HOLDING_RIDER = "(รออ่าน)"
HOLDING_DIR = "_พร้อมอ่าน"
GROUP_OF = {"Saver Bike": "2 W Saver", "Standard Bike": "2 W Standard",
            "Standard Car": "4 W Standard", "Saver Car": "4 W Standard"}


def holding_job_ids(d_from, d_to):
    """Jobs that hold pictures nobody owns yet — one per week, made by the round."""
    return [j["id"] for j in db.jobs_by_week().get((d_from, d_to), [])
            if (j.get("driver_name") or "") == HOLDING_RIDER]


def staged_rows(d_from, d_to):
    """[row] read and waiting to be filed, oldest first so a week fills in the order it was driven."""
    ids = holding_job_ids(d_from, d_to)
    if not ids:
        return []
    t = db.trips.c
    with db.engine.begin() as c:
        rows = [dict(r) for r in c.execute(
            select(t.id, t.job_id, t.file_name, t.service_type, t.trip_date, t.trip_time, t.note)
            .where(t.job_id.in_(ids), t.status == "done")).mappings().all()]
    rows.sort(key=lambda r: (r.get("trip_date") or "", r.get("trip_time") or "", r["id"]))
    return rows


def room_left(d_from, d_to, target=None):
    """{group: how many more trips this week may take} — repeats and voided rows never count."""
    target = config.WEEKLY_TARGET_PER_GROUP if target is None else target
    have = db.week_group_counts(d_from, d_to)
    return {g: target - have.get(g, 0) for g in set(GROUP_OF.values()) | set(have)}


def file_rows(drive, week_id, d_from, d_to, rows=None, target=None, log=print):
    """Move each read row into the rider folder its own slip points at. Returns a summary."""
    rows = staged_rows(d_from, d_to) if rows is None else rows
    out = Counter()
    if not rows:
        return {"filed": 0, "left": 0, "by_group": {}, "jobs": set(), "reasons": out}
    room = room_left(d_from, d_to, target)
    pool_names = {k: [n for n, kd in db.name_pool_for(k[0]) if kd == k[1]]
                  for k in (("2W", "Win"), ("2W", "Home"), ("4W", "Taxi"), ("4W", "Home"))}
    alloc = distribute.Allocator(drive, week_id, pool_names, log=log,
                                 styles=db.rider_styles(week_id))
    pics = db.drive_ids_for_trips([r["id"] for r in rows])
    jobs_seen, by_group = set(), Counter()
    for r in rows:
        svc = car_is_standard((r.get("service_type") or "").strip())
        group = GROUP_OF.get(svc)
        if not group:
            out["ยังไม่รู้ประเภทงาน"] += 1
            continue
        if room.get(group, 0) <= 0:
            out[f"{group} ครบเป้าแล้ว — รอสัปดาห์หน้า"] += 1
            continue
        wheel = "2W" if group.startswith("2 W") else "4W"
        fid, err = alloc.folder_for(group, wheel)
        if err:
            out[err[:60]] += 1
            continue
        rider = alloc.rider_at(fid)
        jid = db.find_job_by_folder(fid, d_from) or db.find_job(rider, d_from, d_to, category=group)
        if jid is None:
            jid = db.create_job(rider, "Trips", d_from, d_to, category=group,
                                folder_name=f"{group}/{distribute.bare(rider)}", drive_folder_id=fid)
            log(f"  + job #{jid} {rider} · {group}")
        pic = pics.get(r["id"])
        if pic:
            try:
                drive.move_file(pic, fid)
            except Exception as e:  # noqa: BLE001 — the row still belongs to the rider
                out[f"ย้ายรูปไม่สำเร็จ: {str(e)[:40]}"] += 1
        else:
            out["ไม่พบรูปต้นฉบับบน Drive"] += 1
        db.move_trips_to_job([r["id"]], jid)
        note = f"ลงที่หลังอ่าน: {svc} → {group} · {rider}"
        db.update_trip(r["id"], {"note": f"{note} | {r['note']}" if r.get("note") else note})
        room[group] -= 1
        by_group[group] += 1
        jobs_seen.add(jid)
    filed = sum(by_group.values())
    if filed:
        log("📥 ลงที่หลังอ่าน " + " · ".join(f"{g} {n}" for g, n in sorted(by_group.items())))
    for why, n in out.most_common():
        log(f"  ⏸ {n} แถวยังไม่ได้ลงที่: {why}")
    return {"filed": filed, "left": sum(out.values()), "by_group": dict(by_group),
            "jobs": jobs_seen, "reasons": out}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="ลงที่ให้แถวที่อ่านแล้วแต่ยังไม่มีเจ้าของ (โหมดอ่านก่อนลงที่)")
    ap.add_argument("--week", required=True, help="ชื่อโฟลเดอร์สัปดาห์บน Drive")
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    db.init_db()
    rows = staged_rows(a.d_from, a.d_to)
    print(f"{a.d_from}..{a.d_to} · แถวที่อ่านแล้วรอลงที่ {len(rows)}")
    print("  ตามประเภทงาน: " + " · ".join(f"{k or '?'} {v}" for k, v in
                                           Counter(r.get("service_type") for r in rows).most_common()))
    if not rows or not a.apply:
        print("\n(รายงานอย่างเดียว — ใส่ --apply เพื่อลงที่จริง)" if rows else "ไม่มีอะไรต้องลงที่ ✔")
        return 0
    import roster
    drive = roster._drive()
    wk = next((f for f in drive.list_folders(config.DRIVE_INBOX_FOLDER_ID)
               if f["name"].strip() == a.week.strip()), None)
    if wk is None:
        print(f"✗ ไม่พบสัปดาห์ {a.week!r} ใน Inbox")
        return 1
    res = file_rows(drive, wk["id"], a.d_from, a.d_to, rows=rows)
    print(f"\nลงที่แล้ว {res['filed']} แถว · ยังค้าง {res['left']}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
