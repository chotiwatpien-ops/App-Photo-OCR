# -*- coding: utf-8 -*-
"""A/B: what dropping the two full-address fields actually saves.

The SAME images are read twice — once with the current schema, once without pickup_text and
dropoff_text — so the token difference is the fields themselves, not sampling luck. Also
checks the money fields still agree, since a smaller schema could in principle change how the
model reads the rest.
"""
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "backend")
sys.stdout.reconfigure(encoding="utf-8")
import config                                                   # noqa: E402
import db                                                       # noqa: E402
import extractor                                                # noqa: E402
from drive_client import DriveClient                            # noqa: E402
from sqlalchemy import func, select                             # noqa: E402

MODEL = config.GEMINI_MODEL
DROP = ("pickup_text", "dropoff_text")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 25
PIN, POUT = config.GEMINI_PRICE[MODEL]
THB = config.USD_THB

t, f = db.trips.c, db.ingested_files.c
with db.engine.begin() as c:
    rows = c.execute(
        select(t.id, t.file_name, t.net_earnings, t.base_fare, f.drive_id)
        .select_from(db.trips.join(db.ingested_files, f.trip_id == t.id))
        .where(t.status == "done", t.committed == 1, t.net_earnings.isnot(None))
        .order_by(func.random()).limit(N)).mappings().all()

drive = DriveClient(config.GOOGLE_SERVICE_ACCOUNT, config.DRIVE_OAUTH_TOKEN)
with ThreadPoolExecutor(max_workers=6) as ex:
    imgs = dict(zip([r["id"] for r in rows],
                    ex.map(lambda r: drive.download(r["drive_id"]), rows)))
rows = [r for r in rows if imgs.get(r["id"])]
print(f"อ่านซ้ำรูปเดิม {len(rows)} ใบ สองแบบ ด้วย {MODEL}\n")


def run(drop):
    def one(r):
        try:
            return r, extractor.extract_image(imgs[r["id"]], "image/jpeg", model=MODEL, drop=drop)
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ {r['file_name']}: {str(e)[:90]}")
            return r, None

    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(one, rows))
    tin = tout = tthink = 0
    money_ok = money_total = 0
    out = {}
    for r, d in res:
        if not d:
            continue
        u = d.get("_usage", {})
        tin += u.get("tok_in", 0)
        tout += u.get("tok_out", 0)
        tthink += u.get("tok_think", 0) or 0
        out[r["id"]] = d
        for k in ("net_earnings", "base_fare"):
            if r[k] is None:
                continue
            money_total += 1
            if d.get(k) is not None and abs(float(d[k]) - float(r[k])) <= 0.01:
                money_ok += 1
    n = max(1, len(out))
    baht = ((tin / n) * PIN + ((tout + tthink) / n) * POUT) / 1e6 * THB
    return {"n": n, "in": tin / n, "out": tout / n, "think": tthink / n, "baht": baht,
            "money": 100.0 * money_ok / max(1, money_total), "data": out}


full = run(())
trim = run(DROP)
for label, x in (("เก็บช่องที่อยู่ (แบบปัจจุบัน)", full), ("ตัดช่องที่อยู่ออก", trim)):
    print(f"{label:<32} in {x['in']:7.0f} · out {x['out']:6.0f} · think {x['think']:5.0f} "
          f"· ฿{x['baht']:.4f}/รูป · เงินตรง {x['money']:.0f}%")

d_out = full["out"] - trim["out"]
d_baht = full["baht"] - trim["baht"]
print(f"\nต่างกัน: out ลด {d_out:.0f} โทเคน/รูป → ประหยัด ฿{d_baht:.4f}/รูป "
      f"({100 * d_baht / full['baht']:.1f}%)")
for label, imgs_per_week in (("ต่อสัปดาห์ (1,100 รูป)", 1100), ("ต่อเดือน (4,400 รูป)", 4400),
                             ("ทั้งโปรเจกต์ที่อ่านไปแล้ว (9,297 รูป)", 9297)):
    print(f"  {label:<38} ประหยัด ฿{d_baht * imgs_per_week:,.0f}")
print(f"\nถ้าทำพร้อม Batch API (ครึ่งราคา): ประหยัดเพิ่มอีก ฿{d_baht / 2 * 1100:,.0f}/สัปดาห์ "
      f"— ตัวเลขจะเล็กลงเพราะราคาต่อโทเคนถูกลงครึ่งหนึ่ง")
