# -*- coding: utf-8 -*-
"""Merge the shards of a chip audit, say what they found, and write it if told to.

The reading is split across parallel jobs because it costs about three seconds a picture and a
week holds several thousand. Each shard reports its own findings and writes them as JSON;
nothing touches the database until every shard has finished, so a shard that dies leaves nothing
half-applied and can just be re-run.

APPLY=true writes the tier corrections. WHEELS=true also writes the wheel corrections, and only
for rows whose chip actually named a vehicle — chips that name none ('Standard | Women driver')
are counted by label and left for Ops, because guessing from 'Standard' alone once put a bike
rider's whole week under 4 W Standard.

    python apply_chip_audit.py shards/*.json
"""
import glob
import json
import os
import sys
from collections import Counter

import db


def load(paths):
    tiers, wheels, unnamed = {}, {}, Counter()
    for p in paths:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        for x in d.get("tiers", []):
            tiers[x["id"]] = x
        for x in d.get("wheels", []):
            wheels[x["id"]] = x
        unnamed.update(d.get("unnamed", {}))
    return tiers, wheels, unnamed


def main(argv):
    paths = [p for a in argv for p in glob.glob(a)]
    if not paths:
        print("✗ ไม่มีไฟล์ผลจากก้อนไหนเลย")
        return 1
    tiers, wheels, unnamed = load(paths)
    print(f"รวมผลจาก {len(paths)} ก้อน")

    print(f"\n=== 1. tier ไม่ตรงกับชิป: {len(tiers)} แถว ===")
    for (o, n), c in Counter((x["old"], x["new"]) for x in tiers.values()).most_common():
        print(f"    {o} → {n}: {c} แถว")

    print(f"\n=== 2. ล้อไม่ตรง (ชิประบุรถชัดเจน): {len(wheels)} แถว ===")
    for (o, n), c in Counter((x["old"], x["new"]) for x in wheels.values()).most_common():
        print(f"    {o} → {n}: {c} แถว")
    for x in list(wheels.values())[:10]:
        print(f"      ชิป {x.get('label')!r} → {x['new']}")

    print(f"\n=== 3. ชิปอ่านออกแต่ไม่ระบุว่ารถอะไร: {sum(unnamed.values())} แถว ===")
    for lab, c in unnamed.most_common(20):
        print(f"    {str(lab):<36}{c:>6} แถว")
    print("  ↑ ป้ายพวกนี้ไม่มีคำว่า bike/car — ให้ Ops ชี้ว่าอันไหนคือรถยนต์ ระบบไม่เดาเอง")

    apply = os.environ.get("APPLY", "").lower() in ("1", "true", "yes")
    do_wheels = os.environ.get("WHEELS", "").lower() in ("1", "true", "yes")
    if not apply:
        print("\n(รายงานอย่างเดียว — ติ๊ก apply เพื่อแก้จริง)")
        return 0

    db.init_db()
    n = 0
    for x in tiers.values():
        note = f"ประเภทตามชิปบนสลิป: {x['new']} (เดิม {x['old']} จากกลุ่มของ job)"
        db.update_trip(x["id"], {"service_type": x["new"], "note": note})
        n += 1
    if do_wheels:
        for x in wheels.values():
            note = f"รถตามชิปบนสลิป ({x.get('label')}): {x['new']} (เดิม {x['old']})"
            db.update_trip(x["id"], {"service_type": x["new"], "note": note})
            n += 1
    else:
        print(f"  (ไม่ได้แก้ล้อ {len(wheels)} แถว — ติ๊ก wheels ถ้าต้องการ)")
    print(f"\nแก้แล้ว {n} แถว — รูปไม่ได้ถูกย้าย (Ops 2026-09-10)")
    print("ขั้นต่อไป: รัน ingest ด้วย xlsx_only เพื่อเขียนไฟล์ส่งลูกค้าใหม่")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
