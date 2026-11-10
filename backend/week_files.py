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


def write(drive, exports_id, weeks=None, force=False, log=print):
    """Write the file of each week that changed. Returns (files written, errors)."""
    import week_phase3
    from ingest import week_label
    written = errors = 0
    for d_from, d_to in (weeks if weeks is not None else open_weeks()):
        if not applies(d_from):
            continue
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
