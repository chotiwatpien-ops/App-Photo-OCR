# -*- coding: utf-8 -*-
"""Order ID (requirement 2026-11-08): driver id + date + receipt number.

    0056 + 091126 + 01  ->  005609112601

4-digit driver id (name_pool.driver_id), the trip date as DDMMYY, and the trip's place among
that driver's trips of the day, 01, 02, … From ORDER_ID_FROM on (Fiat 2026-11-10, from W46) the
customer picture is named '<Order ID>.jpg' and the file carries Driver ID and Order ID after the
driver's name, so a picture and its row match by name.

The picture name is the record: the file reads the Order ID back out of it, so the two cannot
disagree. A number once given is kept (the way the old 'WK46-name7.jpg' numbers were): a trip
added later takes the next free number of its day instead of renumbering pictures already made.
A trip whose rider or date changes (rehome, carry) no longer owns its name and gets a new one.
"""
import re
from datetime import date

import config

NAME = re.compile(r"^(\d{4})(\d{6})(\d{2})\.jpe?g$", re.IGNORECASE)


def applies(week_from) -> bool:
    """Whether a job of the week starting week_from is named by Order ID."""
    return bool(config.ORDER_ID_FROM and week_from and week_from >= config.ORDER_ID_FROM)


def stamp(trip_date) -> str:
    """'2026-11-09' -> '091126'."""
    return date.fromisoformat(trip_date).strftime("%d%m%y")


def parse(name):
    """'005609112601.jpg' -> ('0056', '091126', 1), or None for any other name."""
    m = NAME.match(name or "")
    return (m.group(1), m.group(2), int(m.group(3))) if m else None


def of_picture(name):
    """The Order ID a customer picture is named by, or None."""
    p = parse(name)
    return f"{p[0]}{p[1]}{p[2]:02d}" if p else None


def picture_name(driver_id, trip_date, seq) -> str:
    return f"{driver_id}{stamp(trip_date)}{seq:02d}.jpg"


def assign(rows, driver_id, names_in_week):
    """{trip id: picture name} for a rider's rows that have a date.

    rows: dicts with id, trip_date, trip_time and customer_image. A row whose current picture
    name is this driver's for its own date keeps it; the others take the lowest free number of
    their day, in date and slip-time order. names_in_week: every customer picture name already
    given in the week, any rider, so a number another job of the same rider holds is never
    handed out twice. A day past 99 trips gets no Order ID name (left to the caller)."""
    taken = {}
    for name in names_in_week:
        p = parse(name)
        if p and p[0] == driver_id:
            taken.setdefault(p[1], set()).add(p[2])
    out = {}
    for r in rows:
        p = parse(r.get("customer_image"))
        if r.get("trip_date") and p and p[0] == driver_id and p[1] == stamp(r["trip_date"]):
            out[r["id"]] = r["customer_image"]
            taken.setdefault(p[1], set()).add(p[2])
    fresh = sorted((r for r in rows if r.get("trip_date") and r["id"] not in out),
                   key=lambda r: (r["trip_date"], r.get("trip_time") or "99:99", r["id"]))
    for r in fresh:
        day = stamp(r["trip_date"])
        used = taken.setdefault(day, set())
        seq = next(n for n in range(1, 101) if n not in used)
        if seq > 99:
            continue
        used.add(seq)
        out[r["id"]] = picture_name(driver_id, r["trip_date"], seq)
    return out
