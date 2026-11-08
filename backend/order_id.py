# -*- coding: utf-8 -*-
"""Order ID (requirement 2026-11-08): driver id + date + receipt number.

    0001 + 301126 + 01  ->  000130112601
    4-digit driver id (name_pool.driver_id), the trip date as DDMMYY, and the trip's place among
    that driver's trips of the day, 01, 02, … by the time on the slip.

A trip without a driver id or a date gets no Order ID rather than a made-up one. Not used by any
file yet: where it goes (a column, the picture name, or both) waits on the customer.
"""
from collections import defaultdict
from datetime import date


def order_ids(rows, driver_ids):
    """{trip id: order id or None}. rows: dicts with id, driver_name, trip_date (YYYY-MM-DD) and
    trip_time (HH:MM or None); driver_ids: {driver_name: '0001'} as db.driver_ids() gives."""
    out, by_day = {}, defaultdict(list)
    for r in rows:
        did = driver_ids.get(r.get("driver_name"))
        if not did or not r.get("trip_date"):
            out[r["id"]] = None
            continue
        by_day[(did, r["trip_date"])].append(r)
    for (did, day), trips in by_day.items():
        stamp = date.fromisoformat(day).strftime("%d%m%y")
        for n, r in enumerate(sorted(trips, key=lambda t: (t.get("trip_time") or "99:99", t["id"])), start=1):
            out[r["id"]] = f"{did}{stamp}{n:02d}" if n <= 99 else None
    return out
