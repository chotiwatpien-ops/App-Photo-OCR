# -*- coding: utf-8 -*-
"""One customer file per week, in that week's own Exports folder (Fiat 2026-11-10).

    Exports/2026-W46/Rider Trips 2026-W46 Phase 3.xlsx

Until W45 three files held every week ('Rider Trips.xlsx', '… Phase 2.xlsx', '… Phase 3.xlsx'),
each rewritten from every approved row whenever any row changed, and the customer had to find
their week inside them. From WEEK_FILES_FROM a week's file holds that week only, in the Phase 3
layout with Driver ID and Order ID, under the same name and in the same place the close writes
its final copy, so there is one file per week and it is always the current one.

A closed week is left as the close wrote it. A week whose rows have not changed since its file
was written is not written again (db.week_fingerprint)."""
import config
import db
import excel_writer


def applies(week_from) -> bool:
    return bool(config.WEEK_FILES_FROM and week_from and week_from >= config.WEEK_FILES_FROM)


def name(week_from) -> str:
    import week_phase3
    return week_phase3.file_name(week_from)


def folder(drive, exports_id, week_from) -> str:
    from ingest import week_label
    fid = drive.ensure_folder(exports_id, week_label(week_from))
    db.record_drive_file(week_label(week_from), "week_folder", fid)
    return fid


def open_weeks():
    """(date_from, date_to) of every week from WEEK_FILES_FROM that has work and is not closed."""
    closed = set(db.closed_weeks())
    return sorted(w for w in db.jobs_by_week() if applies(w[0]) and w[0] not in closed)


OUT_DIR = "_ไม่อยู่ในไฟล์"


def _names_in_file(d_from, d_to):
    """{group folder: {picture names of the rows in the week's file}}."""
    from sqlalchemy import select
    t, j = db.trips.c, db.jobs.c
    with db.engine.begin() as c:
        rows = c.execute(select(j.category, t.customer_image)
                         .select_from(db.trips.join(db.jobs, j.id == t.job_id))
                         .where(j.date_from == d_from, j.date_to == d_to, t.status == "done",
                                t.committed == 1, t.customer_image.isnot(None))).all()
    out = {}
    for cat, name in rows:
        out.setdefault((cat or "อัปโหลดมือ").strip(), set()).add(name)
    return out


def tidy(drive, exports_id, d_from, d_to, log=print):
    """Keep a week's picture folders to the pictures of the rows in its file. Returns (out, back).

    A picture is made when its slip is read, before anyone decides on the row, so a row waiting
    in the review queue, deleted there or parked as a repeat left its picture beside the delivered
    ones (W46: 005111112621.jpg and 005215112605.jpg, two repeats waiting for a person). Such a
    picture moves into <group>/_ไม่อยู่ในไฟล์ (moved, never deleted) and comes back by itself
    once its row is approved."""
    from ingest import week_label
    want = _names_in_file(d_from, d_to)
    if not want:
        return 0, 0                    # nothing approved yet: nothing to measure the folders by
    week_dir = next((f["id"] for f in drive.list_folders(exports_id) if f["name"] == week_label(d_from)), None)
    if not week_dir:
        return 0, 0
    out = back = 0
    for g in drive.list_folders(week_dir):
        if g["name"].startswith("_"):
            continue
        names = want.get(g["name"].strip(), set())
        here = drive.list_images(g["id"])
        stray = [f for f in here if f["name"] not in names]
        if len(stray) > 20 and len(stray) * 2 > len(here):
            # most of a folder not in the file means the folder and the rows disagree on the
            # group's name, not that the pictures are stray — say so and touch nothing
            log(f"⚠ {week_label(d_from)}/{g['name']}: รูป {len(stray)} จาก {len(here)} ไม่ตรงกับแถวในไฟล์ — ไม่ได้ย้าย")
            continue
        held = next((f["id"] for f in drive.list_folders(g["id"]) if f["name"] == OUT_DIR), None)
        for f in stray:
            held = held or drive.ensure_folder(g["id"], OUT_DIR)
            drive.move_file(f["id"], held)
            out += 1
        if held:
            present = {f["name"] for f in here} - {f["name"] for f in stray}
            for f in drive.list_images(held):
                if f["name"] in names and f["name"] not in present:
                    drive.move_file(f["id"], g["id"])
                    present.add(f["name"])
                    back += 1
    if out or back:
        log(f"🗂 {week_label(d_from)}: รูปที่ไม่อยู่ในไฟล์ย้ายออก {out} · อนุมัติแล้วย้ายกลับ {back}")
    return out, back


def write(drive, exports_id, weeks=None, force=False, log=print):
    """Tidy the picture folders and write the file of each week that changed.
    Returns (files written, errors)."""
    import week_phase3
    from ingest import week_label
    written = errors = 0
    for d_from, d_to in (weeks if weeks is not None else open_weeks()):
        if not applies(d_from):
            continue
        try:
            tidy(drive, exports_id, d_from, d_to, log=log)
        except Exception as e:  # noqa: BLE001 — a folder that cannot be tidied must not stop the file
            log(f"⚠ จัดโฟลเดอร์รูปของสัปดาห์ {week_label(d_from)} ไม่สำเร็จ: {str(e)[:200]}")
        key = f"week_file:{d_from}"
        stamp = f"{excel_writer.LAYOUT}:{db.week_fingerprint(d_from, d_to)}"
        if not force and db.state_get(key) == stamp:
            continue
        rows = week_phase3.week_rows(d_from, d_to)
        if not rows:
            continue
        try:
            fid = drive.upload_xlsx(folder(drive, exports_id, d_from), name(d_from),
                                    excel_writer.build_fare_lines_workbook(rows, every_week=True))
            db.record_drive_file(week_label(d_from), "xlsx", fid, name(d_from))
            db.state_set(key, stamp)
            written += 1
            log(f"📄 {week_label(d_from)}/{name(d_from)}: {len(rows):,} แถว")
        except Exception as e:  # noqa: BLE001 — one week's file must not stop the others
            errors += 1
            log(f"✗ เขียนไฟล์ของสัปดาห์ {week_label(d_from)} ไม่สำเร็จ: {str(e)[:200]}")
    return written, errors
