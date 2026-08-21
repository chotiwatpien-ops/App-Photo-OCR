# -*- coding: utf-8 -*-
"""Compare PoC Gemini extractions against admin-keyed rows in Admin A sheet."""
import datetime
import json
import re
import sys
from pathlib import Path

import openpyxl

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
RESULTS = json.loads((HERE / "poc_results.json").read_text(encoding="utf-8"))
XLSX = Path(r"d:\Users\pichotiwat\AppData\Local\Temp\claude\D--Users-pichotiwat-OneDrive---Central-Group-Desktop-App-Photo-OCR\593607dc-ad95-46cf-9669-93e782829ba5\scratchpad\rider_copy.xlsx")


def norm_distance(v):
    """Admin sheet has keying errors where 3.11 became time 03:11:00 — recover the number."""
    if isinstance(v, (datetime.time, datetime.datetime)):
        return float(f"{v.hour}.{v.minute:02d}"), True
    return float(v), False


def norm_service(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


wb = openpyxl.load_workbook(XLSX, data_only=True)
ws = wb["Admin A"]
truth = []
for r in ws.iter_rows(min_row=2, values_only=True):
    if r[0] and "กิตติพงศ์" in str(r[0]):
        dist, was_time = norm_distance(r[7])
        truth.append({
            "date": r[1].strftime("%d-%b"), "service": r[3], "payment": r[4],
            "distance": dist, "dist_keyed_as_time": was_time,
            "net": float(r[9]), "base": float(r[10]),
        })

# match each extraction to the closest unclaimed truth row by (net, distance)
claimed = set()
matches = []
for x in [r for r in RESULTS if "_error" not in r]:
    best, best_score = None, None
    for i, t in enumerate(truth):
        if i in claimed:
            continue
        score = abs(t["net"] - x["net_earnings"]) * 10 + abs(t["distance"] - x["distance_km"])
        if best_score is None or score < best_score:
            best, best_score = i, score
    claimed.add(best)
    matches.append((x, truth[best]))

fields_ok = {"net": 0, "base": 0, "distance": 0, "service": 0, "payment": 0}
n = len(matches)
print(f"{'img':<14}{'Excel(admin)':<34}{'Gemini':<34}diff")
print("-" * 96)
for x, t in matches:
    diffs = []
    if t["net"] == x["net_earnings"]:
        fields_ok["net"] += 1
    else:
        diffs.append(f"net {t['net']}≠{x['net_earnings']}")
    if t["base"] == x["base_fare"]:
        fields_ok["base"] += 1
    else:
        diffs.append(f"base {t['base']}≠{x['base_fare']}")
    if abs(t["distance"] - x["distance_km"]) < 0.005:
        fields_ok["distance"] += 1
    else:
        diffs.append(f"dist {t['distance']}≠{x['distance_km']}" + (" [EXCEL-AS-TIME]" if t["dist_keyed_as_time"] else ""))
    if norm_service(t["service"]) == norm_service(x["service_type"]):
        fields_ok["service"] += 1
    else:
        diffs.append(f"svc {t['service']!r}≠{x['service_type']!r}")
    if str(t["payment"]).strip().upper() == str(x["payment_method"]).strip().upper():
        fields_ok["payment"] += 1
    else:
        diffs.append(f"pay {t['payment']}≠{x['payment_method']}")
    excel_desc = f"{t['date']} {t['payment']} ฿{t['net']:g} {t['distance']:g}km"
    gem_desc = f"{x['payment_method']} ฿{x['net_earnings']:g} {x['distance_km']:g}km"
    print(f"{x['_file']:<14}{excel_desc:<34}{gem_desc:<34}{'; '.join(diffs) or 'OK'}")

unmatched = [t for i, t in enumerate(truth) if i not in claimed]
print(f"\nExcel rows with no image (expected — images 8/16 missing): {len(unmatched)}")
for t in unmatched:
    print(f"  {t['date']} {t['service']} {t['payment']} ฿{t['net']:g} {t['distance']:g}km")

print(f"\nField accuracy over {n} matched images:")
for f, ok in fields_ok.items():
    print(f"  {f:<10}{ok}/{n}  ({ok / n * 100:.0f}%)")
