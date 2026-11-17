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
import re

from sqlalchemy import func, select

import db
import duplicate_report as dr
from pipeline import car_is_standard

SERVICES = ("Saver Bike", "Standard Bike", "Standard Car")
# what a trip row's status means for the person being paid
UNUSABLE = {"duplicate": "ซ้ำ (เลขจองซ้ำ)", "voided": "ยกเลิก", "error": "อ่านไม่ได้", "set_aside": "พักไว้"}
DELETED = "ลบในคิวตรวจ"
COPY = "รูปซ้ำเป๊ะ (ไฟล์เดียวกัน)"
UNPAIRED = "รูปครึ่งที่หาคู่ไม่ได้"
TAG = re.compile(r"_(\d+)\+(\d+)_฿")
WHEEL = re.compile(r"^\s*(?:\d\s*W)\s*[-_ ]*(?:(?:win|home|taxi)\b\s*[-_ ]*)?", re.I)


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
                                 "booking_code", "net_earnings", "source_url", "source_album", "note")]


def _half_tag(file_name):
    import pool
    return pool.half_tag(file_name) if file_name else None


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
    with db.engine.begin() as c:
        return {a.strip(): w for a, w in c.execute(
            select(t.source_album, func.min(j.date_from))
            .select_from(db.trips.join(db.jobs, j.id == t.job_id))
            .where(t.source_album.in_(sorted(albums))).group_by(t.source_album)).all()}


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


def _copies(albums):
    t = db.skipped_copies.c
    with db.engine.begin() as c:
        return [dict(r) for r in c.execute(select(db.skipped_copies).where(t.album.in_(sorted(albums))))
                .mappings().all()] if albums else []


def _leftovers(d_from, albums):
    """{album: [file, ...]} half pictures still unpaired, from the latest pool run that saw each
    album in each week folder (a closed week's pool is not scanned again, so its last word stays)."""
    import ingest
    with db.engine.begin() as c:
        reports = c.execute(select(db.pool_runs.c.report).where(
            db.pool_runs.c.mode == "move", db.pool_runs.c.started_at >= d_from)
            .order_by(db.pool_runs.c.id.desc()).limit(400)).scalars().all()
    seen, out = set(), collections.defaultdict(list)
    for rep in reports:
        try:
            entries = json.loads(rep or "{}").get("albums") or []
        except ValueError:
            continue
        for e in entries:
            key = (e.get("album"), e.get("week"))
            if e.get("album") not in albums or key in seen or not ingest.parse_range(e.get("week") or ""):
                continue
            seen.add(key)
            out[e["album"]] += [x.get("file") for x in e.get("leftovers") or []]
    return out


def build(d_from, d_to):
    """{"albums": [..], "admins": [..], "items": [..]} for the albums placed in this week."""
    from ingest import week_label
    week_rows = _week_rows(d_from, d_to)
    album_of = lambda r: dr.album_of(r["file_name"], r.get("folder_name"), r.get("driver_name"),
                                     r.get("source_album"))
    pool_albums = {(r.get("source_album") or "").strip() for r in week_rows if (r.get("source_album") or "").strip()}
    first = _first_week(pool_albums)
    earlier = {a for a, w in first.items() if w < d_from}          # an earlier week's report holds them
    rows = [r for r in week_rows if album_of(r) not in earlier]
    mine = {album_of(r) for r in rows}
    rows += _later_rows({a for a in pool_albums if a in mine}, d_to)
    # a deleted row is gone; its album is in its file name (a pair) or else its job's other rows
    job_album = {}
    for j_id, names in _group(rows, "job_id", album_of).items():
        job_album[j_id] = names.most_common(1)[0][0]
    with db.engine.begin() as c:
        here = set(c.execute(select(db.jobs.c.id).where(db.jobs.c.date_from >= d_from,
                                                        db.jobs.c.date_from <= d_to)).scalars())
    deleted = []
    for d in _deleted(d_from, here | set(job_album)):
        named = (d.get("source_album") or "").strip() or (
            dr.album_of(d["file_name"]) if dr.ALBUM.match(d["file_name"]) else "")
        if d["job_id"] in here:
            d["album"] = named or job_album.get(d["job_id"], "ไม่รู้อัลบั้ม")
            if d["album"] not in earlier:
                deleted.append(d)
        elif named in mine:
            # a later week's rider holds work of many albums: only a row that names its album
            d["album"] = named
            deleted.append(d)
    copies = _copies(mine)
    left = _leftovers(d_from, mine)

    acc = collections.defaultdict(lambda: {
        "full": 0, "half": 0, "unknown": 0, "used_here": collections.Counter(), "used_later": 0,
        "waiting": 0, "bad": collections.Counter(), "bad_pictures": collections.Counter()})
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
        elif st in ("done", "pending"):
            v["waiting"] += 1
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
        v["bad"][DELETED] += 1
        items.append({"album": a, "why": DELETED, "file": d["file_name"], "code": d.get("booking_code"),
                      "amount": d.get("net_earnings"), "pictures": "เต็ม" if full else f"ครึ่ง {half}",
                      "link": d.get("source_url"), "note": ""})
    for cp in copies:
        a = (cp.get("album") or "").strip()
        kept = (cp.get("same_as") or "").split("/")[-1]
        tag = _half_tag(kept)
        if kept in longs[a]:
            kind = "เต็ม"
            acc[a]["full"] += 1
        elif tag and tag in tags[a] or kept in left.get(a, []):
            kind = "ครึ่ง 1"
            acc[a]["half"] += 1
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
            items.append({"album": a, "why": UNPAIRED, "file": f, "code": None, "amount": None,
                          "pictures": "ครึ่ง 1", "link": None, "note": ""})

    albums = []
    for a, v in acc.items():
        used_here = sum(v["used_here"].values())
        albums.append({
            "album": a, "admin": admin_of(a), "pictures": v["full"] + v["half"] + v["unknown"],
            "full": v["full"], "half": v["half"], "unknown": v["unknown"],
            "usable": used_here + v["used_later"] + v["waiting"], "used_here": used_here,
            **{s: v["used_here"].get(s, 0) for s in SERVICES},
            "used_later": v["used_later"], "waiting": v["waiting"],
            "unusable": sum(v["bad"].values()), **{k: v["bad"].get(k, 0) for k in BAD_TRIPS},
            **{k: v["bad_pictures"].get(k, 0) for k in BAD_PICTURES},
            "ops": dr.ops_count(a)})
    albums.sort(key=lambda x: (x["admin"].lower(), x["album"]))
    admins = []
    for name in sorted({x["admin"] for x in albums}, key=str.lower):
        mine_ = [x for x in albums if x["admin"] == name]
        admins.append({"admin": name, "albums": len(mine_),
                       **{k: sum(x[k] for x in mine_) for k in SUM_KEYS}})
    items.sort(key=lambda x: (admin_of(x["album"]).lower(), x["album"], x["why"], str(x["file"])))
    return {"week": week_label(d_from), "d_from": d_from, "d_to": d_to,
            "albums": albums, "admins": admins, "items": items}


BAD_TRIPS = ("ซ้ำ (เลขจองซ้ำ)", DELETED, "อ่านไม่ได้", "ยกเลิก", "พักไว้")
BAD_PICTURES = (COPY, UNPAIRED)
SUM_KEYS = ("pictures", "full", "half", "unknown", "usable", "used_here", *SERVICES, "used_later",
            "waiting", "unusable", *BAD_TRIPS, *BAD_PICTURES)
COLUMNS = [("pictures", "รูปที่ส่งมา"), ("full", "รูปเต็ม"), ("half", "รูปครึ่ง"), ("unknown", "รูปไม่ทราบชนิด"),
           ("usable", "งานที่ใช้ได้"), ("used_here", "ลงไฟล์สัปดาห์นี้"),
           *[(s, f"ลงไฟล์ · {s}") for s in SERVICES],
           ("used_later", "ไปลงสัปดาห์ถัดไป"), ("waiting", "ยังรอตรวจ/รออ่าน"),
           ("unusable", "งานที่ใช้ไม่ได้"), *[(k, f"ใช้ไม่ได้ · {k}") for k in BAD_TRIPS],
           *[(k, k) for k in BAD_PICTURES]]


def build_xlsx(data) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    head, fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1E3A5F")

    def sheet(ws, header, rows):
        ws.append(header)
        for c in ws[1]:
            c.font, c.fill = head, fill
        for r in rows:
            ws.append(r)
        ws.freeze_panes = "B2"
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = max(10, min(48, max(len(str(c.value or "")) for c in col) + 2))

    ws = wb.active
    ws.title = "สรุปต่อ Admin"
    sheet(ws, ["Admin", "จำนวนอัลบั้ม"] + [h for _k, h in COLUMNS],
          [[a["admin"], a["albums"]] + [a[k] for k, _h in COLUMNS] for a in data["admins"]]
          + [["รวม", sum(a["albums"] for a in data["admins"])]
             + [sum(a[k] for a in data["admins"]) for k, _h in COLUMNS]])
    sheet(wb.create_sheet("รายอัลบั้ม"), ["Admin (อ่านจากชื่ออัลบั้ม)", "อัลบั้ม"] + [h for _k, h in COLUMNS]
          + ["ยอดที่ Ops จดในชื่ออัลบั้ม"],
          [[x["admin"], x["album"]] + [x[k] for k, _h in COLUMNS] + [x["ops"]] for x in data["albums"]])
    sheet(wb.create_sheet("รายการที่ใช้ไม่ได้"),
          ["Admin", "อัลบั้ม", "เหตุผล", "รูป", "ไฟล์", "รหัสการจอง", "ยอด", "หมายเหตุ", "ลิงก์รูป"],
          [[admin_of(i["album"]), i["album"], i["why"], i["pictures"], i["file"], i["code"], i["amount"],
            i["note"], i["link"]] for i in data["items"]])
    ws = wb.create_sheet("อ่านก่อน")
    for line in (f"รายงานบัญชี {data['week']} ({data['d_from']} ถึง {data['d_to']})",
                 "นับทุกอัลบั้มที่วางในโฟลเดอร์ของสัปดาห์นี้ อัลบั้มนับในสัปดาห์ที่วางครั้งแรก",
                 "งานที่ใช้ได้ = ลงไฟล์สัปดาห์นี้ + ไปลงสัปดาห์ถัดไป (สัปดาห์นี้เต็มแล้ว) + ยังรอตรวจหรือรออ่าน",
                 "รูปที่ส่งมา = รูปเต็ม (แคปยาว 1 รูปต่อ 1 งาน) + รูปครึ่ง (บนและล่าง 2 รูปต่อ 1 งาน)"
                 " รวมรูปซ้ำเป๊ะและรูปครึ่งที่หาคู่ไม่ได้",
                 "ชื่อ Admin อ่านจากชื่ออัลบั้ม ถ้าไม่ตรง ให้ดูชีตรายอัลบั้ม"):
        ws.append([line])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def file_name(data):
    return f"บัญชี {data['week']}.xlsx"
