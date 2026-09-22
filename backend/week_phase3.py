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


def drop_repeats(rows, keep=()):
    """(kept, dropped, held): one row per booking code — the one that says the most.

    W34 carried 293 booking codes on 642 rows, nearly all the same slip sent again and filed under
    another rider (Fiat 2026-09-22: clean the week, one step at a time). `dropped` is [(row, the
    kept row)]. A code whose rows disagree on the base fare is not a repeat anyone can be sure of —
    a misread code looks the same — so all its rows stay, and `held` lists them for a person, unless
    `keep` names the row a person picked after opening the pictures (W34: all seven such codes were
    one trip, one row with the fare misread — 175 for 184, 103 for 108 — or joined to another trip's
    bottom half)."""
    keep = set(keep or ())
    full = {norm_code(r.get("booking_code")) for r in rows
            if r.get("booking_code") and not cut_short(r["booking_code"])}
    by_code = {}
    for r in rows:
        code = norm_code(r.get("booking_code"))
        if code and cut_short(r["booking_code"]):
            whole = [c for c in full if c.startswith(code)]
            code = whole[0] if len(whole) == 1 else code + "..."
        if code:
            by_code.setdefault(code, []).append(r)
    drop, held = {}, []
    for g in by_code.values():
        if len(g) < 2:
            continue
        if len({r.get("base_fare") for r in g if r.get("base_fare")}) > 1:
            chosen = [r for r in g if r["id"] in keep]
            if len(chosen) != 1:
                held.append(g)
                continue
            for r in g:
                if r is not chosen[0]:
                    drop[r["id"]] = (r, chosen[0], "รหัสการจองซ้ำ (เปิดรูปแล้ว: ค่ารอบของแถวนี้อ่านผิดหรือต่อผิดคู่)")
            continue
        # the row that says the most stands for the trip (a joined picture over the half the album
        # counted on its own: W34's 16.jpg is a top with no passenger figures, 'วรวิทย์ 4.jpg' the
        # same trip whole); all else equal, the one read first
        first = max(g, key=_richness)
        for r in g:
            if r is not first:
                drop[r["id"]] = (r, first, "รหัสการจองซ้ำ")
    kept = [r for r in rows if r["id"] not in drop]
    # the same picture under two riders, read without its code: equal in day, time, fare, distance
    # and pick-up to the last character. W34's พงศ์กฤษณ์ and วิมลวรรณ hold the very same
    # MyImage-….jpg files; all 13 such sets were opened and each was one trip (2026-09-23)
    same = {}
    for r in kept:
        if r.get("base_fare") and r.get("distance_km") and (r.get("pickup_text") or "").strip():
            same.setdefault((r.get("trip_date"), r.get("trip_time"), r["base_fare"], r["distance_km"],
                             r["pickup_text"].strip()), []).append(r)
    for g in same.values():
        if len(g) < 2 or not all(codes_agree(a.get("booking_code"), b.get("booking_code"))
                                 for a in g for b in g):
            continue
        first = max(g, key=_richness)
        for r in g:
            if r is not first:
                drop[r["id"]] = (r, first, "เหมือนกันทุกช่อง (วัน เวลา ค่ารอบ ระยะทาง จุดรับ) ไม่มีรหัสการจองให้แยก")
    kept = [r for r in rows if r["id"] not in drop]
    # the same trip twice under one rider, with no code to say so (W34 วรวิทย์, 2026-09-23)
    for stands, gone in same_trip_groups(kept):
        for r, why in gone:
            drop[r["id"]] = (r, stands, why)
    kept = [r for r in rows if r["id"] not in drop]
    return kept, list(drop.values()), held


def _num(name):
    """The picture's number in its album: 'วรวิทย์ 12.jpg' → 12, '48666_0_48667_0.jpg' → 48666,
    'MyImage-1787829600-00.jpg' → 1787829600 — the longest run of digits, not the last one (the
    '_0' and '-00' LINE and phones append made every such picture look next to every other)."""
    import re
    m = re.findall(r"\d+", (name or "").rsplit(".", 1)[0])
    return int(max(m, key=len)) if m else None


def _family(name):
    """How an upload names its pictures, digits taken out: '41.jpg' and 'วรวิทย์ 14.jpg' are two
    uploads; 'Screenshot 2026-08-28 124028.png' and '…124219.png' are one."""
    import re
    return re.sub(r"\d+", "#", (name or "").rsplit(".", 1)[0]).strip()


def _minutes(t):
    """'21:46' → 1306; a time bucket ('18:00-23:59') or nothing → None."""
    import re
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", t or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _richness(r):
    """Which of a trip's rows to keep: the one that says the most — a booking code, both halves
    (the passenger block), a base fare — and, all else equal, the one read first."""
    return (bool(r.get("base_fare")), bool((r.get("booking_code") or "").strip()),
            r.get("passenger_paid") is not None, bool(r.get("pickup_text")), -r["id"])


def norm_code(code):
    """A booking code as the reader's two usual confusions leave it: O for 0 and I for 1, and
    without the '...' a slip prints when the code is too long for the line. #8210 reads
    'A-9O3NIXK...' where the same slip uploaded again reads 'A-903NIXK'."""
    c = (code or "").strip().upper().replace("O", "0").replace("I", "1").replace("…", "...")
    return c[:-3].rstrip() if c.endswith("...") else c


def cut_short(code):
    return (code or "").strip().endswith(("...", "…"))


def codes_agree(a, b):
    """Two rows' codes can be one slip's: equal, or one cut short and the start of the other."""
    ca, cb = norm_code(a), norm_code(b)
    if not ca or not cb:
        return True
    if ca == cb:
        return True
    return (cut_short(a) and cb.startswith(ca)) or (cut_short(b) and ca.startswith(cb))


def same_trip_groups(rows):
    """[(kept row, [(dropped row, why)])] — rows of ONE rider that are one trip.

    วรวิทย์'s W34 came in twice: an album of halves (1.jpg–63.jpg), where many bottom halves were
    counted as trips of their own, and a second upload of the same trips already joined. 49 rows,
    about 28 trips (Fiat 2026-09-23). A booking code only settles the rows that carry one — most of
    the album's tops do not — so rows of the same rider are also one trip when:
      * a bottom half with no base (paid and fare only) carries the paid and fare of a row that has
        a base — the half the reader could not price;
      * two rows print the same base AND the same คุณได้รับ, and one of them carries nothing the
        other contradicts: no second booking code, no different passenger figures. Two album tops
        of the same fare are two trips unless their pictures stand next to each other (the two
        halves of one slip are shot back to back).
    Kept is the row that says the most; each dropped row says why."""
    by_rider = {}
    for r in rows:
        by_rider.setdefault((r.get("driver_name"), r.get("category")), []).append(r)
    out = []
    for _k, rs in by_rider.items():
        parent = {r["id"]: r["id"] for r in rs}
        why = {}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def join(a, b, reason):
            ra, rb = find(a["id"]), find(b["id"])
            if ra != rb:
                parent[rb] = ra
                why.setdefault(b["id"], reason)
                why.setdefault(a["id"], reason)

        code = lambda r: norm_code(r.get("booking_code"))
        pt = lambda r: (r.get("passenger_paid"), r.get("passenger_total"))
        priced = [r for r in rs if r.get("base_fare")]
        for b in rs:
            if b.get("base_fare") or None in pt(b):
                continue
            match = [a for a in priced if pt(a) == pt(b)]
            if len({(a.get("base_fare"), a.get("net_earnings")) for a in match}) == 1:
                join(match[0], b, "ครึ่งล่างของงานนี้ (ไม่มีค่ารอบ ยอดผู้โดยสารตรงกัน)")
                continue
            # no priced row carries its passenger figures: its own top half is the one priced row
            # a few pictures away that has no passenger figures of its own (24.jpg is the bottom of
            # 22.jpg's ฿247 trip; the second upload that joined them was already set aside)
            nb = _num(b.get("file_name"))
            near = [a for a in priced if pt(a) == (None, None) and nb is not None
                    and _num(a.get("file_name")) is not None and abs(_num(a["file_name"]) - nb) <= 3
                    and (a.get("file_name") or "")[:1].isdigit() == (b.get("file_name") or "")[:1].isdigit()]
            # a slip is shot top first: of two tops either side, the one just before is its own
            before = [a for a in near if _num(a["file_name"]) < nb]
            pick = (max(before, key=lambda a: _num(a["file_name"])) if before
                    else near[0] if len(near) == 1 else None)
            if pick is not None:
                join(pick, b, "ครึ่งล่างของงานนี้ (ไม่มีค่ารอบ รูปติดกับครึ่งบน)")
        for b in rs:
            # a row with nothing on it at all — no base, no คุณได้รับ, no passenger figure — is
            # not a trip anyone can bill; it joins the picture beside it, where there is one
            if b.get("base_fare") or b.get("net_earnings") or any(pt(b)):
                continue
            nb = _num(b.get("file_name"))
            near = [a for a in rs if a is not b and nb is not None and _num(a.get("file_name")) is not None
                    and abs(_num(a["file_name"]) - nb) <= 1]
            if near:
                join(max(near, key=_richness), b, "แถวว่างทุกช่อง (รูปติดกับงานนี้)")
        for i, a in enumerate(priced):
            for b in priced[i + 1:]:
                if (a.get("base_fare"), a.get("net_earnings")) != (b.get("base_fare"), b.get("net_earnings")):
                    continue
                if not codes_agree(a.get("booking_code"), b.get("booking_code")):
                    continue
                pa, pb = a.get("passenger_paid") is not None, b.get("passenger_paid") is not None
                if pa and pb and any(x is not None and y is not None and x != y for x, y in zip(pt(a), pt(b))):
                    continue                   # both print the passenger's figures, and they differ
                if not (pa or pb):
                    continue                   # two tops: two trips, each with a bottom of its own
                da, db_ = a.get("distance_km"), b.get("distance_km")
                if da and db_ and abs(da - db_) > 0.05:
                    # ฿24 over a 23/24 fee card is every other short trip: เสน่ห์ 17 and 18 print the
                    # same figures and stand side by side, but one ran 1.95 km and the other 1.65
                    continue
                na, nb = _num(a.get("file_name")), _num(b.get("file_name"))
                same_upload = _family(a.get("file_name")) == _family(b.get("file_name"))
                adjacent = same_upload and na is not None and nb is not None and abs(na - nb) <= 2
                # shot within a few minutes counts only across two uploads of the same trips: the
                # second keeps the screenshots' own clock. Within one upload a rider shoots a whole
                # evening's ฿24 trips minutes apart, and those are different trips.
                ma, mb = _minutes(a.get("trip_time")), _minutes(b.get("trip_time"))
                close = (not same_upload) and ma is not None and mb is not None and abs(ma - mb) <= 3
                if adjacent or close:
                    join(a, b, "ค่ารอบและคุณได้รับตรงกัน ไรเดอร์เดียวกัน"
                         + (" (รูปติดกัน)" if adjacent else " (อัปสองรอบ เวลาในรูปห่างไม่เกิน 3 นาที)"))
        groups = {}
        for r in rs:
            groups.setdefault(find(r["id"]), []).append(r)
        for g in groups.values():
            if len(g) < 2:
                continue
            keep = max(g, key=_richness)
            out.append((keep, [(r, why.get(r["id"], "งานเดียวกัน")) for r in g if r is not keep]))
    return out


def removed_sheet(data, dropped, held):
    """The clean file with the rows it left out, and the ones it would not decide, on sheets of
    their own — so anyone can put a row back by hand."""
    import io
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data))
    cols = ["id ที่ตัดออก", "ไรเดอร์", "Service Type", "วันที่", "รหัสการจอง", "ค่ารอบ", "รูปส่งลูกค้า", "ไฟล์",
            "เหตุผล", "เก็บไว้ที่ id", "ไรเดอร์ที่เก็บไว้", "รูปส่งลูกค้าที่เก็บไว้", "ไฟล์ที่เก็บไว้", "ลิงก์รูปที่ตัด"]
    ws = wb.create_sheet("ตัดออก-งานซ้ำ")
    ws.append(cols)
    for r, k, why in sorted(dropped, key=lambda x: (x[2], x[0].get("driver_name") or "", x[0]["id"])):
        ws.append([r["id"], r.get("driver_name"), r.get("service_type"), r.get("trip_date"), r.get("booking_code"),
                   r.get("base_fare"), r.get("customer_image"), r.get("file_name"), why, k["id"], k.get("driver_name"),
                   k.get("customer_image"), k.get("file_name"), r.get("source_url")])
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
    ap.add_argument("--from", dest="d_from", required=True, help="วันแรกของสัปดาห์ (หลายสัปดาห์: คั่นด้วยจุลภาค)")
    ap.add_argument("--to", dest="d_to", required=True, help="วันสุดท้ายของสัปดาห์ (เรียงคู่กับ --from)")
    ap.add_argument("--folder", default="", help="วางไฟล์ในโฟลเดอร์ชื่อนี้ใต้ Exports (สร้างให้ถ้ายังไม่มี)")
    ap.add_argument("--name", default="", help="ชื่อไฟล์ที่จะวาง (ว่าง = ตั้งจากสัปดาห์)")
    ap.add_argument("--xlsx", help="เขียนไฟล์ไว้ที่นี่")
    ap.add_argument("--to-drive", action="store_true", help="วางไฟล์ลง Drive ข้างไฟล์ประจำสัปดาห์")
    ap.add_argument("--keep", default="", help="id ที่คนเปิดรูปแล้วเลือกเก็บ ในรหัสที่ค่ารอบไม่ตรงกัน (คั่นด้วยจุลภาค)")
    ap.add_argument("--drop-repeats", action="store_true",
                    help="ฉบับคลีน: รหัสการจองเดียวกันเก็บใบที่อ่านก่อน ตัดที่เหลือ (ไฟล์แยก ไม่แตะฐานข้อมูล)")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    db.init_db()
    # one file may carry several weeks: Ops reads the re-delivery of W34 and W35 as one file
    # in one folder, not four files beside the weekly ones (Fiat 2026-09-23)
    froms = [x for x in a.d_from.replace(" ", "").split(",") if x]
    tos = [x for x in a.d_to.replace(" ", "").split(",") if x]
    if len(froms) != len(tos):
        print("✗ --from กับ --to ต้องมีจำนวนเท่ากัน")
        return 1
    rows = []
    for f, t in zip(froms, tos):
        part = week_rows(f, t)
        print(f"สัปดาห์ {f}..{t} ({week_label(f)}): {len(part):,} แถว")
        print("  " + " · ".join(f"{k or '?'} {v:,}" for k, v in Counter(r.get("category") for r in part).most_common()))
        rows += part
    if len(froms) > 1:
        print(f"รวมทั้งหมด {len(rows):,} แถว ในไฟล์เดียว")
    lines = sum(1 for r in rows if any(r.get(k) for k in ("discount", "insurance_fee", "passenger_tolls")))
    print(f"  แถวที่มีบรรทัดส่วนลด/ประกัน/ทางด่วนแยกแล้ว {lines:,}")
    if not rows:
        return 1
    dropped = held = None
    if a.drop_repeats:
        rows, dropped, held = drop_repeats(rows, keep={int(x) for x in a.keep.replace(" ", "").split(",") if x})
        for why, k in Counter(w for _r, _k, w in dropped).most_common():
            print(f"    ตัด {k:,} แถว: {why}")
        print("    ไรเดอร์ที่ถูกตัดเพราะงานเดียวกันในคนเดียว: " + " · ".join(
            f"{d} {n}" for d, n in Counter(r.get("driver_name") for r, _k, w in dropped if w != "รหัสการจองซ้ำ").most_common(12)))
        print(f"  ฉบับคลีน: ตัดงานซ้ำ {len(dropped):,} แถว (ค่ารอบ ฿{sum(r.get('base_fare') or 0 for r, _k, _w in dropped):,.0f})"
              f" · เหลือ {len(rows):,} แถว · รหัสที่ค่ารอบไม่ตรง ยังไม่ตัด {len(held)} รหัส")
        print("  เหลือตาม Service Type: " + " · ".join(f"{k or '?'} {v:,}" for k, v in
                                                       Counter(r.get("service_type") for r in rows).most_common()))
    data = excel_writer.build_fare_lines_workbook(rows, every_week=True)
    if dropped is not None:
        data = removed_sheet(data, dropped, held)
    name = a.name or (file_name(froms[0], clean=a.drop_repeats) if len(froms) == 1 else
                      f"Rider Trips {'-'.join(week_label(f) for f in froms)} Phase 3.xlsx")
    if a.xlsx:
        open(a.xlsx, "wb").write(data)
        print(f"เขียนไฟล์แล้ว: {a.xlsx}")
    if a.to_drive:
        import config
        import roster
        drive = roster._drive()
        where = config.DRIVE_EXPORTS_FOLDER_ID
        if a.folder:
            where = drive.ensure_folder(where, a.folder)
        fid = drive.upload_xlsx(where, name, data)
        print(f"วางลง Drive แล้ว: {(a.folder + '/') if a.folder else ''}{name}"
              f" → https://drive.google.com/file/d/{fid}/view")
    if not (a.xlsx or a.to_drive):
        print(f"\n(นับอย่างเดียว — ใส่ --to-drive เพื่อวาง '{name}' ลง Drive)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
