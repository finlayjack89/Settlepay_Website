"""Console auth primitives: argon2id password, signed session cookie, CSRF,
login rate limiting, and Cloud Scheduler OIDC verification for POST /tick.

Pure primitives — the FastAPI wiring (middleware, routes, cookie handling) lives
in web.py. Nothing here touches the DB or the network except the default /tick
token verifier, which fetches Google's public certs.

LOUD WARNING — OPEN MODE: when `auth_configured()` is False (SESSION_SECRET or
CONSOLE_PASSWORD_HASH unset) the console runs OPEN, with no login at all. That is
deliberate for local dev against a .env without console secrets; the middleware
in web.py checks `auth_configured()` and skips every auth gate. Both values MUST
be set on any deployment that is reachable from the internet.

The in-memory rate limiter and session scheme are only valid because the Cloud
Run service runs at max-instances=1: one process holds all state, so there is no
cross-instance store to coordinate with.
"""
from __future__ import annotations
import hashlib
import hmac
import time
from collections import deque
from typing import Callable, Optional

import httpx
from argon2 import PasswordHasher
from itsdangerous import URLSafeTimedSerializer

from . import config

COOKIE_NAME = "ops_session"

_hasher = PasswordHasher()  # argon2id with library defaults


def auth_configured() -> bool:
    """True only when BOTH SESSION_SECRET and CONSOLE_PASSWORD_HASH are set.

    False => the console is OPEN (no login, no CSRF, no rate limit) — local dev
    only. The middleware in web.py consults this before enforcing anything."""
    return bool(config.SESSION_SECRET and config.CONSOLE_PASSWORD_HASH)


def hash_password(pw: str) -> str:
    return _hasher.hash(pw)


def verify_password(pw: str) -> bool:
    if not config.CONSOLE_PASSWORD_HASH:
        return False
    try:
        return _hasher.verify(config.CONSOLE_PASSWORD_HASH, pw)
    except Exception:
        return False


def _serializer() -> URLSafeTimedSerializer:
    # built per call so a rotated SESSION_SECRET (or a test monkeypatch) takes effect
    return URLSafeTimedSerializer(config.SESSION_SECRET, salt="ops-session")


def create_session() -> str:
    return _serializer().dumps({"u": "operator"})


def verify_session(token: Optional[str]) -> bool:
    if not token or not config.SESSION_SECRET:
        return False
    try:
        payload = _serializer().loads(token, max_age=config.SESSION_TTL_HOURS * 3600)
        return payload.get("u") == "operator"
    except Exception:
        return False


def csrf_token(session_token: str) -> str:
    """Derive the CSRF token from the session token — no server-side state, and it
    rotates automatically with every new session."""
    return hmac.new(config.SESSION_SECRET.encode(),
                    b"csrf:" + session_token.encode(), hashlib.sha256).hexdigest()


def verify_csrf(session_token: Optional[str], provided: Optional[str]) -> bool:
    if not session_token or not provided or not config.SESSION_SECRET:
        return False
    try:
        return hmac.compare_digest(csrf_token(session_token), provided)
    except Exception:
        return False


class LoginRateLimiter:
    """Sliding-window limit on failed logins, keyed by client IP.

    In-memory on purpose: Cloud Run runs this service at max-instances=1, so a
    single process sees every request and a dict of deques is sufficient. An
    instance restart forgets the counts — acceptable for a single-operator tool."""

    def __init__(self, max_attempts: int = 5, window_secs: int = 300):
        self.max_attempts = max_attempts
        self.window_secs = window_secs
        self._failures: dict[str, deque[float]] = {}

    def _prune(self, key: str) -> None:
        now = time.monotonic()
        dq = self._failures.get(key)
        while dq and now - dq[0] > self.window_secs:
            dq.popleft()
        if dq is not None and not dq:
            self._failures.pop(key, None)

    def allow(self, key: str) -> bool:
        self._prune(key)
        return len(self._failures.get(key, ())) < self.max_attempts

    def record_failure(self, key: str) -> None:
        self._failures.setdefault(key, deque()).append(time.monotonic())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


class _HttpxResponse:
    """google.auth.transport.Response over an httpx response."""

    def __init__(self, raw: httpx.Response):
        self.status = raw.status_code
        self.headers = raw.headers
        self.data = raw.content


class _HttpxRequest:
    """google.auth.transport.Request backed by httpx. The venv ships httpx, not
    requests, so google.auth.transport.requests.Request may be unimportable;
    google-auth only needs this callable to fetch its signing certs."""

    def __call__(self, url, method="GET", body=None, headers=None, timeout=30, **kwargs):
        resp = httpx.request(method, url, content=body, headers=headers,
                             timeout=timeout or 30)
        return _HttpxResponse(resp)


def _transport_request():
    try:
        from google.auth.transport.requests import Request
        return Request()
    except ImportError:
        return _HttpxRequest()


def _google_verifier(token: str) -> dict:
    from google.oauth2 import id_token
    return id_token.verify_oauth2_token(token, _transport_request(),
                                        audience=config.TICK_AUDIENCE)


def verify_tick_request(authorization_header: Optional[str], *,
                        verifier: Optional[Callable[[str], dict]] = None) -> bool:
    """True only for a valid Cloud Scheduler OIDC token: `Authorization: Bearer
    <token>` whose signature, audience (TICK_AUDIENCE) and verified email
    (TICK_INVOKER_SA) all check out. False on ANY failure — including unset
    config — and never raises, so /tick can 403 without a try/except.
    `verifier` injects a fake in tests; production uses Google's cert check."""
    if not (config.TICK_INVOKER_SA and config.TICK_AUDIENCE):
        return False
    if not authorization_header or not authorization_header.startswith("Bearer "):
        return False
    token = authorization_header[len("Bearer "):].strip()
    if not token:
        return False
    try:
        claims = (verifier or _google_verifier)(token)
        return bool(claims.get("email_verified")) and claims.get("email") == config.TICK_INVOKER_SA
    except Exception:
        return False
