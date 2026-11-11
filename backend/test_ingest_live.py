# -*- coding: utf-8 -*-
"""The reading button knows a round is running (Fiat 2026-11-11): the page asks GitHub, because
the database hears of a round only when its Python starts, and pressing again is refused."""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-live-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from fastapi import HTTPException                               # noqa: E402

import archive_runs                                             # noqa: E402
import config                                                   # noqa: E402
import main                                                     # noqa: E402

ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


def run(status, started="2026-11-11T15:30:00Z", event="workflow_dispatch"):
    return {"status": status, "run_started_at": started, "created_at": started, "event": event}


done = run("completed")
check("ไม่มีรอบค้าง: ปุ่มกดได้", main.live_from([done, done]) == {"known": True, "active": False})
live = main.live_from([run("queued", "2026-11-11T15:40:00Z"), run("in_progress", event="schedule"), done])
check("❗ มีรอบกำลังรัน: บอกเวลาเริ่มเป็นเวลาไทย",
      live["active"] and live["state"] == "running" and live["started_at"] == "2026-11-11T22:30:00"
      and live["count"] == 2 and not live["by_hand"], live)
check("รอบที่ GitHub ยังไม่เริ่ม: บอกว่ารอเริ่ม", main.live_from([run("queued")])["state"] == "queued")

config.GITHUB_TOKEN, config.GITHUB_REPO = "", ""
check("ไม่ได้ตั้งค่า GitHub: บอกว่าไม่รู้ (หน้าเว็บใช้สถานะจากฐานข้อมูลแทน)", main.ingest_live(fresh=True) == {"known": False})

config.GITHUB_TOKEN, config.GITHUB_REPO = "t", "me/repo"
runs, asked, sent = [run("in_progress")], [], []
archive_runs._get = lambda url, token: asked.append(url) or {"workflow_runs": runs}
main._dispatch = lambda wf, inputs=None: sent.append(wf) or True
try:
    main.trigger_ingest()
    refused = None
except HTTPException as e:
    refused = e
check("❗ กดสั่งตอนมีรอบรันอยู่: ไม่สั่ง GitHub และบอกเหตุผล",
      refused is not None and refused.status_code == 409 and "กำลังรัน" in refused.detail and sent == [], refused)
check("ถามสถานะซ้ำภายใน 15 วินาทีใช้คำตอบเดิม", (main.ingest_live(), main.ingest_live()) and len(asked) == 1, asked)

runs[:] = [done]
check("❗ รอบจบแล้ว: สั่งได้ และคำตอบเก่าถูกล้าง", main.trigger_ingest()["ok"] and sent == ["ingest.yml"]
      and main._live["data"] is None, sent)


def broken(url, token):
    raise OSError("GitHub down")


archive_runs._get = broken
check("ถาม GitHub ไม่ได้: บอกว่าไม่รู้ และยังสั่งรอบได้",
      main.ingest_live(fresh=True) == {"known": False} and main.trigger_ingest()["ok"])

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
