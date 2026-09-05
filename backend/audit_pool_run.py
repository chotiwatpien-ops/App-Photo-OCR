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
    by_name = {p["file"]: p for p in mine}
    from sqlalchemy import select
    with db.engine.begin() as c:
        rows = [dict(r) for r in c.execute(
            select(db.trips, db.jobs.c.driver_name, db.jobs.c.category)
            .select_from(db.trips.join(db.jobs, db.trips.c.job_id == db.jobs.c.id))
            .where(db.trips.c.file_name.in_(list(by_name)))).mappings().all()]
    print(f"\nกลายเป็นแถวในฐานข้อมูล {len(rows)} แถว")
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
    print(f"\nแถวที่มาจากคู่ห่างเกิน {FAR} ใบ: {len(far_rows)} แถว · ในนั้นเลขขัดกัน {len(bad)} แถว")
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
            later = [dict(r) for r in c.execute(
                select(db.trips.c.id, db.trips.c.file_name, db.trips.c.booking_code)
                .where(db.trips.c.file_name.in_([p["file"] for p in theirs]))).mappings().all()]
        later_codes = {r["booking_code"] for r in later if r.get("booking_code")}
        both = codes & later_codes
        print(f"  รหัสการจองที่รอบ #{a.against} อ่านได้ซ้ำกับรอบ #{a.run}: {len(both)} เที่ยว")
        print(f"  รหัสที่มีเฉพาะรอบ #{a.run}: {len(codes - later_codes)} เที่ยว  "
              f"← ส่วนใหญ่คือคู่ที่จับผิด รหัสจึงไม่ตรงกับใคร")

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
    print("\n(รายงานอย่างเดียว — ไม่ได้แก้อะไรทั้งสิ้น)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
