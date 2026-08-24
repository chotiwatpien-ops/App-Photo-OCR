# -*- coding: utf-8 -*-
"""One trip through Gemini → checks → DB. Shared by the web app (manual upload) and ingest.py."""
import re

import db
import extractor

# fields that only the bottom half can show — copied onto the top half when pairing
BOTTOM_FIELDS = ["passenger_total", "passenger_paid", "grab_commission", "app_fee", "other_adj", "fare_refund", "tip", "intl_fee"]
# incentives appear on the bottom half too; take them when the top half has none
BOTTOM_IF_MISSING = ["bonus", "turbo", "tolls"]


def _natural_key(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name or "")]


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _halves_match(top, bot) -> bool:
    """Do an adjacent top half and bottom half belong to the same trip?
    Both halves print ค่าโดยสารพื้นฐาน, so base fare is the primary key. Fallbacks cover the
    bottom half reporting base as 'net' (car trips with turbo) or a missing base."""
    tn, tb = _num(top["net_earnings"]), _num(top["base_fare"])
    bn, bb = _num(bot["net_earnings"]), _num(bot["base_fare"])
    def eq(a, c): return a is not None and c is not None and a > 0 and abs(a - c) <= 0.01
    return eq(tb, bb) or eq(tn, bn) or eq(tb, bn) or eq(tn, bb)


def pair_fragments(job_id) -> int:
    """Riders often send one trip as two screenshots (top half with the route, bottom half with
    the fare breakdown). Pair each 'top' with an adjacent 'bottom' (by file order) that shows the
    same 'คุณได้รับ' amount, fold the bottom's fields into the top, and hide the bottom row.
    Idempotent. Returns number of pairs made."""
    rows = sorted(db.done_trips_for_pairing(job_id), key=lambda r: _natural_key(r["file_name"]))
    used, pairs = set(), 0
    for i, r in enumerate(rows):
        if r["kind"] != "top" or r["id"] in used or db.has_merged_child(r["id"]):
            continue
        for j in (i - 1, i + 1):
            if j < 0 or j >= len(rows):
                continue
            b = rows[j]
            if b["kind"] != "bottom" or b["id"] in used or b["merged_into"]:
                continue
            if not _halves_match(r, b):
                continue
            top, bot = db.get_trip(r["id"]), db.get_trip(b["id"])
            fields = {k: bot.get(k) for k in BOTTOM_FIELDS if bot.get(k) is not None}
            for k in BOTTOM_IF_MISSING:
                if not top.get(k) and bot.get(k):
                    fields[k] = bot[k]
            if not top.get("base_fare") and bot.get("base_fare"):
                fields["base_fare"] = bot["base_fare"]
            # the driver's net ('คุณได้รับ', incl. turbo) is only reliable on the top half; the bottom
            # half often starts below it and reports 'รวมรายได้จากรอบขับ' (= base) instead
            if top.get("net_earnings") is None and bot.get("net_earnings") is not None:
                fields["net_earnings"] = bot["net_earnings"]
            merged = {**top, **fields}
            fields["check_status"] = extractor.arithmetic_check({
                "net_earnings": merged.get("net_earnings"), "base_fare": merged.get("base_fare"),
                "bonus": merged.get("bonus"), "turbo": merged.get("turbo"),
                "passenger_total": merged.get("passenger_total"),
                "grab_commission": merged.get("grab_commission"),
                "net_earnings_left_panel": None,
            })
            fields["kind"] = "full"
            note = f"รวม 2 รูป: {r['file_name']} + {b['file_name']}"
            prior = top.get("note") or ""
            # a bottom half that happened to show the booking code got flagged as a duplicate of
            # its own top half — once they are merged that is not a duplicate
            if top.get("duplicate_of") == b["id"]:
                fields["duplicate_of"] = None
                prior = " | ".join(p for p in prior.split(" | ") if "ซ้ำกับ" not in p)
            fields["note"] = f"{note} | {prior}" if prior else note
            db.merge_bottom_into_top(b["id"], r["id"], fields)
            used.update({r["id"], b["id"]})
            pairs += 1
            break
    db.refresh_job_status(job_id)
    return pairs


def spread_dates(job_id, date_from, date_to, only_missing=True) -> int:
    """The screenshots carry no trip date, so spread a job's trips evenly over its week
    (Mon..Sun) in file order — 21 trips -> 3 per day, 20 -> 3,3,3,3,3,3,2.
    only_missing=True touches rows without a date (day-subfolder rows keep theirs)."""
    from datetime import date, timedelta
    rows = sorted(db.done_trips_for_dating(job_id, only_missing), key=lambda r: _natural_key(r["file_name"]))
    if not rows:
        return 0
    d0, d1 = date.fromisoformat(date_from), date.fromisoformat(date_to)
    days = [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)] or [date_from]
    n, k = len(rows), len(days)
    base, extra = divmod(n, k)
    i = 0
    for di, day in enumerate(days):
        take = base + (1 if di < extra else 0)
        for r in rows[i:i + take]:
            db.update_trip(r["id"], {"trip_date": day})
        i += take
    return n


def customer_images(job_id, rider, fetch=None):
    """Yield (file_name, jpeg_bytes) for every trip in customer order: '<rider>1.jpg', '<rider>2.jpg', ...
    Uses the stored blobs; when they were already cleared (approved rows) and `fetch(drive_id)`
    is given, re-downloads the originals from Drive."""
    import stitch
    rows = db.trips_with_images(job_id)
    rows.sort(key=lambda r: (r["trip_date"] or "9999", _natural_key(r["file_name"])))
    drive_ids = db.drive_ids_for_job(job_id) if fetch else {}
    if fetch:  # re-download cleared blobs in parallel before stitching
        from concurrent.futures import ThreadPoolExecutor
        from config import DRIVE_PARALLEL
        need = []
        for r in rows:
            if r["top_blob"] is None and r["id"] in drive_ids:
                need.append((r, "top_blob", drive_ids[r["id"]]))
            bid = r.get("bottom_id")
            if r["bottom_blob"] is None and bid and bid in drive_ids:
                need.append((r, "bottom_blob", drive_ids[bid]))
        with ThreadPoolExecutor(max_workers=DRIVE_PARALLEL) as ex:
            for (r, key, _), data in zip(need, ex.map(lambda t: fetch(t[2]), need)):
                r[key] = data
    n = 0
    for r in rows:
        if not r["top_blob"]:
            continue
        n += 1
        name = stitch.customer_name(rider, n)
        db.update_trip(r["id"], {"customer_image": name})  # so Sheet1 can trace back to this file
        yield name, stitch.stitch(r["top_blob"], r["bottom_blob"])


# team's vehicle groups -> template Service Type values
CATEGORY_SERVICE = {
    "4 W Standard": "Standard Car", "4 W Saver": "Saver Car",
    "2 W Standard": "Standard Bike", "2 W Saver": "Saver Bike",
}


def normalize_service(ai_value, category):
    """Map whatever Grab printed ('Standard (JustGrab)', 'Saver Bike', ...) onto the template's four
    values, using the rider's vehicle group to settle car-vs-bike. Returns (value, conflict_note)."""
    raw = (ai_value or "").lower()
    tier = "Saver" if "saver" in raw else ("Standard" if ("standard" in raw or "justgrab" in raw) else None)
    wheel = "Bike" if "bike" in raw else ("Car" if ("car" in raw or "justgrab" in raw) else None)
    cat = CATEGORY_SERVICE.get(category or "")
    if cat:
        # team decision (2026-08-23): column D means the RIDER'S GROUP, not the trip's product —
        # always use the folder's category; still flag a car/bike contradiction for review
        cat_wheel = cat.split()[1]
        note = None
        if wheel and wheel != cat_wheel:
            note = f"รูปบอก {ai_value} แต่ไรเดอร์อยู่กลุ่ม {category}"
        return cat, note
    if tier and wheel:
        return f"{tier} {wheel}", None
    return ai_value, None


def process_trip(trip_id: int, job_id: int) -> str:
    """Extract one stored image and persist the result. Returns 'done' | 'error'."""
    try:
        img = db.get_trip_image(trip_id)
        if not img:
            raise RuntimeError("image missing")
        data = extractor.extract_image(img[0], img[1])
        data["bonus"] = (data.get("bonus") or 0) + (data.get("tip") or 0)  # so the identity check sees the tip
        check = extractor.arithmetic_check(data)
        note = data.get("confidence_note")
        dup = db.find_job_duplicate(job_id, data.get("booking_code"), trip_id)
        if dup:
            dup_msg = f"รูปนี้ซ้ำกับ {dup['file_name']} (booking code เดียวกัน)"
            note = f"{dup_msg} | {note}" if note else dup_msg
        usage = data.get("_usage", {})
        job = db.get_job_meta(job_id)
        service, svc_note = normalize_service(data.get("service_type"), job.get("category") if job else None)
        if data.get("kind") == "bottom":
            svc_note = None  # no service chip on the bottom half — the model guessed
        if data.get("kind") in ("full", "bottom") and data.get("passenger_paid") is None and data.get("passenger_total") is None:
            pf_note = "P ว่าง — รูปหุบหัวข้อ 'ค่าโดยสารของผู้โดยสารทั้งหมด' (แจ้งไรเดอร์กางก่อนแคป)"
            note = f"{pf_note} | {note}" if note else pf_note
        if svc_note:
            note = f"{svc_note} | {note}" if note else svc_note
            if check == "pass":
                check = "fail"  # car/bike contradiction — a person must look
        db.update_trip(trip_id, {
            "status": "done",
            "booking_code": data.get("booking_code"),
            "check_status": check,
            "duplicate_of": dup["id"] if dup else None,
            "service_type": (service or "").strip(),
            "payment_method": extractor.resolve_payment(data),
            "pickup_code": data.get("pickup_province"),
            "dropoff_code": data.get("dropoff_province"),
            "pickup_text": data.get("pickup_text"),
            "dropoff_text": data.get("dropoff_text"),
            "distance_km": data.get("distance_km"),
            "duration_mins": data.get("duration_mins"),
            "net_earnings": data.get("net_earnings"),
            "base_fare": data.get("base_fare"),
            "bonus": (data.get("bonus") or 0) + (data.get("tip") or 0),  # tip counts as Bonus (M)
            "tip": data.get("tip") or 0,
            "intl_fee": abs(data.get("intl_fee") or 0),
            "turbo": data.get("turbo") or 0,
            "tolls": data.get("tolls") or 0,
            "passenger_total": data.get("passenger_total"),
            "passenger_paid": data.get("passenger_paid"),
            "grab_commission": data.get("grab_commission"),
            "pickup_district": data.get("pickup_district"),
            "dropoff_district": data.get("dropoff_district"),
            "surge": 1 if data.get("surge") else 0,
            "queue_type": data.get("queue_type"),
            "num_stops": data.get("num_stops"),
            "app_fee": data.get("app_fee"),
            "other_adj": data.get("other_adjustments"),
            "fare_refund": data.get("fare_refund"),
            "model": usage.get("model"),
            "tok_in": usage.get("tok_in"),
            "tok_out": usage.get("tok_out"),
            "tok_think": usage.get("tok_think"),
            "trip_time": extractor.normalize_time(data.get("screen_time")),
            "kind": data.get("kind") or "full",
            "note": note,
        })
        return "done"
    except Exception as e:  # noqa: BLE001 - surface any failure on the trip row
        db.update_trip(trip_id, {"status": "error", "error": str(e)[:500]})
        return "error"
    finally:
        db.refresh_job_status(job_id)
