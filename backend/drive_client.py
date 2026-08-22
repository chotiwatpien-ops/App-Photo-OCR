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
import threading
from pathlib import Path

IMAGE_MIMES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
EXT_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class DriveClient:
    """Service-account client. Share the Inbox/Exports folders with the service account email."""

    SCOPES = ["https://www.googleapis.com/auth/drive"]

    def __init__(self, service_account_json: str = None, oauth_token_json: str = None):
        """Prefers a user OAuth token (can WRITE to a personal Drive); falls back to a service
        account (read-only in practice — Google gives service accounts no storage quota)."""
        from googleapiclient.discovery import build

        self._local = threading.local()  # googleapiclient/httplib2 objects are not thread-safe
        creds = None
        tok = oauth_token_json or os.environ.get("DRIVE_OAUTH_TOKEN_JSON")
        if tok:
            from google.oauth2.credentials import Credentials
            info = json.loads(tok) if tok.strip().startswith("{") else json.loads(Path(tok).read_text(encoding="utf-8"))
            creds = Credentials.from_authorized_user_info(info, self.SCOPES)
            self.mode = "oauth"
        else:
            from google.oauth2 import service_account
            raw = service_account_json or os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
            info = json.loads(raw) if raw.strip().startswith("{") else json.loads(Path(raw).read_text(encoding="utf-8"))
            creds = service_account.Credentials.from_service_account_info(info, scopes=self.SCOPES)
            self.mode = "service_account"
        self._creds = creds
        self._build = build

    @property
    def svc(self):
        """A Drive API client per thread, so uploads/downloads can run in parallel safely."""
        s = getattr(self._local, "svc", None)
        if s is None:
            s = self._local.svc = self._build("drive", "v3", credentials=self._creds, cache_discovery=False)
        return s

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

    def ensure_folder(self, parent_id, name) -> str:
        """Id of child folder `name`, created if missing."""
        q = (f"'{parent_id}' in parents and name='{name}' and "
             f"mimeType='application/vnd.google-apps.folder' and trashed=false")
        found = self._list(q, "id")
        if found:
            return found[0]["id"]
        meta = {"name": name, "parents": [parent_id], "mimeType": "application/vnd.google-apps.folder"}
        return self.svc.files().create(body=meta, fields="id", supportsAllDrives=True).execute()["id"]

    def upload_file(self, parent_id, name, data: bytes, mime: str) -> str:
        """Create or overwrite `name` inside the folder."""
        from googleapiclient.http import MediaIoBaseUpload
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime, resumable=False)
        existing = self._list(f"'{parent_id}' in parents and name='{name}' and trashed=false", "id")
        if existing:
            fid = existing[0]["id"]
            self.svc.files().update(fileId=fid, media_body=media, supportsAllDrives=True).execute()
            return fid
        meta = {"name": name, "parents": [parent_id], "mimeType": mime}
        return self.svc.files().create(body=meta, media_body=media, fields="id",
                                       supportsAllDrives=True).execute()["id"]

    def upload_xlsx(self, parent_id, name, data: bytes) -> str:
        return self.upload_file(parent_id, name, data, XLSX_MIME)


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

    def ensure_folder(self, parent_id, name) -> str:
        p = Path(parent_id) / name
        p.mkdir(parents=True, exist_ok=True)
        return str(p)

    def upload_file(self, parent_id, name, data: bytes, mime: str) -> str:
        out = Path(parent_id)
        out.mkdir(parents=True, exist_ok=True)
        (out / name).write_bytes(data)
        return str(out / name)

    def upload_xlsx(self, parent_id, name, data: bytes) -> str:
        return self.upload_file(parent_id, name, data, XLSX_MIME)
