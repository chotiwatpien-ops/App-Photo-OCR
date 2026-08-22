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
            description="The 'รวมค่าโดยสารของผู้โดยสาร' TOTAL line (bold, at the bottom of the 'ค่าโดยสารของผู้โดยสารทั้งหมด' section) — NOT the 'ยอดที่ผู้โดยสารชำระ' sub-line above it. Null if that section is collapsed.",
        ),
        "passenger_paid": types.Schema(
            type=types.Type.NUMBER, nullable=True,
            description="The 'ยอดที่ผู้โดยสารชำระ' sub-line (first line inside the 'ค่าโดยสารของผู้โดยสารทั้งหมด' section) — the amount the passenger actually paid, BEFORE the app fee / discount lines. Null if not visible.",
        ),
        "grab_commission": types.Schema(
            type=types.Type.NUMBER, nullable=True,
            description="'ค่าบริการที่แกร็บได้รับ' — Grab's cut in THB. Null if collapsed/not shown.",
        ),
        "booking_code": types.Schema(
            type=types.Type.STRING, nullable=True,
            description="รหัสการจอง booking code like 'A-9LO9AMUGXEO', printed near the top of the left screen. Null if not visible.",
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
- net_earnings comes from the RIGHT screen (or the only screen). If a LEFT screen also
  shows 'คุณได้รับ ฿X', report that separately as net_earnings_left_panel — copy each
  screen's number as printed even if they differ; do not reconcile them yourself.
- payment_method comes from the chip row under the map — the left-most chip:
  'GrabPay' → GRAB PAY, 'QR payment' → QR PAY, 'Cash'/'เงินสด' → CASH.
  Read the chip text exactly as printed; never guess CASH as a default.
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
    return bad


def _gen_config(model: str) -> types.GenerateContentConfig:
    cfg = dict(response_mime_type="application/json", response_schema=SCHEMA, temperature=0)
    if model.startswith("gemini-3"):
        # 3.x: thinking on by default and billed as output — cap it for extraction work
        cfg["thinking_config"] = types.ThinkingConfig(thinking_level=GEMINI_THINKING_LEVEL)
    elif GEMINI_THINKING_BUDGET is not None:
        # 2.5: dynamic thinking by default (~1,000 tokens/image measured) — budget=0 turns it off
        cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=GEMINI_THINKING_BUDGET)
    return types.GenerateContentConfig(**cfg)


def _call_gemini(img, model: str = None) -> dict:
    model = model or GEMINI_MODEL
    resp = client().models.generate_content(
        model=model, contents=[PROMPT, img], config=_gen_config(model),
    )
    data = json.loads(resp.text)
    u = resp.usage_metadata
    data["_usage"] = {
        "model": model,
        "tok_in": u.prompt_token_count or 0,
        "tok_out": u.candidates_token_count or 0,
        "tok_think": u.thoughts_token_count or 0,
    }
    return data


def extract_image(image_bytes: bytes, mime_type: str = "image/jpeg", model: str = None) -> dict:
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
            data = _call_gemini(img, model)
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
    for f in bad:
        data[f] = None
    note = f"อ่านค่าไม่ได้ ต้องกรอกเอง: {', '.join(bad)}"
    data["confidence_note"] = f"{note} | {data['confidence_note']}" if data.get("confidence_note") else note
    return data
