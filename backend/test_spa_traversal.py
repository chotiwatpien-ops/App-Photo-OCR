# -*- coding: utf-8 -*-
"""The SPA catch-all serves only what is inside the built folder (2026-09-11).

That route answers without a cookie — the auth gate only guards paths under /api/ — and it used
to hand `FRONTEND_DIST / path` straight to FileResponse. A client normalises a plain '..' away,
but '%2e%2e' and '..%2f' survive it, arrive here decoded, and walked out of the folder:
'/%2e%2e/%2e%2e/service_account.json' returned the Drive key, and on the server
'/%2e%2e/%2e%2e/%2e%2e/%2e%2e/proc/self/environ' the database URL and every API key at once.

A stand-in file outside the built folder plays the secret; nothing real is read.
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-spa-")
DIST = os.path.join(WORK, "frontend", "dist")
os.makedirs(os.path.join(DIST, "assets"))
open(os.path.join(DIST, "index.html"), "w", encoding="utf-8").write("INDEX")
open(os.path.join(DIST, "assets", "app.js"), "w", encoding="utf-8").write("APP")
open(os.path.join(WORK, "secret_stand_in.json"), "w", encoding="utf-8").write("STAND-IN-SECRET")

os.environ["PHOTO_OCR_DATA"] = WORK
os.environ["FRONTEND_DIST"] = DIST
os.environ.pop("DATABASE_URL", None)
os.environ.pop("APP_PASSWORD", None)          # the gate is off; the route must still hold
sys.path.insert(0, "backend")

import config                                                    # noqa: E402

config.FRONTEND_DIST = __import__("pathlib").Path(DIST)

import main                                                      # noqa: E402
from fastapi.testclient import TestClient                        # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


c = TestClient(main.app)
LEAK = "STAND-IN-SECRET"

check("ไฟล์ใน dist ยังเสิร์ฟได้", c.get("/index.html").text == "INDEX")
check("ไฟล์ในโฟลเดอร์ย่อยยังเสิร์ฟได้", c.get("/assets/app.js").text == "APP")
check("เส้นทางที่แอปจัดการเองได้ index กลับไป", c.get("/review").text == "INDEX")

for probe in ("/../secret_stand_in.json",
              "/../../secret_stand_in.json",
              "/%2e%2e/secret_stand_in.json",
              "/%2e%2e/%2e%2e/secret_stand_in.json",
              "/..%2fsecret_stand_in.json",
              "/..%2f..%2fsecret_stand_in.json",
              "/%2E%2E/%2E%2E/secret_stand_in.json",
              "/assets/../../secret_stand_in.json",
              "/assets/%2e%2e/%2e%2e/secret_stand_in.json"):
    r = c.get(probe)
    check(f"ออกนอกโฟลเดอร์ไม่ได้: {probe}", LEAK not in r.text)

check("ชื่อไฟล์ที่ระบบไฟล์ไม่รับ ไม่ทำให้ล่ม", c.get("/%00bad").status_code in (200, 400, 404))

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
