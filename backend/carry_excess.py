# -*- coding: utf-8 -*-
"""Carry a group's rows above the week's target into the following week, latest trips first.

The customer takes a fixed number of trips per vehicle group per week. Once the chip audit and
the rehome have put every row where its slip says, a group can hold more than that number; the
rows above it go to the next week's file rather than being cut (Fiat, 2026-09-10). Which rows:
the latest-dated first, because those are nearest the week they are moving into and the choice
needs no explaining. Who drove them is not a factor.

What moves, per row:
  1. the row, to a job for the same rider under next week's dates and the same group — the one
     that exists, else one is made with its own rider folder under <next week>/<group>/;
  2. the stitched picture, into that rider folder;
  3. the delivered picture, OUT of this week's Export Pic into its _แทนที่แล้ว holding folder —
     it was named for this week (WK36-…), and next week's export names its own (WK37-…), so the
     row's customer_image is cleared and the exporter makes it afresh under the new name.
  4. the date: the carried rows are dated across next week in the order they were driven
     (redate_to_week.spread), the slip's own day kept in the note. They were first left as
     driven, and Fiat reversed that on seeing the file the same evening: a W37 file must not
     carry W36 dates ("วันที่ต้องไม่ใช่ WK ที่ Run").
Nothing is deleted and no row is re-read.

    python carry_excess.py --week "Week 31 Aug-6 Sep" --from 2026-08-31 --to 2026-09-06 --target 1470
    python carry_excess.py ... --apply
"""
import argparse
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import select

import db
import redate_to_week
from distribute import NUM_PREFIX, bare, folder_label

REPLACED_DIR = "_แทนที่แล้ว"
GROUPS = ("2 W Saver", "2 W Standard", "4 W Standard")


MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
RANGE_RE = re.compile(r"(\d{1,2})(?:\s*([A-Za-z]{3}))?\s*-\s*(\d{1,2})\s*([A-Za-z]{3})", re.IGNORECASE)


def next_week_folder(week_name, d_from, d_to):
    """'Week 31 Aug-6 Sep' -> 'Week 7-13 Sep', spelled the way Ops spells it: the month once
    when both days share it, twice when they do not, whatever came before the dates kept.

    pool.next_week_name does the same, but importing pool pulls in the OCR stack, which the
    carry runner does not install — run #1 died on that import in thirty seconds."""
    n_from, n_to = (date.fromisoformat(d) + timedelta(days=7) for d in (d_from, d_to))
    m = RANGE_RE.search(week_name or "")
    head = week_name[:m.start()].rstrip() if m else "Week"
    span = (f"{n_from.day}-{n_to.day} {MONTH_ABBR[n_to.month - 1]}" if n_from.month == n_to.month
            else f"{n_from.day} {MONTH_ABBR[n_from.month - 1]}-{n_to.day} {MONTH_ABBR[n_to.month - 1]}")
    return f"{head} {span}".strip()


def next_week(d_from, d_to):
    a, b = (date.fromisoformat(d) + timedelta(days=7) for d in (d_from, d_to))
    return a.isoformat(), b.isoformat()


def excess_rows(d_from, d_to, target, groups=GROUPS):
    """{group: [(row, job)...]} — the rows above target in each group, latest trip first."""
    jobs = {j["id"]: j for j in db.jobs_by_week().get((d_from, d_to), [])}
    if not jobs:
        return {}, {}, jobs
    t = db.trips.c
    with db.engine.begin() as c:
        rows = [dict(r) for r in c.execute(
            select(t.id, t.job_id, t.file_name, t.trip_date, t.trip_time, t.customer_image, t.note)
            .where(t.job_id.in_(list(jobs)), t.status == "done")).mappings().all()]
    per = defaultdict(list)
    for r in rows:
        per[(jobs[r["job_id"]].get("category") or "").strip()].append(r)
    counts = {g: len(per.get(g, [])) for g in groups}
    out = {}
    for g in groups:
        n = counts[g] - target
        if n <= 0:
            continue
        ranked = sorted(per[g], key=lambda r: (r.get("trip_date") or "", r.get("trip_time") or "", r["id"]),
                        reverse=True)
        out[g] = [(r, jobs[r["job_id"]]) for r in ranked[:n]]
    return out, counts, jobs


class Weeks:
    """This week's and next week's folders on Drive, read once."""

    def __init__(self, drive, inbox_id, week_name, next_name, exports_week_id):
        self.drive = drive
        tops = {f["name"].strip(): f["id"] for f in drive.list_folders(inbox_id)}
        self.this_id = tops.get(week_name.strip())
        self.next_id = tops.get(next_name.strip()) or drive.ensure_folder(inbox_id, next_name)
        self.next_groups = {g["name"].strip(): g["id"] for g in drive.list_folders(self.next_id)}
        self.exports_week_id = exports_week_id
        self.export_dir = ({g["name"].strip(): g["id"] for g in drive.list_folders(exports_week_id)}
                           if exports_week_id else {})
        self.riders = {}
        self.made = 0

    def _riders(self, group):
        if group not in self.riders:
            gid = self.next_groups.get(group) or self.drive.ensure_folder(self.next_id, group)
            self.next_groups[group] = gid
            self.riders[group] = {bare(f["name"]).lower(): (f["id"], f["name"])
                                  for f in self.drive.list_folders(gid)}
        return self.riders[group]

    def rider_folder(self, group, name):
        have = self._riders(group)
        hit = have.get(bare(name).lower())
        if hit:
            return hit[0], False
        taken = [int(re.sub(r"[^0-9]", "", m.group(0))) for _f, lab in have.values()
                 for m in [NUM_PREFIX.match(lab)] if m and re.search(r"[0-9]", m.group(0))]
        label = folder_label(max(taken, default=0) + 1, bare(name))
        fid = self.drive.ensure_folder(self.next_groups[group], label)
        have[bare(name).lower()] = (fid, label)
        self.made += 1
        return fid, True

    def find_in(self, folder_id, file_name):
        """A picture by name in a folder, from a listing taken once per folder.

        Listing the folder again for every row is what timed run #3 out at sixty minutes:
        the week's Export Pic group holds ~2,000 pictures and was read from Drive once per row,
        six hundred times over. A folder only ever loses pictures here, so one listing serves."""
        if not hasattr(self, "_listing"):
            self._listing = {}
        if folder_id not in self._listing:
            self._listing[folder_id] = {i["name"]: i["id"] for i in self.drive.list_images(folder_id)}
        return self._listing[folder_id].get(file_name)

    def replaced_dir(self):
        if not self.exports_week_id:
            return None
        if REPLACED_DIR not in self.export_dir:
            self.export_dir[REPLACED_DIR] = self.drive.ensure_folder(self.exports_week_id, REPLACED_DIR)
        return self.export_dir[REPLACED_DIR]


def apply(drive, wk, d_from, d_to, excess, log=print):
    n_from, n_to = next_week(d_from, d_to)
    done = Counter()
    moved = []
    for group, items in excess.items():
        by_rider = defaultdict(list)
        for r, j in items:
            by_rider[(j["driver_name"], j.get("admin"))].append((r, j))
        for (name, admin), rows in by_rider.items():
            fid, made = wk.rider_folder(group, name)
            jid = db.find_job(name, n_from, n_to, category=group, admin=admin)
            if not jid:
                jid = db.create_job(name, "Trips", n_from, n_to, category=group,
                                    folder_name=f"{group}/{bare(name)}", admin=admin, drive_folder_id=fid)
                db.set_job_status(jid, "committed")   # holds finished rows only; "running" would be re-reconciled every round
                log(f"  + job #{jid} {name} · {group} · {n_from}..{n_to}" + (" (เปิดโฟลเดอร์ใหม่)" if made else ""))
            for r, j in rows:
                src = j.get("drive_folder_id")
                pic = wk.find_in(src, r["file_name"]) if src else None
                if pic:
                    drive.move_file(pic, fid)
                    done["ย้ายรูปรวมร่าง"] += 1
                else:
                    done["หารูปรวมร่างในโฟลเดอร์เดิมไม่เจอ"] += 1
                if r.get("customer_image") and wk.exports_week_id:
                    cdir = wk.export_dir.get(group)
                    cid = wk.find_in(cdir, r["customer_image"]) if cdir else None
                    if cid:
                        drive.move_file(cid, wk.replaced_dir())
                        done["เก็บรูปลูกค้าเดิมออก"] += 1
                    else:
                        done["หารูปลูกค้าเดิมไม่เจอ"] += 1
                db.move_trips_to_job([r["id"]], jid)
                note = f"ยกไปสัปดาห์ {n_from}..{n_to} เพราะ {group} เกินเป้า (เดิม job #{j['id']})"
                db.update_trip(r["id"], {"customer_image": None,
                                         "note": f"{note} | {r['note']}" if r.get("note") else note})
                r["note"] = f"{note} | {r['note']}" if r.get("note") else note
                moved.append(r)
                done["ย้ายแถว"] += 1
                if done["ย้ายแถว"] % 50 == 0:
                    log(f"    ย้ายแล้ว {done['ย้ายแถว']} แถว")
    # the carried rows take dates inside the week they now belong to, spread in driven order
    done["ลงวันที่ในสัปดาห์หน้า"] = redate_to_week.apply(redate_to_week.spread(moved, n_from, n_to),
                                                       n_from, n_to, log=log)
    return done


def main(argv=None):
    ap = argparse.ArgumentParser(description="ยกงานที่เกินเป้าของแต่ละกลุ่มไปสัปดาห์ถัดไป")
    ap.add_argument("--week", required=True, help="ชื่อโฟลเดอร์สัปดาห์นี้บน Drive")
    ap.add_argument("--next-week", help="ชื่อโฟลเดอร์สัปดาห์หน้า (ค่าเริ่มต้น: ตั้งจากวันที่)")
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--target", type=int, default=1470, help="งานต่อกลุ่มที่ลูกค้ารับ")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    db.init_db()
    import config
    import roster
    from ingest import week_label
    drive = roster._drive()

    excess, counts, _jobs = excess_rows(a.d_from, a.d_to, a.target)
    print(f"{a.d_from}..{a.d_to} · เป้า {a.target}/กลุ่ม")
    for g in GROUPS:
        over = len(excess.get(g, []))
        print(f"    {g:<14} มี {counts.get(g, 0):>5}   " + (f"เกิน {over} → ยกไปสัปดาห์หน้า" if over else "ไม่เกิน"))
    if not excess:
        print("ไม่มีกลุ่มไหนเกิน")
        return 0
    for g, items in excess.items():
        dates = Counter(r.get("trip_date") for r, _j in items)
        print(f"  {g}: วันที่ที่ถูกยก " + " · ".join(f"{d} {n}" for d, n in sorted(dates.items(), reverse=True)))
    if not a.apply:
        print("\n(รายงานอย่างเดียว — ใส่ --apply เพื่อยกจริง)")
        return 0

    nxt = a.next_week or next_week_folder(a.week, a.d_from, a.d_to)
    if not nxt:
        print("✗ ตั้งชื่อโฟลเดอร์สัปดาห์หน้าจากชื่อสัปดาห์นี้ไม่ได้ — ใส่ --next-week")
        return 1
    inbox = config.DRIVE_INBOX_FOLDER_ID
    exports = next((f for f in drive.list_folders(inbox) if f["name"].strip() == "Export Pic"), None)
    exports_week = (next((f["id"] for f in drive.list_folders(exports["id"]) if f["name"] == week_label(a.d_from)), None)
                    if exports else None)
    wk = Weeks(drive, inbox, a.week, nxt, exports_week)
    done = apply(drive, wk, a.d_from, a.d_to, excess)
    print("\nทำแล้ว: " + " · ".join(f"{k} {v}" for k, v in done.most_common()))
    print(f"เปิดโฟลเดอร์ไรเดอร์ใหม่ใน '{nxt}' {wk.made} โฟลเดอร์")
    print("ขั้นต่อไป: ingest ด้วย exports_only ทั้งสองสัปดาห์ — รูปลูกค้าของแถวที่ยกจะถูกสร้างใหม่ในชื่อสัปดาห์หน้า")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
