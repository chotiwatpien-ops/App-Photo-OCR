# -*- coding: utf-8 -*-
"""Put every row's stitched picture in the folder of the job that holds the row.

The rehome and the carry move a row to another job and look for its picture in the old job's
folder by drive_folder_id. On 2026-09-10 that found 44 of 601: the rider folders hold their
pictures under the names Ops uploaded ('LINE_ALBUM_…', '168711_168712.jpg', 'S__…'), many older
jobs carry no drive_folder_id at all, and the '…_0+0_' names from the overwrite bug are shared
by several rows. Excel and Export Pic were right — they follow the row — but the working
folders Ops read still showed a Saver trip's picture under 2 W Standard.

So this reads the week's rider folders once, indexes every picture by name, and for each row
whose picture sits somewhere other than its job's folder, moves it there. A name that appears
more than once is left alone and listed: no picture is moved on a guess. Rows whose job has no
folder yet get one, numbered after the highest in use. Nothing is deleted, no row is changed.

    python reconcile_pictures.py --week "Week 31 Aug-6 Sep" --from 2026-08-31 --to 2026-09-06
    python reconcile_pictures.py ... --apply
"""
import argparse
import re
import sys
from collections import Counter, defaultdict

from sqlalchemy import select

import db
from distribute import NUM_PREFIX, bare, folder_label

GROUPS = ("2 W Saver", "2 W Standard", "4 W Standard")


class Week:
    """Every rider folder of the week and every picture in them, read once."""

    def __init__(self, drive, week_id):
        self.drive = drive
        self.group_dir = {g["name"].strip(): g["id"] for g in drive.list_folders(week_id)
                          if g["name"].strip() in GROUPS}
        self.week_id = week_id
        self.folders = {}            # folder id -> (group, label)
        self.by_name = defaultdict(list)   # picture name -> [(file id, folder id)]
        self.riders = {g: {} for g in GROUPS}   # group -> bare name lower -> (folder id, label)
        for g, gid in self.group_dir.items():
            for f in drive.list_folders(gid):
                self.folders[f["id"]] = (g, f["name"])
                self.riders[g][bare(f["name"]).lower()] = (f["id"], f["name"])
                for i in drive.list_images(f["id"]):
                    self.by_name[i["name"]].append((i["id"], f["id"]))
        self.made = 0

    def folder_for(self, group, name):
        have = self.riders.setdefault(group, {})
        hit = have.get(bare(name).lower())
        if hit:
            return hit[0], False
        gid = self.group_dir.get(group) or self.drive.ensure_folder(self.week_id, group)
        self.group_dir[group] = gid
        taken = [int(re.sub(r"[^0-9]", "", m.group(0))) for _f, lab in have.values()
                 for m in [NUM_PREFIX.match(lab)] if m and re.search(r"[0-9]", m.group(0))]
        label = folder_label(max(taken, default=0) + 1, bare(name))
        fid = self.drive.ensure_folder(gid, label)
        have[bare(name).lower()] = (fid, label)
        self.folders[fid] = (group, label)
        self.made += 1
        return fid, True


def plan(wk, d_from, d_to):
    """(moves, ambiguous, missing, jobs_without_folder) for the week's finished rows."""
    jobs = {j["id"]: j for j in db.jobs_by_week().get((d_from, d_to), [])}
    if not jobs:
        return [], [], [], set(), jobs
    t = db.trips.c
    with db.engine.begin() as c:
        rows = [dict(r) for r in c.execute(
            select(t.id, t.job_id, t.file_name).where(t.job_id.in_(list(jobs)), t.status == "done")).mappings().all()]
    moves, ambiguous, missing, need_folder = [], [], [], set()
    for r in rows:
        j = jobs[r["job_id"]]
        group = (j.get("category") or "").strip()
        if group not in GROUPS:
            continue
        hits = wk.by_name.get(r["file_name"], [])
        if not hits:
            missing.append((r, j))
            continue
        if len(hits) > 1:
            ambiguous.append((r, j, hits))
            continue
        pic_id, in_folder = hits[0]
        target = j.get("drive_folder_id")
        if not target or target not in wk.folders:
            target = wk.riders.get(group, {}).get(bare(j["driver_name"]).lower(), (None,))[0]
            if not target:
                need_folder.add(j["id"])
        if target and in_folder == target:
            continue
        moves.append((r, j, pic_id, in_folder, target))
    return moves, ambiguous, missing, need_folder, jobs


def apply(wk, moves, jobs, log=print):
    done = Counter()
    for r, j, pic_id, in_folder, target in moves:
        if not target:
            target, made = wk.folder_for((j.get("category") or "").strip(), j["driver_name"])
            if made:
                log(f"  + โฟลเดอร์ {wk.folders[target][1]} ใน {j.get('category')}")
        wk.drive.move_file(pic_id, target)
        done["ย้ายรูป"] += 1
    return done


def main(argv=None):
    ap = argparse.ArgumentParser(description="จัดรูปรวมร่างให้อยู่โฟลเดอร์ของ job ที่ถือแถว")
    ap.add_argument("--week", required=True)
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    db.init_db()
    import config
    import roster
    drive = roster._drive()
    week = next((f for f in drive.list_folders(config.DRIVE_INBOX_FOLDER_ID)
                 if f["name"].strip() == a.week.strip()), None)
    if not week:
        print(f"✗ ไม่พบโฟลเดอร์สัปดาห์ '{a.week}'")
        return 1
    wk = Week(drive, week["id"])
    print(f"อ่านโฟลเดอร์ไรเดอร์ {len(wk.folders)} โฟลเดอร์ · รูป {sum(len(v) for v in wk.by_name.values())} ใบ")
    moves, ambiguous, missing, need_folder, jobs = plan(wk, a.d_from, a.d_to)
    by = Counter((wk.folders.get(f, ('?', '?'))[0], (j.get("category") or "").strip()) for _r, j, _p, f, _t in moves)
    print(f"\nรูปที่อยู่ผิดโฟลเดอร์และย้ายได้แน่นอน: {len(moves)}")
    for (frm, to), n in by.most_common():
        print(f"    {frm} → {to}: {n}")
    print(f"ชื่อซ้ำหลายที่ ไม่ย้าย (ต้องดูเอง): {len(ambiguous)}")
    for r, j, hits in ambiguous[:5]:
        print(f"    {r['file_name']} · {len(hits)} ที่ · job #{j['id']} {j['driver_name']}")
    print(f"หาไม่เจอในสัปดาห์นี้เลย: {len(missing)}")
    print(f"job ที่ยังไม่มีโฟลเดอร์ จะเปิดให้: {len(need_folder)}")
    if not a.apply:
        print("\n(รายงานอย่างเดียว — ใส่ --apply เพื่อย้ายจริง)")
        return 0
    done = apply(wk, moves, jobs)
    print("\nทำแล้ว: " + " · ".join(f"{k} {v}" for k, v in done.most_common()) + f" · เปิดโฟลเดอร์ใหม่ {wk.made}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
