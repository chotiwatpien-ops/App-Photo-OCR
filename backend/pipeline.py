# -*- coding: utf-8 -*-
"""One trip through Gemini → checks → DB. Shared by the web app (manual upload) and ingest.py."""
import re

import db
import extractor

# fields that only the bottom half can show — copied onto the top half when pairing
BOTTOM_FIELDS = ["passenger_total", "grab_commission", "app_fee", "other_adj", "fare_refund"]
# incentives appear on the bottom half too; take them when the top half has none
BOTTOM_IF_MISSING = ["bonus", "turbo", "tolls"]


def _natural_key(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name or "")]


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
            if r["net_earnings"] is None or b["net_earnings"] is None:
                continue
            if abs(float(r["net_earnings"]) - float(b["net_earnings"])) > 0.01:
                continue
            top, bot = db.get_trip(r["id"]), db.get_trip(b["id"])
            fields = {k: bot.get(k) for k in BOTTOM_FIELDS if bot.get(k) is not None}
            for k in BOTTOM_IF_MISSING:
                if not top.get(k) and bot.get(k):
                    fields[k] = bot[k]
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
            fields["note"] = f"{note} | {top['note']}" if top.get("note") else note
            db.merge_bottom_into_top(b["id"], r["id"], fields)
            used.update({r["id"], b["id"]})
            pairs += 1
            break
    db.refresh_job_status(job_id)
    return pairs


def process_trip(trip_id: int, job_id: int) -> str:
    """Extract one stored image and persist the result. Returns 'done' | 'error'."""
    try:
        img = db.get_trip_image(trip_id)
        if not img:
            raise RuntimeError("image missing")
        data = extractor.extract_image(img[0], img[1])
        check = extractor.arithmetic_check(data)
        note = data.get("confidence_note")
        dup = db.find_job_duplicate(job_id, data.get("booking_code"), trip_id)
        if dup:
            dup_msg = f"รูปนี้ซ้ำกับ {dup['file_name']} (booking code เดียวกัน)"
            note = f"{dup_msg} | {note}" if note else dup_msg
        usage = data.get("_usage", {})
        db.update_trip(trip_id, {
            "status": "done",
            "booking_code": data.get("booking_code"),
            "check_status": check,
            "duplicate_of": dup["id"] if dup else None,
            "service_type": (data.get("service_type") or "").strip(),
            "payment_method": extractor.resolve_payment(data),
            "pickup_code": data.get("pickup_province"),
            "dropoff_code": data.get("dropoff_province"),
            "pickup_text": data.get("pickup_text"),
            "dropoff_text": data.get("dropoff_text"),
            "distance_km": data.get("distance_km"),
            "duration_mins": data.get("duration_mins"),
            "net_earnings": data.get("net_earnings"),
            "base_fare": data.get("base_fare"),
            "bonus": data.get("bonus") or 0,
            "turbo": data.get("turbo") or 0,
            "tolls": data.get("tolls") or 0,
            "passenger_total": data.get("passenger_total"),
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
