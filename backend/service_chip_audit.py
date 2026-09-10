# -*- coding: utf-8 -*-
"""What a row says its service was, against the chip printed on its own slip.

service_audit.py asks the folder. That works only while the folder is right, and on 2026-09-10
Ops found rows where it is not. Two different faults, both invisible to a folder check because
the folder is wrong in the same direction as the row:

TIER. WK36-มนันตรา Win20 is a Saver trip whose job was opened under 2 W Standard, whose picture
was therefore filed in 2 W Standard, and whose row reads Standard Bike. Job, folder and row all
agree and all three are wrong — the chip says 'Saver Bike'. The tier came from the job's group,
and a job is one group for a whole week, so a rider who drove both tiers came out as one tier on
every row. normalize_service() stopped doing that on 2026-09-09, but rows written before keep
what they were given, which is most of a delivered workbook.

WHEEL. WK36-ชลิต Home4 is a car sitting in 2 W Standard. Its chip reads 'Standard | Women
driver' — a label naming no vehicle at all, so the reader answers 'wheel unknown' and the job's
group decides. The fix is NOT to guess from it: 'Standard' was once read as meaning a car and it
put a bike rider's whole week under 4 W Standard. So every chip whose label names no vehicle is
counted and listed by label, for Ops to rule on.

Nothing is deleted and no picture is moved (Ops, 2026-09-10). With --apply only service_type
changes, and every changed row keeps a note saying what it was and what the chip said.

    python service_chip_audit.py --from 2026-08-31 --to 2026-09-06
    python service_chip_audit.py --from 2026-08-31 --to 2026-09-06 --apply
    python service_chip_audit.py --from 2026-08-31 --to 2026-09-06 --shard 0/8   (for a matrix)
"""
import argparse
import io
import json
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

import db

TIER_RE = re.compile(r"\b(saver|standard)\b", re.IGNORECASE)
WHEEL_RE = re.compile(r"\b(bike|car)\b", re.IGNORECASE)
ID_RE = re.compile(r"[-\w]{25,}")            # a Drive file id inside a webViewLink
# The chip phrase kept whole, so a label nobody has seen before is counted rather than guessed at.
LABEL_RE = re.compile(r"(saver|standard|justgrab)[a-z ()|.-]{0,26}", re.IGNORECASE)
WHEEL_WORD = {"2W": "Bike", "4W": "Car"}


def chip_label(txt):
    """The chip phrase as the OCR saw it — 'standard bike', 'standardwomen driver'."""
    m = LABEL_RE.search(txt or "")
    return " ".join(m.group(0).lower().split()) if m else None


def tier_of(text):
    m = TIER_RE.search(text or "")
    return m.group(1).capitalize() if m else None


def wheel_of(text):
    m = WHEEL_RE.search(text or "")
    return m.group(1).capitalize() if m else None


def file_id(url):
    m = ID_RE.search(url or "")
    return m.group(0) if m else None


def rows_of_week(d_from, d_to):
    """Every finished row of the week, with the link back to the picture it was read from."""
    jobs = db.jobs_by_week().get((d_from, d_to), [])
    ids = [j["id"] for j in jobs]
    if not ids:
        return [], []
    t = db.trips.c
    with db.engine.begin() as c:
        rows = [dict(r) for r in c.execute(
            select(t.id, t.job_id, t.file_name, t.service_type, t.source_url,
                   t.customer_image, t.status, t.committed, t.note)
            .where(t.job_id.in_(ids), t.status == "done").order_by(t.id)).mappings().all()]
    return jobs, rows


def read_chips(drive, rows, workers=8, log=print):
    """{trip id: (wheel, tier, label)} — read off each row's own picture; failures are absent."""
    import pairing
    from PIL import Image
    out, misses = {}, Counter()

    def one(r):
        fid = file_id(r.get("source_url"))
        if not fid:
            misses["ไม่มีลิงก์รูปใน source_url"] += 1
            return None
        try:
            im = Image.open(io.BytesIO(drive.download(fid))).convert("RGB")
            wheel = tier = txt = None
            for w in (720, 1200):
                txt = pairing._read_text(
                    im.resize((w, int(im.height * w / im.width)), Image.LANCZOS)).lower()
                wheel, tier = pairing.wheels_from_chip(txt), pairing.tier_from_chip(txt)
                if wheel and tier:
                    break
            return r["id"], (wheel, tier, chip_label(txt))
        except Exception as e:                       # noqa: BLE001 — one bad file must not stop the audit
            misses[f"โหลด/อ่านไม่ได้: {str(e)[:40]}"] += 1
            return None

    with ThreadPoolExecutor(workers) as ex:
        for i, got in enumerate(ex.map(one, rows), 1):
            if got:
                out[got[0]] = got[1]
            if i % 200 == 0:
                log(f"    อ่านแล้ว {i}/{len(rows)}")
    for k, n in misses.most_common():
        log(f"  ⚠ {k}: {n} แถว")
    return out


def verdicts(rows, chips):
    """(tier flips, wheel flips, rows whose chip named no vehicle).

    Tier and wheel are ruled on separately because they carry different risk. A tier the chip
    states is taken — 'Saver' is printed or it is not. A wheel is taken only when the chip names
    the vehicle; a chip reading 'Standard | Women driver' names none, and those rows are handed
    back by label for Ops to rule on rather than guessed at."""
    tiers, wheels, unnamed = [], [], []
    for r in rows:
        got = chips.get(r["id"])
        if not got:
            continue
        wheel, tier, label = got
        row_tier, row_wheel = tier_of(r["service_type"]), wheel_of(r["service_type"])
        if not row_tier or not row_wheel:
            continue
        if wheel and WHEEL_WORD[wheel] != row_wheel:
            wheels.append((r, f"{tier or row_tier} {WHEEL_WORD[wheel]}", label))
        elif not wheel:
            unnamed.append((r, label))
        if tier and tier != row_tier:
            tiers.append((r, tier, f"{tier} {row_wheel}"))
    return tiers, wheels, unnamed


def report(jobs, rows, chips, log=print):
    tiers, wheels, unnamed = verdicts(rows, chips)
    name = {j["id"]: j["driver_name"] for j in jobs}
    log(f"\nอ่านชิปได้ {len(chips)} จาก {len(rows)} แถว")
    log("  ชิปบอก tier: " + " · ".join(f"{t or 'อ่านไม่ออก'} {n}"
                                        for t, n in Counter(v[1] for v in chips.values()).most_common()))
    log("  ชิปบอกล้อ: " + " · ".join(f"{w or 'ไม่ระบุรถ'} {n}"
                                      for w, n in Counter(v[0] for v in chips.values()).most_common()))

    log(f"\n=== 1. tier ไม่ตรง: {len(tiers)} แถว ===")
    for (old, new), n in Counter((r["service_type"], new) for r, _t, new in tiers).most_common():
        log(f"    {old} → {new}: {n} แถว")
    jb = Counter(r["job_id"] for r, _t, _n in tiers)
    log(f"  กระจายอยู่ใน {len(jb)} job · มากสุด: " +
        ", ".join(f"{name.get(j, j)} {n}" for j, n in jb.most_common(6)))

    log(f"\n=== 2. ล้อไม่ตรง (ชิประบุรถชัดเจน): {len(wheels)} แถว ===")
    for (old, new), n in Counter((r["service_type"], new) for r, new, _l in wheels).most_common():
        log(f"    {old} → {new}: {n} แถว")
    for r, new, label in wheels[:10]:
        log(f"      {name.get(r['job_id'], '?')} · {r['customer_image']} · ชิป {label!r} → {new}")

    log(f"\n=== 3. ชิปอ่านออกแต่ไม่ระบุว่ารถอะไร: {len(unnamed)} แถว ===")
    lab = Counter(l for _r, l in unnamed)
    for l, n in lab.most_common(15):
        ex = next(r["customer_image"] for r, ll in unnamed if ll == l)
        log(f"    {str(l):<34}{n:>5} แถว   เช่น {ex}")
    log("  ↑ ป้ายพวกนี้ไม่มีคำว่า bike/car — ต้องให้ Ops ชี้ว่าอันไหนคือรถยนต์ ระบบไม่เดาเอง")
    return tiers, wheels, unnamed


def main(argv=None):
    ap = argparse.ArgumentParser(description="ตรวจประเภทงานในแถว เทียบกับชิปบนสลิปของแถวนั้นเอง")
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--apply", action="store_true",
                    help="เขียน service_type ใหม่ตามชิป (tier เท่านั้น ถ้าไม่ใส่ --wheels)")
    ap.add_argument("--wheels", action="store_true",
                    help="แก้ล้อด้วย เฉพาะแถวที่ชิประบุรถชัดเจน")
    ap.add_argument("--limit", type=int, help="อ่านแค่กี่แถว (ไว้ลองก่อน)")
    ap.add_argument("--shard", help="i/n — อ่านเฉพาะส่วนที่ i จาก n ส่วน สำหรับรันขนานหลาย job")
    ap.add_argument("--out", help="เขียนผลดิบเป็น JSON ไว้รวมทีหลัง")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args(argv)
    db.init_db()
    import roster
    drive = roster._drive()

    jobs, rows = rows_of_week(a.d_from, a.d_to)
    if not rows:
        print(f"✗ ไม่มีแถวของ {a.d_from}..{a.d_to}")
        return 1
    if a.shard:
        i, n = (int(x) for x in a.shard.split("/"))
        rows = [r for k, r in enumerate(rows) if k % n == i]
        print(f"ส่วนที่ {i+1}/{n}")
    if a.limit:
        rows = rows[:a.limit]
    print(f"{a.d_from}..{a.d_to}: job {len(jobs)} · แถวที่จะอ่าน {len(rows)}")
    print("  ที่บันทึกไว้ตอนนี้: " + " · ".join(
        f"{k} {v}" for k, v in Counter(r["service_type"] for r in rows).most_common()))

    chips = read_chips(drive, rows, workers=a.workers)
    tiers, wheels, unnamed = report(jobs, rows, chips)

    if a.out:
        payload = {"tiers": [{"id": r["id"], "old": r["service_type"], "new": new}
                             for r, _t, new in tiers],
                   "wheels": [{"id": r["id"], "old": r["service_type"], "new": new, "label": l}
                              for r, new, l in wheels],
                   "unnamed": dict(Counter(l for _r, l in unnamed))}
        with io.open(a.out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        print(f"\nเขียนผลดิบไว้ที่ {a.out}")

    if not a.apply:
        print("\n(รายงานอย่างเดียว — ใส่ --apply เพื่อแก้จริง)")
        return 0

    fixed = 0
    for r, _tier, new in tiers:
        note = f"ประเภทตามชิปบนสลิป: {new} (เดิม {r['service_type']} จากกลุ่มของ job)"
        db.update_trip(r["id"], {"service_type": new,
                                 "note": f"{note} | {r['note']}" if r.get("note") else note})
        fixed += 1
    if a.wheels:
        for r, new, label in wheels:
            note = f"รถตามชิปบนสลิป ({label}): {new} (เดิม {r['service_type']})"
            db.update_trip(r["id"], {"service_type": new,
                                     "note": f"{note} | {r['note']}" if r.get("note") else note})
            fixed += 1
    else:
        print(f"  (ไม่ได้แก้ล้อ {len(wheels)} แถว — ใส่ --wheels ถ้าต้องการ)")
    print(f"\nแก้แล้ว {fixed} แถว — รูปไม่ได้ถูกย้าย (Ops 2026-09-10)")
    print("ต้องเขียนไฟล์ส่งลูกค้าใหม่: ingest.py --xlsx-only")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
