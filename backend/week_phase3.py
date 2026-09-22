# -*- coding: utf-8 -*-
"""One delivered week, again, in the Phase 3 layout — as a file of its own.

Ops asked for W35 (24–30 Aug) in the layout the customer reads from W38 on (Fiat 2026-09-22:
a separate file; the delivered Rider Trips.xlsx is not touched, and no amount changes). The
passenger block lines are filled in first by reread_passenger.py, which keeps a row's own paid
and fare figures; this only writes the rows out.

The week is the week of the job, as in the weekly files — the rows the customer received as W35 —
approved and finished rows only.

    python week_phase3.py --from 2026-08-24 --to 2026-08-30                 # count, write nothing
    python week_phase3.py --from 2026-08-24 --to 2026-08-30 --xlsx w35.xlsx
    python week_phase3.py --from 2026-08-24 --to 2026-08-30 --to-drive      # next to the weekly files
"""
import argparse
import sys
from collections import Counter

from sqlalchemy import select

import db
import excel_writer
from ingest import week_label


def week_rows(d_from, d_to):
    t, j = db.trips.c, db.jobs.c
    with db.engine.begin() as c:
        return [dict(r) for r in c.execute(
            select(*db.TRIP_COLS, j.driver_name, j.category)
            .select_from(db.trips.join(db.jobs, j.id == t.job_id))
            .where(j.date_from == d_from, j.date_to == d_to, t.status == "done", t.committed == 1)
            .order_by(t.trip_date, j.driver_name, t.trip_time, t.id)).mappings().all()]


def file_name(d_from, clean=False):
    return f"Rider Trips {week_label(d_from)} Phase 3{' (คลีน)' if clean else ''}.xlsx"


def drop_repeats(rows):
    """(kept, dropped, held): one row per booking code — the one read first, as the round keeps.

    W34 carried 293 booking codes on 642 rows, nearly all the same slip sent again and filed under
    another rider (Fiat 2026-09-22: clean the week, one step at a time). `dropped` is [(row, the
    kept row)]. A code whose rows disagree on the base fare is not a repeat anyone can be sure of —
    a misread code looks the same — so all its rows stay, and `held` lists them for a person."""
    by_code = {}
    for r in rows:
        code = (r.get("booking_code") or "").strip().upper()
        if code:
            by_code.setdefault(code, []).append(r)
    drop, held = {}, []
    for g in by_code.values():
        if len(g) < 2:
            continue
        if len({r.get("base_fare") for r in g}) > 1:
            held.append(g)
            continue
        first = min(g, key=lambda r: r["id"])
        for r in g:
            if r is not first:
                drop[r["id"]] = (r, first)
    kept = [r for r in rows if r["id"] not in drop]
    return kept, list(drop.values()), held


def removed_sheet(data, dropped, held):
    """The clean file with the rows it left out, and the ones it would not decide, on sheets of
    their own — so anyone can put a row back by hand."""
    import io
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data))
    cols = ["id ที่ตัดออก", "ไรเดอร์", "Service Type", "วันที่", "รหัสการจอง", "ค่ารอบ", "รูปส่งลูกค้า",
            "เก็บไว้ที่ id", "ไรเดอร์ที่เก็บไว้", "รูปส่งลูกค้าที่เก็บไว้"]
    ws = wb.create_sheet("ตัดออก-งานซ้ำ")
    ws.append(cols)
    for r, k in sorted(dropped, key=lambda x: (x[0].get("trip_date") or "", x[0]["id"])):
        ws.append([r["id"], r.get("driver_name"), r.get("service_type"), r.get("trip_date"), r.get("booking_code"),
                   r.get("base_fare"), r.get("customer_image"), k["id"], k.get("driver_name"), k.get("customer_image")])
    ws2 = wb.create_sheet("ยังไม่ตัด-ค่ารอบไม่ตรง")
    ws2.append(["ชุด", "id", "ไรเดอร์", "รหัสการจอง", "ค่ารอบ", "รูปส่งลูกค้า", "ไฟล์", "ลิงก์รูป"])
    for i, g in enumerate(held, 1):
        for r in g:
            ws2.append([i, r["id"], r.get("driver_name"), r.get("booking_code"), r.get("base_fare"),
                        r.get("customer_image"), r.get("file_name"), r.get("source_url")])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def main(argv=None):
    ap = argparse.ArgumentParser(description="ออกไฟล์ของสัปดาห์เดียวในรูปแบบ Phase 3 (ไฟล์แยก)")
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--xlsx", help="เขียนไฟล์ไว้ที่นี่")
    ap.add_argument("--to-drive", action="store_true", help="วางไฟล์ลง Drive ข้างไฟล์ประจำสัปดาห์")
    ap.add_argument("--drop-repeats", action="store_true",
                    help="ฉบับคลีน: รหัสการจองเดียวกันเก็บใบที่อ่านก่อน ตัดที่เหลือ (ไฟล์แยก ไม่แตะฐานข้อมูล)")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    db.init_db()
    rows = week_rows(a.d_from, a.d_to)
    print(f"สัปดาห์ {a.d_from}..{a.d_to} ({week_label(a.d_from)}): {len(rows):,} แถว")
    print("  " + " · ".join(f"{k or '?'} {v:,}" for k, v in Counter(r.get("category") for r in rows).most_common()))
    lines = sum(1 for r in rows if any(r.get(k) for k in ("discount", "insurance_fee", "passenger_tolls")))
    print(f"  แถวที่มีบรรทัดส่วนลด/ประกัน/ทางด่วนแยกแล้ว {lines:,}")
    if not rows:
        return 1
    dropped = held = None
    if a.drop_repeats:
        rows, dropped, held = drop_repeats(rows)
        print(f"  ฉบับคลีน: ตัดงานซ้ำ {len(dropped):,} แถว (ค่ารอบ ฿{sum(r.get('base_fare') or 0 for r, _k in dropped):,.0f})"
              f" · เหลือ {len(rows):,} แถว · รหัสที่ค่ารอบไม่ตรง ยังไม่ตัด {len(held)} รหัส")
        print("  เหลือตาม Service Type: " + " · ".join(f"{k or '?'} {v:,}" for k, v in
                                                       Counter(r.get("service_type") for r in rows).most_common()))
    data = excel_writer.build_fare_lines_workbook(rows, every_week=True)
    if dropped is not None:
        data = removed_sheet(data, dropped, held)
    name = file_name(a.d_from, clean=a.drop_repeats)
    if a.xlsx:
        open(a.xlsx, "wb").write(data)
        print(f"เขียนไฟล์แล้ว: {a.xlsx}")
    if a.to_drive:
        import config
        import roster
        fid = roster._drive().upload_xlsx(config.DRIVE_EXPORTS_FOLDER_ID, name, data)
        print(f"วางลง Drive แล้ว: {name} → https://drive.google.com/file/d/{fid}/view")
    if not (a.xlsx or a.to_drive):
        print(f"\n(นับอย่างเดียว — ใส่ --to-drive เพื่อวาง '{name}' ลง Drive)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
