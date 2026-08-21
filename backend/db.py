# -*- coding: utf-8 -*-
"""Storage layer — SQLAlchemy Core so the same code runs on SQLite (local) and Postgres (Neon).

Images are kept as blobs only while a job is under review and cleared on commit,
so the database stays small enough for a free Postgres tier.
"""
from datetime import datetime

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
    Column("passenger_total", Float),
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
)

TRIP_EDITABLE = [
    "trip_date", "trip_time", "service_type", "payment_method",
    "pickup_code", "dropoff_code", "pickup_text", "dropoff_text",
    "distance_km", "duration_mins", "net_earnings", "base_fare",
    "intl_fee", "bonus", "turbo", "tolls", "passenger_total",
    "pickup_district", "dropoff_district", "surge", "queue_type",
    "num_stops", "app_fee", "other_adj", "fare_refund", "note",
]
_SYSTEM_FIELDS = ["status", "error", "booking_code", "check_status", "duplicate_of",
                  "grab_commission", "model", "tok_in", "tok_out", "tok_think"]
# columns returned to the API (everything except the blob)
TRIP_COLS = [c for c in trips.c if c.name != "image_blob"]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def init_db():
    meta.create_all(engine)
    if _is_sqlite:
        # older local DBs: add columns that appeared after they were created (safe no-op otherwise)
        with engine.begin() as c:
            c.execute(text("PRAGMA journal_mode=WAL"))
            existing = {r[1] for r in c.execute(text("PRAGMA table_info(trips)"))}
            for col in trips.c:
                if col.name not in existing:
                    typ = {"INTEGER": "INTEGER", "REAL": "REAL", "BLOB": "BLOB"}.get(
                        str(col.type).split("(")[0].upper(), "TEXT")
                    c.execute(text(f"ALTER TABLE trips ADD COLUMN {col.name} {typ}"))


# ---------- jobs ----------

def create_job(driver_name, sheet, date_from, date_to) -> int:
    with engine.begin() as c:
        r = c.execute(insert(jobs).values(
            driver_name=driver_name, sheet=sheet, date_from=date_from, date_to=date_to,
            status="running", created_at=_now()))
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
    q = (select(jobs, func.count(trips.c.id).label("trip_count"), done, err)
         .select_from(jobs.outerjoin(trips, trips.c.job_id == jobs.c.id))
         .group_by(*jobs.c).order_by(jobs.c.id.desc()).limit(limit))
    with engine.begin() as c:
        return [dict(r) for r in c.execute(q).mappings().all()]


def mark_committed(job_id):
    """Approve all done trips and drop their image blobs (only needed during review)."""
    with engine.begin() as c:
        c.execute(update(trips).where(trips.c.job_id == job_id, trips.c.status == "done")
                  .values(committed=1, image_blob=None))
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


def auto_approve_job(job_id) -> dict:
    """Commit rows that passed every check (✓, not a duplicate, booking code unseen);
    leave the rest for a person. Returns {approved, flagged}."""
    with engine.begin() as c:
        rows = c.execute(select(trips.c.id, trips.c.check_status, trips.c.duplicate_of,
                                trips.c.booking_code, trips.c.trip_date)
                         .where(trips.c.job_id == job_id, trips.c.status == "done",
                                trips.c.committed == 0)).mappings().all()
        codes = [r["booking_code"] for r in rows if r["booking_code"]]
        seen = set()
        if codes:
            seen = {r[0] for r in c.execute(select(trips.c.booking_code)
                                            .where(trips.c.committed == 1,
                                                   trips.c.booking_code.in_(codes))).all()}
        ok_ids = [r["id"] for r in rows
                  if r["check_status"] == "pass" and not r["duplicate_of"] and r["trip_date"]
                  and (not r["booking_code"] or r["booking_code"] not in seen)]
        if ok_ids:
            c.execute(update(trips).where(trips.c.id.in_(ok_ids))
                      .values(committed=1, auto_approved=1, image_blob=None))
        remaining = c.execute(select(func.count()).select_from(trips)
                              .where(trips.c.job_id == job_id, trips.c.status == "done",
                                     trips.c.committed == 0)).scalar()
        c.execute(update(jobs).where(jobs.c.id == job_id)
                  .values(status="committed" if remaining == 0 else "review"))
        return {"approved": len(ok_ids), "flagged": len(rows) - len(ok_ids)}


def start_ingest_run() -> int:
    with engine.begin() as c:
        return c.execute(insert(ingest_runs).values(started_at=_now())).inserted_primary_key[0]


def finish_ingest_run(run_id, **stats):
    with engine.begin() as c:
        c.execute(update(ingest_runs).where(ingest_runs.c.id == run_id)
                  .values(finished_at=_now(), **stats))


def find_job(driver_name, date_from, date_to):
    """Existing job for this rider + week (ingest appends to it across runs)."""
    with engine.begin() as c:
        r = c.execute(select(jobs.c.id).where(jobs.c.driver_name == driver_name,
                                              jobs.c.date_from == date_from,
                                              jobs.c.date_to == date_to)
                      .order_by(jobs.c.id.desc()).limit(1)).first()
        return r[0] if r else None


def get_trip(trip_id):
    with engine.begin() as c:
        r = c.execute(select(*TRIP_COLS).where(trips.c.id == trip_id)).mappings().first()
        return dict(r) if r else None


def get_trip_image(trip_id):
    """(bytes, mime) or None — blobs are cleared after commit."""
    with engine.begin() as c:
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
    q = (select(*TRIP_COLS, jobs.c.driver_name, jobs.c.id.label("job_id_"))
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
    q = q.order_by(jobs.c.driver_name, trips.c.trip_date, trips.c.trip_time, trips.c.id)
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
