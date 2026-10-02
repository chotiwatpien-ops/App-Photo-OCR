# -*- coding: utf-8 -*-
"""Photo OCR — FastAPI backend.

Local:  uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8600
Cloud:  see render.yaml (DATABASE_URL, GEMINI_API_KEY, APP_PASSWORD, SECRET_KEY)
"""
import contextvars
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, TimestampSigner

import config
import db
import excel_writer
import pipeline

app = FastAPI(title="Photo OCR")
db.init_db()
_pool = ThreadPoolExecutor(max_workers=config.MAX_PARALLEL_EXTRACTIONS)
_signer = TimestampSigner(config.SECRET_KEY)

MIME_BY_EXT = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
COOKIE = "pocr_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
PUBLIC_API = {"/api/health", "/api/login", "/api/logout", "/api/me"}


# ---------- auth (single shared password; disabled when APP_PASSWORD unset) ----------

def _logged_in(request: Request) -> bool:
    if not config.APP_PASSWORD:
        return True
    tok = request.cookies.get(COOKIE)
    if not tok:
        return False
    try:
        _signer.unsign(tok, max_age=SESSION_MAX_AGE)
        return True
    except BadSignature:
        return False


def _diag_ok(request: Request) -> bool:
    """Read-only diagnostic access via header key — valid ONLY for /api/diag/* paths."""
    import hmac
    key = config.DIAG_KEY or ""
    given = request.headers.get("x-diag-key") or ""
    return bool(key) and hmac.compare_digest(given, key)


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    p = request.url.path
    if p.startswith("/api/diag/") or p == "/api/ingest/cron":
        if _diag_ok(request) or _logged_in(request):
            return await call_next(request)
        return JSONResponse({"detail": "diag_key_required"}, status_code=401)
    if p.startswith("/api/") and p not in PUBLIC_API and not _logged_in(request):
        return JSONResponse({"detail": "login_required"}, status_code=401)
    return await call_next(request)


# ---------- action log: who changed what, when, from where (support / MA) ----------
# Every request that is not a GET is written to action_log, refused ones included. A handler that
# changes data says what it changed with _note(); the middleware adds the request's own facts.
# The handler and the middleware share one dict through a context variable, so no handler needs
# a Request parameter just for this. Request bodies are never logged — login carries a password.

_AUDIT = contextvars.ContextVar("audit", default=None)


def _note(action=None, target=None, **detail):
    a = _AUDIT.get()
    if a is None:
        return
    if action:
        a["action"] = action
    if target:
        a["target"] = target
    if detail:
        a.setdefault("detail", {}).update(detail)


def _client_ip(request: Request):
    fwd = request.headers.get("x-forwarded-for")          # Render sits in front of the app
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None))


@app.middleware("http")
async def action_log(request: Request, call_next):
    if not request.url.path.startswith("/api/"):
        return await call_next(request)
    note = {}
    token = _AUDIT.set(note)
    t0 = time.monotonic()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        _AUDIT.reset(token)
        if request.method != "GET" or note.get("action"):
            route = request.scope.get("route")
            db.log_action(
                method=request.method, path=request.url.path, query=str(request.url.query or "")[:500],
                status=status, ip=_client_ip(request), user_agent=(request.headers.get("user-agent") or "")[:300],
                action=note.get("action") or f"{request.method} {getattr(route, 'path', request.url.path)}",
                target=note.get("target"), detail=note.get("detail"),
                ms=int((time.monotonic() - t0) * 1000))


@app.get("/api/me")
def me(request: Request):
    return {"auth_required": bool(config.APP_PASSWORD), "logged_in": _logged_in(request)}


@app.post("/api/login")
async def login(body: dict, response: Response):
    if not config.APP_PASSWORD:
        return {"ok": True}
    _note("auth.login")
    if body.get("password") != config.APP_PASSWORD:
        raise HTTPException(401, "รหัสผ่านไม่ถูกต้อง")
    response.set_cookie(COOKIE, _signer.sign("ok").decode(), max_age=SESSION_MAX_AGE,
                        httponly=True, samesite="lax", secure=config.IS_CLOUD)
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response):
    _note("auth.logout")
    response.delete_cookie(COOKIE)
    return {"ok": True}


# ---------- background extraction ----------

def _extract_worker(trip_id: int, job_id: int):
    pipeline.process_trip(trip_id, job_id)
    j = db.get_job(job_id)
    if j and not any(t["status"] == "pending" for t in j["trips"]):
        pipeline.pair_fragments(job_id)  # last image in: pair top/bottom halves (idempotent)


# ---------- API ----------

@app.get("/api/health")
def health():
    excel_locked = False
    if config.EXCEL_APPEND and config.EXCEL_PATH.exists():
        try:
            with open(config.EXCEL_PATH, "r+b"):
                pass
        except PermissionError:
            excel_locked = True
    return {"ok": True, "is_cloud": config.IS_CLOUD, "excel_append": config.EXCEL_APPEND,
            "excel_locked": excel_locked, "excel_name": config.EXCEL_PATH.name,
            "model": config.GEMINI_MODEL, "auth_required": bool(config.APP_PASSWORD),
            "api_key_source": config.api_key_source()}


@app.post("/api/jobs")
async def create_job(
    driver_name: str = Form(...),
    date_from: str = Form(...),
    date_to: str = Form(...),
    files: list[UploadFile] = File(...),
):
    if not files:
        raise HTTPException(400, "ไม่มีไฟล์รูป")
    # re-uploading the same rider+week must land in the SAME job — a second job would double
    # every trip in the workbook (this is exactly how สุรวิทย์ ended up counted three times)
    name = driver_name.strip()
    job_id = (db.find_job(name, date_from, date_to)
              or db.create_job(name, excel_writer.SHEET, date_from, date_to))
    _note("job.upload", f"job:{job_id}", rider=name, date_from=date_from, date_to=date_to, files=len(files))
    for f in files:
        ext = Path(f.filename or "img.jpg").suffix.lower() or ".jpg"
        mime = MIME_BY_EXT.get(ext)
        if not mime:
            continue
        trip_id = db.create_trip(job_id, f.filename or f"img{ext}", await f.read(), mime)
        _pool.submit(_extract_worker, trip_id, job_id)
    db.refresh_job_status(job_id)  # handles the "no valid images" case
    return db.get_job(job_id)


@app.get("/api/jobs")
def jobs():
    return {"jobs": db.list_jobs()}


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: int):
    j = db.get_job(job_id)
    if not j:
        raise HTTPException(404, "ไม่พบ job")
    return j


# the figures arithmetic_check reads — editing any of them makes its old verdict stale
MONEY_FIELDS = {"net_earnings", "base_fare", "bonus", "turbo", "passenger_total", "tip"}


@app.patch("/api/trips/{trip_id}")
async def patch_trip(trip_id: int, fields: dict):
    t = db.get_trip(trip_id)
    if not t:
        raise HTTPException(404, "ไม่พบรายการ")
    if t["committed"]:
        raise HTTPException(409, "รายการนี้อนุมัติแล้ว แก้ไขไม่ได้")
    change = {k: v for k, v in fields.items() if k in db.TRIP_EDITABLE}
    _note("trip.edit", f"trip:{trip_id}", job=t["job_id"], file=t.get("file_name"),
          before={k: t.get(k) for k in change}, after=change)
    db.update_trip(trip_id, change)
    t = db.get_trip(trip_id)
    # the row was held back because its numbers disagreed; a person has just changed one of
    # them, so ask the same question again. Without this the queue keeps calling a corrected
    # row broken, and 'approve everything that passes' skips the rows someone just fixed.
    if MONEY_FIELDS & set(fields):
        import extractor
        new = extractor.arithmetic_check(t)
        if new != t.get("check_status"):
            db.update_trip(trip_id, {"check_status": new})
            t = db.get_trip(trip_id)
    return t


@app.delete("/api/trips/{trip_id}")
def remove_trip(trip_id: int):
    t = db.get_trip(trip_id)
    if not t:
        raise HTTPException(404, "ไม่พบรายการ")
    if t["committed"]:
        raise HTTPException(409, "รายการนี้อนุมัติแล้ว ลบไม่ได้")
    _note("trip.delete", f"trip:{trip_id}", row={k: t.get(k) for k in (
        "job_id", "file_name", "booking_code", "trip_date", "trip_time", "service_type",
        "base_fare", "net_earnings", "status", "source_url")})
    # The picture goes to <week>/_ทิ้ง-กดลบ/<rider>/ before the row does, while the job and the
    # Drive id can still be read off it. A row thrown away by hand is a picture worth looking at
    # again — and left in the rider's folder it is worse than useless, because the sweep counts
    # it as read and Ops count it as a trip. A failed move never fails the delete.
    import trash_picture
    moved = trash_picture.move_to_trash(trip_id)
    _note(picture_moved_to=moved)
    db.delete_trip(trip_id)
    db.refresh_job_status(t["job_id"])
    return {"deleted": trip_id, "picture": moved}


_DRIVE_PIC = {}          # trip image fetched back from Drive, kept for this process only


@app.get("/api/trips/{trip_id}/image")
def trip_image(trip_id: int, part: int = 1):
    img = db.get_trip_image(trip_id, part)
    if not img:
        # The blob is gone — approved, or freed from a row parked as a repeat. The picture
        # itself never was: the row still points at its file on Drive. Fetching it back means a
        # restored row arrives with its slip, and an approved trip can still be looked at.
        img = _picture_from_drive(trip_id, part)
    if not img:
        raise HTTPException(404, "ไม่มีรูปเก็บไว้ และตามหาต้นฉบับบน Drive ไม่เจอ")
    return Response(content=img[0], media_type=img[1],
                    headers={"Cache-Control": "private, max-age=3600"})


def _picture_from_drive(trip_id: int, part: int):
    """(bytes, mime) from the row's own Drive file, or None. Never raises: a picture we cannot
    fetch is a 404, not a broken page."""
    key = (trip_id, part)
    if key in _DRIVE_PIC:
        return _DRIVE_PIC[key]
    try:
        url = db.trip_image_source(trip_id, part)
        if not url:
            return None
        import re
        m = re.search(r"/d/([^/?]+)", url)
        fid = m.group(1) if m else url.rstrip("/").split("/")[-1]
        if not fid:
            return None
        import roster
        got = (roster._drive().download(fid), "image/jpeg")
    except Exception as e:                                       # noqa: BLE001
        logging.warning("ดึงรูป trip %s จาก Drive ไม่สำเร็จ: %s", trip_id, str(e)[:120])
        return None
    if len(_DRIVE_PIC) > 200:                    # a reviewer's session, not a cache layer
        _DRIVE_PIC.clear()
    _DRIVE_PIC[key] = got
    return got


@app.post("/api/jobs/{job_id}/commit")
def commit(job_id: int, force: bool = False):
    _note("job.approve", f"job:{job_id}", force=force)
    j = db.get_job(job_id)
    if not j:
        raise HTTPException(404, "ไม่พบ job")
    if j["status"] == "committed":
        raise HTTPException(409, "job นี้อนุมัติไปแล้ว")
    done = [t for t in j["trips"] if t["status"] == "done" and not t["committed"]]
    if not done:
        raise HTTPException(400, "ไม่มีรายการที่รออนุมัติ")
    missing = [t["file_name"] for t in done if not t["trip_date"]]
    if missing:
        raise HTTPException(400, f"ยังไม่ได้ระบุวันที่: {', '.join(missing[:5])}")
    if any(t["status"] == "pending" for t in j["trips"]):
        raise HTTPException(400, "ยังอ่านไม่เสร็จ")
    same_rider = db.find_same_rider_code_conflicts(job_id, [t["booking_code"] for t in done])
    if same_rider:
        names = [f"{d['file_name']} (job #{d['job_id']})" for d in same_rider[:5]]
        raise HTTPException(409, f"เที่ยวเหล่านี้ของไรเดอร์คนนี้อนุมัติไปแล้ว: {', '.join(names)} — "
                                 f"ลบรูปที่ซ้ำออกก่อน (กดยืนยันข้ามไม่ได้ เพราะจะทำให้เงินซ้ำ)")
    from collections import Counter
    repeats = [c for c, n in Counter(t["booking_code"] for t in done if t["booking_code"]).items()
               if n > 1]
    if repeats:
        files = [t["file_name"] for t in done if t["booking_code"] in repeats]
        raise HTTPException(409, f"ชุดนี้มีเที่ยวเดียวกันซ้ำกันเอง {len(repeats)} รหัส "
                                 f"({', '.join(files[:5])}) — ลบรูปซ้ำออกก่อน "
                                 f"(กดยืนยันข้ามไม่ได้ เพราะจะทำให้เงินซ้ำ)")
    if not force:
        dup_in_job = [t["file_name"] for t in done if t["duplicate_of"]]
        if dup_in_job:
            raise HTTPException(409, f"มีรูปซ้ำกันเองใน job นี้ ({', '.join(dup_in_job[:5])}) — "
                                     f"ลบรูปที่ซ้ำออกก่อน หรือกดยืนยันบันทึกซ้ำ")
        committed_dups = [d for d in db.find_committed_duplicates([t["booking_code"] for t in done],
                                                                  week=(j["date_from"], j["date_to"]))
                          if d["job_id"] != job_id]
        if committed_dups:
            names = [f"{d['file_name']} (job #{d['job_id']})" for d in committed_dups[:5]]
            raise HTTPException(409, f"พบ {len(committed_dups)} เที่ยวที่เคยอนุมัติไปแล้ว: "
                                     f"{', '.join(names)} — อาจบันทึกซ้ำ ตรวจสอบก่อน หรือกดยืนยันบันทึกซ้ำ")
        if config.EXCEL_APPEND:
            try:
                existing = excel_writer.count_existing_rows(j["driver_name"], {t["trip_date"] for t in done})
            except Exception as e:  # noqa: BLE001 - best-effort guard
                logging.warning("duplicate guard: could not read Excel (%s)", e)
                existing = 0
            if existing:
                raise HTTPException(409, f"ไฟล์ Excel มีข้อมูลของ '{j['driver_name']}' ในช่วงวันที่นี้อยู่แล้ว "
                                         f"{existing} แถว — อาจบันทึกซ้ำ ตรวจสอบก่อน หรือกดยืนยันบันทึกซ้ำ")
    done.sort(key=lambda t: (t["trip_date"], t["trip_time"] or "99:99"))
    written_file = None
    if config.EXCEL_APPEND:
        # local mode: drop the customer images next to the workbook before the blobs are cleared
        out_dir = config.EXCEL_PATH.parent / "Rider Images" / f"{j['date_from']}_{j['date_to']}" / j["driver_name"]
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            for name, data in pipeline.customer_images(job_id, j["driver_name"]):
                (out_dir / name).write_bytes(data)
        except Exception as e:  # noqa: BLE001
            logging.warning("customer images: %s", e)
    if config.EXCEL_APPEND:
        try:
            excel_writer.append_trips(j["driver_name"], done)
            written_file = config.EXCEL_PATH.name
        except excel_writer.ExcelLockedError:
            raise HTTPException(423, f"ไฟล์ {config.EXCEL_PATH.name} ถูกเปิดอยู่ — กรุณาปิดใน Excel ก่อนแล้วลองใหม่")
    db.mark_committed(job_id)
    _note(rider=j["driver_name"], approved=len(done), trip_ids=[t["id"] for t in done])
    return {"written": len(done), "file": written_file}


@app.post("/api/jobs/{job_id}/spread-dates")
def spread_dates(job_id: int, all_rows: bool = False):
    """Spread the job's unapproved trips evenly over its date range (Mon..Sun) in file order."""
    j = db.get_job(job_id)
    if not j:
        raise HTTPException(404, "ไม่พบ job")
    n = pipeline.spread_dates(job_id, j["date_from"], j["date_to"], only_missing=not all_rows)
    _note("job.spread_dates", f"job:{job_id}", all_rows=all_rows, dated=n)
    return {"dated": n}


@app.get("/api/jobs/{job_id}/images.zip")
def job_images_zip(job_id: int):
    """Customer-facing images (stitched, '<rider>N.jpg') — available while the job is unapproved."""
    import io
    import zipfile
    j = db.get_job(job_id)
    if not j:
        raise HTTPException(404, "ไม่พบ job")
    buf = io.BytesIO()
    n = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in pipeline.customer_images(job_id, j["driver_name"]):
            z.writestr(name, data)
            n += 1
    if n == 0:
        raise HTTPException(404, "ไม่มีรูปให้ดาวน์โหลดแล้ว (รูปถูกลบออกจากระบบหลังอนุมัติ) — ดาวน์โหลดก่อนกดอนุมัติ")
    fname = f"{j['driver_name']} {j['date_from']}_{j['date_to']}.zip"
    return Response(content=buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}",
                             "X-File-Count": str(n)})


@app.post("/api/weeks/{date_from}/close")
def close_week(date_from: str, date_to: str = None):
    """ประกาศว่าสัปดาห์นี้จบ — ส่งไฟล์ให้ลูกค้าแล้ว งานอัตโนมัติจะไม่แตะสัปดาห์นี้อีก

    ที่หยุดคือ: การเก็บกวาดรูปซ้ำออกจากโฟลเดอร์ไรเดอร์ และการสร้างรูปส่งลูกค้าใหม่ทับของเดิม
    ที่ยังทำได้: ทุกอย่างที่คนสั่งเอง — ปุ่มบน GitHub, การกดอนุมัติในคิว, การขอไฟล์ Excel"""
    _note("week.lock", f"week:{date_from}")
    if not db.close_week(date_from, date_to, by="app"):
        return {"ok": True, "already": True}
    return {"ok": True}


@app.post("/api/weeks/{date_from}/reopen")
def reopen_week(date_from: str):
    """เปิดสัปดาห์อีกครั้ง — ใช้เมื่อยังต้องแก้ต่อหลังกดปิดไปแล้ว"""
    _note("week.unlock", f"week:{date_from}")
    return {"ok": db.reopen_week(date_from)}


@app.get("/api/weeks")
def weeks():
    open_b = db.open_batches()
    shut = db.closed_weeks()
    rows = db.weeks_overview()
    for w in rows:                       # หน้าเว็บต้องรู้ว่าสัปดาห์ไหนปิดแล้ว เพื่อสลับปุ่ม
        w["closed"] = w.get("date_from") in shut
        w["closed_at"] = (shut.get(w.get("date_from")) or {}).get("closed_at")
    return {"weeks": rows, "last_run": db.latest_ingest_run(),
            "runs": db.list_ingest_runs(10), "issues": db.list_ingest_issues(50),
            "batch_waiting": sum(b.get("n_trips") or 0 for b in open_b),
            "batch_since": (open_b[0]["created_at"] if open_b else None),
            "can_trigger": bool(config.GITHUB_TOKEN and config.GITHUB_REPO),
            "exports_folder": config.DRIVE_EXPORTS_FOLDER_ID, "inbox_folder": config.DRIVE_INBOX_FOLDER_ID}


def _refresh_batch_states(rows, limit=40, workers=10):
    """Ask Gemini where each open batch actually is.

    The stored state only moves when a round collects, so without this a batch that finished
    minutes after being sent still reads 'รอคิว' hours later. Asking one at a time made that
    worse — with twenty batches open only the newest few were ever refreshed, and the rest sat
    on screen looking queued when they were done. They are asked together instead."""
    from concurrent.futures import ThreadPoolExecutor

    import batch_client
    todo = [r for r in rows if not r.get("finished_at")][:limit]
    if not todo:
        return rows

    def one(r):
        try:
            live = batch_client.state(r["name"])
            if live and live != r["state"]:
                db.touch_batch(r["name"], live)
                r["state"] = live
        except Exception as e:  # noqa: BLE001
            r["state_error"] = str(e)[:120]   # keep the stored state, say it is not fresh
        return r

    with ThreadPoolExecutor(max_workers=min(workers, len(todo))) as ex:
        list(ex.map(one, todo))
    return rows


@app.get("/api/batches")
def batches(limit: int = 20):
    """What is out with the batch reader right now, and what came back lately.

    The stored state only moves when a round collects, so an open batch is asked directly —
    otherwise the page would show 'รอคิว' for four hours after the work was actually done."""
    rows = _refresh_batch_states(db.recent_batches(limit))
    open_rows = [r for r in rows if not r.get("finished_at")]
    return {"batches": rows, "open": len(open_rows),
            "ready_images": sum(r.get("n_trips") or 0 for r in open_rows
                                if str(r.get("state") or "").endswith("SUCCEEDED")),
            "waiting_images": sum(r.get("n_trips") or 0 for r in open_rows),
            "mode": "batch" if config.INGEST_BATCH else "live"}


@app.post("/api/batches/collect")
def collect_batches_now():
    _note("batches.collect")
    """Pull in whatever the batch reader has finished, without waiting for the next round.

    Runs in the web app, which has no Drive credentials, so the customer images and the Drive
    workbook still wait for a proper round — but the trips, the pairing and the approvals land
    immediately, which is what Ops is looking at."""
    import ingest
    try:
        got, errs, jobs_touched, issues = ingest.collect_batches(None)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"เก็บผล batch ไม่สำเร็จ: {str(e)[:200]}")
    # this path cannot reach Drive, so the customer images are still owed — leave that on the
    # issue list one by one, which is the list the next round works through
    for key, kind, message in issues:
        db.note_issue(key, kind, message)
    still = db.open_batches()
    return {"ok": True, "trips": got, "errors": errs, "jobs": len(jobs_touched),
            "waiting": sum(b.get("n_trips") or 0 for b in still)}


# The 'งานซ้ำ' tab: the duplicate report's per-album sheet, for a phone (Fiat 2026-09-29: "เช็คงาน
# ซ้ำแบบไม่เปิดคอม ... ง่ายๆ ที่สุด ไม่ต้อง Details"). Weeks from W39 on — earlier weeks were
# delivered before the pool noted which album a picture came from.
DUP_TAB_FROM = "2026-09-21"
DUP_ALBUM_KEYS = ["no", "album", "first", "read", "filed", "pre", "post", "dup", "pct", "with",
                  "left", "waiting", "status"]
_dup_cache = {}          # week -> (time, payload): a phone reopening the tab does not re-query


def _dup_weeks():
    from sqlalchemy import func, select
    with db.engine.begin() as c:
        found = c.execute(select(func.distinct(db.jobs.c.date_from))
                          .where(db.jobs.c.date_from >= DUP_TAB_FROM)).scalars().all()
    return sorted({w for w in found if w}, reverse=True)


def _dup_week(w):
    """{cases, undecided, pre, albums} of one week, kept DUP_CACHE_SECONDS — a phone reopening
    the tab, the overview and the detail panel all ask for the same thing."""
    import time as _time
    from datetime import date, timedelta

    import duplicate_report as dr
    hit = _dup_cache.get(w)
    if hit and _time.time() - hit[0] < DUP_CACHE_SECONDS:
        return hit[1]
    d_to = (date.fromisoformat(w) + timedelta(days=6)).isoformat()
    cases, undecided = dr.build(*dr.load(w, d_to))
    pre = dr.pre_read_cases(w)
    data = {"cases": cases, "undecided": undecided, "pre": pre,
            "albums": dr.album_overview(w, d_to, cases, pre),
            "as_of": datetime.now().strftime("%Y-%m-%d %H:%M")}
    _dup_cache[w] = (_time.time(), data)
    return data


DUP_CACHE_SECONDS = 120


@app.get("/api/duplicates/albums")
def duplicate_albums(week: str = ""):
    from ingest import week_label
    weeks_ = _dup_weeks()
    shut = db.closed_weeks()
    listing = [{"date_from": w, "label": week_label(w), "closed": w in shut} for w in weeks_]
    if not weeks_:
        return {"weeks": [], "week": None, "albums": []}
    w = week if week in weeks_ else weeks_[0]
    d = _dup_week(w)
    return {"week": w, "label": week_label(w), "albums": [dict(zip(DUP_ALBUM_KEYS, r)) for r in d["albums"]],
            "as_of": d["as_of"], "weeks": listing}


@app.get("/api/duplicates/album")
def duplicate_album(week: str, album: str):
    """Every repeat of one album, each beside the picture it repeats: read ones (booking code,
    can be put back) and copies dropped before reading (same file, nothing was read)."""
    if week not in _dup_weeks():
        raise HTTPException(404, "ไม่พบสัปดาห์นี้")
    d = _dup_week(week)
    pairs = [{"kind": c.get("ประเภทการซ้ำ"), "trip_id": c["id"], "twin_id": c.get("twin_id"),
              "rider": c.get("โฟลเดอร์ที่ระบบวาง"), "date": c.get("วันที่งาน"), "code": c.get("รหัสการจอง"),
              "net": c.get("ยอด"), "file": c.get("ไฟล์ที่ซ้ำ"), "twin_file": c.get("ซ้ำกับไฟล์"),
              "twin_album": c.get("ของไรเดอร์"), "url": c.get("ลิงก์รูป"), "twin_url": c.get("twin_url"),
              "restorable": True}
             for c in d["cases"] if c.get("ไรเดอร์ผู้ส่ง") == album]
    pairs += [{"kind": p.get("ประเภทการซ้ำ") or "ไฟล์เดิมส่งซ้ำ", "pre": True, "file": p.get("ไฟล์ที่ซ้ำ"),
               "twin_file": p.get("ซ้ำกับไฟล์"), "twin_album": p.get("ของอัลบั้ม"), "link": p.get("ลิงก์รูป"),
               "found": p.get("เจอเมื่อ"), "restorable": False}
              for p in d["pre"] if p.get("ไรเดอร์ผู้ส่ง") == album]
    return {"week": week, "album": album, "pairs": pairs}


@app.get("/api/duplicates/report.xlsx")
def duplicate_report_xlsx(week: str):
    """The same workbook the ingest round puts in Drive, built now, for the admins."""
    import duplicate_report as dr
    from ingest import week_label
    if week not in _dup_weeks():
        raise HTTPException(404, "ไม่พบสัปดาห์นี้")
    d = _dup_week(week)
    data = dr.build_xlsx(d["cases"], d["undecided"], d["pre"], d["albums"])
    name = f"งานซ้ำ {week_label(week).replace('-W', ' WK')}.xlsx"
    return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


# ---------- ภาพรวม: the customer's first screen (overview.py) ----------

OVERVIEW_WEEKS_SHOWN = 3


@app.get("/api/overview")
def overview_page(week: str = ""):
    from datetime import date, timedelta

    from sqlalchemy import func, select

    import overview
    from ingest import week_label
    today = datetime.now(db._TZ_BKK).date()
    with db.engine.begin() as c:
        found = c.execute(select(func.distinct(db.jobs.c.date_from))).scalars().all()
    weeks_ = sorted({w for w in found if w and w <= today.isoformat()}, reverse=True)[:OVERVIEW_WEEKS_SHOWN]
    shut = db.closed_weeks()
    listing = [{"date_from": w, "label": week_label(w), "closed": w in shut,
                "current": w <= today.isoformat() <= (date.fromisoformat(w) + timedelta(days=6)).isoformat()}
               for w in weeks_]
    if not weeks_:
        return {"weeks": [], "week": None}
    w = week if week in weeks_ else weeks_[0]
    d_to = (date.fromisoformat(w) + timedelta(days=6)).isoformat()
    # The albums card is the slow part (every picture of every album of the week) and was making
    # each week switch wait for it (Fiat 2026-10-02: "สลับวีคมันหน่วง"). The page asks for it
    # separately, from /api/duplicates/albums, and fills the card when it comes.
    out = overview.build(w, d_to)
    out.update(weeks=listing, label=week_label(w), days_left=max(0, (date.fromisoformat(d_to) - today).days))
    return out


# ---------- ปิดสัปดาห์: one button instead of six workflows (close_week.py) ----------

CLOSE_WEEKS_SHOWN = 4
PLAN_FRESH_HOURS = 12        # a plan older than this is not enough to press 'ปิดจริง' on


def _plan_fresh(runs):
    """The newest finished plan, if it is recent and nothing has been closed since."""
    for r in runs:
        if r["mode"] == "apply" and r["status"] == "done":
            return None                      # closed (or tried) after any plan below it
        if r["mode"] == "plan" and r["status"] == "done" and r.get("finished_at"):
            age = (datetime.now(db._TZ_BKK).replace(tzinfo=None)
                   - datetime.fromisoformat(r["finished_at"])).total_seconds() / 3600
            return r if age < PLAN_FRESH_HOURS else None
    return None


@app.get("/api/close-week")
def close_week_page(week: str = ""):
    from datetime import date, timedelta

    from sqlalchemy import func, select

    import close_week as cw
    from ingest import week_label
    with db.engine.begin() as c:
        found = c.execute(select(func.distinct(db.jobs.c.date_from))).scalars().all()
    today = datetime.now(db._TZ_BKK).date().isoformat()
    weeks_ = sorted({w for w in found if w and w <= today}, reverse=True)[:CLOSE_WEEKS_SHOWN]
    shut = db.closed_weeks()
    listing = [{"date_from": w, "label": week_label(w), "closed": w in shut} for w in weeks_]
    if not weeks_:
        return {"weeks": [], "week": None}
    # the week to show first: the oldest one not closed yet — that is the one waiting to be closed
    open_ = [w for w in weeks_ if w not in shut]
    w = week if week in weeks_ else (open_[-1] if open_ else weeks_[0])
    d_to = (date.fromisoformat(w) + timedelta(days=6)).isoformat()
    runs = db.close_runs_of_week(w)
    for r in runs:                           # the page shows summaries; logs come one run at a time
        for s in r["steps"]:
            s.pop("log", None)
    active = db.close_run_active()
    folder = next((x["drive_id"] for x in db.drive_links()
                   if x["week"] == week_label(w) and x["kind"] == "week_folder" and not x.get("ref")), None)
    last_close = db.last_close_run(w)
    files = {"pictures": f"https://drive.google.com/drive/folders/{folder}" if folder else None,
             "phase3": (last_close or {}).get("result", {}).get("file"),
             "audit": (last_close or {}).get("result", {}).get("audit_file")}
    return {"weeks": listing, "week": w, "week_to": d_to, "label": week_label(w), "files": files,
            "closed": shut.get(w), "preflight": cw.preflight(w, d_to), "runs": runs,
            "plan_ok": bool(_plan_fresh(runs)), "active": active and active["id"],
            "target": config.WEEKLY_TARGET_PER_GROUP,
            "can_dispatch": bool(config.GITHUB_TOKEN and config.GITHUB_REPO)}


@app.get("/api/close-week/runs/{run_id}")
def close_week_run(run_id: int):
    r = db.get_close_run(run_id)
    if not r:
        raise HTTPException(404, f"ไม่พบรอบปิด #{run_id}")
    return r


@app.post("/api/close-week/{date_from}/{mode}")
def close_week_start(date_from: str, mode: str):
    """Start a plan or a real close. A real close needs: the checks passing, a plan finished in
    the last PLAN_FRESH_HOURS, and no other close queued or running."""
    from datetime import date, timedelta

    import close_week as cw
    if mode not in ("plan", "apply"):
        raise HTTPException(400, "mode ต้องเป็น plan หรือ apply")
    try:
        d_to = (date.fromisoformat(date_from) + timedelta(days=6)).isoformat()
    except ValueError:
        raise HTTPException(400, "วันที่ไม่ถูกต้อง")
    active = db.close_run_active()
    if active:
        raise HTTPException(409, f"มีรอบปิด #{active['id']} ของสัปดาห์ {active['week_from']} กำลังรันอยู่ — รอให้จบก่อน")
    if mode == "apply":
        pre = cw.preflight(date_from, d_to)
        if not pre["ok"]:
            bad = [f"{c['label']}: {c['detail']}" for c in pre["checks"] if c["level"] == "block" and not c["ok"]]
            raise HTTPException(409, "ยังปิดไม่ได้ — " + " · ".join(bad))
        if not _plan_fresh(db.close_runs_of_week(date_from)):
            raise HTTPException(409, f"กด 'ดูแผน' ก่อน — ต้องมีแผนที่ทำไม่เกิน {PLAN_FRESH_HOURS} ชม.")
    _note(f"close.{mode}", f"week:{date_from}")
    run_id = db.create_close_run(date_from, d_to, mode)
    _note(run=run_id)
    try:
        _dispatch("close-week.yml", {"week_from": date_from, "week_to": d_to, "mode": mode,
                                     "run_id": str(run_id)})
    except HTTPException as e:
        db.update_close_run(run_id, status="failed", finished_at=db._now(), message=str(e.detail))
        raise
    return db.get_close_run(run_id)


@app.get("/api/completeness")
def completeness():
    """Per week and vehicle group: how much work is in, how much is owed, who is short.

    The Agent reads this before asking an admin for more slips, so everything is counted in
    trips. Each vehicle group owes the customer WEEKLY_TARGET_PER_GROUP trips on its own —
    a group that runs over does not cover one that runs short, so the week's shortfall is the
    sum of the groups' shortfalls, never target-minus-total. Groups outside the team's four
    vehicle categories (hand uploads, unfiled) have no target of their own and are measured by
    the riders in them. A rider who sent nothing at all is counted against the group they rode
    for last time (otherwise the biggest hole is invisible), and a slip that has arrived but
    has not been read yet already counts as collected: the Agent must not go asking for photos
    that are sitting in the queue."""
    exp = config.EXPECTED_TRIPS_PER_WEEK
    quota = config.WEEKLY_TARGET_PER_GROUP
    import pipeline
    with_quota = set(pipeline.CATEGORY_SERVICE)
    weeks_ = db.weeks_overview()
    # where each rider was last seen, so an absent rider still lands in a vehicle group
    last_group = {}
    # Who was working the week before, which is what makes 'sent nothing' mean anything. Ops
    # rotates about a fifth of the pool out every week on purpose, so 'anyone ever seen who is
    # not here now' grows for good and never shrinks: it read 212 riders as having sent nothing
    # in 31 Aug-6 Sep, when almost all of them were simply not rostered. Somebody who worked
    # last week and sent nothing this week is a person to go and ask about.
    prev_people = {}
    seen_before = set()
    for W in sorted(weeks_, key=lambda w: w["date_from"]):
        here = set()
        for g in W["groups"]:
            for j in g["jobs"]:
                last_group[j["driver_name"]] = g["category"]
                here.add(j["driver_name"])
        prev_people[W["date_from"]] = set(seen_before)
        seen_before = here

    # a group with a target that sent nothing this week is the biggest hole there is, and it
    # has no jobs to be found through — so every group the team actually runs is seeded empty
    running = {g["category"] for W in weeks_ for g in W["groups"] if g["category"] in with_quota}

    def blank(cat):
        return {"category": cat, "riders": 0, "done": 0, "read": 0, "approved": 0,
                "waiting": 0, "unread": 0, "short": [], "absent": [], "_people": set()}

    out = []
    for W in weeks_:
        groups, present = {cat: blank(cat) for cat in running}, set()
        # A rider is a person, not a folder. Someone who works both tiers has a folder in each
        # group and one 21 across the two — the way the allocator has counted them since the
        # quota was moved onto the person. Counting folders here reported มานิตย์ as 21/21 in
        # Standard and, on the same screen, 0/21 in Saver; it counted a folder the quota
        # rebalance had emptied as a whole missing 21; and it read the ~500 seats that repeat
        # pictures were holding as riders who had sent nothing. So the totals below stay per
        # group, because trips are what a group owes, and who is short is asked of the person.
        people = {}
        for g in W["groups"]:
            cat = g["category"] or "ไม่ระบุกลุ่มรถ"
            b = groups.setdefault(cat, blank(cat))
            for j in g["jobs"]:
                present.add(j["driver_name"])
                # read + still queued + failed to read: all three are slips already in hand
                collected = (j["done"] or 0) + (j["pending"] or 0) + (j["errors"] or 0)
                b["done"] += collected
                b["read"] += j["done"] or 0
                b["approved"] += j["approved"] or 0
                b["waiting"] += j["waiting"] or 0
                b["unread"] += (j["pending"] or 0) + (j["errors"] or 0)
                b["_people"].add(j["driver_name"])
                p = people.setdefault(j["driver_name"], {
                    "driver_name": j["driver_name"], "done": 0, "read": 0, "approved": 0,
                    "waiting": 0, "pending": 0, "errors": 0, "job_id": j["id"], "cats": {},
                })
                p["done"] += collected
                p["read"] += j["done"] or 0
                p["approved"] += j["approved"] or 0
                p["waiting"] += j["waiting"] or 0
                p["pending"] += j["pending"] or 0
                p["errors"] += j["errors"] or 0
                p["cats"][cat] = p["cats"].get(cat, 0) + collected
                if collected >= max(p["cats"].values()):
                    p["job_id"] = j["id"]        # open the folder holding most of their week
        for p in people.values():
            missing = max(0, exp - p["done"])
            if not missing:
                continue
            home = max(p["cats"], key=lambda c: (p["cats"][c], c))
            groups.setdefault(home, blank(home))["short"].append({
                "driver_name": p["driver_name"], "job_id": p["job_id"], "done": p["done"],
                "read": p["read"], "approved": p["approved"], "waiting": p["waiting"],
                "pending": p["pending"], "errors": p["errors"], "missing": missing,
                # so the screen can say 'ยังอ่านไม่เสร็จ' rather than 'ยังไม่ได้ส่ง': a rider
                # whose slips are all sitting in a batch is not a rider anyone should chase
                "folders": len(p["cats"]),
                "unread": p["pending"] + p["errors"],
            })
        for rider in prev_people.get(W["date_from"], ()):
            if rider in present:
                continue
            cat = last_group.get(rider) or "ไม่ระบุกลุ่มรถ"
            groups.setdefault(cat, blank(cat))["absent"].append(rider)

        packed = []
        for b in groups.values():
            b["riders"] = len(b.pop("_people"))          # people, not folders
            b["short"].sort(key=lambda r: -r["missing"])
            b["absent"].sort()
            heads = b["riders"] + len(b["absent"])
            b["quota"] = b["category"] in with_quota          # does the customer buy this group?
            b["target"] = quota if b["quota"] else heads * exp
            b["missing"] = max(0, b["target"] - b["done"])
            # what the riders on the books can produce at the weekly quota each — a group can be
            # short on trips because people under-sent, or because there are not enough people
            b["capacity"] = heads * exp
            # riders still to be recruited: even everyone hitting their quota would fall short
            b["heads_needed"] = max(0, -(-(b["target"] - b["capacity"]) // exp)) if b["quota"] else 0
            b["complete"] = b["riders"] - len(b["short"])
            packed.append(b)
        packed.sort(key=lambda b: -b["missing"])
        out.append({
            "week": W["week"], "date_from": W["date_from"], "date_to": W["date_to"],
            # summing the groups counts anyone who works two tiers twice
            "riders": len(people) + sum(len(b["absent"]) for b in packed),
            "short": sum(len(b["short"]) for b in packed),
            "done": sum(b["done"] for b in packed),
            "read": sum(b["read"] for b in packed),
            "unread": sum(b["unread"] for b in packed),
            "approved": sum(b["approved"] for b in packed),
            "waiting": sum(b["waiting"] for b in packed),
            "target": sum(b["target"] for b in packed),
            "missing": sum(b["missing"] for b in packed),
            "groups": packed,
        })
    return {"weeks": out, "expected": exp, "group_target": quota}


def _dispatch_ingest():
    return _dispatch(config.GITHUB_WORKFLOW)


def _dispatch(workflow, inputs=None):
    if not (config.GITHUB_TOKEN and config.GITHUB_REPO):
        raise HTTPException(501, "ยังไม่ได้ตั้งค่า GITHUB_TOKEN / GITHUB_REPO — ตั้งแล้วปุ่มนี้จะสั่งรันได้")
    import urllib.request
    url = f"https://api.github.com/repos/{config.GITHUB_REPO}/actions/workflows/{workflow}/dispatches"
    body = json.dumps({"ref": "main", "inputs": inputs or {}}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {config.GITHUB_TOKEN}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status in (200, 204)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"สั่ง GitHub ไม่สำเร็จ: {str(e)[:200]}")


@app.post("/api/ingest/trigger")
def trigger_ingest():
    """Kick the GitHub Actions ingest workflow (workflow_dispatch)."""
    _note("ingest.trigger")
    return {"ok": _dispatch_ingest(), "url": f"https://github.com/{config.GITHUB_REPO}/actions"}


@app.get("/api/ingest/cron")
@app.post("/api/ingest/cron")
def cron_ingest(min_gap_hours: float = 4.0):
    """Start a round from OUTSIDE GitHub, for a free external cron service to call.

    GitHub's own scheduler is the weak link: it silently dropped both of 2026-08-27's rounds
    and habitually runs 27-31 minutes late. This endpoint takes the diag key instead of a
    login, refuses to pile a second round on top of a running one, and ignores calls that
    come too soon after the last round — so a pinger firing more often than intended, or
    twice by accident, costs nothing."""
    runs = db.list_ingest_runs(1)
    last = runs[0] if runs else None
    _note("ingest.cron")
    if last and not last.get("finished_at"):
        return {"ok": False, "skipped": "มีรอบกำลังรันอยู่", "run": last.get("started_at")}
    if last and last.get("started_at"):
        from datetime import datetime
        age = (datetime.now(db._TZ_BKK).replace(tzinfo=None)
               - datetime.fromisoformat(last["started_at"])).total_seconds() / 3600
        if age < min_gap_hours:
            return {"ok": False, "skipped": f"รอบล่าสุดเพิ่งจบไป {age:.1f} ชม.",
                    "run": last.get("started_at")}
    return {"ok": _dispatch_ingest(), "dispatched_at": db._now()}


@app.patch("/api/jobs/{job_id}/rider")
async def rename_job_rider(job_id: int, body: dict):
    """Rename the rider on a job — for a Drive folder that arrived without a name."""
    old = db.get_job(job_id)
    _note("job.rename", f"job:{job_id}", before=old and old.get("driver_name"), after=body.get("name"))
    try:
        r = db.rename_job(job_id, body.get("name"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not r:
        raise HTTPException(404, f"ไม่พบ job #{job_id}")
    return r


@app.get("/api/drivers")
def drivers():
    return {"drivers": db.list_drivers()}


@app.get("/api/export")
def export(date_from: str = None, date_to: str = None, driver: str = None,
           job_id: int = None, committed_only: bool = True):
    rows = db.query_trips(date_from, date_to, driver, committed_only, job_id)
    data = excel_writer.build_workbook(rows)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    parts = ["Rider Trips"]
    if job_id:
        parts.append(f"job{job_id}")
    if date_from or date_to:
        parts.append(f"{date_from or ''}_{date_to or ''}")
    fname = f"{' '.join(parts)} {stamp}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}",
                 "X-Row-Count": str(len(rows))},
    )


@app.get("/api/export/phase2")
def export_phase2():
    """The Phase 2 workbook (real pick-up / drop-off from W36 on), built from the database now."""
    rows = db.query_trips(committed_only=True)
    data = excel_writer.build_location_workbook(rows) or excel_writer.build_workbook([])
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    fname = f"Rider Trips Phase 2 {stamp}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}"},
    )


@app.get("/api/export/phase3")
def export_phase3():
    """The Phase 3 workbook (every line of the passenger's fare block, from W38), built now."""
    rows = db.query_trips(committed_only=True)
    data = excel_writer.build_fare_lines_workbook(rows) or excel_writer.build_workbook([])
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    fname = f"Rider Trips Phase 3 {stamp}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}"},
    )


@app.get("/api/export/week")
def export_week(week: str):
    """One week's customer file in the Phase 3 layout, built now — the 'ไฟล์ส่งลูกค้า' card of
    the close-week tab. The same rows and layout week_phase3.py puts on Drive at the close."""
    import week_phase3
    from datetime import date, timedelta
    try:
        d_to = (date.fromisoformat(week) + timedelta(days=6)).isoformat()
    except ValueError:
        raise HTTPException(400, "วันที่ไม่ถูกต้อง")
    rows = week_phase3.week_rows(week, d_to)
    if not rows:
        raise HTTPException(404, "สัปดาห์นี้ยังไม่มีแถวที่อนุมัติแล้ว")
    data = excel_writer.build_fare_lines_workbook(rows, every_week=True)
    name = week_phase3.file_name(week)
    return Response(content=data,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
                             "X-Row-Count": str(len(rows))})


# Ops (2026-09-09): "a button that syncs the Excel without waiting for an ingest round". An
# ingest round rewrites both customer workbooks on Drive, but only every few hours and only
# after the whole round; an approval made in the review queue at 10:00 reached the customer's
# file at 13:00. This does the same rewrite, from the same rows, on demand — in the background,
# because 13,000 rows take a little while, and the page asks how it went.
_sync = {"state": "idle"}
_sync_lock = __import__("threading").Lock()


def _sync_workbooks():
    import ingest
    import roster
    try:
        # The same fingerprint an ingest round uses: three numbers from one small query. When
        # nothing approved has changed since the workbooks were last written, there is nothing
        # to write — and no 13,000-row pull from Neon for a click that changes nothing.
        stamp = f"{excel_writer.LAYOUT}:{db.committed_fingerprint()}"
        if stamp == db.state_get(ingest.XLSX_KEY):
            _sync.update(state="done", rows=0, unchanged=True, error=None,
                         finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            return
        drive = roster._drive()
        rows = db.query_trips(committed_only=True)
        fid = drive.upload_xlsx(config.DRIVE_EXPORTS_FOLDER_ID, "Rider Trips.xlsx",
                                excel_writer.build_workbook(rows))
        for later, data in excel_writer.later_workbooks(rows):
            drive.upload_xlsx(config.DRIVE_EXPORTS_FOLDER_ID, later, data)
        for (d_from, _), _js in db.jobs_by_week().items():
            db.record_drive_file(ingest.week_label(d_from), "xlsx", fid, "Rider Trips.xlsx")
        db.state_set(ingest.XLSX_KEY, f"{excel_writer.LAYOUT}:{db.committed_fingerprint()}")
        _sync.update(state="done", rows=len(rows), finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                     error=None)
    except Exception as e:  # noqa: BLE001 — the page shows the reason; nothing else is affected
        _sync.update(state="error", error=str(e)[:200], finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


@app.get("/api/export/sync")
def export_sync_status():
    return dict(_sync)


@app.post("/api/export/sync")
def export_sync():
    _note("export.sync")
    if not (config.DRIVE_OAUTH_TOKEN or config.GOOGLE_SERVICE_ACCOUNT) or not config.DRIVE_EXPORTS_FOLDER_ID:
        raise HTTPException(501, "เซิร์ฟเวอร์นี้ยังเขียน Drive ไม่ได้ — ตั้ง DRIVE_OAUTH_TOKEN_JSON และ "
                                 "DRIVE_EXPORTS_FOLDER_ID ใน Render ก่อน (ค่าเดียวกับ GitHub secret) · "
                                 "ระหว่างนี้ใช้ปุ่มดาวน์โหลดได้")
    with _sync_lock:
        if _sync.get("state") == "running":
            return dict(_sync)
        _sync.update(state="running", started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), error=None)
    __import__("threading").Thread(target=_sync_workbooks, daemon=True).start()
    return dict(_sync)


# ---------- Phase C: dashboard / data view / review queue ----------

@app.get("/api/summary")
def summary(date_from: str = None, date_to: str = None):
    return {**db.summary(date_from, date_to), "ingest_runs": db.list_ingest_runs(8)}


@app.get("/api/trips")
def trips_view(date_from: str = None, date_to: str = None, driver: str = None,
               status: str = "all", q: str = None, page: int = 1, size: int = 50):
    size = max(1, min(size, 200))
    rows, total = db.search_trips(date_from, date_to, driver, status, q, size, (max(page, 1) - 1) * size)
    from zones import zone_for
    for r in rows:  # the same derived values Sheet1 shows (คอลัมน์ C/F/G/J/P/Q)
        r["time_band"] = excel_writer.time_band(r.get("trip_time"))
        r["pickup_zone"] = zone_for(r.get("pickup_district"), r.get("pickup_code"), r.get("pickup_text"))
        r["dropoff_zone"] = zone_for(r.get("dropoff_district"), r.get("dropoff_code"), r.get("dropoff_text"))
        pf = excel_writer.passenger_fare(r)
        net = None
        if r.get("base_fare") is not None:
            net = round((r.get("base_fare") or 0) + (r.get("bonus") or 0) + (r.get("turbo") or 0), 2)
        r["passenger_fare"] = pf
        r["passenger_fare_estimated"] = excel_writer.passenger_fare_estimated(r)
        r["sheet_net"] = net
        r["service_fee"] = round(pf - net, 2) if (pf is not None and net is not None) else None
    return {"rows": rows, "total": total, "page": page, "size": size}


@app.get("/api/review-queue")
def review_queue():
    return {"rows": db.review_queue(), "issues": db.list_ingest_issues(50)}


@app.post("/api/review-queue/approve-passing")
def approve_passing():
    """One click for the whole queue: approve every waiting row that passed the checks, is not
    a duplicate, and has a date. Anything the system is unsure about stays put."""
    rows = db.review_queue()
    ok = [r for r in rows if r.get("check_status") == "pass" and not r.get("duplicate_of")
          and r.get("trip_date") and not r.get("seen_in_job")]
    done, failed, ids = 0, [], []
    for r in ok:
        res = db.approve_trip(r["id"])
        if "error" in res:
            failed.append({"file_name": r["file_name"], "error": res["error"]})
        else:
            done += 1
            ids.append(r["id"])
    _note("queue.approve_passing", approved=done, trip_ids=ids, failed=len(failed))
    return {"approved": done, "skipped": len(rows) - len(ok), "failed": failed}


@app.post("/api/trips/{trip_id}/approve")
def approve_trip(trip_id: int):
    _note("trip.approve", f"trip:{trip_id}")
    r = db.approve_trip(trip_id)
    if "error" in r:
        raise HTTPException(400, r["error"])
    return r


# ---------- read-only diagnostics (header X-Diag-Key; see auth_gate) ----------

@app.get("/api/diag/schedule")
def diag_schedule():
    """Ask GitHub why the scheduled rounds are not firing.

    A workflow can be switched off — by hand, or by GitHub itself when a repository goes quiet —
    and nothing about that is visible from inside the app. This reads the workflow's own state
    and its last runs by event, which separates 'never triggered' from 'triggered and failed'."""
    import urllib.request
    if not (config.GITHUB_TOKEN and config.GITHUB_REPO):
        raise HTTPException(501, "ยังไม่ได้ตั้งค่า GITHUB_TOKEN / GITHUB_REPO")
    base = f"https://api.github.com/repos/{config.GITHUB_REPO}"
    head = {"Authorization": f"Bearer {config.GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}

    def get(path):
        req = urllib.request.Request(base + path, headers=head)
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    out = {}
    try:
        wf = get(f"/actions/workflows/{config.GITHUB_WORKFLOW}")
        out["workflow"] = {"name": wf.get("name"), "state": wf.get("state"),
                           "path": wf.get("path")}
    except Exception as e:  # noqa: BLE001
        out["workflow_error"] = str(e)[:200]
    for event in ("schedule", "workflow_dispatch"):
        try:
            runs = get(f"/actions/workflows/{config.GITHUB_WORKFLOW}/runs"
                       f"?event={event}&per_page=5")
            out[event] = [{"created_at": r["created_at"], "status": r["status"],
                           "conclusion": r["conclusion"], "branch": r["head_branch"]}
                          for r in runs.get("workflow_runs", [])]
            out[f"{event}_total"] = runs.get("total_count")
        except Exception as e:  # noqa: BLE001
            out[f"{event}_error"] = str(e)[:200]
    return out


@app.get("/api/diag/jobs")
def diag_jobs():
    """Every job with week, vehicle group, admin and counts — for roster questions."""
    return {"jobs": db.jobs_overview()}


@app.get("/api/diag/db")
def diag_db():
    """Why the database is refusing us, in words. Every other diagnostic answers 500 when the
    connection is gone, which says nothing about whether it is the network, the credentials or
    the provider suspending the project."""
    from sqlalchemy import text
    out = {"url_host": (config.DATABASE_URL.split("@")[-1].split("/")[0]
                        if "@" in config.DATABASE_URL else "local")}
    try:
        with db.engine.begin() as c:
            out["select_1"] = c.execute(text("SELECT 1")).scalar()
            out["trips"] = c.execute(text("SELECT count(*) FROM trips")).scalar()
            out["db_size_mb"] = round((c.execute(
                text("SELECT pg_database_size(current_database())")).scalar() or 0) / 1e6, 1)
        out["ok"] = True
    except Exception as e:  # noqa: BLE001
        out["ok"] = False
        out["error_type"] = type(e).__name__
        out["error"] = str(e)[:600]
    return out


@app.get("/api/diag/summary")
def diag_summary():
    from sqlalchemy import case, func, select
    with db.engine.begin() as c:
        t = db.trips.c
        r = c.execute(select(
            func.sum(case((t.status == "done", 1), else_=0)),
            func.sum(case(((t.status == "done") & (t.committed == 1), 1), else_=0)),
            func.sum(case(((t.status == "done") & (t.committed == 0), 1), else_=0)),
            func.sum(case((t.status == "error", 1), else_=0)),
            func.sum(case((t.status == "pending", 1), else_=0)),
            func.count(func.distinct(t.job_id)))).first()
    return {"done": r[0] or 0, "approved": r[1] or 0, "waiting": r[2] or 0,
            "errors": r[3] or 0, "pending": r[4] or 0, "jobs": r[5] or 0,
            "runs": db.list_ingest_runs(10), "issues": db.list_ingest_issues(30)}


def _strip_logs(runs):
    for r in runs:
        for s in r.get("steps") or []:
            s.pop("log", None)
    return runs


@app.get("/api/diag/actions")
def diag_actions(limit: int = 200, since: str = "", target: str = "", action: str = ""):
    """Who changed what: every non-GET request, newest first (action_log)."""
    return {"actions": db.list_actions(min(limit, 2000), since or None, target or None, action or None)}


@app.get("/api/diag/close-runs")
def diag_close_runs(week: str = "", limit: int = 20):
    """Close-week runs, without the step logs; /api/diag/close-runs/{id} has them."""
    from sqlalchemy import select
    q = select(db.close_runs).order_by(db.close_runs.c.id.desc()).limit(min(limit, 200))
    if week:
        q = q.where(db.close_runs.c.week_from == week)
    with db.engine.begin() as c:
        runs = [db._close_run_dict(r) for r in c.execute(q).mappings().all()]
    return {"runs": _strip_logs(runs)}


@app.get("/api/diag/close-runs/{run_id}")
def diag_close_run(run_id: int):
    r = db.get_close_run(run_id)
    if not r:
        raise HTTPException(404, f"ไม่พบรอบปิด #{run_id}")
    return r


@app.get("/api/diag/runs")
def diag_runs(limit: int = 50, workflow: str = "", conclusion: str = "", since: str = ""):
    """GitHub Actions runs archived by archive_runs.py — kept a year, GitHub keeps 90 days."""
    return {"runs": db.list_workflow_runs(min(limit, 500), workflow or None, conclusion or None, since or None)}


@app.get("/api/diag/runs/{run_id}")
def diag_run(run_id: int):
    r = db.get_workflow_run(run_id)
    if not r:
        raise HTTPException(404, f"ไม่พบรอบ #{run_id} ในที่เก็บ (เก็บวันละครั้ง — รอบที่เพิ่งจบดูบน GitHub)")
    return r


@app.get("/api/diag/support")
def diag_support():
    """One look at the whole system for support: what is waiting, what failed, who did what."""
    from datetime import timedelta
    week_ago = (datetime.now(db._TZ_BKK).replace(tzinfo=None) - timedelta(days=7)).isoformat(timespec="seconds")
    runs = db.list_ingest_runs(10)
    last = runs[0] if runs else None
    open_b = db.open_batches()
    from sqlalchemy import select
    with db.engine.begin() as c:
        closes = [db._close_run_dict(r) for r in c.execute(
            select(db.close_runs).order_by(db.close_runs.c.id.desc()).limit(5)).mappings().all()]
    return {
        "now": db._now(),
        "counts": {k: v for k, v in diag_summary().items() if k not in ("runs", "issues")},
        "ingest": {"last": last, "runs": runs},
        "issues": db.list_ingest_issues(30),
        "batches": {"open": len(open_b), "trips": sum(b.get("n_trips") or 0 for b in open_b),
                    "oldest": open_b[0]["created_at"] if open_b else None},
        "close_runs": _strip_logs(closes),
        "failed_runs": db.list_workflow_runs(30, conclusion="failure", since=week_ago),
        "archived_last": (db.list_workflow_runs(1) or [{}])[0].get("archived_at"),
        "actions": db.list_actions(40),
        "closed_weeks": db.closed_weeks(),
    }


@app.get("/api/review-queue/discarded")
def discarded(limit: int = 200, everything: bool = False):
    """Rows the system dropped by itself as already-counted repeats — kept visible, and undoable.
    Shows what has arrived since the log was last cleared; `everything` brings back the rest."""
    return db.discarded_duplicates(limit, everything=everything)


@app.post("/api/review-queue/discarded/clear")
def clear_discarded():
    """Hide what is in the log today and count again from here. Nothing is deleted."""
    _note("queue.clear_discarded")
    return {"hidden": db.clear_discarded_log()}


@app.post("/api/trips/{trip_id}/restore")
def restore_trip(trip_id: int):
    _note("trip.restore", f"trip:{trip_id}")
    _dup_cache.clear()                    # the row stops being a repeat: every week's view is stale
    if not db.restore_discarded(trip_id):
        raise HTTPException(404, "ไม่พบแถวที่ถูกทิ้ง (หรือถูกกู้คืนไปแล้ว)")
    # ท้ายรอบ ingest ย้ายรูปของแถวที่ถูกพักไปไว้ที่ <สัปดาห์>/_ซ้ำ/ ตั้งแต่ 2026-09-13 กู้คืนแถว
    # อย่างเดียวจึงไม่พอแล้ว: ถ้ารูปไม่กลับเข้าโฟลเดอร์ไรเดอร์ แถวจะกลับเข้าคิวโดยไม่มีรูปให้ส่ง
    # ลูกค้า และตัวจัดโควตาก็ยังไม่นับที่นั่งนี้ ย้ายไม่สำเร็จไม่ล้มการกู้คืน — แถวกลับมาแล้ว
    import free_dup_seats
    return {"ok": True, "picture_returned": free_dup_seats.return_picture(trip_id)}


@app.get("/api/diag/batches")
def diag_batches(limit: int = 20):
    """Batch queue seen from outside the login — the office network blocks the database port,
    and 'is the reading done yet' is exactly the question that comes up on those days."""
    rows = _refresh_batch_states(db.recent_batches(limit))
    waiting = [r for r in rows if not r.get("finished_at")]
    return {"batches": rows, "open": len(waiting),
            "waiting_images": sum(r.get("n_trips") or 0 for r in waiting),
            "ready_images": sum(r.get("n_trips") or 0 for r in waiting
                                if str(r.get("state") or "").endswith("SUCCEEDED"))}


@app.get("/api/diag/models")
def diag_models(recent: int = 500):
    """Which model actually read the trips, and what it cost — the check after a model switch."""
    from sqlalchemy import func, select
    t = db.trips.c

    def rows(where=None):
        q = select(t.model, func.count(), func.sum(t.tok_in), func.sum(t.tok_out),
                   func.sum(t.tok_think), func.max(t.id)).group_by(t.model)
        if where is not None:
            q = q.where(where)
        with db.engine.begin() as c:
            out = []
            for m, n, ti, to, tk, last in c.execute(q).all():
                pin, pout = config.GEMINI_PRICE.get(m or "", (0.30, 2.50))
                cost = ((ti or 0) * pin + ((to or 0) + (tk or 0)) * pout) / 1e6 * config.USD_THB
                out.append({"model": m, "trips": n, "tok_in": ti or 0, "tok_out": to or 0,
                            "tok_think": tk or 0, "baht": round(cost, 2),
                            "baht_per_trip": round(cost / n, 4) if n else 0, "last_trip_id": last})
            return sorted(out, key=lambda r: r["last_trip_id"] or 0, reverse=True)

    with db.engine.begin() as c:
        newest = c.execute(select(func.max(t.id))).scalar() or 0
    return {"configured": config.GEMINI_MODEL, "all_time": rows(),
            "recent": {"since_trip_id": max(0, newest - recent), "by_model": rows(t.id > newest - recent)}}


@app.get("/api/diag/waiting")
def diag_waiting(job_id: int = None, limit: int = 500):
    rows = db.review_queue()
    if job_id is not None:
        rows = [r for r in rows if r["job_id"] == job_id]
    return {"total": len(rows), "rows": rows[:max(1, min(limit, 1000))]}


@app.get("/api/diag/job/{job_id}")
def diag_job(job_id: int):
    j = db.get_job(job_id)
    if not j:
        raise HTTPException(404, "ไม่พบ job")
    return j


@app.get("/api/diag/trip/{trip_id}/image")
def diag_trip_image(trip_id: int, part: int = 1):
    img = db.get_trip_image(trip_id, part)
    if not img:
        raise HTTPException(404, "ไม่มีรูป (ถูกลบหลังอนุมัติ)")
    return Response(content=img[0], media_type=img[1])


@app.get("/api/diag/pool")
def diag_pool(limit: int = 5, report: bool = False):
    """Phase 2 pool runs (pool.py): what the pairing found in the album pool, newest first."""
    rows = db.recent_pool_runs(limit, with_report=report)
    if report:
        for r in rows:
            try:
                r["report"] = json.loads(r["report"] or "{}")
            except ValueError:
                pass
    return {"runs": rows}


@app.get("/api/diag/audit")
def diag_audit():
    """System-wide double-count audit: same file ingested twice inside a job, a rider holding
    more than one job in a week, and the same booking code approved more than once."""
    from sqlalchemy import func, select
    out = {}
    with db.engine.begin() as c:
        t, j = db.trips.c, db.jobs.c
        dup_files = c.execute(
            select(t.job_id, j.driver_name, t.file_name, func.count().label("n"))
            .select_from(db.trips.join(db.jobs, j.id == t.job_id))
            .group_by(t.job_id, j.driver_name, t.file_name)
            .having(func.count() > 1)).mappings().all()
        agg = {}
        for r in dup_files:
            k = (r["job_id"], r["driver_name"])
            agg[k] = agg.get(k, 0) + 1
        out["jobs_with_repeated_files"] = [
            {"job_id": k[0], "driver_name": k[1], "files": v} for k, v in sorted(agg.items())]

        rows = c.execute(select(j.driver_name, j.date_from, func.count().label("n"),
                                func.min(j.id), func.max(j.id))
                         .group_by(j.driver_name, j.date_from)
                         .having(func.count() > 1)).all()
        out["riders_with_multiple_jobs"] = [
            {"driver_name": r[0], "week_from": r[1], "jobs": r[2]} for r in rows]

        # A repeat only means money counted twice when it is the SAME rider in the SAME week.
        # The team allows a rider to reuse a slip in another week, so counting those here made
        # the audit cry double-count over something Ops had explicitly signed off.
        same_week = c.execute(select(t.booking_code, j.driver_name, j.date_from,
                                     func.count().label("n"))
                              .select_from(db.trips.join(db.jobs, j.id == t.job_id))
                              .where(t.committed == 1, t.booking_code.isnot(None))
                              .group_by(t.booking_code, j.driver_name, j.date_from)
                              .having(func.count() > 1)).mappings().all()
        out["approved_code_repeats_same_rider_same_week"] = len(same_week)
        out["extra_approved_rows"] = sum(r["n"] - 1 for r in same_week)
        money = 0.0
        for r in same_week:
            vals = c.execute(select(t.id, t.net_earnings)
                             .select_from(db.trips.join(db.jobs, j.id == t.job_id))
                             .where(t.committed == 1, t.booking_code == r["booking_code"],
                                    j.driver_name == r["driver_name"],
                                    j.date_from == r["date_from"])
                             .order_by(t.id)).all()
            money += sum((v[1] or 0) for v in vals[1:])  # everything past the first is extra
        out["extra_approved_baht"] = round(money, 2)
        out["same_week_repeat_sample"] = [
            {"code": r["booking_code"], "driver_name": r["driver_name"],
             "week_from": r["date_from"], "times": r["n"]} for r in same_week[:15]]

        # same rider, ANOTHER week — allowed by the team's slip-reuse rule, reported only
        cross_week_same_rider = c.execute(
            select(t.booking_code, j.driver_name,
                   func.count(func.distinct(j.date_from)).label("weeks"))
            .select_from(db.trips.join(db.jobs, j.id == t.job_id))
            .where(t.committed == 1, t.booking_code.isnot(None))
            .group_by(t.booking_code, j.driver_name)
            .having(func.count(func.distinct(j.date_from)) > 1)).mappings().all()
        out["same_rider_across_weeks_allowed"] = len(cross_week_same_rider)

        # slips reused ACROSS riders or ACROSS weeks — the team allows these (different
        # riders may legitimately hold the same code), so they are reported, never blocked
        cross = c.execute(select(t.booking_code,
                                 func.count(func.distinct(j.driver_name)).label("riders"),
                                 func.count(func.distinct(j.date_from)).label("weeks"),
                                 func.count().label("rows"))
                          .select_from(db.trips.join(db.jobs, j.id == t.job_id))
                          .where(t.committed == 1, t.booking_code.isnot(None))
                          .group_by(t.booking_code)
                          .having(func.count() > 1)).mappings().all()
        multi_rider = [r for r in cross if r["riders"] > 1]
        multi_week = [r for r in cross if r["weeks"] > 1]
        out["code_used_by_multiple_riders"] = len(multi_rider)
        out["code_used_in_multiple_weeks"] = len(multi_week)
        sample = []
        for r in (multi_week or multi_rider)[:12]:
            who = c.execute(select(j.driver_name, j.date_from, t.file_name, t.net_earnings)
                            .select_from(db.trips.join(db.jobs, j.id == t.job_id))
                            .where(t.committed == 1, t.booking_code == r["booking_code"])
                            .order_by(t.id)).mappings().all()
            sample.append({"code": r["booking_code"], "rows": r["rows"],
                           "where": [{"driver_name": w["driver_name"], "week_from": w["date_from"],
                                      "file_name": w["file_name"], "net": w["net_earnings"]}
                                     for w in who]})
        out["cross_use_sample"] = sample
    return out


# ---------- frontend ----------

if config.FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        """Serve a built file, or the SPA's index for any route the app handles itself.

        The path must resolve INSIDE the built folder. This route sits outside the /api/
        prefix the auth gate checks, so it answers without a cookie — and '..' written as
        '%2e%2e' or '..%2f' survives the client's own normalising, arrives here decoded, and
        walked straight out of the folder: '/%2e%2e/%2e%2e/service_account.json' handed over
        the Drive key, and on the server '/%2e%2e/%2e%2e/%2e%2e/%2e%2e/proc/self/environ' the
        database URL and every API key in one request. Verified reproducible before the fix.
        """
        root = config.FRONTEND_DIST.resolve()
        try:
            f = (root / path).resolve()
        except (OSError, ValueError):          # a name the filesystem will not even parse
            f = None
        # index.html names this build's hashed bundle, so a browser that keeps an old copy keeps
        # the old app — the งานซ้ำ tab was live for an hour before Fiat's desktop showed it
        # (2026-09-29). The bundles themselves are hashed and may be cached forever.
        fresh = {"Cache-Control": "no-cache"}
        if path and f is not None and f.is_file() and root in f.parents:
            return FileResponse(f, headers=fresh if f.name == "index.html" else None)
        return FileResponse(root / "index.html", headers=fresh)
