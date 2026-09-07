# -*- coding: utf-8 -*-
"""Put an album back the way it arrived, so its pictures can be looked at as halves again.

Ploy145 paired 139 trips and only 26 of them were adjacent; the rest reached 2 to 79 pictures
across the album for a partner with a matching fare. Two of those halves, opened side by side,
were taken fourteen minutes apart with the battery five points higher on the lower one — the
figures agreed because the trip was a promotion where Grab took nothing, and ฿24 with a zero cut
is not a rare shape in an album of 145. So the album is going back to Ops' own two halves, to be
read again as training data rather than delivered as trips.

Nothing was ever deleted: joining a pair moves both originals to Pool/_ใช้แล้ว/<album>/, so the
album can be reassembled exactly. The stitched pictures go to Week/_ดึงกลับ/<album>/, also moved.

The rows are the part that cannot simply be parked. A batch result sets status='done' when it
lands, without asking whether anybody voided the row while it was away — so a row left behind
would come back to life next round, attached to a picture that no longer exists. Removing them
is a separate switch for that reason, and it says out loud what it is about to remove.

    python revert_album.py --week "Week 31 Aug-6 Sep" --album "2W-Win Ploy145"
"""
import argparse
import sys
from collections import Counter

import config
import db

HOLD_DIR = "_ดึงกลับ"
USED_DIR = "_ใช้แล้ว"
POOL_NAMES = ("pool", "กอง")


def week_folder(drive, inbox_id, week_name):
    return next((f for f in drive.list_folders(inbox_id)
                 if f["name"].strip() == week_name.strip()), None)


def pool_folder(drive, week_id):
    return next((f for f in drive.list_folders(week_id)
                 if f["name"].strip().lower() in POOL_NAMES), None)


def stitched_in_week(drive, week_id, album):
    """[(rider folder name, image)] — the joined pictures this album produced.

    They carry the album in their own name ('2W-Win Ploy145_146+225_฿45.jpg'), which is what
    makes them findable at all once they are scattered across riders and vehicle groups."""
    want = f"{album}_"
    out = []
    for cat in drive.list_folders(week_id):
        n = cat["name"].strip()
        if n.lower() in POOL_NAMES or n.startswith("_"):
            continue
        for rider in drive.list_folders(cat["id"]):
            for img in drive.list_images(rider["id"]):
                if img["name"].startswith(want):
                    out.append((f"{n}/{rider['name']}", img))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="คืนอัลบั้มกลับเป็นรูปครึ่งเดิม (รายงานอย่างเดียวถ้าไม่ใส่ --apply)")
    ap.add_argument("--week", required=True, help='เช่น "Week 31 Aug-6 Sep"')
    ap.add_argument("--album", action="append", required=True, help="ชื่ออัลบั้ม (ใส่ซ้ำได้)")
    ap.add_argument("--apply", action="store_true", help="ย้ายไฟล์จริงบน Drive")
    ap.add_argument("--delete-rows", action="store_true",
                    help="ลบแถวที่สร้างจากรูปที่ต่อแล้วด้วย (ต้องใส่คู่กับ --apply)")
    a = ap.parse_args(argv)
    db.init_db()

    import roster
    drive = roster._drive()
    wk = week_folder(drive, config.DRIVE_INBOX_FOLDER_ID, a.week)
    if wk is None:
        print(f"✗ ไม่พบสัปดาห์ {a.week!r} ใน Inbox")
        return 1
    pool = pool_folder(drive, wk["id"])
    if pool is None:
        print(f"✗ ไม่พบโฟลเดอร์กองใน {a.week!r}")
        return 1
    used_root = next((f for f in drive.list_folders(pool["id"])
                      if f["name"].strip() == USED_DIR), None)

    plan = []
    for album in a.album:
        used = next((f for f in drive.list_folders(used_root["id"])
                     if f["name"].strip() == album.strip()), None) if used_root else None
        originals = drive.list_images(used["id"]) if used else []
        stitched = stitched_in_week(drive, wk["id"], album)
        rows = db.trips_from_album(f"{album}_")
        plan.append({"album": album, "used": used, "originals": originals,
                     "stitched": stitched, "rows": rows})

        st = Counter(str(r["status"]) for r in rows)
        committed = sum(1 for r in rows if r["committed"])
        print(f"\n[{album}]")
        print(f"  ต้นฉบับที่เก็บไว้ใน {USED_DIR}/: {len(originals)} ใบ"
              + ("" if used else "  ← ไม่พบโฟลเดอร์"))
        print(f"  รูปที่ต่อแล้วในโฟลเดอร์ไรเดอร์: {len(stitched)} ใบ")
        print(f"  แถวที่สร้างจากรูปพวกนี้: {len(rows)} แถว · "
              + (" · ".join(f"{k} {v}" for k, v in sorted(st.items())) or "ไม่มี")
              + f" · ลงไฟล์ส่งลูกค้าแล้ว {committed}")
        who = Counter(x[0] for x in stitched)
        for folder, n in who.most_common(6):
            print(f"      {folder}: {n} ใบ")
        if len(who) > 6:
            print(f"      … อีก {len(who) - 6} โฟลเดอร์")

    tot_o = sum(len(p["originals"]) for p in plan)
    tot_s = sum(len(p["stitched"]) for p in plan)
    tot_r = sum(len(p["rows"]) for p in plan)
    tot_c = sum(1 for p in plan for r in p["rows"] if r["committed"])
    print(f"\nรวม: คืนต้นฉบับ {tot_o} ใบ · เก็บรูปที่ต่อแล้ว {tot_s} ใบ · แถวที่เกี่ยวข้อง {tot_r}"
          f" (ลงไฟล์แล้ว {tot_c})")
    if tot_o != tot_s * 2:
        print(f"  ⚠ ต้นฉบับควรเป็นสองเท่าของรูปที่ต่อแล้ว ({tot_s * 2}) แต่ได้ {tot_o}"
              " — อาจมีบางคู่ถูกย้ายหรือลบไปแล้ว")

    if not a.apply:
        print("\n(รายงานอย่างเดียว — ยังไม่ได้แตะอะไร · ใส่ --apply เพื่อทำจริง)")
        return 0

    moved_back = held = 0
    for p in plan:
        album_dir = drive.ensure_folder(pool["id"], p["album"])
        for img in p["originals"]:
            try:
                drive.move_file(img["id"], album_dir)
                moved_back += 1
            except Exception as e:                              # noqa: BLE001
                print(f"  ⚠ คืนไม่สำเร็จ {img['name']}: {str(e)[:70]}")
        hold = drive.ensure_folder(drive.ensure_folder(wk["id"], HOLD_DIR), p["album"])
        for _folder, img in p["stitched"]:
            try:
                drive.move_file(img["id"], hold)
                held += 1
            except Exception as e:                              # noqa: BLE001
                print(f"  ⚠ เก็บไม่สำเร็จ {img['name']}: {str(e)[:70]}")
    print(f"\nคืนต้นฉบับกลับเข้ากอง {moved_back} ใบ · เก็บรูปที่ต่อแล้วไว้ที่ {a.week}/{HOLD_DIR}/ {held} ใบ"
          " (ไม่ได้ลบ)")

    if not a.delete_rows:
        print(f"\n⚠ ยังไม่ได้แตะแถว {tot_r} แถว — ผลจาก batch ที่ค้างอยู่จะกลับมาเขียนทับให้เป็น done"
              " แล้วไหลเข้าไฟล์ส่งลูกค้า ทั้งที่รูปไม่อยู่แล้ว")
        print("  ใส่ --delete-rows ด้วยถ้าจะเอาออก")
        return 0
    ids = [r["id"] for p in plan for r in p["rows"]]
    gone = db.delete_trips(ids)
    print(f"\nลบแถวที่สร้างจากรูปที่ต่อแล้ว {sum(1 for r in gone if r['found'])} แถว"
          " (พร้อมบันทึกว่าเคยอ่านไฟล์นั้น — รูปครึ่งเดิมจึงถูกอ่านใหม่ได้)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
