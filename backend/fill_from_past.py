# -*- coding: utf-8 -*-
"""Bring a group up to the week's target with trips copied from earlier weeks.

The last resort, after the week's own parked work is back in (Fiat, 2026-09-10: "งานที่ขาด …
Random เอา Week เก่ามาเติม"). It is a copy, not a move: the earlier week keeps its row and its
picture, and this week gets a new row that says the same thing under a job of the same rider.
The date on the row is the date on the slip and stays that. Every copied row carries a note
naming the week and the row it came from, so it can always be told apart from the week's own
work and taken out again.

Which rows: drawn at random from the finished, committed rows of the same group in every
earlier week, with a fixed seed so the same draw can be repeated. Rows already parked as
duplicates or voided are never drawn, and a row is never drawn twice.

    python fill_from_past.py --week "Week 31 Aug-6 Sep" --from 2026-08-31 --to 2026-09-06 \
        --group "2 W Standard" --need 300 [--seed 36]            # report
    python fill_from_past.py ... --apply                         # copy
"""
import argparse
import random
import re
import sys
from collections import Counter, defaultdict

from sqlalchemy import insert, select

import db
from distribute import NUM_PREFIX, bare, folder_label

SERVICE_OF = {"2 W Saver": "Saver Bike", "2 W Standard": "Standard Bike", "4 W Standard": "Standard Car"}
# what a copied row must NOT carry over: its identity, its owner, the picture bookkeeping that
# belongs to the original, and the delivered name this week's export will make afresh
RESET = {"id", "job_id", "customer_image", "source_url", "image_hash", "batch_name",
         "duplicate_of", "merged_into", "image_blob", "note"}


def candidates(d_from, group):
    """Finished, committed rows of this group from every week before d_from, keyed by row id."""
    weeks = db.jobs_by_week()
    jobs = {}
    for (a, b), js in weeks.items():
        if a < d_from:
            for j in js:
                if (j.get("category") or "").strip() == group:
                    jobs[j["id"]] = (j, a, b)
    if not jobs:
        return {}
    t = db.trips.c
    want = SERVICE_OF[group]
    with db.engine.begin() as c:
        rows = [dict(r) for r in c.execute(
            select(*db.TRIP_COLS).where(t.job_id.in_(list(jobs)), t.status == "done", t.committed == 1,
                                        t.duplicate_of.is_(None), t.service_type == want)).mappings().all()]
    return {r["id"]: (r, *jobs[r["job_id"]]) for r in rows}


def draw(cands, need, seed):
    ids = sorted(cands)
    rng = random.Random(seed)
    rng.shuffle(ids)
    return [cands[i] for i in ids[:need]]


class Target:
    """This week's group folder and rider folders, read once."""

    def __init__(self, drive, week_id, group):
        self.drive = drive
        gid = next((g["id"] for g in drive.list_folders(week_id) if g["name"].strip() == group), None)
        self.gid = gid or drive.ensure_folder(week_id, group)
        self.riders = {bare(f["name"]).lower(): (f["id"], f["name"]) for f in drive.list_folders(self.gid)}
        self.made = 0

    def rider_folder(self, name):
        hit = self.riders.get(bare(name).lower())
        if hit:
            return hit[0], False
        taken = [int(re.sub(r"[^0-9]", "", m.group(0))) for _f, lab in self.riders.values()
                 for m in [NUM_PREFIX.match(lab)] if m and re.search(r"[0-9]", m.group(0))]
        label = folder_label(max(taken, default=0) + 1, bare(name))
        fid = self.drive.ensure_folder(self.gid, label)
        self.riders[bare(name).lower()] = (fid, label)
        self.made += 1
        return fid, True


def file_id(url):
    m = re.search(r"[-\w]{25,}", url or "")
    return m.group(0) if m else None


def apply(drive, tgt, d_from, d_to, group, picks, log=print):
    done = Counter()
    by_rider = defaultdict(list)
    for r, j, a, b in picks:
        by_rider[(j["driver_name"], j.get("admin"))].append((r, j, a, b))
    for (name, admin), items in by_rider.items():
        fid, made = tgt.rider_folder(name)
        jid = db.find_job(name, d_from, d_to, category=group, admin=admin)
        if not jid:
            jid = db.create_job(name, "Trips", d_from, d_to, category=group,
                                folder_name=f"{group}/{bare(name)}", admin=admin, drive_folder_id=fid)
            # every row it will ever hold is already finished; left as "running" the round
            # would re-reconcile it, seven seconds a job, a hundred and fifty jobs at a time
            db.set_job_status(jid, "committed")
            log(f"  + job #{jid} {name} · {group}" + (" (เปิดโฟลเดอร์ใหม่)" if made else ""))
        for r, j, a, b in items:
            # a Drive link carries the file id; a local stand-in's link IS the path
            src = file_id(r.get("source_url")) or r.get("source_url")
            if not src:
                done["ไม่มีลิงก์รูปต้นทาง"] += 1
                continue
            try:
                data = drive.download(src)
            except Exception as e:                                 # noqa: BLE001
                done[f"โหลดรูปไม่ได้: {str(e)[:30]}"] += 1
                continue
            new_id = drive.create_file(fid, r["file_name"], data, r.get("image_mime") or "image/jpeg")
            vals = {k: v for k, v in r.items() if k not in RESET}
            vals.update(job_id=jid, source_url=f"https://drive.google.com/file/d/{new_id}/view",
                        customer_image=None,
                        note=f"เติมจากสัปดาห์ {a}..{b} (สำเนาของแถว #{r['id']} · วันที่บนสลิปคงไว้)")
            with db.engine.begin() as c:
                c.execute(insert(db.trips).values(**vals))
            done["คัดลอกแถว"] += 1
    return done


def main(argv=None):
    ap = argparse.ArgumentParser(description="เติมงานของกลุ่มให้ถึงเป้าด้วยสำเนาจากสัปดาห์ก่อน ๆ")
    ap.add_argument("--week", required=True, help="ชื่อโฟลเดอร์สัปดาห์นี้บน Drive")
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--group", required=True, choices=sorted(SERVICE_OF))
    ap.add_argument("--need", type=int, required=True, help="จำนวนแถวที่ต้องเติม")
    ap.add_argument("--seed", type=int, default=36)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    db.init_db()
    cands = candidates(a.d_from, a.group)
    print(f"{a.group}: แถวในสัปดาห์ก่อน ๆ ที่หยิบได้ {len(cands)} · ต้องการ {a.need} · seed {a.seed}")
    if len(cands) < a.need:
        print(f"  ⚠ มีไม่พอ — จะเติมได้แค่ {len(cands)}")
    picks = draw(cands, a.need, a.seed)
    wk = Counter(f"{a_}..{b_}" for _r, _j, a_, b_ in picks)
    print("  หยิบจาก: " + " · ".join(f"{k} {n}" for k, n in sorted(wk.items())))
    riders = Counter(j["driver_name"] for _r, j, _a, _b in picks)
    print(f"  กระจายใน {len(riders)} ไรเดอร์ · มากสุด " + ", ".join(f"{n} {c}" for n, c in riders.most_common(5)))
    if not a.apply:
        print("\n(รายงานอย่างเดียว — ใส่ --apply เพื่อคัดลอกจริง)")
        return 0
    import config
    import roster
    drive = roster._drive()
    inbox = config.DRIVE_INBOX_FOLDER_ID
    week = next((f for f in drive.list_folders(inbox) if f["name"].strip() == a.week.strip()), None)
    if not week:
        print(f"✗ ไม่พบโฟลเดอร์สัปดาห์ '{a.week}'")
        return 1
    tgt = Target(drive, week["id"], a.group)
    done = apply(drive, tgt, a.d_from, a.d_to, a.group, picks)
    print("\nทำแล้ว: " + " · ".join(f"{k} {v}" for k, v in done.most_common()))
    print(f"เปิดโฟลเดอร์ไรเดอร์ใหม่ {tgt.made} โฟลเดอร์")
    print("ขั้นต่อไป: ingest ด้วย exports_only — รูปลูกค้าของแถวที่เติมจะถูกสร้างในชื่อสัปดาห์นี้")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
