# -*- coding: utf-8 -*-
"""Two rows that are one trip although their booking codes are not equal letter for letter.

db.trip_key matches codes exactly. Grab prints the code across two lines and the reader slips
at the break: W46 (Fiat 2026-11-11) approved A-AWRFU6TGWWTFAV twice, read once as
'…TGWTFAV' and once as '…TGWWWTFAV', ฿38 counted twice. Two kinds of evidence say "same trip"
without an exact code:

    code    codes at most two letters apart, same base fare, same distance — strong enough to
            block closing the week
    route   same pick-up, drop-off, distance and base fare (and clock time when both have one) —
            a regular commute can repeat this, so a person decides

Neither is acted on automatically: a row found this way waits in the review queue (SUSPECT in
its note keeps the round from parking it), and a person approves or deletes it."""
import re

SUSPECT = "สงสัยว่าซ้ำ"
CODE, ROUTE = "code", "route"
REASON = {CODE: "เลขจองต่างกันไม่เกิน 2 ตัว ค่ารอบและระยะทางตรงกัน",
          ROUTE: "จุดรับ จุดส่ง ระยะทาง และค่ารอบตรงกัน"}
_FOLD = str.maketrans({"O": "0", "Q": "0", "I": "1", "L": "1"})
MIN_CODE = 8


def fold(code) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper()).translate(_FOLD)


def _place(text) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()[:30]


def _eq(a, b) -> bool:
    return a is not None and b is not None and abs(a - b) < 0.005


def _close(a, b, most=2) -> bool:
    """Edit distance between a and b is at most `most`."""
    if abs(len(a) - len(b)) > most:
        return False
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        if min(cur) > most:
            return False
        prev = cur
    return prev[-1] <= most


def kind(a, b):
    """CODE, ROUTE or None for two rows (dicts with booking_code, base_fare, distance_km,
    pickup_text, dropoff_text, trip_time)."""
    if not _eq(a.get("base_fare"), b.get("base_fare")):
        return None
    ka, kb = a.get("distance_km"), b.get("distance_km")
    ca, cb = fold(a.get("booking_code")), fold(b.get("booking_code"))
    if (len(ca) >= MIN_CODE and len(cb) >= MIN_CODE and _close(ca, cb)
            and (ka is None or kb is None or _eq(ka, kb))):
        return CODE
    ta, tb = a.get("trip_time"), b.get("trip_time")
    pa, da = _place(a.get("pickup_text")), _place(a.get("dropoff_text"))
    if (_eq(ka, kb) and pa and da and pa == _place(b.get("pickup_text"))
            and da == _place(b.get("dropoff_text")) and (not ta or not tb or ta == tb)):
        return ROUTE
    return None


def find_twin(row, others):
    """(the first of `others` that is the same trip as `row`, kind) or (None, None)."""
    for o in others:
        if o.get("id") != row.get("id"):
            k = kind(row, o)
            if k:
                return o, k
    return None, None


def groups(rows):
    """[(kind, [rows])] of rows that are one trip. CODE groups join rows by CODE evidence only, so
    a row that merely shares a route never lands in a "counted twice" group; ROUTE groups join the
    remaining ROUTE pairs. Rows are compared within the same base fare only, so a week of several
    thousand stays quick."""
    by_fare = {}
    for r in rows:
        if r.get("base_fare") is not None:
            by_fare.setdefault(round(r["base_fare"], 2), []).append(r)
    edges = {CODE: [], ROUTE: []}
    for same in by_fare.values():
        for i, a in enumerate(same):
            for b in same[i + 1:]:
                k = kind(a, b)
                if k:
                    edges[k].append((a, b))
    out = []
    code_of = {}
    for k in (CODE, ROUTE):
        parent = {}

        def root(x):
            while parent.get(x, x) != x:
                x = parent[x]
            return x
        rows_of = {}
        for a, b in edges[k]:
            if k == ROUTE and code_of.get(a["id"]) is not None and code_of.get(a["id"]) == code_of.get(b["id"]):
                continue                  # already one trip by its code
            rows_of[a["id"]], rows_of[b["id"]] = a, b
            ra, rb = root(a["id"]), root(b["id"])
            if ra != rb:
                parent[rb] = ra
        members = {}
        for i, r in rows_of.items():
            members.setdefault(root(i), []).append(r)
        for g, ms in members.items():
            ms = sorted(ms, key=lambda r: r["id"])
            out.append((k, ms))
            if k == CODE:
                code_of.update({r["id"]: g for r in ms})
    return out
