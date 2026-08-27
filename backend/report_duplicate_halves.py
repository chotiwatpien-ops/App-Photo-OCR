# -*- coding: utf-8 -*-
"""Report only. Approved code-less lower halves that may be a second copy of a trip already
counted: compare every stored field against the suspected twin, and say what each row is.

Nothing is written. Use --fetch to also pull both images off Drive for a visual check.
"""
import argparse
import collections
import os
import re
import sys

sys.path.insert(0, "backend")
sys.stdout.reconfigure(encoding="utf-8")
import db                                                      # noqa: E402
from sqlalchemy import select                                  # noqa: E402

t, j = db.trips.c, db.jobs.c
FIELDS = ("net_earnings", "base_fare", "bonus", "turbo", "passenger_total", "passenger_paid",
          "grab_commission", "distance_km", "duration_mins", "trip_date")


def natural(s):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", s or "")]


def load():
    cols = [t.id, t.job_id, j.driver_name, j.date_from, j.folder_name, t.file_name, t.kind,
            t.status, t.committed, t.merged_into, t.booking_code, t.source_url, t.note]
    cols += [getattr(t, f) for f in FIELDS]
    with db.engine.begin() as c:
        return c.execute(select(*cols).select_from(db.trips.join(db.jobs, j.id == t.job_id))
                         ).mappings().all()


rows = load()
by_job = collections.defaultdict(list)
for r in rows:
    by_job[r["job_id"]].append(r)
has_child = {r["merged_into"] for r in rows if r["merged_into"]}

cases = []
for jid, rs in by_job.items():
    live = [r for r in rs if r["status"] == "done"]
    order = sorted(live, key=lambda r: natural(r["file_name"]))
    pos = {r["id"]: i for i, r in enumerate(order)}
    for r in live:
        if not (r["committed"] and r["kind"] == "bottom" and not r["booking_code"]):
            continue
        twins = [o for o in live if o["id"] != r["id"] and o["committed"]
                 and o["kind"] in ("full", "top") and o["net_earnings"] == r["net_earnings"]]
        if not twins:
            continue
        tw = min(twins, key=lambda o: abs(pos[o["id"]] - pos[r["id"]]))
        def agrees(f):
            a, b = r[f], tw[f]
            if a is None or b is None:
                return None
            if isinstance(a, str) or isinstance(b, str):
                return str(a) == str(b)
            return abs(float(a) - float(b)) < 0.01

        same = [f for f in FIELDS if agrees(f) is True]
        differ = [f for f in FIELDS if agrees(f) is False]
        cases.append({"row": r, "twin": tw, "gap": abs(pos[tw["id"]] - pos[r["id"]]),
                      "same": same, "differ": differ, "twin_complete": tw["id"] in has_child})

cases.sort(key=lambda c: (c["gap"], -len(c["same"])))
print(f"ครึ่งล่างที่อนุมัติแล้วและมีคู่ยอดเท่ากัน: {len(cases)} แถว "
      f"(฿{sum(c['row']['net_earnings'] or 0 for c in cases):,.0f})\n")
for i, c in enumerate(cases, 1):
    r, tw = c["row"], c["twin"]
    verdict = ("คู่มีครึ่งล่างของตัวเองแล้ว → รูปนี้เป็นใบที่สาม (ซ้ำแน่)" if c["twin_complete"]
               else "คู่ยังไม่มีครึ่งล่าง → รูปนี้น่าจะเป็นครึ่งล่างที่รวมไม่ติด (ซ้ำ)")
    if c["gap"] > 10 and len(c["same"]) <= 2:
        verdict = "ห่างกันมากและตรงกันน้อย → น่าจะคนละทริปที่ยอดบังเอิญเท่ากัน"
    print(f"{i:2d}. {r['driver_name']} · {r['date_from']} · job #{r['job_id']}")
    print(f"    {r['file_name']}  ฿{r['net_earnings']:,.0f}   ↔   {tw['file_name']} "
          f"(ห่าง {c['gap']} ไฟล์, โค้ด {tw['booking_code']})")
    print(f"    ตรงกัน: {', '.join(c['same']) or '-'}")
    print(f"    ต่างกัน: {', '.join(c['differ']) or '-'}")
    print(f"    → {verdict}")

# only neighbouring files are worth a human's eyes: a rider's two shots of one trip land next
# to each other. Anything further apart is far more likely two trips that earned the same fare.
sure = [c for c in cases if c["gap"] <= 2]
print(f"\nสรุป: น่าจะซ้ำจริง {len(sure)} แถว = ฿{sum(c['row']['net_earnings'] or 0 for c in sure):,.0f}")

ap = argparse.ArgumentParser()
ap.add_argument("--fetch", action="store_true", help="download both images of each suspected pair")
ap.add_argument("--out", default=".")
a = ap.parse_args()
if a.fetch:
    from drive_client import DriveClient
    from PIL import Image
    import config
    drive = DriveClient(config.GOOGLE_SERVICE_ACCOUNT, config.DRIVE_OAUTH_TOKEN)
    os.makedirs(a.out, exist_ok=True)
    for i, c in enumerate(sure, 1):
        try:
            ims = []
            for r in (c["twin"], c["row"]):
                m = re.search(r"/d/([^/?]+)", r["source_url"] or "")   # .../file/d/<id>/view?usp=...
                fid = m.group(1) if m else (r["source_url"] or "").rstrip("/").split("/")[-1]
                data = drive.download(fid)
                p = os.path.join(a.out, f"pair{i:02d}_{r['kind']}_{r['file_name']}")
                open(p, "wb").write(data)
                im = Image.open(p).convert("RGB")
                im.thumbnail((430, 950))
                ims.append(im)
            w = sum(im.width for im in ims) + 16
            h = max(im.height for im in ims)
            sheet = Image.new("RGB", (w, h), "white")
            x = 0
            for im in ims:
                sheet.paste(im, (x, 0))
                x += im.width + 16
            out = os.path.join(a.out, f"pair{i:02d}_{c['row']['driver_name']}.jpg")
            sheet.save(out, quality=85)
            print(f"  บันทึก {out}")
        except Exception as e:
            print(f"  คู่ที่ {i} โหลดไม่ได้: {type(e).__name__}: {str(e)[:120]}")
