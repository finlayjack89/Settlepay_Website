"""Inbound ingestion — reply / bounce / unsubscribe / complaint handling.

Closes the most important pre-live-send gap (assessment): without this we would
re-contact people who asked to stop (a PECR breach), keep hard-bouncing (trashing
domain reputation), and be unable to compute the bounce rate the graduation policy
requires.

Mirrors the project's provider pattern (LLMProvider / WebsiteResolver): a swappable
`MailboxSource` (live Microsoft Graph read, or an inline source for tests/dry-run)
feeds deterministic, fully-testable classification + suppression logic. Ingestion is
idempotent on the provider message id, so re-reading the mailbox is safe.

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
#  mailbox sources (swappable; inline for tests, Graph for live)
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


class GraphMailboxSource(MailboxSource):
    """Live read via Microsoft Graph (app-only, needs Mail.Read). Only used when
    GRAPH_* credentials are configured; never required for the build/tests."""

    def __init__(self, inbox: Optional[str] = None, *, top: int = 50):
        self.inbox = inbox or config.GRAPH_SENDER
        self.top = top

    def fetch(self) -> list[dict]:
        import httpx
        tenant, cid, secret = config.GRAPH_TENANT_ID, config.GRAPH_CLIENT_ID, config.GRAPH_CLIENT_SECRET
        if not all([tenant, cid, secret, self.inbox]):
            raise RuntimeError("Microsoft Graph credentials / inbox not configured")
        tok = httpx.post(
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            data={"client_id": cid, "client_secret": secret,
                  "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"},
            timeout=30)
        tok.raise_for_status()
        access = tok.json()["access_token"]
        r = httpx.get(
            f"https://graph.microsoft.com/v1.0/users/{self.inbox}/mailFolders/inbox/messages",
            headers={"Authorization": f"Bearer {access}"},
            params={"$top": self.top, "$select": "id,subject,from,bodyPreview,toRecipients,receivedDateTime"},
            timeout=30)
        r.raise_for_status()
        out = []
        for m in r.json().get("value", []):
            sender = (((m.get("from") or {}).get("emailAddress") or {}).get("address") or "").lower()
            out.append({
                "id": m.get("id"),
                "from_email": sender,
                "subject": m.get("subject") or "",
                "body": m.get("bodyPreview") or "",
                "received_at": m.get("receivedDateTime"),
                "raw": {"id": m.get("id")},
            })
        return out


def get_source(name: Optional[str] = None, **kwargs) -> MailboxSource:
    name = name or config.INBOUND_SOURCE
    if name == "inline":
        return InlineMailboxSource(**kwargs)
    if name == "graph":
        return GraphMailboxSource(**kwargs)
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
