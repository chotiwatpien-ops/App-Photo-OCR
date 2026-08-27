# -*- coding: utf-8 -*-
"""Model accuracy benchmark against our own approved data.

Samples N committed single-image trips (their values were validated by the checks and a
person/auto approval), re-extracts the original Drive images with a CANDIDATE model, and
reports field-by-field agreement + cost. Writes nothing to the DB.

Usage:  python model_bench.py --model gemini-2.5-flash-lite --sample 100
"""
import argparse
import sys
from concurrent.futures import ThreadPoolExecutor

import config
import db
import extractor
from drive_client import DriveClient
from sqlalchemy import func, select

PRICE = config.GEMINI_PRICE
THB = config.USD_THB
MONEY_TOL = 0.01


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemini-2.5-flash-lite")
    ap.add_argument("--sample", type=int, default=100)
    a = ap.parse_args()

    db.init_db()
    t, f = db.trips.c, db.ingested_files.c
    with db.engine.begin() as c:
        merged_tops = select(t.merged_into).where(t.merged_into.isnot(None))
        rows = c.execute(
            select(t.id, t.file_name, t.net_earnings, t.base_fare, t.distance_km,
                   t.booking_code, f.drive_id)
            .select_from(db.trips.join(db.ingested_files, f.trip_id == t.id))
            .where(t.status == "done", t.committed == 1, t.booking_code.isnot(None),
                   t.net_earnings.isnot(None), t.id.notin_(merged_tops))
            .order_by(func.random()).limit(a.sample)).mappings().all()
    if not rows:
        sys.exit("ไม่มีแถวตัวอย่าง (ต้องมีงานอนุมัติแบบรูปเดี่ยวก่อน)")
    print(f"benchmark {a.model} กับ {len(rows)} รูปที่อนุมัติแล้ว (เฉลย = ค่าที่ผ่านเช็ค+อนุมัติ)\n")

    drive = DriveClient(config.GOOGLE_SERVICE_ACCOUNT, config.DRIVE_OAUTH_TOKEN)

    def one(r):
        try:
            img = drive.download(r["drive_id"])
            data = extractor.extract_image(img, "image/jpeg", model=a.model)
            return r, data, None
        except Exception as e:  # noqa: BLE001
            return r, None, e

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(one, rows))

    fields = [("net_earnings", "เงิน"), ("base_fare", "เงิน"), ("distance_km", "เงิน"),
              ("booking_code", "ข้อความ")]
    ok = {k: 0 for k, _ in fields}
    total = {k: 0 for k, _ in fields}
    tok_in = tok_out = tok_think = 0
    errors = 0
    for r, data, err in results:
        if err is not None:
            errors += 1
            print(f"  ✗ {r['file_name']}: API error {err}")
            continue
        u = data.get("_usage", {})
        tok_in += u.get("tok_in", 0)
        tok_out += u.get("tok_out", 0)
        tok_think += u.get("tok_think", 0) or 0
        for k, kind in fields:
            ref, new = r[k], data.get(k)
            if ref is None:
                continue
            total[k] += 1
            if kind == "เงิน":
                match = new is not None and abs(float(new) - float(ref)) <= MONEY_TOL
            else:
                # whitespace is model noise on both sides — compare compacted
                a_ = "".join(str(new or "").split())
                b_ = "".join(str(ref).split())
                match = a_ == b_
            if match:
                ok[k] += 1
            else:
                print(f"  ✗ {r['file_name']} [{k}]: เฉลย {ref} → {a.model} อ่านได้ {new}")

    n = len(results) - errors
    print(f"\n== ผล {a.model} ({n} รูปสำเร็จ, {errors} error) ==")
    worst = 100.0
    for k, _ in fields:
        pct = 100.0 * ok[k] / total[k] if total[k] else 0
        worst = min(worst, pct)
        print(f"  {k:14s}: {ok[k]}/{total[k]}  ({pct:.1f}%)")
    if n:
        pin, pout = PRICE.get(a.model, (0.30, 2.50))
        cost = ((tok_in / n) * pin + ((tok_out + tok_think) / n) * pout) / 1e6 * THB
        print(f"  tokens เฉลี่ย/รูป: in {tok_in // n} · out {tok_out // n} · think {tok_think // n}")
        print(f"  ต้นทุน ≈ ฿{cost:.3f}/รูป")
    print(f"\nสรุป: ช่องที่แม่นต่ำสุด {worst:.1f}% — "
          + ("ใช้แทนได้" if worst >= 99.5 else "ยังไม่ควรเปลี่ยน (ต่ำกว่าเกณฑ์ 99.5%)"))


if __name__ == "__main__":
    main()
