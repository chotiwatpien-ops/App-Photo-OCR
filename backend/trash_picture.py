# -*- coding: utf-8 -*-
"""Keep the picture when a person presses ลบ on a row.

Pressing ลบ removed the row and left its picture where it was, in the rider's own folder. The
round that follows never looks at it again — `ingested_files` still holds its Drive id, so the
sweep counts it as read — and Ops reading the folder sees a trip that no longer exists in the
workbook. Nobody notices until the folder is counted.

The picture is worth more than that. A row a person threw away is a picture the reader got
wrong, or a slip that should never have been paired, which is exactly the material worth
looking at again and worth training on. So it moves to <week>/_ทิ้ง-กดลบ/<rider>/, beside the
week it came from, under the name it arrived with.

The web server has no way into Drive, so on the web every move failed (W46: all three deletes,
2026-11-11 and 2026-11-15). A move that cannot happen now is written down (db.trash_moves) and
the next round, which does reach Drive, makes it. Nothing is deleted here, and a move that
fails never fails the delete: the row is already gone by then.
"""
import config
import db

TRASH_DIR = "_ทิ้ง-กดลบ"


def _target(trip_id):
    """{drive_id, date_from, date_to, rider, trip_id} of a row about to be deleted, or why not."""
    trip = db.get_trip(trip_id)
    if not trip:
        return "ไม่พบแถว"
    fid = db.drive_ids_for_trips([trip_id]).get(trip_id)
    if not fid:
        return "แถวนี้ไม่มีรูปบน Drive ที่ตามรอยได้"
    job = db.get_job(trip["job_id"]) or {}
    if not (job.get("date_from") and job.get("date_to")):
        return "งานนี้ไม่มีช่วงวันที่ หาโฟลเดอร์สัปดาห์ไม่ได้"
    return {"drive_id": fid, "date_from": job["date_from"], "date_to": job["date_to"],
            "rider": str(job.get("driver_name") or "ไม่ทราบชื่อ"), "trip_id": trip_id}


class InUse(Exception):
    """Another row still has this picture: moving it would take a counted trip's slip out of the
    rider's folder."""


def _move(drive, item):
    """Move it; the folder it went to, or None when the week has no folder. Raises on Drive errors."""
    others = db.rows_using_picture(item["drive_id"], except_trip=item.get("trip_id"))
    if others:
        raise InUse(f"ยังมีแถว {', '.join(map(str, others[:5]))} ใช้รูปนี้อยู่")
    import rebalance_quota as rq
    wk = rq.week_folder(drive, config.DRIVE_INBOX_FOLDER_ID, item["date_from"], item["date_to"])
    if wk is None:
        return None
    dest = drive.ensure_folder(drive.ensure_folder(wk["id"], TRASH_DIR), item["rider"])
    drive.move_file(item["drive_id"], dest)
    return f"{wk['name']}/{TRASH_DIR}/{item['rider']}"


def move_to_trash(trip_id, drive=None, log=print) -> dict:
    """Move one row's picture to <week>/_ทิ้ง-กดลบ/<rider>/. Call BEFORE deleting the row —
    the job, the rider's name and the Drive id all have to be read while the row still exists.

    Returns {"moved": bool, "why": str} and, when the move is left to the next round,
    "queued": True. Never raises."""
    try:
        item = _target(trip_id)
    except Exception as e:                                       # noqa: BLE001
        return {"moved": False, "why": str(e)[:90]}
    if isinstance(item, str):
        return {"moved": False, "why": item}
    try:
        if drive is None:
            import roster
            drive = roster._drive()
        where = _move(drive, item)
    except InUse as e:
        return {"moved": False, "why": f"ไม่ย้ายรูป: {e}"}
    except Exception as e:                                       # noqa: BLE001
        log(f"⚠ ลบแถว {trip_id} แล้ว แต่ย้ายรูปไป {TRASH_DIR} ตอนนี้ไม่ได้: {str(e)[:90]}")
        try:
            db.queue_trash_move(**item)
        except Exception as qe:                                  # noqa: BLE001
            return {"moved": False, "why": f"{str(e)[:60]} · จดไว้ให้รอบอ่านย้ายก็ไม่ได้: {str(qe)[:60]}"}
        return {"moved": False, "queued": True, "why": "รอบอ่านถัดไปจะย้ายรูปให้"}
    if where is None:
        return {"moved": False, "why": f"ไม่พบโฟลเดอร์สัปดาห์ {item['date_from']}..{item['date_to']}"}
    return {"moved": True, "why": where}


def queue_from_log(open_week=None):
    """Write down the deletes whose move failed before the queue existed. Returns how many.

    Only weeks still open: a delivered week's folders are left as they were delivered."""
    import free_dup_seats
    open_week = open_week or free_dup_seats.week_is_open
    import dup_examples
    added = 0
    for a in db.list_actions(limit=2000, action="trip.delete"):
        d = a.get("detail") if isinstance(a.get("detail"), dict) else {}
        row, moved = d.get("row") or {}, d.get("picture_moved_to") or {}
        fid = dup_examples.drive_id(row.get("source_url"))
        if a.get("status") != 200 or moved.get("moved") or moved.get("queued") or not fid:
            continue
        job = db.get_job(row.get("job_id")) or {}
        if not (job.get("date_from") and job.get("date_to")) or not open_week(job["date_from"], job["date_to"]):
            continue
        added += db.queue_trash_move(fid, job["date_from"], job["date_to"],
                                     str(job.get("driver_name") or "ไม่ทราบชื่อ"))
    return added


def move_queued(drive, log=print) -> int:
    """The round's step: make every move the web could not. Returns how many moved."""
    try:
        queue_from_log()
    except Exception as e:                                       # noqa: BLE001
        log(f"  ⚠ อ่านบันทึกการกดลบไม่สำเร็จ: {str(e)[:90]}")
    moved = 0
    for item in db.pending_trash_moves():
        try:
            where = _move(drive, item)
        except InUse as e:
            db.finish_trash_move(item["drive_id"], f"ไม่ย้าย: {e}")
            log(f"  ⚠ ไม่ย้ายรูป {item['drive_id']} ไป {TRASH_DIR}: {e}")
            continue
        except Exception as e:                                   # noqa: BLE001
            if "404" in str(e) or "not found" in str(e).lower():
                db.finish_trash_move(item["drive_id"], "ไม่พบรูปบน Drive แล้ว")
            else:
                log(f"  ⚠ ย้ายรูปที่ถูกกดลบ {item['drive_id']} ไม่สำเร็จ ลองใหม่รอบหน้า: {str(e)[:90]}")
            continue
        db.finish_trash_move(item["drive_id"], where or "ไม่พบโฟลเดอร์สัปดาห์")
        moved += where is not None
    if moved:
        log(f"🗑 ย้ายรูปของแถวที่ถูกกดลบในหน้าเว็บไป {TRASH_DIR} แล้ว {moved} รูป")
    return moved
