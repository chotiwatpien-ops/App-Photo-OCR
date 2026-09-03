# -*- coding: utf-8 -*-
"""Phase 2 pool: whole LINE albums in, paired trips out.

Layout on Drive — the pool lives inside the week it belongs to:
    Inbox/
      Week 17-23 Aug/            <- the week the Agent is working on (ingest reads its rider folders)
        2 W Saver/ …             <- the usual category / admin / rider folders — untouched
        Pool/                    <- ingest skips this one (ingest.POOL_FOLDER_NAMES)
          2W/                    <- vehicle group, as the Agent sorted it
            LINE_ALBUM_2W93 kanjana standard/   <- album folder, files named as LINE saved them
              LINE_ALBUM_2W93 kanjana standard_260902_1.jpg ...
          4W/
          _รายงาน/               <- written by this job: stitched previews + the report text
(Alternative: one separate folder DRIVE_POOL_FOLDER_ID holding <Week …>/<group>/<album>/.)

What a run does (mode "report", the default):
  1. lists every album, downloads the images
  2. drops exact duplicates (same bytes) across the whole pool
  3. tells long screenshots from halves and pairs the halves — free local OCR, no Gemini
     (see pairing.py)
  4. writes a report: per album how many pairs, what is left and why; stitched previews so a
     person can check the pairs by eye
  5. records the run in the database (pool_runs) so the web app can show it
In report mode nothing in the pool is moved, renamed or deleted. With --move (mode "move"):
paired trips become ONE stitched image in Week/<vehicle category>/ and their two originals go to
Pool/_ใช้แล้ว/<album>/ (moved, never deleted); long screenshots move as they are into
Week/<vehicle category>/; anything unpaired or of unknown vehicle type stays where it is, so a
re-run only works on what is still open. The category comes from the service chip on the photo
(Bike/Car, Saver/Standard), else the album name, else the album's majority — see CATEGORY_FALLBACK.
Distributing into rider folders (the roster + 21-per-rider quota) is the next step, not here.

    python pool.py                      # every week folder in the pool, report only
    python pool.py --week "Week 17-23 Aug" --album "kanjana" --move
    python pool.py --local <folder>     # same layout on disk (tests)
"""
import argparse
import hashlib
import io
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import config
import pairing


def log(msg):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode(), flush=True)


REPORT_DIR = "_รายงาน"
POOL_FOLDER_NAMES = ("pool", "กอง")
# category folders that do not exist in the Inbox (yet) and where those trips go instead —
# the team runs no "4 W Saver" group, so a Saver Car trip files under 4 W Standard (2026-09-03)
CATEGORY_FALLBACK = {"4 W Saver": "4 W Standard"}


# --- 1. what is in the pool ---------------------------------------------------------------
def _albums_in(drive, pool_folder, week_name):
    """Albums under one week's pool folder: <group>/<album>/images (images lying directly in
    the group folder count as one album). Each album remembers the pool folder so the report
    can be written next to it."""
    albums = []
    loose = drive.list_images(pool_folder["id"])          # photos dropped straight into Pool/
    if loose:
        albums.append({"week": week_name, "group": "", "pool_id": pool_folder["id"],
                       "album": "(กองรวม)", "folder_id": pool_folder["id"], "images": loose})
    for grp in sorted(drive.list_folders(pool_folder["id"]), key=lambda f: f["name"]):
        if grp["name"].startswith("_"):
            continue
        base = {"week": week_name, "group": grp["name"], "pool_id": pool_folder["id"]}
        direct = drive.list_images(grp["id"])
        if direct:
            albums.append({**base, "album": grp["name"], "folder_id": grp["id"], "images": direct})
        for alb in sorted(drive.list_folders(grp["id"]), key=lambda f: f["name"]):
            if alb["name"].startswith("_"):
                continue
            imgs = drive.list_images(alb["id"])
            if imgs:
                albums.append({**base, "album": alb["name"], "folder_id": alb["id"], "images": imgs})
    return albums


def _wanted(week_name, only_week):
    return not week_name.startswith("_") and (not only_week or week_name.strip() == only_week.strip())


def scan_inbox(drive, inbox_id, only_week=None):
    """Inbox/<Week …>/Pool/<group>/<album>/ — the production layout."""
    albums = []
    for wk in sorted(drive.list_folders(inbox_id), key=lambda f: f["name"]):
        if not wk["name"].strip().lower().startswith("week") or not _wanted(wk["name"], only_week):
            continue
        for child in drive.list_folders(wk["id"]):
            if child["name"].strip().lower() in POOL_FOLDER_NAMES:
                for a in _albums_in(drive, child, wk["name"]):
                    a["week_id"] = wk["id"]
                    albums.append(a)
    return albums


def scan(drive, pool_id, only_week=None):
    """<pool folder>/<Week …>/<group>/<album>/ — the alternative, separate-folder layout."""
    albums = []
    for wk in sorted(drive.list_folders(pool_id), key=lambda f: f["name"]):
        if _wanted(wk["name"], only_week):
            for a in _albums_in(drive, wk, wk["name"]):
                a["week_id"] = wk["id"]
                albums.append(a)
    return albums


def fetch(drive, images, workers, errors):
    """id -> bytes for every image; failures are reported, not fatal."""
    def one(img):
        try:
            return img["id"], drive.download(img["id"])
        except Exception as e:  # noqa: BLE001
            errors.append(f"โหลดไม่ได้ {img['name']}: {str(e)[:120]}")
            return img["id"], None
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return {k: v for k, v in ex.map(one, images) if v is not None}


# --- 2-3. duplicates + pairing ------------------------------------------------------------
def analyse(albums, data, workers):
    report = {"albums": [], "duplicates": [], "errors": []}
    seen = {}                                   # md5 -> "album/name" of the first copy
    todo = []                                   # (album index, image) that need inspecting
    for ai, alb in enumerate(albums):
        alb["_keep"] = []
        for img in sorted(alb["images"], key=lambda i: pairing._natural(i["name"])):
            raw = data.get(img["id"])
            if raw is None:
                continue
            h = hashlib.md5(raw).hexdigest()
            where = f"{alb['album']}/{img['name']}"
            if h in seen:
                report["duplicates"].append({"week": alb["week"], "group": alb["group"],
                                             "file": where, "same_as": seen[h]})
                continue
            seen[h] = where
            alb["_keep"].append(img)
            todo.append((ai, img))

    def inspect(item):
        ai, img = item
        try:
            return img["id"], pairing.inspect(data[img["id"]])
        except Exception as e:  # noqa: BLE001
            report["errors"].append(f"ตรวจรูปไม่ได้ {img['name']}: {str(e)[:120]}")
            return img["id"], None
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        info = dict(ex.map(inspect, todo))

    def target_for(img_id, album_name):
        """Category folder for a trip: the chip on its top/long image, else the album name."""
        try:
            wheels, tier = pairing.vehicle_type(data[img_id])
        except Exception:  # noqa: BLE001
            wheels, tier = None, None
        aw, at = pairing.type_from_album(album_name)
        cat = pairing.category_folder(wheels or aw, tier or at)
        return CATEGORY_FALLBACK.get(cat, cat)

    for alb in albums:
        items = [(img["name"], info[img["id"]]) for img in alb["_keep"] if info.get(img["id"])]
        by_name = {img["name"]: img for img in alb["_keep"]}
        pairs, leftovers = pairing.pair_album(items)
        d = dict(items)
        entry = {
            "week": alb["week"], "group": alb["group"], "album": alb["album"],
            "n_images": len(alb["images"]),
            "n_duplicates": len(alb["images"]) - len(alb["_keep"]),
            "long": [{"file": n, "id": by_name[n]["id"], "target": target_for(by_name[n]["id"], alb["album"])}
                     for n, i in items if i["role"] == "long"],
            "pairs": [{"top": t, "bottom": b, "amount": d[t]["amount"], "distance": dist,
                       "top_id": by_name[t]["id"], "bottom_id": by_name[b]["id"],
                       "target": target_for(by_name[t]["id"], alb["album"])} for t, b, dist in pairs],
            "leftovers": [{"file": n, "role": d[n]["role"], "amount": d[n]["amount"],
                           "why": ("อ่านยอดไม่ออก" if d[n]["amount"] is None and d[n]["role"] == "top"
                                   else "ไม่มีคู่ที่ยอดตรง")} for n in leftovers],
        }
        # a chip the OCR could not read: borrow the type most of that LINE album's other trips show
        groups = {}
        for x in entry["pairs"] + entry["long"]:
            key = pairing.album_of(x.get("top") or x.get("file"))
            groups.setdefault(key, []).append(x)
        for key, xs in groups.items():
            known = [x["target"] for x in xs if x["target"]]
            if known and len(known) >= len(xs) / 2:
                majority = max(set(known), key=known.count)
                for x in xs:
                    if not x["target"]:
                        x["target"] = CATEGORY_FALLBACK.get(majority, majority)
                        x["target_from"] = "อัลบั้มเดียวกัน"
        report["albums"].append(entry)
    t = {"n_images": sum(a["n_images"] for a in report["albums"]),
         "n_duplicates": len(report["duplicates"]),
         "n_long": sum(len(a["long"]) for a in report["albums"]),
         "n_pairs": sum(len(a["pairs"]) for a in report["albums"]),
         "n_leftover": sum(len(a["leftovers"]) for a in report["albums"])}
    halves = t["n_images"] - t["n_duplicates"] - t["n_long"]
    t["pair_rate"] = round(100 * 2 * t["n_pairs"] / halves) if halves else None
    report["totals"] = t
    return report


# --- 4. the report ------------------------------------------------------------------------
def render(report):
    t = report["totals"]
    mode = "ย้ายจริง" if report.get("mode") == "move" else "รายงานอย่างเดียว ไม่ย้ายไฟล์"
    lines = [f"จัดกอง ({mode}) · {report.get('started_at', '')}",
             f"รูปทั้งหมด {t['n_images']} · ซ้ำเป๊ะ {t['n_duplicates']} · รูปยาว {t['n_long']} · "
             f"จับคู่ได้ {t['n_pairs']} คู่" + (f" ({t['pair_rate']}% ของครึ่งรูป)" if t["pair_rate"] is not None else "")
             + f" · ค้าง {t['n_leftover']}" + (f" · ย้ายแล้ว {t['n_moved']}" if "n_moved" in t else ""), ""]
    for a in report["albums"]:
        lines.append(f"[{a['week']} / {a['group']}] {a['album']}: {a['n_images']} รูป · ซ้ำ {a['n_duplicates']} · "
                     f"ยาว {len(a['long'])} · คู่ {len(a['pairs'])} · ค้าง {len(a['leftovers'])}")
        for p in a["pairs"]:
            lines.append(f"    คู่  {p['top']}  +  {p['bottom']}   ฿{p['amount']:g}"
                         + ("" if p["distance"] == 1 else f"  (ห่าง {p['distance']})")
                         + f"  → {p.get('target') or 'ไม่รู้ประเภทรถ'}"
                         + (f"  ✔ {p['moved']}" if "/" in p.get("moved", "") else ""))
        for l in a["long"]:
            lines.append(f"    ยาว {l['file']}  → {l.get('target') or 'ไม่รู้ประเภทรถ'}"
                         + ("  ✔ ย้ายแล้ว" if "/" in l.get("moved", "") else ""))
        for l in a["leftovers"]:
            amt = "" if l["amount"] is None else f" ฿{l['amount']:g}"
            lines.append(f"    ค้าง {l['file']}  ({'ครึ่งบน' if l['role'] == 'top' else 'ครึ่งล่าง'}{amt}) — {l['why']}")
        lines.append("")
    if report["duplicates"]:
        lines.append("รูปซ้ำเป๊ะ (เก็บใบแรก ไม่นับใบหลัง):")
        lines += [f"    {d['file']}  =  {d['same_as']}" for d in report["duplicates"]]
        lines.append("")
    if report["errors"]:
        lines.append("ปัญหา:")
        lines += [f"    {e}" for e in report["errors"]]
    return "\n".join(lines)


def write_previews(drive, albums, data, report, log=log):
    """Stitched pairs + the text report under <week's pool>/_รายงาน/ so a person can check by
    eye. Writes only into _รายงาน; the album folders are not touched."""
    week_ids = {a["week"]: a["pool_id"] for a in albums}
    stamp = time.strftime("%Y-%m-%d %H%M")
    for wk, wid in week_ids.items():
        rep_dir = drive.ensure_folder(wid, REPORT_DIR)
        n = 0
        for a in report["albums"]:
            if a["week"] != wk or not a["pairs"]:
                continue
            alb_dir = drive.ensure_folder(rep_dir, a["album"])
            if a["group"] and a["group"] != a["album"]:          # only nest when there is a real group level
                alb_dir = drive.ensure_folder(drive.ensure_folder(rep_dir, a["group"]), a["album"])
            for i, p in enumerate(a["pairs"], 1):
                img = pairing.stitch(io.BytesIO(data[p["top_id"]]), io.BytesIO(data[p["bottom_id"]]))
                buf = io.BytesIO()
                img.save(buf, "JPEG", quality=88)
                tn, bn = (x.rsplit("_", 1)[1].rsplit(".", 1)[0] for x in (p["top"], p["bottom"]))
                try:
                    drive.upload_file(alb_dir, f"{i:03d}_฿{p['amount']:g}_{tn}+{bn}.jpg", buf.getvalue(), "image/jpeg")
                    n += 1
                except Exception as e:  # noqa: BLE001 — one dropped preview must not lose the report
                    report["errors"].append(f"อัปโหลดรูปตัวอย่างไม่สำเร็จ {p['top']}: {str(e)[:100]}")
        drive.upload_file(rep_dir, f"รายงานจัดกอง {stamp}.txt", render(report).encode("utf-8"), "text/plain")
        log(f"  ↳ {wk}/{REPORT_DIR}: รูปที่ต่อแล้ว {n} ใบ + รายงาน")


# --- 5. move mode ---------------------------------------------------------------------------
USED_DIR = "_ใช้แล้ว"


def apply_moves(drive, albums, data, report, log=log):
    """Paired trips → one stitched image in Week/<category>/; their two originals → Pool/_ใช้แล้ว/
    <album>/ (moved, never deleted). Long screenshots → moved as they are into Week/<category>/.
    Anything unpaired or of unknown vehicle type stays exactly where it is."""
    by_key = {(a["week"], a["album"]): a for a in albums}
    moved = 0
    for entry in report["albums"]:
        alb = by_key[(entry["week"], entry["album"])]
        week_id, pool_id = alb["week_id"], alb["pool_id"]
        cats = {}

        def cat_dir(name):
            if name not in cats:
                cats[name] = drive.ensure_folder(week_id, name)
            return cats[name]

        used_dir = None
        n = 0
        for p in entry["pairs"]:
            if not p["target"]:
                p["moved"] = "ไม่รู้ประเภทรถ — ยังอยู่ในกอง"
                continue
            img = pairing.stitch(io.BytesIO(data[p["top_id"]]), io.BytesIO(data[p["bottom_id"]]))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=88)
            tn, bn = (re.search(r'(\d+)\.\w+$', x).group(1) for x in (p["top"], p["bottom"]))
            name = f"{entry['album']}_{tn}+{bn}_฿{p['amount']:g}.jpg"
            drive.upload_file(cat_dir(p["target"]), name, buf.getvalue(), "image/jpeg")
            if used_dir is None:
                used_dir = drive.ensure_folder(drive.ensure_folder(pool_id, USED_DIR), entry["album"])
            drive.move_file(p["top_id"], used_dir)
            drive.move_file(p["bottom_id"], used_dir)
            p["moved"] = f"{p['target']}/{name}"
            n += 1
        for l in entry["long"]:
            if not l["target"]:
                l["moved"] = "ไม่รู้ประเภทรถ — ยังอยู่ในกอง"
                continue
            drive.move_file(l["id"], cat_dir(l["target"]))
            l["moved"] = f"{l['target']}/{l['file']}"
            n += 1
        moved += n
        log(f"  ↳ {entry['album']}: ย้ายแล้ว {n} รายการ")
    report["totals"]["n_moved"] = moved
    return moved


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", default="", help="เฉพาะโฟลเดอร์สัปดาห์นี้ในกอง (ว่าง = ทุกสัปดาห์)")
    ap.add_argument("--no-preview", action="store_true", help="ไม่อัปโหลดรูปที่ต่อแล้ว/รายงานขึ้น _รายงาน")
    ap.add_argument("--album", default="", help="เฉพาะอัลบั้มที่ชื่อมีข้อความนี้ (คั่นด้วยจุลภาค) — ว่าง = ทุกอัลบั้ม")
    ap.add_argument("--limit", type=int, default=0, help="จำกัดจำนวนรูปที่ตรวจ (ทดลอง)")
    ap.add_argument("--local", default="", help="โฟลเดอร์ในเครื่องที่มีโครงเหมือน Inbox (ทดสอบ)")
    ap.add_argument("--no-db", action="store_true", help="ไม่บันทึกผลลงฐานข้อมูล")
    ap.add_argument("--move", action="store_true",
                    help="ย้ายจริง: คู่ที่จับได้ → รูปต่อแล้วใน Week/<ประเภทรถ>/ (ต้นฉบับไป Pool/_ใช้แล้ว) · "
                         "รูปยาว → Week/<ประเภทรถ>/ · ที่เหลืออยู่ที่เดิม")
    args = ap.parse_args(argv)

    started = time.strftime("%Y-%m-%d %H:%M:%S")
    if args.local:
        from drive_client import LocalDrive
        drive = LocalDrive(args.local)
        albums = scan_inbox(drive, args.local, args.week or None)
    else:
        from drive_client import DriveClient
        drive = DriveClient(config.GOOGLE_SERVICE_ACCOUNT, config.DRIVE_OAUTH_TOKEN)
        if config.DRIVE_POOL_FOLDER_ID:
            albums = scan(drive, config.DRIVE_POOL_FOLDER_ID, args.week or None)
        elif config.DRIVE_INBOX_FOLDER_ID:
            albums = scan_inbox(drive, config.DRIVE_INBOX_FOLDER_ID, args.week or None)
        else:
            log("ยังไม่ได้ตั้ง DRIVE_INBOX_FOLDER_ID — หยุด")
            return 2
    if args.album:
        want = [w.strip().lower() for w in args.album.split(",") if w.strip()]
        albums = [a for a in albums if any(w in a["album"].lower() for w in want)]
    n_img = sum(len(a["images"]) for a in albums)
    log(f"กอง: {len(albums)} อัลบั้ม · {n_img} รูป" + (f" · เฉพาะ {args.week}" if args.week else ""))
    if args.limit:
        left = args.limit
        for a in albums:
            a["images"] = a["images"][:max(0, left)]
            left -= len(a["images"])
        albums = [a for a in albums if a["images"]]
    errors = []
    t0 = time.time()
    data = fetch(drive, [i for a in albums for i in a["images"]], config.DRIVE_PARALLEL, errors)
    log(f"โหลดแล้ว {len(data)} รูป ใน {time.time() - t0:.0f} วิ")
    t0 = time.time()
    report = analyse(albums, data, config.POOL_PARALLEL)
    report["errors"] = errors + report["errors"]
    report["started_at"] = started
    report["mode"] = "move" if args.move else "report"
    log(f"ตรวจและจับคู่เสร็จใน {time.time() - t0:.0f} วิ")
    if args.move and albums:
        apply_moves(drive, albums, data, report)
    summary = render(report)
    log(summary)
    if albums and args.move:                                  # the stitched files ARE the output; keep the text log
        try:
            for pid in {a["pool_id"] for a in albums}:
                drive.upload_file(drive.ensure_folder(pid, REPORT_DIR),
                                  f"รายงานย้าย {time.strftime('%Y-%m-%d %H%M')}.txt", summary.encode("utf-8"), "text/plain")
        except Exception as e:  # noqa: BLE001
            log(f"อัปโหลดรายงานไม่สำเร็จ: {str(e)[:200]}")
    if albums and not args.no_preview and not args.move:
        try:
            write_previews(drive, albums, data, report)
        except Exception as e:  # noqa: BLE001
            log(f"อัปโหลดรายงานไม่สำเร็จ: {str(e)[:200]}")
            report["errors"].append(f"อัปโหลดรายงานไม่สำเร็จ: {str(e)[:200]}")
    if not args.no_db:
        import db
        db.init_db()
        # the JSON keeps only what the page needs — no file ids
        slim = {k: v for k, v in report.items()}
        slim["albums"] = [{**a, "pairs": [{k: v for k, v in p.items() if not k.endswith("_id")} for p in a["pairs"]],
                           "long": [{k: v for k, v in l.items() if k != "id"} for l in a["long"]]}
                          for a in report["albums"]]
        rid = db.record_pool_run(report["mode"], ",".join(sorted({a["week"] for a in albums})),
                                 report["totals"], summary, slim)
        log(f"บันทึกผลเป็น pool run #{rid}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
