# -*- coding: utf-8 -*-
"""Copy finished GitHub Actions runs into the database — facts plus the tail of the log.

GitHub deletes a run's log after 90 days, and a support contract runs a year: a customer asking
in month five why a week came out short needs the log of the round that filed it. Run daily by
archive-runs.yml; a run already archived is skipped, rows older than db.RUN_LOG_DAYS dropped.

    python archive_runs.py                 # runs finished in the last 3 days
    python archive_runs.py --days 90       # everything GitHub still has
"""
import argparse
import io
import json
import os
import re
import sys
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone

import db

API = "https://api.github.com"
TAIL_BYTES = 16_000                       # per run; the end of a log is where it says what happened
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z ", re.MULTILINE)
BKK = timezone(timedelta(hours=7))


def _get(url, token, raw=False):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    return data if raw else json.loads(data)


def bkk(iso):
    """GitHub's UTC '2026-10-02T08:00:00Z' → the app's Bangkok wall clock '2026-10-02T15:00:00'."""
    if not iso:
        return None
    t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return t.astimezone(BKK).replace(tzinfo=None).isoformat(timespec="seconds")


def tail(text, limit=TAIL_BYTES):
    text = STAMP.sub("", text)
    b = text.encode("utf-8")
    if len(b) <= limit:
        return text
    return "…(ตัดต้น log)\n" + b[-limit:].decode("utf-8", "ignore")


def run_log(repo, run_id, token):
    """The run's log as one text: every job, every step, in order (GitHub serves it as a zip)."""
    try:
        data = _get(f"{API}/repos/{repo}/actions/runs/{run_id}/logs", token, raw=True)
    except Exception as e:  # noqa: BLE001
        return f"(ดึง log ไม่ได้: {str(e)[:200]})"
    parts = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        # the zip holds one file per job ('0_close.txt') and per step ('close/3_Close the week.txt');
        # the per-job files already contain every step, so only those are taken
        for name in sorted(n for n in z.namelist() if "/" not in n) or sorted(z.namelist()):
            parts.append(f"== {name}\n" + z.read(name).decode("utf-8", "ignore"))
    return "\n".join(parts)


def archive(repo, token, days=3, log=print):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    runs, page = [], 1
    while True:
        got = _get(f"{API}/repos/{repo}/actions/runs?status=completed&per_page=100&page={page}"
                   f"&created=%3E%3D{since}", token).get("workflow_runs", [])
        runs += got
        if len(got) < 100 or page >= 20:
            break
        page += 1
    have = db.archived_run_ids([r["id"] for r in runs])
    new = [r for r in runs if r["id"] not in have]
    for r in new:
        db.archive_workflow_run({
            "id": r["id"], "workflow": r.get("name"), "event": r.get("event"),
            "title": (r.get("display_title") or "")[:300], "status": r.get("status"),
            "conclusion": r.get("conclusion"), "started_at": bkk(r.get("run_started_at") or r.get("created_at")),
            "finished_at": bkk(r.get("updated_at")), "actor": (r.get("actor") or {}).get("login"),
            "url": r.get("html_url"), "log_tail": tail(run_log(repo, r["id"], token))})
    gone = db.prune_workflow_runs()
    log(f"พบ {len(runs)} รอบที่จบใน {days} วัน · เก็บใหม่ {len(new)} · มีอยู่แล้ว {len(have)}"
        f" · ลบที่เก่ากว่า {db.RUN_LOG_DAYS} วัน {gone}")
    return len(new)


def main(argv=None):
    ap = argparse.ArgumentParser(description="เก็บ log ของ GitHub Actions ลงฐานข้อมูล")
    ap.add_argument("--days", type=int, default=3)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if not (repo and token):
        print("ต้องมี GITHUB_REPOSITORY และ GITHUB_TOKEN (บน Actions มีให้เอง)")
        return 1
    db.init_db()
    archive(repo, token, a.days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
