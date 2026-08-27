# -*- coding: utf-8 -*-
"""Photo OCR — FastAPI backend.

Local:  uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8600
Cloud:  see render.yaml (DATABASE_URL, GEMINI_API_KEY, APP_PASSWORD, SECRET_KEY)
"""
import json
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


def _diag_ok(request: Request) -> bool:
    """Read-only diagnostic access via header key — valid ONLY for /api/diag/* paths."""
    import hmac
    key = config.DIAG_KEY or ""
    given = request.headers.get("x-diag-key") or ""
    return bool(key) and hmac.compare_digest(given, key)


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    p = request.url.path
    if p.startswith("/api/diag/"):
        if _diag_ok(request) or _logged_in(request):
            return await call_next(request)
        return JSONResponse({"detail": "diag_key_required"}, status_code=401)
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
def trip_image(trip_id: int, part: int = 1):
    img = db.get_trip_image(trip_id, part)
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
    return {"written": len(done), "file": written_file}


@app.post("/api/jobs/{job_id}/spread-dates")
def spread_dates(job_id: int, all_rows: bool = False):
    """Spread the job's unapproved trips evenly over its date range (Mon..Sun) in file order."""
    j = db.get_job(job_id)
    if not j:
        raise HTTPException(404, "ไม่พบ job")
    n = pipeline.spread_dates(job_id, j["date_from"], j["date_to"], only_missing=not all_rows)
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


@app.get("/api/weeks")
def weeks():
    return {"weeks": db.weeks_overview(), "last_run": db.latest_ingest_run(),
            "runs": db.list_ingest_runs(10), "issues": db.list_ingest_issues(50),
            "can_trigger": bool(config.GITHUB_TOKEN and config.GITHUB_REPO),
            "exports_folder": config.DRIVE_EXPORTS_FOLDER_ID, "inbox_folder": config.DRIVE_INBOX_FOLDER_ID}


@app.get("/api/completeness")
def completeness():
    """Per-week rider check: who is short of the expected trips, who sent nothing at all.
    Complete riders are simply not listed (the flag disappears once the data is in)."""
    exp = config.EXPECTED_TRIPS_PER_WEEK
    weeks_ = db.weeks_overview()
    first_seen = {}  # rider -> earliest week date_from they appeared
    for W in weeks_:
        for g in W["groups"]:
            for j in g["jobs"]:
                d = first_seen.get(j["driver_name"])
                if d is None or W["date_from"] < d:
                    first_seen[j["driver_name"]] = W["date_from"]
    out = []
    for W in weeks_:
        incomplete, present = [], set()
        for g in W["groups"]:
            for j in g["jobs"]:
                present.add(j["driver_name"])
                settled = (j["waiting"] or 0) == 0 and (j["pending"] or 0) == 0 and (j["errors"] or 0) == 0
                if (j["approved"] or 0) >= exp and settled:
                    continue  # ครบ — no flag
                incomplete.append({
                    "driver_name": j["driver_name"], "category": g["category"], "job_id": j["id"],
                    "images": j["images"] or 0, "done": j["done"] or 0, "approved": j["approved"] or 0,
                    "waiting": j["waiting"] or 0, "pending": j["pending"] or 0, "errors": j["errors"] or 0,
                    "missing": max(0, exp - (j["done"] or 0)),
                })
        absent = sorted(r for r, d in first_seen.items()
                        if r not in present and d < W["date_from"])
        out.append({"week": W["week"], "date_from": W["date_from"], "date_to": W["date_to"],
                    "riders": W["riders"], "incomplete": incomplete, "absent": absent})
    return {"weeks": out, "expected": exp}


@app.post("/api/ingest/trigger")
def trigger_ingest():
    """Kick the GitHub Actions ingest workflow (workflow_dispatch)."""
    if not (config.GITHUB_TOKEN and config.GITHUB_REPO):
        raise HTTPException(501, "ยังไม่ได้ตั้งค่า GITHUB_TOKEN / GITHUB_REPO — ตั้งแล้วปุ่มนี้จะสั่งรันได้")
    import urllib.request
    url = f"https://api.github.com/repos/{config.GITHUB_REPO}/actions/workflows/{config.GITHUB_WORKFLOW}/dispatches"
    body = json.dumps({"ref": "main", "inputs": {}}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {config.GITHUB_TOKEN}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            status = r.status
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"สั่ง GitHub ไม่สำเร็จ: {str(e)[:200]}")
    return {"ok": status in (200, 204), "url": f"https://github.com/{config.GITHUB_REPO}/actions"}


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
    done, failed = 0, []
    for r in ok:
        res = db.approve_trip(r["id"])
        if "error" in res:
            failed.append({"file_name": r["file_name"], "error": res["error"]})
        else:
            done += 1
    return {"approved": done, "skipped": len(rows) - len(ok), "failed": failed}


@app.post("/api/trips/{trip_id}/approve")
def approve_trip(trip_id: int):
    r = db.approve_trip(trip_id)
    if "error" in r:
        raise HTTPException(400, r["error"])
    return r


# ---------- read-only diagnostics (header X-Diag-Key; see auth_gate) ----------

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


@app.get("/api/review-queue/discarded")
def discarded(limit: int = 200):
    """Rows the system dropped by itself as already-counted repeats — kept visible, and undoable."""
    return db.discarded_duplicates(limit)


@app.post("/api/trips/{trip_id}/restore")
def restore_trip(trip_id: int):
    if not db.restore_discarded(trip_id):
        raise HTTPException(404, "ไม่พบแถวที่ถูกทิ้ง (หรือถูกกู้คืนไปแล้ว)")
    return {"ok": True}


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

        codes = c.execute(select(t.booking_code, j.driver_name, func.count().label("n"))
                          .select_from(db.trips.join(db.jobs, j.id == t.job_id))
                          .where(t.committed == 1, t.booking_code.isnot(None))
                          .group_by(t.booking_code, j.driver_name)
                          .having(func.count() > 1)).mappings().all()
        out["approved_code_repeats_same_rider"] = len(codes)
        extra_rows = sum(r["n"] - 1 for r in codes)
        out["extra_approved_rows"] = extra_rows
        pairs = [(r["booking_code"], r["driver_name"]) for r in codes]
        money = 0.0
        for code, drv in pairs:
            vals = c.execute(select(t.id, t.net_earnings)
                             .select_from(db.trips.join(db.jobs, j.id == t.job_id))
                             .where(t.committed == 1, t.booking_code == code,
                                    j.driver_name == drv)
                             .order_by(t.id)).all()
            money += sum((v[1] or 0) for v in vals[1:])  # everything past the first is extra
        out["extra_approved_baht"] = round(money, 2)

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
        out["approved_code_repeat_sample"] = [
            {"code": r["booking_code"], "driver_name": r["driver_name"], "times": r["n"]}
            for r in codes[:15]]
    return out


# ---------- frontend ----------

if config.FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = config.FRONTEND_DIST / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(config.FRONTEND_DIST / "index.html")
