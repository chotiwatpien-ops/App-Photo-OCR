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
        return None, None, f"อ่านประเภทบริการไม่ออก ({t.get('service_type')!r})"
    fid, err = alloc.folder_for(cat, wheel, t.get("style"))
    return fid, cat, err


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
    return finish(drive, touched, wk["name"].strip(), log)


def stale_export_images(drive, exports_id, week_name, names):
    """The customer pictures belonging to riders whose trips have just changed hands.

    A job's pictures are numbered in trip order ('มานิตย์ Home7.jpg'), so once trips have left or
    arrived, every number means a different trip and the whole set is wrong. Matching is on the
    name with its number taken off — the same name the export wrote in the first place."""
    out = []
    for week_dir in drive.list_folders(exports_id):
        if week_dir["name"].strip() != week_name:
            continue
        for cat_dir in drive.list_folders(week_dir["id"]):
            if cat_dir["name"].lstrip().startswith("_"):
                continue                       # our own holding folders
            for img in drive.list_images(cat_dir["id"]):
                stem = re.sub(r"\s*\d+\.jpe?g$", "", img["name"], flags=re.IGNORECASE).strip()
                if stem in names:
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


def main(argv=None):
    ap = argparse.ArgumentParser(description="ใครทำเกินโควตาสัปดาห์ และต้องทำอะไรถึงจะแก้ได้ (รายงานอย่างเดียว)")
    ap.add_argument("--from", dest="d_from", required=True, help="วันเริ่มสัปดาห์ YYYY-MM-DD")
    ap.add_argument("--to", dest="d_to", required=True, help="วันจบสัปดาห์ YYYY-MM-DD")
    ap.add_argument("--per-rider", type=int, default=config.EXPECTED_TRIPS_PER_WEEK)
    ap.add_argument("--list", action="store_true", help="พิมพ์รายเที่ยวที่จะถูกเอาออก")
    ap.add_argument("--reassign", action="store_true",
                    help="หาเจ้าของใหม่ให้เที่ยวส่วนเกิน (ยังเป็นรายงาน จนกว่าจะใส่ --apply)")
    ap.add_argument("--apply", action="store_true",
                    help="ทำจริง: ย้ายรูปบน Drive · เปลี่ยนเจ้าของแถว · สร้างรูปและ Excel ใหม่")
    a = ap.parse_args(argv)
    db.init_db()

    rows = db.query_trips(date_from=a.d_from, date_to=a.d_to)
    if not rows:
        print(f"ไม่มีแถวที่ลงไฟล์แล้วในช่วง {a.d_from}..{a.d_to}")
        return 0
    riders = {t["driver_name"] for t in rows}
    print(f"{a.d_from}..{a.d_to} · {len(rows)} เที่ยว · {len(riders)} ไรเดอร์ · โควตา {a.per_rider}/คน")

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
