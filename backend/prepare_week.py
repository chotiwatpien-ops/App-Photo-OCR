# -*- coding: utf-8 -*-
"""Make a week's folders in the Drive Inbox before its work arrives.

    Inbox/Week 9-15 Nov/
        Pool/2W/  Pool/4W/            Ops drop the LINE albums here
        2 W Saver/  2 W Standard/  4 W Standard/

Rider folders are not made here: the pool opens one the moment it files a pair for a new
rider (distribute.Allocator). There is no 4 W Saver: a Saver car counts as Standard Car.

Safe to run again. A folder Ops already made is used as it is, however they spelled it (a week
is matched by the dates its name means), and nothing is renamed, moved or deleted.

    python prepare_week.py --from 2026-11-09
"""
import argparse
import sys
from datetime import date, timedelta

GROUPS = ("2W", "4W")
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
CATEGORIES = ("2 W Saver", "2 W Standard", "4 W Standard")


def week_name(d_from):
    """'2026-11-09' -> 'Week 9-15 Nov', spelled as Ops spell it (pool.next_week_name). The month
    names are kept here because importing pool pulls in the OCR libraries, which this
    workflow does not install."""
    d1 = date.fromisoformat(d_from)
    d2 = d1 + timedelta(days=6)
    if d1.month == d2.month:
        return f"Week {d1.day}-{d2.day} {MONTH_ABBR[d2.month - 1]}"
    return f"Week {d1.day} {MONTH_ABBR[d1.month - 1]}-{d2.day} {MONTH_ABBR[d2.month - 1]}"


def _child(drive, parent, wanted):
    """An existing child folder whose cleaned, lower-cased name is in `wanted`."""
    import ingest
    return next((f for f in drive.list_folders(parent)
                 if ingest.clean_name(f["name"]).lower() in wanted), None)


def prepare(drive, inbox_id, d_from, log=print):
    import ingest
    d1 = date.fromisoformat(d_from)
    if d1.weekday() != 0:
        raise ValueError(f"{d_from} ไม่ใช่วันจันทร์ — สัปดาห์ต้องเริ่มวันจันทร์")
    d2 = (d1 + timedelta(days=6)).isoformat()
    made, kept = [], []

    def ensure(parent, name, wanted, path):
        found = _child(drive, parent, wanted)
        if found:
            kept.append(f"{path}{found['name']}")
            return found["id"]
        made.append(f"{path}{name}")
        return drive.ensure_folder(parent, name)

    week = next((f for f in drive.list_folders(inbox_id)
                 if ingest.parse_range(ingest.clean_name(f["name"])) == (d1, date.fromisoformat(d2))), None)
    if week:
        kept.append(week["name"])
        week_id, wname = week["id"], week["name"]
    else:
        wname = week_name(d_from)
        made.append(wname)
        week_id = drive.ensure_folder(inbox_id, wname)
    pool = ensure(week_id, "Pool", set(ingest.POOL_FOLDER_NAMES), f"{wname}/")
    for g in GROUPS:
        ensure(pool, g, {g.lower()}, f"{wname}/Pool/")
    for cat in CATEGORIES:
        ensure(week_id, cat, {cat.lower()}, f"{wname}/")
    for p in made:
        log(f"  + สร้าง {p}")
    for p in kept:
        log(f"  = มีอยู่แล้ว {p}")
    log(f"สัปดาห์ {ingest.week_label(d_from)} ({wname}): สร้างใหม่ {len(made)} · มีอยู่แล้ว {len(kept)}")
    return {"week": wname, "made": made, "kept": kept}


def main(argv=None):
    ap = argparse.ArgumentParser(description="สร้างโฟลเดอร์ของสัปดาห์ใน Inbox ล่วงหน้า")
    ap.add_argument("--from", dest="d_from", required=True, help="วันจันทร์ของสัปดาห์ เช่น 2026-11-09")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    import config
    from drive_client import DriveClient
    if not config.DRIVE_INBOX_FOLDER_ID:
        sys.exit("ไม่พบ DRIVE_INBOX_FOLDER_ID")
    drive = DriveClient(config.GOOGLE_SERVICE_ACCOUNT, config.DRIVE_OAUTH_TOKEN)
    if drive.mode != "oauth":
        sys.exit("ต้องใช้ DRIVE_OAUTH_TOKEN_JSON (service account สร้างโฟลเดอร์ใน Drive ส่วนตัวไม่ได้)")
    prepare(drive, config.DRIVE_INBOX_FOLDER_ID, a.d_from)
    return 0


if __name__ == "__main__":
    sys.exit(main())
