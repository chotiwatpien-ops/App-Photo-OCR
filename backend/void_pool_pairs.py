# -*- coding: utf-8 -*-
"""Take back the trips a pool run built out of two halves that do not belong together.

Run 7 paired an album Ops had only uploaded a third of. With most partners missing, the matcher
reached for whatever half carried the same fare and glued halves 8 to 52 pictures apart. Riders
send the two shots back to back, so the distance between them is the tell — and it is written
into the stitched file's own name ('…_8+29_฿56.jpg').

These rows cannot be repaired by hand. The picture is two different trips, so the booking code,
date and distance come from one and the passenger fare from the other; correcting the numbers
would invent a trip that never happened. And the real trip behind each half is already in the
database from the later run over the complete upload.

Nothing is deleted. The stitched picture moves to a holding folder beside the week, and the row
is parked as 'voided' with its note saying why — db.restore_voided() puts one back.

    python void_pool_pairs.py --run 7                 # report only
    python void_pool_pairs.py --run 7 --apply         # do it
"""
import argparse
import re
import sys
from collections import defaultdict

import audit_pool_run as audit
import config
import db

HOLD_DIR = "_ทิ้ง-จับคู่ผิด"


def drive_id(source_url):
    """'https://drive.google.com/file/d/<id>/view?usp=…' -> '<id>'."""
    m = re.search(r"/d/([^/?]+)", source_url or "")
    return m.group(1) if m else ((source_url or "").rstrip("/").split("/")[-1] or None)


def scan_week(week_name, min_distance, apply_it):
    """Judge the stitched pictures already sitting in a week's rider folders, by name alone.

    Backfill moved 150 of them out of the group folders and into riders, where the next round
    will read them — and they were made by pool runs older than every pairing fix. The distance
    between the two halves is in the file's own name, so a bad pair can be found and pulled
    before it is ever read, without OCR, a model call or a database row to undo."""
    import roster
    drive = roster._drive()
    inbox = config.DRIVE_INBOX_FOLDER_ID
    week = next((f for f in drive.list_folders(inbox) if f["name"].strip() == week_name.strip()), None)
    if week is None:
        print(f"✗ ไม่พบสัปดาห์ {week_name!r} ใน Inbox")
        return 1
    found, far = 0, []
    for cat in drive.list_folders(week["id"]):
        if cat["name"].strip().lower() in ("pool", "กอง") or cat["name"].lstrip().startswith("_"):
            continue
        for rider in drive.list_folders(cat["id"]):
            for img in drive.list_images(rider["id"]):
                d = audit.digits(img["name"])
                if d is None:
                    continue
                found += 1
                gap = abs(d[0] - d[1])
                if gap >= min_distance:
                    far.append((gap, cat["name"], rider["name"], img["name"], img["id"]))
    print(f"{week_name}: รูปที่ต่อแล้วในโฟลเดอร์ไรเดอร์ {found} ใบ")
    print(f"  ครึ่งบน/ครึ่งล่างห่างกันตั้งแต่ {min_distance} ใบ: {len(far)} ใบ"
          + ("  ← น่าสงสัยว่าจับผิดคู่" if far else "  ✓ ติดกันหมด"))
    for gap, cat, rider, name, _ in sorted(far, reverse=True)[:40]:
        print(f"    ห่าง {gap:>3}  {cat}/{rider}/{name}")
    if not far:
        return 0
    if not apply_it:
        print("\n(รายงานอย่างเดียว — ใส่ --apply เพื่อย้ายออกไปพักไว้)")
        return 0
    hold = drive.ensure_folder(week["id"], HOLD_DIR)
    n = 0
    for _gap, _cat, _rider, name, fid in far:
        try:
            drive.move_file(fid, hold)
            n += 1
        except Exception as e:                                    # noqa: BLE001
            print(f"  ⚠ ย้ายไม่สำเร็จ {name}: {str(e)[:80]}")
    print(f"\nย้ายไป {week_name}/{HOLD_DIR}/ แล้ว {n} ใบ (ไม่ได้ลบ) — "
          f"รอบถัดไปจะไม่อ่านมันเข้าฐานข้อมูล")
    from sqlalchemy import select
    with db.engine.begin() as c:                      # any of them already read? park those too
        ids = [r[0] for r in c.execute(select(db.trips.c.id).where(
            db.trips.c.file_name.in_([f[3] for f in far]),
            db.trips.c.status != "voided")).all()]
    if ids:
        db.void_trips(ids, "ทิ้ง: คู่ผิด (ตรวจจากระยะห่างในชื่อไฟล์)")
        print(f"และพักแถวที่เคยอ่านไปแล้ว {len(ids)} แถว")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="เอาแถวที่เกิดจากคู่ผิดของ pool run ออก (ไม่ลบ)")
    ap.add_argument("--run", type=int, help="เลข pool run (ไม่ต้องใส่ถ้า --release-only)")
    ap.add_argument("--min-distance", type=int, default=audit.FAR + 1,
                    help=f"ห่างกันตั้งแต่กี่ใบถึงถือว่าผิดคู่ (ค่าเริ่มต้น {audit.FAR + 1})")
    ap.add_argument("--apply", action="store_true", help="ทำจริง (ไม่ใส่ = รายงานอย่างเดียว)")
    ap.add_argument("--keep-images", action="store_true", help="ไม่ต้องย้ายรูปบน Drive")
    ap.add_argument("--release-only", action="store_true",
                    help="ไม่พักแถวใหม่ แค่ปลดธงซ้ำของแถวที่ชี้ไปหาแถวที่พักไปแล้ว")
    ap.add_argument("--scan-week", default="",
                    help="ตรวจไฟล์ที่ต่อแล้วในโฟลเดอร์ไรเดอร์ของสัปดาห์นี้ จากชื่อไฟล์ (ยังไม่ต้องอ่าน)")
    a = ap.parse_args(argv)
    db.init_db()

    if a.release_only:
        n = db.release_dup_flags_pointing_at_voided()
        print(f"ปลดธงซ้ำให้ {n} แถวที่ชี้ไปหาแถวที่ถูกพักไว้แล้ว — กลับไปเข้าเส้นทางอนุมัติปกติ")
        return 0
    if a.scan_week:
        return scan_week(a.scan_week, a.min_distance, a.apply)
    if not a.run:
        ap.error("ต้องระบุ --run, --scan-week หรือ --release-only")

    r = audit.resolve(a.run, far=a.min_distance - 1)
    if r is None:
        print(f"✗ ไม่พบ pool run #{a.run}")
        return 1
    rows = r["far_rows"]
    print(f"pool run #{a.run} · {r['run']['week']} · {r['run']['started_at']}")
    print(f"  คู่ที่ห่างกันตั้งแต่ {a.min_distance} ใบขึ้นไป: {len(r['far'])} ไฟล์ → {len(rows)} แถว")
    if not rows:
        print("  ไม่มีอะไรต้องทำ")
        return 0

    st = defaultdict(int)
    for t in rows:
        st[(t.get("status"), t.get("check_status"), bool(t.get("committed")))] += 1
    print(f"\n{'สถานะ':<12}{'ผลตรวจเลข':<12}{'ลงไฟล์แล้ว':<12}{'แถว':>5}")
    for (s, cs, com), n in sorted(st.items(), key=lambda kv: -kv[1]):
        print(f"{str(s):<12}{str(cs):<12}{('ใช่' if com else 'ยัง'):<12}{n:>5}")
    sent = [t for t in rows if t.get("committed")]
    print(f"\nในนั้นอยู่ในไฟล์ส่งลูกค้าแล้ว {len(sent)} แถว — เอาออกแล้วไฟล์จะถูกเขียนใหม่เองรอบหน้า")

    print(f"\n{'ห่าง':>5}  {'ไรเดอร์':<22}{'ผลตรวจ':<8}{'ไฟล์'}")
    for t in sorted(rows, key=lambda t: -t["distance"]):
        print(f"{t['distance']:>5}  {str(t.get('driver_name'))[:22]:<22}"
              f"{str(t.get('check_status')):<8}{t['file_name']}")

    if not a.apply:
        print("\n(รายงานอย่างเดียว — ยังไม่ได้แตะอะไร · ใส่ --apply เพื่อทำจริง)")
        return 0

    moved = 0
    if not a.keep_images:
        import roster
        drive = roster._drive()
        inbox = config.DRIVE_INBOX_FOLDER_ID
        week = next((f for f in drive.list_folders(inbox)
                     if f["name"].strip() == (r["run"]["week"] or "").strip()), None)
        if week is None:
            print(f"⚠ ไม่พบโฟลเดอร์สัปดาห์ {r['run']['week']!r} — ข้ามการย้ายรูป แถวยังเอาออกตามปกติ")
        else:
            hold = drive.ensure_folder(week["id"], HOLD_DIR)
            for t in rows:
                fid = drive_id(t.get("source_url"))
                if not fid:
                    continue
                try:
                    drive.move_file(fid, hold)
                    moved += 1
                except Exception as e:                            # noqa: BLE001
                    print(f"  ⚠ ย้ายไม่สำเร็จ {t['file_name']}: {str(e)[:80]}")
            print(f"\nย้ายรูปไป {r['run']['week']}/{HOLD_DIR}/ แล้ว {moved} ไฟล์ (ไม่ได้ลบ)")

    why = f"ทิ้ง: คู่ผิดจาก pool run #{a.run} (ครึ่งบน/ครึ่งล่างคนละเที่ยว)"
    n = db.void_trips([t["id"] for t in rows], why)
    print(f"เอาออกจากคิวตรวจและไฟล์ส่งงาน {n} แถว — แถวยังอยู่ กู้คืนได้ด้วย db.restore_voided(id)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
