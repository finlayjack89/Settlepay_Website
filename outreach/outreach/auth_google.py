"""One-off Google OAuth bootstrap for the Gmail send + inbound mailbox.

Runs the interactive consent flow ONCE (loopback redirect) with the gmail.send AND
gmail.readonly scopes and prints the refresh token, so GOOGLE_REFRESH_TOKEN can be
set in .env without wiring OAuth by hand. One consent covers both outbound sending
and the inbound reply/bounce reader. The OAuth app is "Internal" in our own
Workspace, so no Google verification is needed.

The refresh token is durable and mailbox-scoped: it only works for the single mailbox
that consents — cross-mailbox sending is impossible by construction (no service account
/ domain-wide delegation).

NOTE: a token minted before the readonly scope was added is send-only — re-run this
bootstrap once to mint a token carrying both scopes.

  python -m outreach auth-google        # sign in AS the sending mailbox when prompted
"""
from __future__ import annotations
import http.server
import urllib.parse
import webbrowser

import httpx

from . import config

SCOPE = "https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly"
AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"


def _catch_code(port: int) -> str:
    """Serve exactly one loopback redirect and return its ?code=."""
    holder: dict[str, str] = {}

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.urlparse(self.path).query
            holder["code"] = urllib.parse.parse_qs(query).get("code", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h3>SettlePay: authorised. You can close this tab.</h3>")

        def log_message(self, *args):  # keep the console quiet
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), _Handler)
    server.handle_request()
    return holder.get("code", "")


def run(port: int = 8765) -> str:
    cid, secret = config.GOOGLE_CLIENT_ID, config.GOOGLE_CLIENT_SECRET
    if not cid or not secret:
        raise SystemExit("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in outreach/.env first.")
    redirect = f"http://localhost:{port}/"
    url = f"{AUTH_URI}?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code",
        "scope": SCOPE, "access_type": "offline", "prompt": "consent"})
    print(f"Opening the Google consent screen — sign in AS the sending mailbox.\n{url}\n")
    webbrowser.open(url)
    code = _catch_code(port)
    if not code:
        raise SystemExit("No authorization code received.")
    r = httpx.post(TOKEN_URI, data={
        "code": code, "client_id": cid, "client_secret": secret,
        "redirect_uri": redirect, "grant_type": "authorization_code"}, timeout=30)
    r.raise_for_status()
    refresh = r.json().get("refresh_token")
    if not refresh:
        raise SystemExit("No refresh_token returned — re-run (needs access_type=offline & prompt=consent).")
    print("\nSuccess. Add this to outreach/.env (never commit it):\n")
    print(f"GOOGLE_REFRESH_TOKEN={refresh}\n")
    return refresh


if __name__ == "__main__":
    run()
