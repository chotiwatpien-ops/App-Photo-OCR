# -*- coding: utf-8 -*-
"""Move closed weeks' system-made copies on Drive to the trash, to free the system account's space.

Ops confirmed on 2026-11-05 that these kinds may go, for the closed weeks W33–W39 (drive_usage
measured 9.49 GB of them, the account at 94% of 15 GB):
    customer pictures and their _แทนที่แล้ว, the stitched pairs in rider folders, _เติมงาน Ops,
    _ซ้ำ, and the system account's own files in _ใช้แล้ว.

Only files the system account owns are touched: anything Ops uploaded stays theirs and stays put.
Only weeks that are closed in the database AND named in --weeks. Files go to the trash, where
Drive keeps them 30 days; the space comes back once the trash is emptied. Without --apply it only
reports. Safe to run again: trashed files are no longer listed, so a second run picks up where a
failed one stopped.

    python clear_drive.py --weeks 2026-W33,2026-W34,...            # report
    python clear_drive.py --weeks ... --apply                      # trash
"""
import argparse
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import drive_usage as du

KINDS = {
    du.CUSTOMER,
    du.EXPORT_KINDS["_แทนที่แล้ว"],
    du.RIDER,
    du.INBOX_KINDS["_ใช้แล้ว"],
    "โฟลเดอร์ของระบบ _เติมงาน Ops",
    "โฟลเดอร์ของระบบ _ซ้ำ",
}


def plan(inbox_files, export_files, weeks):
    """(files to trash [(week, kind, id, bytes)], exports week folders to trash whole).

    An Exports week folder holding only the system account's files is trashed as one folder,
    one call instead of ~5,000; any other folder is cleared file by file, the system's files only."""
    picked = []
    for root, files in (("inbox", inbox_files), ("exports", export_files)):
        for parts, e in files:
            week, kind = du.classify(root, parts)
            if week in weeks and kind in KINDS and e["mine"]:
                picked.append((root, parts, week, kind, e))
    whole = set()
    by_folder = defaultdict(list)
    for parts, e in export_files:
        if parts and parts[0] in weeks:
            by_folder[parts[0]].append(e)
    for week, entries in by_folder.items():
        if all(e["mine"] for e in entries):
            whole.add(week)
    files = [(week, kind, e["id"], e["bytes"]) for root, parts, week, kind, e in picked
             if not (root == "exports" and parts and parts[0] in whole)]
    folder_bytes = {w: sum(e["bytes"] for e in by_folder[w]) for w in whole}
    return files, folder_bytes, picked


def summary(picked, weeks, applied, failed=0):
    t = defaultdict(lambda: [0, 0])
    for _root, _parts, week, kind, e in picked:
        t[(week, kind)][0] += 1
        t[(week, kind)][1] += e["bytes"]
    lines = [f"# {'ย้ายไปถังขยะแล้ว' if applied else 'แผน (ยังไม่ได้ลบ)'}: ไฟล์ของบัญชีระบบ สัปดาห์ {', '.join(sorted(weeks))}", "",
             "| สัปดาห์ | ชนิด | ไฟล์ | GB |", "|---|---|---:|---:|"]
    for (week, kind), (n, b) in sorted(t.items()):
        lines.append(f"| {week} | {kind} | {n:,} | {du.gb(b)} |")
    total = sum(b for _n, b in t.values())
    lines += ["", f"รวม **{sum(n for n, _b in t.values()):,} ไฟล์ · {du.gb(total)} GB**"]
    if applied:
        lines.append(f"- ล้มเหลว {failed:,} ไฟล์ (กดรันซ้ำได้ ไฟล์ที่ย้ายแล้วจะไม่ถูกนับอีก)" if failed else "- ไม่มีไฟล์ที่ล้มเหลว")
        lines.append("- พื้นที่จะคืนเมื่อล้างถังขยะของบัญชีนี้ (ใน Drive: ถังขยะ → ล้างถังขยะ)")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="ย้ายไฟล์ของบัญชีระบบในสัปดาห์ที่ปิดแล้วไปถังขยะ")
    ap.add_argument("--weeks", required=True, help="เช่น 2026-W33,2026-W34")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    import config
    import db
    import ingest
    from drive_client import DriveClient
    if not os.environ.get("DATABASE_URL"):
        sys.exit("ต้องมี DATABASE_URL เพื่อเช็คว่าสัปดาห์ปิดแล้วจริง")
    asked = {w.strip() for w in a.weeks.split(",") if w.strip()}
    closed = {ingest.week_label(d) for d in db.closed_weeks()}
    weeks = asked & closed
    if asked - closed:
        print(f"⚠ ข้ามสัปดาห์ที่ยังไม่ปิด: {', '.join(sorted(asked - closed))}")
    if not weeks:
        sys.exit("ไม่มีสัปดาห์ที่ปิดแล้วให้ลบ")
    inbox, exports = config.DRIVE_INBOX_FOLDER_ID, config.DRIVE_EXPORTS_FOLDER_ID
    drive = DriveClient(config.GOOGLE_SERVICE_ACCOUNT, config.DRIVE_OAUTH_TOKEN)
    children = du.drive_children(drive)
    inbox_files = du.walk(children, inbox, skip_ids={exports} if exports else ())
    export_files = du.walk(children, exports) if exports else []
    files, folder_bytes, picked = plan(inbox_files, export_files, weeks)
    failed = 0
    if a.apply:
        def trash(fid):
            try:
                drive._retry(lambda: drive.svc.files().update(
                    fileId=fid, body={"trashed": True}, supportsAllDrives=True).execute(), tries=5)
                return True
            except Exception as e:  # noqa: BLE001 - one stubborn file must not stop the rest
                print(f"  ✗ {fid}: {str(e)[:120]}")
                return False
        week_ids = {f["name"]: f["id"] for f in drive.list_folders(exports)} if exports else {}
        for w in sorted(folder_bytes):
            ok = trash(week_ids[w])
            failed += 0 if ok else 1
            print(f"  {'✓' if ok else '✗'} Exports/{w} ทั้งโฟลเดอร์ ({du.gb(folder_bytes[w])} GB)")
        with ThreadPoolExecutor(max_workers=6) as ex:
            results = list(ex.map(trash, [f[2] for f in files]))
        failed += results.count(False)
    text = summary(picked, weeks, a.apply, failed)
    print(text)
    out = os.environ.get("GITHUB_STEP_SUMMARY")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
