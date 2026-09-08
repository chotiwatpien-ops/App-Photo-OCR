# -*- coding: utf-8 -*-
"""Central config for the Photo OCR app — env vars first, then photo_ocr_config.json, then defaults.

Cloud (Render) env vars:
  DATABASE_URL      postgresql://...  (Neon)        — default: local SQLite
  GEMINI_API_KEY    Gemini key                      — default: photo_ocr_config.json / Voice QA config
  APP_PASSWORD      shared login password           — default: no login (local dev)
  SECRET_KEY        cookie signing secret           — default: generated once into DATA_DIR
  GEMINI_MODEL      e.g. gemini-3.7-flash (3.5-flash-lite reads upper halves as whole screens — see below)
"""
import json
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "photo_ocr_config.json"
# fallback: reuse a sibling app's Gemini key on the developer's own machine (local dev only).
# Written out in full here until the repository went public, which put one person's username,
# employer and folder layout in it; point PHOTO_OCR_SIBLING_CONFIG at the file instead.
VOICE_QA_CONFIG = Path(os.environ.get("PHOTO_OCR_SIBLING_CONFIG")
                       or BASE_DIR.parent / "Voice_QA Application" / "csqa_config.json")
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"


def _config_value(key: str, default=None):
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get(key, default)
    return default


def _setting(env: str, key: str, default=None):
    v = os.environ.get(env)
    if v not in (None, ""):
        return v
    return _config_value(key, default)


IS_CLOUD = bool(os.environ.get("RENDER") or os.environ.get("DATABASE_URL"))

# --- storage ---
# local: outside OneDrive (WAL journal + sync = SQLite corruption); cloud: ephemeral, only for temp files
_local_app = os.environ.get("LOCALAPPDATA")
DATA_DIR = Path(os.environ.get("PHOTO_OCR_DATA")
                or (Path(_local_app) / "photo-ocr-data" if _local_app else BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{(DATA_DIR / 'photo_ocr.db').as_posix()}"
if DATABASE_URL.startswith("postgres://"):  # old-style scheme some providers still emit
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

# --- Excel ---
# local: commit appends to this workbook; cloud: commit = approve in DB, Excel comes from /api/export
EXCEL_PATH = Path(os.environ.get("PHOTO_OCR_EXCEL") or BASE_DIR / "Rider Trips.xlsx")
EXCEL_APPEND = str(_setting("PHOTO_OCR_EXCEL_APPEND", "excel_append", "0" if IS_CLOUD else "1")).lower() in ("1", "true", "yes")

# --- auth ---
APP_PASSWORD = _setting("APP_PASSWORD", "app_password")  # None -> login disabled (local dev)


def _secret_key() -> str:
    v = os.environ.get("SECRET_KEY")
    if v:
        return v
    f = DATA_DIR / "secret.key"
    if not f.exists():
        f.write_text(secrets.token_hex(32), encoding="utf-8")
    return f.read_text(encoding="utf-8").strip()


SECRET_KEY = _secret_key()

# --- GitHub Actions trigger (button "ดูดรูปจาก Drive ตอนนี้") ---
GITHUB_TOKEN = _setting("GITHUB_TOKEN", "github_token")          # fine-grained PAT with Actions: write
GITHUB_REPO = _setting("GITHUB_REPO", "github_repo")             # "owner/repo"
GITHUB_WORKFLOW = _setting("GITHUB_WORKFLOW", "github_workflow", "ingest.yml")

# trips each rider owes the customer per week (3/day × 7) — used for the per-rider shortfall list
EXPECTED_TRIPS_PER_WEEK = int(os.environ.get("EXPECTED_TRIPS_PER_WEEK", "21"))
# How a customer picture gets its number. 'append': a picture already delivered keeps the number
# it has and new work takes the numbers after it — so adding two trips to a rider who was already
# finished costs two files, not twenty-one. 'bydate': renumber every time so the numbers always
# run in date order, which is what happened until 2026-09-09 and cost a round forty minutes of
# rebuilding files whose contents had not changed. Ops decides which the customer reads.
CUSTOMER_IMAGE_NUMBERING = os.environ.get("CUSTOMER_IMAGE_NUMBERING", "append").strip().lower()
# Skip listing a rider folder Drive says has not been touched since the round that last read it
# to the end. Set to 0 to walk every folder every round.
WALK_CACHE = os.environ.get("WALK_CACHE", "1").strip().lower() not in ("0", "false", "no")
# One round can carry a different figure for one vehicle group (or one wheel count): Ops
# (2026-09-08) wanted this week's 2 W Saver complete before anything else and let the 21 go
# for that group only — a rider may hold more than 21 when the extra are Saver trips, and
# still no more than 21 Standard ones. QUOTA_2_W_SAVER=23 in the environment does that;
# QUOTA_2W would do it for both bike groups. Unset, everything is the figure above.
WEEK_QUOTA = {}
for _k in ("2 W Saver", "2 W Standard", "4 W Saver", "4 W Standard", "2W", "4W"):
    _v = os.environ.get("QUOTA_" + _k.replace(" ", "_").upper())
    if _v:
        WEEK_QUOTA[_k] = int(_v)

# what the customer buys: every vehicle group must reach this many trips a week on its own.
# A group that beats it does not cover one that misses it, so the Dashboard totals the
# shortfalls rather than the trips. 1,470 = 70 riders × the 21 above.
WEEKLY_TARGET_PER_GROUP = int(_setting("WEEKLY_TARGET_PER_GROUP", "weekly_target_per_group", 1470))

# read-only diagnostic API key (header X-Diag-Key on /api/diag/* only); unset = feature off
DIAG_KEY = _setting("DIAG_KEY", "diag_key", None)

# --- Gemini ---
# Audited 2026-08-21 (5 rounds x 19 images each, 100% on money fields for all three):
#   gemini-3.7-flash  thinking=low   ฿0.09/img  (default — user's plan)
#   gemini-2.5-flash  thinking=0     ฿0.03/img  (cheapest; set "model": "gemini-2.5-flash")
#   gemini-2.5-flash  thinking=auto  ฿0.13/img  (never use — ~1,000 hidden thinking tokens/img)
# 2026-08-27: gemini-3.5-flash-lite was tried live at ฿0.055/img and pulled the same day. It
# reads every UPPER half of a split screenshot as a whole screen (84 images: 42 full, 42 bottom,
# 0 top), so halves never pair and both rows get approved — 25 trips counted twice, ฿7,258, in
# one round. The batch guard in auto_approve_job now catches that shape, but the readings would
# still be wrong (base guessed = net, passenger fare empty). Cheaper is not cheaper here.
GEMINI_MODEL = _setting("GEMINI_MODEL", "model", "gemini-3.7-flash")

# $/1M tokens (in, out) for image prompts under 200k; thinking bills as output.
# Read off ai.google.dev/gemini-api/docs/pricing on 2026-08-27. Used by /api/diag/models
# and model_bench. NOTE 3.7/3.6 Flash are at intro pricing — both double on 2027-01-01.
GEMINI_PRICE = {
    "gemini-3.1-pro-preview": (2.00, 12.00),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.7-flash": (0.75, 3.75),
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3-flash-preview": (0.50, 3.00),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
}
USD_THB = 35.0
# Fields the model is NOT asked for. Output is billed at 5x input, so dropping one is worth
# real money: the two full addresses were 95 of the ~450 output tokens a slip costs — 9.8% of
# the bill, measured by reading the same 30 images both ways.
#
# They were dropped on 2026-09-02 ("nobody opens them") and asked for again on 2026-09-05, this
# time as the pick-up and drop-off shown on Sheet1 itself, where the zone had been saying
# "Downtown" for 84% of rows. At ~4,400 images a week that is about ฿40 a week, halved again by
# batch reading. Nothing is dropped now; the setting stays so a field can be switched off again
# without a code change.
EXTRACT_DROP_FIELDS = tuple(
    f for f in str(_setting("EXTRACT_DROP_FIELDS", "extract_drop_fields", "")).split(",")
    if f.strip())
GEMINI_THINKING_LEVEL = _setting("GEMINI_THINKING_LEVEL", "thinking_level", "low")
_tb = _setting("GEMINI_THINKING_BUDGET", "thinking_budget", 0)
GEMINI_THINKING_BUDGET = int(_tb) if _tb not in (None, "") else None
MAX_PARALLEL_EXTRACTIONS = int(_setting("MAX_PARALLEL", "max_parallel", 4))      # web app
INGEST_PARALLEL = int(_setting("INGEST_PARALLEL", "ingest_parallel", 12))        # Gemini calls in ingest
# Batch API for scheduled rounds: half the token price, and a round submits instead of waiting
# for Gemini (30 min of GitHub runner per round became ~3). Results arrive the FOLLOWING round.
# The web app's manual upload always reads live — Ops is standing there waiting for it.
INGEST_BATCH = str(_setting("INGEST_BATCH", "ingest_batch", "1")).lower() in ("1", "true", "yes")
# Images wait in the DB (blob and all) while a batch reads them, so one round must not park
# more than the free Neon tier can hold: ~131 KB a slip, 500 MB the ceiling. 1,500 keeps a
# round near 200 MB, and six rounds a day still clear 9,000 images — more than a full week's.
MAX_NEW_PER_ROUND = int(_setting("MAX_NEW_PER_ROUND", "max_new_per_round", 1500))

# ask Drive in one call whether anything new arrived before walking 600-odd folders for five
# minutes. Set to 0 to always walk (the old behaviour) if the probe ever looks untrustworthy.
DRIVE_PROBE = str(_setting("DRIVE_PROBE", "drive_probe", "1")).lower() in ("1", "true", "yes")
# Photos pulled from Drive are NOT copied into the database: the original stays on Drive, which
# charges nothing to read, while every copy in and out of Neon counts against a 5 GB monthly
# transfer allowance — 9,900 photos crossing it twice each exhausted the free tier in four days.
# A row that ends up waiting for a person does get its image stored, so the review page still
# shows it. Manual uploads always store, since there is no Drive copy to go back to.
STORE_DRIVE_IMAGES = str(_setting("STORE_DRIVE_IMAGES", "store_drive_images", "0")).lower() in ("1", "true", "yes")
DRIVE_PARALLEL = int(_setting("DRIVE_PARALLEL", "drive_parallel", 8))            # Drive uploads/downloads

# Sheet1 "Time" band source. The Grab trip screen has NO trip time — only the phone clock at
# capture time (riders screenshot in the evening). "screen_clock" bands that clock; "na" writes N/A.
TIME_BAND_SOURCE = _setting("TIME_BAND_SOURCE", "time_band_source", "screen_clock")

# Sheet1 "Passenger Fare": "total" = รวมค่าโดยสารของผู้โดยสาร, "paid" = ยอดที่ผู้โดยสารชำระ.
# Both are kept in the Analysis sheet. It was "paid" from 2026-08-21, matching the rows Operation
# had keyed for ขวัญชัย, but the customer sent Week 35 back: on the 21 rows they corrected by hand
# (docs/Rider Data Train.xlsx) รวม matches 21/21 and ชำระ matches 0/21 — the two differ whenever the
# passenger had a discount or an app fee, which is most trips. Changed 2026-09-04.
PASSENGER_FARE_SOURCE = _setting("PASSENGER_FARE_SOURCE", "passenger_fare_source", "total")

# --- Google Drive (ingest) ---
# service account: env GOOGLE_SERVICE_ACCOUNT_JSON (JSON text or path) > config "service_account_file" > ./service_account.json
_sa_default = BASE_DIR / "service_account.json"
GOOGLE_SERVICE_ACCOUNT = (os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
                          or _config_value("service_account_file")
                          or (str(_sa_default) if _sa_default.exists() else None))
# user OAuth token (drive_auth.py) — needed to WRITE into a personal Drive
_tok_default = BASE_DIR / "drive_token.json"
DRIVE_OAUTH_TOKEN = (os.environ.get("DRIVE_OAUTH_TOKEN_JSON")
                     or _config_value("drive_token_file")
                     or (str(_tok_default) if _tok_default.exists() else None))
DRIVE_INBOX_FOLDER_ID = _setting("DRIVE_INBOX_FOLDER_ID", "drive_inbox_folder_id")
DRIVE_EXPORTS_FOLDER_ID = _setting("DRIVE_EXPORTS_FOLDER_ID", "drive_exports_folder_id")
# Phase 2 "pool": whole LINE albums dropped as Inbox/<Week …>/Pool/<vehicle group>/<album>/
# (ingest skips a "Pool" folder inside a week). pool.py pairs the halves there and, once
# trusted, distributes trips into that week's rider folders. Set DRIVE_POOL_FOLDER_ID only for
# the alternative layout of one separate folder holding Pool/<Week …>/<group>/<album>/.
DRIVE_POOL_FOLDER_ID = _setting("DRIVE_POOL_FOLDER_ID", "drive_pool_folder_id")
POOL_PARALLEL = int(_setting("POOL_PARALLEL", "pool_parallel", 4))                # local OCR threads
# every ingest round first pairs and files what is in Week/Pool (pool.round_step); "0" leaves the
# pool alone so only the manual "Pool" workflow touches it
POOL_IN_ROUND = str(_setting("POOL_IN_ROUND", "pool_in_round", "1")).lower() in ("1", "true", "yes")
# Week folders kept for trying things out: skipped by the round (both the pool step and the
# rider-folder read), still reachable from the manual "Pool" workflow by naming the week.
# Matching is case-insensitive on any part of the folder name.
IGNORE_WEEKS = tuple(w.strip().lower() for w in
                     str(_setting("IGNORE_WEEKS", "ignore_weeks", "test,ทดสอบ,sandbox")).split(",") if w.strip())


def week_ignored(name: str) -> bool:
    n = (name or "").lower()
    return any(w in n for w in IGNORE_WEEKS)


def _usable_key(k) -> bool:
    return bool(k) and "PASTE" not in str(k).upper() and len(str(k).strip()) >= 30


def api_key_source() -> str:
    """Where the Gemini key comes from (never the key itself) — shown in /api/health."""
    if os.environ.get("GEMINI_API_KEY"):
        return "env GEMINI_API_KEY"
    for p, label in ((CONFIG_PATH, "photo_ocr_config.json"), (VOICE_QA_CONFIG, "Voice QA csqa_config.json")):
        if p.exists() and _usable_key(json.loads(p.read_text(encoding="utf-8")).get("api_key")):
            return label
    return "NOT FOUND"


def load_api_key() -> str:
    v = os.environ.get("GEMINI_API_KEY")
    if v:
        return v
    for p in (CONFIG_PATH, VOICE_QA_CONFIG):
        if p.exists():
            key = json.loads(p.read_text(encoding="utf-8")).get("api_key", "")
            if _usable_key(key):
                return key.strip()
    raise RuntimeError("Gemini API key not found. Set GEMINI_API_KEY or create photo_ocr_config.json")
