# -*- coding: utf-8 -*-
"""Turn the customer's zone sheet into backend/zone_table.csv, the table zones.table_zone reads.

The sheet ("Zone Mapping W46", downloaded as CSV) has one row per area: its name, level, the zone
proposed, and a column where the customer either ticks ✓ or writes the right zone. The customer's
word wins; a tick keeps the proposal; a row still marked "? ต้องเลือก" is left out, so the area
falls to Other (Bangkok) or blank (outside) until somebody decides.

    python zone_table_build.py "Zone Mapping W46.csv"            # writes zone_table.csv
    python zone_table_build.py "Zone Mapping W46.csv" --check    # report only
"""
import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

LEVELS = {"แขวง", "เขต", "อำเภอ", "เมือง"}
# The file shows the team's colours (Fiat, 2026-11-08). Whatever the sheet says, area name, colour
# or Thai colour, comes out as the colour.
COLOUR = {}
for colour, *names in (("Green", "City Center", "เขียว"), ("Grey", "Inner City", "เทา", "Gray"),
                       ("Orange", "Outer Ring", "ส้ม"), ("Pink", "Pattaya", "ชมพู", "พัทยา"),
                       ("Blue", "Other", "น้ำเงิน")):
    for n in (colour, *names):
        COLOUR[n.lower()] = colour
OUT = Path(__file__).with_name("zone_table.csv")


def names_of(cell):
    """'บางเสาธง / บางบ่อ' -> ['บางเสาธง', 'บางบ่อ']; '(...)' notes are dropped. A 'เมือง…' district
    is also matched by the bare province name the reader often gives instead."""
    out = []
    for part in cell.split("/"):
        n = re.sub(r"\(.*?\)", "", part).strip()
        if not n:
            continue
        out.append(n)
        if n.startswith("เมือง") and len(n) > 5:
            out.append(n[len("เมือง"):])
    return out


def build(rows):
    """[(name, level, zone)] from the sheet's rows (dicts keyed by its Thai headers)."""
    table = []
    for r in rows:
        level = (r.get("ระดับ") or "").strip()
        if level not in LEVELS:
            continue
        said = (r.get("ลูกค้ายืนยัน (✓ หรือใส่โซนที่ถูก)") or "").strip()
        zone = said if said and said not in ("✓", "/", "ok", "OK") else (r.get("โซนที่เสนอ") or "").strip()
        if not zone or zone.startswith("?"):
            continue
        zone = COLOUR.get(zone.lower(), zone)
        for n in names_of(r.get("พื้นที่") or ""):
            table.append((n, "แขวง" if level == "แขวง" else "เขต", zone))
    return table


def main(argv=None):
    ap = argparse.ArgumentParser(description="ชีตโซนของลูกค้า -> zone_table.csv")
    ap.add_argument("sheet")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    with open(a.sheet, encoding="utf-8-sig") as fh:
        table = build(csv.DictReader(fh))
    dup = [n for n, k in Counter(n for n, _l, _z in table).items() if k > 1]
    print(f"{len(table)} ชื่อ · " + " · ".join(f"{z} {n}" for z, n in Counter(z for *_r, z in table).most_common()))
    if dup:
        print(f"⚠ ชื่อซ้ำ: {', '.join(dup)}")
    if not a.check:
        with open(OUT, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["name", "level", "zone"])
            w.writerows(table)
        print(f"เขียน {OUT.name} แล้ว")
    return 1 if dup else 0


if __name__ == "__main__":
    sys.exit(main())
