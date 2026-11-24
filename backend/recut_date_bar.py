# -*- coding: utf-8 -*-
"""Take the date bar off one week's stitched pictures that still carry it.

Ops dates every trip in the workbook themselves, so a slip date printed on the picture contradicts
the one beside it, and the pool cuts that bar off a top half (pairing.date_bar_cut). Until r15 the
cut landed at the first gap of writing, and on a screenshot that keeps the phone's status bar that
gap is under the clock: the clock went and '11 ต.ค. 2026, 05:15' stayed. W47's customer pictures
went out of the pool like that.

For every finished row of the week this looks at the picture the row points at. When its left half
(or the whole of a one-piece screenshot) still opens on a date bar, the bar is cut, the new bytes
replace the old in the same Drive file (rows keep pointing at the same id), and the customer picture
of that row is made again under its own name. The old bytes go to Exports/_ก่อนตัดวันที่/<week>/
first: nothing is lost.

A picture found free of a bar is remembered by its bytes (sweep), so a second look at the same
week opens only what is new, what changed, and what still carries a bar. W47 was swept five times,
57 + 32 + 86 + 113 + 84 minutes, each time downloading and reading all 4,411 pictures again.

    python recut_date_bar.py --week 2026-11-16            # report only
    python recut_date_bar.py --week 2026-11-16 --apply
"""
import argparse
import contextlib
import hashlib
import io
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image
from sqlalchemy import select

import config
import db
import pairing
import stitch
from file_after_read import HOLDING_RIDER
from ingest import week_label

BACKUP_DIR = "_ก่อนตัดวันที่"
GAP = 16
# Half of the version a 'no bar' verdict is remembered under; pairing.READER is the other half and
# follows date_bar_cut. Bump this when halves() or recut() could answer differently for bytes they
# have already seen, or when requirements-pairing.txt moves the OCR to another version.
CHECKER = 1
META_THREADS = 12       # a checksum is one small Drive call; the OCR stays at OCR_THREADS
OCR_THREADS = 4
PROGRESS_EVERY = 200


def drive_id(url):
    m = re.search(r"/d/([^/?]+)", url or "")
    return m.group(1) if m else ((url or "").rstrip("/").split("/")[-1] or None)


def halves(im):
    """(left, right) of a picture the pool joined side by side, or (im, None) for one screen.

    The pool pastes the top at x=0 and the bottom GAP white columns to its right, so the white
    band nearest the middle is the join."""
    if im.width < im.height * 0.9:
        return im, None
    g = np.asarray(im.convert("L"))
    white = (g > 225).mean(axis=0) > 0.98        # a JPEG smears the dark edge into the gap
    mid = (im.width - GAP) // 2
    if white[mid:mid + GAP].all():
        return im.crop((0, 0, mid, im.height)), im.crop((mid + GAP, 0, im.width, im.height))
    runs, start = [], None
    for x in range(int(im.width * 0.3), int(im.width * 0.7)):
        if white[x] and start is None:
            start = x
        elif not white[x] and start is not None:
            runs.append((start, x))
            start = None
    runs = [r for r in runs if r[1] - r[0] >= 6]  # a resized picture narrows the gap
    if not runs:
        return None, None
    a, b = min(runs, key=lambda r: abs((r[0] + r[1]) / 2 - im.width / 2))
    return im.crop((0, 0, a, im.height)), im.crop((b, 0, im.width, im.height))


def recut(data):
    """New bytes without the date bar, or None when there is no bar to take."""
    im = Image.open(io.BytesIO(data)).convert("RGB")
    left, right = halves(im)
    if left is None:
        return None
    cut = pairing.date_bar_cut(left)
    if not cut:
        return None
    out = (pairing.stitch(left, right, cut_top=cut) if right is not None
           else left.crop((0, cut, left.width, left.height)))
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def clean_key(md5_hex):
    """The pool_ocr_cache row that says: these exact bytes, seen by this checker, carry no date bar."""
    key = f"c{CHECKER}{pairing.READER}:{md5_hex}"
    assert len(key) <= 40, f"คีย์ {key!r} ยาวเกินคอลัมน์ 40 ตัวอักษรของ pool_ocr_cache"
    return key


_ocr = threading.local()


@contextlib.contextmanager
def ocr_failures_noted():
    """While a sweep runs, a read the OCR failed on leaves a mark on its thread.

    date_bar_cut answers None both for 'no bar' and for 'the OCR could not read this', and only
    the first is true of the bytes. Remembering the second would hide a bar for good."""
    read = pairing._read_text

    def noted(img):
        try:
            return read(img)
        except Exception:
            _ocr.failed = True
            raise

    pairing._read_text = noted
    try:
        yield
    finally:
        pairing._read_text = read


def remember(clean):
    try:
        db.pool_ocr_cache_save(clean)
    except Exception as e:  # noqa: BLE001 — the memory only saves time; the sweep's answer does not need it
        print(f"  ⚠ จำผลไม่ได้ {len(clean)} รูป (รอบหน้าจะเปิดดูใหม่): {str(e)[:120]}")


def sweep(drive, rows):
    """(pictures with a bar, pictures that could not be opened, how many were skipped, how many
    the OCR failed on) for the rows of one week.

    A picture is skipped only when the md5 Drive holds for it now is one recut() has already
    answered None for under this checker, so skipping gives the verdict a fresh look would give.
    Only 'no bar' is remembered, under the md5 of the bytes that were actually read. A picture
    with a bar is opened every time; once it is cut its bytes are new, so the next sweep reads
    the cut picture for real before it is remembered."""
    def checksum(r):
        try:
            return drive.md5(drive_id(r["source_url"]))
        except Exception:  # noqa: BLE001 — no checksum only means the picture is opened
            return None

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=META_THREADS) as ex:
        sums = list(ex.map(checksum, rows))
    known = db.pool_ocr_cache_load({clean_key(h) for h in sums if h})
    todo = [r for r, h in zip(rows, sums) if not h or clean_key(h) not in known]
    skipped = len(rows) - len(todo)
    print(f"เคยตรวจแล้วว่าไม่มีแถบ {skipped:,} รูป (ไม่ต้องโหลด) · ต้องเปิดดู {len(todo):,} รูป"
          f" · ถาม Drive {time.time() - t0:.0f} วิ")

    def look(r):
        _ocr.failed = False
        try:
            old = drive.download(drive_id(r["source_url"]))
            return r, old, recut(old), None, _ocr.failed
        except Exception as e:  # noqa: BLE001 — one picture must not stop the week
            return r, None, None, str(e)[:120], False

    t0 = time.time()
    hit, bad, clean, unread = [], [], {}, 0
    with ocr_failures_noted(), ThreadPoolExecutor(max_workers=OCR_THREADS) as ex:
        for n, (r, old, new, err, ocr_failed) in enumerate(ex.map(look, todo), 1):
            if err:
                bad.append((r, err))
            elif new:
                hit.append((r, old, new))
            elif ocr_failed:
                unread += 1
            else:
                clean[clean_key(hashlib.md5(old).hexdigest())] = {"bar": False}
            if n % PROGRESS_EVERY == 0:
                # saved as it goes: a run that is cancelled or times out keeps what it has checked
                remember(clean)
                clean = {}
                print(f"  … เปิดดูแล้ว {n:,}/{len(todo):,} รูป · พบแถบวันที่ {len(hit):,} · {time.time() - t0:.0f} วิ")
    remember(clean)
    return hit, bad, skipped, unread


def week_rows(d_from, d_to):
    jobs = {j["id"]: j for j in db.jobs_by_week().get((d_from, d_to), [])}
    t = db.trips
    with db.engine.begin() as c:
        rows = c.execute(select(t.c.id, t.c.job_id, t.c.file_name, t.c.source_url, t.c.customer_image)
                         .where(t.c.job_id.in_(list(jobs)), t.c.status == "done")).mappings().all()
    return [dict(r, job=jobs[r["job_id"]]) for r in rows if drive_id(r["source_url"])]


def from_original(olds, drop):
    """Bytes to put back, made from the tallest kept copy (every cut only shortens a picture).

    With `drop` the operator has looked at that copy: its date sits under the phone's status bar
    where date_bar_cut cannot see it, so exactly that many rows come off the top (0 = the copy
    carried no date at all and goes back as it was)."""
    if not olds:
        return None
    sized = [(Image.open(io.BytesIO(o)).height, o) for o in olds]
    orig = max(sized, key=lambda s: s[0])[1]
    if drop is None:
        return recut(orig)
    if not drop:
        return orig
    im = Image.open(io.BytesIO(orig)).convert("RGB")
    buf = io.BytesIO()
    im.crop((0, drop, im.width, im.height)).save(buf, "JPEG", quality=88)
    return buf.getvalue()


def _drive():
    from drive_client import DriveClient
    return DriveClient(config.GOOGLE_SERVICE_ACCOUNT, config.DRIVE_OAUTH_TOKEN)


def restore(week, names, apply_it, drive=None):
    """Remake pictures a second recut cut too far, from the bytes kept before the first cut.

    Every cut leaves the bytes it replaced in _ก่อนตัดวันที่ under '<row id>_<file name>', so a
    picture cut twice has two of them: the original and the first cut. A name alone cuts the date
    bar once from the original; 'name:N' takes N rows off its top instead (see from_original)."""
    drops = {}
    for n in names:
        name, _, rows_off = n.partition(":")
        drops[name] = int(rows_off) if rows_off else None
    names = list(drops)
    db.init_db()
    rng = next((w for w in db.jobs_by_week() if w[0] == week), None)
    if rng is None:
        print(f"✗ ไม่มีสัปดาห์ที่เริ่ม {week}")
        return 1
    wk = week_label(rng[0])
    rows = {r["customer_image"]: r for r in week_rows(*rng) if r["customer_image"] in names}
    for n in names:
        if n not in rows:
            print(f"  ✗ {n}: ไม่พบแถวในสัปดาห์นี้")
    drive = drive or _drive()
    backup = drive.ensure_folder(drive.ensure_folder(config.DRIVE_EXPORTS_FOLDER_ID, BACKUP_DIR), wk)
    kept = {}
    for f in drive.list_images(backup):
        kept.setdefault(f["name"], []).append(f["id"])
    week_dir = drive.ensure_folder(config.DRIVE_EXPORTS_FOLDER_ID, wk)
    bad = 0
    for n, r in rows.items():
        olds = [drive.download(i) for i in kept.get(f"{r['id']}_{r['file_name']}", [])]
        made = from_original(olds, drops[n])
        if made is None:
            print(f"  ✗ {n}: ไม่มีต้นฉบับที่ยังมีแถบวันที่ใน {BACKUP_DIR}/{wk} ({len(olds)} ไฟล์)")
            bad += 1
            continue
        how = ("ตัดแถบวันที่ครั้งเดียว" if drops[n] is None else
               "คืนต้นฉบับตามเดิม" if not drops[n] else f"ตัดบนออก {drops[n]} แถว")
        h = Image.open(io.BytesIO(made)).height
        print(f"  {'✔' if apply_it else '·'} {n}: ทำใหม่จากต้นฉบับ — {how}, สูง {h}px ({len(olds)} ไฟล์สำรอง)")
        if apply_it:
            drive.replace_content(drive_id(r["source_url"]), made, "image/jpeg")
            cat = r["job"].get("category") or "อัปโหลดมือ"
            drive.upload_file(drive.ensure_folder(week_dir, cat), n, stitch.stitch(made), "image/jpeg")
    print(f"{'ทำใหม่แล้ว' if apply_it else 'จะทำใหม่'} {len(rows) - bad} รูป · ไม่ได้ {bad + len(names) - len(rows)}")
    return 1 if bad or len(rows) < len(names) else 0


def main(argv=None, drive=None):
    ap = argparse.ArgumentParser(description="ตัดแถบวันที่ออกจากรูปที่ต่อแล้วของสัปดาห์หนึ่ง")
    ap.add_argument("--week", required=True, help="วันแรกของสัปดาห์ เช่น 2026-11-16")
    ap.add_argument("--apply", action="store_true", help="ทำจริง (ไม่ใส่ = รายงานอย่างเดียว)")
    ap.add_argument("--restore", default="",
                    help="ชื่อรูปส่งลูกค้าที่ถูกตัดเกิน คั่นด้วย , — ทำใหม่จากต้นฉบับใน _ก่อนตัดวันที่ (ชื่อ:N = ตัดบนออก N แถว, ชื่อ:0 = คืนต้นฉบับตามเดิม)")
    a = ap.parse_args(argv)
    if a.restore:
        return restore(a.week, [n.strip() for n in a.restore.split(",") if n.strip()], a.apply, drive)
    db.init_db()
    rng = next((w for w in db.jobs_by_week() if w[0] == a.week), None)
    if rng is None:
        print(f"✗ ไม่มีสัปดาห์ที่เริ่ม {a.week}")
        return 1
    wk = week_label(rng[0])
    rows = week_rows(*rng)
    print(f"{wk}: ตรวจ {len(rows):,} รูป")
    drive = drive or _drive()
    hit, bad, skipped, unread = sweep(drive, rows)
    for r, err in bad:
        print(f"  ⚠ #{r['id']} {r['file_name']}: {err}")
    by_job = {}
    for r, *_ in hit:
        by_job.setdefault(r["job"]["driver_name"], []).append(r["customer_image"] or r["file_name"])
    print(f"มีแถบวันที่ {len(hit):,} รูป · อ่านไม่ได้ {len(bad)} รูป"
          f" · ข้าม {skipped:,} รูปที่เคยตรวจแล้วว่าไม่มีแถบ"
          + (f" · OCR อ่านไม่ได้ {unread} รูป (ไม่จำ รอบหน้าเปิดดูใหม่)" if unread else ""))
    for name, files in sorted(by_job.items()):
        print(f"  {name}: {len(files)} — {', '.join(files[:6])}{' …' if len(files) > 6 else ''}")
    if not a.apply or not hit:
        return 0

    backup = drive.ensure_folder(drive.ensure_folder(config.DRIVE_EXPORTS_FOLDER_ID, BACKUP_DIR), wk)
    week_dir = drive.ensure_folder(config.DRIVE_EXPORTS_FOLDER_ID, wk)
    cat_dirs = {}
    for r, *_ in hit:
        cat = r["job"].get("category") or "อัปโหลดมือ"
        if r["customer_image"] and r["job"]["driver_name"] != HOLDING_RIDER and cat not in cat_dirs:
            cat_dirs[cat] = drive.ensure_folder(week_dir, cat)

    def fix(s):
        r, old, new = s
        try:
            drive.create_file(backup, f"{r['id']}_{r['file_name']}", old, "image/jpeg")
            drive.replace_content(drive_id(r["source_url"]), new, "image/jpeg")
            if r["customer_image"] and r["job"]["driver_name"] != HOLDING_RIDER:
                cat = r["job"].get("category") or "อัปโหลดมือ"
                drive.upload_file(cat_dirs[cat], r["customer_image"], stitch.stitch(new), "image/jpeg")
            return None
        except Exception as e:  # noqa: BLE001
            return f"#{r['id']} {r['file_name']}: {str(e)[:120]}"

    with ThreadPoolExecutor(max_workers=4) as ex:
        errs = [e for e in ex.map(fix, hit) if e]
    for e in errs:
        print(f"  ✗ {e}")
    print(f"ตัดแล้ว {len(hit) - len(errs):,} รูป (ของเดิมเก็บไว้ที่ Exports/{BACKUP_DIR}/{wk}/) · พลาด {len(errs)}")
    return 1 if errs else 0


if __name__ == "__main__":
    # line by line, or the run log stays empty until the sweep is over
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.exit(main())
