# -*- coding: utf-8 -*-
"""ชุดเฉลย, the answer key. A person looks at the slip picture of an auto-approved trip and says,
field by field, what the picture prints. The reader's accuracy per field is counted from that.

The truth is what the picture prints, written the way the sheet writes it, never what a rule
worked out. Each fact is one row of key_facts: (trip, field) -> truth and what the trip row held
when the person looked. A missing truth means the fact is not on the picture. Right or wrong is
worked out from the two on every read and never stored.

This module is the only reader and writer of key_facts and key_slips, and it never writes trips.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Callable, Iterable, Mapping, Optional, Union

from sqlalchemy import BigInteger, and_, cast, func, insert, literal_column, or_, select, update
from sqlalchemy.exc import IntegrityError

import db
from extractor import normalize_time
from pipeline import car_is_standard


@dataclass(frozen=True)
class KeyField:
    """One checkable fact. `key` is also the trips column it is compared with."""
    key: str
    label: str
    kind: str               # time | code | number | choice
    hint: str               # where to look on the slip, and when it counts as not on the picture
    options: tuple = ()     # choice only
    alias: Optional[Callable] = None    # choice only: a printed name -> the name the sheet uses

    def canon(self, value) -> Optional[str]:
        """Any way of writing the value -> its one canonical text, or None for empty. What a
        person typed and what a trip row holds both pass through here, so two values are the same
        fact exactly when their canonical texts are equal. Raises ValueError for a value the kind
        cannot hold."""
        text = "" if value is None else str(value).strip()
        if not text:
            return None
        if self.kind == "time":
            out = normalize_time(text)
            if out is None:
                raise ValueError(text)
            return out
        if self.kind == "code":
            return "".join(text.split()).upper()
        if self.kind == "number":
            number = float(text.replace(",", ""))
            if not math.isfinite(number):
                raise ValueError(text)
            return f"{number:.2f}"
        if text.upper() == "UNKNOWN":
            return None
        name = self.alias(text) if self.alias else text
        if name not in self.options:
            raise ValueError(text)
        return name

    def public(self) -> dict:
        return {"key": self.key, "label": self.label, "kind": self.kind, "hint": self.hint,
                "options": list(self.options)}


# The only list of answer-key fields: the page is served it, the report iterates it. In the order
# the eye meets them on the slip: status bar, code, route panel, chips, income card.
FIELDS: tuple = (
    KeyField("trip_time", "เวลาบนแถบสถานะ", "time",
             "นาฬิกาบนแถบสถานะของจอซ้าย · ไม่มีแถบสถานะ = ไม่มีในรูป"),
    KeyField("booking_code", "รหัสการจอง", "code",
             "อ่านให้ครบทั้งสองบรรทัด · จอตัดด้วย … = ไม่มีในรูป"),
    KeyField("distance_km", "ระยะทาง (กม.)", "number", "มุมบนซ้ายของแผงเส้นทาง"),
    KeyField("service_type", "ประเภทบริการ", "choice", "ชิปใต้แผนที่ · รถยนต์ทุกแบบ = Standard Car",
             ("Saver Bike", "Standard Bike", "Standard Car"), car_is_standard),
    KeyField("payment_method", "การจ่ายเงิน", "choice", "ชิปซ้ายสุดใต้แผนที่",
             ("CASH", "GRAB PAY", "QR PAY")),
    KeyField("net_earnings", "คุณได้รับ", "number", "ตัวเลขบนสุดของจอขวา"),
    KeyField("base_fare", "ค่าโดยสารพื้นฐาน", "number", "ในการ์ดรายได้ · การ์ดพับอยู่ = ไม่มีในรูป"),
    KeyField("turbo", "Turbo", "number",
             "บรรทัด Turbo/เทอร์โบ ในการ์ดรายได้ · การ์ดกางแต่ไม่มีบรรทัดนี้ = 0 · การ์ดพับ = ไม่มีในรูป"),
)
FIELD: Mapping = {f.key: f for f in FIELDS}


@dataclass(frozen=True)
class KeyFact:
    """One answered field. truth is canonical text; None means not on the picture."""
    trip_id: int
    field: str
    truth: Optional[str]


_Z = 1.959964       # standard deviations either side of the mean that hold 95%


@dataclass(frozen=True)
class Tally:
    """One field's count. Two questions stay apart: was the reader right when the fact is on the
    picture (right / wrong), and what did the row hold when it is not (blank / filled)."""
    right: int = 0
    wrong: int = 0
    missed: int = 0             # of the wrong ones: the row was empty though the picture shows it
    absent_blank: int = 0
    absent_filled: int = 0      # not on the picture, yet the row holds a value: a prefix, a rule, a guess

    @property
    def rate(self) -> Optional[float]:
        seen = self.right + self.wrong
        return self.right / seen if seen else None

    def interval(self) -> Optional[tuple]:
        """The 95% Wilson interval (low, high) of rate. A hundred slips out of four thousand is a
        small sample, and 100% of them must not read as proof."""
        n = self.right + self.wrong
        if not n:
            return None
        p = self.right / n
        centre = p + _Z * _Z / (2 * n)
        spread = _Z * math.sqrt(p * (1 - p) / n + _Z * _Z / (4 * n * n))
        scale = 1 + _Z * _Z / n
        # the interval holds the rate by construction; rounding at 0% and 100% must not undo that
        return max(0.0, min(p, (centre - spread) / scale)), min(1.0, max(p, (centre + spread) / scale))

    def public(self) -> dict:
        low, high = self.interval() or (None, None)
        return {"right": self.right, "wrong": self.wrong, "missed": self.missed,
                "absent_blank": self.absent_blank, "absent_filled": self.absent_filled,
                "rate": self.rate, "low": low, "high": high}


def verdict(truth: Optional[str], value: Optional[str]) -> str:
    """right | wrong | absent_blank | absent_filled: the one place a truth meets a value. Both are
    canonical text or None. An empty value against a printed truth is wrong."""
    if truth is None:
        return "absent_blank" if value is None else "absent_filled"
    return "right" if truth == value else "wrong"


def tally(pairs: Iterable) -> dict:
    """Pairs of (KeyFact, value) -> {field key: Tally}, every field of FIELDS present. `value` is
    the canonical text the reader produced for that fact, or None for empty."""
    count = {f.key: dict(right=0, wrong=0, missed=0, absent_blank=0, absent_filled=0) for f in FIELDS}
    for fact, value in pairs:
        said = verdict(fact.truth, value)
        count[fact.field][said] += 1
        if said == "wrong" and value is None:
            count[fact.field]["missed"] += 1
    return {key: Tally(**c) for key, c in count.items()}


_RANK_MULT, _RANK_MOD = 2654435761, 4294967296


def rank(trip_id: int) -> int:
    """The trip's fixed place in the checking order. Slips are handed out in ascending rank among
    a week's eligible trips, and the rank depends on nothing but the id. So the slips checked so
    far are a random sample of the week however many were done, stopping and resuming needs no
    stored sample, and a trip that arrives late takes its own place instead of being left out.

    Never change the two constants: every week checked so far would stop being a prefix."""
    return (trip_id * _RANK_MULT) % _RANK_MOD


def _rank_sql():
    """rank() as a column expression, so the next slip is one single-row query on both engines."""
    return (cast(db.trips.c.id, BigInteger) * literal_column(str(_RANK_MULT))) % literal_column(str(_RANK_MOD))


@dataclass(frozen=True)
class Checked:
    """A whole slip answered: exactly one KeyFact per entry of FIELDS, every truth canonical.
    parse_answer makes that so and everything after relies on it."""
    trip_id: int
    facts: tuple
    seconds: Optional[int] = None


@dataclass(frozen=True)
class NoPicture:
    """The person could not see the slip. Recorded, counted, not offered again."""
    trip_id: int


Answer = Union[Checked, NoPicture]


class BadAnswer(ValueError):
    """The body is not a complete, valid answer. Carries the Thai message for the person."""


class NotHandedOut(Exception):
    """An answer for a trip the key never handed to anyone. This is what keeps the key a sample:
    nobody can add a hand-picked trip through the page."""


_INCOMPLETE = "ส่งคำตอบมาไม่ครบทุกช่อง"
MAX_SECONDS = 600
_MAX_TRUTH = 64


def parse_answer(body) -> Answer:
    """The only place a request body becomes an Answer.

        {"trip_id": 5, "no_picture": true}                                    -> NoPicture
        {"trip_id": 5, "facts": {field: text}, "absent": [field], "seconds"}  -> Checked

    facts and absent together must name every field exactly once. An empty truth is refused,
    never read as absent: absent is said out loud or not at all."""
    if not isinstance(body, Mapping) or type(body.get("trip_id")) is not int:
        raise BadAnswer(_INCOMPLETE)
    trip_id = body["trip_id"]
    if body.get("no_picture") is True:
        return NoPicture(trip_id)
    facts, absent = body.get("facts") or {}, body.get("absent") or []
    if not isinstance(facts, Mapping) or not isinstance(absent, list):
        raise BadAnswer(_INCOMPLETE)
    if sorted(str(name) for name in [*facts, *absent]) != sorted(FIELD):
        raise BadAnswer(_INCOMPLETE)
    out = []
    for f in FIELDS:
        truth = None
        if f.key not in absent:
            value = facts[f.key]
            try:
                if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                    raise ValueError(value)
                truth = f.canon(value)
            except ValueError:
                truth = None
            if truth is None or len(truth) > _MAX_TRUTH:
                raise BadAnswer(f"ค่าของช่อง {f.label} ไม่ถูกต้อง")
        out.append(KeyFact(trip_id, f.key, truth))
    return Checked(trip_id, tuple(out), _seconds(body.get("seconds")))


def _seconds(value) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    return min(int(value), MAX_SECONDS)


@dataclass(frozen=True)
class Picture:
    drive_id: Optional[str]     # for the Drive thumbnail, loaded by the viewer's own browser
    fallback: str               # the server's copy
    open: Optional[str]         # the Drive view link


@dataclass(frozen=True)
class Slip:
    """One trip handed to a person: its picture(s) and what the row holds per field, canonical."""
    trip_id: int
    pictures: tuple             # 1, or 2 when a lower half was merged in
    shown: Mapping              # field key -> canonical text or None, for every entry of FIELDS


@dataclass(frozen=True)
class Progress:
    eligible: int       # auto-approved trips of the week
    checked: int
    no_picture: int


@dataclass(frozen=True)
class Turn:
    slip: Optional[Slip]        # None: nothing left to hand out in this week right now
    progress: Progress


ALL = "all"
CLAIM_MINUTES = 20
_CLAIM_TRIES = 5
_TRIPS = db.trips.join(db.jobs, db.jobs.c.id == db.trips.c.job_id)
_DRIVE_ID = re.compile(r"/d/([\w-]+)|[?&]id=([\w-]+)")


# W46, the first week after the project restarted (Fiat 2026-11-27). Older weeks' pictures may
# have left Drive, so they are neither listed nor counted in "all".
FIRST_WEEK = "2026-11-09"


def _eligible(week: str):
    """The population the key samples: rows the ingest round approved with nobody looking."""
    t = db.trips.c
    rows = [t.status == "done", t.committed == 1, t.auto_approved == 1, db.jobs.c.date_from >= FIRST_WEEK]
    if week != ALL:
        rows.append(db.jobs.c.date_from == week)
    return and_(*rows)


def weeks() -> list:
    """[{date_from, label, closed}] newest first: every week from FIRST_WEEK that has a job. A
    closed week is listed like any other, because checking writes nothing to the week."""
    from ingest import week_label
    with db.engine.begin() as c:
        found = c.execute(select(func.distinct(db.jobs.c.date_from))
                          .where(db.jobs.c.date_from >= FIRST_WEEK)).scalars().all()
    shut = db.closed_weeks()
    return [{"date_from": w, "label": week_label(w), "closed": w in shut}
            for w in sorted({w for w in found if w}, reverse=True)]


def turn(week: str, checker: str, answer: Optional[Answer] = None) -> Turn:
    """The check loop's one operation: store the answer, if any, then hand this checker the slip
    to look at now.

    Sending the same answer again stores the same facts and returns the same slip, because a
    checker's own open claim is always handed back first.

    Raises LookupError for a week with no job, NotHandedOut for an answer to a trip the key never
    handed out."""
    if week not in {w["date_from"] for w in weeks()}:
        raise LookupError(week)
    if answer is not None:
        _record(answer, checker)
    return Turn(_claim_next(week, checker), _progress(week))


def _row_canon(field: KeyField, value) -> Optional[str]:
    """What the row holds, canonical. A stored value the kind cannot hold stays as its own text:
    it is what the row holds, and it will never equal a truth."""
    try:
        return field.canon(value)
    except ValueError:
        return str(value).strip()


def _record(answer: Answer, checker: str) -> None:
    """One transaction. The trip row is read here, for what it held and who read it, and never
    written. Answering a slip again replaces the earlier answer; the action log keeps both."""
    s, k, t = db.key_slips.c, db.key_facts.c, db.trips.c
    now = db._now()
    with db.engine.begin() as c:
        row = c.execute(select(t.model, t.prompt_version, *[t[f.key] for f in FIELDS])
                        .select_from(db.trips.join(db.key_slips, s.trip_id == t.id))
                        .where(t.id == answer.trip_id)).mappings().first()
        if row is None:
            raise NotHandedOut(answer.trip_id)
        done = {"checker": checker, "finished_at": now}
        if isinstance(answer, NoPicture):
            c.execute(update(db.key_slips).where(s.trip_id == answer.trip_id)
                      .values(outcome="no_picture", **done))
            return
        for fact in answer.facts:
            held = {"truth": fact.truth, "row_value": _row_canon(FIELD[fact.field], row[fact.field]),
                    "checked_at": now}
            mine = and_(k.trip_id == fact.trip_id, k.field == fact.field)
            if not c.execute(update(db.key_facts).where(mine).values(**held)).rowcount:
                c.execute(insert(db.key_facts).values(trip_id=fact.trip_id, field=fact.field, **held))
        c.execute(update(db.key_slips).where(s.trip_id == answer.trip_id)
                  .values(outcome="checked", model=row["model"], prompt_version=row["prompt_version"],
                          seconds=answer.seconds, **done))


def _claim_next(week: str, checker: str) -> Optional[Slip]:
    """Hand out the lowest-ranked eligible trip of the week that nobody holds. No locks: the claim
    is a compare-and-swap on key_slips, and whoever loses it picks again."""
    t, s = db.trips.c, db.key_slips.c
    for _ in range(_CLAIM_TRIES):
        now = db._now()
        expiry = (datetime.fromisoformat(now) - timedelta(minutes=CLAIM_MINUTES)).isoformat(timespec="seconds")
        try:
            with db.engine.begin() as c:
                mine = c.execute(
                    select(t.id).select_from(_TRIPS.join(db.key_slips, s.trip_id == t.id))
                    .where(_eligible(week), s.checker == checker, s.outcome.is_(None), s.claimed_at >= expiry)
                    .order_by(_rank_sql()).limit(1)).scalar()
                if mine is not None:
                    return _slip(c, mine)
                free = c.execute(
                    select(t.id, s.checker, s.claimed_at)
                    .select_from(_TRIPS.outerjoin(db.key_slips, s.trip_id == t.id))
                    .where(_eligible(week),
                           or_(s.trip_id.is_(None), and_(s.outcome.is_(None), s.claimed_at < expiry)))
                    .order_by(_rank_sql()).limit(1)).first()
                if free is None:
                    return None
                if free.checker is None:
                    c.execute(insert(db.key_slips).values(trip_id=free.id, checker=checker, claimed_at=now))
                elif not c.execute(
                        update(db.key_slips)
                        .where(s.trip_id == free.id, s.outcome.is_(None), s.checker == free.checker,
                               s.claimed_at == free.claimed_at)
                        .values(checker=checker, claimed_at=now)).rowcount:
                    continue
                return _slip(c, free.id)
        except IntegrityError:
            continue
    return None


def _slip(c, trip_id: int) -> Slip:
    t = db.trips.c
    row = c.execute(select(t.source_url, *[t[f.key] for f in FIELDS]).where(t.id == trip_id)).mappings().one()
    lower = c.execute(select(t.source_url).where(t.merged_into == trip_id).order_by(t.id).limit(1)).first()
    urls = [row["source_url"]] + ([lower[0]] if lower else [])
    return Slip(trip_id, tuple(_picture(trip_id, part, url) for part, url in enumerate(urls, 1)),
                {f.key: _row_canon(f, row[f.key]) for f in FIELDS})


def _picture(trip_id: int, part: int, url: Optional[str]) -> Picture:
    found = _DRIVE_ID.search(url or "")
    drive_id = (found.group(1) or found.group(2)) if found else None
    return Picture(drive_id, f"/api/trips/{trip_id}/image?part={part}",
                   f"https://drive.google.com/file/d/{drive_id}/view" if drive_id else None)


def _progress(week: str) -> Progress:
    s = db.key_slips.c
    with db.engine.begin() as c:
        eligible = c.execute(select(func.count()).select_from(_TRIPS).where(_eligible(week))).scalar()
        done = dict(c.execute(
            select(s.outcome, func.count())
            .select_from(_TRIPS.join(db.key_slips, s.trip_id == db.trips.c.id))
            .where(_eligible(week), s.outcome.isnot(None)).group_by(s.outcome)).tuples().all())
    return Progress(eligible, done.get("checked", 0), done.get("no_picture", 0))


_MISSES = 200


def report(week: str = "") -> dict:
    """How far the check of one week got and how often each field was read right. week '' is the
    newest week, 'all' is every week together. Raises LookupError for a week with no job.

    A slip is grouped under the reader its key_slips row names, not the one the trip row names
    today. Facts of a field no longer in FIELDS stay stored and are left out."""
    listing = weeks()
    known = {w["date_from"]: w for w in listing}
    week = week or (listing[0]["date_from"] if listing else ALL)
    if week != ALL and week not in known:
        raise LookupError(week)
    s, k, t = db.key_slips.c, db.key_facts.c, db.trips.c
    checked = (db.key_facts.join(db.key_slips, and_(s.trip_id == k.trip_id, s.outcome == "checked"))
               .join(db.trips, t.id == k.trip_id).join(db.jobs, db.jobs.c.id == t.job_id))
    with db.engine.begin() as c:
        rows = c.execute(
            select(k.trip_id, k.field, k.truth, k.row_value, s.model, s.prompt_version, s.seconds,
                   s.finished_at, t.source_url)
            .select_from(checked).where(db.jobs.c.date_from >= FIRST_WEEK,
                                        *([] if week == ALL else [db.jobs.c.date_from == week]))).all()
    rows = [r for r in rows if r.field in FIELD]
    slips = {r.trip_id: r for r in rows}
    wrong = [r for r in rows if verdict(r.truth, r.row_value) == "wrong"]
    readers = {}
    for r in rows:
        readers.setdefault((r.model, r.prompt_version), []).append(r)
    seconds = [r.seconds for r in slips.values() if r.seconds is not None]
    return {
        "week": week, "label": known[week]["label"] if week in known else "ทุกสัปดาห์",
        "closed": week in known and known[week]["closed"], "weeks": listing,
        "progress": asdict(_progress(week)),
        "fields": [f.public() for f in FIELDS],
        "total": {"slips": len(slips), "all_right": len(slips) - len({r.trip_id for r in wrong}),
                  "seconds_per_slip": median(seconds) if seconds else None, "fields": _counted(rows)},
        "by_reader": sorted(
            ({"model": model, "prompt_version": version, "slips": len({r.trip_id for r in read}),
              "fields": _counted(read)} for (model, version), read in readers.items()),
            key=lambda g: (-g["slips"], g["model"] or "", g["prompt_version"] or "")),
        "misses": [{"trip_id": r.trip_id, "field": r.field, "row": r.row_value, "truth": r.truth,
                    "open": _picture(r.trip_id, 1, r.source_url).open}
                   for r in sorted(wrong, key=lambda r: (r.finished_at or "", r.trip_id), reverse=True)[:_MISSES]],
    }


def _counted(rows) -> dict:
    return {key: count.public()
            for key, count in tally((KeyFact(r.trip_id, r.field, r.truth), r.row_value) for r in rows).items()}
