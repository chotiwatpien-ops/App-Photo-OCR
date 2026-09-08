# -*- coding: utf-8 -*-
"""The 'sync Excel now' button (Ops, 2026-09-09).

An ingest round rewrites both customer workbooks on Drive, but only every few hours and only
after the whole round. This button does the same rewrite from the same rows, on demand, in the
background — and says plainly when the server cannot write to Drive at all, instead of
pretending. Downloading either workbook works whatever the server's Drive access is.
"""
import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-sync-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import config                                                   # noqa: E402
import main                                                     # noqa: E402
from fastapi.testclient import TestClient                       # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


main.PUBLIC_API = set(main.PUBLIC_API) | {"/api/export/sync", "/api/export/phase2"}   # no login here
c = TestClient(main.app)

check("ยังไม่เคย sync → สถานะ idle", c.get("/api/export/sync").json() == {"state": "idle"})

# a server with no Drive access says so, and points at the download instead
config.DRIVE_OAUTH_TOKEN, config.GOOGLE_SERVICE_ACCOUNT = "", ""
r = c.post("/api/export/sync")
check("ไม่มีสิทธิ์ Drive → 501 พร้อมบอกว่าต้องตั้งอะไร", r.status_code == 501 and "DRIVE_OAUTH_TOKEN_JSON" in r.json()["detail"])
check("และยังชี้ให้ใช้ปุ่มดาวน์โหลด", "ดาวน์โหลด" in r.json()["detail"])

# the downloads never depend on Drive
r = c.get("/api/export/phase2")
from urllib.parse import unquote                                # noqa: E402
check("ดาวน์โหลด Phase 2 ได้เสมอ (เป็นไฟล์ xlsx)", r.status_code == 200 and r.content[:2] == b"PK"
      and "Rider Trips Phase 2" in unquote(r.headers.get("content-disposition", "")))
r = c.get("/api/export")
check("ดาวน์โหลด Rider Trips ได้เสมอ", r.status_code == 200 and r.content[:2] == b"PK")


# with Drive access, the work runs in the background and the status follows it
class FakeDrive:
    def __init__(self):
        self.uploaded = []

    def upload_xlsx(self, parent, name, data):
        self.uploaded.append((parent, name, len(data)))
        return f"id-{name}"


fake = FakeDrive()
import roster                                                   # noqa: E402
roster._drive = lambda: fake
config.DRIVE_OAUTH_TOKEN, config.DRIVE_EXPORTS_FOLDER_ID = "{token}", "exports"
main._sync.clear(); main._sync.update(state="idle")
r = c.post("/api/export/sync")
check("มีสิทธิ์ → รับงานทันที สถานะ running", r.status_code == 200 and r.json()["state"] == "running")
for _ in range(100):
    if main._sync["state"] != "running":
        break
    time.sleep(0.1)
st = c.get("/api/export/sync").json()
check("ทำเสร็จเอง → done พร้อมจำนวนแถวและเวลา", st["state"] == "done" and st["rows"] == 0 and st.get("finished_at"))
check("เขียน Rider Trips.xlsx ขึ้นโฟลเดอร์ Exports", ("exports", "Rider Trips.xlsx") in [(p, n) for p, n, _ in fake.uploaded])
check("ไม่มีแถว W36 ก็ไม่เขียนไฟล์ Phase 2 (ไม่มีอะไรจะเขียน)",
      all(n != "Rider Trips Phase 2.xlsx" for _, n, _ in fake.uploaded))

# a second click while one is running does not start a second one
main._sync.update(state="running")
r = c.post("/api/export/sync")
check("กดซ้ำระหว่างทำ → ตอบสถานะเดิม ไม่เริ่มใหม่", r.json()["state"] == "running")
main._sync.update(state="idle")

# nothing approved has changed since the last write: no 13,000-row pull from Neon, no upload
n_before = len(fake.uploaded)
c.post("/api/export/sync")
for _ in range(100):
    if main._sync["state"] != "running":
        break
    time.sleep(0.1)
check("กดซ้ำเมื่อไม่มีอะไรเปลี่ยน → บอกว่าไม่มีอะไรเปลี่ยน ไม่เขียนไฟล์ ไม่ดึงแถว",
      main._sync["state"] == "done" and main._sync.get("unchanged") is True and len(fake.uploaded) == n_before)

# a Drive failure is reported, not swallowed
class BadDrive:
    def upload_xlsx(self, *a):
        raise RuntimeError("EOF occurred in violation of protocol")


import db                                                       # noqa: E402
import ingest                                                   # noqa: E402
db.state_set(ingest.XLSX_KEY, "")                               # something changed since
roster._drive = lambda: BadDrive()
c.post("/api/export/sync")
for _ in range(100):
    if main._sync["state"] != "running":
        break
    time.sleep(0.1)
check("Drive ล้ม → สถานะ error พร้อมเหตุผล", main._sync["state"] == "error" and "EOF" in main._sync["error"])

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
