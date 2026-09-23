# -*- coding: utf-8 -*-
"""Top up delivered weeks from a folder Ops hands over, only the groups still short.

W34 and W35 went back to the customer clean (apply_clean.py), each group below its 1,470. Ops
sent a folder of pictures to fill the gaps (Fiat 2026-09-23), with three rules:
  * only these two weeks — nothing from the folder goes to any other week until they say so;
  * only the vehicle types a week is short of — a group at or over target takes nothing;
  * riders already working the week take the extra trips, past 21 each; no new names; dates
    fall inside the week.
Every round skips a closed week, so none of this can go through the normal round.

Three steps, each its own run:
  --read    pair the halves as the pool does (pool.analyse), join each trip into one picture and
            read it into the first week's '(รออ่าน)' job. A row there counts nowhere: not in the
            scorecard, not in any file, not in the dashboard. Pictures read before are skipped,
            so a second --read picks up only what was added to the folder since.
  (plain)   the plan: for every read row, a repeat of W34/W35 or not, which week and group it
            would join, and why the rest would not.
  --apply   does the plan: each row moves to the rider in its week and group who has the fewest
            trips, gets a day of that week, and a delivered picture numbered after the rider's
            last one in Exports/<week>/<group>/. Rows whose figures do not add up, repeats and
            whatever no week has room for stay in the waiting job and are listed — they never
            go to another week.

    python refill_weeks.py --source <folder id>[,<folder id>] --weeks 2026-08-17,2026-08-24 --read
    python refill_weeks.py --source ... --weeks ...                 # the plan
    python refill_weeks.py --source ... --weeks ... --apply
"""
import argparse
import hashlib
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from sqlalchemy import select, update

import config
import db
from file_after_read import GROUP_OF, HOLDING_RIDER, room_left
from ingest import week_label
from pipeline import _number_in, car_is_standard
import stitch
from week_phase3 import codes_agree, norm_code, week_rows

MARK = "เติมงาน Ops"                 # every row this reads carries it at the start of its note
SKIP_DEFAULT = r"\d+\s*Aug\.jpg$"     # Ops' page-sized collages — cut apart and sent separately
READ_PARALLEL = 16


def week_end(d_from):
    return (date.fromisoformat(d_from) + timedelta(days=6)).isoformat()


# ---------------------------------------------------------------- reading ------------------------
def albums_in(drive, folder_ids, skip=SKIP_DEFAULT):
    """Every sub-folder of each source is one album, as the pool's albums are; pictures lying
    loose in a source form an album named after it."""
    pat = re.compile(skip) if skip else None
    out = []
    for fid in folder_ids:
        meta = drive.file_meta(fid) if hasattr(drive, "file_meta") else {}
        subs = [(f["name"], f["id"]) for f in drive.list_folders(fid) if not f["name"].startswith("_")]
        for name, sid in [(meta.get("name") or fid, fid)] + subs:
            imgs = [i for i in drive.list_images(sid) if not (pat and pat.search(i["name"]))]
            if imgs:
                out.append({"album": name, "week": "เติมงาน", "group": "", "images": imgs})
    return out


def trips_in(drive, albums, workers=12, log=print):
    """[(album, label, jpeg bytes)] — one per trip: a stitched pair or a whole picture."""
    import pool
    errors = []
    data = pool.Images({}, fetch_one=drive.download, workers=workers, errors=errors)
    report = pool.analyse(albums, data, workers)
    out = []
    for e in report["albums"]:
        for p in e["pairs"]:
            out.append((e["album"], f"{p['top']}+{p['bottom']}",
                        stitch.stitch(data[p["top_id"]], data[p["bottom_id"]])))
        for x in e["long"]:
            out.append((e["album"], x["file"], stitch.stitch(data[x["id"]])))
        log(f"  {e['album']}: {e['n_images']} รูป → คู่ {len(e['pairs'])} · ทั้งใบ {len(e['long'])} · "
            f"ค้าง {len(e['leftovers'])} · ซ้ำในกอง {e['n_duplicates']}")
    for err in errors + report.get("errors", []):
        log(f"  ⚠ {err}")
    return out


def holding_job(d_from):
    d_to = week_end(d_from)
    for j in db.jobs_by_week().get((d_from, d_to), []):
        if (j.get("driver_name") or "") == HOLDING_RIDER:
            return j["id"]
    return db.create_job(HOLDING_RIDER, "Trips", d_from, d_to)


def read_rows(drive, folder_ids, weeks, staged_parent, skip=SKIP_DEFAULT, log=print):
    """Read every trip in the folders not read before into the first week's waiting job."""
    import pipeline
    jid = holding_job(weeks[0])
    have = set()
    for d_from in weeks:
        have |= set(db.seen_image_hashes_week(d_from, week_end(d_from)))
    trips = trips_in(drive, albums_in(drive, folder_ids, skip), log=log)
    fresh, seen = [], 0
    for album, label, data in trips:
        h = hashlib.sha1(data).hexdigest()
        if h in have:
            seen += 1
            continue
        have.add(h)
        fresh.append((album, label, data, h))
    log(f"เที่ยวในกอง {len(trips)} · อ่านไปแล้ว/ซ้ำไฟล์ใน W34-W35 {seen} · ต้องอ่าน {len(fresh)}")
    staged = drive.ensure_folder(staged_parent, "_ต่อแล้ว")

    def one(item):
        album, label, data, h = item
        name = f"{album}_{label}".replace("/", "_")
        fid = drive.upload_file(staged, name if name.lower().endswith(".jpg") else name + ".jpg",
                                data, "image/jpeg")
        tid = db.create_trip(jid, name, None, "image/jpeg",
                             source_url=f"https://drive.google.com/file/d/{fid}/view",
                             image_hash=h, source_album=album)
        db.update_trip(tid, {"note": f"{MARK}: {album}/{label}"})
        st = pipeline.process_trip(tid, jid, image=(data, "image/jpeg"))
        if st == "done":                         # the reader writes its own note — keep ours first
            r = db.get_trip(tid)
            if not (r.get("note") or "").startswith(MARK):
                db.update_trip(tid, {"note": f"{MARK}: {album}/{label}" + (f" | {r['note']}" if r.get("note") else "")})
        return st
    with ThreadPoolExecutor(max_workers=READ_PARALLEL) as ex:
        res = Counter(ex.map(one, fresh))
    db.refresh_job_status(jid)
    log(f"อ่านแล้ว {res.get('done', 0)} · error {res.get('error', 0)} → job #{jid} (รออ่าน) {weeks[0]}")
    return res


# ---------------------------------------------------------------- planning -----------------------
def waiting_rows(d_from):
    t, j = db.trips.c, db.jobs.c
    with db.engine.begin() as c:
        rows = c.execute(select(db.trips, j.driver_name)
                         .select_from(db.trips.join(db.jobs, j.id == t.job_id))
                         .where(j.date_from == d_from, j.date_to == week_end(d_from),
                                j.driver_name == HOLDING_RIDER, t.note.like(f"{MARK}%"))
                         .order_by(t.id)).mappings().all()
    return [dict(r) for r in rows]


PAGE_ALBUM = re.compile(r"\d+\s*Aug$|_p\d+$")      # one of Ops' collage or PDF pages, cut into screens


def source_of(r):
    """(album, label) this row was read from — kept at the start of its note by read_rows."""
    m = re.match(rf"{MARK}: (.*?)/([^|]*?)(?: \||$)", r.get("note") or "")
    return (m.group(1), m.group(2).strip()) if m else (None, None)


def half_of_page(r):
    """A screen of a cut page that the pool took for a whole picture is half a trip: a page's
    trips are two screens each, and only a pair (or two screens joined by their place on the
    page) is whole. The two pages whose grid the cutter misread did this (สัญญา/ชุมสิน 6 Aug)."""
    album, label = source_of(r)
    return bool(album and PAGE_ALBUM.search(album) and "+" not in (label or ""))


def _fingerprint(r):
    """A slip without a booking code (the old app screen) is one trip by its money and distance."""
    if r.get("base_fare") in (None, 0) or r.get("distance_km") in (None, 0):
        return None
    return (GROUP_OF.get(car_is_standard((r.get("service_type") or "").strip())),
            round(r["base_fare"]), round(r.get("net_earnings") or 0), round(r["distance_km"], 1))


class Seen:
    """What the two weeks already hold, and what this top-up adds as it goes."""

    def __init__(self, rows):
        self.codes, self.prints = {}, {}
        for r in rows:
            self.add(r)

    def add(self, r):
        c = norm_code(r.get("booking_code"))
        if c:
            self.codes.setdefault(c[:8], []).append(r)
        fp = _fingerprint(r)
        if fp:
            self.prints.setdefault(fp, r)

    def repeat_of(self, r):
        c = norm_code(r.get("booking_code"))
        if c:
            for other in self.codes.get(c[:8], []):
                if codes_agree(r.get("booking_code"), other.get("booking_code")):
                    return other
            return None                  # a code nobody else has is new, whatever its money
        fp = _fingerprint(r)
        return self.prints.get(fp) if fp else None


def riders(d_from):
    """{group: {job id: (rider, trips)}} — who already works the week, and how much."""
    d_to = week_end(d_from)
    n = Counter(r["job_id"] for r in week_rows(d_from, d_to))
    out = defaultdict(dict)
    for j in db.jobs_by_week().get((d_from, d_to), []):
        if (j.get("driver_name") or "") == HOLDING_RIDER or not j.get("category"):
            continue
        if n.get(j["id"]):
            out[j["category"]][j["id"]] = [j["driver_name"], n[j["id"]]]
    return out


def plan(weeks):
    """[(row, week or None, group, job id or None, why)] for every waiting row, in reading order."""
    existing = []
    for d_from in weeks:
        existing += week_rows(d_from, week_end(d_from))
    seen = Seen(existing)
    room = {d: room_left(d, week_end(d)) for d in weeks}
    who = {d: riders(d) for d in weeks}
    out = []
    for r in waiting_rows(weeks[0]):
        group = GROUP_OF.get(car_is_standard((r.get("service_type") or "").strip()))
        if r["status"] != "done":
            out.append((r, None, group, None, "อ่านไม่สำเร็จ"))
            continue
        if not group:
            out.append((r, None, group, None, f"ไม่ใช่งานรับคน/ไม่รู้ประเภท ({r.get('service_type') or '-'})"))
            continue
        if half_of_page(r):
            out.append((r, None, group, None, "จอเดียวจากหน้ารวมรูป/PDF — ไม่ครบเที่ยว"))
            continue
        if r.get("check_status") != "pass":
            out.append((r, None, group, None, "ตัวเลขไม่ลงตัว — รอคนดู"))
            continue
        other = seen.repeat_of(r)
        if other:
            where = f"#{other['id']} {other.get('driver_name') or ''}".strip()
            out.append((r, None, group, None, f"ซ้ำกับงานที่มีอยู่ ({where})"))
            continue
        placed = False
        for d in weeks:
            if room[d].get(group, 0) > 0 and who[d].get(group):
                jid = min(who[d][group], key=lambda k: (who[d][group][k][1], who[d][group][k][0]))
                who[d][group][jid][1] += 1
                room[d][group] -= 1
                seen.add({**r, "driver_name": who[d][group][jid][0]})
                out.append((r, d, group, jid, "เติม"))
                placed = True
                break
        if not placed:
            out.append((r, None, group, None, f"{group} ครบเป้าแล้วทั้ง {len(weeks)} สัปดาห์"))
    return out


# ---------------------------------------------------------------- applying -----------------------
def apply(drive, exports_id, planned, log=print):
    """File every row the plan placed. Returns how many were filed."""
    placed = [p for p in planned if p[1]]
    if not placed:
        return 0
    jobs = {j["id"]: j for js in db.jobs_by_week().values() for j in js}
    # a day of the week for each new trip, taking turns so no day piles up
    per_job = Counter()
    have = Counter(r["job_id"] for d in {p[1] for p in placed} for r in week_rows(d, week_end(d)))
    # the next picture number for each rider in each week, after the last one in use
    taken = {}
    folders = {}
    n = 0
    for r, d, group, jid, _why in placed:
        rider, wk = jobs[jid]["driver_name"], week_label(d)
        wkn = f"WK{date.fromisoformat(d).isocalendar()[1]:02d}"
        if (d, rider) not in taken:
            taken[(d, rider)] = {k for k in (_number_in(x, rider, wkn)
                                             for x in db.customer_images_in_week(d, week_end(d))) if k}
        nums = taken[(d, rider)]
        k = max(nums, default=0) + 1
        nums.add(k)
        name = stitch.customer_name(rider, k, wkn)
        if (wk, group) not in folders:
            folders[(wk, group)] = drive.ensure_folder(drive.ensure_folder(exports_id, wk), group)
        m = re.search(r"/d/([^/]+)", r.get("source_url") or "")
        drive.upload_file(folders[(wk, group)], name, drive.download(m.group(1)), "image/jpeg")
        i = have[jid] + per_job[jid]
        per_job[jid] += 1
        day = (date.fromisoformat(d) + timedelta(days=i % 7)).isoformat()
        db.move_trips_to_job([r["id"]], jid)
        db.update_trip(r["id"], {"trip_date": day, "customer_image": name,
                                 "note": f"{r['note']} | ลงให้ {rider} · {group} · {wk}"})
        with db.engine.begin() as c:            # approval is not a field a person edits
            c.execute(update(db.trips).where(db.trips.c.id == r["id"]).values(committed=1, auto_approved=1))
        n += 1
    for jid in {p[3] for p in placed}:
        db.refresh_job_status(jid)
    return n


def summary(planned, log=print):
    by = Counter((p[1], p[2]) for p in planned if p[1])
    for (d, g), k in sorted(by.items()):
        log(f"  เติม {week_label(d)} · {g}: {k}")
    for why, k in Counter(p[4] for p in planned if not p[1]).most_common():
        log(f"  ไม่เติม {k}: {why}")
    riders_used = Counter((p[1], p[3]) for p in planned if p[1])
    if riders_used:
        log(f"  ไรเดอร์ที่ได้งานเพิ่ม {len(riders_used)} คน · มากสุดคนละ {max(riders_used.values())} เที่ยว")


PLAN_COLS = ["id", "ที่มา", "Service Type", "ค่ารอบ", "คุณได้รับ", "ผู้โดยสารจ่าย", "รหัสการจอง",
             "ระยะทาง", "ผล", "สัปดาห์", "กลุ่ม", "ไรเดอร์", "เหตุผล"]


def plan_workbook(planned):
    """Every waiting row, what the plan does with it and why — for a person to read before --apply."""
    import io

    import openpyxl
    from openpyxl.styles import Font
    jobs = {j["id"]: j for js in db.jobs_by_week().values() for j in js}
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "สรุป"
    ws.append(["สัปดาห์", "กลุ่ม", "เติม"])
    for (d, g), k in sorted(Counter((p[1], p[2]) for p in planned if p[1]).items()):
        ws.append([week_label(d), g, k])
    ws.append([])
    ws.append(["ไม่เติม — เหตุผล", "", "จำนวน"])
    for why, k in Counter(re.sub(r" \(#.*\)$", "", p[4]) for p in planned if not p[1]).most_common():
        ws.append([why, "", k])
    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 14
    for title, rows in (("เติม", [p for p in planned if p[1]]), ("ไม่เติม", [p for p in planned if not p[1]])):
        sh = wb.create_sheet(title)
        sh.append(PLAN_COLS)
        for c in sh[1]:
            c.font = Font(bold=True)
        for r, d, g, jid, why in rows:
            album, label = source_of(r)
            sh.append([r["id"], f"{album}/{label}", r.get("service_type"), r.get("base_fare"),
                       r.get("net_earnings"), r.get("passenger_paid"), r.get("booking_code"),
                       r.get("distance_km"), "เติม" if d else "ไม่เติม", week_label(d) if d else None,
                       g, jobs[jid]["driver_name"] if jid in jobs else None, why])
        for col, w in zip("ABCDEFGHIJKLM", (8, 40, 14, 8, 9, 11, 20, 9, 8, 10, 13, 18, 44)):
            sh.column_dimensions[col].width = w
        sh.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def main(argv=None):
    ap = argparse.ArgumentParser(description="เติมงานสัปดาห์ที่ส่งแล้ว จากโฟลเดอร์ที่ Ops ให้ — เฉพาะกลุ่มที่ยังขาด")
    ap.add_argument("--source", default="", help="id โฟลเดอร์รูป (คั่นด้วยจุลภาค)")
    ap.add_argument("--weeks", required=True, help="วันจันทร์ของแต่ละสัปดาห์ เรียงตามลำดับที่จะเติมก่อน")
    ap.add_argument("--skip", default=SKIP_DEFAULT, help="regex ชื่อไฟล์ที่ไม่เอา")
    ap.add_argument("--read", action="store_true", help="จับคู่และอ่านรูปใหม่เข้าที่พัก")
    ap.add_argument("--apply", action="store_true", help="ลงงานตามแผนจริง")
    ap.add_argument("--report", default="", help="โฟลเดอร์ใน Exports ที่จะวางไฟล์แผนรายเที่ยว (ว่าง = ไม่เขียน)")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    db.init_db()
    weeks = [w.strip() for w in a.weeks.split(",") if w.strip()]
    shut = set(db.closed_weeks())
    for d in weeks:
        print(f"{week_label(d)} ({d}..{week_end(d)}){' · ปิดสัปดาห์แล้ว' if d in shut else ''} · "
              + " · ".join(f"{g} ว่าง {max(0, v)}" for g, v in sorted(room_left(d, week_end(d)).items())))
    drive = None
    if a.read or a.apply:
        import roster
        drive = roster._drive()
    if a.read:
        ids = [x.strip() for x in a.source.split(",") if x.strip()]
        if not ids:
            print("✗ ต้องระบุ --source")
            return 2
        wk = next((f for f in drive.list_folders(config.DRIVE_INBOX_FOLDER_ID)
                   if f["name"].strip() == weeks_folder_name(weeks[0])), None)
        parent = wk["id"] if wk else ids[0]
        read_rows(drive, ids, weeks, drive.ensure_folder(parent, f"_{MARK}"), a.skip)
    planned = plan(weeks)
    print(f"\nแผน: แถวที่อ่านแล้วรอเติม {len(planned)}")
    summary(planned)
    if a.report:
        import roster
        drive = drive or roster._drive()
        exp = config.DRIVE_EXPORTS_FOLDER_ID
        folder = next((f["id"] for f in drive.list_folders(exp) if f["name"].strip() == a.report), None) \
            or drive.ensure_folder(exp, a.report)
        name = f"แผนเติมงาน {'-'.join(week_label(d)[-3:] for d in weeks)}.xlsx"
        drive.upload_xlsx(folder, name, plan_workbook(planned))
        print(f"📋 แผนรายเที่ยว → Exports/{a.report}/{name}")
    if not a.apply:
        print("\n(รายงานอย่างเดียว — ใส่ --apply เพื่อลงงานจริง)")
        return 0
    n = apply(drive, config.DRIVE_EXPORTS_FOLDER_ID, planned)
    print(f"\n✓ ลงงานแล้ว {n} เที่ยว")
    return 0


def weeks_folder_name(d_from):
    """'2026-08-17' → 'Week 17-23 Aug' — the Inbox folder of that week."""
    a = date.fromisoformat(d_from)
    b = a + timedelta(days=6)
    if a.month == b.month:
        return f"Week {a.day}-{b.day} {a:%b}"
    return f"Week {a.day} {a:%b}-{b.day} {b:%b}"


if __name__ == "__main__":
    sys.exit(main())
