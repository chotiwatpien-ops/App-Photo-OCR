# -*- coding: utf-8 -*-
"""The login, as it runs in the cloud: the API's self-description is not public, a missing
password closes the app instead of opening it, guessing is slowed down, logging out ends the
session on the server, and changing the password ends every session."""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-auth-")
os.environ.pop("DATABASE_URL", None)
os.environ["RENDER"] = "1"                     # cloud rules, on a throwaway SQLite
os.environ["APP_PASSWORD"] = "correct horse"
sys.path.insert(0, "backend")

import auth                                                     # noqa: E402
import config                                                   # noqa: E402
import main                                                     # noqa: E402
from fastapi.testclient import TestClient                       # noqa: E402

ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


def client():
    return TestClient(main.app, base_url="https://testserver")   # the cookie is Secure in the cloud


web = client()
check("หน้าอธิบาย API (/docs, /openapi.json) ปิดในคลาวด์",
      web.get("/docs").status_code == 404 or "swagger" not in web.get("/docs").text.lower())
check("/openapi.json ไม่เปิดให้ใครก็อ่าน", web.get("/openapi.json").status_code != 200
      or "paths" not in web.get("/openapi.json").text)
r = web.get("/api/health")
check("ทุกคำตอบมีหัวกันฝัง/กันเดาชนิดไฟล์", r.headers.get("x-content-type-options") == "nosniff"
      and r.headers.get("x-frame-options") == "DENY" and "max-age" in r.headers.get("strict-transport-security", ""))
check("ยังไม่ล็อกอิน → เรียก API ไม่ได้", web.get("/api/review-queue/count").status_code == 401)
check("หน้าที่ถูกปฏิเสธก็มีหัวความปลอดภัย", web.get("/api/review-queue/count").headers.get("x-frame-options") == "DENY")

check("รหัสผิด → 401", web.post("/api/login", json={"password": "nope"}).status_code == 401)
r = web.post("/api/login", json={"password": "correct horse"})
check("รหัสถูก → เข้าได้ และคุกกี้เป็น HttpOnly/Secure",
      r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower() and "secure" in r.headers["set-cookie"].lower())
token = web.cookies.get(main.COOKIE)
check("ล็อกอินแล้วเรียก API ได้", web.get("/api/review-queue/count").status_code == 200)

copy = client()
copy.cookies.set(main.COOKIE, token)
check("คุกกี้ที่ถูกคัดลอกไปใช้ได้ก่อนออกจากระบบ", copy.get("/api/review-queue/count").status_code == 200)
web.post("/api/logout")
check("❗ ออกจากระบบแล้ว คุกกี้เดิมใช้ไม่ได้อีก แม้ในเครื่องอื่นที่คัดลอกไป",
      copy.get("/api/review-queue/count").status_code == 401)

other = client()
other.post("/api/login", json={"password": "correct horse"})
check("ออกจากระบบเครื่องหนึ่ง ไม่เตะเครื่องอื่นที่ล็อกอินแยก", other.get("/api/review-queue/count").status_code == 200)
config.APP_PASSWORD = "new password"
check("❗ เปลี่ยนรหัสผ่าน → ทุก session เดิมหมดอายุทันที", other.get("/api/review-queue/count").status_code == 401)

main._throttle = auth.Throttle(limit=3, window=300)
guess = client()
codes = [guess.post("/api/login", json={"password": f"x{i}"}).status_code for i in range(4)]
check("เดารหัสผิดเกินกำหนด → ถูกพักไว้ (429)", codes == [401, 401, 401, 429], codes)
check("ระหว่างพัก แม้รหัสถูกก็ยังรอ", guess.post("/api/login", json={"password": "new password"}).status_code == 429)
t = auth.Throttle(limit=2, window=10)
t.failed(now=0); t.failed(now=1)
check("พักครบเวลาแล้วเดาใหม่ได้", t.wait(now=5) > 0 and t.wait(now=12) == 0)

config.APP_PASSWORD = ""
r = client().get("/api/review-queue/count")
check("❗ ลืมตั้งรหัสผ่านในคลาวด์ → แอปปิด ไม่เปิดโล่ง", r.status_code == 503 and "APP_PASSWORD" in r.json()["detail"], r.status_code)
check("ตรวจสุขภาพยังตอบได้ (Render ใช้ดูว่าแอปขึ้นไหม)", client().get("/api/health").status_code == 200)

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
