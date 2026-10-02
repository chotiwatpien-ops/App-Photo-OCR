# -*- coding: utf-8 -*-
"""What the customer's first screen shows for one week — the 'ภาพรวม' tab (redesign 2026-10).

Counted by Service Type, the way the customer counts, and split by where each trip stands:
in the file, waiting for a person, or still being read. Then what to do next, in the order it
should be done, so someone opening the app for the first time is not left to work that out.

A row not read yet has no Service Type; it is placed by its folder's group, as the pool placed
it. A read row still in _พร้อมอ่าน is filed by the next round by itself, so to the person
looking it is still 'being read'.
"""
from datetime import datetime, timedelta

from sqlalchemy import select

import config
import db
from pipeline import CATEGORY_SERVICE, car_is_standard

SERVICES = ("Saver Bike", "Standard Bike", "Standard Car")
GROUP_OF = {"Saver Bike": "2 W Saver", "Standard Bike": "2 W Standard", "Standard Car": "4 W Standard"}
ROUND_HOURS, ROUND_MINUTE, ROUND_FIRST_HOUR, MIN_GAP_HOURS = 3, 23, 1, 2.5   # ingest.yml: 23 */3 UTC


def _service(row):
    svc = (row["service_type"] or "").strip() or CATEGORY_SERVICE.get((row["category"] or "").strip(), "")
    svc = car_is_standard(svc) if svc else ""
    return svc if svc in SERVICES else None


def week_rows(d_from, d_to):
    t, j = db.trips.c, db.jobs.c
    with db.engine.begin() as c:
        return [dict(r) for r in c.execute(
            select(t.id, t.status, t.committed, t.service_type, t.trip_date, t.check_status,
                   t.duplicate_of, t.booking_code, j.category, j.driver_name)
            .select_from(db.trips.join(db.jobs, j.id == t.job_id))
            .where(j.date_from == d_from, j.date_to == d_to)).mappings().all()]


def progress(rows, target):
    out = {s: {"service": s, "filed": 0, "review": 0, "reading": 0} for s in SERVICES}
    unplaced = errors = 0
    for r in rows:
        holding = r["driver_name"] == db.HOLDING_RIDER
        if r["status"] == "error":
            errors += 1
            continue
        if r["status"] == "pending" or (r["status"] == "done" and holding):
            key = "reading"
        elif r["status"] == "done":
            key = "filed" if r["committed"] else "review"
        else:
            continue                               # duplicate / voided: on nobody's bill
        svc = _service(r)
        if svc is None:
            unplaced += key == "reading"
            continue
        out[svc][key] += 1
    groups = []
    for s in SERVICES:
        g = out[s]
        g["have"] = g["filed"] + g["review"] + g["reading"]
        g["short"] = max(0, target - g["have"])
        g["over"] = max(0, g["have"] - target)
        groups.append(g)
    return groups, unplaced, errors


def review_reasons(d_from, d_to):
    """The week's rows waiting for a person, by why they are waiting."""
    week_jobs = {j["id"] for j in db.jobs_by_week().get((d_from, d_to), [])}
    out = {"dup": 0, "date": 0, "money": 0, "ready": 0}
    for r in db.review_queue():
        if r["job_id"] not in week_jobs:
            continue
        if r.get("duplicate_of") or r.get("seen_in_job"):
            out["dup"] += 1
        elif not r.get("trip_date"):
            out["date"] += 1
        elif r.get("check_status") != "pass":
            out["money"] += 1
        else:
            out["ready"] += 1
    out["total"] = sum(out.values())
    return out


def next_round(now, last_finished=None):
    """When the next reading round should run: the schedule's next slot that the gate lets
    through (a round finished less than MIN_GAP_HOURS ago makes the next slot skip)."""
    slot = now.replace(minute=ROUND_MINUTE, second=0, microsecond=0)
    if slot <= now:
        slot += timedelta(hours=1)
    while slot.hour % ROUND_HOURS != ROUND_FIRST_HOUR:
        slot += timedelta(hours=1)
    if last_finished:
        while slot < last_finished + timedelta(hours=MIN_GAP_HOURS):
            slot += timedelta(hours=ROUND_HOURS)
    return slot


def riders_with_room(rows, short_services):
    """People in a group that is still short who can take more this week, most room first."""
    exp = config.EXPECTED_TRIPS_PER_WEEK
    have = {}
    for r in rows:
        if r["driver_name"] == db.HOLDING_RIDER or r["status"] not in ("done", "pending", "error"):
            continue
        cat = (r["category"] or "").strip()
        svc = CATEGORY_SERVICE.get(cat)
        svc = car_is_standard(svc) if svc else None
        if svc not in short_services:
            continue
        key = (r["driver_name"], svc)
        have[key] = have.get(key, 0) + 1
    out = []
    for (name, svc), n in have.items():
        cap = config.WEEK_QUOTA.get(GROUP_OF[svc], exp)
        if n < cap:
            out.append({"name": name, "service": svc, "have": n, "cap": cap, "room": cap - n})
    out.sort(key=lambda x: (-x["room"], x["name"]))
    return out


def build(d_from, d_to, albums=(), now=None):
    target = config.WEEKLY_TARGET_PER_GROUP
    now = now or datetime.now(db._TZ_BKK).replace(tzinfo=None)
    rows = week_rows(d_from, d_to)
    groups, unplaced, errors = progress(rows, target)
    reasons = review_reasons(d_from, d_to)
    reading = sum(g["reading"] for g in groups) + unplaced
    last = db.latest_ingest_run()
    finished = datetime.fromisoformat(last["finished_at"]) if last and last.get("finished_at") else None
    running = bool(last and not last.get("finished_at"))
    short = {g["service"]: g["short"] for g in groups if g["short"]}
    riders = riders_with_room(rows, set(short))
    today = now.date().isoformat()

    todos = []
    if reasons["total"]:
        parts = [f"{label} {reasons[k]:,}" for k, label in
                 (("money", "ตัวเลขไม่ลงตัว"), ("date", "ไม่มีวันที่"), ("dup", "สงสัยว่าซ้ำ"), ("ready", "ผ่านแล้ว รอกดอนุมัติ"))
                 if reasons[k]]
        todos.append({"kind": "review", "tone": "danger", "mark": f"{reasons['total']:,}",
                      "title": f"ตรวจ {reasons['total']:,} แถวที่ระบบไม่แน่ใจ", "sub": " · ".join(parts),
                      "action": "ไปที่คิวตรวจ", "go": "queue"})
    if short:
        todos.append({"kind": "short", "tone": "warn", "mark": "!",
                      "title": "ขอรูปเพิ่ม " + " · ".join(f"{s} {n:,}" for s, n in short.items()) + " เที่ยว",
                      "sub": (f"มีไรเดอร์ที่ยังรับงานได้ {len(riders):,} คน (รายชื่ออยู่ด้านล่าง)" if riders
                              else "ไรเดอร์ที่มีอยู่รับครบโควตาแล้ว ต้องหาคนเพิ่ม"),
                      "action": "ดูรายชื่อ" if riders else "", "go": "riders"})
    if reading:
        nxt = next_round(now, finished)
        todos.append({"kind": "reading", "tone": "wait", "mark": "…",
                      "title": f"รอผลอ่าน {reading:,} รูป",
                      "sub": ("กำลังอ่านอยู่ตอนนี้" if running else f"จะเข้าระบบรอบถัดไป ประมาณ {nxt:%H:%M}")
                             + " — ไม่ต้องส่งรูปซ้ำ", "action": "", "go": ""})
    if errors:
        todos.append({"kind": "errors", "tone": "warn", "mark": f"{errors:,}",
                      "title": f"รูปที่อ่านไม่สำเร็จ {errors:,} รูป", "sub": "จะไม่อยู่ในไฟล์ส่งลูกค้า ถ้าไม่ได้แก้",
                      "action": "ดูรายการ", "go": "queue"})
    if not todos:
        todos.append({"kind": "done", "tone": "ok", "mark": "✓", "title": "ไม่มีอะไรค้าง",
                      "sub": "ทุกกลุ่มครบเป้า ไม่มีแถวรอตรวจ — ไปปิดสัปดาห์ได้เมื่อสัปดาห์จบ",
                      "action": "ไปปิดสัปดาห์", "go": "close"})

    albums = list(albums)
    return {
        "week": d_from, "week_to": d_to, "target": target, "now": now.isoformat(timespec="seconds"),
        "closed": db.week_closed(d_from),
        "groups": groups, "todos": todos, "review": reasons, "errors": errors,
        "reading": {"total": reading, "running": running,
                    "last_started": last and last.get("started_at"),
                    "last_finished": last and last.get("finished_at"),
                    "next": next_round(now, finished).strftime("%H:%M"),
                    "batch": sum(b.get("n_trips") or 0 for b in db.open_batches()),
                    "albums_today": sum(1 for a in albums if (a.get("first") or "").startswith(today))},
        "riders": riders[:8], "riders_total": len(riders),
        "albums": albums[::-1][:5], "albums_total": len(albums),
        "albums_dup": sum(1 for a in albums if a.get("status") == "ซ้ำ"),
    }
