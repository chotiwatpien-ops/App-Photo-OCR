# -*- coding: utf-8 -*-
"""PoC: extract Grab rider trip data from screenshots via Gemini structured output.

Usage:  python poc_extract.py
Reads all .jpg in the rider folder, sends each to gemini-2.5-flash with a
JSON schema matching the Admin sheet columns, saves results to poc_results.json.
"""
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from google import genai
from google.genai import types

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).resolve().parent.parent
IMG_DIR = BASE / "01 กิตติพงศ์ 3-9 Aug"
OUT_FILE = Path(__file__).resolve().parent / "poc_results.json"
CONFIG = Path(r"D:\Users\pichotiwat\OneDrive - Central Group\Desktop\Voice_QA Application\csqa_config.json")

MODEL = "gemini-2.5-flash"

SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "service_type": types.Schema(
            type=types.Type.STRING,
            description="Vehicle/service chip shown, e.g. 'Saver Bike', 'Standard Bike', 'Saver Car', 'Standard Car'. Thai 'รถเก๋ง'→Car types. If shown in Thai, translate to the English service name.",
        ),
        "payment_method": types.Schema(
            type=types.Type.STRING,
            enum=["CASH", "GRAB PAY", "QR PAY", "UNKNOWN"],
            description="Payment chip: 'Cash'/'เงินสด'→CASH, 'GrabPay'→GRAB PAY, 'QR'→QR PAY.",
        ),
        "pickup_text": types.Schema(type=types.Type.STRING, description="Pick-up location text (green dot / first stop)."),
        "dropoff_text": types.Schema(type=types.Type.STRING, description="Drop-off location text (red dot / last stop)."),
        "distance_km": types.Schema(type=types.Type.NUMBER, description="Trip distance in km as printed (e.g. 10.79)."),
        "duration_mins": types.Schema(type=types.Type.NUMBER, nullable=True, description="Trip duration in minutes if printed (e.g. '28 นาที'), else null."),
        "net_earnings": types.Schema(type=types.Type.NUMBER, description="ยอดรายได้สุทธิ / รายได้จากรอบขับ / คุณได้รับ — the driver's net earnings in THB."),
        "base_fare": types.Schema(type=types.Type.NUMBER, description="ค่าโดยสารพื้นฐาน in THB."),
        "bonus": types.Schema(type=types.Type.NUMBER, description="โบนัส if shown, else 0."),
        "turbo_incentive": types.Schema(type=types.Type.NUMBER, description="Turbo / เทอร์โบ incentive if shown, else 0."),
        "tolls": types.Schema(type=types.Type.NUMBER, description="ค่าทางด่วน / reimbursements if shown, else 0."),
        "adjustments": types.Schema(type=types.Type.NUMBER, description="ส่วนลด/ค่าธรรมเนียม/ส่วนอื่นๆ adjustments if shown, else 0."),
        "screen_time": types.Schema(type=types.Type.STRING, nullable=True, description="Clock time in the phone status bar, HH:MM, if readable."),
        "booking_code": types.Schema(type=types.Type.STRING, nullable=True, description="Booking code like 'A-9LO9AMUGXEO' if shown."),
        "confidence_note": types.Schema(type=types.Type.STRING, nullable=True, description="Note anything ambiguous or unreadable, else null."),
    },
    required=["service_type", "payment_method", "distance_km", "net_earnings", "base_fare"],
)

PROMPT = """You are reading a screenshot from the Grab Driver app (Thai UI). The image may contain
one or two phone screens side by side showing the SAME single trip (left: route/map/payment,
right: earnings breakdown).

Extract the trip data into the JSON schema. Rules:
- Amounts are Thai Baht; strip the ฿ symbol.
- 'ยอดรายได้สุทธิ' or 'รายได้จากรอบขับ' or 'คุณได้รับ' = net_earnings.
- 'ค่าโดยสารพื้นฐาน' = base_fare. Do NOT confuse with 'ค่าโดยสารของผู้โดยสาร' (what the passenger paid) or 'ค่าบริการที่แกร็บได้รับ' (Grab's cut) — ignore those.
- If both screens show the same field, they must agree; if they conflict, mention it in confidence_note.
- distance_km comes from the printed km value (e.g. '10.79 km' or '14.72 กม.').
"""


def load_key() -> str:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    return cfg["api_key"]


def extract_one(client: genai.Client, path: Path) -> dict:
    img = types.Part.from_bytes(data=path.read_bytes(), mime_type="image/jpeg")
    last_err = None
    for attempt in range(3):
        try:
            resp = client.models.generate_content(
                model=MODEL,
                contents=[PROMPT, img],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=SCHEMA,
                    temperature=0,
                ),
            )
            data = json.loads(resp.text)
            data["_file"] = path.name
            data["_usage"] = {
                "in": resp.usage_metadata.prompt_token_count,
                "out": resp.usage_metadata.candidates_token_count,
            }
            return data
        except Exception as e:  # noqa: BLE001 - PoC: retry on any API hiccup
            last_err = e
            time.sleep(2 * (attempt + 1))
    return {"_file": path.name, "_error": str(last_err)}


def img_number(name: str) -> int:
    m = re.search(r"(\d+)", name)
    return int(m.group(1)) if m else 0


def main() -> None:
    client = genai.Client(api_key=load_key())
    images = sorted(IMG_DIR.glob("*.jpg"), key=lambda p: img_number(p.name))
    print(f"Extracting {len(images)} images with {MODEL} ...")

    results = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(extract_one, client, p): p for p in images}
        for fut in as_completed(futs):
            r = fut.result()
            status = "ERROR " + r.get("_error", "")[:60] if "_error" in r else f"฿{r.get('net_earnings')} / {r.get('distance_km')} km"
            print(f"  {r['_file']}: {status}")
            results.append(r)

    results.sort(key=lambda r: img_number(r["_file"]))
    OUT_FILE.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    elapsed = time.time() - t0
    tokens_in = sum(r.get("_usage", {}).get("in", 0) for r in results)
    tokens_out = sum(r.get("_usage", {}).get("out", 0) for r in results)
    print(f"\nDone in {elapsed:.1f}s → {OUT_FILE.name}")
    print(f"Tokens: {tokens_in} in / {tokens_out} out")
    # gemini-2.5-flash pricing: $0.30/1M input, $2.50/1M output
    cost = tokens_in / 1e6 * 0.30 + tokens_out / 1e6 * 2.50
    print(f"Est. cost: ${cost:.4f} (~฿{cost * 36:.2f}) for {len(images)} images")


if __name__ == "__main__":
    main()
