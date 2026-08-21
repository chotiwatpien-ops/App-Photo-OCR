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

def create_trip(job_id, file_name, image_bytes: bytes, mime: str) -> int:
    with engine.begin() as c:
        r = c.execute(insert(trips).values(
            job_id=job_id, file_name=file_name, image_blob=image_bytes, image_mime=mime,
            status="pending", committed=0))
        return r.inserted_primary_key[0]


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
