# -*- coding: utf-8 -*-
"""Google Drive access for ingest — plus a local-folder stand-in for testing without Drive.

Both expose the same tiny interface:
    list_folders(parent_id) -> [{id, name}]
    list_images(parent_id)  -> [{id, name, mime, url}]
    download(file_id)       -> bytes
    upload_xlsx(parent_id, name, data) -> file id   (overwrites a same-named file)
"""
import io
import json
import os
from pathlib import Path

IMAGE_MIMES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
EXT_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class DriveClient:
    """Service-account client. Share the Inbox/Exports folders with the service account email."""

    def __init__(self, service_account_json: str = None):
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        raw = service_account_json or os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
        info = json.loads(raw) if raw.strip().startswith("{") else json.loads(Path(raw).read_text(encoding="utf-8"))
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"])
        self.svc = build("drive", "v3", credentials=creds, cache_discovery=False)

    def _list(self, q, fields):
        out, token = [], None
        while True:
            resp = self.svc.files().list(
                q=q, fields=f"nextPageToken, files({fields})", pageSize=1000, pageToken=token,
                supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
            out.extend(resp.get("files", []))
            token = resp.get("nextPageToken")
            if not token:
                return out

    def list_folders(self, parent_id):
        rows = self._list(f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
                          "id, name")
        return [{"id": r["id"], "name": r["name"]} for r in rows]

    def list_images(self, parent_id):
        rows = self._list(f"'{parent_id}' in parents and trashed=false", "id, name, mimeType, webViewLink")
        return [{"id": r["id"], "name": r["name"], "mime": r["mimeType"], "url": r.get("webViewLink")}
                for r in rows if r["mimeType"] in IMAGE_MIMES]

    def download(self, file_id) -> bytes:
        from googleapiclient.http import MediaIoBaseDownload
        buf = io.BytesIO()
        req = self.svc.files().get_media(fileId=file_id, supportsAllDrives=True)
        dl = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = dl.next_chunk()
        return buf.getvalue()

    def upload_xlsx(self, parent_id, name, data: bytes) -> str:
        from googleapiclient.http import MediaIoBaseUpload
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=XLSX_MIME, resumable=False)
        existing = self._list(f"'{parent_id}' in parents and name='{name}' and trashed=false", "id")
        if existing:
            fid = existing[0]["id"]
            self.svc.files().update(fileId=fid, media_body=media, supportsAllDrives=True).execute()
            return fid
        meta = {"name": name, "parents": [parent_id], "mimeType": XLSX_MIME}
        return self.svc.files().create(body=meta, media_body=media, fields="id",
                                       supportsAllDrives=True).execute()["id"]


class LocalDrive:
    """Same interface over a local directory tree — for testing ingest without Google."""

    def __init__(self, root):
        self.root = Path(root)

    def list_folders(self, parent_id):
        p = Path(parent_id)
        return [{"id": str(d), "name": d.name} for d in sorted(p.iterdir()) if d.is_dir()]

    def list_images(self, parent_id):
        p = Path(parent_id)
        return [{"id": str(f), "name": f.name, "mime": EXT_MIME[f.suffix.lower()], "url": f.as_uri()}
                for f in sorted(p.iterdir()) if f.is_file() and f.suffix.lower() in EXT_MIME]

    def download(self, file_id) -> bytes:
        return Path(file_id).read_bytes()

    def upload_xlsx(self, parent_id, name, data: bytes) -> str:
        out = Path(parent_id)
        out.mkdir(parents=True, exist_ok=True)
        (out / name).write_bytes(data)
        return str(out / name)
