# -*- coding: utf-8 -*-
"""Where the Drive space goes, by week and by kind of folder. Read-only.

Drive was close to full before reopening (Fiat, 2026-11-05). Space counts against the OWNER of a
file, so the question is not only "how big is a week" but "how much of it is the system
account's own": the stitched pairs the pool writes, the customer pictures, the workbooks. The
pictures Ops upload stay Ops' even after the round moves them into _ใช้แล้ว, so deleting those
frees nothing for the system account.

Nothing is moved or deleted. The log names weeks and folder kinds only, never a file or a
rider: the repository is public, and so are its Actions logs.

    python drive_usage.py                 # Drive from env (DRIVE_OAUTH_TOKEN_JSON, folder ids)
"""
import argparse
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

FOLDER = "application/vnd.google-apps.folder"

# folder name (as Drive shows it) -> kind, for folders the tools make inside a week
INBOX_KINDS = {
    "_ใช้แล้ว": "กอง: ต้นฉบับที่จับคู่แล้ว (_ใช้แล้ว)",
    "_รายงาน": "กอง: รายงาน (_รายงาน)",
    "_พร้อมอ่าน": "รอลงที่ (_พร้อมอ่าน)",
    "_ทิ้ง-กดลบ": "รูปที่คนกดลบ (_ทิ้ง-กดลบ)",
}
EXPORT_KINDS = {
    "_แทนที่แล้ว": "รูปส่งลูกค้าที่ถูกแทนที่ (_แทนที่แล้ว)",
}
RIDER = "โฟลเดอร์ไรเดอร์ (ต้นฉบับ + รูปคู่ที่กองต่อ)"
POOL = "กอง: รูปที่ยังไม่ได้จับคู่"
CUSTOMER = "รูปส่งลูกค้า"


def inbox_week(name):
    """'Week 24-30 Aug' or '2026-W35' -> '2026-W35', else None."""
    import ingest
    clean = ingest.clean_name(name)
    rng = ingest.parse_range(clean) if clean.lower().startswith("week") else None
    if rng:
        return ingest.week_label(rng[0].isoformat())
    bounds = ingest.week_bounds(name)
    return ingest.week_label(bounds[0].isoformat()) if bounds else None


def kind_in_inbox_week(parts):
    """Kind of a file at <week>/<parts...>/file. parts are the folder names below the week."""
    import ingest
    if not parts:
        return "ไฟล์ที่วางตรงในโฟลเดอร์สัปดาห์"
    for p in parts:
        if p.strip() in INBOX_KINDS:
            return INBOX_KINDS[p.strip()]
    top = ingest.clean_name(parts[0]).lower()
    if top in ingest.POOL_FOLDER_NAMES:
        return POOL
    if top in ingest.CATEGORIES:
        return RIDER
    return "โฟลเดอร์อื่นในสัปดาห์" if not parts[0].startswith("_") else f"โฟลเดอร์ของระบบ {parts[0].strip()}"


def classify(root, parts):
    """(week or None, kind) for a file under the Inbox ('inbox') or the Exports ('exports') root.
    parts are the folder names from the root down to the file's folder."""
    if root == "exports":
        if not parts:
            return None, "ไฟล์ Excel และไฟล์อื่นที่ราก Exports"
        week = parts[0] if parts[0].startswith("20") and "-W" in parts[0] else None
        if week:
            kind = next((EXPORT_KINDS[p.strip()] for p in parts[1:] if p.strip() in EXPORT_KINDS), CUSTOMER)
            return week, kind
        return None, f"Exports: {parts[0].strip()}" if parts[0].startswith("_") else "Exports: ชุดงานแก้/โฟลเดอร์อื่น"
    if not parts:
        return None, "ไฟล์ที่ราก Inbox"
    week = inbox_week(parts[0])
    if week is None:
        return None, "Inbox: โฟลเดอร์ที่ไม่ใช่สัปดาห์"
    return week, kind_in_inbox_week(parts[1:])


def walk(children, root_id, skip_ids=(), workers=8):
    """Every file under root_id as (folder names below the root, entry). children(folder_id)
    returns entries {id, name, folder, bytes, mine}. Folders in skip_ids are not entered."""
    out, frontier = [], [((), root_id)]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        while frontier:
            listed = list(ex.map(lambda f: (f[0], children(f[1])), frontier))
            frontier = []
            for parts, entries in listed:
                for e in entries:
                    if e["folder"]:
                        if e["id"] not in skip_ids:
                            frontier.append((parts + (e["name"],), e["id"]))
                    else:
                        out.append((parts, e))
    return out


def tally(files, root):
    """{(week, kind): {files, bytes, mine}} for files walked from one root ('inbox' or 'exports')."""
    t = defaultdict(lambda: {"files": 0, "bytes": 0, "mine": 0})
    for parts, e in files:
        week, kind = classify(root, parts)
        cell = t[(week, kind)]
        cell["files"] += 1
        cell["bytes"] += e["bytes"]
        cell["mine"] += e["bytes"] if e["mine"] else 0
    return t


def gb(n):
    return f"{n / 1024 ** 3:,.2f}"


def report(quota, tallies, closed):
    lines = ["# พื้นที่ Drive แยกตามสัปดาห์", ""]
    if quota:
        lim = int(quota.get("limit") or 0)
        used = int(quota.get("usage") or 0)
        lines += [f"- บัญชีระบบ ใช้ไป **{gb(used)} GB**" + (f" จาก {gb(lim)} GB ({used / lim:.0%})" if lim else
                                                            " (ไม่มีเพดาน หรือเป็น Shared drive)"),
                  f"- ในถังขยะ {gb(int(quota.get('usageInDriveTrash') or 0))} GB "
                  f"(ยังนับเป็นพื้นที่ที่ใช้ จนกว่าจะล้างถังขยะ)", ""]
    lines += ["| สัปดาห์ | สถานะ | ชนิด | ไฟล์ | GB ทั้งหมด | GB ของบัญชีระบบ |", "|---|---|---|---:|---:|---:|"]
    merged = defaultdict(lambda: {"files": 0, "bytes": 0, "mine": 0})
    for t in tallies:
        for key, c in t.items():
            for k in c:
                merged[key][k] += c[k]
    order = sorted(merged.items(), key=lambda kv: (kv[0][0] or "~", -kv[1]["bytes"]))
    free_closed = 0
    for (week, kind), c in order:
        state = "ไม่มีสัปดาห์" if week is None else ("ปิดแล้ว" if week in closed else "ยังเปิด")
        if week in closed:
            free_closed += c["mine"]
        lines.append(f"| {week or '-'} | {state} | {kind} | {c['files']:,} | {gb(c['bytes'])} | {gb(c['mine'])} |")
    total = sum(c["bytes"] for c in merged.values())
    mine = sum(c["mine"] for c in merged.values())
    lines += ["", f"- รวมทุกไฟล์ใต้ Inbox และ Exports **{gb(total)} GB**, เป็นของบัญชีระบบ **{gb(mine)} GB**",
              f"- ส่วนของบัญชีระบบในสัปดาห์ที่ปิดแล้ว **{gb(free_closed)} GB**: นี่คือพื้นที่สูงสุดที่ลบสัปดาห์ที่ปิดแล้วจะคืนให้บัญชีระบบได้",
              "- ไฟล์ที่ไม่ใช่ของบัญชีระบบ (ต้นฉบับที่ Ops อัป) ลบแล้วคืนพื้นที่ให้เจ้าของไฟล์ ไม่ใช่บัญชีระบบ"]
    if total and not mine:
        lines.append("- ⚠ ไม่มีไฟล์ไหนเป็นของบัญชีระบบเลย: โฟลเดอร์น่าจะอยู่ใน Shared drive ซึ่งนับพื้นที่ของ Shared drive แทน")
    return "\n".join(lines)


def drive_children(drive):
    def children(folder_id):
        rows = drive._list(f"'{folder_id}' in parents and trashed=false",
                           "id, name, mimeType, quotaBytesUsed, size, ownedByMe")
        return [{"id": r["id"], "name": r["name"], "folder": r["mimeType"] == FOLDER,
                 "bytes": int(r.get("quotaBytesUsed") or r.get("size") or 0),
                 "mine": bool(r.get("ownedByMe"))} for r in rows]
    return children


def main(argv=None):
    ap = argparse.ArgumentParser(description="พื้นที่ Drive แยกตามสัปดาห์และชนิดโฟลเดอร์ (อ่านอย่างเดียว)")
    ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    import config
    import db
    from drive_client import DriveClient
    inbox, exports = config.DRIVE_INBOX_FOLDER_ID, config.DRIVE_EXPORTS_FOLDER_ID
    if not inbox:
        sys.exit("ไม่พบ DRIVE_INBOX_FOLDER_ID")
    drive = DriveClient(config.GOOGLE_SERVICE_ACCOUNT, config.DRIVE_OAUTH_TOKEN)
    quota = drive.svc.about().get(fields="storageQuota").execute().get("storageQuota")
    closed = set()
    if os.environ.get("DATABASE_URL"):
        import ingest
        closed = {ingest.week_label(d) for d in db.closed_weeks()}
    children = drive_children(drive)
    tallies = [tally(walk(children, inbox, skip_ids={exports} if exports else ()), "inbox")]
    if exports:
        tallies.append(tally(walk(children, exports), "exports"))
    text = report(quota, tallies, closed)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
