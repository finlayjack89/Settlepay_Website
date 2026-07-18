"""Shared Google OAuth token exchange (refresh token -> short-lived access token).

Single home for the credential check + token POST so send, alerts and digests all
refresh identically. WHY per-user OAuth and no service account / domain-wide
delegation: the refresh token is inherently mailbox-scoped — it only works for the
single mailbox that consented, so cross-mailbox sending is impossible by
construction. The refresh token is a durable secret: it lives in .env only and
must NEVER be logged or echoed in errors.
"""
from __future__ import annotations

from . import config

TOKEN_URL = "https://oauth2.googleapis.com/token"


class OAuthNotConfigured(RuntimeError):
    pass


def access_token(*, client=None) -> str:
    """Exchange the configured refresh token for a fresh access token."""
    cid, secret, refresh = config.GOOGLE_CLIENT_ID, config.GOOGLE_CLIENT_SECRET, config.GOOGLE_REFRESH_TOKEN
    if not all([cid, secret, refresh]):
        raise OAuthNotConfigured("Google OAuth credentials not configured")
    if client is None:
        import httpx
        client = httpx
    resp = client.post(
        TOKEN_URL,
        data={"client_id": cid, "client_secret": secret,
              "refresh_token": refresh, "grant_type": "refresh_token"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]
