"""Gmail API send backend (users.messages.send), shared by outreach and operator mail.

Carries NO guardrail logic on purpose: PECR gates (G-SEND, kill switch, suppression,
caps) belong to the callers — send.py enforces them for outreach, while operator/
transactional mail (alerts, digests) must keep working when the kill switch blocks
outreach. Wire behaviour mirrors the original inline sender: RFC 822 message,
base64url-encoded, posted as {'raw': ...}.
"""
from __future__ import annotations
import base64
from email.message import EmailMessage

from . import config, google_oauth
from .google_oauth import OAuthNotConfigured

SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/{sender}/messages/send"


def send_message(sender: str, to_email: str, subject: str, body: str, *,
                 html: str | None = None, client=None) -> str:
    """Send one email as `sender` (falls back to config.GMAIL_SENDER). Plain text
    always; `html` adds a multipart/alternative part (clients prefer it, and the
    text part remains the audited source). Returns the Gmail message id."""
    sender = sender or config.GMAIL_SENDER
    if not sender:
        raise OAuthNotConfigured("no Gmail sender configured")
    access = google_oauth.access_token(client=client)
    msg = EmailMessage()
    msg["To"], msg["From"], msg["Subject"] = to_email, sender, (subject or "")
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    if client is None:
        import httpx
        client = httpx
    resp = client.post(
        SEND_URL.format(sender=sender),
        headers={"Authorization": f"Bearer {access}"},
        json={"raw": raw},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("id", "gmail-accepted")
