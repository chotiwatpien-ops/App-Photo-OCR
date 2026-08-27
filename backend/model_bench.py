# -*- coding: utf-8 -*-
"""Model accuracy benchmark against our own approved data.

Samples N committed single-image trips (their values were validated by the checks and a
person/auto approval), re-extracts the original Drive images with each CANDIDATE model, and
reports field-by-field agreement + cost. Writes nothing to the DB.

Every candidate reads the SAME images, so the comparison is like-for-like, and the cost
column is computed from the tokens each model actually spent — not from its headline price.

Usage:  python model_bench.py --models gemini-2.5-pro,gemini-3.7-flash --sample 40
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
FIELDS = [("net_earnings", "เงิน"), ("base_fare", "เงิน"), ("distance_km", "เงิน"),
          ("booking_code", "ข้อความ")]


def shrink(data, width):
    """Gemini bills an image by 768x768 tiles: a 869x1882 slip is 2x3 = 6 tiles = 1,548 tokens.
    Narrowing it to 768 makes that 1x3 = 774. Whether the text survives is what --resize tests."""
    if not width or not data:
        return data
    from io import BytesIO

    from PIL import Image
    im = Image.open(BytesIO(data))
    if im.width <= width:
        return data
    im = im.convert("RGB")
    im.thumbnail((width, width * 10), Image.LANCZOS)
    buf = BytesIO()
    im.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def _download(drive, drive_id):
    try:
        return drive.download(drive_id)
    except Exception:  # noqa: BLE001
        return None


def run_model(model, rows, images, workers):
    """One candidate over the shared sample. Returns its scores, tokens and baht per image."""
    def one(r):
        try:
            return r, extractor.extract_image(images[r["id"]], "image/jpeg", model=model), None
        except Exception as e:  # noqa: BLE001
            return r, None, e

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(one, rows))

    ok = {k: 0 for k, _ in FIELDS}
    total = {k: 0 for k, _ in FIELDS}
    tok_in = tok_out = tok_think = errors = 0
    misses = []
    for r, data, err in results:
        if err is not None:
            errors += 1
            if errors <= 2:
                print(f"      ✗ {r['file_name']}: {str(err)[:110]}")
            continue
        u = data.get("_usage", {})
        tok_in += u.get("tok_in", 0)
        tok_out += u.get("tok_out", 0)
        tok_think += u.get("tok_think", 0) or 0
        for k, kind in FIELDS:
            ref, new = r[k], data.get(k)
            if ref is None:
                continue
            total[k] += 1
            if kind == "เงิน":
                match = new is not None and abs(float(new) - float(ref)) <= MONEY_TOL
            else:  # whitespace is model noise on both sides — compare compacted
                match = "".join(str(new or "").split()) == "".join(str(ref).split())
            if match:
                ok[k] += 1
            elif k == "net_earnings":
                misses.append(f"{r['file_name']}: เฉลย {ref} → อ่านได้ {new}")

    n = max(1, len(results) - errors)
    pin, pout = PRICE.get(model, (0.30, 2.50))
    baht = ((tok_in / n) * pin + ((tok_out + tok_think) / n) * pout) / 1e6 * THB

    def pct(k):
        return 100.0 * ok[k] / total[k] if total[k] else 0.0

    print(f"  {model:<26} net {pct('net_earnings'):5.1f}% · base {pct('base_fare'):5.1f}% · "
          f"กม. {pct('distance_km'):5.1f}% · code {pct('booking_code'):5.1f}% · ฿{baht:.4f}/รูป"
          + (f" · error {errors}" if errors else ""))
    for m in misses[:3]:
        print(f"      net พลาด — {m}")
    return {"model": model, "net": pct("net_earnings"), "base": pct("base_fare"),
            "dist": pct("distance_km"), "code": pct("booking_code"), "baht": baht,
            "errors": errors, "tok_in": tok_in // n, "tok_out": tok_out // n,
            "tok_think": tok_think // n}


def run_halves(model, pairs, images, workers):
    """The test the single-image bench cannot do: hand the model each HALF of a split
    screenshot and see whether it still knows which half it is holding. A model that calls an
    upper half a whole screen is the one that broke pairing in production — halves stop
    merging, both rows are approved, and the money is counted twice."""
    jobs = [(p, half) for p in pairs for half in ("top", "bottom")]

    def one(item):
        p, half = item
        try:
            data = extractor.extract_image(images[p[half + "_id"]], "image/jpeg", model=model)
            return p, half, data, None
        except Exception as e:  # noqa: BLE001
            return p, half, None, e

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(one, jobs))

    seen = {"top": 0, "bottom": 0}
    right = {"top": 0, "bottom": 0}
    called_full = 0
    errors = 0
    for p, half, data, err in results:
        if err is not None:
            errors += 1
            continue
        seen[half] += 1
        kind = (data or {}).get("kind")
        if kind == half:
            right[half] += 1
        elif kind == "full":
            called_full += 1
    n_top, n_bot = max(1, seen["top"]), max(1, seen["bottom"])
    out = {"model": model, "top": 100.0 * right["top"] / n_top,
           "bottom": 100.0 * right["bottom"] / n_bot,
           "full": called_full, "seen": seen["top"] + seen["bottom"], "errors": errors}
    print(f"  {model:<26} ครึ่งบนถูก {out['top']:5.1f}% · ครึ่งล่างถูก {out['bottom']:5.1f}% · "
          f"เรียกว่ารูปเต็มผิดๆ {called_full} ใบ" + (f" · error {errors}" if errors else ""))
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemini-2.5-flash-lite")
    ap.add_argument("--models", help="comma-separated candidates, all judged on one shared sample")
    ap.add_argument("--sample", type=int, default=100)
    ap.add_argument("--images", type=int, default=8, help="parallel Gemini calls")
    ap.add_argument("--project", type=int, default=8000, help="image count for the projected total")
    ap.add_argument("--resize", type=int, default=0,
                    help="narrow every image to this width before sending (0 = original)")
    ap.add_argument("--halves", action="store_true",
                    help="judge split screenshots instead: can the model tell a half from a whole?")
    a = ap.parse_args()
    models = [m.strip() for m in (a.models or a.model).split(",") if m.strip()]

    db.init_db()
    t, f = db.trips.c, db.ingested_files.c
    if a.halves:
        return _halves_main(a, models)
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

    drive = DriveClient(config.GOOGLE_SERVICE_ACCOUNT, config.DRIVE_OAUTH_TOKEN)
    images = {}
    with ThreadPoolExecutor(max_workers=a.images) as ex:
        for r, img in zip(rows, ex.map(lambda r: _download(drive, r["drive_id"]), rows)):
            if img:
                images[r["id"]] = shrink(img, a.resize)
    rows = [r for r in rows if r["id"] in images]
    print(f"ตัวอย่างร่วม {len(rows)} รูป (เฉลย = ค่าที่ผ่านเช็คและอนุมัติแล้ว) · "
          f"ผู้เข้าแข่ง {len(models)} ตัว"
          + (f" · ย่อรูปเหลือกว้าง {a.resize}px" if a.resize else " · รูปขนาดเดิม"))
    print()

    table = [run_model(m, rows, images, a.images) for m in models]

    print()
    print("=" * 104)
    print(f"{'โมเดล':<26}{'net':>7}{'base':>7}{'กม.':>7}{'code':>7}"
          f"{'in':>8}{'out':>7}{'think':>7}{'฿/รูป':>9}{'฿/' + str(a.project) + ' รูป':>14}")
    print("-" * 104)
    for x in sorted(table, key=lambda x: x["baht"]):
        print(f"{x['model']:<26}{x['net']:>6.0f}%{x['base']:>6.0f}%{x['dist']:>6.0f}%"
              f"{x['code']:>6.0f}%{x['tok_in']:>8}{x['tok_out']:>7}{x['tok_think']:>7}"
              f"{x['baht']:>9.4f}{x['baht'] * a.project:>14,.0f}")
    print("=" * 104)
    print("net = ยอดที่ไรเดอร์ได้รับ — ช่องเดียวที่ไม่มีกฎไหนซ่อมย้อนหลังให้ได้")
    scored = [x for x in table if x["baht"] > 0]
    if scored:
        cheap = min(scored, key=lambda x: x["baht"])
        print(f"ถูกสุดที่อ่านได้จริง: {cheap['model']} ฿{cheap['baht']:.4f}/รูป "
              f"(net {cheap['net']:.0f}%)")
    for x in table:
        if x["baht"] <= 0:
            print(f"ไม่มีผล: {x['model']} — เรียกไม่สำเร็จทั้ง {x['errors']} ครั้ง")


def _halves_main(a, models):
    """Sample approved trips that were built from a pair of screenshots, and judge each
    candidate on the halves themselves."""
    t, f = db.trips.c, db.ingested_files.c
    half, half_file = db.trips.alias("half"), db.ingested_files.alias("half_file")
    kid, kf = half.c, half_file.c
    with db.engine.begin() as c:
        rows = c.execute(
            select(t.id.label("top_id"), t.file_name.label("top_name"), f.drive_id.label("top_drive"),
                   kid.id.label("bottom_id"), kid.file_name.label("bottom_name"),
                   kf.drive_id.label("bottom_drive"))
            .select_from(db.trips.join(db.ingested_files, f.trip_id == t.id)
                         .join(half, kid.merged_into == t.id)
                         .join(half_file, kf.trip_id == kid.id))
            .where(t.status == "done", t.committed == 1)
            .order_by(func.random()).limit(a.sample)).mappings().all()
    if not rows:
        sys.exit("ไม่มีคู่รูปครึ่งบน/ครึ่งล่างที่อนุมัติแล้วให้ทดสอบ")

    drive = DriveClient(config.GOOGLE_SERVICE_ACCOUNT, config.DRIVE_OAUTH_TOKEN)
    images, pairs = {}, []
    with ThreadPoolExecutor(max_workers=a.images) as ex:
        got = list(ex.map(lambda r: (r, _download(drive, r["top_drive"]),
                                     _download(drive, r["bottom_drive"])), rows))
    for r, top_img, bot_img in got:
        if top_img and bot_img:
            images[r["top_id"]] = shrink(top_img, a.resize)
            images[r["bottom_id"]] = shrink(bot_img, a.resize)
            pairs.append(dict(r))
    print(f"คู่รูปที่ทดสอบ {len(pairs)} คู่ ({len(pairs) * 2} ใบ) · ผู้เข้าแข่ง {len(models)} ตัว")
    print("ถ้าโมเดลอ่านครึ่งบนว่าเป็น 'รูปเต็ม' = จับคู่ไม่ติด = เงินถูกนับสองรอบ")
    print()
    table = [run_halves(m, pairs, images, a.images) for m in models]
    print()
    print("=" * 78)
    print(f"{'โมเดล':<26}{'ครึ่งบนถูก':>13}{'ครึ่งล่างถูก':>15}{'อ่านเป็นรูปเต็ม':>18}")
    print("-" * 78)
    for x in sorted(table, key=lambda x: -(x["top"] + x["bottom"])):
        print(f"{x['model']:<26}{x['top']:>12.0f}%{x['bottom']:>14.0f}%{x['full']:>15} ใบ")
    print("=" * 78)


if __name__ == "__main__":
    main()
