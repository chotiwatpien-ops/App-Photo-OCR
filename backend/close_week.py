# -*- coding: utf-8 -*-
"""Close a week in one go — what the web's 'ปิดสัปดาห์' button runs (workflow close-week.yml).

Until now a week was closed by pressing six GitHub workflows in an order only Fiat knew
(2026-09-16: chip audit → rehome → carry → carry_back, then pictures, the Phase 3 file and the
audit). A customer running the app by themselves cannot do that, so this runs the same tools,
in the same order, with the same arguments, and writes each step's outcome to `close_runs`
for the page to show.

    plan   every step report-only, then the audit from the database: what pressing would do
    apply  the steps for real; the week is locked (week_locks) only if the audit finds nothing
           that would put a wrong row or a missing picture in front of the customer

Not included: the chip audit. It reads the chip on every picture with OCR (sharded, ~an hour)
and since 2026-09-09 the reader lets the chip decide the tier as it reads.

The steps call each tool's own main() — the code paths that closed W36-W39 — instead of a
second copy of their logic. Their printed report becomes the step's log."""
import argparse
import io
import re
import sys
import traceback
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta

import db

STEPS = [
    ("rehome", "ย้ายแถวไปกลุ่มตาม Service Type"),
    ("carry", "ยกงานที่เกินเป้าไปสัปดาห์หน้า"),
    ("carry_back", "ดึงงานกลับ ถ้ากลุ่มไหนขาดเป้า"),
    ("staged", "ย้ายแถวที่ค้างกองพักไปสัปดาห์หน้า"),
    ("pictures", "สร้างรูปส่งลูกค้าใหม่ (สัปดาห์นี้ + สัปดาห์หน้า)"),
    ("phase3", "ออกไฟล์ Phase 3"),
    ("audit", "ตรวจสัปดาห์"),
    ("lock", "ติดป้าย 'ปิดแล้ว'"),
]
PLAN_SKIPS = {"pictures": "ทำตอนปิดจริงเท่านั้น", "lock": "ทำตอนปิดจริงเท่านั้น"}

# audit sheets that mean the file is wrong or a picture is missing — the week is not locked
BLOCKING = ["งานซ้ำ-รหัสการจอง", "กลุ่มไม่ตรงServiceType", "ไม่มีรูปส่งลูกค้า",
            "ชื่อรูปซ้ำในกลุ่มเดียวกัน", "รูปหายจาก Drive"]
SERVICES = ("Saver Bike", "Standard Bike", "Standard Car")
INGEST_STALE_HOURS = 3


def next_week(d_from, d_to):
    a, b = (date.fromisoformat(d) + timedelta(days=7) for d in (d_from, d_to))
    return a.isoformat(), b.isoformat()


def _ingest_running():
    last = db.latest_ingest_run()
    if not last or last.get("finished_at") or not last.get("started_at"):
        return None
    age = (datetime.now(db._TZ_BKK).replace(tzinfo=None)
           - datetime.fromisoformat(last["started_at"])).total_seconds() / 3600
    return last if age < INGEST_STALE_HOURS else None      # older: died without saying so


def preflight(d_from, d_to, today=None):
    """What has to be true before the week may be closed. Read-only and cheap — the web page
    asks it on every visit. `block` checks stop the button; `warn` ones are shown and allowed."""
    w = db.week_waiting_counts(d_from, d_to)
    card = db.week_scorecard(d_from, d_to)
    today = today or datetime.now(db._TZ_BKK).date().isoformat()
    running = _ingest_running()
    import move_staged
    # read rows in _พร้อมอ่าน the week still has room for: a round files them, and after the
    # close nothing would — they would be read, paid for and never delivered
    keep = len(move_staged.plan(d_from, d_to)[0])
    checks = [
        {"key": "pending", "level": "block", "ok": w["pending"] == 0,
         "label": "รูปที่ยังอ่านไม่เสร็จ (รวมที่รอผล batch)",
         "detail": f"{w['pending']:,} รูป — รอรอบ ingest ถัดไปเก็บผลก่อน" if w["pending"] else "ไม่มี"},
        {"key": "review", "level": "block", "ok": w["review"] == 0,
         "label": "แถวในคิวตรวจของสัปดาห์นี้",
         "detail": (f"{w['review']:,} แถว — ตรวจในแท็บคิวตรวจก่อน ไม่งั้นตอนยกงานระบบจะนับเป็นงานที่เสร็จแล้ว"
                    if w["review"] else "ไม่มี")},
        {"key": "staged", "level": "block", "ok": keep == 0,
         "label": "แถวที่อ่านแล้ว รอลงโฟลเดอร์ (กลุ่มยังมีที่ว่าง)",
         "detail": f"{keep:,} แถว — รอรอบ ingest ถัดไปลงโฟลเดอร์ให้ก่อน" if keep else "ไม่มี"},
        {"key": "ingest", "level": "block", "ok": running is None,
         "label": "รอบ ingest ที่กำลังรัน",
         "detail": f"เริ่ม {running['started_at']} — รอให้จบก่อน" if running else "ไม่มี"},
        {"key": "closed", "level": "block", "ok": not db.week_closed(d_from),
         "label": "สัปดาห์นี้ปิดไปแล้วหรือยัง",
         "detail": "ปิดแล้ว — กดเปิดใหม่ก่อนถ้าจะปิดอีกรอบ" if db.week_closed(d_from) else "ยังไม่ปิด"},
        {"key": "ended", "level": "warn", "ok": today > d_to,
         "label": "สัปดาห์จบแล้วหรือยัง",
         "detail": "จบแล้ว" if today > d_to else f"ยังไม่จบ (ถึง {d_to}) — งานที่วางหลังจากปิดจะไปสัปดาห์หน้า"},
        {"key": "error", "level": "warn", "ok": card["error"] == 0,
         "label": "รูปที่อ่านไม่สำเร็จ",
         "detail": f"{card['error']:,} รูป — จะไม่อยู่ในไฟล์" if card["error"] else "ไม่มี"},
    ]
    return {"ok": all(c["ok"] for c in checks if c["level"] == "block"), "checks": checks,
            "card": _card(card)}


def _card(card):
    """The part of the scorecard the page shows: each service against the target."""
    return {"by_service": {s: card["by_service"].get(s, 0) for s in SERVICES},
            "other": {k: v for k, v in card["by_service"].items() if k not in SERVICES},
            "under": card["under"], "over": card["over"], "staged": card["staged"],
            "no_picture": card["no_picture"], "shared_picture": card["shared_picture"]}


class _Tee(io.StringIO):
    """Keeps what a tool prints for the page and still shows it in the Actions log. The tools
    call sys.stdout.reconfigure(), which a plain StringIO does not have."""

    def __init__(self, echo):
        super().__init__()
        self._echo = echo

    def write(self, s):
        try:
            self._echo.write(s)
        except Exception:  # noqa: BLE001
            pass
        return super().write(s)

    def reconfigure(self, **_kw):
        return None


def _call(fn, *args, **kw):
    """(return value, printed text) of fn(*args)."""
    out = _Tee(sys.__stdout__)
    with redirect_stdout(out):
        rv = fn(*args, **kw)
    return rv, out.getvalue()


def _summary(text, limit=14):
    """The lines worth reading on the page — the tools' own report minus the run-again hints."""
    keep = [ln.rstrip() for ln in text.splitlines()
            if ln.strip() and not ln.strip().startswith(("(รายงานอย่างเดียว", "(นับอย่างเดียว", "ขั้นต่อไป:"))]
    return "\n".join(keep[:limit] + (["…"] if len(keep) > limit else []))


def week_folder(drive, inbox, d_from, d_to):
    """The Inbox folder whose name spells this week, e.g. 'Week 21-27 Sep'."""
    from ingest import parse_range
    want = (date.fromisoformat(d_from), date.fromisoformat(d_to))
    for f in drive.list_folders(inbox):
        if parse_range(f["name"], default_year=want[0].year) == want:
            return f["name"].strip()
    return None


class Runner:
    def __init__(self, run_id, d_from, d_to, mode):
        self.id, self.d_from, self.d_to, self.mode = run_id, d_from, d_to, mode
        self.steps = [{"key": k, "title": t, "status": "waiting", "summary": "", "log": ""} for k, t in STEPS]
        self.result = {}

    def save(self, **fields):
        db.update_close_run(self.id, steps=self.steps, result=self.result, **fields)

    def step(self, key):
        return next(s for s in self.steps if s["key"] == key)

    def run_step(self, key, fn):
        s = self.step(key)
        s["status"] = "running"
        self.save()
        try:
            rv, text = _call(fn)
        except Exception as e:  # noqa: BLE001
            s.update(status="failed", summary=f"{type(e).__name__}: {e}"[:500],
                     log=traceback.format_exc()[-6000:])
            self.save()
            raise
        # a tool's main() returns 0/1; export_only returns (errors, failed). 1 == True in Python,
        # so the cases are told apart by type, not by `in`.
        if isinstance(rv, tuple):
            ok = not rv[0]
        elif isinstance(rv, bool):
            ok = rv
        else:
            ok = rv in (0, None)
        s.update(status="done" if ok else "failed", summary=_summary(text), log=text[-20000:])
        self.save()
        if not ok:
            raise RuntimeError(f"ขั้น '{s['title']}' ไม่สำเร็จ")
        return text

    def skip(self, key, why):
        self.step(key).update(status="skipped", summary=why)

    def go(self):
        d_from, d_to, apply = self.d_from, self.d_to, self.mode == "apply"
        n_from, n_to = next_week(d_from, d_to)
        db.update_close_run(self.id, status="running", started_at=db._now())
        pre = preflight(d_from, d_to)
        self.result["before"] = pre["card"]
        if apply and not pre["ok"]:
            why = " · ".join(f"{c['label']}: {c['detail']}" for c in pre["checks"]
                             if c["level"] == "block" and not c["ok"])
            for s in self.steps:
                s["status"] = "skipped"
            self.save(status="blocked", finished_at=db._now(), message=f"ยังปิดไม่ได้ — {why}")
            return 1

        import carry_back
        import carry_excess
        import config
        import move_staged
        import rehome_by_service
        import week_phase3
        flag = ["--apply"] if apply else []
        drive = wk = None
        if apply:
            import roster
            drive = roster._drive()
            wk = week_folder(drive, config.DRIVE_INBOX_FOLDER_ID, d_from, d_to)
            if not wk:
                self.save(status="failed", finished_at=db._now(),
                          message=f"ไม่พบโฟลเดอร์ของสัปดาห์ {d_from}..{d_to} ใน Inbox บน Drive")
                return 1
        # report-only runs never open Drive, and the tools only need the folder name to move files
        name = wk or "Week"
        rng = ["--from", d_from, "--to", d_to]
        target = ["--target", str(config.WEEKLY_TARGET_PER_GROUP)]     # the tools default to 1470
        try:
            self.run_step("rehome", lambda: rehome_by_service.main(rng + ["--week", name] + flag))
            self.run_step("carry", lambda: carry_excess.main(rng + ["--week", name] + target + flag))
            self.run_step("carry_back", lambda: carry_back.main(rng + ["--week", name] + target + flag))
            self.run_step("staged", lambda: move_staged.main(rng + flag))
            if apply:
                import ingest
                labels = {ingest.week_label(d_from), ingest.week_label(n_from)}
                self.run_step("pictures", lambda: ingest.export_only(
                    drive, config.DRIVE_EXPORTS_FOLDER_ID, weeks=labels))
                text = self.run_step("phase3", lambda: week_phase3.main(rng + ["--to-drive"]))
                m = re.search(r"https://drive\.google\.com/file/d/[\w-]+/view", text)
                self.result["file"] = m.group(0) if m else None
            else:
                self.skip("pictures", PLAN_SKIPS["pictures"])
                self.run_step("phase3", lambda: week_phase3.main(rng))
            found = self.audit(drive)
            blocking = {k: n for k, n in found.items() if k in BLOCKING and n}
            if not apply:
                self.skip("lock", PLAN_SKIPS["lock"])
            elif blocking:
                self.skip("lock", "ไม่ติดป้าย — audit พบ " + " · ".join(f"{k} {n}" for k, n in blocking.items()))
            else:
                db.close_week(d_from, d_to, by="close-week")
                self.step("lock").update(status="done", summary="ปิดแล้ว — งานอัตโนมัติจะไม่แตะสัปดาห์นี้อีก")
            after = _card(db.week_scorecard(d_from, d_to))
            if not apply:
                after = self.projected(after)
            self.result.update(after=after, next_week=_card(db.week_scorecard(n_from, n_to)),
                               audit=found, closed=apply and not blocking)
            self.save(status="done", finished_at=db._now(), message=self.verdict(after, blocking))
            return 0
        except Exception as e:  # noqa: BLE001
            for s in self.steps:
                if s["status"] == "waiting":
                    s["status"] = "skipped"
            self.save(status="failed", finished_at=db._now(), message=str(e)[:500])
            return 1

    def projected(self, now):
        """What the week would hold after a real close, from the plan's own arithmetic: a group
        over target is carried down to it; one under gets back what was carried out of it, as
        far as that goes. Neither moving groups nor the waiting room changes a Service Type count."""
        import config
        from carry_back import SERVICE_OF, candidates
        target = config.WEEKLY_TARGET_PER_GROUP
        group_of = {v: k for k, v in SERVICE_OF.items()}
        out = dict(now, by_service=dict(now["by_service"]), under={}, over={}, projected=True)
        for svc, have in now["by_service"].items():
            if have > target:
                out["by_service"][svc] = target
            elif have < target and svc in group_of:
                out["by_service"][svc] = have + min(target - have, len(candidates(self.d_from, self.d_to, group_of[svc])))
            left = out["by_service"][svc] - target
            if left < 0:
                out["under"][svc] = -left
        return out

    def audit(self, drive):
        """week_audit's checks, kept as counts for the page; with Drive, the pictures as well and
        the report goes to Exports/_ตรวจสัปดาห์ like the workflow puts it."""
        import config
        import week_audit
        from ingest import week_label

        def go():
            rows = week_audit.week_rows(self.d_from, self.d_to)
            pics = (week_audit.pictures_on_drive(drive, config.DRIVE_EXPORTS_FOLDER_ID, self.d_from)
                    if drive else None)
            out = week_audit.audit(rows, pics)
            print(f"ตรวจ {week_label(self.d_from)} ({self.d_from}..{self.d_to})")
            print("\n".join(week_audit.summary(rows, out)))
            if drive:
                folder = drive.ensure_folder(config.DRIVE_EXPORTS_FOLDER_ID, week_audit.DRIVE_DIR)
                fid = drive.upload_xlsx(folder, f"ตรวจ {week_label(self.d_from)}.xlsx",
                                        week_audit.build_xlsx(rows, out, self.d_from))
                print(f"วางรายงานลง Drive: https://drive.google.com/file/d/{fid}/view")
            return {k: len(v) for k, v in out.items()}

        s = self.step("audit")
        s["status"] = "running"
        self.save()
        found, text = _call(go)
        m = re.search(r"https://drive\.google\.com/file/d/[\w-]+/view", text)
        if m:
            self.result["audit_file"] = m.group(0)
        bad = [k for k in BLOCKING if found.get(k)]
        if self.mode == "plan":     # nothing has moved yet: a repeat across groups, say, is still here
            text = "ตรวจจากสภาพตอนนี้ ก่อนย้าย/ยกงาน — ตอนปิดจริงจะตรวจใหม่หลังทำทุกขั้น\n" + text
        s.update(status="done", summary=_summary(text, 20), log=text[-20000:],
                 flag="block" if bad else ("warn" if any(found.values()) else None))
        self.save()
        return found

    def verdict(self, after, blocking):
        short = " · ".join(f"{s} ขาด {n:,}" for s, n in after["under"].items())
        over = " · ".join(f"{s} เกิน {n:,}" for s, n in after["over"].items())
        if self.mode == "plan":
            head = "แผนพร้อม — ตัวเลขแต่ละขั้นคิดจากสภาพตอนนี้ ขั้นหลังจะคำนวณใหม่ตอนปิดจริง"
        elif blocking:
            head = "ทำครบทุกขั้น แต่ยังไม่ติดป้ายปิด — audit พบปัญหา ดูขั้นตรวจสัปดาห์"
        else:
            head = "ปิดสัปดาห์แล้ว"
        return " · ".join(x for x in (head, short, over) if x)


def main(argv=None):
    ap = argparse.ArgumentParser(description="ปิดสัปดาห์ในครั้งเดียว (ปุ่มบนเว็บ)")
    ap.add_argument("--from", dest="d_from")
    ap.add_argument("--to", dest="d_to")
    ap.add_argument("--mode", choices=("plan", "apply"), default="plan")
    ap.add_argument("--run-id", type=int, help="แถวใน close_runs ที่เว็บสร้างไว้ (ว่าง = สร้างใหม่)")
    ap.add_argument("--mark-failed", type=int, metavar="RUN_ID",
                    help="ใช้ใน workflow เมื่อรันล้มก่อนถึงตัวนี้ — บอกหน้าเว็บว่ารอบนี้ตายแล้ว")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    db.init_db()
    if a.mark_failed:
        run = db.get_close_run(a.mark_failed)
        if run and run["status"] in ("queued", "running"):
            db.update_close_run(a.mark_failed, status="failed", finished_at=db._now(),
                                message="รอบนี้ล้มกลางทาง (ดู log บน GitHub Actions)")
        return 0
    if not (a.d_from and a.d_to):
        ap.error("ต้องใส่ --from และ --to")
    run_id = a.run_id or db.create_close_run(a.d_from, a.d_to, a.mode)
    rc = Runner(run_id, a.d_from, a.d_to, a.mode).go()
    run = db.get_close_run(run_id)
    print(f"\n== close run #{run_id}: {run['status']} — {run.get('message') or ''}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
