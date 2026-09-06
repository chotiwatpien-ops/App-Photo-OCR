# -*- coding: utf-8 -*-
"""Hand every paired trip to a rider, and open a rider's folder only when there is work for it.

Two things about a trip are read from two different places, and they are not the same thing:

    what service it was    the chip on the slip        -> 2 W Saver | 2 W Standard | 4 W Standard
    who drove it           the name of the pool album  -> Win | Home | Taxi

A Win rider and a Home rider both take Saver and Standard fares, so an album of Home work splits
across two vehicle groups; and 'ตฤณ Win' is a different person from 'ตฤณ Taxi', which is why the
kind travels with the name into the folder and from there into the workbook.

Names come from Ops' list, at random, never twice in one week — a job is keyed on rider and week,
so one name in two folders is one rider to everything downstream. Riders who are not yet at the
weekly quota are filled before anyone new is drawn, which keeps a week to the fewest names it can
be done with and leaves no half-empty folders behind.
"""
import argparse
import random
import re
import sys

import config

# What the pool album says about the driver. Anything else is not guessed at.
KINDS = {"win": ("2W", "Win"), "home2": ("2W", "Home"),
         "taxi": ("4W", "Taxi"), "home4": ("4W", "Home")}
WHEEL_RE = re.compile(r"^\s*([24])\s*w\b", re.IGNORECASE)
KIND_RE = re.compile(r"\b(win|home|taxi)\b", re.IGNORECASE)


def driver_kind(album_name):
    """('2W', 'Home') from '2W-Home bike 150', or None when the album does not say.

    Names like '2W-saver 109' describe the service, not the driver, and there is no way to tell
    a Win rider from a Home one by looking at the slips — so those get an error, not a guess.
    Picking the wrong sheet would spread the wrong names across a whole week."""
    n = (album_name or "").replace("-", " ").replace("_", " ")
    w = WHEEL_RE.match(n)
    k = KIND_RE.search(n)
    if not w or not k:
        return None
    wheel, kind = f"{w.group(1)}W", k.group(1).capitalize()
    if (wheel, kind) in {("2W", "Win"), ("2W", "Home"), ("4W", "Taxi"), ("4W", "Home")}:
        return wheel, kind
    return None                      # '4W-Win' and '2W-Taxi' are not things


def folder_label(i, name):
    return f"{i:02d}-{name}"


NUM_PREFIX = re.compile(r"^\s*\d{1,3}\s*[-. ]?\s*")


def bare(folder_name):
    return re.sub(r"\s+", " ", NUM_PREFIX.sub("", folder_name or "")).strip()


class Allocator:
    """Which rider folder the next trip of a given group and driver kind belongs in.

    Built once per run over a week, because 'this name is already used' has to hold across every
    group in that week, not just the one being filled."""

    def __init__(self, drive, week_id, pool, per_rider=None, seed=None, log=print):
        self.drive, self.week_id, self.log = drive, week_id, log
        self.per_rider = per_rider or config.EXPECTED_TRIPS_PER_WEEK
        self.rng = random.Random(seed)
        # {(wheel, kind): [names]} straight from Ops' list, already labelled
        self.pool = {k: [f"{n} {k[1]}".strip() for n in v] for k, v in pool.items()}
        self.groups = {}             # category -> {"id":…, "riders":[{name,id,n}]}
        self.used = set()            # every name spoken for this week, any group
        self.made = 0

    def _load(self, category):
        if category in self.groups:
            return self.groups[category]
        cat_id = self.drive.ensure_folder(self.week_id, category)
        riders = []
        for f in self.drive.list_folders(cat_id):
            if re.match(r"^\s*admin\b", f["name"], re.IGNORECASE):
                continue             # the old layout; leave those alone
            name = bare(f["name"])
            riders.append({"name": name, "id": f["id"], "n": len(self.drive.list_images(f["id"]))})
            self.used.add(name)
        self.groups[category] = {"id": cat_id, "riders": riders}
        return self.groups[category]

    def prime(self, categories):
        """Read every group first, so a name already working in one is never drawn for another."""
        for c in categories:
            self._load(c)

    def folder_for(self, category, wheel, kind):
        """Folder id for the next trip, or (None, reason) when Ops' list has nobody left."""
        g = self._load(category)
        want = f" {kind}"
        # someone already on this week's books who is not full yet — always before a new name
        for r in sorted(g["riders"], key=lambda r: (-r["n"], r["name"])):
            if r["n"] < self.per_rider and r["name"].endswith(want):
                r["n"] += 1
                return r["id"], None
        free = [n for n in self.pool.get((wheel, kind), []) if n not in self.used]
        if not free:
            return None, (f"รายชื่อ {kind} ของ {wheel} หมดแล้ว "
                          f"({len(self.pool.get((wheel, kind), []))} ชื่อถูกใช้ครบในสัปดาห์นี้)")
        name = self.rng.choice(free)
        self.used.add(name)
        fid = self.drive.ensure_folder(g["id"], folder_label(len(g["riders"]) + 1, name))
        g["riders"].append({"name": name, "id": fid, "n": 1})
        self.made += 1
        self.log(f"    + {category}/{folder_label(len(g['riders']), name)}")
        return fid, None


# --- one-off: work already sitting loose in a vehicle-group folder -----------------------------
# Rounds before 2026-09-05 dropped stitched pairs straight into Week/<group>/, where discover()
# never looks — a rider folder is what it reads. Those files carry the album they came from in
# their own name ('2W-Home bike 150_1+2_฿86.jpg'), so the driver kind is recoverable and nothing
# has to be guessed at. Anything whose name does not say is reported and left alone.

def kind_of_file(file_name):
    return driver_kind((file_name or "").rsplit("_", 2)[0])


def backfill(drive, week_id, categories, pool, per_rider=None, seed=None, dry_run=True, log=print):
    """Move loose images in each category folder into rider folders. Returns (moved, stuck)."""
    alloc = Allocator(drive, week_id, pool, per_rider=per_rider, seed=seed, log=log)
    alloc.prime(categories)
    moved, stuck = 0, []
    for cat in categories:
        before = moved
        g = alloc._load(cat)
        loose = drive.list_images(g["id"])
        log(f"\n{cat}: ไฟล์ลอย {len(loose)} รูป")
        for f in sorted(loose, key=lambda x: x["name"]):
            kind = kind_of_file(f["name"])
            if kind is None:
                stuck.append((cat, f["name"]))
                continue
            wheel = f'{cat.replace(" ", "")[0]}W'
            if wheel != kind[0]:
                # the album says one thing and the folder it landed in says another; the folder
                # is what the slip decided, so trust it and only take the driver kind from the name
                kind = (wheel, kind[1])
            fid, err = alloc.folder_for(cat, *kind)
            if err:
                stuck.append((cat, f"{f['name']} — {err}"))
                continue
            if not dry_run:
                drive.move_file(f["id"], fid)
            moved += 1
        log(f"  ย้าย {moved - before} · ค้าง {len(stuck)}")   # this group, not the running total
    return moved, stuck


def main(argv=None):
    import db
    import roster                        # its _drive() already knows both credential shapes

    ap = argparse.ArgumentParser(description="ย้ายงานที่ลอยอยู่ในโฟลเดอร์ประเภทรถ เข้าโฟลเดอร์ไรเดอร์")
    ap.add_argument("--week", required=True, help="ชื่อโฟลเดอร์สัปดาห์ เช่น 'Week 31 Aug-6 Sep'")
    ap.add_argument("--group", action="append", default=[],
                    help="กลุ่มรถที่จะจัด (ใส่ซ้ำได้) — ว่าง = ทุกกลุ่มที่มี")
    ap.add_argument("--per-rider", type=int, default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--move", action="store_true", help="ย้ายจริง (ไม่ใส่ = รายงานอย่างเดียว)")
    a = ap.parse_args(argv)
    db.init_db()

    drive = roster._drive()
    inbox = config.DRIVE_INBOX_FOLDER_ID
    wk = next((f for f in drive.list_folders(inbox) if f["name"].strip() == a.week.strip()), None)
    if wk is None:
        print(f"✗ ไม่พบสัปดาห์ {a.week!r} ใน Inbox")
        return 1
    groups = a.group or [f["name"] for f in drive.list_folders(wk["id"])
                         if f["name"].strip().lower() not in ("pool", "กอง")
                         and not f["name"].startswith("_")]
    pool = {k: [n for n, kd in db.name_pool_for(k[0]) if kd == k[1]]
            for k in (("2W", "Win"), ("2W", "Home"), ("4W", "Taxi"), ("4W", "Home"))}
    if not any(pool.values()):
        print("✗ ยังไม่มีรายชื่อในฐานข้อมูล — สั่ง roster.py --import-drive ก่อน")
        return 1
    print(f"{'ย้ายจริง' if a.move else 'รายงานอย่างเดียว'} · {a.week} · {len(groups)} กลุ่ม")
    moved, stuck = backfill(drive, wk["id"], groups, pool, per_rider=a.per_rider,
                            seed=a.seed, dry_run=not a.move)
    print(f"\nรวม: ย้าย {moved} · ค้าง {len(stuck)}")
    for cat, why in stuck[:40]:
        print(f"  ✗ [{cat}] {why}")
    if len(stuck) > 40:
        print(f"  … อีก {len(stuck) - 40} รายการ")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
