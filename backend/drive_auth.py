# -*- coding: utf-8 -*-
"""One-time Google Drive sign-in as a real user (needed for WRITING to a personal Drive —
service accounts have no storage quota there).

Steps (once):
  1. Google Cloud console → APIs & Services → OAuth consent screen → External → fill name/email
     → PUBLISH (keep it unverified; "In production" stops the 7-day token expiry of Testing mode)
  2. Credentials → + Create credentials → OAuth client ID → Desktop app → Download JSON
     → save as  oauth_client.json  in the project folder
  3. python backend/drive_auth.py   → browser opens → sign in with the Drive account → Allow
     → writes  drive_token.json  (refresh token). Keep it private (gitignored).

Cloud (GitHub Actions): put the CONTENT of drive_token.json in secret DRIVE_OAUTH_TOKEN_JSON.
"""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CLIENT = BASE / "oauth_client.json"
TOKEN = BASE / "drive_token.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if not CLIENT.exists():
        sys.exit(f"ไม่พบ {CLIENT.name} — ดาวน์โหลด OAuth client (Desktop app) จาก Google Cloud แล้ววางไว้ที่ {BASE}")
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline",
                                  authorization_prompt_message="เปิดเบราว์เซอร์เพื่อล็อกอิน Google Drive...")
    data = json.loads(creds.to_json())
    if not data.get("refresh_token"):
        sys.exit("ไม่ได้ refresh token — ลองใหม่ และกด 'Allow' ทุกข้อ")
    TOKEN.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ บันทึก {TOKEN.name} แล้ว (บัญชี: ดูใน Drive ที่เพิ่งล็อกอิน) — ingest จะใช้ token นี้เขียนไฟล์ลง Drive")


if __name__ == "__main__":
    main()
