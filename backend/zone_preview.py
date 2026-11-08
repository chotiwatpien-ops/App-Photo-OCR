# -*- coding: utf-8 -*-
"""What the proposed zone table would do to real trips, before the customer confirms it.

Runs zone_table.csv over the pick-up and drop-off of every approved trip in a date range and
reports how many land in each zone, and which district names the reader gave that the table does
not name (they fall to Other in Bangkok, or blank outside it). Those are the rows worth a second
look in the sheet. Read-only; prints zone and district names and counts, never an address.

    python zone_preview.py --from 2026-08-31 --to 2026-10-04
"""
import argparse
import os
import sys
from collections import Counter

import zones


def preview(rows, table=None):
    """(zone counts, unnamed district counts) over both ends of every row."""
    table = table or zones.load_table()
    names = {n for part in table for n, _z in part}
    got, unnamed = Counter(), Counter()
    for r in rows:
        for end in ("pickup", "dropoff"):
            z = zones.table_zone(r.get(f"{end}_district"), r.get(f"{end}_code"), r.get(f"{end}_text"), table=table)
            got[z or "(นอกพื้นที่ ว่าง)"] += 1
            if z in ("", zones.TABLE_OTHER):
                d = zones._norm(r.get(f"{end}_district")) or "(ตัวอ่านไม่ได้ให้เขต)"
                if d not in names:
                    unnamed[(d, r.get(f"{end}_code") or "-", z or "ว่าง")] += 1
    return got, unnamed


def report(got, unnamed, d_from, d_to, n):
    total = sum(got.values())
    lines = [f"# ลองโซนใหม่กับเที่ยวจริง {d_from} ถึง {d_to}", "",
             f"{n:,} เที่ยว × 2 จุด (รับ/ส่ง) = {total:,} จุด", "",
             "| โซน | จุด | % |", "|---|---:|---:|"]
    lines += [f"| {z} | {c:,} | {c / total:.1%} |" for z, c in got.most_common()]
    lines += ["", "## เขตที่ตัวอ่านให้มา แต่ตารางไม่ได้ระบุ (ตกไป Other หรือว่าง)", "",
              "| เขตที่อ่านได้ | จังหวัด | ได้โซน | จุด |", "|---|---|---|---:|"]
    lines += [f"| {d} | {p} | {z} | {c:,} |" for (d, p, z), c in unnamed.most_common(40)]
    if len(unnamed) > 40:
        lines.append(f"| … อีก {len(unnamed) - 40} ชื่อ | | | {sum(c for _k, c in unnamed.most_common()[40:]):,} |")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="ลองโซนใหม่กับเที่ยวจริง (อ่านอย่างเดียว)")
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    import db
    db.init_db()
    rows = db.query_trips(a.d_from, a.d_to, committed_only=True)
    got, unnamed = preview(rows)
    text = report(got, unnamed, a.d_from, a.d_to, len(rows))
    print(text)
    out = os.environ.get("GITHUB_STEP_SUMMARY")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
