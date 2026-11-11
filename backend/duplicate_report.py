# -*- coding: utf-8 -*-
"""รายงานรูปซ้ำรายสัปดาห์ — ให้ลูกค้าตีกลับไรเดอร์ได้ (2026-09-12, ระยะ 1)

อ่านอย่างเดียว ไม่แก้ไม่ลบอะไรทั้งสิ้น

ระบบพักรูปซ้ำไว้เป็น status='duplicate' พร้อมโน้ตว่าไปซ้ำกับไฟล์ไหน แต่โน้ตเป็นข้อความ ค้นไม่ได้
และไม่มีที่บันทึกว่าตีกลับไปหรือยัง ตัวนี้ประกอบเคสให้ครบ: ใบไหน ของไรเดอร์คนไหน ซ้ำกับงานไหน
ของใคร สัปดาห์ไหน แล้วเขียนเป็น Excel ให้ส่งต่อได้

กติกาที่ Ops ตอบไว้ 2026-09-12: ตีกลับ 'ไรเดอร์เจ้าของอัลบั้มที่ส่งมา' และเอา 'คนที่ส่งทีหลัง'
ระบบอนุมัติใบแรกที่เข้ามาเสมอ ใบที่ถูกพักจึงเป็นของคนที่ส่งทีหลังอยู่แล้วโดยโครงสร้าง

ระยะถัดไป (ยังไม่ได้ทำ): ตาราง dup_cases เก็บสถานะการตีกลับและคำตอบผู้ส่ง + ปุ่มในหน้า Admin
แล้วรายงานนี้จะอ่านสถานะจากตารางนั้นแทนคอลัมน์ว่าง

    python duplicate_report.py --from 2026-09-07 --to 2026-09-13
    python duplicate_report.py --from 2026-09-07 --to 2026-09-13 --xlsx dup_w37.xlsx
"""
import argparse
import collections
import re
import sys

from sqlalchemy import select

import db

# 'LINE_ALBUM_2W-Win ป๋อง = 71_86659+86658_฿30.jpg' -> ชื่ออัลบั้มที่ไรเดอร์ส่งมา
ALBUM = re.compile(r"^(?:LINE_ALBUM_)?(.+?)_\d+\+\d+_฿")
KIND_BOTTOM = "ครึ่งล่างของงานที่นับไปแล้ว"
KIND_SAME_WEEK = "รหัสการจองซ้ำในสัปดาห์เดียวกัน"
KIND_OTHER_WEEK = "รหัสการจองซ้ำข้ามสัปดาห์"
KIND_SAME_FILE = "ไฟล์เดิมส่งซ้ำ"
KIND_SUSPECT = "ข้อมูลตรงกัน แต่เลขจองไม่ตรงทุกตัว"
KINDS = (KIND_SAME_FILE, KIND_SAME_WEEK, KIND_OTHER_WEEK, KIND_BOTTOM, KIND_SUSPECT)


def album_of(file_name, folder_name=None, driver_name=None, source_album=None):
    """ไรเดอร์เจ้าของอัลบั้มที่ส่งรูปใบนี้มา

    สามชั้น ตามความน่าเชื่อจากมากไปน้อย:
      1. source_album ที่ pool จดไว้ตอนวางไฟล์ — รู้แน่ ไม่ต้องเดา (ตั้งแต่ 2026-09-13)
      2. ชื่ออัลบั้มที่ติดมาในชื่อไฟล์ของคู่ที่ต่อแล้ว — ใช้กับแถวเก่าก่อนหน้านั้น
      3. โฟลเดอร์ต้นทาง — ถูกต้องเมื่อ Ops อัปเข้าโฟลเดอร์ไรเดอร์เอง

    ต่างจากโฟลเดอร์ที่ระบบเอารูปไปวาง เพราะระบบกระจายงานให้ไรเดอร์คนไหนก็ได้ที่ยังมีที่ว่าง
    (รอบ W37 อัลบั้มของ ป๋อง ไปโผล่ในโฟลเดอร์ของสรธรและธีรพงศ์)"""
    if (source_album or "").strip():
        return source_album.strip()
    m = ALBUM.match(file_name or "")
    if m:
        return m.group(1).strip()
    return (folder_name or driver_name or "").strip() or "ไม่รู้อัลบั้ม"


def kind_of(row, twin):
    if (row.get("note") or "").startswith("ครึ่งล่างของงานที่อนุมัติแล้ว"):
        return KIND_BOTTOM
    if db.SUSPECT in (row.get("note") or ""):
        return KIND_SUSPECT
    if twin and row.get("image_hash") and row["image_hash"] == twin.get("image_hash"):
        return KIND_SAME_FILE
    if twin and twin.get("date_from") and row.get("date_from") != twin["date_from"]:
        return KIND_OTHER_WEEK
    return KIND_SAME_WEEK


COLS = ["id", "ไฟล์ที่ซ้ำ", "ไรเดอร์ผู้ส่ง", "โฟลเดอร์ที่ระบบวาง", "กลุ่ม", "สัปดาห์",
        "รหัสการจอง", "ยอด", "ยอดของต้นฉบับ", "วันที่งาน", "ซ้ำกับไฟล์", "ของไรเดอร์",
        "สัปดาห์ของต้นฉบับ", "รูปที่ส่งลูกค้า", "ประเภทการซ้ำ", "ลิงก์รูป", "สถานะเคส",
        "ผู้ตีกลับ", "วันที่ตีกลับ", "คำตอบผู้ส่ง"]


def build(rows, twins):
    """(เคสที่พร้อมตีกลับ, เคสที่ต้องให้คนตัดสิน) — twins: id -> แถวต้นฉบับที่อนุมัติแล้ว"""
    cases, undecided = [], []
    for r in rows:
        twin = twins.get(r.get("duplicate_of")) or twins.get(r.get("twin_id"))
        if r.get("cross_week") or (twin and twin.get("date_from") and r.get("date_from")
                                   and twin["date_from"] != r["date_from"]):
            # ลูกค้า 2026-09-14: สลิปที่นับไปแล้วในสัปดาห์ก่อน กลับมาเป็นงานได้ในสัปดาห์หลัง
            # ไม่ใช่ของซ้ำ ไม่มีอะไรให้ตีกลับ — รวมถึงไฟล์เดิมเป๊ะที่ต้นฉบับอยู่สัปดาห์อื่น
            continue
        t = twin or {}
        case = {
            "id": r["id"],
            "ไฟล์ที่ซ้ำ": r["file_name"],
            "ไรเดอร์ผู้ส่ง": album_of(r["file_name"], r.get("folder_name"), r.get("driver_name"),
                                      r.get("source_album")),
            # ชี้ตัวคนส่งได้แน่ หรือได้แค่ชื่อโฟลเดอร์ปลายทาง — ต้องบอกให้ชัด ไม่งั้นการเทียบ
            # "ส่งใต้ชื่อคนอื่น" จะเอาอัลบั้มฝั่งหนึ่งไปชนกับโฟลเดอร์อีกฝั่งแล้วนับผิด
            "ผู้ส่งแน่ชัด": bool((r.get("source_album") or "").strip() or ALBUM.match(r["file_name"] or "")),
            "โฟลเดอร์ที่ระบบวาง": r.get("driver_name"),
            "กลุ่ม": r.get("category"),
            "สัปดาห์": r.get("date_from"),
            "รหัสการจอง": r.get("booking_code"),
            "ยอด": r.get("net_earnings"),
            "ยอดของต้นฉบับ": t.get("net_earnings"),
            "วันที่งาน": r.get("trip_date"),
            "ซ้ำกับไฟล์": t.get("file_name"),
            "ของไรเดอร์": album_of(t.get("file_name"), None, t.get("driver_name"),
                                   t.get("source_album")) if twin else None,
            "ต้นฉบับแน่ชัด": bool(twin and ((t.get("source_album") or "").strip()
                                            or ALBUM.match(t.get("file_name") or ""))),
            "สัปดาห์ของต้นฉบับ": t.get("date_from"),
            "twin_id": t.get("id"),          # the web shows the two pictures side by side; not a sheet column
            "twin_url": t.get("source_url"),  # and falls back to Drive in the viewer's own browser
            "committed": r.get("committed"),
            # the same trip by the guard's own rule as a counted row: cannot be put back (db.restore_refusal)
            "restorable": not (twin and t.get("committed") == 1 and db.trip_key(r)
                               and db.trip_key(r) == db.trip_key(t)),
            "รูปที่ส่งลูกค้า": t.get("customer_image"),
            "ประเภทการซ้ำ": kind_of(r, twin),
            "ลิงก์รูป": r.get("source_url"),
            "สถานะเคส": "รอตีกลับ",
            "ผู้ตีกลับ": "", "วันที่ตีกลับ": "", "คำตอบผู้ส่ง": "",
        }
        (cases if r["status"] == "duplicate" else undecided).append(case)
    return cases, undecided


def sent_by_someone_else(case) -> bool:
    """สลิปใบนี้ถูกส่งใต้ชื่อไรเดอร์คนละคนกับต้นฉบับ — ตอบเฉพาะเมื่อรู้ตัวคนส่งทั้งสองฝั่ง

    2026-09-13 เคยตอบ 391 จาก 475 เพราะเทียบ 'อัลบั้ม' ฝั่งหนึ่งกับ 'โฟลเดอร์ปลายทาง' อีกฝั่ง
    ซึ่งเป็นคนละสิ่งกัน ตัวเลขนั้นเกือบทั้งหมดไม่จริง และเป็นตัวเลขที่จะถูกส่งให้ลูกค้าไปตีกลับคน"""
    return bool(case.get("ผู้ส่งแน่ชัด") and case.get("ต้นฉบับแน่ชัด")
                and case.get("ของไรเดอร์") and case["ของไรเดอร์"] != case["ไรเดอร์ผู้ส่ง"])


KIND_PRE = "ซ้ำก่อนอ่าน"
PRE_COLS = ["ไรเดอร์ผู้ส่ง", "ไฟล์ที่ซ้ำ", "ซ้ำกับไฟล์", "ของอัลบั้ม", "ประเภทการซ้ำ", "สัปดาห์",
            "เจอเมื่อ", "ลิงก์รูป"]


def pre_read_cases(d_from):
    """รูปที่ระบบตัดทิ้งก่อนส่งให้ AI อ่าน เพราะเป็นไฟล์เดียวกันเป๊ะกับใบที่มีอยู่แล้ว

    ไม่มีรหัสการจองหรือยอด (ยังไม่ได้อ่าน) บอกได้แค่ว่าไฟล์เหมือนกันทุก byte — แต่ Ops นับเข้า
    'ใบซ้ำ' ของคนส่งด้วย (เฟียส 2026-09-22) เพราะใช้ทักคนส่งเหมือนกัน"""
    out = []
    for r in db.skipped_copies_for_week(d_from):
        out.append({
            "ไรเดอร์ผู้ส่ง": r.get("album") or "ไม่รู้อัลบั้ม",
            "ไฟล์ที่ซ้ำ": r.get("file_name"),
            "ซ้ำกับไฟล์": r.get("same_as"),
            "ของอัลบั้ม": r.get("same_as_album"),
            "ประเภทการซ้ำ": r.get("kind"),
            "สัปดาห์": r.get("week_from"),
            "เจอเมื่อ": r.get("found_at"),
            "ลิงก์รูป": (f"https://drive.google.com/file/d/{r['drive_id']}/view"
                         if r.get("drive_id") else None),
        })
    return out


def pre_read_by_album(pre):
    """หนึ่งแถวต่ออัลบั้ม — ประโยคที่ใช้ทักคนส่ง เช่น 'สำเนาในอัลบั้มเดียวกัน 48 ใบ'"""
    by = collections.defaultdict(collections.Counter)
    for c in pre:
        by[c["ไรเดอร์ผู้ส่ง"]][c["ประเภทการซ้ำ"]] += 1
    rows = []
    for album, kinds in sorted(by.items(), key=lambda kv: -sum(kv[1].values())):
        rows.append([album, sum(kinds.values()),
                     " · ".join(f"{k} {n} ใบ" for k, n in kinds.most_common())])
    return rows


def backfill_pre_read(d_from, d_to, log=print):
    """ครั้งเดียวต่อสัปดาห์: เก็บรูปซ้ำเป๊ะที่กองเคยตัดไว้ในรอบก่อน ๆ (จากผลของแต่ละรอบใน pool_runs)
    เข้าตาราง skipped_copies — ตารางเพิ่งมีเมื่อ 2026-09-22 แต่ผลของทุกรอบเก็บไว้ครบ

    รอบก่อนหน้านั้นไม่ได้จดรหัสไฟล์ไว้ ลิงก์รูปของแถวเหล่านี้จึงว่าง และสำเนาที่เคยถูกทิ้งไว้ในกอง
    โผล่ซ้ำทุกรอบ — แถวของไฟล์เดียวกันนับครั้งเดียว"""
    key = f"pre_read_backfill:{d_from}"
    if db.state_get(key):
        return 0
    # after the check: pool pulls in the pairing stack (numpy, OCR), which the report workflow
    # does not install — a week already filled never needs it (W39 report run, 2026-09-29)
    import json
    import pool
    rows = []
    with db.engine.begin() as c:
        for (rep,) in c.execute(select(db.pool_runs.c.report)
                                .where(db.pool_runs.c.mode == "move",
                                       db.pool_runs.c.started_at >= d_from)).all():
            try:
                rows += [r for r in pool.duplicate_rows(json.loads(rep or "{}"))
                         if r["week_from"] == d_from]
            except Exception:  # noqa: BLE001 — one unreadable run must not stop the rest
                continue
    n = db.record_skipped_copies(rows)
    db.state_set(key, "1")
    if n:
        log(f"📋 รายงานรูปซ้ำ: เติมรูปซ้ำก่อนอ่านจากรอบก่อน ๆ ของสัปดาห์ {d_from} {n} ใบ")
    return n


ALBUM_COLS = ["ลำดับ", "อัลบั้ม", "เข้าระบบครั้งแรก", "เที่ยวที่อ่าน", "ลงงาน", "ซ้ำก่อนอ่าน",
              "ซ้ำหลังอ่าน", "ซ้ำรวม", "% ซ้ำ", "ซ้ำกับอัลบั้ม", "ครึ่งรูปค้างในกอง", "รออ่าน", "สถานะ",
              # the album's own count, top to bottom (Fiat 2026-11-11) — see album_overview
              "รูปทั้งหมด", "ต้นฉบับ", "จับคู่ครบได้", "จับคู่ได้แล้ว", "ลบในคิวตรวจ", "งานจริง", "ค้างในระบบ",
              "ยอดที่ Ops จด", "ต่างจากยอด Ops"]
STATUS = ALBUM_COLS.index("สถานะ")
OPS_COUNT = re.compile(r"(\d[\d,]*)\s*งาน")


def album_overview(d_from, d_to, cases, pre=()):
    """One row for EVERY album of the week, in the order it came in — repeats or not (Fiat
    2026-09-29: "ทุก album ที่อัพ ... เรียงตามวันที่ที่ถูกอัพโหลด จะได้รู้ว่า Album ไหนซ้ำ ไม่ซ้ำ").

    'เข้าระบบครั้งแรก' is when a round first took one of its pictures in (ingested_files), the
    nearest thing to an upload time the database holds; an album of copies only takes the time
    its first copy was dropped. Half pictures still waiting in the pool come from the latest pool
    run of the week. 'รออ่าน' is what was sent to be read and has not come back (a batch returns
    in the next round): its repeats can still add to 'ซ้ำหลังอ่าน' (Fiat 2026-09-29).

    The last columns count the album top to bottom (Fiat 2026-11-11): every picture it holds =
    exact copies + the halves of every trip made from it (two for a stitched pair, one for a long
    screenshot) + the halves still unpaired; the most trips it can give = trips so far + half the
    unpaired; real trips = trips less the repeats parked after reading and the rows a person
    deleted in the review queue (found in action_log, since the row itself is gone). Nothing here
    is stored: when a later pool run pairs a leftover, the next report says so."""
    import json
    t, j, f = db.trips.c, db.jobs.c, db.ingested_files.c
    src = db.trips.join(db.jobs, j.id == t.job_id).outerjoin(db.ingested_files, f.trip_id == t.id)
    with db.engine.begin() as c:
        trips = [dict(r) for r in c.execute(
            select(t.id, t.file_name, t.status, t.committed, t.source_album, j.driver_name,
                   j.folder_name, f.ingested_at)
            .select_from(src)
            .where(j.date_from >= d_from, j.date_from <= d_to, t.status != "merged")).mappings().all()]
        last = c.execute(select(db.pool_runs.c.report).where(db.pool_runs.c.mode == "move",
                                                            db.pool_runs.c.started_at >= d_from)
                         .order_by(db.pool_runs.c.id.desc()).limit(1)).scalar()
        week_jobs = set(c.execute(select(j.id).where(j.date_from >= d_from, j.date_from <= d_to)).scalars())
        deleted = c.execute(select(db.action_log.c.detail).where(db.action_log.c.action == "trip.delete",
                                                                 db.action_log.c.at >= d_from)).scalars().all()
    row = collections.defaultdict(lambda: {"first": None, "read": set(), "filed": set(), "waiting": set(),
                                           "pre": 0, "post": 0, "with": set(), "left": 0,
                                           "halves": 0, "deleted": 0})

    def seen(a, when):
        if when and (row[a]["first"] is None or when < row[a]["first"]):
            row[a]["first"] = when
    for r in trips:
        a = album_of(r["file_name"], r.get("folder_name"), r.get("driver_name"), r.get("source_album"))
        row[a]["waiting" if r.get("status") == "pending" else "read"].add(r["id"])
        if r.get("committed") == 1:
            row[a]["filed"].add(r["id"])
        row[a]["halves"] += 2 if ALBUM.match(r["file_name"] or "") else 1
        seen(a, r.get("ingested_at"))
    for d in deleted:
        try:
            gone = (json.loads(d or "{}").get("row") or {})
        except ValueError:
            continue
        if gone.get("job_id") in week_jobs and gone.get("file_name"):
            a = album_of(gone["file_name"])
            row[a]["deleted"] += 1
            row[a]["halves"] += 2 if ALBUM.match(gone["file_name"]) else 1
    for c_ in pre:
        a = c_["ไรเดอร์ผู้ส่ง"]
        row[a]["pre"] += 1
        seen(a, c_.get("เจอเมื่อ"))
        # a re-send of a picture read before names no album — say what it is instead of nothing
        row[a]["with"].add(c_.get("ของอัลบั้ม") or "(รูปที่เคยส่งและอ่านไปแล้ว)")
    for c_ in cases:
        a = c_["ไรเดอร์ผู้ส่ง"]
        row[a]["post"] += 1
        row[a]["with"].add(c_.get("ของไรเดอร์") or "")
    try:
        import ingest
        for e in (json.loads(last or "{}").get("albums") or []):
            rng = ingest.parse_range(e.get("week") or "")
            if rng and rng[0].isoformat() == d_from and e.get("leftovers"):
                row[e["album"]]["left"] += len(e["leftovers"])
    except Exception:  # noqa: BLE001 — a report that cannot be read leaves the column empty
        pass
    out = []
    for a, v in row.items():
        dup = v["pre"] + v["post"]
        others = sorted(x for x in v["with"] if x and x != a)
        same = any(x == a for x in v["with"])
        with_ = " · ".join((["ในอัลบั้มเดียวกัน"] if same else []) + others)
        base = len(v["read"]) + len(v["waiting"]) + v["pre"]
        trips_n = len(v["read"]) + len(v["waiting"]) + v["deleted"]
        real = trips_n - v["post"] - v["deleted"]
        m = OPS_COUNT.search(a or "")
        ops = int(m.group(1).replace(",", "")) if m else None
        most = trips_n + v["left"] // 2
        out.append([None, a, v["first"], len(v["read"]), len(v["filed"]), v["pre"], v["post"],
                    dup, round(dup / base, 3) if base else None, with_,
                    v["left"] or None, len(v["waiting"]) or None, "ซ้ำ" if dup else "ไม่ซ้ำ",
                    v["halves"] + v["pre"] + v["left"], v["halves"] + v["left"], most, trips_n,
                    v["deleted"] or None, real, real - len(v["filed"]) or None,
                    ops, ops - (most - v["post"] - v["deleted"]) if ops is not None else None])
    out.sort(key=lambda r: (r[2] is None, r[2] or "", r[1]))
    for i, r in enumerate(out, 1):
        r[0] = i
    return out


def counted_twice(d_from, d_to):
    """(approved rows of the week, [[ids] counted twice], [[ids] that may be one trip]).

    The customer's file is the approved rows, so an empty second list is the proof that no trip
    in it is paid twice. Counted twice = the same db.trip_key, or same_trip's CODE evidence (a
    code misread by a letter or two at the line break, W46). The third list is same_trip's ROUTE
    evidence: same route, distance and fare, which a person has to look at."""
    import same_trip
    t, j = db.trips.c, db.jobs.c
    with db.engine.begin() as c:
        rows = [dict(r) for r in c.execute(
            select(t.id, t.booking_code, t.base_fare, t.trip_time, t.distance_km, t.pickup_text, t.dropoff_text)
            .select_from(db.trips.join(db.jobs, j.id == t.job_id))
            .where(j.date_from >= d_from, j.date_from <= d_to, t.committed == 1)).mappings().all()]
    by = collections.defaultdict(list)
    for r in rows:
        k = db.trip_key(r)
        if k:
            by[k].append(r["id"])
    twice = [sorted(ids) for ids in by.values() if len(ids) > 1]
    exact = {i for g in twice for i in g}
    suspect = []
    for k, g in same_trip.groups(rows):
        ids = [r["id"] for r in g]
        if set(ids) <= exact:
            continue
        (twice if k == same_trip.CODE else suspect).append(ids)
    return len(rows), twice, suspect


def half_ids(d_from):
    """{(album, file): Drive id} of the file each exact copy of the week copies, so the copy can be
    shown beside it (skipped_copies names that file by path only). The pool run's stored report
    keeps it as same_as_id; it drops the ids of paired pictures to save database transfer."""
    import json

    import ingest
    out = {}
    with db.engine.begin() as c:
        reports = c.execute(select(db.pool_runs.c.report).where(db.pool_runs.c.mode == "move",
                                                               db.pool_runs.c.started_at >= d_from)).scalars().all()
    for rep in reports:
        try:
            dups = json.loads(rep or "{}").get("duplicates") or []
        except ValueError:
            continue
        for e in dups:
            rng = ingest.parse_range(e.get("week") or "")
            if rng and rng[0].isoformat() == d_from and e.get("same_as_id"):
                album, _, name = (e.get("same_as") or "").rpartition("/")
                out[(album, name)] = e["same_as_id"]
    return out


def summary(cases, pre=()):
    """สรุปรายไรเดอร์ผู้ส่ง — แถวที่ลูกค้าใช้คุยกับคนส่ง"""
    by = collections.defaultdict(collections.Counter)
    for c in pre:
        s = by[c["ไรเดอร์ผู้ส่ง"]]
        s["ใบซ้ำ"] += 1
        s[KIND_PRE] += 1
    for c in cases:
        s = by[c["ไรเดอร์ผู้ส่ง"]]
        s["ใบซ้ำ"] += 1
        s["ยอดรวม"] += c["ยอด"] or 0
        s[c["ประเภทการซ้ำ"]] += 1
        if sent_by_someone_else(c):
            s["ซ้ำใต้ชื่อคนอื่น"] += 1
    return by


def load(d_from, d_to):
    """แถวซ้ำของสัปดาห์ + ต้นฉบับของมัน (ต้นฉบับอยู่สัปดาห์ไหนก็ได้)"""
    t, j = db.trips.c, db.jobs.c
    cols = [t.id, t.file_name, t.status, t.committed, t.booking_code, t.duplicate_of,
            t.net_earnings, t.base_fare, t.trip_time, t.trip_date, t.note, t.customer_image, t.source_url, t.image_hash,
            t.source_album, j.driver_name, j.category, j.folder_name, j.date_from]
    src = db.trips.join(db.jobs, j.id == t.job_id)
    with db.engine.begin() as c:
        week = [dict(r) for r in c.execute(
            select(*cols).select_from(src)
            .where(j.date_from >= d_from, j.date_from <= d_to,
                   (t.status == "duplicate") | (t.duplicate_of.isnot(None)))).mappings().all()]
        ids = [r["duplicate_of"] for r in week if r["duplicate_of"]]
        codes = [r["booking_code"] for r in week if r["booking_code"]]
        twins = [dict(r) for r in c.execute(
            select(*cols).select_from(src).where(t.id.in_(ids))).mappings().all()] if ids else []
        by_code = [dict(r) for r in c.execute(
            select(*cols).select_from(src)
            .where(t.committed == 1, t.booking_code.in_(codes))).mappings().all()] if codes else []
    twin_by_id = {r["id"]: r for r in twins}
    code_twin = {}
    for r in sorted(by_code, key=lambda r: r["id"]):     # ใบแรกที่อนุมัติคือต้นฉบับ
        code_twin.setdefault((db.trip_key(r), r["date_from"]), r)
    other_week = {db.trip_key(r) for r in by_code}
    for r in week:                                      # เติมต้นฉบับให้แถวที่ไม่มี duplicate_of
        if not r["duplicate_of"] and r["booking_code"]:
            # ต้นฉบับต้องอยู่สัปดาห์เดียวกัน (ลูกค้า 2026-09-14) ถ้ามีแต่ของสัปดาห์อื่น แถวนี้เป็นงาน
            tw = code_twin.get((db.trip_key(r), r["date_from"]))
            if tw and tw["id"] != r["id"]:
                r["twin_id"] = tw["id"]
                twin_by_id[tw["id"]] = tw
            elif db.trip_key(r) in other_week:
                r["cross_week"] = True
    return week, twin_by_id


# แยกจากไฟล์หลักที่ส่งลูกค้า (Rider Trips*.xlsx และโฟลเดอร์รูปของแต่ละสัปดาห์) — Ops 2026-09-13
# ขีดล่างนำหน้าให้เรียงแยกจากโฟลเดอร์สัปดาห์ และบอกด้วยตาว่านี่ไม่ใช่ของส่งมอบประจำสัปดาห์
DRIVE_DIR = "_รายงานรูปซ้ำ"
FINGERPRINT_KEY = "dup_report"


def report_name(d_from) -> str:
    """'2026-09-07' → 'รูปซ้ำ_2026-W37.xlsx' — หนึ่งไฟล์ต่อสัปดาห์ รันซ้ำแล้วทับของเดิม"""
    from datetime import date
    y, w, _ = date.fromisoformat(d_from).isocalendar()
    return f"รูปซ้ำ_{y}-W{w:02d}.xlsx"


def upload_to_drive(drive, exports_id, d_from, data: bytes):
    """วางรายงานลง Drive ใต้ Exports/_รายงานรูปซ้ำ/ → (folder_id, file_id)

    ทับไฟล์ชื่อเดิมของสัปดาห์เดียวกัน: รายงานเปลี่ยนทุกรอบที่มีใบซ้ำเพิ่ม และสิ่งที่คนเปิดดูควรเป็น
    ฉบับล่าสุดเสมอ ไม่ใช่ไล่เลือกจากสิบฉบับที่ชื่อเหมือนกัน"""
    folder = drive.ensure_folder(exports_id, DRIVE_DIR)
    return folder, drive.upload_xlsx(folder, report_name(d_from), data)


def refresh_week(drive, exports_id, d_from, d_to, log=print):
    """ท้ายรอบ ingest: ประกอบรายงานของสัปดาห์นั้นใหม่แล้ววางทับใน Drive → dict หรือ None

    ใบซ้ำถูกพักตอนอนุมัติในรอบ ถ้ารายงานยังเป็นปุ่มแยก คนที่เปิดดูใน Drive จะเห็นฉบับที่ช้ากว่า
    ความจริงไปจนกว่าจะมีคนนึกได้ว่าต้องกด — เหมือนที่นั่ง 475 ที่เคยค้างรอคนกดคืน
    สัปดาห์ที่ไม่มีใบซ้ำเลยไม่สร้างไฟล์เปล่า ๆ ขึ้นมา"""
    rows, twins = load(d_from, d_to)
    cases, undecided = build(rows, twins)
    backfill_pre_read(d_from, d_to, log=log)
    pre = pre_read_cases(d_from)
    if not cases and not undecided and not pre:
        return None
    albums = album_overview(d_from, d_to, cases, pre)
    sure = sum(1 for c in cases if c.get("ผู้ส่งแน่ชัด") and c.get("ต้นฉบับแน่ชัด"))
    # The same report twice is one upload too many: a week's repeats settle once it is read,
    # and every round after that wrote an identical file back to Drive (and paid Drive and Neon
    # transfer for it). The fingerprint is of what the file says, so any change still goes out.
    import hashlib
    import json
    sig = hashlib.sha1(json.dumps([cases, undecided, pre, albums], ensure_ascii=False, sort_keys=True,
                                  default=str).encode("utf-8")).hexdigest()
    key = f"{FINGERPRINT_KEY}:{d_from}"
    if db.state_get(key) == sig:
        log(f"📋 รายงานรูปซ้ำ {report_name(d_from)}: ไม่มีอะไรเปลี่ยนตั้งแต่รอบก่อน (ใบซ้ำ {len(cases)}"
            f" · ซ้ำก่อนอ่าน {len(pre)}) — ไม่ต้องเขียนใหม่")
        return {"cases": len(cases), "undecided": len(undecided), "pre": len(pre), "sure": sure,
                "file_id": None, "unchanged": True}
    found, links = with_pictures(drive, exports_id, d_from, cases, undecided, pre, albums, log)
    folder, fid = upload_to_drive(drive, exports_id, d_from,
                                  build_xlsx(cases, undecided, pre, albums, admin_rows(found, links)))
    db.state_set(key, sig)
    log(f"📋 รายงานรูปซ้ำ {report_name(d_from)}: ใบซ้ำ {len(cases)} · ซ้ำก่อนอ่าน {len(pre)}"
        f" · รอคนตัดสิน {len(undecided)} · ระบุตัวคนส่งได้ {sure}"
        f" → https://drive.google.com/file/d/{fid}/view")
    return {"cases": len(cases), "undecided": len(undecided), "pre": len(pre), "sure": sure,
            "file_id": fid}


def with_pictures(drive, exports_id, d_from, cases, undecided, pre, albums, log=print):
    """([dup_examples.Entry], {picture name: Drive id}): one comparison picture per repeat, made
    before the workbook so its first sheet can link each row to its picture. Never raises."""
    try:
        import dup_examples
        from ingest import week_label
        found = dup_examples.entries(cases, undecided, pre, half_ids(d_from))
        folder = drive.ensure_folder(exports_id, DRIVE_DIR)
        return found, dup_examples.write(drive, folder, week_label(d_from), found, albums, log=log)
    except Exception as e:  # noqa: BLE001 — the report goes out without pictures rather than not at all
        log(f"⚠ รูปเปรียบเทียบงานซ้ำทำไม่สำเร็จ: {str(e)[:150]}")
        return [], {}


ADMIN_COLS = ["ลำดับ", "ประเภท", "รูปที่ซ้ำ", "อัลบั้มของรูปที่ซ้ำ", "ส่งโดย", "ซ้ำกับรูป", "อัลบั้มของต้นฉบับ",
              "ต้นฉบับส่งโดย", "ต้นฉบับในไฟล์ลูกค้า", "เลขจอง", "ยอด", "สถานะ", "รูปเปรียบเทียบ"]


def admin_rows(found, links):
    """The sheet to forward to the admins: one row per repeat, the comparison picture linked."""
    from dup_examples import sender
    rows = []
    for i, e in enumerate(sorted(found, key=lambda e: (e.album, e.kind, e.file)), 1):
        fid = links.get(e.name)
        rows.append([i, e.kind, e.file, e.album, sender(e.album), e.orig_file, e.orig_album,
                     sender(e.orig_album), e.counted_as or None, e.code or None, e.amount, e.status,
                     f"https://drive.google.com/file/d/{fid}/view" if fid else None])
    return rows


def build_xlsx(cases, undecided, pre=(), albums=None, admin=None) -> bytes:
    import io
    buf = io.BytesIO()
    write_xlsx(buf, cases, undecided, pre, albums, admin)
    return buf.getvalue()


def write_xlsx(path, cases, undecided, pre=(), albums=None, admin=None):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    head, fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1E3A5F")

    def sheet(ws, headers, rows_):
        ws.append(headers)
        for cell in ws[1]:
            cell.font, cell.fill = head, fill
            cell.alignment = Alignment(vertical="center")
        for r in rows_:
            ws.append(r)
        for i, h in enumerate(headers, 1):
            ws.column_dimensions[ws.cell(1, i).column_letter].width = max(12, min(46, len(str(h)) + 8))
        ws.freeze_panes = "A2"
        return ws

    sheet(wb.active, ["ไรเดอร์ผู้ส่ง", "ใบซ้ำ", "ยอดรวม", KIND_SAME_FILE, KIND_SAME_WEEK,
                      KIND_OTHER_WEEK, KIND_BOTTOM, KIND_PRE, "ซ้ำใต้ชื่อคนอื่น"],
          [[k, v["ใบซ้ำ"], round(v["ยอดรวม"], 2), v[KIND_SAME_FILE], v[KIND_SAME_WEEK],
            v[KIND_OTHER_WEEK], v[KIND_BOTTOM], v[KIND_PRE], v["ซ้ำใต้ชื่อคนอื่น"]]
           for k, v in sorted(summary(cases, pre).items(), key=lambda kv: -kv[1]["ใบซ้ำ"])])
    wb.active.title = "สรุปรายผู้ส่ง"
    if albums is not None:
        # every album of the week first, oldest upload on top — the sheet Ops follows
        ws = wb.create_sheet("รายอัลบั้ม", 0)
        sheet(ws, ALBUM_COLS, albums)
        dup_fill = PatternFill("solid", fgColor="FDE8E8")
        for i, r in enumerate(albums, 2):
            if r[STATUS] == "ซ้ำ":
                for cell in ws[i]:
                    cell.fill = dup_fill
            ws.cell(i, ALBUM_COLS.index("% ซ้ำ") + 1).number_format = "0.0%"
        ws.column_dimensions["B"].width = 34
        ws.column_dimensions["C"].width = 20
        ws.column_dimensions["J"].width = 40
        wb.active = 0
    if admin:
        # the sheet the customer forwards to the admins comes first, each row linked to its picture
        ws = wb.create_sheet("ส่งแอดมิน", 0)
        sheet(ws, ADMIN_COLS, admin)
        link_col = len(ADMIN_COLS)
        for i in range(2, len(admin) + 2):
            cell = ws.cell(i, link_col)
            if cell.value:
                cell.hyperlink, cell.value = cell.value, "เปิดรูป"
                cell.font = Font(color="1E5AA8", underline="single")
        for col, w in (("C", 26), ("D", 26), ("F", 26), ("G", 26), ("I", 20)):
            ws.column_dimensions[col].width = w
        wb.active = 0
    sheet(wb.create_sheet("รายใบ"), COLS, [[c.get(k) for k in COLS] for c in cases])
    sheet(wb.create_sheet("ค้างตัดสิน"), COLS, [[c.get(k) for k in COLS] for c in undecided])
    # ซ้ำก่อนอ่าน: ไม่มีรหัสการจอง ไม่มียอด — ตัดทิ้งก่อนเสียค่าอ่าน บอกได้แค่ว่าไฟล์เหมือนกันเป๊ะ
    sheet(wb.create_sheet("ซ้ำก่อนอ่าน-รายอัลบั้ม"), ["ไรเดอร์ผู้ส่ง", "ใบ", "เจออะไร"],
          pre_read_by_album(pre))
    sheet(wb.create_sheet("ซ้ำก่อนอ่าน-รายใบ"), PRE_COLS, [[c.get(k) for k in PRE_COLS] for c in pre])
    wb.save(path)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--xlsx", help="เขียนไฟล์ Excel ไว้ที่นี่")
    ap.add_argument("--to-drive", action="store_true",
                    help=f"วางไฟล์ลง Drive ที่ Exports/{DRIVE_DIR}/ (แยกจากไฟล์หลักที่ส่งลูกค้า)")
    a = ap.parse_args(argv)

    db.init_db()
    rows, twins = load(a.d_from, a.d_to)
    cases, undecided = build(rows, twins)
    backfill_pre_read(a.d_from, a.d_to)
    pre = pre_read_cases(a.d_from)
    print(f"สัปดาห์ {a.d_from} ถึง {a.d_to}")
    print(f"ใบซ้ำที่ระบบพักไว้ {len(cases):,} · ซ้ำก่อนอ่าน {len(pre):,} · ยังต้องให้คนตัดสิน {len(undecided):,}")
    for album, n, what in pre_read_by_album(pre):
        print(f"    ซ้ำก่อนอ่าน {album[:30]:<32}{n:>5}  {what}")
    if not cases and not undecided and not pre:
        print("ไม่พบรูปซ้ำในสัปดาห์นี้")
        return 0
    albums = album_overview(a.d_from, a.d_to, cases, pre)
    print(f"\nรายอัลบั้ม {len(albums)} อัลบั้ม (เรียงตามเวลาที่เข้าระบบ) · ซ้ำ {sum(1 for r in albums if r[STATUS] == 'ซ้ำ')}")
    for r in albums:
        print(f"  {r[0]:>3}. {str(r[2] or '')[:16]:<17}{str(r[1])[:30]:<32}อ่าน {r[3]:>4} · ซ้ำ {r[7]:>3}  {r[STATUS]}"
              + (f" · กับ {r[9]}" if r[9] else ""))
    if cases:
        print(f"\n{'ไรเดอร์ผู้ส่ง':<26}{'ใบซ้ำ':>7}{'ยอดรวม':>10}  ประเภทที่เจอ")
        for k, v in sorted(summary(cases).items(), key=lambda kv: -kv[1]["ใบซ้ำ"]):
            kinds = " · ".join(f"{n} {name}" for name in KINDS for n in [v[name]] if n)
            print(f"{k[:25]:<26}{v['ใบซ้ำ']:>7}{v['ยอดรวม']:>10,.0f}  {kinds}")
    shared = [c for c in cases if sent_by_someone_else(c)]
    unsure = sum(1 for c in cases if not (c.get("ผู้ส่งแน่ชัด") and c.get("ต้นฉบับแน่ชัด")))
    if unsure:
        print(f"\n{unsure} ใบยังชี้ตัวคนส่งไม่ได้แน่ — รูปเข้ามาก่อนที่ระบบจะเริ่มจดต้นทาง "
              f"(2026-09-13) ช่อง 'ไรเดอร์ผู้ส่ง' ของแถวพวกนี้คือโฟลเดอร์ที่ระบบเอารูปไปวาง "
              f"ใช้ตีกลับไม่ได้")
    if shared:
        print(f"\nในนั้น {len(shared)} ใบเป็นสลิปที่ถูกส่งใต้ชื่อไรเดอร์คนละคน:")
        for c in shared[:15]:
            print(f"  {(c['ไฟล์ที่ซ้ำ'] or '')[:46]:<48} ส่งโดย {c['ไรเดอร์ผู้ส่ง'][:18]:<20}"
                  f"ซ้ำกับของ {c['ของไรเดอร์']}")
    if undecided:
        # รหัสการจองเดียวกันแต่เงินคนละยอด = คำถามจริง ไม่ใช่รูปถ่ายเกิน ระบบจึงไม่ทิ้งให้
        # (db.discard_settled_duplicates) พิมพ์ส่วนต่างออกมาให้เห็น จะได้รู้ว่าต้องเปิดรูปใบไหน
        print(f"\nต้องให้คนตัดสิน {len(undecided)} ใบ — รหัสการจองซ้ำแต่ยอดไม่ตรง:\n")
        print(f"{'id':>7}  {'ไรเดอร์ผู้ส่ง':<22}{'ยอดใบนี้':>10}{'ยอดต้นฉบับ':>12}{'ต่าง':>9}  ไฟล์")
        for c in undecided:
            a1, a2 = c["ยอด"], c["ยอดของต้นฉบับ"]
            gap = f"{a1 - a2:+,.0f}" if a1 is not None and a2 is not None else "—"
            print(f"{c['id']:>7}  {str(c['ไรเดอร์ผู้ส่ง'])[:21]:<22}"
                  f"{(a1 if a1 is not None else 0):>10,.0f}{(a2 if a2 is not None else 0):>12,.0f}"
                  f"{gap:>9}  {str(c['ไฟล์ที่ซ้ำ'])[:48]}")
            print(f"{'':>7}  ซ้ำกับ {str(c['ซ้ำกับไฟล์'])[:48]} ของ {c['ของไรเดอร์']}"
                  f" · รูปที่ส่งลูกค้า {c['รูปที่ส่งลูกค้า'] or '—'}")
    if a.xlsx:
        print(f"\nเขียนไฟล์แล้ว: {write_xlsx(a.xlsx, cases, undecided, pre, albums)}")
    if a.to_drive:
        import config
        import roster
        drive = roster._drive()
        found, links = with_pictures(drive, config.DRIVE_EXPORTS_FOLDER_ID, a.d_from, cases, undecided, pre, albums)
        folder, fid = upload_to_drive(drive, config.DRIVE_EXPORTS_FOLDER_ID, a.d_from,
                                      build_xlsx(cases, undecided, pre, albums, admin_rows(found, links)))
        print(f"\nวางลง Drive แล้ว: Exports/{DRIVE_DIR}/{report_name(a.d_from)}")
        print(f"  เปิดไฟล์: https://drive.google.com/file/d/{fid}/view")
        print(f"  โฟลเดอร์: https://drive.google.com/drive/folders/{folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
