# -*- coding: utf-8 -*-
"""What a pool run put into the database, and what a later run has already done again.

Run #7 (2026-09-05) paired an album that Ops had only uploaded a third of. With most partners
missing, the matcher reached for whatever half carried the same amount, and glued together halves
that are 17 to 52 pictures apart — two different trips in one picture. Run #8, on the complete
upload, paired the same album strictly in sequence.

This says which rows came from which, and never changes anything: read-only, on purpose. The
distance between the two halves is the giveaway and it is printed for every pair, because it is
readable straight off the stitched file's own name ('…_8+29_฿56.jpg').

    python audit_pool_run.py --run 7                 # what run 7 produced
    python audit_pool_run.py --run 7 --against 8     # …and which of it run 8 has redone
"""
import argparse
import json
import re
import sys
from collections import defaultdict

import db

FAR = 6                    # halves further apart than this were never sent as a pair by a rider


def when(s):
    """pool_runs writes '2026-09-06 00:38:06' and jobs write the ISO '…T00:38:06'. Compared
    as text the T sorts after the space, so every job of the morning looked later than a run
    that started after it. One shape, then compare."""
    return (s or "").replace("T", " ")


def pairs_of(run):
    """[(file name, distance between the two halves, where it was filed)] for one pool run."""
    report = json.loads(run["report"] or "{}")
    out = []
    for alb in report.get("albums", []):
        for p in alb.get("pairs", []):
            moved = p.get("moved") or ""
            if "/" not in moved:
                continue                                  # never actually filed
            out.append({"file": moved.split("/")[-1], "where": moved,
                        "album": alb["album"], "amount": p.get("amount"),
                        "distance": p.get("distance") or 0})
    return out


def digits(name):
    m = re.search(r"_(\d+)\+(\d+)_", name or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def resolve(run_id, far=FAR):
    """(run, every pair it filed, the far ones, the rows they became, the far rows).

    Shared with void_pool_pairs.py on purpose: a tool that removes rows must be looking at
    exactly the same set the report showed, decided by the same rule."""
    from sqlalchemy import select
    runs = {r["id"]: r for r in db.recent_pool_runs(50, with_report=True)}
    if run_id not in runs:
        return None
    run = runs[run_id]
    mine = pairs_of(run)
    nxt = [when(r["started_at"]) for r in runs.values()
           if when(r["started_at"]) > when(run["started_at"])]
    cutoff = min(nxt) if nxt else None
    with db.engine.begin() as c:
        every = [dict(r) for r in c.execute(
            select(db.trips, db.jobs.c.driver_name, db.jobs.c.category, db.jobs.c.created_at,
                   db.jobs.c.date_from, db.jobs.c.date_to)
            .select_from(db.trips.join(db.jobs, db.trips.c.job_id == db.jobs.c.id))
            .where(db.trips.c.file_name.in_([p["file"] for p in mine]))).mappings().all()]
    rows = [r for r in every if cutoff is None or when(r.get("created_at")) < cutoff]
    far_files = {p["file"] for p in mine if p["distance"] > far}
    by_file = {p["file"]: p for p in mine}
    far_rows = [dict(r, distance=by_file[r["file_name"]]["distance"])
                for r in rows if r["file_name"] in far_files]
    return {"runs": runs, "run": run, "pairs": mine, "far": [by_file[f] for f in far_files],
            "rows": rows, "far_rows": far_rows, "cutoff": cutoff, "shared": len(every) - len(rows)}



def health(rows):
    """Is the week finished, and did any trip end up counted twice or not at all?

    Two runs over the same photos make two rows per trip, and which copy survives is decided by
    the duplicate guard as each one is read. That is only safe to judge once every picture has
    come back from its batch — until then a trip can look lost simply because its reading has
    not arrived yet. So the readiness line comes first, and the two counts below it mean nothing
    while it is above zero."""
    from sqlalchemy import func, select
    weeks = {(r["date_from"], r["date_to"]) for r in rows if r.get("date_from")}
    if not weeks:
        return
    with db.engine.begin() as c:
        ids = []
        for a, b in weeks:
            ids += [r[0] for r in c.execute(select(db.jobs.c.id).where(
                db.jobs.c.date_from == a, db.jobs.c.date_to == b)).all()]
        waiting = c.execute(select(func.count()).select_from(db.trips).where(
            db.trips.c.job_id.in_(ids), db.trips.c.batch_name.isnot(None),
            db.trips.c.status == "pending")).scalar() or 0
        pending = c.execute(select(func.count()).select_from(db.trips).where(
            db.trips.c.job_id.in_(ids), db.trips.c.status == "pending")).scalar() or 0
        got = [dict(r) for r in c.execute(
            select(db.trips.c.booking_code, db.trips.c.status, db.trips.c.committed,
                   db.trips.c.file_name, db.jobs.c.driver_name)
            .select_from(db.trips.join(db.jobs, db.trips.c.job_id == db.jobs.c.id))
            .where(db.trips.c.job_id.in_(ids),
                   db.trips.c.booking_code.isnot(None))).mappings().all()]
    print(f"\nสุขภาพของสัปดาห์ ({len(ids)} job)")
    print(f"  ยังรอผลจาก batch: {waiting} รูป · ยังไม่ได้อ่านเลย {pending} รูป"
          + ("  ← ตัวเลขสองบรรทัดล่างยังเชื่อไม่ได้จนกว่าจะเป็น 0" if pending else "  ✓ อ่านครบแล้ว"))
    by_code = {}
    for r in got:
        if len(r["booking_code"]) >= db.DUP_FULL_CODE:
            by_code.setdefault(r["booking_code"], []).append(r)
    twice = {k: v for k, v in by_code.items() if sum(1 for x in v if x["committed"]) > 1}
    lost = {k: v for k, v in by_code.items()
            if not any(x["committed"] for x in v)
            and all(x["status"] in ("duplicate", "voided") for x in v)}
    print(f"  เที่ยวที่ลงไฟล์ส่งงานซ้ำสองรอบ: {len(twice)}"
          + ("  ← นับเงินซ้ำ ต้องเอาออกหนึ่งแถว" if twice else " ✓"))
    for code, v in list(twice.items())[:10]:
        print(f"     {code}  " + " · ".join(f"{x['driver_name']}/{x['file_name']}"
                                            for x in v if x["committed"]))
    print(f"  เที่ยวที่ทุกแถวถูกพักไว้ ไม่มีตัวไหนลงไฟล์: {len(lost)}"
          + ("  ← ตกหล่น ต้องกู้คืนหนึ่งแถว" if lost else " ✓"))
    for code, v in list(lost.items())[:10]:
        print(f"     {code}  " + " · ".join(f"{x['driver_name']}/{x['file_name']}({x['status']})"
                                            for x in v))



def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=int, required=True, help="เลข pool run ที่จะตรวจ")
    ap.add_argument("--against", type=int, default=0, help="เทียบกับ pool run ที่ทำซ้ำทีหลัง")
    ap.add_argument("--list", action="store_true", help="พิมพ์รายไฟล์ทั้งหมด ไม่ใช่แค่สรุป")
    a = ap.parse_args(argv)
    db.init_db()

    runs = {r["id"]: r for r in db.recent_pool_runs(50, with_report=True)}
    if a.run not in runs:
        print(f"✗ ไม่พบ pool run #{a.run} (มี: {', '.join(str(i) for i in sorted(runs, reverse=True))})")
        return 1
    mine = pairs_of(runs[a.run])
    print(f"pool run #{a.run} · {runs[a.run]['week']} · โหมด {runs[a.run]['mode']} · "
          f"{runs[a.run]['started_at']}")
    print(f"  ต่อรูปแล้วย้ายเข้าโฟลเดอร์ไรเดอร์ {len(mine)} ไฟล์")

    far = [p for p in mine if p["distance"] > FAR]
    print(f"  ในนั้นครึ่งบน/ครึ่งล่างห่างกันเกิน {FAR} ใบ: {len(far)} ไฟล์  ← น่าสงสัยว่าจับผิดคู่")

    # --- the rows those files became -----------------------------------------------------------
    # The stitched name is '<album>_<top>+<bottom>_฿<amount>', so two runs over the same album
    # produce the SAME name whenever they pair the same positions for the same fare — which a
    # re-upload does constantly, and the name alone then picks up both runs' rows. The job's
    # creation time separates them: a row belongs to this run only if its job was opened before
    # the next run started.
    by_name = {p["file"]: p for p in mine}
    nxt = [when(r["started_at"]) for r in runs.values() if when(r["started_at"]) > when(runs[a.run]["started_at"])]
    cutoff = min(nxt) if nxt else None
    from sqlalchemy import select
    with db.engine.begin() as c:
        every = [dict(r) for r in c.execute(
            select(db.trips, db.jobs.c.driver_name, db.jobs.c.category, db.jobs.c.created_at,
                   db.jobs.c.date_from, db.jobs.c.date_to)
            .select_from(db.trips.join(db.jobs, db.trips.c.job_id == db.jobs.c.id))
            .where(db.trips.c.file_name.in_(list(by_name)))).mappings().all()]
    rows = [r for r in every if cutoff is None or when(r.get("created_at")) < cutoff]
    print(f"\nกลายเป็นแถวในฐานข้อมูล {len(rows)} แถว")
    if cutoff:
        print(f"  (ชื่อไฟล์ชนกับรอบหลัง {len(every) - len(rows)} แถว — คัดออกด้วยเวลาเปิด job ก่อน {cutoff})")
    if len(rows) < len(mine):
        print(f"  (อีก {len(mine) - len(rows)} ไฟล์ยังไม่ได้อ่าน หรืออ่านแล้วแต่ชื่อไม่ตรง)")

    st = defaultdict(int)
    for r in rows:
        st[(r.get("status"), r.get("check_status"), bool(r.get("committed")))] += 1
    print(f"\n{'สถานะ':<12}{'ผลตรวจเลข':<12}{'ลงไฟล์แล้ว':<12}{'แถว':>5}")
    for (s, cs, com), n in sorted(st.items(), key=lambda kv: -kv[1]):
        print(f"{str(s):<12}{str(cs):<12}{('ใช่' if com else 'ยัง'):<12}{n:>5}")

    far_names = {p["file"] for p in far}
    far_rows = [r for r in rows if r["file_name"] in far_names]
    bad = [r for r in far_rows if r.get("check_status") == "fail"]
    quiet = [r for r in far_rows if r.get("check_status") != "fail"]
    sent = [r for r in quiet if r.get("committed")]
    print(f"\nแถวที่มาจากคู่ห่างเกิน {FAR} ใบ: {len(far_rows)} แถว")
    print(f"  เลขขัดกัน (คิวตรวจจับได้): {len(bad)} แถว")
    print(f"  ผ่านการตรวจเลข: {len(quiet)} แถว  ← ไม่มีอะไรเตือน แต่เป็นสองเที่ยวคนละเที่ยว")
    print(f"    ในนั้นลงไฟล์ส่งงานไปแล้ว: {len(sent)} แถว")
    print(f"แถวที่มาจากคู่ติดกัน: {len(rows) - len(far_rows)} แถว")

    # --- what a later run has already redone ---------------------------------------------------
    if a.against:
        if a.against not in runs:
            print(f"\n✗ ไม่พบ pool run #{a.against}")
            return 1
        theirs = pairs_of(runs[a.against])
        print(f"\nเทียบกับ pool run #{a.against} ({len(theirs)} ไฟล์)")
        codes = {r["booking_code"] for r in rows if r.get("booking_code")}
        from sqlalchemy import select
        with db.engine.begin() as c:
            after = [dict(r) for r in c.execute(
                select(db.trips.c.booking_code, db.jobs.c.created_at)
                .select_from(db.trips.join(db.jobs, db.trips.c.job_id == db.jobs.c.id))
                .where(db.trips.c.file_name.in_([p["file"] for p in theirs]))).mappings().all()]
        start = when(runs[a.against]["started_at"])
        later_codes = {r["booking_code"] for r in after
                       if r.get("booking_code") and when(r.get("created_at")) >= start}
        both = codes & later_codes
        print(f"  รหัสการจองที่รอบ #{a.against} อ่านได้ซ้ำกับรอบ #{a.run}: {len(both)} เที่ยว ← เที่ยวเดียวกันมีสองแถว")
        print(f"  รหัสที่มีเฉพาะรอบ #{a.run}: {len(codes - later_codes)} เที่ยว")

    if a.list:
        print(f"\n--- ไฟล์ที่ครึ่งบน/ครึ่งล่างห่างกันเกิน {FAR} ใบ ---")
        seen = {r["file_name"]: r for r in rows}
        for p in sorted(far, key=lambda p: -p["distance"]):
            r = seen.get(p["file"], {})
            d = digits(p["file"])
            print(f"  ห่าง {p['distance']:>3}  {p['where']}"
                  f"{'  [' + str(r.get('check_status')) + ']' if r else '  [ยังไม่ได้อ่าน]'}"
                  f"{'  ' + str(r.get('booking_code')) if r.get('booking_code') else ''}"
                  + (f"  ({d[0]} กับ {d[1]})" if d else ""))
    health(rows)
    print("\n(รายงานอย่างเดียว — ไม่ได้แก้อะไรทั้งสิ้น)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
