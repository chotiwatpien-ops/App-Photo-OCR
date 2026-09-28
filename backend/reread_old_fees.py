# -*- coding: utf-8 -*-
"""Fill Passenger Fare for rows read from the OLD Grab screen, and put its fee lines in the signs
the new screen prints — without touching the ride fare, the base fare or the net.

The old screen has no 'ยอดที่ผู้โดยสารชำระ' line, so the reader left passenger_paid empty (W34/W35:
1,216 rows; Ops found 153 in W34 4W, 2026-09-28). But the old screen does print what the passenger
paid: the bold Total of its 'ค่าธรรมเนียมของผู้โดยสาร' card, which starts from the fare
('รวมยอดค่าโดยสาร') and ADDS the app fee, the international fee, the tip and the tolls, taking a
ส่วนลด away. The new screen goes the other way — from the paid figure down to the fare, printing
the app fee NEGATIVE — and Sheet1's columns and Total Commission (= Grab Service Fee − app fee) are
built on the new screen's signs. So an old row with its app fee stored +20 shows Total Commission
฿24 where the same trip on a new screen shows ฿64 (ฉลวย, W34).

For each such row: read that card, turn every line into the new screen's sign, and keep the
reading only when it adds up — Total, less its lines, equals the row's own ride fare. Anything
else is listed for a person and left as it was. The tip is never written (it moves Bonus and the
net): a card with a tip line the row does not already hold does not add up and is listed.

    python reread_old_fees.py --weeks 2026-08-17,2026-08-24                 # report (reads)
    python reread_old_fees.py --weeks 2026-08-17,2026-08-24 --apply
"""
import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from google.genai import types

import config
import db
from reread_passenger import TOL, _f, _file_id, _write, gap, rows_of_week

NUM = lambda d: types.Schema(type=types.Type.NUMBER, nullable=True, description=d)  # noqa: E731
SCHEMA = types.Schema(type=types.Type.OBJECT, properties={
    "screen": types.Schema(type=types.Type.STRING, enum=["old", "new", "none"], description=(
        "'old' if the picture shows the card 'ค่าธรรมเนียมของผู้โดยสาร' (starts with "
        "'รวมยอดค่าโดยสาร', ends with a bold 'Total'); 'new' if it shows 'ยอดที่ผู้โดยสารชำระ' inside "
        "'ค่าโดยสารของผู้โดยสารทั้งหมด'; 'none' if neither card is visible.")),
    "fare": NUM("OLD: 'รวมยอดค่าโดยสาร' (first line of the card). NEW: the bold 'รวมค่าโดยสารของผู้โดยสาร'."),
    "total": NUM("OLD: the bold 'Total' at the bottom of 'ค่าธรรมเนียมของผู้โดยสาร'. NEW: 'ยอดที่ผู้โดยสารชำระ'."),
    "app_fee": NUM("'ค่าธรรมเนียมการใช้แอป' exactly as printed, with its sign (old screen: usually +; new: −)."),
    "intl_fee": NUM("'ค่าธุรกรรมต่างประเทศ' as printed, with its sign."),
    "discount": NUM("'ส่วนลด' as printed, with its sign."),
    "tip": NUM("'ค่าทิป' as printed in THIS card, with its sign."),
    "passenger_tolls": NUM("'ค่าทางด่วน' / 'ค่าผ่านทาง' as printed in THIS card, with its sign."),
    "insurance_fee": NUM("'ค่าธรรมเนียมซื้อประกันภัยการเดินทางเพิ่มเติม' as printed, with its sign."),
    "other": NUM("Sum of any OTHER line in this card (e.g. 'บริจาคเพื่อชดเชยคาร์บอน', 'อื่นๆ'), sign as printed."),
    "grab_fare": NUM("In the card 'ค่าบริการที่แกร็บได้รับ': the line 'ค่าโดยสารของผู้โดยสาร'."),
    "grab_ride": NUM("In the card 'ค่าบริการที่แกร็บได้รับ': the line 'รายได้จากรอบขับ'."),
    "grab_cut": NUM("In the card 'ค่าบริการที่แกร็บได้รับ': its bold total (Grab's cut)."),
}, required=["screen"])

PROMPT = """This is a Grab driver's trip-detail screenshot (Thai). Read ONLY the passenger's fee card.
Amounts are Thai Baht; the ฿ glyph is a currency symbol, not a digit. Copy every line exactly as
printed, keeping its sign (a line printed '-3' is -3; a line printed '20' is 20). Report null for
a line that is not printed. Do not add anything up yourself."""


def _config(model):
    cfg = dict(response_mime_type="application/json", response_schema=SCHEMA, temperature=0)
    if model.startswith("gemini-3"):
        cfg["thinking_config"] = types.ThinkingConfig(thinking_level=config.GEMINI_THINKING_LEVEL)
    return types.GenerateContentConfig(**cfg)


def read_card(image_bytes, model):
    import extractor
    img = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
    last = None
    for attempt in range(3):
        try:
            resp = extractor.client().models.generate_content(model=model, contents=[PROMPT, img],
                                                              config=_config(model))
            data = json.loads(resp.text)
            u = resp.usage_metadata
            data["_usage"] = {"tok_in": u.prompt_token_count or 0, "tok_out": u.candidates_token_count or 0,
                              "tok_think": u.thoughts_token_count or 0}
            return data
        except Exception as e:                                     # noqa: BLE001
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def as_new_screen(card):
    """The card's lines in the new screen's signs: paid first, every line then taken on the way
    down to the fare. The old card runs upward from the fare, so its lines change sign."""
    old = card.get("screen") == "old"
    flip = (lambda v: None if v is None else -_f(v)) if old else (lambda v: v)
    return {
        "passenger_paid": card.get("total"),
        "app_fee": flip(card.get("app_fee")),
        "intl_fee": abs(_f(card.get("intl_fee"))) if card.get("intl_fee") else None,
        "discount": flip(card.get("discount")),
        "insurance_fee": flip(card.get("insurance_fee")),
        "passenger_tolls": flip(card.get("passenger_tolls")),
        "other_adj": flip(card.get("other")),
    }


def grab_card_agrees(t, card):
    """Grab's own card ties the fare to this row: fare − Grab's cut = the base fare the row holds."""
    fare = card.get("grab_fare") if card.get("grab_fare") is not None else card.get("fare")
    if fare is None or t.get("base_fare") is None:
        return False
    if card.get("grab_ride") is not None and abs(_f(card["grab_ride"]) - _f(t["base_fare"])) < TOL:
        return True
    return card.get("grab_cut") is not None and abs(_f(fare) - _f(card["grab_cut"]) - _f(t["base_fare"])) < TOL


def decide(t, card):
    """(fields to write, why). Keeps nothing that does not add up.

    The fare is taken from the slip only where the row has none (the file showed an estimate off
    the base fare) or differs by at most ฿1, and only when Grab's own card ties it to the row's
    base fare. Any other difference means another trip or a misreading, and the row is left."""
    if card.get("screen") == "none" or card.get("total") is None:
        return None, "ไม่เห็นบล็อกค่าธรรมเนียมของผู้โดยสาร"
    fare = card.get("fare") if card.get("fare") is not None else card.get("grab_fare")
    if fare is None:
        return None, "ไม่เห็นค่าโดยสารบนสลิป"
    fields = {}
    have = t.get("passenger_total")
    if have is None or abs(_f(fare) - _f(have)) >= TOL:
        if have is not None and abs(_f(fare) - _f(have)) > 1.01:
            return None, f"ค่าโดยสารบนสลิป {_f(fare):g} ≠ Ride Fare เดิม {_f(have):g}"
        if not grab_card_agrees(t, card):
            return None, f"ค่าโดยสารบนสลิป {_f(fare):g} ผูกกับค่ารอบ {_f(t.get('base_fare')):g} ไม่ได้"
        fields["passenger_total"] = _f(fare)
        t = {**t, "passenger_total": _f(fare)}
    fields.update(as_new_screen(card))
    if card.get("tip") and abs(abs(_f(card["tip"])) - _f(t.get("tip"))) >= TOL:
        return None, f"บล็อกมีค่าทิป {abs(_f(card['tip'])):g} แต่แถวมี {_f(t.get('tip')):g}"
    g = gap({**t, **fields})
    if g is None or abs(g) >= TOL:
        return None, f"อ่านแล้วบวกลบไม่ลงตัว ขาด {g:g}"
    return fields, "ลงตัว"


def rows_needing(week):
    """Delivered rows of a week with no paid figure — the old screen."""
    return [t for t in rows_of_week(week) if t.get("committed") == 1 and t.get("passenger_paid") is None]


def run(weeks, apply=False, limit=None, model=None, workers=16, log=print):
    import extractor
    import roster
    model = model or config.GEMINI_MODEL
    todo = []
    for w in weeks:
        rs = rows_needing(w)
        log(f"สัปดาห์ {w}: ไม่มียอดที่ผู้โดยสารจ่าย {len(rs):,} แถว")
        todo += rs
    if limit is not None and limit < len(todo):
        step = len(todo) / max(limit, 1)
        todo = [todo[int(i * step)] for i in range(limit)]
    drive = roster._drive()

    def one(t):
        # the half that was tracked as the passenger block first, then the row's own picture:
        # W34's test read found no fee card on 16 of 30 tracked halves
        fids = []
        for u in (t.get("_picture"), t.get("source_url")):
            f = _file_id(u)
            if f and f not in fids:
                fids.append(f)
        if not fids:
            return t, None, "ไม่มีรูปบน Drive ให้ตามไปอ่าน"
        card, spent = None, {"tok_in": 0, "tok_out": 0, "tok_think": 0}
        try:
            for fid in fids:
                card = read_card(drive.download(fid), model)
                for k in spent:
                    spent[k] += card["_usage"][k]
                if card.get("screen") != "none" and card.get("total") is not None:
                    break
            card["_usage"] = spent
            return t, card, None
        except Exception as e:                                     # noqa: BLE001
            return t, None, f"อ่านไม่สำเร็จ: {str(e)[:100]}"

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(one, todo))
    took, why, tok, screens = [], {}, {"tok_in": 0, "tok_out": 0, "tok_think": 0}, {}
    for t, card, err in results:
        if card:
            screens[card.get("screen")] = screens.get(card.get("screen"), 0) + 1
            for k in tok:
                tok[k] += card["_usage"][k]
        fields, reason = (None, err) if err else decide(t, card)
        if fields:
            took.append((t, fields, card))
        else:
            why.setdefault(re.sub(r"-?\d[\d.,]*", "…", reason), []).append((t, reason))
    log(f"\nอ่าน {len(todo):,} แถวใน {time.time() - t0:.0f} วิ · จอ {screens} · token เข้า {tok['tok_in']:,} "
        f"ออก {tok['tok_out']:,} คิด {tok['tok_think']:,}")
    log(f"  ✓ ลงตัวและเก็บได้ {len(took):,} แถว")
    for t, f, c in took[:8]:
        log(f"      #{t['id']} {t.get('driver_name') or ''} {t.get('customer_image') or ''}: จ่าย {f['passenger_paid']:g}"
            f" · ค่าแอป {_f(f['app_fee']):g} · ค่าโดยสาร {_f(f.get('passenger_total', t.get('passenger_total'))):g}"
            f"{' (ใหม่ เดิมไม่มี)' if t.get('passenger_total') is None else (' (เดิม ' + format(_f(t['passenger_total']), 'g') + ')' if 'passenger_total' in f else '')} ({c.get('screen')})")
    fare_new = sum(1 for t, f, _c in took if "passenger_total" in f and t.get("passenger_total") is None)
    fare_fix = sum(1 for t, f, _c in took if "passenger_total" in f and t.get("passenger_total") is not None)
    log(f"    Ride Fare ที่เคยเป็นค่าประมาณ ได้ค่าจริง {fare_new:,} · ต่าง ฿1 แก้ตามสลิป {fare_fix:,}")
    left = sum(len(v) for v in why.values())
    log(f"  ✗ ไม่เก็บ ปล่อยไว้ให้คนดู {left:,} แถว")
    for reason, ts in sorted(why.items(), key=lambda kv: -len(kv[1])):
        log(f"    {len(ts):4}  {reason}")
        for t, detail in ts[:6]:
            log(f"          #{t['id']} {t.get('driver_name') or ''} {t.get('customer_image') or ''} — {detail}")
    if apply:
        _write((t["id"], {k: v for k, v in f.items()}) for t, f, _c in took)
        log(f"\n✓ เขียนแล้ว {len(took):,} แถว")
    else:
        log("\n(รายงานอย่างเดียว — ใส่ --apply เพื่อเขียนจริง)")
    return {"read": len(todo), "took": len(took), "left": left, **tok}


def main(argv=None):
    ap = argparse.ArgumentParser(description="เติม Passenger Fare ของสลิปจอเก่า และกลับเครื่องหมายบรรทัดค่าธรรมเนียมให้เหมือนจอใหม่")
    ap.add_argument("--weeks", required=True, help="วันจันทร์ของแต่ละสัปดาห์ คั่นด้วยจุลภาค")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--model", default=None)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    db.init_db()
    run([w.strip() for w in a.weeks.split(",") if w.strip()], apply=a.apply, limit=a.limit, model=a.model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
