# -*- coding: utf-8 -*-
"""Storage layer — SQLAlchemy Core so the same code runs on SQLite (local) and Postgres (Neon).

Images are kept as blobs only while a job is under review and cleared on commit,
so the database stays small enough for a free Postgres tier.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import (Column, Float, Integer, LargeBinary, MetaData, String, Table, Text,
                        case, create_engine, delete, func, insert, select, text, update)

from config import DATABASE_URL

_is_sqlite = DATABASE_URL.startswith("sqlite")
engine = create_engine(
    DATABASE_URL, future=True, pool_pre_ping=True,
    connect_args={"check_same_thread": False, "timeout": 10} if _is_sqlite else {},
)
meta = MetaData()

jobs = Table(
    "jobs", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("driver_name", Text, nullable=False),
    Column("sheet", Text, nullable=False, default="Trips"),
    Column("date_from", String(10), nullable=False),
    Column("date_to", String(10), nullable=False),
    Column("status", String(16), nullable=False, default="running"),  # running | review | committed
    Column("created_at", String(19), nullable=False),
    Column("category", String(32)),      # team's vehicle group: 4 W Standard | 4 W Saver | 2 W Standard | 2 W Saver
    Column("folder_name", Text),         # original rider folder path on Drive (mirrored into Exports)
    Column("admin", String(64)),         # which admin's folder the photos came from
)

trips = Table(
    "trips", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("job_id", Integer, nullable=False, index=True),
    Column("file_name", Text, nullable=False),
    Column("image_path", Text),            # legacy local path (pre-blob); unused for new rows
    Column("image_blob", LargeBinary),     # cleared on commit
    Column("image_mime", String(32)),
    Column("status", String(16), nullable=False, default="pending"),  # pending | done | error
    Column("error", Text),
    Column("trip_date", String(10)),
    Column("trip_time", String(5)),
    Column("service_type", Text),
    Column("payment_method", Text),
    Column("pickup_code", Text),
    Column("dropoff_code", Text),
    Column("pickup_text", Text),
    Column("dropoff_text", Text),
    Column("distance_km", Float),
    Column("duration_mins", Float),
    Column("net_earnings", Float),
    Column("base_fare", Float),
    Column("intl_fee", Float, default=0),
    Column("bonus", Float, default=0),
    Column("turbo", Float, default=0),
    Column("tolls", Float, default=0),
    Column("tip", Float, default=0),          # ค่าทิป — folded into Bonus (M) for the sheet's J=K+M+N
    Column("passenger_total", Float),      # รวมค่าโดยสารของผู้โดยสาร (total incl. fees/discounts)
    Column("passenger_paid", Float),       # ยอดที่ผู้โดยสารชำระ (what the passenger paid) — the team's "Passenger Fare"
    Column("grab_commission", Float),
    Column("pickup_district", Text),
    Column("dropoff_district", Text),
    Column("surge", Integer, default=0),
    Column("queue_type", Text),
    Column("num_stops", Integer),
    Column("app_fee", Float),
    Column("other_adj", Float),
    Column("fare_refund", Float),
    Column("model", Text),
    Column("tok_in", Integer),
    Column("tok_out", Integer),
    Column("tok_think", Integer),
    Column("note", Text),
    Column("booking_code", Text, index=True),
    Column("check_status", String(8)),     # pass | fail | no_data
    Column("duplicate_of", Integer),
    Column("committed", Integer, nullable=False, default=0),
    Column("auto_approved", Integer, nullable=False, default=0),  # 1 = committed by ingest, not a person
    Column("source_url", Text),                                   # Drive link to the original image
    Column("customer_image", Text),       # the delivered image's file name (e.g. 'นภสิทธิ์7.jpg') — traceback from Sheet1
    Column("kind", String(8)),            # full | top | bottom — which part of the trip screen the image shows
    Column("merged_into", Integer),       # bottom half folded into this trip id (status becomes 'merged')
)

# Drive files already pulled in — makes every ingest run idempotent
ingested_files = Table(
    "ingested_files", meta,
    Column("drive_id", String(128), primary_key=True),
    Column("name", Text),
    Column("job_id", Integer),
    Column("trip_id", Integer),
    Column("ingested_at", String(19), nullable=False),
)

# where ingest put things on Drive, so the UI can link straight to them
drive_files = Table(
    "drive_files", meta,
    Column("key", String(96), primary_key=True),   # f"{week}|{kind}|{ref}"
    Column("week", String(12), nullable=False),
    Column("kind", String(16), nullable=False),    # xlsx | week_folder | rider_folder
    Column("ref", String(16), nullable=False, default=""),  # job id for rider_folder, else ""
    Column("drive_id", Text, nullable=False),
    Column("name", Text),
    Column("updated_at", String(19), nullable=False),
)

ingest_runs = Table(
    "ingest_runs", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("started_at", String(19), nullable=False),
    Column("finished_at", String(19)),
    Column("files_new", Integer, default=0),
    Column("files_skipped", Integer, default=0),
    Column("jobs_created", Integer, default=0),
    Column("auto_approved", Integer, default=0),
    Column("flagged", Integer, default=0),
    Column("errors", Integer, default=0),
    Column("notes", Text),
    Column("files_total", Integer),     # target for this round — lets the UI show live progress
)

# problems seen by ingest runs — one row per distinct problem, auto-resolved (but kept as
# history) once a later run no longer sees it
ingest_issues = Table(
    "ingest_issues", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("key", Text, nullable=False),     # stable identity, e.g. "folder:<path>" / "download:<file id>"
    Column("kind", String(24)),              # folder | download | process | images | xlsx
    Column("message", Text),
    Column("first_run", Integer),
    Column("last_run", Integer),
    Column("times_seen", Integer, default=1),
    Column("resolved_run", Integer),
    Column("resolved_at", String(19)),
)

TRIP_EDITABLE = [
    "trip_date", "trip_time", "service_type", "payment_method",
    "pickup_code", "dropoff_code", "pickup_text", "dropoff_text",
    "distance_km", "duration_mins", "net_earnings", "base_fare",
    "intl_fee", "bonus", "turbo", "tolls", "tip", "passenger_total", "passenger_paid",
    "pickup_district", "dropoff_district", "surge", "queue_type",
    "num_stops", "app_fee", "other_adj", "fare_refund", "note",
]
_SYSTEM_FIELDS = ["status", "error", "booking_code", "check_status", "duplicate_of",
                  "grab_commission", "model", "tok_in", "tok_out", "tok_think", "kind", "merged_into",
                  "customer_image"]
# columns returned to the API (everything except the blob)
TRIP_COLS = [c for c in trips.c if c.name != "image_blob"]


_TZ_BKK = timezone(timedelta(hours=7))


def _now() -> str:
    """Thai wall-clock, always — runs happen on UTC runners AND local machines, and mixed
    zones scrambled the run-history ordering."""
    return datetime.now(_TZ_BKK).replace(tzinfo=None).isoformat(timespec="seconds")


def init_db():
    meta.create_all(engine)
    if _is_sqlite:
        # older local DBs: add columns that appeared after they were created (safe no-op otherwise)
        with engine.begin() as c:
            c.execute(text("PRAGMA journal_mode=WAL"))
            for tbl in (trips, jobs, ingest_runs):
                existing = {r[1] for r in c.execute(text(f"PRAGMA table_info({tbl.name})"))}
                for col in tbl.c:
                    if col.name not in existing:
                        typ = {"INTEGER": "INTEGER", "REAL": "REAL", "BLOB": "BLOB", "FLOAT": "REAL"}.get(
                            str(col.type).split("(")[0].upper(), "TEXT")
                        c.execute(text(f"ALTER TABLE {tbl.name} ADD COLUMN {col.name} {typ}"))
    else:
        with engine.begin() as c:
            c.execute(text("ALTER TABLE ingest_runs ADD COLUMN IF NOT EXISTS files_total INTEGER"))


# ---------- jobs ----------

def create_job(driver_name, sheet, date_from, date_to, category=None, folder_name=None, admin=None) -> int:
    with engine.begin() as c:
        r = c.execute(insert(jobs).values(
            driver_name=driver_name, sheet=sheet, date_from=date_from, date_to=date_to,
            status="running", created_at=_now(), category=category, folder_name=folder_name, admin=admin))
        return r.inserted_primary_key[0]


def get_job(job_id):
    with engine.begin() as c:
        j = c.execute(select(jobs).where(jobs.c.id == job_id)).mappings().first()
        if not j:
            return None
        rows = c.execute(select(*TRIP_COLS).where(trips.c.job_id == job_id)
                         .order_by(trips.c.id)).mappings().all()
        return {**dict(j), "trips": [dict(r) for r in rows]}


def set_job_status(job_id, status):
    with engine.begin() as c:
        c.execute(update(jobs).where(jobs.c.id == job_id).values(status=status))


def refresh_job_status(job_id):
    """running → review once no trips are pending."""
    with engine.begin() as c:
        pending = c.execute(select(func.count()).select_from(trips)
                            .where(trips.c.job_id == job_id, trips.c.status == "pending")).scalar()
        if pending == 0:
            c.execute(update(jobs).where(jobs.c.id == job_id, jobs.c.status == "running")
                      .values(status="review"))


def list_jobs(limit=30):
    done = func.sum(case((trips.c.status == "done", 1), else_=0)).label("done_count")
    err = func.sum(case((trips.c.status == "error", 1), else_=0)).label("error_count")
    cnt = func.sum(case((trips.c.status != "merged", 1), else_=0)).label("trip_count")
    q = (select(jobs, cnt, done, err)
         .select_from(jobs.outerjoin(trips, trips.c.job_id == jobs.c.id))
         .group_by(*jobs.c).order_by(jobs.c.id.desc()).limit(limit))
    with engine.begin() as c:
        return [dict(r) for r in c.execute(q).mappings().all()]


def mark_committed(job_id):
    """Approve all done trips and drop their image blobs (only needed during review)."""
    with engine.begin() as c:
        c.execute(update(trips).where(trips.c.job_id == job_id, trips.c.status == "done")
                  .values(committed=1, image_blob=None))
        c.execute(update(trips).where(trips.c.job_id == job_id, trips.c.status == "merged")
                  .values(image_blob=None))
        c.execute(update(jobs).where(jobs.c.id == job_id).values(status="committed"))


# ---------- trips ----------

def create_trip(job_id, file_name, image_bytes: bytes, mime: str, source_url: str = None) -> int:
    with engine.begin() as c:
        r = c.execute(insert(trips).values(
            job_id=job_id, file_name=file_name, image_blob=image_bytes, image_mime=mime,
            status="pending", committed=0, auto_approved=0, source_url=source_url))
        return r.inserted_primary_key[0]


# ---------- ingest support ----------

def already_ingested(drive_ids):
    ids = list(drive_ids)
    if not ids:
        return set()
    with engine.begin() as c:
        return {r[0] for r in c.execute(select(ingested_files.c.drive_id)
                                        .where(ingested_files.c.drive_id.in_(ids))).all()}


def record_ingested(drive_id, name, job_id, trip_id):
    with engine.begin() as c:
        c.execute(insert(ingested_files).values(
            drive_id=drive_id, name=name, job_id=job_id, trip_id=trip_id, ingested_at=_now()))


def delete_jobs(job_ids) -> list:
    """User-ordered removal of whole jobs (e.g. duplicate manual uploads). Returns a log."""
    out = []
    with engine.begin() as c:
        for jid in job_ids:
            j = c.execute(select(jobs.c.id, jobs.c.driver_name, jobs.c.date_from)
                          .where(jobs.c.id == jid)).mappings().first()
            if not j:
                out.append({"job_id": jid, "found": False})
                continue
            n = c.execute(select(func.count()).select_from(trips)
                          .where(trips.c.job_id == jid)).scalar()
            c.execute(delete(ingested_files).where(ingested_files.c.job_id == jid))
            c.execute(delete(trips).where(trips.c.job_id == jid))
            c.execute(delete(jobs).where(jobs.c.id == jid))
            out.append({"job_id": jid, "found": True, "driver_name": j["driver_name"],
                        "date_from": j["date_from"], "trips": n})
    return out


def dedupe_approved_trips() -> list:
    """Same booking code approved more than once for the SAME rider: keep the earliest row,
    delete the extras (and any half merged into them). Returns a log of what went."""
    removed = []
    with engine.begin() as c:
        dups = c.execute(
            select(trips.c.booking_code, jobs.c.driver_name)
            .select_from(trips.join(jobs, jobs.c.id == trips.c.job_id))
            .where(trips.c.committed == 1, trips.c.booking_code.isnot(None))
            .group_by(trips.c.booking_code, jobs.c.driver_name)
            .having(func.count() > 1)).all()
        for code, driver in dups:
            rows = c.execute(
                select(trips.c.id, trips.c.job_id, trips.c.file_name, trips.c.net_earnings)
                .select_from(trips.join(jobs, jobs.c.id == trips.c.job_id))
                .where(trips.c.committed == 1, trips.c.booking_code == code,
                       jobs.c.driver_name == driver)
                .order_by(trips.c.id)).mappings().all()
            for r in rows[1:]:  # keep the first, drop the rest
                kids = c.execute(delete(trips).where(trips.c.merged_into == r["id"])).rowcount
                c.execute(delete(ingested_files).where(ingested_files.c.trip_id == r["id"]))
                c.execute(delete(trips).where(trips.c.id == r["id"]))
                removed.append({"driver_name": driver, "code": code, "trip_id": r["id"],
                                "job_id": r["job_id"], "file_name": r["file_name"],
                                "net": r["net_earnings"] or 0, "merged_children": kids})
    return removed


def mark_orphan_bottom_duplicates(job_id) -> int:
    """A code-less lower half that never paired is either (a) the other half of a trip already
    counted — its amount matches an approved row in the same job, so flag it as a duplicate for
    a person to delete — or (b) a genuine trip whose upper half is missing, which may pass.
    Team rule 2026-08-25: separate the two automatically instead of holding both."""
    with engine.begin() as c:
        orphans = c.execute(select(trips.c.id, trips.c.file_name, trips.c.net_earnings,
                                   trips.c.base_fare, trips.c.note)
                            .where(trips.c.job_id == job_id, trips.c.status == "done",
                                   trips.c.committed == 0, trips.c.kind == "bottom",
                                   trips.c.merged_into.is_(None),
                                   trips.c.booking_code.is_(None),
                                   trips.c.duplicate_of.is_(None))).mappings().all()
        if not orphans:
            return 0
        approved = c.execute(select(trips.c.id, trips.c.file_name, trips.c.net_earnings,
                                    trips.c.base_fare)
                             .where(trips.c.job_id == job_id, trips.c.committed == 1)).mappings().all()
        n = 0
        for o in orphans:
            amt = o["net_earnings"] if o["net_earnings"] is not None else o["base_fare"]
            if amt is None:
                continue
            twin = next((a for a in approved
                         if (a["net_earnings"] is not None and abs(a["net_earnings"] - amt) <= 0.01)
                         or (a["base_fare"] is not None and abs(a["base_fare"] - amt) <= 0.01)), None)
            if not twin:
                continue  # no counted twin — a real trip missing its upper half; let it pass
            msg = f"ครึ่งล่างของงานที่อนุมัติแล้ว ({twin['file_name']}) — รูปเกิน ลบได้"
            note = f"{msg} | {o['note']}" if o["note"] else msg
            c.execute(update(trips).where(trips.c.id == o["id"])
                      .values(duplicate_of=twin["id"], note=note))
            n += 1
        return n


def auto_approve_job(job_id) -> dict:
    """Commit rows that passed every check (✓, not a duplicate, booking code unseen);
    leave the rest for a person. Returns {approved, flagged}."""
    mark_orphan_bottom_duplicates(job_id)
    with engine.begin() as c:
        rows = c.execute(select(trips.c.id, trips.c.check_status, trips.c.duplicate_of,
                                trips.c.booking_code, trips.c.trip_date, trips.c.kind)
                         .where(trips.c.job_id == job_id, trips.c.status == "done",
                                trips.c.committed == 0)).mappings().all()
        codes = [r["booking_code"] for r in rows if r["booking_code"]]
        seen = set()
        if codes:
            # team rule 2026-08-25: a code approved under ANOTHER rider does not block this
            # one — only a repeat by the SAME rider counts as a duplicate
            job_driver = c.execute(select(jobs.c.driver_name)
                                   .where(jobs.c.id == job_id)).scalar()
            seen = {r[0] for r in c.execute(
                select(trips.c.booking_code)
                .select_from(trips.join(jobs, jobs.c.id == trips.c.job_id))
                .where(trips.c.committed == 1, trips.c.booking_code.in_(codes),
                       jobs.c.driver_name == job_driver)).all()}
        ok_ids = [r["id"] for r in rows
                  if r["check_status"] == "pass" and not r["duplicate_of"] and r["trip_date"]
                  # team rule 2026-08-25: balanced money is the bar — a missing booking code
                  # (some Grab screens don't show one) or km does NOT hold a row back. Stray
                  # lower halves are handled by mark_orphan_bottom_duplicates() above: the
                  # ones matching a counted trip carry duplicate_of and are excluded here.
                  and (not r["booking_code"] or r["booking_code"] not in seen)]
        if ok_ids:
            c.execute(update(trips).where(trips.c.id.in_(ok_ids))
                      .values(committed=1, auto_approved=1, image_blob=None))
            c.execute(update(trips).where(trips.c.merged_into.in_(ok_ids)).values(image_blob=None))
        remaining = c.execute(select(func.count()).select_from(trips)
                              .where(trips.c.job_id == job_id, trips.c.status == "done",
                                     trips.c.committed == 0)).scalar()
        c.execute(update(jobs).where(jobs.c.id == job_id)
                  .values(status="committed" if remaining == 0 else "review"))
        return {"approved": len(ok_ids), "flagged": len(rows) - len(ok_ids)}


def start_ingest_run() -> int:
    with engine.begin() as c:
        # a run that never finished = the previous job crashed mid-way — close it out so the
        # UI's "กำลังรัน" state (and the trigger button) don't stay stuck forever
        c.execute(update(ingest_runs).where(ingest_runs.c.finished_at.is_(None))
                  .values(finished_at=_now(), errors=ingest_runs.c.errors + 1,
                          notes="รอบนี้ไม่จบตามปกติ (ระบบล่มกลางทาง) — ดู log ใน GitHub Actions"))
        return c.execute(insert(ingest_runs).values(started_at=_now())).inserted_primary_key[0]


def update_ingest_run_progress(run_id, files_new=None, auto_approved=None, flagged=None,
                               files_total=None):
    """Live progress during a round (updated after every rider) — the UI polls this, and a
    cancelled round keeps its real partial numbers instead of zeros."""
    vals = {k: v for k, v in (("files_new", files_new), ("auto_approved", auto_approved),
                              ("flagged", flagged), ("files_total", files_total)) if v is not None}
    if not vals or run_id is None:
        return
    with engine.begin() as c:
        c.execute(update(ingest_runs).where(ingest_runs.c.id == run_id).values(**vals))


def finish_ingest_run(run_id, **stats):
    with engine.begin() as c:
        c.execute(update(ingest_runs).where(ingest_runs.c.id == run_id)
                  .values(finished_at=_now(), **stats))


def delete_model_trips(model_substring: str) -> dict:
    """User-ordered redo: drop every trip read by the given model (plus its ingest records,
    and any job left empty) so the next discovery re-reads those files with the current model."""
    with engine.begin() as c:
        ids = [r[0] for r in c.execute(select(trips.c.id)
                                       .where(trips.c.model.ilike(f"%{model_substring}%")))]
        if not ids:
            return {"trips": 0, "files": 0, "jobs": 0}
        jids = {r[0] for r in c.execute(select(trips.c.job_id)
                                        .where(trips.c.id.in_(ids))).all()}
        nf = c.execute(delete(ingested_files).where(ingested_files.c.trip_id.in_(ids))).rowcount
        nt = c.execute(delete(trips).where(trips.c.id.in_(ids))).rowcount
        nj = 0
        for j in jids:
            left = c.execute(select(func.count()).select_from(trips)
                             .where(trips.c.job_id == j)).scalar()
            if left == 0:
                c.execute(delete(jobs).where(jobs.c.id == j))
                nj += 1
        return {"trips": nt, "files": nf or 0, "jobs": nj}


def normalize_booking_codes() -> int:
    """Strip whitespace the model inserted inside stored booking codes (it breaks dedup)."""
    with engine.begin() as c:
        r = c.execute(update(trips).where(trips.c.booking_code.like("% %"))
                      .values(booking_code=func.replace(trips.c.booking_code, " ", "")))
        return r.rowcount or 0


def stuck_pending_trips():
    """(trip_id, job_id) rows left in 'pending' by a cancelled run — their files are already
    recorded as ingested so nothing would ever retry them without this."""
    with engine.begin() as c:
        rows = c.execute(select(trips.c.id, trips.c.job_id)
                         .where(trips.c.status == "pending",
                                trips.c.image_blob.isnot(None))).all()
        return [(r[0], r[1]) for r in rows]


def jobs_missing_dates():
    """Jobs holding done rows with no trip_date = a cancelled round died before its
    spread_dates step; those rows can never auto-approve until the dates are filled."""
    with engine.begin() as c:
        return [r[0] for r in c.execute(
            select(func.distinct(trips.c.job_id))
            .where(trips.c.status == "done", trips.c.committed == 0,
                   trips.c.trip_date.is_(None))).all()]


def open_image_issue_jobs():
    """Job ids whose customer-image upload failed and was never retried successfully."""
    with engine.begin() as c:
        rows = c.execute(select(ingest_issues.c.key)
                         .where(ingest_issues.c.resolved_run.is_(None),
                                ingest_issues.c.kind == "images")).all()
    out = []
    for (k,) in rows:
        try:
            out.append(int(k.split(":", 1)[1]))
        except (IndexError, ValueError):
            pass
    return out


def review_job_ids():
    with engine.begin() as c:
        return [r[0] for r in c.execute(select(jobs.c.id)
                                        .where(jobs.c.status == "review")).all()]


def stale_running_jobs():
    """Jobs still marked 'running' at the START of a round = a previous round was cancelled
    before their pair/approve steps (the concurrency lock guarantees no other round is live)."""
    with engine.begin() as c:
        return [r[0] for r in c.execute(select(jobs.c.id)
                                        .where(jobs.c.status == "running")).all()]


def jobs_dates(job_ids):
    with engine.begin() as c:
        rows = c.execute(select(jobs.c.id, jobs.c.date_from, jobs.c.date_to)
                         .where(jobs.c.id.in_(list(job_ids)))).all()
        return [(r[0], r[1], r[2]) for r in rows]


def find_job(driver_name, date_from, date_to):
    """Existing job for this rider + week (ingest appends to it across runs)."""
    with engine.begin() as c:
        r = c.execute(select(jobs.c.id).where(jobs.c.driver_name == driver_name,
                                              jobs.c.date_from == date_from,
                                              jobs.c.date_to == date_to)
                      .order_by(jobs.c.id.desc()).limit(1)).first()
        return r[0] if r else None


def name_shared_in_group(driver_name, date_from, date_to, category, job_id):
    """True when ANOTHER job in the same week + vehicle group carries the same display name
    (two riders under different admins with identical names → exports need an -Admin suffix)."""
    with engine.begin() as c:
        n = c.execute(select(func.count()).select_from(jobs).where(
            jobs.c.driver_name == driver_name, jobs.c.date_from == date_from,
            jobs.c.date_to == date_to, jobs.c.category == category,
            jobs.c.id != job_id)).scalar()
        return bool(n)


def get_trip(trip_id):
    with engine.begin() as c:
        r = c.execute(select(*TRIP_COLS).where(trips.c.id == trip_id)).mappings().first()
        return dict(r) if r else None


def get_trip_image(trip_id, part=1):
    """(bytes, mime) or None — blobs are cleared after commit. part=2 -> merged bottom half."""
    with engine.begin() as c:
        if part == 2:
            r = c.execute(select(trips.c.image_blob, trips.c.image_mime)
                          .where(trips.c.merged_into == trip_id).order_by(trips.c.id).limit(1)).first()
        else:
            r = c.execute(select(trips.c.image_blob, trips.c.image_mime)
                          .where(trips.c.id == trip_id)).first()
        if not r or r[0] is None:
            return None
        return bytes(r[0]), r[1] or "image/jpeg"


def update_trip(trip_id, fields: dict):
    allowed = set(TRIP_EDITABLE + _SYSTEM_FIELDS)
    vals = {k: v for k, v in fields.items() if k in allowed}
    if not vals:
        return
    with engine.begin() as c:
        c.execute(update(trips).where(trips.c.id == trip_id).values(**vals))


def delete_trip(trip_id):
    with engine.begin() as c:
        c.execute(delete(trips).where(trips.c.id == trip_id))


def find_job_duplicate(job_id, booking_code, exclude_id):
    """Earlier trip in the same job with the same booking code, or None."""
    if not booking_code:
        return None
    with engine.begin() as c:
        r = c.execute(select(trips.c.id, trips.c.file_name)
                      .where(trips.c.job_id == job_id, trips.c.booking_code == booking_code,
                             trips.c.id < exclude_id)
                      .order_by(trips.c.id).limit(1)).mappings().first()
        return dict(r) if r else None


def find_committed_duplicates(codes):
    """Trips already committed (any job) whose booking codes are in `codes`."""
    codes = [x for x in codes if x]
    if not codes:
        return []
    with engine.begin() as c:
        rows = c.execute(select(trips.c.booking_code, trips.c.job_id, trips.c.file_name)
                         .where(trips.c.committed == 1, trips.c.booking_code.in_(codes))).mappings().all()
        return [dict(r) for r in rows]


def query_trips(date_from=None, date_to=None, driver=None, committed_only=True, job_id=None):
    """Rows for export / the data view, joined with the job's driver name."""
    q = (select(*TRIP_COLS, jobs.c.driver_name, jobs.c.category, jobs.c.admin, jobs.c.id.label("job_id_"))
         .select_from(trips.join(jobs, jobs.c.id == trips.c.job_id))
         .where(trips.c.status == "done"))
    if committed_only:
        q = q.where(trips.c.committed == 1)
    if job_id is not None:
        q = q.where(trips.c.job_id == job_id)
    if date_from:
        q = q.where(trips.c.trip_date >= date_from)
    if date_to:
        q = q.where(trips.c.trip_date <= date_to)
    if driver:
        q = q.where(jobs.c.driver_name.ilike(f"%{driver}%"))
    # one continuous log: week block first, then rider, then day
    q = q.order_by(jobs.c.date_from, jobs.c.driver_name, trips.c.trip_date, trips.c.trip_time, trips.c.id)
    with engine.begin() as c:
        return [dict(r) for r in c.execute(q).mappings().all()]


def list_drivers():
    with engine.begin() as c:
        return [r[0] for r in c.execute(select(jobs.c.driver_name).distinct()
                                        .order_by(jobs.c.driver_name)).all()]


# ---------- Phase C: dashboard / data view / review queue ----------

def _trip_join(where_committed=None):
    q = (select(*TRIP_COLS, jobs.c.driver_name)
         .select_from(trips.join(jobs, jobs.c.id == trips.c.job_id))
         .where(trips.c.status == "done"))
    if where_committed is not None:
        q = q.where(trips.c.committed == where_committed)
    return q


def summary(date_from=None, date_to=None):
    """Aggregates for the dashboard — computed in Python; a few tens of thousands of rows is fine."""
    q = (select(trips.c.trip_date, trips.c.committed, trips.c.net_earnings, trips.c.distance_km,
                trips.c.check_status, trips.c.duplicate_of, trips.c.surge, trips.c.payment_method,
                jobs.c.driver_name)
         .select_from(trips.join(jobs, jobs.c.id == trips.c.job_id))
         .where(trips.c.status == "done"))
    if date_from:
        q = q.where(trips.c.trip_date >= date_from)
    if date_to:
        q = q.where(trips.c.trip_date <= date_to)
    with engine.begin() as c:
        rows = c.execute(q).mappings().all()

    weeks, riders = {}, {}
    tot = {"trips": 0, "approved": 0, "waiting": 0, "net": 0.0, "km": 0.0, "surge": 0, "cash": 0}
    for r in rows:
        if r["trip_date"]:
            y, w, _ = datetime.strptime(r["trip_date"], "%Y-%m-%d").isocalendar()
            wk = f"{y}-W{w:02d}"
        else:
            wk = "ไม่ระบุ"
        for bucket, key in ((weeks, wk), (riders, r["driver_name"])):
            b = bucket.setdefault(key, {"trips": 0, "approved": 0, "waiting": 0, "net": 0.0,
                                        "km": 0.0, "surge": 0, "riders": set()})
            b["trips"] += 1
            b["riders"].add(r["driver_name"])
            if r["committed"]:
                b["approved"] += 1
                b["net"] += r["net_earnings"] or 0
                b["km"] += r["distance_km"] or 0
            else:
                b["waiting"] += 1
            b["surge"] += 1 if r["surge"] else 0
        tot["trips"] += 1
        if r["committed"]:
            tot["approved"] += 1
            tot["net"] += r["net_earnings"] or 0
            tot["km"] += r["distance_km"] or 0
        else:
            tot["waiting"] += 1
        tot["surge"] += 1 if r["surge"] else 0
        tot["cash"] += 1 if r["payment_method"] == "CASH" else 0

    def pack(d, key_name):
        out = []
        for k, b in d.items():
            out.append({key_name: k, **{x: b[x] for x in ("trips", "approved", "waiting", "surge")},
                        "net": round(b["net"], 2), "km": round(b["km"], 2), "riders": len(b["riders"])})
        return out

    by_week = sorted(pack(weeks, "week"), key=lambda x: x["week"], reverse=True)
    by_rider = sorted(pack(riders, "driver_name"), key=lambda x: -x["net"])
    tot["net"] = round(tot["net"], 2)
    tot["km"] = round(tot["km"], 2)
    return {"totals": tot, "by_week": by_week, "by_rider": by_rider}


def search_trips(date_from=None, date_to=None, driver=None, status="all", q=None,
                 limit=50, offset=0):
    """Paginated rows for the data view. status: all | approved | waiting."""
    base = _trip_join({"approved": 1, "waiting": 0}.get(status))
    if date_from:
        base = base.where(trips.c.trip_date >= date_from)
    if date_to:
        base = base.where(trips.c.trip_date <= date_to)
    if driver:
        base = base.where(jobs.c.driver_name == driver)
    if q:
        like = f"%{q.strip()}%"
        base = base.where(trips.c.booking_code.ilike(like) | trips.c.file_name.ilike(like)
                          | trips.c.pickup_text.ilike(like) | trips.c.dropoff_text.ilike(like))
    with engine.begin() as c:
        total = c.execute(select(func.count()).select_from(base.subquery())).scalar()
        rows = c.execute(base.order_by(trips.c.trip_date.desc(), trips.c.trip_time.desc(), trips.c.id.desc())
                         .limit(limit).offset(offset)).mappings().all()
        return [dict(r) for r in rows], total


def review_queue():
    """Every done-but-unapproved row across all jobs, oldest job first.
    Adds seen_in_job: the job that already approved the same booking code (why auto-approve held it)."""
    q = _trip_join(0).order_by(trips.c.job_id, trips.c.id)
    with engine.begin() as c:
        rows = [dict(r) for r in c.execute(q).mappings().all()]
        codes = [r["booking_code"] for r in rows if r["booking_code"]]
        seen = {}
        if codes:
            for code, jid in c.execute(select(trips.c.booking_code, trips.c.job_id)
                                       .where(trips.c.committed == 1, trips.c.booking_code.in_(codes))).all():
                seen.setdefault(code, jid)
        for r in rows:
            r["seen_in_job"] = seen.get(r["booking_code"])
        return rows


def approve_trip(trip_id) -> dict:
    """Approve a single row (after a person looked at it) and sync its job's status."""
    with engine.begin() as c:
        t = c.execute(select(trips.c.job_id, trips.c.status, trips.c.trip_date)
                      .where(trips.c.id == trip_id)).mappings().first()
        if not t:
            return {"error": "not found"}
        if t["status"] != "done":
            return {"error": "ยังอ่านไม่เสร็จ"}
        if not t["trip_date"]:
            return {"error": "ยังไม่ได้ระบุวันที่"}
        c.execute(update(trips).where(trips.c.id == trip_id)
                  .values(committed=1, auto_approved=0, image_blob=None))
        c.execute(update(trips).where(trips.c.merged_into == trip_id).values(image_blob=None))
        remaining = c.execute(select(func.count()).select_from(trips)
                              .where(trips.c.job_id == t["job_id"], trips.c.status == "done",
                                     trips.c.committed == 0)).scalar()
        c.execute(update(jobs).where(jobs.c.id == t["job_id"])
                  .values(status="committed" if remaining == 0 else "review"))
        return {"ok": True, "job_id": t["job_id"], "job_done": remaining == 0}


def list_ingest_runs(limit=10):
    with engine.begin() as c:
        return [dict(r) for r in c.execute(select(ingest_runs).order_by(ingest_runs.c.id.desc())
                                           .limit(limit)).mappings().all()]


def sync_ingest_issues(run_id, issues):
    """issues = [(key, kind, message)] seen this run. Open issues seen again get their counter
    bumped; new ones are inserted; open ones NOT seen are auto-resolved (row kept as history).
    'process' issues resolve only when their trip is fixed or deleted, since a failed trip is
    not retried by later runs."""
    seen = {key: (kind, msg) for key, kind, msg in issues}
    with engine.begin() as c:
        open_rows = c.execute(select(ingest_issues)
                              .where(ingest_issues.c.resolved_run.is_(None))).mappings().all()
        open_by_key = {r["key"]: r for r in open_rows}
        for key, (kind, msg) in seen.items():
            row = open_by_key.get(key)
            if row:
                c.execute(update(ingest_issues).where(ingest_issues.c.id == row["id"])
                          .values(last_run=run_id, message=msg,
                                  times_seen=(row["times_seen"] or 1) + 1))
            else:
                c.execute(insert(ingest_issues).values(
                    key=key, kind=kind, message=msg,
                    first_run=run_id, last_run=run_id, times_seen=1))
        for key, row in open_by_key.items():
            if key in seen:
                continue
            if row["kind"] == "process":
                try:
                    tid = int(key.split(":", 1)[1])
                except ValueError:
                    tid = None
                if tid is not None:
                    t = c.execute(select(trips.c.status).where(trips.c.id == tid)).first()
                    if t and t[0] == "error":
                        continue  # still broken — keep open
            c.execute(update(ingest_issues).where(ingest_issues.c.id == row["id"])
                      .values(resolved_run=run_id, resolved_at=_now()))


def list_ingest_issues(limit=100):
    """Open issues first (newest first), then recently resolved history."""
    with engine.begin() as c:
        rows = c.execute(select(ingest_issues)
                         .order_by(ingest_issues.c.resolved_run.isnot(None),
                                   ingest_issues.c.id.desc())
                         .limit(limit)).mappings().all()
        return [dict(r) for r in rows]


# ---------- half-screenshot pairing ----------

def done_trips_for_pairing(job_id):
    """Minimal rows needed to pair top/bottom halves (done, not yet merged)."""
    with engine.begin() as c:
        rows = c.execute(select(trips.c.id, trips.c.file_name, trips.c.kind, trips.c.net_earnings,
                                trips.c.base_fare, trips.c.bonus, trips.c.turbo,
                                trips.c.booking_code, trips.c.merged_into)
                         .where(trips.c.job_id == job_id, trips.c.status == "done")).mappings().all()
        return [dict(r) for r in rows]


def has_merged_child(trip_id) -> bool:
    with engine.begin() as c:
        return bool(c.execute(select(func.count()).select_from(trips)
                              .where(trips.c.merged_into == trip_id)).scalar())


def merge_bottom_into_top(bottom_id, top_id, fields: dict):
    """Fold a bottom-half trip into its top half: copy fields, hide the bottom row."""
    with engine.begin() as c:
        vals = {k: v for k, v in fields.items() if k in set(TRIP_EDITABLE + _SYSTEM_FIELDS)}
        if vals:
            c.execute(update(trips).where(trips.c.id == top_id).values(**vals))
        c.execute(update(trips).where(trips.c.id == bottom_id, trips.c.status == "done")
                  .values(status="merged", merged_into=top_id))


def done_trips_for_dating(job_id, only_missing=True):
    q = (select(trips.c.id, trips.c.file_name)
         .where(trips.c.job_id == job_id, trips.c.status == "done", trips.c.committed == 0))
    if only_missing:
        q = q.where(trips.c.trip_date.is_(None))
    with engine.begin() as c:
        return [dict(r) for r in c.execute(q).mappings().all()]


def trips_with_images(job_id):
    """Done trips of a job with their image blobs — the merged bottom half's blob attached as
    `bottom_blob`. Only useful while blobs exist (before approval clears them)."""
    with engine.begin() as c:
        rows = c.execute(select(trips.c.id, trips.c.file_name, trips.c.trip_date,
                                trips.c.image_blob)
                         .where(trips.c.job_id == job_id, trips.c.status == "done")).mappings().all()
        bottoms = {r["merged_into"]: (r["id"], r["image_blob"]) for r in c.execute(
            select(trips.c.id, trips.c.merged_into, trips.c.image_blob)
            .where(trips.c.job_id == job_id, trips.c.status == "merged")).mappings().all()}
    out = []
    for r in rows:
        b = bottoms.get(r["id"])
        out.append({"id": r["id"], "file_name": r["file_name"], "trip_date": r["trip_date"],
                    "top_blob": bytes(r["image_blob"]) if r["image_blob"] else None,
                    "bottom_id": b[0] if b else None,
                    "bottom_blob": bytes(b[1]) if b and b[1] else None})
    return out


def get_job_meta(job_id):
    with engine.begin() as c:
        r = c.execute(select(jobs).where(jobs.c.id == job_id)).mappings().first()
        return dict(r) if r else None


def drive_ids_for_job(job_id):
    """trip_id -> Drive file id (for re-downloading originals after blobs were cleared)."""
    with engine.begin() as c:
        return {r[1]: r[0] for r in c.execute(select(ingested_files.c.drive_id, ingested_files.c.trip_id)
                                              .where(ingested_files.c.job_id == job_id)).all()}


def jobs_by_week():
    """{(date_from, date_to): [job meta...]} for every job — used by --exports-only."""
    with engine.begin() as c:
        rows = [dict(r) for r in c.execute(select(jobs).order_by(jobs.c.id)).mappings().all()]
    out = {}
    for j in rows:
        out.setdefault((j["date_from"], j["date_to"]), []).append(j)
    return out


# ---------- Drive links + weekly overview (Phase D UI) ----------

def record_drive_file(week, kind, drive_id, name=None, ref=""):
    key = f"{week}|{kind}|{ref}"
    with engine.begin() as c:
        c.execute(delete(drive_files).where(drive_files.c.key == key))
        c.execute(insert(drive_files).values(key=key, week=week, kind=kind, ref=str(ref),
                                             drive_id=str(drive_id), name=name, updated_at=_now()))


def drive_links():
    with engine.begin() as c:
        return [dict(r) for r in c.execute(select(drive_files)).mappings().all()]


def latest_ingest_run():
    with engine.begin() as c:
        r = c.execute(select(ingest_runs).order_by(ingest_runs.c.id.desc()).limit(1)).mappings().first()
        return dict(r) if r else None


def weeks_overview():
    """Jobs grouped by week → category → rider, with per-job counts and Drive links."""
    done = func.sum(case((trips.c.status == "done", 1), else_=0)).label("done")
    waiting = func.sum(case(((trips.c.status == "done") & (trips.c.committed == 0), 1), else_=0)).label("waiting")
    approved = func.sum(case(((trips.c.status == "done") & (trips.c.committed == 1), 1), else_=0)).label("approved")
    auto = func.sum(case(((trips.c.status == "done") & (trips.c.auto_approved == 1), 1), else_=0)).label("auto")
    errors = func.sum(case((trips.c.status == "error", 1), else_=0)).label("errors")
    pending = func.sum(case((trips.c.status == "pending", 1), else_=0)).label("pending")
    images = func.sum(case((trips.c.status != "x", 1), else_=0)).label("images")
    net = func.sum(case(((trips.c.status == "done") & (trips.c.committed == 1), trips.c.net_earnings), else_=0)).label("net")
    q = (select(jobs, done, waiting, approved, auto, errors, pending, images, net)
         .select_from(jobs.outerjoin(trips, trips.c.job_id == jobs.c.id))
         .group_by(*jobs.c).order_by(jobs.c.date_from.desc(), jobs.c.category, jobs.c.driver_name))
    with engine.begin() as c:
        rows = [dict(r) for r in c.execute(q).mappings().all()]
    links = drive_links()
    by_week_links = {}
    for l in links:
        by_week_links.setdefault(l["week"], {})[(l["kind"], l["ref"])] = l
    weeks = {}
    for j in rows:
        y, w, _ = datetime.strptime(j["date_from"], "%Y-%m-%d").isocalendar()
        wk = f"{y}-W{w:02d}"
        W = weeks.setdefault(wk, {"week": wk, "date_from": j["date_from"], "date_to": j["date_to"],
                                  "riders": 0, "images": 0, "trips": 0, "approved": 0, "auto": 0,
                                  "waiting": 0, "errors": 0, "pending": 0, "net": 0.0,
                                  "xlsx": None, "folder": None, "groups": {}})
        L = by_week_links.get(wk, {})
        if ("xlsx", "") in L:
            W["xlsx"] = L[("xlsx", "")]["drive_id"]
        if ("week_folder", "") in L:
            W["folder"] = L[("week_folder", "")]["drive_id"]
        j["rider_folder"] = L.get(("rider_folder", str(j["id"])), {}).get("drive_id")
        j["net"] = round(j["net"] or 0, 2)
        for k in ("riders", "images", "trips", "approved", "auto", "waiting", "errors", "pending"):
            W[k] += 1 if k == "riders" else (j["done"] if k == "trips" else (j[k] or 0))
        W["net"] = round(W["net"] + (j["net"] or 0), 2)
        W["groups"].setdefault(j["category"] or "อัปโหลดมือ", []).append(j)
    out = list(weeks.values())
    for W in out:
        W["groups"] = [{"category": k, "jobs": v} for k, v in W["groups"].items()]
    return out
