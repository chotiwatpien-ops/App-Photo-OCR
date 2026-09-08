# -*- coding: utf-8 -*-
"""Find riders carrying more than a week's worth of work, and say what it would take to fix.

A rider works 21 trips in a week. Four of them in 31 Aug-6 Sep are carrying 37 to 42, because
the allocator used to read one vehicle group at a time: 'this name is already working' was only
true of the group it had just looked at, so the same person could be drawn again in the other
group and handed a second, separate 21. The count that proves it is the tier split — มานิตย์ is
Saver 21 plus Standard 21, exactly two full folders.

The allocator now reads the whole week before it decides anything and counts the quota against
the person, so this cannot happen again. It does not undo what already happened, and the rows are
in the delivered file, which is why this reports and does not touch anything.

    python rebalance_quota.py --from 2026-08-31 --to 2026-09-06
"""
import argparse
import io
import re
import sys
import zlib
from collections import defaultdict

import config
import db


def plan(rows, per_rider):
    """{rider: {"keep": [...], "release": [...]}} for whoever is over.

    Keep the same days, thinned. Taking simply the first 21 of the week is a rule anyone can
    check, which is why it was tried first — but on this data it left every one of the four
    working Monday to Thursday and then nothing at all, and a rider who stops dead three days
    before the week ends is a stranger sight than one who did 42. So the seats are handed out a
    day at a time, always to the day with the most trips still waiting: a rider who worked seven
    days still works seven days. Deterministic, and it does not depend on the order rows arrive
    in — which is what made the first rule checkable, and this one keeps."""
    by_rider = defaultdict(list)
    for t in rows:
        by_rider[t["driver_name"]].append(t)
    out = {}
    for who, ts in by_rider.items():
        if len(ts) <= per_rider:
            continue
        by_day = defaultdict(list)
        for t in sorted(ts, key=lambda t: t["id"]):
            by_day[str(t.get("trip_date") or "")].append(t)
        days = sorted(by_day)
        # Largest remainder. Each day keeps its share of the 21 in proportion to what it holds,
        # rounded down, and the seats left over go to the days that lost the most in the
        # rounding. A day that did more still keeps more, none of them empties, and the answer
        # is a named method rather than whatever a tie-break happened to do.
        total = len(ts)
        exact = {d: per_rider * len(by_day[d]) / total for d in days}
        seats = {d: int(exact[d]) for d in days}
        for d in sorted(days, key=lambda d: (-(exact[d] - seats[d]), d))[:per_rider - sum(seats.values())]:
            seats[d] += 1
        keep = [t for d in days for t in by_day[d][:seats[d]]]
        release = [t for d in days for t in by_day[d][seats[d]:]]
        out[who] = {"keep": keep, "release": release}
    return out


def room(rows, per_rider, over):
    """Seats left this week among everyone who is not over — where the released work could go."""
    n = defaultdict(int)
    for t in rows:
        n[t["driver_name"]] += 1
    return {w: per_rider - c for w, c in n.items() if c < per_rider and w not in over}


def days_line(ts):
    """'08-31:3 09-01:3 …' — a rider who worked every day has to go on working every day."""
    c = defaultdict(int)
    for t in ts:
        c[str(t.get("trip_date") or "?")] += 1
    return " ".join(f"{d[5:]}:{n}" for d, n in sorted(c.items()))


def tiers(ts):
    c = defaultdict(int)
    for t in ts:
        c[str(t.get("service_type") or "?")] += 1
    return " · ".join(f"{k} {v}" for k, v in sorted(c.items()))


STITCHED = re.compile(r"_\d+\+\d+_฿")          # '<album>_188+187_฿32.jpg' — one we joined
HOLD_DIR = "_แทนที่แล้ว"


def style_of(name, blob):
    """What this picture looks like, in the same words the pool run uses.

    How it was made is in its own name — only pictures we joined carry '_188+187_฿32'. The theme
    has to come from the pixels, and it is the mean brightness, so it costs one download and no
    OCR at all."""
    import pairing
    import numpy as np
    from PIL import Image
    kind = "ครึ่ง" if STITCHED.search(name or "") else "ยาว"
    theme = pairing.theme_of(np.asarray(Image.open(io.BytesIO(blob)).convert("RGB")).astype(int))
    return f"{kind}/{theme}"


def week_folder(drive, inbox_id, d_from, d_to):
    """The week folder whose name covers these dates — matched by what it means, not by spelling."""
    import ingest
    for f in drive.list_folders(inbox_id):
        n = ingest.clean_name(f["name"])
        if not n.lower().startswith("week"):
            continue
        rng = ingest.parse_range(n)
        if rng and rng[0].isoformat() == d_from and rng[1].isoformat() == d_to:
            return f
    return None


def find_new_home(alloc, t):
    """(folder id, category, error) for a trip that has to go to somebody else.

    The tier is the fare's own — a Saver Bike stays a Saver Bike, whoever ends up driving it —
    so it decides the group, and the allocator decides the person under every rule that applies
    to a normal round: the weekly 21 counted against the person, one look per rider, and the
    Win-heavy mix."""
    import pairing
    svc = str(t.get("service_type") or "").lower()
    wheel, tier = pairing.wheels_from_chip(svc), pairing.tier_from_chip(svc)
    cat = pairing.category_folder(wheel, tier)
    if not cat:
        # A row whose slip has not come back from the batch yet says nothing about itself, but
        # the group it was filed in was read off the album, and that is the group it belongs in.
        cat = t.get("_category")
        wheel = wheel_of_category(cat)
    if not cat or not wheel:
        return None, None, f"อ่านประเภทบริการไม่ออก ({t.get('service_type')!r})"
    fid, err = alloc.folder_for(cat, wheel, t.get("style"))
    return fid, cat, err


def wheel_of_category(cat):
    """'2 W Saver' -> '2W'. None when the group name does not say."""
    m = re.match(r"\s*([24])\s*W\b", cat or "", re.IGNORECASE)
    return f"{m.group(1)}W" if m else None


def _norm(s):
    return re.sub(r"[\s​]+", " ", s or "").strip().lower()   # LINE leaves zero-width spaces in names


def rider_wheel(name, pools):
    """Which wheel this rider drives: Ops' list first, then the kind on the name.

    'Home' is used on both lists, so a Home rider who is on neither list cannot be judged and
    the answer is None — never a guess."""
    low = _norm(name)
    for (wheel, kind), names in pools.items():
        if any(_norm(f"{n} {kind}") == low for n in names):
            return wheel
    kind = (name or "").rsplit(" ", 1)[-1]
    return {"Win": "2W", "Taxi": "4W"}.get(kind)


def misfiled_jobs(jobs, pools):
    """[(job, wheel of the group, wheel of the rider)] where the two disagree.

    Runs 131 and 132 lent riders across the wheel: a Win rider with room was handed a folder in
    4 W Standard for the car album Rabbit=246, and once every 2W name was used up eight car
    riders were handed folders in 2 W Saver. A job is the folder, so the job's category against
    the rider's own wheel is exactly the question."""
    out = []
    for j in jobs:
        cw, rw = wheel_of_category(j.get("category")), rider_wheel(j.get("driver_name"), pools)
        if cw and rw and cw != rw:
            out.append((j, cw, rw))
    return out


WRONG_WHEEL_DIR = "_ผิดล้อ"


def trip_wheel(t):
    """What the trip itself was: the slip when it has been read, the group it sat in until then."""
    import pairing
    return (pairing.wheels_from_chip(str(t.get("service_type") or "").lower())
            or wheel_of_category(t.get("_category")))


def classify(job, trip, pools):
    """None | 'other' | 'refile' — what a trip in this job needs.

    'other': the trip is not what this rider drives — a car fare under a Win name, a bike fare
    under a Taxi name — and has to go to somebody else. 'refile': the trip is right for the rider
    but the job is in the other wheel's group (ดวงพร Win's bike fares in 4 W Standard), so it goes
    to the same rider's own job on the right side and the customer folder follows. The delivered
    file already carries ten bike slips under Taxi names from car albums, so this is asked of
    every trip of the week, not only of the folders opened on the wrong side."""
    rw = rider_wheel(job.get("driver_name"), pools)
    if not rw:
        return None
    tw = trip_wheel(trip)
    if tw and tw != rw:
        return "other"
    cw = wheel_of_category(job.get("category"))
    if cw and cw != rw:
        return "refile"
    return None


def _refile(drive, wk, jobs, pools, d_from, d_to, apply_it, log):
    """Move each (job, trip) to the same rider's job in the group of their own wheel."""
    import excel_writer
    import pairing
    from void_pool_pairs import drive_id
    cats = {f["name"].strip(): f["id"] for f in drive.list_folders(wk["id"])}
    touched, done = set(), 0
    for job, ts in jobs:
        rw = rider_wheel(job["driver_name"], pools)
        for t in ts:
            svc = str(t.get("service_type") or "").lower()
            tier = pairing.tier_from_chip(svc) or (str(job.get("category") or "").split()[-1] or None)
            cat = pairing.category_folder(rw, tier)
            if not cat:
                log(f"  ✗ {job['driver_name']} · {t.get('file_name')} — บอกไม่ได้ว่า Saver หรือ Standard")
                continue
            if not apply_it:
                done += 1
                continue
            cat_id = cats.get(cat) or drive.ensure_folder(wk["id"], cat)
            cats[cat] = cat_id
            riders = drive.list_folders(cat_id)
            mine = next((f["id"] for f in riders
                         if _norm(bare(f["name"])) == _norm(job["driver_name"])), None)
            if mine is None:
                import distribute
                mine = drive.ensure_folder(cat_id, distribute.folder_label(len(riders) + 1, job["driver_name"]))
            job2 = (db.find_job(job["driver_name"], d_from, d_to, cat, None)
                    or db.create_job(job["driver_name"], excel_writer.SHEET, d_from, d_to, category=cat,
                                     folder_name=f"{cat}/{job['driver_name']}", drive_folder_id=mine))
            src = drive_id(t.get("source_url"))
            if src:
                try:
                    drive.move_file(src, mine)
                except Exception as e:                          # noqa: BLE001
                    log(f"  ⚠ ย้ายรูปไม่สำเร็จ {t.get('file_name')}: {str(e)[:80]}")
                    continue
            db.move_trips_to_job([t["id"]], job2)
            touched.update({job2, job["id"]})
            done += 1
    return done, touched


def bare(folder_name):
    import distribute
    return distribute.bare(folder_name)


def wrong_wheel(d_from, d_to, per_rider, apply_it, log=print):
    """Every trip of the week that is on the wrong side of the wheel, and where it goes.

    Reports unless apply_it. Rows are not re-read: a fare stays what it was read as, only the
    owner or the group changes. Rows still waiting for their batch result go too — the result
    lands on the row wherever it lives, and whichever job holds it then exports it."""
    pools = {k: [n for n, kd in db.name_pool_for(k[0]) if kd == k[1]]
                      for k in (("2W", "Win"), ("2W", "Home"), ("4W", "Taxi"), ("4W", "Home"))}
    jobs = [j for (f, t), js in db.jobs_by_week().items() if f == d_from and t == d_to for j in js]
    other, refile = {}, []
    table = []
    for j in jobs:
        full = db.get_job(j["id"]) or {"trips": []}
        o, r = [], []
        for t in full["trips"]:
            if t.get("status") not in ("pending", "done", "error"):
                continue
            t["_category"], t["driver_name"], t["job_id_"] = j.get("category"), j["driver_name"], j["id"]
            what = classify(j, t, pools)
            if what == "other":
                o.append(t)
            elif what == "refile":
                r.append(t)
        if o:
            other.setdefault(j["driver_name"], {"keep": [], "release": []})["release"].extend(o)
        if r:
            refile.append((j, r))
        if o or r:
            table.append((j, o, r))
    log(f"{d_from}..{d_to} · {len(jobs)} job · job ที่มีเที่ยวผิดล้อ {len(table)}")
    if not table:
        log("ไม่มี ✔")
        return 0
    log(f"\n{'กลุ่ม':<14}{'ไรเดอร์':<22}{'ขับ':<5}{'ไปคนอื่น':>9}{'ย้ายกลุ่ม':>10}{'รอผล':>6}{'ลงไฟล์แล้ว':>11}")
    for j, o, r in sorted(table, key=lambda x: (str(x[0]["category"]), x[0]["driver_name"])):
        ts = o + r
        log(f"{str(j['category'])[:14]:<14}{j['driver_name'][:22]:<22}"
            f"{rider_wheel(j['driver_name'], pools):<5}{len(o):>9}{len(r):>10}"
            f"{sum(1 for t in ts if t.get('status') != 'done'):>6}"
            f"{sum(1 for t in ts if t.get('committed')):>11}")
    n_other = sum(len(v["release"]) for v in other.values())
    n_refile = sum(len(r) for _j, r in refile)
    log(f"\nไปหาคนอื่น {n_other} เที่ยว · ย้ายไปกลุ่มที่ถูกของคนเดิม {n_refile} เที่ยว\n")

    import roster
    drive = roster._drive()
    if not apply_it:
        drive = DryDrive(drive)
    wk = week_folder(drive, config.DRIVE_INBOX_FOLDER_ID, d_from, d_to)
    if wk is None:
        log(f"✗ ไม่พบโฟลเดอร์สัปดาห์ที่ครอบ {d_from}..{d_to} ใน Inbox")
        return 1
    rc = 0
    if refile:
        moved, touched = _refile(drive, wk, refile, pools, d_from, d_to, apply_it, log)
        log(f"ย้ายกลุ่มให้คนเดิม{'แล้ว' if apply_it else 'ได้'} {moved} เที่ยว")
        if apply_it and touched:
            import ingest
            rc = finish(drive, touched, ingest.week_label(d_from), log)
    if other:
        rc = reassign(other, d_from, d_to, per_rider, apply_it, log=log) or rc
    elif not apply_it:
        log("\n(รายงานอย่างเดียว — ยังไม่ได้แตะอะไร · ใส่ --apply เพื่อทำจริง)")
    if not apply_it or rc:
        return rc

    # The folders opened on the wrong side are empty now. Left where they are, they are riders in
    # the wrong group that the next round will read and count; parked beside the week they are a
    # record of what happened, and nothing is deleted.
    # Tidying up, and every trip has already moved and every customer picture has already been
    # rebuilt by the time we get here. The first run of this died on the very first read of this
    # loop with a dropped SSL socket and exited 1, which reads as 'the apply failed' when what
    # actually failed was putting an empty folder away. Say so and finish.
    parked = 0
    for j, _cw, _rw in misfiled_jobs(jobs, pools):
        fid = j.get("drive_folder_id")
        try:
            if not fid or drive.list_images(fid):
                continue
            drive.move_file(fid, drive.ensure_folder(wk["id"], WRONG_WHEEL_DIR))
            parked += 1
        except Exception as e:                                  # noqa: BLE001
            log(f"  ⚠ พักโฟลเดอร์ {j.get('folder_name')} ไม่สำเร็จ: {str(e)[:60]}")
    log(f"พักโฟลเดอร์ที่ว่างแล้วไว้ที่ {WRONG_WHEEL_DIR}/ {parked} โฟลเดอร์ (ไม่ได้ลบ)"
        "\n  (งานย้ายเที่ยวและสร้างรูปเสร็จไปก่อนหน้านี้แล้ว — ขั้นนี้เป็นแค่การเก็บกวาด)")
    return 0


class DryDrive:
    """Reads Drive; refuses to change it. Wraps the real client for the report.

    Working out who should take a trip means asking the allocator, and the allocator opens a
    folder the moment it draws a name — so a report that used it directly would leave new rider
    folders behind on Drive and stop being a report. Folders that already exist answer normally;
    a new one gets an id shaped like the path it would have had, which is enough for everything
    downstream to name it and count against it."""

    def __init__(self, real):
        self._real = real
        self._made = {}

    def __getattr__(self, name):
        return getattr(self._real, name)

    def ensure_folder(self, parent_id, name):
        for f in self._real.list_folders(parent_id):
            if f["name"].strip() == str(name).strip():
                return f["id"]
        return self._made.setdefault(f"{parent_id}/{name}", f"{parent_id}/{name}")

    def list_folders(self, parent_id):
        return self._real.list_folders(parent_id) if self._is_real(parent_id) else []

    def list_images(self, parent_id):
        return self._real.list_images(parent_id) if self._is_real(parent_id) else []

    def _is_real(self, fid):
        return fid not in self._made

    def move_file(self, file_id, new_parent_id):
        raise AssertionError("DryDrive ต้องไม่ถูกสั่งย้ายไฟล์")

    def upload_file(self, *a, **k):
        raise AssertionError("DryDrive ต้องไม่ถูกสั่งอัปโหลด")


def reassign(over, d_from, d_to, per_rider, apply_it, log=print):
    """Give the released trips to riders who have room. Reports unless apply_it."""
    import config
    import distribute
    import excel_writer
    import roster
    from void_pool_pairs import drive_id

    drive = roster._drive()
    if not apply_it:
        drive = DryDrive(drive)
    wk = week_folder(drive, config.DRIVE_INBOX_FOLDER_ID, d_from, d_to)
    if wk is None:
        log(f"✗ ไม่พบโฟลเดอร์สัปดาห์ที่ครอบ {d_from}..{d_to} ใน Inbox")
        return 1
    log(f"สัปดาห์บน Drive: {wk['name']}")

    names = {k: [n for n, kd in db.name_pool_for(k[0]) if kd == k[1]]
             for k in (("2W", "Win"), ("2W", "Home"), ("4W", "Taxi"), ("4W", "Home"))}
    # Tie the draw to the week, so the report is the thing that happens. Names come out at
    # random, and with nothing holding them still the run that was approved and the run that
    # acts pick different people — which makes a report shown for approval worth nothing.
    seed = zlib.crc32(str(wk["id"]).encode("utf-8"))
    alloc = distribute.Allocator(drive, wk["id"], names, per_rider=per_rider, seed=seed, log=log,
                                 styles=db.rider_styles(wk["id"]))

    released = [(who, t) for who, v in sorted(over.items()) for t in v["release"]]
    log(f"ต้องหาเจ้าของใหม่ให้ {len(released)} เที่ยว\n")

    moves, stuck = [], []
    for who, t in released:
        fid_src = drive_id(t.get("source_url"))
        if not fid_src:
            stuck.append((who, t, "ไม่รู้ว่ารูปอยู่ไฟล์ไหนบน Drive"))
            continue
        try:
            t["style"] = style_of(t.get("file_name"), drive.download(fid_src))
        except Exception as e:                                  # noqa: BLE001
            stuck.append((who, t, f"อ่านรูปไม่ได้: {str(e)[:60]}"))
            continue
        dest, cat, err = find_new_home(alloc, t)
        if err or not dest:
            stuck.append((who, t, err or "ไม่มีที่ว่าง"))
            continue
        to = alloc.rider_at(dest)
        if not to:
            stuck.append((who, t, f"ไม่รู้ว่าโฟลเดอร์ {dest} เป็นของใคร"))
            continue
        moves.append({"from": who, "trip": t, "src": fid_src, "dest": dest, "category": cat,
                      "to": to})

    by_pair = defaultdict(list)
    for m in moves:
        by_pair[(m["from"], m["to"], m["category"], m["trip"]["style"])].append(m)
    log(f"{'จาก':<18}{'ไป':<20}{'กลุ่ม':<14}{'สไตล์':<12}{'เที่ยว':>6}")
    for (src, dst, cat, style), ms in sorted(by_pair.items()):
        log(f"{src[:18]:<18}{dst[:20]:<20}{cat:<14}{style:<12}{len(ms):>6}")
    log(f"\nย้ายได้ {len(moves)} · ติดขัด {len(stuck)}")
    for who, t, why in stuck[:20]:
        log(f"  ✗ {who} · {t.get('file_name')} — {why}")

    if not apply_it:
        log("\n(รายงานอย่างเดียว — ยังไม่ได้แตะอะไร · ใส่ --apply เพื่อทำจริง)")
        return 0
    if not moves:
        log("ไม่มีอะไรให้ย้าย")
        return 0

    touched, done = set(), 0
    for m in moves:
        t, dest = m["trip"], m["dest"]
        job = (db.find_job(m["to"], d_from, d_to, m["category"], None)
               or db.create_job(m["to"], excel_writer.SHEET, d_from, d_to,
                                category=m["category"], folder_name=f"{m['category']}/{m['to']}",
                                drive_folder_id=dest))
        try:
            drive.move_file(m["src"], dest)
        except Exception as e:                                  # noqa: BLE001
            log(f"  ⚠ ย้ายรูปไม่สำเร็จ {t.get('file_name')}: {str(e)[:80]}")
            continue
        db.move_trips_to_job([t["id"]], job)
        touched.add(job)
        touched.add(t.get("job_id_") or t.get("job_id"))
        done += 1
    log(f"\nย้ายแล้ว {done} เที่ยว · job ที่ต้องสร้างรูปใหม่ {len(touched)}")
    db.rider_styles_save(wk["id"], alloc.new_styles)
    import ingest
    # Not wk['name']. The Inbox calls this week 'Week 31 Aug-6 Sep' and Exports calls it
    # '2026-W36', and comparing one against the other found nothing at all — which is what
    # '0 ไฟล์' meant on the run that moved 75 trips and left all 75 old pictures behind.
    return finish(drive, touched, ingest.week_label(d_from), log)


def rider_of_export(file_name):
    """'WK36-มานิตย์ Home7.jpg' -> 'มานิตย์ Home'. None when it is not one of ours.

    Guessing this shape twice cost two runs. stitch.customer_name puts the week in front so a
    file forwarded on its own still says which week it belongs to, and export_only puts the admin
    behind when two riders in one group share a display name. Taking only the trailing number off
    left 'WK36-มานิตย์ Home', which matched no rider, and the sweep reported nothing to do."""
    m = re.match(r"^\s*(?:WK\d+\s*-\s*)?(.+?)\s*\d+\.jpe?g\s*$", file_name or "", re.IGNORECASE)
    return m.group(1).strip() if m else None


def stale_export_images(drive, exports_id, week_name, names):
    """The customer pictures belonging to riders whose trips have just changed hands.

    A job's pictures are numbered in trip order, so once trips have left or arrived, every number
    means a different trip and the whole set is wrong."""
    out = []
    for week_dir in drive.list_folders(exports_id):
        if week_dir["name"].strip() != week_name:
            continue
        for cat_dir in drive.list_folders(week_dir["id"]):
            if cat_dir["name"].lstrip().startswith("_"):
                continue                       # our own holding folders
            for img in drive.list_images(cat_dir["id"]):
                who = rider_of_export(img["name"])
                if who and (who in names or who.rsplit("-", 1)[0].strip() in names):
                    out.append((week_dir["id"], img))
    return out


def finish(drive, touched, week_name, log):
    """Take down the pictures that are no longer right, and build them again.

    Nothing is deleted — the old ones move to a holding folder beside the week, the same as
    everything else this project takes back."""
    import config
    import ingest
    jobs = [db.get_job(j) for j in touched if j]
    names = {j["driver_name"] for j in jobs if j}
    exports = config.DRIVE_EXPORTS_FOLDER_ID
    stale = stale_export_images(drive, exports, week_name, names)
    moved = 0
    hold = None
    for week_id, img in stale:
        hold = hold or drive.ensure_folder(week_id, HOLD_DIR)
        try:
            drive.move_file(img["id"], hold)
            moved += 1
        except Exception as e:                                  # noqa: BLE001
            log(f"  ⚠ เก็บรูปเก่าไม่สำเร็จ {img['name']}: {str(e)[:60]}")
    log(f"เก็บรูปส่งลูกค้าชุดเก่าไปพักไว้ {moved} ไฟล์ (ไม่ได้ลบ)")
    errs, failed = ingest.export_only(drive, exports, only_job_ids={j for j in touched if j},
                                      with_xlsx=True, force=True)
    log(f"สร้างรูปและ Excel ใหม่แล้ว · error {errs}"
        + (f" · job ที่ยังไม่สำเร็จ {failed}" if failed else ""))
    return 1 if errs else 0


def fix_exports(d_from, d_to, apply_it, log=print):
    """Rebuild every customer picture of a week, because some of them are of the wrong trip.

    A job's pictures are numbered in trip order, so a job that lost trips keeps pictures past its
    new length and a job that gained them has pictures under numbers that now mean something
    else. There is no way to tell which is which by looking at a file, so the whole week is taken
    down — moved, never deleted — and written again from what the database says today."""
    import config
    import ingest
    import roster
    drive = roster._drive()
    week = ingest.week_label(d_from)
    jobs = [j for (f, t), js in db.jobs_by_week().items() if f == d_from and t == d_to for j in js]
    names = {j["driver_name"] for j in jobs}
    log(f"{week}: {len(jobs)} job · {len(names)} ไรเดอร์")
    stale = stale_export_images(drive, config.DRIVE_EXPORTS_FOLDER_ID, week, names)
    log(f"รูปส่งลูกค้าที่ต้องสร้างใหม่ {len(stale)} ไฟล์")
    if not apply_it:
        log("\n(รายงานอย่างเดียว — ใส่ --apply เพื่อทำจริง)")
        return 0
    moved = 0
    for week_id, img in stale:
        hold = drive.ensure_folder(week_id, HOLD_DIR)
        try:
            drive.move_file(img["id"], hold)
            moved += 1
        except Exception as e:                                  # noqa: BLE001
            log(f"  ⚠ เก็บไม่สำเร็จ {img['name']}: {str(e)[:60]}")
    log(f"เก็บไปพักไว้ {moved} ไฟล์ (ไม่ได้ลบ)")
    errs, failed = ingest.export_only(drive, config.DRIVE_EXPORTS_FOLDER_ID,
                                      only_job_ids={j["id"] for j in jobs},
                                      with_xlsx=True, force=True)
    log(f"สร้างใหม่แล้ว · error {errs}" + (f" · ยังไม่สำเร็จ {failed}" if failed else ""))
    return 1 if errs else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="ใครทำเกินโควตาสัปดาห์ และต้องทำอะไรถึงจะแก้ได้ (รายงานอย่างเดียว)")
    ap.add_argument("--from", dest="d_from", required=True, help="วันเริ่มสัปดาห์ YYYY-MM-DD")
    ap.add_argument("--to", dest="d_to", required=True, help="วันจบสัปดาห์ YYYY-MM-DD")
    ap.add_argument("--per-rider", type=int, default=config.EXPECTED_TRIPS_PER_WEEK)
    ap.add_argument("--list", action="store_true", help="พิมพ์รายเที่ยวที่จะถูกเอาออก")
    ap.add_argument("--reassign", action="store_true",
                    help="หาเจ้าของใหม่ให้เที่ยวส่วนเกิน (ยังเป็นรายงาน จนกว่าจะใส่ --apply)")
    ap.add_argument("--fix-exports", action="store_true",
                    help="สร้างรูปส่งลูกค้าของสัปดาห์นี้ใหม่ทั้งหมด (ใช้เมื่อเจ้าของเที่ยวเปลี่ยนไปแล้ว)")
    ap.add_argument("--wrong-wheel", action="store_true",
                    help="หาโฟลเดอร์ที่คนขับผิดล้อ (วินในรถยนต์ / Taxi ในวิน) แล้วย้ายเที่ยวไปให้คนที่ขับถูก")
    ap.add_argument("--apply", action="store_true",
                    help="ทำจริง: ย้ายรูปบน Drive · เปลี่ยนเจ้าของแถว · สร้างรูปและ Excel ใหม่")
    a = ap.parse_args(argv)
    db.init_db()

    # Before the rows are even asked for: the folders opened on the wrong side hold trips that
    # are mostly still waiting for their batch result, which the delivered-rows query below
    # does not see and would answer 'nothing delivered' about.
    if a.wrong_wheel:
        return wrong_wheel(a.d_from, a.d_to, a.per_rider, a.apply, log=print)

    rows = db.query_trips(date_from=a.d_from, date_to=a.d_to)
    if not rows:
        print(f"ไม่มีแถวที่ลงไฟล์แล้วในช่วง {a.d_from}..{a.d_to}")
        return 0
    riders = {t["driver_name"] for t in rows}
    print(f"{a.d_from}..{a.d_to} · {len(rows)} เที่ยว · {len(riders)} ไรเดอร์ · โควตา {a.per_rider}/คน")

    # Before the quota check, not after. Rebuilding a week's pictures is what you do once the
    # trips have already moved — which is precisely when nobody is over the quota and the check
    # below returns. Asked for it then, the run printed 'ไม่มีใครเกินโควตา ✔' and did nothing.
    if a.fix_exports:
        print()
        return fix_exports(a.d_from, a.d_to, a.apply, log=print)

    over = plan(rows, a.per_rider)
    if not over:
        print("ไม่มีใครเกินโควตา ✔")
        return 0

    extra = sum(len(v["release"]) for v in over.values())
    print(f"\nเกินโควตา {len(over)} คน · เที่ยวส่วนเกินรวม {extra}")
    print(f"\n{'ไรเดอร์':<22}{'มี':>5}{'เก็บ':>6}{'เอาออก':>8}  แยกตามบริการ")
    for who, v in sorted(over.items(), key=lambda kv: -len(kv[1]["release"])):
        n = len(v["keep"]) + len(v["release"])
        print(f"{who[:22]:<22}{n:>5}{len(v['keep']):>6}{len(v['release']):>8}  "
              f"เก็บ [{tiers(v['keep'])}] · ออก [{tiers(v['release'])}]")
        print(f"{'':<22}      วันละ: " + days_line(v["keep"]))

    free = room(rows, a.per_rider, over)
    seats = sum(free.values())
    print(f"\nที่ว่างในสัปดาห์นี้ {seats} ที่ จากไรเดอร์ {len(free)} คนที่ยังไม่เต็ม")
    if seats < extra:
        need = -(-(extra - seats) // a.per_rider)      # ceil
        print(f"  ไม่พอ — ขาดอีก {extra - seats} ที่ ต้องเปิดไรเดอร์ใหม่อย่างน้อย {need} คน")
        try:
            pool = {k: [n for n, kd in db.name_pool_for(k[0]) if kd == k[1]]
                    for k in (("2W", "Win"), ("2W", "Home"), ("4W", "Taxi"), ("4W", "Home"))}
            used = {w.strip() for w in riders}
            spare = {k: len([n for n in v if f"{n} {k[1]}".strip() not in used])
                     for k, v in pool.items()}
            print("  ชื่อที่ยังไม่ถูกใช้ในสัปดาห์นี้: "
                  + " · ".join(f"{k[0]} {k[1]} {v}" for k, v in sorted(spare.items())))
        except Exception as e:                          # noqa: BLE001
            print(f"  (อ่านรายชื่อไม่ได้: {str(e)[:80]})")
    else:
        print(f"  พอ — ไม่ต้องเปิดชื่อใหม่")

    if a.list:
        print(f"\n{'ไรเดอร์':<22}{'วันที่':<12}{'บริการ':<16}{'ไฟล์'}")
        for who, v in sorted(over.items()):
            for t in v["release"]:
                print(f"{who[:22]:<22}{str(t.get('trip_date')):<12}"
                      f"{str(t.get('service_type'))[:16]:<16}{t.get('file_name')}")

    if a.reassign:
        print()
        return reassign(over, a.d_from, a.d_to, a.per_rider, a.apply, log=print)
    print("\n(รายงานอย่างเดียว — ยังไม่ได้แตะอะไรทั้งสิ้น · ใส่ --reassign เพื่อดูว่าใครจะรับต่อ)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
