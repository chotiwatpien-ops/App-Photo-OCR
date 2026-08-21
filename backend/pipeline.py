# -*- coding: utf-8 -*-
"""One trip through Gemini → checks → DB. Shared by the web app (manual upload) and ingest.py."""
import db
import extractor


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
            "note": note,
        })
        return "done"
    except Exception as e:  # noqa: BLE001 - surface any failure on the trip row
        db.update_trip(trip_id, {"status": "error", "error": str(e)[:500]})
        return "error"
    finally:
        db.refresh_job_status(job_id)
