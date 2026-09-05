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
import random
import re

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
