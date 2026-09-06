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
paired trips become ONE stitched image in Week/<vehicle category>/<rider>/ and their two originals
go to Pool/_ใช้แล้ว/<album>/ (moved, never deleted); long screenshots move the same way; anything
unpaired or of unknown vehicle type stays where it is, so a re-run only works on what is still
open. The category comes from the service chip on the photo (Bike/Car, Saver/Standard), else the
album name, else the album's majority — see CATEGORY_FALLBACK. Which rider, and whether a new
folder is opened at all, is distribute.py: the album name says Win / Home / Taxi, Ops' list
supplies the names, and nobody new is drawn while someone is still short of the weekly quota.

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
import distribute
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
    """A week folder this run should look at. Sandbox weeks (config.IGNORE_WEEKS) are skipped
    unless they are named outright with --week, which is how they stay usable for trials."""
    if week_name.startswith("_"):
        return False
    if only_week:
        return week_name.strip() == only_week.strip()
    return not config.week_ignored(week_name)


def scan_inbox(drive, inbox_id, only_week=None):
    """Inbox/<Week …>/Pool/<group>/<album>/ — the production layout."""
    albums = []
    for wk in sorted(drive.list_folders(inbox_id), key=lambda f: f["name"]):
        if not _wanted(wk["name"], only_week):
            continue
        if not only_week and not wk["name"].strip().lower().startswith("week"):
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
def analyse(albums, data, workers, cache=None):
    """cache: optional dict-like {md5: info} of earlier inspect() results — a half left in the
    pool is looked at again every run, and the OCR verdict for the same bytes never changes."""
    report = {"albums": [], "duplicates": [], "errors": []}
    seen = {}                                   # md5 -> "album/name" of the first copy
    todo = []                                   # (album index, image) that need inspecting
    hashes = {}
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
            hashes[img["id"]] = pairing.cache_key(h)   # dedupe on the bytes, cache on the reader too
            alb["_keep"].append(img)
            todo.append((ai, img))

    cache = cache if cache is not None else {}
    fresh = {}

    def inspect(item):
        ai, img = item
        h = hashes[img["id"]]
        if h in cache:
            return img["id"], cache[h]
        try:
            fresh[h] = pairing.inspect(data[img["id"]])
            return img["id"], fresh[h]
        except Exception as e:  # noqa: BLE001
            report["errors"].append(f"ตรวจรูปไม่ได้ {img['name']}: {str(e)[:120]}")
            return img["id"], None
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        info = dict(ex.map(inspect, todo))
    report["ocr_cached"] = len(todo) - len(fresh)
    report["ocr_fresh"] = fresh

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
            "pairs": [{"top": t, "bottom": b, "cut_top": d[t].get("cut_top"),
                       "amount": pairing.agreed_amount(d[t], d[b]), "distance": dist,
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
                img = pairing.stitch(io.BytesIO(data[p["top_id"]]),
                                     io.BytesIO(data[p["bottom_id"]]), cut_top=p.get("cut_top"))
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


def apply_moves(drive, albums, data, report, log=log, allocators=None, issues=None):
    """Paired trips → one stitched image in Week/<category>/<rider>/; their two originals →
    Pool/_ใช้แล้ว/<album>/ (moved, never deleted). Long screenshots → the same rider folder.
    Anything unpaired, of unknown vehicle type, or from an album that does not say what kind of
    driver it belongs to stays exactly where it is."""
    by_key = {(a["week"], a["album"]): a for a in albums}
    allocators = {} if allocators is None else allocators
    issues = [] if issues is None else issues
    moved = 0
    for entry in report["albums"]:
        alb = by_key[(entry["week"], entry["album"])]
        week_id, pool_id = alb["week_id"], alb["pool_id"]
        # folders first (sequential — Drive must not be asked to create the same one twice),
        # then every upload/move in parallel: each item is independent, and Drive's per-call
        # latency, not bandwidth, is what made this phase slow
        # Which rider each trip belongs to is decided here, before anything is uploaded: the
        # allocator carries 'this name is taken' across every album and group of the week, and
        # sharing that between threads would hand one name to two riders.
        kind = distribute.driver_kind(entry["album"])
        if kind is None and (entry["pairs"] or entry["long"]):
            why = (f"อัลบั้ม '{entry['album']}' ไม่ได้บอกประเภทคนขับ — ตั้งชื่อขึ้นต้นด้วย "
                   f"2W-Win / 2W-Home / 4W-Taxi / 4W-Home แล้วสั่งรอบใหม่")
            log(f"  ⚠ {why}")
            issues.append((f"album:{entry['album']}", "folder", why))
            for x in entry["pairs"] + entry["long"]:
                x["moved"] = "ไม่รู้ประเภทคนขับจากชื่ออัลบั้ม — ยังอยู่ในกอง"
            continue
        alloc = allocators.get(week_id)
        if alloc is None:
            import db                       # imported where used, as everywhere else in this file
            alloc = allocators[week_id] = distribute.Allocator(
                drive, week_id,
                {k: [n for n, kd in db.name_pool_for(k[0]) if kd == k[1]]
                 for k in (("2W", "Win"), ("2W", "Home"), ("4W", "Taxi"), ("4W", "Home"))},
                log=log)
        for x in entry["pairs"] + entry["long"]:
            x["dest"] = None
            if not x["target"]:
                continue
            fid, err = alloc.folder_for(x["target"], *kind)
            if err:
                x["moved"] = err
                if (f"pool:{err}", "folder", err) not in issues:
                    issues.append((f"pool:{err}", "folder", err))
            x["dest"] = fid
        used_dir = (drive.ensure_folder(drive.ensure_folder(pool_id, USED_DIR), entry["album"])
                    if any(p.get("dest") for p in entry["pairs"]) else None)

        def do_pair(p):
            if not p["target"]:
                p["moved"] = "ไม่รู้ประเภทรถ — ยังอยู่ในกอง"
                return 0
            if not p.get("dest"):
                return 0
            try:
                img = pairing.stitch(io.BytesIO(data[p["top_id"]]),
                                     io.BytesIO(data[p["bottom_id"]]), cut_top=p.get("cut_top"))
                buf = io.BytesIO()
                img.save(buf, "JPEG", quality=88)
                tn, bn = (re.search(r'(\d+)\.\w+$', x).group(1) for x in (p["top"], p["bottom"]))
                name = f"{entry['album']}_{tn}+{bn}_฿{p['amount']:g}.jpg"
                drive.upload_file(p["dest"], name, buf.getvalue(), "image/jpeg")
                drive.move_file(p["top_id"], used_dir)
                drive.move_file(p["bottom_id"], used_dir)
                p["moved"] = f"{p['target']}/{name}"
                return 1
            except Exception as e:  # noqa: BLE001 — this pair stays in the pool for the next run
                p["moved"] = f"ย้ายไม่สำเร็จ: {str(e)[:80]}"
                report["errors"].append(f"ย้ายไม่สำเร็จ {p['top']}: {str(e)[:120]}")
                return 0

        def do_long(l):
            if not l["target"]:
                l["moved"] = "ไม่รู้ประเภทรถ — ยังอยู่ในกอง"
                return 0
            if not l.get("dest"):
                return 0
            try:
                drive.move_file(l["id"], l["dest"])
                l["moved"] = f"{l['target']}/{l['file']}"
                return 1
            except Exception as e:  # noqa: BLE001
                l["moved"] = f"ย้ายไม่สำเร็จ: {str(e)[:80]}"
                report["errors"].append(f"ย้ายไม่สำเร็จ {l['file']}: {str(e)[:120]}")
                return 0

        with ThreadPoolExecutor(max_workers=max(1, config.DRIVE_PARALLEL)) as ex:
            n = sum(ex.map(do_pair, entry["pairs"])) + sum(ex.map(do_long, entry["long"]))
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
    if args.limit:
        left = args.limit
        for a in albums:
            a["images"] = a["images"][:max(0, left)]
            left -= len(a["images"])
        albums = [a for a in albums if a["images"]]
    run_pool(drive, albums, move=args.move, preview=not args.no_preview, use_db=not args.no_db,
             started=started, label=(f"เฉพาะ {args.week}" if args.week else ""))
    return 0


def run_pool(drive, albums, move, preview=True, use_db=True, started=None, label="",
             run_id=None, log=log, issues=None):
    """The whole pool step on an already-scanned album list. Used by the CLI and by every ingest
    round (ingest.py, POOL_IN_ROUND). Returns the report dict, or None when the pool is empty."""
    started = started or time.strftime("%Y-%m-%d %H:%M:%S")
    n_img = sum(len(a["images"]) for a in albums)
    log(f"กอง: {len(albums)} อัลบั้ม · {n_img} รูป" + (f" · {label}" if label else ""))
    if not albums:
        return None
    errors = []
    t0 = time.time()
    data = fetch(drive, [i for a in albums for i in a["images"]], config.DRIVE_PARALLEL, errors)
    log(f"โหลดแล้ว {len(data)} รูป ใน {time.time() - t0:.0f} วิ")
    t0 = time.time()
    cache = {}
    if use_db:
        import db
        db.init_db()
        cache = db.pool_ocr_cache_load(pairing.cache_key(hashlib.md5(v).hexdigest())
                                       for v in data.values())
    report = analyse(albums, data, config.POOL_PARALLEL, cache)
    fresh = report.pop("ocr_fresh", {})
    if use_db and fresh:
        db.pool_ocr_cache_save(fresh)
        db.pool_ocr_cache_prune()
    report["errors"] = errors + report["errors"]
    report["started_at"] = started
    report["mode"] = "move" if move else "report"
    log(f"ตรวจและจับคู่เสร็จใน {time.time() - t0:.0f} วิ" + (f" · ใช้ผล OCR เดิม {report['ocr_cached']} รูป" if report.get("ocr_cached") else ""))
    if move:
        apply_moves(drive, albums, data, report, log=log, issues=issues)
    summary = render(report)
    log(summary)
    if move:                                                  # the stitched files ARE the output; keep the text log
        try:
            for pid in {a["pool_id"] for a in albums}:
                drive.upload_file(drive.ensure_folder(pid, REPORT_DIR),
                                  f"รายงานย้าย {time.strftime('%Y-%m-%d %H%M')}.txt", summary.encode("utf-8"), "text/plain")
        except Exception as e:  # noqa: BLE001
            log(f"อัปโหลดรายงานไม่สำเร็จ: {str(e)[:200]}")
    elif preview:
        try:
            write_previews(drive, albums, data, report, log=log)
        except Exception as e:  # noqa: BLE001
            log(f"อัปโหลดรายงานไม่สำเร็จ: {str(e)[:200]}")
            report["errors"].append(f"อัปโหลดรายงานไม่สำเร็จ: {str(e)[:200]}")
    if use_db:
        import db
        # the JSON keeps only what the page needs — no file ids
        slim = {k: v for k, v in report.items() if k != "ocr_fresh"}
        slim["albums"] = [{**a, "pairs": [{k: v for k, v in p.items() if not k.endswith("_id")} for p in a["pairs"]],
                           "long": [{k: v for k, v in l.items() if k != "id"} for l in a["long"]]}
                          for a in report["albums"]]
        if run_id is not None:
            slim["ingest_run_id"] = run_id
        rid = db.record_pool_run(report["mode"], ",".join(sorted({a["week"] for a in albums})),
                                 report["totals"], summary, slim)
        log(f"บันทึกผลเป็น pool run #{rid}")
    return report


def round_step(drive, inbox_id, run_id=None, dry_run=False, log=log, issues=None):
    """What an ingest round does first: pair and file whatever the Agent dropped into any
    Week/Pool. Report-only on a dry run. Never raises — a pool problem must not cost the round."""
    try:
        albums = scan_inbox(drive, inbox_id)
        if not albums:
            log("กอง: ว่าง")
            return None
        # a dry run touches nothing: no move, no preview upload (346 stitched files is minutes of
        # Drive calls), no database row — the report goes to the log
        return run_pool(drive, albums, move=not dry_run, preview=False, use_db=not dry_run,
                        run_id=run_id, log=log, issues=issues)
    except Exception as e:  # noqa: BLE001
        log(f"⚠ ขั้นจัดกองล้มเหลว (ข้ามไป รอบยังทำงานต่อ): {str(e)[:200]}")
        return None


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
