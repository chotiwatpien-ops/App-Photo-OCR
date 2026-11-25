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
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Optional

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
        return max(0.0, (centre - spread) / scale), min(1.0, (centre + spread) / scale)

    def public(self) -> dict:
        low, high = self.interval() or (None, None)
        return {"right": self.right, "wrong": self.wrong, "missed": self.missed,
                "absent_blank": self.absent_blank, "absent_filled": self.absent_filled,
                "rate": self.rate, "low": low, "high": high}


def tally(pairs: Iterable) -> dict:
    """Pairs of (KeyFact, value) -> {field key: Tally}, every field of FIELDS present. `value` is
    the canonical text the reader produced for that fact, or None for empty."""
    count = {f.key: dict(right=0, wrong=0, missed=0, absent_blank=0, absent_filled=0) for f in FIELDS}
    for fact, value in pairs:
        c = count[fact.field]
        if fact.truth is None:
            c["absent_blank" if value is None else "absent_filled"] += 1
        elif fact.truth == value:
            c["right"] += 1
        else:
            c["wrong"] += 1
            c["missed"] += value is None
    return {key: Tally(**c) for key, c in count.items()}


_RANK_MULT, _RANK_MOD = 2654435761, 4294967296


def rank(trip_id: int) -> int:
    """The trip's fixed place in the checking order. Slips are handed out in ascending rank among
    a week's eligible trips, and the rank depends on nothing but the id. So the slips checked so
    far are a random sample of the week however many were done, stopping and resuming needs no
    stored sample, and a trip that arrives late takes its own place instead of being left out.

    Never change the two constants: every week checked so far would stop being a prefix."""
    return (trip_id * _RANK_MULT) % _RANK_MOD
