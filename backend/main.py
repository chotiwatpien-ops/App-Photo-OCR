# -*- coding: utf-8 -*-
"""Photo OCR — FastAPI backend.

Local:  uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8600
Cloud:  see render.yaml (DATABASE_URL, GEMINI_API_KEY, APP_PASSWORD, SECRET_KEY)
"""
import logging
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


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    p = request.url.path
    if p.startswith("/api/") and p not in PUBLIC_API and not _logged_in(request):
        return JSONResponse({"detail": "login_required"}, status_code=401)
    return await call_next(request)


@app.get("/api/me")
def me(request: Request):
    return {"auth_required": bool(config.APP_PASSWORD), "logged_in": _logged_in(request)}


@app.post("/api/login")
async def login(body: dict, response: Response):
    if not config.APP_PASSWORD:
        return {"ok": True}
    if body.get("password") != config.APP_PASSWORD:
        raise HTTPException(401, "รหัสผ่านไม่ถูกต้อง")
    response.set_cookie(COOKIE, _signer.sign("ok").decode(), max_age=SESSION_MAX_AGE,
                        httponly=True, samesite="lax", secure=config.IS_CLOUD)
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


# ---------- background extraction ----------

def _extract_worker(trip_id: int, job_id: int):
    pipeline.process_trip(trip_id, job_id)


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
            "model": config.GEMINI_MODEL, "auth_required": bool(config.APP_PASSWORD)}


@app.post("/api/jobs")
async def create_job(
    driver_name: str = Form(...),
    date_from: str = Form(...),
    date_to: str = Form(...),
    files: list[UploadFile] = File(...),
):
    if not files:
        raise HTTPException(400, "ไม่มีไฟล์รูป")
    job_id = db.create_job(driver_name.strip(), excel_writer.SHEET, date_from, date_to)
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


@app.patch("/api/trips/{trip_id}")
async def patch_trip(trip_id: int, fields: dict):
    t = db.get_trip(trip_id)
    if not t:
        raise HTTPException(404, "ไม่พบรายการ")
    if t["committed"]:
        raise HTTPException(409, "รายการนี้อนุมัติแล้ว แก้ไขไม่ได้")
    db.update_trip(trip_id, {k: v for k, v in fields.items() if k in db.TRIP_EDITABLE})
    return db.get_trip(trip_id)


@app.delete("/api/trips/{trip_id}")
def remove_trip(trip_id: int):
    t = db.get_trip(trip_id)
    if not t:
        raise HTTPException(404, "ไม่พบรายการ")
    if t["committed"]:
        raise HTTPException(409, "รายการนี้อนุมัติแล้ว ลบไม่ได้")
    db.delete_trip(trip_id)
    db.refresh_job_status(t["job_id"])
    return {"deleted": trip_id}


@app.get("/api/trips/{trip_id}/image")
def trip_image(trip_id: int):
    img = db.get_trip_image(trip_id)
    if not img:
        raise HTTPException(404, "ไม่มีรูป (รูปถูกลบหลังอนุมัติ)")
    return Response(content=img[0], media_type=img[1],
                    headers={"Cache-Control": "private, max-age=3600"})


@app.post("/api/jobs/{job_id}/commit")
def commit(job_id: int, force: bool = False):
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
    if not force:
        dup_in_job = [t["file_name"] for t in done if t["duplicate_of"]]
        if dup_in_job:
            raise HTTPException(409, f"มีรูปซ้ำกันเองใน job นี้ ({', '.join(dup_in_job[:5])}) — "
                                     f"ลบรูปที่ซ้ำออกก่อน หรือกดยืนยันบันทึกซ้ำ")
        committed_dups = [d for d in db.find_committed_duplicates([t["booking_code"] for t in done])
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
        try:
            excel_writer.append_trips(j["driver_name"], done)
            written_file = config.EXCEL_PATH.name
        except excel_writer.ExcelLockedError:
            raise HTTPException(423, f"ไฟล์ {config.EXCEL_PATH.name} ถูกเปิดอยู่ — กรุณาปิดใน Excel ก่อนแล้วลองใหม่")
    db.mark_committed(job_id)
    return {"written": len(done), "file": written_file}


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


# ---------- frontend ----------

if config.FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = config.FRONTEND_DIST / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(config.FRONTEND_DIST / "index.html")
