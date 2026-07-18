"""Inbound ingestion — reply / bounce / unsubscribe / complaint handling.

Closes the most important pre-live-send gap (assessment): without this we would
re-contact people who asked to stop (a PECR breach), keep hard-bouncing (trashing
domain reputation), and be unable to compute the bounce rate the graduation policy
requires.

Mirrors the project's provider pattern (LLMProvider / WebsiteResolver): a swappable
`MailboxSource` (inline for tests/dry-run; Gmail for live via gmail.readonly — the
same refresh token as sending once re-minted with both scopes) feeds deterministic,
fully-testable classification + suppression logic. Ingestion is idempotent on the
provider message id, so re-reading the mailbox is safe.

Effect of each inbound message:
  bounce      -> suppress (email) + lead 'bounced'
  unsubscribe -> suppress (email) + lead 'suppressed'   (PECR opt-out, honoured)
  complaint   -> suppress (email) + lead 'suppressed'
  reply       -> lead 'replied'   (no suppression)

CLI:  python -m outreach.inbound            # read the configured mailbox + ingest
"""
from __future__ import annotations
import abc
import json
import re
from typing import Optional

from . import audit, config, db

UNSUB_PHRASES = ("unsubscribe", "opt out", "opt-out", "remove me", "please remove",
                 "stop emailing", "take me off", "do not contact", "no longer wish")
COMPLAINT_PHRASES = ("this is spam", "marked as spam", "report abuse", "abuse report",
                     "feedback loop", "reported as junk")
BOUNCE_SUBJECTS = ("delivery status notification", "undeliverable", "mail delivery failed",
                   "returned mail", "delivery has failed", "failure notice")
BOUNCE_SENDERS = ("mailer-daemon", "postmaster")

SUPPRESS_REASON = {"bounce": "hard bounce", "unsubscribe": "opt-out (PECR)",
                   "complaint": "spam complaint"}


# --------------------------------------------------------------------------- #
#  classification (pure, fully testable)
# --------------------------------------------------------------------------- #
def classify(msg: dict) -> str:
    """Classify a mailbox message into bounce | unsubscribe | complaint | reply.
    Fail-safe: anything that smells like a stop request is treated as such."""
    frm = (msg.get("from_email") or "").lower()
    subj = (msg.get("subject") or "").lower()
    text = f"{subj} {(msg.get('body') or '').lower()}"
    if msg.get("is_ndr") or any(s in frm for s in BOUNCE_SENDERS) \
            or any(s in subj for s in BOUNCE_SUBJECTS):
        return "bounce"
    if any(p in text for p in COMPLAINT_PHRASES):
        return "complaint"
    if any(p in text for p in UNSUB_PHRASES):
        return "unsubscribe"
    return "reply"


# --------------------------------------------------------------------------- #
#  mailbox sources (swappable; inline for tests, Gmail for live — pending)
# --------------------------------------------------------------------------- #
class MailboxSource(abc.ABC):
    @abc.abstractmethod
    def fetch(self) -> list[dict]:
        """Return inbox messages as dicts: {id, from_email, subject, body,
        original_recipient?, is_ndr?, received_at?, raw?}."""


class InlineMailboxSource(MailboxSource):
    """Default for tests / dry-run: returns a supplied list of message dicts."""

    def __init__(self, messages: Optional[list[dict]] = None):
        self._messages = messages or []

    def fetch(self) -> list[dict]:
        return list(self._messages)


def _b64url(data: str) -> str:
    import base64
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
    except Exception:
        return ""


def _walk_parts(payload: dict):
    yield payload
    for p in payload.get("parts") or []:
        yield from _walk_parts(p)


_DSN_RECIPIENT_RE = re.compile(r"(?:Final|Original)-Recipient:.*?;\s*<?([^\s<>]+@[^\s<>]+)", re.I)


def _parse_gmail_message(m: dict) -> dict:
    """Gmail full-format message -> the neutral message dict classify()/ingest()
    consume. DSN (bounce) detection: multipart/report payloads or an embedded
    message/delivery-status part, whose Final-/Original-Recipient names the address
    that actually bounced (the daemon's From never does)."""
    from email.utils import parseaddr

    payload = m.get("payload") or {}
    headers = {h.get("name", "").lower(): h.get("value", "")
               for h in payload.get("headers") or []}
    body, html, original = "", "", None
    is_ndr = "report" in (payload.get("mimeType") or "").lower()
    for part in _walk_parts(payload):
        mt = (part.get("mimeType") or "").lower()
        data = (part.get("body") or {}).get("data")
        if mt == "message/delivery-status":
            is_ndr = True
            if data:
                dm = _DSN_RECIPIENT_RE.search(_b64url(data))
                if dm:
                    original = dm.group(1).strip()
        elif mt == "text/plain" and data and not body:
            body = _b64url(data)
        elif mt == "text/html" and data and not html:
            html = _b64url(data)
    if not body and html:
        body = re.sub(r"<[^>]+>", " ", html)
    return {
        "id": m.get("id"),
        "from_email": parseaddr(headers.get("from", ""))[1],
        "subject": headers.get("subject", ""),
        "body": body[:5000],
        "is_ndr": is_ndr,
        "original_recipient": original or headers.get("x-failed-recipients") or None,
        "received_at": headers.get("date"),
        "raw": {"gmail_id": m.get("id"), "thread_id": m.get("threadId")},
    }


class GmailMailboxSource(MailboxSource):
    """Live read via the Gmail API (gmail.readonly — the send refresh token re-minted
    with both scopes covers it). Read-only and bounded (`newer_than` window + per-run
    cap); ingestion's message-id idempotency makes re-polling the same window safe."""

    QUERY = "in:inbox newer_than:7d"

    def __init__(self, client=None, sender: Optional[str] = None,
                 max_messages: Optional[int] = None):
        self._client = client
        self._sender = sender or config.GMAIL_SENDER
        self._max = max_messages or config.INBOUND_MAX_PER_RUN

    def fetch(self) -> list[dict]:
        import httpx

        from .google_oauth import access_token

        if not self._sender:
            raise RuntimeError("GMAIL_SENDER not configured for the inbound reader")
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30)
        try:
            headers = {"Authorization": f"Bearer {access_token(client=client)}"}
            base = f"https://gmail.googleapis.com/gmail/v1/users/{self._sender}"
            ids: list[str] = []
            page = None
            while len(ids) < self._max:
                params = {"q": self.QUERY, "maxResults": min(100, self._max - len(ids))}
                if page:
                    params["pageToken"] = page
                r = client.get(f"{base}/messages", headers=headers, params=params)
                r.raise_for_status()
                data = r.json() or {}
                ids += [msg["id"] for msg in data.get("messages", []) if msg.get("id")]
                page = data.get("nextPageToken")
                if not page:
                    break
            out: list[dict] = []
            for mid in ids[:self._max]:
                r = client.get(f"{base}/messages/{mid}", headers=headers,
                               params={"format": "full"})
                if r.status_code != 200:
                    continue
                out.append(_parse_gmail_message(r.json()))
            return out
        finally:
            if owns:
                client.close()


def get_source(name: Optional[str] = None, **kwargs) -> MailboxSource:
    name = name or config.INBOUND_SOURCE
    if name == "inline":
        return InlineMailboxSource(**kwargs)
    if name == "gmail":
        return GmailMailboxSource(**kwargs)
    raise ValueError(f"unknown inbound source: {name!r}")


# --------------------------------------------------------------------------- #
#  ingestion (idempotent; writes replies + suppressions + lead state)
# --------------------------------------------------------------------------- #
def _lead_for(cur, email: Optional[str]) -> Optional[str]:
    if not email:
        return None
    cur.execute("select company_number from outreach.enrichment "
                "where lower(contact_email) = lower(%s) limit 1", (email,))
    r = cur.fetchone()
    return r[0] if r else None


def ingest_one(msg: dict, *, cur) -> Optional[str]:
    """Process one message. Returns its kind, or None if skipped (already seen)."""
    mid = msg.get("id")
    if mid:
        cur.execute("select 1 from outreach.replies where message_id=%s", (mid,))
        if cur.fetchone():
            return None  # idempotent: already ingested

    kind = msg.get("kind") or classify(msg)
    # for a bounce the affected address is the ORIGINAL recipient, not the daemon
    target = (msg.get("original_recipient") or msg.get("from_email") or "").lower() or None
    cn = _lead_for(cur, target)

    cur.execute(
        "insert into outreach.replies (company_number, from_email, kind, message_id, raw) "
        "values (%s,%s,%s,%s,%s::jsonb)",
        (cn, msg.get("from_email"), kind, mid, json.dumps(msg.get("raw") or {})))

    if kind in SUPPRESS_REASON:
        cur.execute(
            "insert into outreach.suppressions (email, company_number, reason) values (%s,%s,%s)",
            (target, cn, SUPPRESS_REASON[kind]))
        new_state = "bounced" if kind == "bounce" else "suppressed"
        if cn:
            cur.execute(
                "update outreach.leads set state=%s, updated_at=now() "
                "where company_number=%s and state not in ('suppressed','bounced')",
                (new_state, cn))
    elif kind == "reply" and cn:
        cur.execute(
            "update outreach.leads set state='replied', updated_at=now() "
            "where company_number=%s and state in ('sent','sending','approved')", (cn,))

    if cn:
        audit.record(cn, kind, source="inbound",
                     lawful_basis=audit.LEGITIMATE_INTERESTS,
                     reason=f"inbound {kind} from {msg.get('from_email')}", cur=cur)
    return kind


def ingest(messages: list[dict], *, cur) -> dict:
    counts = {"bounce": 0, "unsubscribe": 0, "complaint": 0, "reply": 0, "skipped": 0}
    for msg in messages:
        kind = ingest_one(msg, cur=cur)
        counts["skipped" if kind is None else kind] += 1
    return counts


def run(*, source: Optional[MailboxSource] = None, cur=None) -> dict:
    source = source or get_source()
    messages = source.fetch()
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    try:
        counts = ingest(messages, cur=cur)
        if own:
            conn.commit()
        return counts
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        if own and conn is not None:
            conn.close()


if __name__ == "__main__":
    print(run())
