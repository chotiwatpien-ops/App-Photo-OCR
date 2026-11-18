# -*- coding: utf-8 -*-
"""What each Admin sent in one week and what came of it, for accounting to pay from (2026-11-17).

The customer asked for a confirmed weekly total to pay each Admin, and Fiat set the scope:
- every album placed in the week's folder;
- work that can be used, and work that cannot, with the reason;
- how many pictures were sent, half pictures and full pictures counted apart.

An album is reported in the week it first came in. The trips the pool sent on to the next week
because this week was full stay on this report, in a column of their own, so the next week's
report does not pay for them again.

Read only: the database, the action log and the pool's own run reports. No Drive, so the web app
can build it.
"""
import collections
import io
import json
import math
import re
from datetime import date, timedelta

from sqlalchemy import func, select

import db
import duplicate_report as dr
import same_trip
from pipeline import car_is_standard

SERVICES = ("Saver Bike", "Standard Bike", "Standard Car")
# what a trip row's status means for the person being paid
REPEAT, UNREADABLE, VOIDED, SET_ASIDE = "ซ้ำ (เลขจองซ้ำ)", "อ่านไม่ได้", "ยกเลิก", "พักไว้"
UNUSABLE = {"duplicate": REPEAT, "voided": VOIDED, "error": UNREADABLE, "set_aside": SET_ASIDE}
DELETED = "ลบในคิวตรวจ"
# The queue tells people to delete a repeat, so most deletes are repeats (W46/W47: all 4)
DELETED_REPEAT = "ซ้ำ (คนกดลบ)"
COPY ="รูปซ้ำเป๊ะ (ไฟล์เดียวกัน)"
UNPAIRED = "รูปครึ่งที่หาคู่ไม่ได้"
WAITING_PAIR = "รูปครึ่งรอคู่"                  # the same pictures while the week is open
READING, REVIEW, FILING = "รออ่าน", "รอคนตรวจ", "รอลงไฟล์"
TAG = re.compile(r"_(\d+)\+(\d+)_฿")
WHEEL = re.compile(r"^\s*(?:\d\s*W)\s*[-_ ]*(?:(?:win|home|taxi)\b\s*[-_ ]*)?", re.I)
# Part of an album Ops uploaded under another name. W46: 1,728 + these 20 = the 1,748 in the name
# of the album they came from (Fiat 2026-11-18: count them as one).
ALBUM_INTO = {"2W Karnjana ทดสอบ": "2W Karnjana 1748 งาน"}


def canon(album):
    return ALBUM_INTO.get(album, album)


def _raw_names(albums):
    """The names these albums are stored under."""
    return set(albums) | {k for k, v in ALBUM_INTO.items() if v in albums}


def admin_of(album):
    """The Admin named in an album's name: '2W Parichart2  473 งาน' → 'Parichart'.

    A best reading of names Ops type by hand; the sheet shows it beside the album so a wrong
    one is seen."""
    rest = WHEEL.sub("", album or "")
    m = re.match(r"([A-Za-z฀-๿]+)", rest)
    if not m:
        return album or "ไม่รู้อัลบั้ม"
    name = re.sub(r"(งาน|รวม)+$", "", m.group(1)) or m.group(1)
    return name[:1].upper() + name[1:] if name.isascii() else name


def _pictures(file_name, kind=None, status=None):
    """(full, half) pictures behind one trip row."""
    if dr.ALBUM.match(file_name or ""):
        return 0, 2                                  # a pair the pool stitched from two halves
    if status == "merged" or kind in ("top", "bottom"):
        return 0, 1
    return 1, 0


COLS = [db.trips.c[k] for k in ("id", "job_id", "file_name", "status", "committed", "kind", "service_type",
                                 "booking_code", "base_fare", "net_earnings", "source_url", "source_album",
                                 "note")]


def _half_tag(file_name):
    from pool_names import half_tag            # not pool: it imports the OCR stack the web app lacks
    return half_tag(file_name) if file_name else None


def _week_rows(d_from, d_to):
    t, j = db.trips.c, db.jobs.c
    with db.engine.begin() as c:
        return [dict(r) for r in c.execute(
            select(*COLS, j.folder_name, j.driver_name, j.date_from)
            .select_from(db.trips.join(db.jobs, j.id == t.job_id))
            .where(j.date_from >= d_from, j.date_from <= d_to)).mappings().all()]


def _later_rows(albums, d_to):
    """Rows of these albums filed in later weeks: the part the pool sent on."""
    if not albums:
        return []
    t, j = db.trips.c, db.jobs.c
    with db.engine.begin() as c:
        return [dict(r) for r in c.execute(
            select(*COLS, j.folder_name, j.driver_name, j.date_from)
            .select_from(db.trips.join(db.jobs, j.id == t.job_id))
            .where(t.source_album.in_(sorted(albums)), j.date_from > d_to)).mappings().all()]


def _first_week(albums):
    """{album: the first week any of its rows was filed in}."""
    if not albums:
        return {}
    t, j = db.trips.c, db.jobs.c
    out = {}
    with db.engine.begin() as c:
        for a, w in c.execute(select(t.source_album, func.min(j.date_from))
                              .select_from(db.trips.join(db.jobs, j.id == t.job_id))
                              .where(t.source_album.in_(sorted(_raw_names(albums))))
                              .group_by(t.source_album)).all():
            a = canon(a.strip())
            out[a] = min(w, out.get(a, w))
    return out


def _group(rows, key, value):
    out = collections.defaultdict(collections.Counter)
    for r in rows:
        out[r[key]][value(r)] += 1
    return out


def _deleted(d_from, job_ids):
    """Rows a person deleted in the review queue, from the action log (the row itself is gone)."""
    with db.engine.begin() as c:
        details = c.execute(select(db.action_log.c.detail).where(
            db.action_log.c.action == "trip.delete", db.action_log.c.at >= d_from,
            db.action_log.c.status == 200)).scalars().all()
    out = []
    for d in details:
        try:
            row = json.loads(d or "{}").get("row") or {}
        except ValueError:
            continue
        if row.get("job_id") in job_ids and row.get("file_name"):
            out.append(row)
    return out


def _monday(day):
    d = date.fromisoformat(day)
    return d - timedelta(days=d.weekday())


def _twin(deleted, counted):
    """The counted trip a deleted row repeats, or None. `counted` is one week's: a repeat across
    weeks is work (customer, 2026-09-14)."""
    code = same_trip.fold(deleted.get("booking_code"))
    if not code:
        return None
    return next((r for r in counted if same_trip.fold(r.get("booking_code")) == code),
                next((r for r in counted if same_trip.kind(deleted, r) == same_trip.CODE), None))


def _copies(albums):
    t = db.skipped_copies.c
    with db.engine.begin() as c:
        return [dict(r) for r in c.execute(select(db.skipped_copies).where(t.album.in_(sorted(albums))))
                .mappings().all()] if albums else []


def _leftovers(d_from, d_to, albums, earlier):
    """{album: [file, ...]} half pictures still unpaired, from the latest pool run that saw each
    album in each week folder (a closed week's pool is not scanned again, so its last word stays).

    Also an album placed in this week's folder that has no trip yet: every picture it holds so far
    is waiting for its other half, and without this line it would not be on the report at all."""
    import ingest
    with db.engine.begin() as c:
        reports = c.execute(select(db.pool_runs.c.report).where(
            db.pool_runs.c.mode == "move", db.pool_runs.c.started_at >= d_from)
            .order_by(db.pool_runs.c.id.desc()).limit(400)).scalars().all()
    seen, out, first = set(), collections.defaultdict(list), {}
    for rep in reports:
        try:
            entries = json.loads(rep or "{}").get("albums") or []
        except ValueError:
            continue
        for e in entries:
            key = (e.get("album"), e.get("week"))
            rng = ingest.parse_range(e.get("week") or "")
            if not e.get("album") or key in seen or not rng:
                continue
            seen.add(key)
            a, week = canon(e["album"].strip()), rng[0].isoformat()
            first[a] = min(week, first.get(a, week))
            if a in albums or (d_from <= week <= d_to and a not in earlier):
                out[a] += [x.get("file") for x in e.get("leftovers") or []]
    filed_from = _first_week({a for a in out if a not in albums})   # the rest of it was filed earlier
    return {a: f for a, f in out.items()
            if f and (a in albums or (first[a] >= d_from and filed_from.get(a, d_from) >= d_from))}


def build(d_from, d_to):
    """{"albums": [..], "admins": [..], "items": [..]} for the albums placed in this week."""
    from ingest import week_label
    closed = db.week_closed(d_from)
    unpaired_why = UNPAIRED if closed else WAITING_PAIR
    week_rows = _week_rows(d_from, d_to)
    album_of = lambda r: canon(dr.album_of(r["file_name"], r.get("folder_name"), r.get("driver_name"),
                                           r.get("source_album")))
    pool_albums = {canon((r.get("source_album") or "").strip()) for r in week_rows
                   if (r.get("source_album") or "").strip()}
    first = _first_week(pool_albums)
    earlier = {a for a, w in first.items() if w < d_from}          # an earlier week's report holds them
    from_earlier = collections.Counter(album_of(r) for r in week_rows if album_of(r) in earlier
                                       and r["status"] == "done" and r["committed"] == 1)
    rows = [r for r in week_rows if album_of(r) not in earlier]
    mine = {album_of(r) for r in rows}
    later = _later_rows(_raw_names({a for a in pool_albums if a in mine}), d_to)
    rows += later
    counted = collections.defaultdict(list)                 # Monday -> trips counted that week
    for r in week_rows + later:
        if r["status"] == "done" and r["committed"] == 1:
            counted[_monday(r["date_from"])].append(r)
    # a deleted row is gone; its album is in its file name (a pair), the trip it repeats, or else
    # its job's other rows
    job_album = {}
    for j_id, names in _group(rows, "job_id", album_of).items():
        job_album[j_id] = names.most_common(1)[0][0]
    with db.engine.begin() as c:
        job_from = dict(c.execute(select(db.jobs.c.id, db.jobs.c.date_from)
                                  .where(db.jobs.c.date_from >= d_from)).all())
    here = {j for j, w in job_from.items() if w <= d_to}
    deleted = []
    for d in _deleted(d_from, here | set(job_album)):
        d["twin"] = _twin(d, counted[_monday(job_from[d["job_id"]])])
        named = canon((d.get("source_album") or "").strip() or (
            dr.album_of(d["file_name"]) if dr.ALBUM.match(d["file_name"]) else "")
            or (album_of(d["twin"]) if d["twin"] else ""))
        if d["job_id"] in here:
            d["album"] = named or job_album.get(d["job_id"], "ไม่รู้อัลบั้ม")
            if d["album"] not in earlier:
                deleted.append(d)
        elif named in mine:
            # a later week's rider holds work of many albums: only a row whose album is known
            d["album"] = named
            deleted.append(d)
    left = _leftovers(d_from, d_to, mine, earlier)
    copies = _copies(_raw_names(mine | set(left)))

    acc = collections.defaultdict(lambda: {
        "full": 0, "half": 0, "unknown": 0, "used_here": collections.Counter(), "used_later": 0,
        "waiting": collections.Counter(), "bad": collections.Counter(),
        "bad_pictures": collections.Counter(), "copy_full": 0, "copy_half": 0})
    items = []
    tags = collections.defaultdict(set)                     # album -> half tags of its pairs
    longs = collections.defaultdict(set)                    # album -> file names of its long pictures
    for r in rows:
        a = album_of(r)
        m = TAG.search(r["file_name"] or "")
        if m:
            tags[a].update(m.groups())
        elif r["status"] != "merged":
            longs[a].add(r["file_name"])
    for r in rows:
        a, v = album_of(r), acc[album_of(r)]
        full, half = _pictures(r["file_name"], r.get("kind"), r["status"])
        v["full"] += full
        v["half"] += half
        st = r["status"]
        if st == "merged":
            continue                                          # a lower half joined to its top
        if st == "done" and r["committed"] == 1:
            if r["date_from"] <= d_to:
                v["used_here"][car_is_standard((r.get("service_type") or "").strip()) or "ไม่รู้ประเภท"] += 1
            else:
                v["used_later"] += 1
        elif st == "pending":
            v["waiting"][READING] += 1
        elif st == "done":
            v["waiting"][FILING if r.get("driver_name") == db.HOLDING_RIDER else REVIEW] += 1
        else:
            why = UNUSABLE.get(st, st)
            v["bad"][why] += 1
            items.append({"album": a, "why": why, "file": r["file_name"], "code": r.get("booking_code"),
                          "amount": r.get("net_earnings"), "pictures": "เต็ม" if full else f"ครึ่ง {half}",
                          "link": r.get("source_url"), "note": r.get("note")})
    for d in deleted:
        a = d["album"]
        v = acc[a]
        full, half = _pictures(d["file_name"], d.get("kind"))
        v["full"] += full
        v["half"] += half
        why = DELETED_REPEAT if d["twin"] else DELETED
        v["bad"][why] += 1
        items.append({"album": a, "why": why, "file": d["file_name"], "code": d.get("booking_code"),
                      "amount": d.get("net_earnings"), "pictures": "เต็ม" if full else f"ครึ่ง {half}",
                      "link": d.get("source_url"),
                      "note": f"ซ้ำกับ {d['twin']['file_name']}" if d["twin"] else ""})
    for cp in copies:
        a = canon((cp.get("album") or "").strip())
        kept = (cp.get("same_as") or "").split("/")[-1]
        tag = _half_tag(kept)
        if kept in longs[a]:
            kind = "เต็ม"
            acc[a]["full"] += 1
            acc[a]["copy_full"] += 1
        elif tag and tag in tags[a] or kept in left.get(a, []):
            kind = "ครึ่ง 1"
            acc[a]["half"] += 1
            acc[a]["copy_half"] += 1
        else:
            kind = "ไม่ทราบ"
            acc[a]["unknown"] += 1
        acc[a]["bad_pictures"][COPY] += 1
        items.append({"album": a, "why": COPY, "file": cp.get("file_name"), "code": None, "amount": None,
                      "pictures": kind, "note": f"ซ้ำกับ {cp.get('same_as')}",
                      "link": f"https://drive.google.com/file/d/{cp['drive_id']}/view" if cp.get("drive_id") else None})
    for a, files in left.items():
        for f in files:
            acc[a]["half"] += 1
            acc[a]["bad_pictures"][UNPAIRED] += 1
            items.append({"album": a, "why": unpaired_why, "file": f, "code": None, "amount": None,
                          "pictures": "ครึ่ง 1", "link": None, "note": ""})

    albums = []
    for a, v in acc.items():
        used_here = sum(v["used_here"].values())
        waiting = sum(v["waiting"].values())
        bad = {k: v["bad"].get(k, 0) for k in BAD_TRIPS}
        lone = v["bad_pictures"].get(UNPAIRED, 0)
        final = used_here + v["used_later"]
        # in trips: a full picture is one, two halves are one, a lone half is still one trip short
        dup_copy = v["copy_full"] + math.ceil((v["copy_half"] + v["unknown"]) / 2)
        dup_read = bad[REPEAT] + bad[DELETED_REPEAT]
        other = bad[UNREADABLE] + bad[VOIDED] + bad[SET_ASIDE]
        pending = waiting + math.ceil(lone / 2)
        jobs = final + dup_copy + dup_read + bad[DELETED] + other + pending
        ops = dr.ops_count(a)
        albums.append({
            "album": a, "admin": admin_of(a), "pictures": v["full"] + v["half"] + v["unknown"],
            "full": v["full"], "half": v["half"], "unknown": v["unknown"],
            "usable": used_here + v["used_later"] + waiting, "used_here": used_here,
            **{s: v["used_here"].get(s, 0) for s in SERVICES},
            "used_later": v["used_later"], "waiting": waiting,
            "unusable": sum(v["bad"].values()), **bad,
            **{k: v["bad_pictures"].get(k, 0) for k in BAD_PICTURES},
            "jobs": jobs, "final": final, "dup": dup_copy + dup_read, "dup_copy": dup_copy,
            "other": other, "pending": pending,
            "read": final + v["waiting"][REVIEW] + v["waiting"][FILING] + dup_read + bad[DELETED]
                    + bad[VOIDED] + bad[SET_ASIDE],
            READING: v["waiting"][READING], REVIEW: v["waiting"][REVIEW], FILING: v["waiting"][FILING],
            "ops": ops, "ops_gap": ops - jobs if ops is not None else None})
    albums.sort(key=lambda x: (x["admin"].lower(), x["album"]))
    admins = []
    for name in sorted({x["admin"] for x in albums}, key=str.lower):
        mine_ = [x for x in albums if x["admin"] == name]
        admins.append(_total(mine_, admin=name, albums=len(mine_)))
    items.sort(key=lambda x: (admin_of(x["album"]).lower(), x["album"], x["why"], str(x["file"])))
    return {"week": week_label(d_from), "d_from": d_from, "d_to": d_to, "closed": closed,
            "made_at": db._now(), "albums": albums, "admins": admins, "items": items,
            "total": _total(albums, admin="รวม", albums=len(albums)),
            "from_earlier": dict(from_earlier)}


def _total(rows, **head):
    """The rows added up. Ops' count only when every album has one: a part would mislead."""
    known = bool(rows) and all(x["ops"] is not None for x in rows)
    return {**head, **{k: sum(x[k] for x in rows) for k in SUM_KEYS},
            "ops": sum(x["ops"] for x in rows) if known else None,
            "ops_gap": sum(x["ops_gap"] for x in rows) if known else None}


BAD_TRIPS = (REPEAT, DELETED_REPEAT, DELETED, UNREADABLE, VOIDED, SET_ASIDE)
BAD_PICTURES = (COPY, UNPAIRED)
SUM_KEYS = ("pictures", "full", "half", "unknown", "usable", "used_here", *SERVICES, "used_later",
            "waiting", "unusable", *BAD_TRIPS, *BAD_PICTURES, "jobs", "final", "dup", "dup_copy",
            "other", "pending", "read", READING, REVIEW, FILING)
# the first sheet: one line per Admin with its albums under it
SUMMARY = [("full", "รูปเต็ม"), ("half", "รูปครึ่ง"), ("jobs", "เทียบงาน"), ("ops", "Ops จด"),
           ("ops_gap", "Ops มากกว่า (+) / น้อยกว่า (-)"), ("read", "อ่านได้"), ("final", "Final"),
           ("used_here", "Final · ลงไฟล์สัปดาห์นี้"), ("used_later", "Final · ไปลงสัปดาห์ถัดไป"),
           ("dup", "ซ้ำ"), (DELETED, "ลบ"), ("other", "ใช้ไม่ได้อื่นๆ"), ("pending", "ค้าง"),
           ("dup_copy", "ซ้ำ · รูปซ้ำเป๊ะ (งาน)"), (REPEAT, "ซ้ำ · เลขจองซ้ำ"), (DELETED_REPEAT, "ซ้ำ · คนกดลบ"),
           (UNREADABLE, "อื่นๆ · อ่านไม่ได้"), (VOIDED, "อื่นๆ · ยกเลิก"), (SET_ASIDE, "อื่นๆ · พักไว้"),
           (READING, f"ค้าง · {READING}"), (REVIEW, f"ค้าง · {REVIEW}"), (FILING, f"ค้าง · {FILING}"),
           (UNPAIRED, f"ค้าง · {WAITING_PAIR} (รูป)")]
COLUMNS = [("pictures", "รูปที่ส่งมา"), ("full", "รูปเต็ม"), ("half", "รูปครึ่ง"), ("unknown", "รูปไม่ทราบชนิด"),
           ("usable", "งานที่ใช้ได้"), ("used_here", "ลงไฟล์สัปดาห์นี้"),
           *[(s, f"ลงไฟล์ · {s}") for s in SERVICES],
           ("used_later", "ไปลงสัปดาห์ถัดไป"), ("waiting", "ยังรอตรวจ/รออ่าน"),
           ("unusable", "งานที่ใช้ไม่ได้"), *[(k, f"ใช้ไม่ได้ · {k}") for k in BAD_TRIPS],
           *[(k, k) for k in BAD_PICTURES]]


def build_xlsx(data) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    head, fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1E3A5F")
    bold, band = Font(bold=True), PatternFill("solid", fgColor="E8EEF5")
    state = "ปิดสัปดาห์แล้ว" if data["closed"] else "ยอดชั่วคราว สัปดาห์ยังไม่ปิด ตัวเลขยังเปลี่ยนได้"

    ws = wb.active
    ws.title = "สรุป"
    ws.append([f"รายงานบัญชี {data['week']} ({data['d_from']} ถึง {data['d_to']}) · {state} · "
               f"ออกเมื่อ {data['made_at'].replace('T', ' ')}"])
    ws["A1"].font = Font(bold=True, size=13, color="000000" if data["closed"] else "B45309")
    ws.append(["Admin / อัลบั้ม"] + [h for _k, h in SUMMARY])
    for c in ws[2]:
        c.font, c.fill = head, fill
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
    ws.row_dimensions[2].height = 48
    ws.sheet_properties.outlinePr.summaryBelow = False

    def line(name, row, strong=False, child=False):
        ws.append([name] + [row[k] for k, _h in SUMMARY])
        at = ws.max_row
        if child:
            ws.cell(at, 1).alignment = Alignment(indent=2)
            ws.row_dimensions[at].outlineLevel = 1
        for c in ws[at]:
            if strong:
                c.font, c.fill = bold, band
            if c.column > 1:
                c.number_format = "#,##0"

    for a in data["admins"]:
        line(a["admin"], a, strong=True)
        for x in data["albums"]:
            if x["admin"] == a["admin"]:
                line(x["album"], x, child=True)
    line("รวมทุก Admin", data["total"], strong=True)
    if data["from_earlier"]:
        ws.append([])
        ws.append([f"งานจากอัลบั้มของสัปดาห์ก่อนที่ลงไฟล์สัปดาห์นี้ {sum(data['from_earlier'].values()):,} งาน "
                   "(นับในรายงานของสัปดาห์ที่วางอัลบั้มแล้ว ไม่นับซ้ำที่นี่): "
                   + " · ".join(f"{a} {n:,}" for a, n in sorted(data["from_earlier"].items()))])
    ws.freeze_panes = "B3"
    ws.column_dimensions["A"].width = 34
    for i in range(2, len(SUMMARY) + 2):
        ws.column_dimensions[ws.cell(2, i).column_letter].width = 12

    def sheet(ws, header, rows):
        ws.append(header)
        for c in ws[1]:
            c.font, c.fill = head, fill
        for r in rows:
            ws.append(r)
        ws.freeze_panes = "B2"
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = max(10, min(48, max(len(str(c.value or "")) for c in col) + 2))

    heads = [h if data["closed"] else h.replace(UNPAIRED, WAITING_PAIR) for _k, h in COLUMNS]
    sheet(wb.create_sheet("สรุปต่อ Admin"), ["Admin", "จำนวนอัลบั้ม"] + heads,
          [[a["admin"], a["albums"]] + [a[k] for k, _h in COLUMNS] for a in data["admins"]]
          + [["รวม", sum(a["albums"] for a in data["admins"])]
             + [sum(a[k] for a in data["admins"]) for k, _h in COLUMNS]])
    sheet(wb.create_sheet("รายอัลบั้ม"), ["Admin (อ่านจากชื่ออัลบั้ม)", "อัลบั้ม"] + heads
          + ["ยอดที่ Ops จดในชื่ออัลบั้ม"],
          [[x["admin"], x["album"]] + [x[k] for k, _h in COLUMNS] + [x["ops"]] for x in data["albums"]])
    sheet(wb.create_sheet("รายการที่ใช้ไม่ได้"),
          ["Admin", "อัลบั้ม", "เหตุผล", "รูป", "ไฟล์", "รหัสการจอง", "ยอด", "หมายเหตุ", "ลิงก์รูป"],
          [[admin_of(i["album"]), i["album"], i["why"], i["pictures"], i["file"], i["code"], i["amount"],
            i["note"], i["link"]] for i in data["items"]])
    ws = wb.create_sheet("อ่านก่อน")
    for text in (f"รายงานบัญชี {data['week']} ({data['d_from']} ถึง {data['d_to']}) · {state}",
                 "นับทุกอัลบั้มที่วางในโฟลเดอร์ของสัปดาห์นี้ อัลบั้มนับในสัปดาห์ที่วางครั้งแรก",
                 "เทียบงาน = Final + ซ้ำ + ลบ + ใช้ไม่ได้อื่นๆ + ค้าง",
                 "ซ้ำ รวมงานที่คนกดลบ เมื่อเลขจองตรงกับงานที่นับแล้วในสัปดาห์เดียวกัน "
                 "(หรือต่างกันไม่เกิน 2 ตัวและค่ารอบตรงกัน) · ลบ = งานที่คนกดลบและไม่ตรงกับงานไหน",
                 "รูปเต็ม 1 รูป = 1 งาน · รูปครึ่ง 2 รูป = 1 งาน · รูปครึ่งที่เหลือเศษนับเป็น 1 งาน",
                 "อ่านได้ = งานที่ AI อ่านผลแล้ว · Final = งานที่ใช้ได้ รวมส่วนที่ไปลงสัปดาห์ถัดไป",
                 "งานที่ใช้ได้ = Final + งานที่ยังรอตรวจหรือรออ่าน",
                 "รูปที่ส่งมา รวมรูปซ้ำเป๊ะและรูปครึ่งที่ยังไม่มีคู่",
                 "ชื่อ Admin อ่านจากชื่ออัลบั้ม ถ้าไม่ตรง ให้ดูแถวอัลบั้ม",
                 "อัลบั้มที่รวมกัน: " + " · ".join(f"{k} นับเป็น {v}" for k, v in ALBUM_INTO.items())):
        ws.append([text])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def file_name(data):
    return f"บัญชี {data['week']}{'' if data['closed'] else ' (ชั่วคราว)'}.xlsx"
