# -*- coding: utf-8 -*-
"""The single shared password, its session cookie, and a brake on guessing it.

A session cookie used to be the signed constant "ok": logging out only deleted it from one
browser, and a copied cookie stayed valid for 30 days whatever happened. Now each login gets its
own id, signed together with a tag of the current password:
  - changing APP_PASSWORD ends every session at once;
  - logging out revokes that one session, on the server, not only in the browser.

    python auth.py   (nothing to run; imported by main.py)
"""
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import deque

from itsdangerous import BadSignature, TimestampSigner

import config

SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
REVOKED_KEY = "revoked_sessions"
REVOKED_KEEP = 500                    # ids kept; older ones have expired by then anyway
_signer = TimestampSigner(config.SECRET_KEY)


def password_required() -> bool:
    """True when a login is needed. In the cloud a missing password is a mistake, not an open
    door: the app refuses every request (see password_missing) instead of serving it to anyone."""
    return bool(config.APP_PASSWORD) or config.IS_CLOUD


def password_missing() -> bool:
    return config.IS_CLOUD and not config.APP_PASSWORD


def _tag() -> str:
    return hashlib.sha256(f"{config.APP_PASSWORD}|{config.SECRET_KEY}".encode()).hexdigest()[:12]


def password_ok(given) -> bool:
    return bool(config.APP_PASSWORD) and hmac.compare_digest(str(given or "").encode(), config.APP_PASSWORD.encode())


def new_token() -> str:
    return _signer.sign(f"{_tag()}.{secrets.token_urlsafe(12)}").decode()


def session_id(token):
    """The session id inside a valid cookie, or None."""
    if not token:
        return None
    try:
        raw = _signer.unsign(token, max_age=SESSION_MAX_AGE).decode()
    except BadSignature:
        return None
    tag, _, sid = raw.partition(".")
    if not sid or not hmac.compare_digest(tag, _tag()):
        return None
    return None if sid in _revoked() else sid


# revoked ids live in app_state so every web process and restart agrees; read at most once a minute
_cache = {"at": 0.0, "ids": frozenset()}
_lock = threading.Lock()


def _revoked():
    import db
    now = time.monotonic()
    if now - _cache["at"] > 60:
        try:
            ids = frozenset(json.loads(db.state_get(REVOKED_KEY) or "[]"))
        except Exception:  # noqa: BLE001 — an unreadable list keeps the last one it read
            ids = _cache["ids"]
        _cache.update(at=now, ids=ids)
    return _cache["ids"]


def revoke(sid) -> None:
    import db
    if not sid:
        return
    with _lock:
        try:
            ids = json.loads(db.state_get(REVOKED_KEY) or "[]")
        except ValueError:
            ids = []
        ids = (ids + [sid])[-REVOKED_KEEP:]
        db.state_set(REVOKED_KEY, json.dumps(ids))
        _cache.update(at=time.monotonic(), ids=frozenset(ids))


class Throttle:
    """At most `limit` wrong passwords in `window` seconds, counted for the whole app.

    Counted globally, not per address: behind Render every request comes from its proxy, and the
    forwarded-for header is whatever the client chose to send. One person uses this app, so a
    lock that also catches them for a few minutes during an attack is the right trade."""

    def __init__(self, limit=10, window=300):
        self.limit, self.window = limit, window
        self.fails = deque()
        self.lock = threading.Lock()

    def _trim(self, now):
        while self.fails and now - self.fails[0] > self.window:
            self.fails.popleft()

    def wait(self, now=None):
        """Seconds until a guess is allowed again, 0 when it is allowed now."""
        now = time.monotonic() if now is None else now
        with self.lock:
            self._trim(now)
            if len(self.fails) < self.limit:
                return 0
            return int(self.window - (now - self.fails[0])) + 1

    def failed(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            self._trim(now)
            self.fails.append(now)
