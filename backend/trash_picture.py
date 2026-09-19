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

Nothing is deleted here, and a move that fails never fails the delete: the row is already gone
by then, and a picture in the wrong folder is a smaller problem than an error on the screen.
"""
import config
import db

TRASH_DIR = "_ทิ้ง-กดลบ"


def move_to_trash(trip_id, drive=None, log=print) -> dict:
    """Move one row's picture to <week>/_ทิ้ง-กดลบ/<rider>/. Call BEFORE deleting the row —
    the job, the rider's name and the Drive id all have to be read while the row still exists.

    Returns {"moved": bool, "why": str} and never raises."""
    try:
        trip = db.get_trip(trip_id)
        if not trip:
            return {"moved": False, "why": "ไม่พบแถว"}
        fid = db.drive_ids_for_trips([trip_id]).get(trip_id)
        if not fid:
            return {"moved": False, "why": "แถวนี้ไม่มีรูปบน Drive ที่ตามรอยได้"}
        job = db.get_job(trip["job_id"]) or {}
        if not (job.get("date_from") and job.get("date_to")):
            return {"moved": False, "why": "งานนี้ไม่มีช่วงวันที่ หาโฟลเดอร์สัปดาห์ไม่ได้"}
        if drive is None:
            import roster
            drive = roster._drive()
        import rebalance_quota as rq
        wk = rq.week_folder(drive, config.DRIVE_INBOX_FOLDER_ID, job["date_from"], job["date_to"])
        if wk is None:
            return {"moved": False, "why": f"ไม่พบโฟลเดอร์สัปดาห์ {job['date_from']}..{job['date_to']}"}
        dest = drive.ensure_folder(drive.ensure_folder(wk["id"], TRASH_DIR),
                                   str(job.get("driver_name") or "ไม่ทราบชื่อ"))
        drive.move_file(fid, dest)
        return {"moved": True, "why": f"{wk['name']}/{TRASH_DIR}/{job.get('driver_name')}"}
    except Exception as e:                                       # noqa: BLE001
        log(f"⚠ ลบแถว {trip_id} แล้ว แต่ย้ายรูปไป {TRASH_DIR} ไม่สำเร็จ: {str(e)[:90]}")
        return {"moved": False, "why": str(e)[:90]}
