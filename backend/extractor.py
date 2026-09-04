# -*- coding: utf-8 -*-
"""Gemini vision extraction for Grab Driver trip screenshots."""
import json
import re
import time

from google import genai
from google.genai import types

from config import GEMINI_MODEL, GEMINI_THINKING_BUDGET, GEMINI_THINKING_LEVEL, load_api_key

PROVINCE_ENUM = ["BKK", "NBI", "PTE", "SPK", "SKN", "NPT", "CBI", "AYA", "OTHER"]

SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "service_type": types.Schema(
            type=types.Type.STRING,
            description="Vehicle/service chip, e.g. 'Saver Bike', 'Standard Bike', 'Saver Car', 'Standard Car'. Translate Thai names to English service names.",
        ),
        "payment_method": types.Schema(
            type=types.Type.STRING,
            enum=["CASH", "GRAB PAY", "QR PAY", "UNKNOWN"],
            description="'Cash'/'เงินสด'→CASH, 'GrabPay'→GRAB PAY, 'QR'→QR PAY.",
        ),
        "payment_chip_text": types.Schema(
            type=types.Type.STRING, nullable=True,
            description="EXACT text of the left-most chip in the row under the map (e.g. 'GrabPay', 'Cash', 'QR payment', 'เงินสด') copied verbatim. Null if no chip row.",
        ),
        "pickup_text": types.Schema(type=types.Type.STRING, description="Pick-up location text (green dot / first stop)."),
        "dropoff_text": types.Schema(type=types.Type.STRING, description="Drop-off location text (red dot / last stop)."),
        "pickup_province": types.Schema(
            type=types.Type.STRING, enum=PROVINCE_ENUM,
            description="Province of pick-up from address text: กรุงเทพ→BKK, นนทบุรี→NBI, ปทุมธานี→PTE, สมุทรปราการ→SPK, สมุทรสาคร→SKN, นครปฐม→NPT, ชลบุรี→CBI, อยุธยา→AYA. Unclear→best guess from district names; unknown→OTHER.",
        ),
        "dropoff_province": types.Schema(
            type=types.Type.STRING, enum=PROVINCE_ENUM,
            description="Province of drop-off, same coding as pickup_province.",
        ),
        "distance_km": types.Schema(type=types.Type.NUMBER, description="Trip distance in km as printed (e.g. 10.79)."),
        "duration_mins": types.Schema(type=types.Type.NUMBER, nullable=True, description="Duration in minutes if printed (e.g. '28 นาที'), else null."),
        "net_earnings": types.Schema(type=types.Type.NUMBER, description="ยอดรายได้สุทธิ / รายได้จากรอบขับ / คุณได้รับ — driver's net earnings in THB."),
        "base_fare": types.Schema(type=types.Type.NUMBER, description="ค่าโดยสารพื้นฐาน in THB."),
        "net_earnings_left_panel": types.Schema(
            type=types.Type.NUMBER, nullable=True,
            description="The 'คุณได้รับ' amount on the LEFT screen (under the payment chips), if that screen is present. Null if only one screen.",
        ),
        "passenger_total": types.Schema(
            type=types.Type.NUMBER, nullable=True,
            description=(
                "The passenger's FARE for this trip - the figure Grab charges its commission on. "
                "Two app versions print it differently. "
                "NEW screen: the bold 'รวมค่าโดยสารของผู้โดยสาร' TOTAL at the bottom of the "
                "'ค่าโดยสารของผู้โดยสารทั้งหมด' section (NOT the 'ยอดที่ผู้โดยสารชำระ' sub-line above it). "
                "OLD screen: the 'ค่าโดยสารของผู้โดยสาร' line INSIDE the 'ค่าบริการที่แกร็บได้รับ' card - "
                "the same figure as 'รวมยอดค่าโดยสาร', the FIRST line of the 'ค่าธรรมเนียมของผู้โดยสาร' card. "
                "NEVER report the old screen's 'ค่าธรรมเนียมของผู้โดยสาร' Total: that receipt total adds the "
                "app fee, tip, tolls and international fee on top of the fare and is a different number. "
                "Null if no such figure is visible."
            ),
        ),
        "passenger_paid": types.Schema(
            type=types.Type.NUMBER, nullable=True,
            description="The 'ยอดที่ผู้โดยสารชำระ' sub-line (first line inside the 'ค่าโดยสารของผู้โดยสารทั้งหมด' section on the NEW screen) — what the passenger actually paid, BEFORE the app fee / discount lines. The OLD screen has no such line: report null there, do not put the fare here.",
        ),
        "grab_commission": types.Schema(
            type=types.Type.NUMBER, nullable=True,
            description="'ค่าบริการที่แกร็บได้รับ' — Grab's cut in THB. Null if collapsed/not shown.",
        ),
        "booking_code": types.Schema(
            type=types.Type.STRING, nullable=True,
            description="รหัสการจอง booking code, ~15-16 chars like 'A-9L4WFXMGXXXFAV', usually ending 'AV'. On screen it often WRAPS onto a second line — read BOTH lines and join them with no space; never stop at the end of the first line. Null if not visible.",
        ),
        "pickup_district": types.Schema(
            type=types.Type.STRING, nullable=True,
            description="District (เขต/อำเภอ) of the PICK-UP, parsed from its address text. ALWAYS in Thai script even when the address is printed in English (e.g. 'Phra Khanong'→'พระโขนง', 'Watthana'→'วัฒนา'). No เขต/อำเภอ prefix. Null if not determinable.",
        ),
        "dropoff_district": types.Schema(
            type=types.Type.STRING, nullable=True,
            description="District (เขต/อำเภอ) of the DROP-OFF, same rules as pickup_district — always Thai script.",
        ),
        "surge": types.Schema(
            type=types.Type.BOOLEAN,
            description="true if a surge indicator is shown (e.g. 'Higher due to surge' badge under the earnings), else false.",
        ),
        "queue_type": types.Schema(
            type=types.Type.STRING, nullable=True,
            description="Text of any EXTRA chip in the chip row beyond the payment and service chips, e.g. 'ไฮบริด'. Null if none.",
        ),
        "num_stops": types.Schema(
            type=types.Type.INTEGER, nullable=True,
            description="Number of route stop points listed above the map (pickup + all drop-offs). 2 for a normal trip, 3+ for multi-stop. Null if the route list is not shown.",
        ),
        "app_fee": types.Schema(
            type=types.Type.NUMBER, nullable=True,
            description="'ค่าธรรมเนียมเรียกใช้บริการ' / 'ค่าธรรมเนียมการใช้แอป' line in the passenger fare breakdown, exactly as printed (often negative, e.g. -1). Null if not shown.",
        ),
        "other_adjustments": types.Schema(
            type=types.Type.NUMBER, nullable=True,
            description="'ส่วนอื่นๆ' / 'ส่วนลด' line in the passenger fare breakdown, as printed. Null if not shown.",
        ),
        "fare_refund": types.Schema(
            type=types.Type.NUMBER, nullable=True,
            description="'เงินคืนค่าโดยสาร' amount if shown anywhere on either screen. Null if not shown.",
        ),
        "bonus": types.Schema(type=types.Type.NUMBER, description="โบนัส if shown, else 0."),
        "tip": types.Schema(type=types.Type.NUMBER, description="'ค่าทิป' inside the 'รายได้เพิ่มเติมที่ไม่หักค่าธรรมเนียม' section (driver's tip income). 0 if not shown. Ignore the negative 'ค่าทิป' line in the passenger section."),
        "intl_fee": types.Schema(type=types.Type.NUMBER, description="'ค่าธุรกรรมต่างประเทศ' line in the passenger fare breakdown, as an absolute number (e.g. -1 -> 1). 0 if not shown."),
        "turbo": types.Schema(type=types.Type.NUMBER, description="Turbo / เทอร์โบ incentive if shown, else 0."),
        "tolls": types.Schema(type=types.Type.NUMBER, description="ค่าทางด่วน / reimbursements if shown, else 0."),
        "screen_time": types.Schema(type=types.Type.STRING, nullable=True, description="Clock in phone status bar, HH:MM, if readable."),
        "confidence_note": types.Schema(type=types.Type.STRING, nullable=True, description="Anything ambiguous/unreadable, in Thai, else null."),
        "kind": types.Schema(
            type=types.Type.STRING, enum=["full", "top", "bottom"],
            description="Which part of the trip screen this image shows. 'top' = route/map/booking code visible but the 'ค่าโดยสารของผู้โดยสารทั้งหมด' section is NOT; 'bottom' = no route/map/booking code, starts at or below 'คุณได้รับ' and shows the fare breakdown; 'full' = both the route and the passenger-fare section are visible (one long or stitched image).",
        ),
    },
    required=["net_earnings", "kind"],
)

PROMPT = """You are reading a screenshot from the Grab Driver app (Thai UI). The image may contain
one or two phone screens side by side showing the SAME single trip (left: route/map/payment,
right: earnings breakdown).

Riders often send ONE trip as TWO separate screenshots (a top half and a bottom half); you may
be given only one half. Report kind=top/bottom/full and fill ONLY what is visible — leave every
field you cannot see as null (never guess a route, booking code, payment chip or passenger total
that is not in the image). net_earnings ('คุณได้รับ') appears on both halves and is always visible.

Extract the trip data into the JSON schema. Rules:
- Amounts are Thai Baht; strip the ฿ symbol. The ฿ glyph is a CURRENCY SYMBOL, not a
  digit — '฿47' is 47 (never 847), '฿51' is 51 (never 851).
- The phone status-bar clock (screen_time): use the LEFT screen's clock; only use the
  right screen's if there is no left screen.
- 'ยอดรายได้สุทธิ' or 'รายได้จากรอบขับ' or 'คุณได้รับ' = net_earnings.
- 'ค่าโดยสารพื้นฐาน' = base_fare. Do NOT confuse it with 'ค่าโดยสารของผู้โดยสาร'
  (passenger total → passenger_total) or 'ค่าบริการที่แกร็บได้รับ' (Grab's cut → grab_commission).
- Older app versions print TWO passenger cards. 'ค่าบริการที่แกร็บได้รับ' lists
  'ค่าโดยสารของผู้โดยสาร' / 'รายได้จากรอบขับ' / the cut — that first line IS passenger_total.
  'ค่าธรรมเนียมของผู้โดยสาร' below it repeats the fare as 'รวมยอดค่าโดยสาร' and then ADDS the app
  fee, tip, tolls and international fee into its own bold 'Total'. That Total is the receipt, not
  the fare: never report it as passenger_total. The identity that always holds is
  passenger_total = รายได้จากรอบขับ + ค่าบริการที่แกร็บได้รับ.
- net_earnings comes from the RIGHT screen (or the only screen). If a LEFT screen also
  shows 'คุณได้รับ ฿X', report that separately as net_earnings_left_panel — copy each
  screen's number as printed even if they differ; do not reconcile them yourself.
- payment_method comes from the chip row under the map — the left-most chip:
  'GrabPay' → GRAB PAY, 'QR payment' → QR PAY, 'Cash'/'เงินสด' → CASH.
  Read the chip text exactly as printed; never guess CASH as a default.
- 'ค่าทิป' in the driver's extra-income section is income (tip); 'รวมรายได้เพิ่มเติมที่ไม่หักค่าธรรมเนียม'
  = bonus + turbo + tip. The driver's 'คุณได้รับ' = ค่าโดยสารพื้นฐาน + that extra income.
- distance_km is printed at the TOP-LEFT of the route panel, above the pickup point
  (e.g. '10.79 km' or '4.73 กม.'). It is never 0 — if you can't see it, look again at
  the very top-left corner of the image.
"""

_client = None


def client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=load_api_key())
    return _client


def _n(x):
    return x if isinstance(x, (int, float)) else None


def receipt_extras(data: dict) -> float:
    """What the old screen's 'ค่าธรรมเนียมของผู้โดยสาร' card adds on top of the fare. The app fee
    counts only when printed as a POSITIVE charge — the new screen prints it negative inside the
    fare itself, where it is part of the total and must not be subtracted."""
    fee = _n(data.get("app_fee")) or 0
    return ((fee if fee > 0 else 0) + (_n(data.get("tip")) or 0)
            + (_n(data.get("tolls")) or 0) + (_n(data.get("intl_fee")) or 0))


def implausible(passenger_total, base_fare) -> bool:
    """Grab's cut tops out around 20-25% of the fare (Standard Car is the dearest service and
    sits at 20%). A passenger fare more than 35% above the driver's base fare is not a rate
    Grab charges — something else got added to it."""
    return base_fare is not None and base_fare > 0 and passenger_total > base_fare * 1.35


def fix_passenger_total(data: dict) -> dict:
    """Keep passenger_total on the FARE, never on the receipt total.

    The pre-2026 trip screen prints the fare twice: once in the 'ค่าบริการที่แกร็บได้รับ' card
    (fare = driver's round income + Grab's cut) and once at the top of the
    'ค่าธรรมเนียมของผู้โดยสาร' card, which then adds the app fee, tip, tolls and international fee
    into a bold Total. Reading that Total as the passenger fare overstated 43 rows across
    W33-W35 by up to ฿235 — the customer checks this column, so a model slip here is expensive.

    Only corrects when the arithmetic proves the extras were added; an unexplained disagreement
    is left alone rather than replaced with a guess. Mutates and returns data.
    """
    pt, paid, base = _n(data.get("passenger_total")), _n(data.get("passenger_paid")), _n(data.get("base_fare"))
    if pt is None:
        return data
    extras = receipt_extras(data)
    fixed = None
    # the fee card states the fare outright: รายได้จากรอบขับ + ค่าบริการที่แกร็บได้รับ
    gc = _n(data.get("grab_commission"))
    card = base + gc if (base is not None and gc is not None and gc >= 0) else None
    if card is not None and abs(pt - card) > 1 and abs((pt - card) - extras) <= 1:
        fixed = card
    # Without the cut printed there is no proof, only arithmetic that happens to fit — and the
    # international-fee line sits INSIDE the new screen's fare, where subtracting it would be
    # wrong. So the remaining branches only run when the figure as read is already impossible:
    # Grab's commission does not reach 35% of the fare on any service type.
    elif not implausible(pt, base):
        pass
    # the receipt total minus its extras lands exactly on the paid line
    elif extras > 0 and paid is not None and abs((pt - extras) - paid) <= 1 and abs(pt - paid) > 1:
        fixed = paid
    # nothing to reconcile against at all: accept the subtraction only when it turns that
    # impossible commission into a plausible one. When the cut IS printed the card above
    # already had its say — an unexplained gap stays unexplained.
    elif (card is None and extras > 0 and paid is None
            and base - 1 <= pt - extras <= base * 1.35):
        fixed = pt - extras
    if fixed is None or abs(fixed - pt) <= 1:
        return data
    data["passenger_total"] = fixed
    note = f"แก้ค่าโดยสารผู้โดยสาร {pt:g} → {fixed:g} (หน้าจอเก่าเอายอดรวมที่ผู้โดยสารจ่ายมา)"
    data["confidence_note"] = f"{note} | {data['confidence_note']}" if data.get("confidence_note") else note
    return data


def arithmetic_check(data: dict) -> str:
    """Cross-check extracted numbers against each other: 'pass' | 'fail' | 'no_data'.

    Independent checks using figures printed in the screenshot itself:
    - net = base_fare + bonus + turbo (identity verified against real Admin-sheet data;
      catches the ฿47→847 currency-glyph misread, since base is read separately)
    - both screens show the driver's net -> they must match
    - passenger_total - grab_commission should equal net (±1 for rounding)
    Any failed check wins; pass needs at least one passing check and none failing.
    """
    net = data.get("net_earnings")
    left = data.get("net_earnings_left_panel")
    pt = data.get("passenger_total")
    gc = data.get("grab_commission")
    base = data.get("base_fare")
    # 1) the identity the team's sheet is built on (J = K + M + N) — decides when available
    if net is not None and base is not None:
        comp = base + (data.get("bonus") or 0) + (data.get("turbo") or 0)
        if abs(net - comp) > 1:
            return "fail"
        if left is not None and abs(left - net) > 0.01:
            return "fail"  # two screens disagree on the driver's net
        return "pass"
    # 2) fallbacks when base is not visible (e.g. a lone bottom half)
    if left is not None and net is not None:
        return "pass" if abs(left - net) <= 0.01 else "fail"
    if pt is not None and gc is not None and net is not None:
        # Grab's cut line is unreliable on car trips (insurance/app fee lines) — advisory only
        return "pass" if abs((pt - gc) - net) <= 1 else "no_data"
    return "no_data"


def normalize_time(s):
    """'8:38' -> '08:38'; anything unparseable -> None (admin fills in)."""
    if not s:
        return None
    m = re.match(r"^\s*(\d{1,2})[:.](\d{2})\s*$", str(s))
    if not m:
        return None
    h, mnt = int(m.group(1)), int(m.group(2))
    if h > 23 or mnt > 59:
        return None
    return f"{h:02d}:{mnt:02d}"


CHIP_TO_PAYMENT = [
    ("grabpay", "GRAB PAY"), ("qr", "QR PAY"),
    ("cash", "CASH"), ("เงินสด", "CASH"),
]


def resolve_payment(data: dict) -> str:
    """Prefer the verbatim chip text over the model's enum guess."""
    chip = (data.get("payment_chip_text") or "").strip().lower()
    for key, method in CHIP_TO_PAYMENT:
        if key in chip:
            return method
    return data.get("payment_method") or "UNKNOWN"


def _suspect_fields(data: dict) -> list[str]:
    """Critical numbers that should never be missing/zero on a real trip."""
    bad = []
    must = ("net_earnings",) if data.get("kind") == "bottom" else ("distance_km", "net_earnings", "base_fare")
    for f in must:
        v = data.get(f)
        if v is None or v <= 0:
            bad.append(f)
    # a Grab code is ~15-16 chars — a shorter read means the model stopped at the on-screen
    # line wrap (weakens dedup); retry, but keep the short read if the retry fares no better
    code = (data.get("booking_code") or "").replace(" ", "")
    if code and len(code) < 14:
        bad.append("booking_code")
    return bad


def _schema_without(drop):
    """The same schema minus some properties — output tokens are the expensive half of a read,
    so a field nobody uses is worth measuring before paying for it on every image."""
    if not drop:
        return SCHEMA
    kept = {k: v for k, v in SCHEMA.properties.items() if k not in set(drop)}
    return types.Schema(type=types.Type.OBJECT, properties=kept, required=SCHEMA.required)


def _gen_config(model: str, drop=()) -> types.GenerateContentConfig:
    cfg = dict(response_mime_type="application/json", response_schema=_schema_without(drop),
               temperature=0)
    if "2.5-pro" in model:
        # 2.5 Pro is the one model that cannot switch thinking off — 128 is its floor
        cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=128)
    elif model.startswith("gemini-3"):
        # 3.x: thinking on by default and billed as output — cap it for extraction work
        cfg["thinking_config"] = types.ThinkingConfig(thinking_level=GEMINI_THINKING_LEVEL)
    elif GEMINI_THINKING_BUDGET is not None:
        # 2.5: dynamic thinking by default (~1,000 tokens/image measured) — budget=0 turns it off
        cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=GEMINI_THINKING_BUDGET)
    return types.GenerateContentConfig(**cfg)


def _call_gemini(img, model: str = None, drop=()) -> dict:
    model = model or GEMINI_MODEL
    resp = client().models.generate_content(
        model=model, contents=[PROMPT, img], config=_gen_config(model, drop),
    )
    data = fix_passenger_total(json.loads(resp.text))
    u = resp.usage_metadata
    data["_usage"] = {
        "model": model,
        "tok_in": u.prompt_token_count or 0,
        "tok_out": u.candidates_token_count or 0,
        "tok_think": u.thoughts_token_count or 0,
    }
    return data


def extract_image(image_bytes: bytes, mime_type: str = "image/jpeg", model: str = None,
                  drop=()) -> dict:
    """Returns extracted dict (with '_usage' token info); raises after 3 failed API attempts.

    A response whose critical numbers are 0/missing counts as a bad read and is
    retried; if it still fails, those fields are blanked and flagged so the
    admin fills them in rather than a silent 0 landing in Excel.
    Token usage accumulates across retries so cost reporting stays honest.
    """
    img = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    last_err = None
    data = None
    spent = {"tok_in": 0, "tok_out": 0, "tok_think": 0}
    for attempt in range(3):
        try:
            data = _call_gemini(img, model, drop)
            for k in spent:
                spent[k] += data["_usage"][k]
            data["_usage"].update(spent)
            if not _suspect_fields(data):
                return data
        except Exception as e:  # noqa: BLE001 - retry any transient API error
            last_err = e
            time.sleep(2 * (attempt + 1))
    if data is None:
        raise RuntimeError(f"Gemini extraction failed: {last_err}")
    bad = _suspect_fields(data)
    notes = []
    if "booking_code" in bad and data.get("booking_code"):
        # a short (line-wrap-truncated) code retried without luck — a partial code still
        # helps a reviewer more than a blank, so keep it but say so
        bad.remove("booking_code")
        notes.append("booking code อาจไม่ครบ (โมเดลอ่านสั้นกว่ารูปแบบปกติ)")
    for f in bad:
        data[f] = None
    if bad:
        notes.append(f"อ่านค่าไม่ได้ ต้องกรอกเอง: {', '.join(bad)}")
    if notes:
        note = " | ".join(notes)
        data["confidence_note"] = f"{note} | {data['confidence_note']}" if data.get("confidence_note") else note
    return data
