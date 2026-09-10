# -*- coding: utf-8 -*-
"""Put every row under a job of the group its service says — and its pictures with it.

A row's Service Type and its job's group disagree after the chip audit writes what the slip
says: 'Saver Bike' on a row whose job was opened under 2 W Standard. Fixing the label alone
leaves everything downstream pointing the old way, because the group folder a customer picture
is delivered to comes from job.category, not from the row (ingest.export_only), and the rider
folder the stitched picture sits in on Drive is the old group's too. Ops reads both, and both
must say what the row says (Fiat, 2026-09-10: "ย้ายงานกับ Excel ต้องตรงกัน").

So for every finished row whose service names a different group than its job:
  1. the row moves to a job of that group for the same rider and week — the one that exists,
     else one is made, with its own rider folder under Week/<group>/ (a person may hold a
     folder in each group; the allocator already counts one 21 across both);
  2. the stitched picture moves from the old rider folder to the new one;
  3. the delivered customer picture moves from Export Pic/<week>/<old group>/ to /<new group>/,
     keeping its name — export_only never removes a picture from a group it has left, so a copy
     under the old name would otherwise sit there contradicting the sheet.
Nothing is deleted and no row is re-read. The numbers on the row are untouched; only whose
week and which folder it is counted in change, and the note says so.

    python rehome_by_service.py --from 2026-08-31 --to 2026-09-06            # report
    python rehome_by_service.py --from 2026-08-31 --to 2026-09-06 --apply    # move
"""
import argparse
import re
import sys
from collections import Counter, defaultdict

from sqlalchemy import select

import db
from distribute import NUM_PREFIX, bare, folder_label

# The four groups and the service each one delivers. A service outside these (a car reading
# 'Saver Car' where no 4 W Saver group exists) has nowhere to go and is reported, not moved.
GROUP_OF = {"Saver Bike": "2 W Saver", "Standard Bike": "2 W Standard",
            "Standard Car": "4 W Standard", "Saver Car": "4 W Saver"}
CUSTOMER_ID_RE = re.compile(r"[-\w]{25,}")


def rows_needing_move(d_from, d_to):
    """[(row, job, target group)] for finished rows whose service names another group."""
    jobs = {j["id"]: j for j in db.jobs_by_week().get((d_from, d_to), [])}
    if not jobs:
        return [], jobs
    t = db.trips.c
    with db.engine.begin() as c:
        rows = [dict(r) for r in c.execute(
            select(t.id, t.job_id, t.file_name, t.service_type, t.customer_image, t.note)
            .where(t.job_id.in_(list(jobs)), t.status == "done").order_by(t.id)).mappings().all()]
    out = []
    for r in rows:
        j = jobs[r["job_id"]]
        want = GROUP_OF.get((r["service_type"] or "").strip())
        if want and want != (j.get("category") or "").strip():
            out.append((r, j, want))
    return out, jobs


class Mover:
    """One week's folders on Drive, read once, with the moves done through it."""

    def __init__(self, drive, week_id, exports_week_id, log=print):
        self.drive, self.week_id, self.exports_week_id, self.log = drive, week_id, exports_week_id, log
        self.group_dir = {g["name"].strip(): g["id"] for g in drive.list_folders(week_id)}
        self.export_dir = ({g["name"].strip(): g["id"] for g in drive.list_folders(exports_week_id)}
                           if exports_week_id else {})
        self.riders = {}          # group -> {bare name lower: (folder id, label)}
        self.made = 0

    def _riders(self, group):
        if group not in self.riders:
            gid = self.group_dir.get(group) or self.drive.ensure_folder(self.week_id, group)
            self.group_dir[group] = gid
            self.riders[group] = {bare(f["name"]).lower(): (f["id"], f["name"])
                                  for f in self.drive.list_folders(gid)}
        return self.riders[group]

    def rider_folder(self, group, name):
        """The rider's folder under Week/<group>/, made with the next number if absent."""
        have = self._riders(group)
        hit = have.get(bare(name).lower())
        if hit:
            return hit[0], False
        # the next number after the highest in use, not count+1: a group whose numbering has a
        # gap would otherwise hand out a prefix that already exists on another rider's folder
        taken = [int(re.sub(r"[^0-9]", "", m.group(0))) for _f, lab in have.values()
                 for m in [NUM_PREFIX.match(lab)] if m and re.search(r"[0-9]", m.group(0))]
        label = folder_label(max(taken, default=0) + 1, bare(name))
        fid = self.drive.ensure_folder(self.group_dir[group], label)
        have[bare(name).lower()] = (fid, label)
        self.made += 1
        return fid, True

    def find_in(self, folder_id, file_name):
        return next((i["id"] for i in self.drive.list_images(folder_id) if i["name"] == file_name), None)

    def export_group(self, group):
        if not self.exports_week_id:
            return None
        if group not in self.export_dir:
            self.export_dir[group] = self.drive.ensure_folder(self.exports_week_id, group)
        return self.export_dir[group]


def apply(drive, mv, d_from, d_to, moves, log=print):
    """Do the three moves for every row; returns a Counter of what happened."""
    grouped = defaultdict(list)
    for r, j, want in moves:
        grouped[(j["driver_name"], j.get("admin"), want)].append((r, j))
    done = Counter()
    for (name, admin, want), items in grouped.items():
        fid, made = mv.rider_folder(want, name)
        jid = db.find_job(name, d_from, d_to, category=want, admin=admin)
        if not jid:
            jid = db.create_job(name, "Trips", d_from, d_to, category=want,
                                folder_name=f"{want}/{bare(name)}", admin=admin, drive_folder_id=fid)
            # every row it will ever hold is already finished; left as "running" the round
            # would re-reconcile it, seven seconds a job, a hundred and fifty jobs at a time
            db.set_job_status(jid, "committed")
            log(f"  + job #{jid} {name} · {want}" + (" (เปิดโฟลเดอร์ใหม่)" if made else ""))
        for r, j in items:
            # 2. the stitched picture, from the old rider folder to the new one
            src = j.get("drive_folder_id")
            pic = mv.find_in(src, r["file_name"]) if src else None
            if pic:
                drive.move_file(pic, fid)
                done["ย้ายรูปรวมร่าง"] += 1
            else:
                done["หารูปรวมร่างในโฟลเดอร์เดิมไม่เจอ"] += 1
            # 3. the delivered picture, from the old group's export folder to the new one
            old_cat = (j.get("category") or "").strip()
            if r.get("customer_image") and mv.exports_week_id:
                src_dir = mv.export_group(old_cat)
                cid = mv.find_in(src_dir, r["customer_image"]) if src_dir else None
                if cid:
                    drive.move_file(cid, mv.export_group(want))
                    done["ย้ายรูปลูกค้า"] += 1
                else:
                    done["หารูปลูกค้าในโฟลเดอร์เดิมไม่เจอ"] += 1
            # 1. the row itself
            db.move_trips_to_job([r["id"]], jid)
            note = f"ย้ายไป {want} ตามประเภทงาน (เดิม job #{j['id']} {old_cat})"
            db.update_trip(r["id"], {"note": f"{note} | {r['note']}" if r.get("note") else note})
            done["ย้ายแถว"] += 1
    return done


def main(argv=None):
    ap = argparse.ArgumentParser(description="ย้ายแถวและรูปไปอยู่กลุ่มที่ประเภทงานบอก")
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--week", required=True, help="ชื่อโฟลเดอร์สัปดาห์บน Drive เช่น 'Week 31 Aug-6 Sep'")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    db.init_db()
    import config
    import roster
    drive = roster._drive()

    moves, jobs = rows_needing_move(a.d_from, a.d_to)
    print(f"{a.d_from}..{a.d_to}: แถวที่ประเภทไม่ตรงกลุ่มของ job: {len(moves)}")
    by = Counter((j.get("category"), want) for _r, j, want in moves)
    for (old, new), n in by.most_common():
        print(f"    {old} → {new}: {n} แถว")
    per_rider = Counter((j["driver_name"], want) for _r, j, want in moves)
    print(f"  ไรเดอร์ที่ต้องมี job เพิ่มในกลุ่มใหม่: {len(per_rider)} คน")
    nowhere = [(r, j, w) for r, j, w in moves if w == "4 W Saver"]
    if nowhere:
        print(f"  ⚠ {len(nowhere)} แถวเป็น Saver Car ซึ่งไม่มีกลุ่ม 4 W Saver — จะไม่ย้าย รอ Ops ตัดสิน")
        moves = [m for m in moves if m[2] != "4 W Saver"]
    if not a.apply:
        print("\n(รายงานอย่างเดียว — ใส่ --apply เพื่อย้ายจริง)")
        return 0

    inbox = config.DRIVE_INBOX_FOLDER_ID
    week = next((f for f in drive.list_folders(inbox) if f["name"].strip() == a.week.strip()), None)
    if not week:
        print(f"✗ ไม่พบโฟลเดอร์สัปดาห์ '{a.week}'")
        return 1
    exports = next((f for f in drive.list_folders(inbox) if f["name"].strip() == "Export Pic"), None)
    from ingest import week_label
    wk_label = week_label(a.d_from)
    exports_week = (next((f["id"] for f in drive.list_folders(exports["id"]) if f["name"] == wk_label), None)
                    if exports else None)
    mv = Mover(drive, week["id"], exports_week)

    done = apply(drive, mv, a.d_from, a.d_to, moves)
    print("\nทำแล้ว: " + " · ".join(f"{k} {v}" for k, v in done.most_common()))
    print(f"เปิดโฟลเดอร์ไรเดอร์ใหม่ {mv.made} โฟลเดอร์")
    print("ขั้นต่อไป: ingest ด้วย xlsx_only เพื่อเขียนไฟล์ Excel ใหม่ (รูปย้ายแล้ว ไม่ต้องสร้างใหม่)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
