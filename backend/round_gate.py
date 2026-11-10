# -*- coding: utf-8 -*-
"""Is a scheduled reading round due? One answer for every place that asks.

The schedule asks every hour (GitHub fires late and skips some). A round is due when:
  - no round has ever run;
  - the last round is still marked running but started more than STALE_RUN_HOURS ago — it died
    without stamping its row, and waiting for it would stop every scheduled round for good;
  - the last round finished at least ROUND_MIN_GAP_HOURS ago;
  - or a Gemini batch has been out at least BATCH_COLLECT_MIN minutes and the last round
    finished at least that long ago, because collecting the answers is what fills the queue.

    python round_gate.py          # prints the answer; writes due=true|false to $GITHUB_OUTPUT
"""
import os
import sys
from datetime import datetime

import config


def _hours(now, stamp):
    return (now - datetime.fromisoformat(stamp)).total_seconds() / 3600 if stamp else None


def decide(now, last_run, oldest_open_batch=None, min_gap=None, collect_min=None, stale=None):
    """(due, reason). last_run is the newest ingest_runs row as a dict, or None; the batch is
    the oldest batch not yet collected, or None. Times are Bangkok wall-clock ISO strings."""
    min_gap = config.ROUND_MIN_GAP_HOURS if min_gap is None else min_gap
    collect_h = (config.BATCH_COLLECT_MIN if collect_min is None else collect_min) / 60
    stale = config.STALE_RUN_HOURS if stale is None else stale
    if not last_run:
        return True, "ยังไม่เคยมีรอบ"
    if not last_run.get("finished_at"):
        age = _hours(now, last_run.get("started_at"))
        if age is not None and age < stale:
            return False, f"มีรอบกำลังรันอยู่ (เริ่มมา {age:.1f} ชม.)"
        return True, f"รอบก่อนค้างอยู่เกิน {stale:g} ชม. ถือว่าล่มไปแล้ว รอบนี้ปิดให้แล้วอ่านต่อ"
    since = _hours(now, last_run["finished_at"])
    if since >= min_gap:
        return True, f"รอบล่าสุดจบไป {since:.1f} ชม. ครบเวลา"
    if oldest_open_batch and oldest_open_batch.get("created_at"):
        out = _hours(now, oldest_open_batch["created_at"])
        if out >= collect_h and since >= collect_h:
            return True, f"มีผลอ่านจาก Gemini รอเก็บ (ส่งไปแล้ว {out * 60:.0f} นาที)"
    return False, f"รอบล่าสุดเพิ่งจบไป {since:.1f} ชม. และไม่มีผลอ่านรอเก็บ"


def check(now=None):
    import db
    now = now or datetime.now(db._TZ_BKK).replace(tzinfo=None)
    batches = db.open_batches()
    return decide(now, db.latest_ingest_run(), batches[0] if batches else None)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        due, why = check()
    except Exception as e:  # noqa: BLE001 — an unreadable answer runs the round; a check must never cost one
        due, why = True, f"ถามฐานข้อมูลไม่สำเร็จ ({str(e)[:120]}) — รันไปก่อน"
    print(("▶ ถึงเวลารอบอ่าน: " if due else "⏭ ยังไม่ถึงเวลา: ") + why)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"due={'true' if due else 'false'}\n")


if __name__ == "__main__":
    main()
