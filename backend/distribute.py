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

# The customer wants a Win-heavy mix and can count it: every driver name in the workbook carries
# its kind. Ops set the target at 70/30 with ten points of slack per week. So the kind is decided
# here, one name at a time, instead of being dictated by whatever the album happened to be called
# — an album of 609 trips named '2W-Home …' used to drain the Home sheet and stop, while the
# larger Win sheet it was allowed to use sat untouched.
MAJOR = {"2W": "Win", "4W": "Taxi"}
MINOR = {"2W": "Home", "4W": "Home"}
TARGET_MAJOR = 0.70


def wheel_of(album_name):
    """'2W' from '2W-Home bike 150' or '2w-saver wk5kanjana', or None.

    Which sheet a name comes from no longer depends on the album, so an album only has to say
    which vehicle it is — and '2W-saver 109', which used to be turned away for not naming a
    driver kind, now says everything that is needed."""
    w = WHEEL_RE.match((album_name or "").replace("-", " ").replace("_", " "))
    return f"{w.group(1)}W" if w else None



def folder_label(i, name):
    return f"{i:02d}-{name}"


NUM_PREFIX = re.compile(r"^\s*\d{1,3}\s*[-. ]?\s*")


def bare(folder_name):
    return re.sub(r"\s+", " ", NUM_PREFIX.sub("", folder_name or "")).strip()


class Allocator:
    """Which rider folder the next trip of a given group belongs in.

    A rider works one week, drives one vehicle and takes 21 trips, and those 21 may be any mix of
    Saver and Standard — the tier is the fare's, not the rider's. So the quota is counted against
    the person, not the folder, and someone who works both tiers has a folder in each group with
    one 21 shared between them.

    Built once per run over a week, because none of that — the quota, 'this name is already
    working', or 'this week is 70% Win' — can be answered from inside a single group."""

    def __init__(self, drive, week_id, pool, per_rider=None, seed=None, log=print, styles=None):
        self.drive, self.week_id, self.log = drive, week_id, log
        self.per_rider = per_rider or config.EXPECTED_TRIPS_PER_WEEK
        self.rng = random.Random(seed)
        # {(wheel, kind): [names]} straight from Ops' list, already labelled
        self.pool = {k: [f"{n} {k[1]}".strip() for n in v] for k, v in pool.items()}
        self.groups = {}             # category -> {"id":…, "riders":[{name,id,n}]}
        self.used = set()            # every name spoken for this week, any group
        self.total = {}              # name -> trips this week, across every group they work in
        self.made = 0
        self._read_week = False
        # A rider sends one phone's screenshots, so one rider holds one kind of picture: all
        # pre-joined or all stitched by us, all dark theme or all light. Mixing them is the first
        # thing anyone checking the work would see. This is keyed on the person, not the folder,
        # so the two folders of someone working both tiers cannot drift apart — and it is passed
        # in from the database and read back out, because a round only sees the pictures it is
        # moving while a rider is filled up across several rounds.
        self.styles = dict(styles or {})     # rider name -> style
        self.new_styles = {}                 # the ones this run decided, for the caller to store

    def _load(self, category):
        if category in self.groups:
            return self.groups[category]
        # Read the whole week before answering anything. A rider's 21 trips and the week's Win
        # share are both counted across every group, so a decision made while only one group has
        # been read is a decision made on a fraction of the facts.
        if not self._read_week:
            self._read_week = True
            for f in self.drive.list_folders(self.week_id):
                n = f["name"].strip()
                if n.lower() not in ("pool", "กอง") and not n.startswith("_"):
                    self._load(n)
            if category in self.groups:      # the sweep above already read this one
                return self.groups[category]
        cat_id = self.drive.ensure_folder(self.week_id, category)
        riders = []
        for f in self.drive.list_folders(cat_id):
            if re.match(r"^\s*admin\b", f["name"], re.IGNORECASE):
                continue             # the old layout; leave those alone
            name = bare(f["name"])
            n = len(self.drive.list_images(f["id"]))
            riders.append({"name": name, "id": f["id"], "n": n})
            self.used.add(name)
            self.total[name] = self.total.get(name, 0) + n
        self.groups[category] = {"id": cat_id, "riders": riders}
        return self.groups[category]

    def rider_at(self, folder_id):
        """Whose folder this is. A Drive id is not a name and cannot be turned into one.

        The name was only ever recoverable from the id for folders this run had just made, whose
        ids happen to look like paths in the dry-run wrapper. Topping up somebody who was already
        working returns a real Drive id, and reading a name out of that produced
        'yW9Sxa_HhW7ED1QvyfZP' — which would have gone into the workbook as a driver."""
        for g in self.groups.values():
            for r in g["riders"]:
                if r["id"] == folder_id:
                    return r["name"]
        return None

    def prime(self, categories):
        """Read every group first, so a name already working in one is never drawn for another."""
        for c in categories:
            self._load(c)

    def kind_counts(self, wheel):
        """{kind: riders working this week} for one wheel count, however they were drawn."""
        out = {}
        for kind in (MAJOR[wheel], MINOR[wheel]):
            out[kind] = len(self.used & set(self.pool.get((wheel, kind), [])))
        return out

    def _draw_order(self, wheel):
        """Which sheet to try first, so the week lands on the mix the customer asked for."""
        c = self.kind_counts(wheel)
        major, minor = MAJOR[wheel], MINOR[wheel]
        total = c[major] + c[minor]
        share = c[major] / total if total else 0.0
        return [major, minor] if share < TARGET_MAJOR else [minor, major]

    def _room(self, name):
        return self.per_rider - self.total.get(name, 0)

    def _fits(self, name, style):
        """Room left in this person's week, and the pictures are the kind they already send."""
        if self._room(name) <= 0:
            return False
        have = self.styles.get(name)
        return not (style and have and have != style)

    def _drives(self, name, wheel):
        """Whether this person drives what the group holds.

        Run 131 opened '4 W Standard/13-ดวงพร Win' for the car album Rabbit=246: a Win rider with
        room left in 2 W Saver was borrowed into the car group because the borrowing loop looked
        at every group of the week and never at the wheel. The customer would have seen a
        motorbike rider with car fares. Ops' list says which wheel a name belongs to; a name on
        no list is judged by its kind, and a kind that both wheels use (Home) is not borrowed
        across at all — that person is still topped up in their own group."""
        low = name.lower()
        for (w, _k), names in self.pool.items():
            if any(n.lower() == low for n in names):
                return w == wheel
        return name.rsplit(" ", 1)[-1] == MAJOR[wheel]

    def _take(self, name, style):
        self.total[name] = self.total.get(name, 0) + 1
        if style and not self.styles.get(name):    # riders from before this rule adopt the first
            self.styles[name] = style
            self.new_styles[name] = style

    def folder_for(self, category, wheel, style=None):
        """Folder id for the next trip, or (None, reason) when Ops' list has nobody left.

        style, when given, is whatever tells two pictures apart to the eye — the caller decides
        what goes in it. A rider is only offered work of the style they already send."""
        g = self._load(category)
        # Someone already working in this group who is not at their weekly 21 — always before a
        # second folder, and long before a new name. Fullest first, so a week uses the fewest
        # people it can. Case-folded on purpose: everything else that reads a folder name off
        # Drive ignores case, and this did not, so a folder someone typed as '01-สมชาย WIN' was
        # never topped up and that person was handed a second folder in the same group.
        here = {r["name"].lower() for r in g["riders"]}
        for r in sorted(g["riders"], key=lambda r: (-r["n"], r["name"])):
            if r["n"] < self.per_rider and self._fits(r["name"], style):
                r["n"] += 1
                self._take(r["name"], style)
                return r["id"], None
        # Someone working elsewhere this week who still has room: a Saver rider taking a Standard
        # fare is the same person, so they get a second folder here and one 21 across both.
        for cat, gg in sorted(self.groups.items()):
            if cat == category:
                continue
            for r in sorted(gg["riders"], key=lambda r: (-self._room(r["name"]), r["name"])):
                if (r["name"].lower() in here or not self._fits(r["name"], style)
                        or not self._drives(r["name"], wheel)):
                    continue
                fid = self.drive.ensure_folder(
                    g["id"], folder_label(len(g["riders"]) + 1, r["name"]))
                g["riders"].append({"name": r["name"], "id": fid, "n": 1})
                self._take(r["name"], style)
                self.made += 1
                self.log(f"    + {category}/{folder_label(len(g['riders']), r['name'])}"
                         f"  (คนเดิมจาก {cat})")
                return fid, None
        for kind in self._draw_order(wheel):
            free = [n for n in self.pool.get((wheel, kind), []) if n not in self.used]
            if free:
                break
        else:
            # Say where the unused room is, not just that the list is empty. Run 15 stopped after
            # 21 of 230, and 'the names are all used' left open whether those riders were full or
            # whether the free seats belonged to people whose pictures do not look like these.
            spare = sum(self._room(n) for n in self.used if self._room(n) > 0)
            have = sum(len(self.pool.get((wheel, k), [])) for k in (MAJOR[wheel], MINOR[wheel]))
            return None, (f"รายชื่อของ {wheel} หมดแล้ว ({have} ชื่อถูกใช้ครบในสัปดาห์นี้) · "
                          + (f"ยังมีที่ว่างอีก {spare} เที่ยว แต่เป็นของคนที่ส่งรูปคนละแบบ"
                             if spare else "และทุกคนเต็มแล้ว — ต้องขอชื่อเพิ่มจาก Ops"))
        name = self.rng.choice(free)
        self.used.add(name)
        fid = self.drive.ensure_folder(g["id"], folder_label(len(g["riders"]) + 1, name))
        g["riders"].append({"name": name, "id": fid, "n": 1})
        self._take(name, style)
        self.made += 1
        self.log(f"    + {category}/{folder_label(len(g['riders']), name)}")
        return fid, None


# --- one-off: work already sitting loose in a vehicle-group folder -----------------------------
# Rounds before 2026-09-05 dropped stitched pairs straight into Week/<group>/, where discover()
# never looks — a rider folder is what it reads. The group folder they are sitting in says which
# vehicle they are, which is all the allocator needs, so none of them has to be left behind.

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
        # the group folder is where the slip decided this belongs, and that already says
        # which wheel — the album name inside the file no longer has to say anything
        wheel = f'{cat.replace(" ", "")[0]}W'
        for f in sorted(loose, key=lambda x: x["name"]):
            fid, err = alloc.folder_for(cat, wheel)
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
