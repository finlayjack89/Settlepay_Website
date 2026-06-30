"""Phase G — send (Gmail API). HARD-GATED, OFF by default.

Live cold sending is DISABLED until a human clears gate G-SEND
(`config.send_enabled()` == G_SEND truthy). The loop can NEVER set G_SEND. Until
then this runs dry-run / test-mailbox only and records nothing as a live send.

EVERY send (dry-run or live) passes ALL guardrails first, in order:
  1. global kill switch          (config.KILL_SWITCH)
  2. individual/unknown block    (only corporate subscribers may be contacted)
  3. check_suppression           (outreach.suppressions ∪ inbound enquirers)
  4. risky-tier opt-in           (catch-all contacts need config.RISKY_SEND_ENABLED)
  5. per-inbox daily cap         (config.PER_INBOX_DAILY_CAP; Google tolerates a higher
                                  cold limit ~18-22/inbox/day than M365's 3-5 — config-driven)
What gets sent is body_final (the human-approved text), never body_original.

Backend: Gmail API users.messages.send, per-user OAuth (refresh token), from a Google
Workspace secondary domain. The guardrail wrapper around the backend is unchanged.
"""
from __future__ import annotations
import datetime
from typing import Optional

from . import audit, config, db, sequence
from .firewall import check_suppression
from .states import LeadState, SubscriberClass


class SendRefused(Exception):
    pass


def _kill_switch_on() -> bool:
    return str(config.KILL_SWITCH).strip().lower() in {"1", "true", "yes", "on"}


def _gmail_send(sender: str, to_email: str, subject: str, body: str) -> str:
    """Real Gmail API users.messages.send (per-user OAuth + refresh token). Only ever
    reached on a LIVE send, which itself requires G-SEND cleared — so it never runs
    during the build. WHY no service account / domain-wide delegation: the refresh
    token is inherently mailbox-scoped — it only works for the single mailbox that
    consented, so cross-mailbox sending is impossible by construction. Returns the
    Gmail message id."""
    import base64
    from email.message import EmailMessage

    import httpx

    cid, secret, refresh = config.GOOGLE_CLIENT_ID, config.GOOGLE_CLIENT_SECRET, config.GOOGLE_REFRESH_TOKEN
    sender = sender or config.GMAIL_SENDER
    if not all([cid, secret, refresh, sender]):
        raise SendRefused("Gmail API credentials not configured")
    # refresh token -> short-lived access token, fresh each run
    tok = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={"client_id": cid, "client_secret": secret,
              "refresh_token": refresh, "grant_type": "refresh_token"},
        timeout=30,
    )
    tok.raise_for_status()
    access = tok.json()["access_token"]
    # build an RFC 822 (MIME) message and base64url-encode it
    msg = EmailMessage()
    msg["To"], msg["From"], msg["Subject"] = to_email, sender, (subject or "")
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    r = httpx.post(
        f"https://gmail.googleapis.com/gmail/v1/users/{sender}/messages/send",
        headers={"Authorization": f"Bearer {access}"},
        json={"raw": raw},
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("id", "gmail-accepted")


def send_one(draft_id, *, mode: str = "dry_run", inbox: Optional[str] = None, cur) -> dict:
    inbox = inbox or config.GMAIL_SENDER or "test@getsettlepay.uk"

    cur.execute(
        "select d.company_number, d.subject, d.body_final, d.status, "
        "       l.subscriber_class::text, l.state::text, e.contact_email, e.contact_tier "
        "from outreach.drafts d "
        "join outreach.leads l on l.company_number = d.company_number "
        "left join outreach.enrichment e on e.company_number = d.company_number "
        "where d.id = %s", (draft_id,))
    row = cur.fetchone()
    if not row:
        raise SendRefused(f"draft {draft_id} not found")
    cn, subject, body_final, status, sub, lead_state, email, tier = row

    # only an approved draft with a non-empty body_final may be sent
    if status != "approved":
        raise SendRefused(f"draft not approved ({status})")
    if not body_final or not body_final.strip():
        raise SendRefused("no body_final to send")

    # ---- GUARDRAILS (enforced for dry-run AND live) ----
    if _kill_switch_on():
        raise SendRefused("global kill switch is ON")
    if sub != SubscriberClass.CORPORATE.value:
        raise SendRefused(f"individual/unknown subscriber blocked ({sub})")
    if not email:
        raise SendRefused("no contact email")
    if check_suppression(email=email, company_number=cn, cur=cur):
        raise SendRefused("suppressed / existing enquirer")
    # risky (catch-all) contacts are unconfirmable — sending needs a separate opt-in
    # on top of G-SEND, so a routine batch never sprays catch-all mailboxes
    if tier == "risky" and not config.RISKY_SEND_ENABLED:
        raise SendRefused("risky (catch-all) contact — set RISKY_SEND_ENABLED to send")
    # warm-up-aware per-inbox daily cap: ramp a new sending mailbox up gradually
    # (deliverability) — effective cap = min(steady ceiling, today's warm-up cap).
    cur.execute("select min(created_at::date) from outreach.sends "
                "where from_inbox = %s and mode = 'live'", (inbox,))
    first_live = cur.fetchone()[0]
    warmup_day = ((datetime.date.today() - first_live).days + 1) if first_live else 1
    effective_cap = min(config.PER_INBOX_DAILY_CAP, sequence.warmup_cap(warmup_day))
    cur.execute(
        "select count(*) from outreach.sends "
        "where from_inbox = %s and created_at::date = current_date "
        "and status in ('sent', 'dry_run_ok')", (inbox,))
    if cur.fetchone()[0] >= effective_cap:
        raise SendRefused(f"per-inbox daily cap reached ({effective_cap}; warm-up day {warmup_day})")

    # ---- LIVE gate: never send live unless a human cleared G-SEND ----
    if mode == "live":
        if not config.send_enabled():
            raise SendRefused("live send disabled — gate G-SEND not cleared (G_SEND unset)")
        provider_id = _gmail_send(inbox, email, subject or "", body_final)
        send_mode, send_status = "live", "sent"
    else:
        provider_id, send_mode, send_status = None, "dry_run", "dry_run_ok"

    cur.execute(
        "insert into outreach.sends "
        "(draft_id, company_number, to_email, from_inbox, mode, status, provider_message_id) "
        "values (%s,%s,%s,%s,%s,%s,%s)",
        (draft_id, cn, email, inbox, send_mode, send_status, provider_id))

    if mode == "live":
        cur.execute("update outreach.leads set state='sent', updated_at=now() where company_number=%s", (cn,))
        cur.execute("update outreach.drafts set status='sent' where id=%s", (draft_id,))

    audit.record(cn, ("sent" if mode == "live" else "dry_run_send"), source="send",
                 lawful_basis=audit.LEGITIMATE_INTERESTS,
                 reason=f"mode={send_mode} inbox={inbox} -> {send_status}", cur=cur)
    return {"draft_id": str(draft_id), "company_number": cn, "mode": send_mode,
            "status": send_status, "to": email}


def run(*, mode: str = "dry_run", inbox: Optional[str] = None, cur=None) -> list[dict]:
    """Attempt to send every approved draft (dry-run by default). Refusals are
    recorded as skips, not raised, so one bad lead doesn't halt the batch."""
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    results: list[dict] = []
    try:
        cur.execute("select id from outreach.drafts where status='approved' order by created_at")
        for (draft_id,) in cur.fetchall():
            try:
                results.append(send_one(draft_id, mode=mode, inbox=inbox, cur=cur))
            except SendRefused as e:
                results.append({"draft_id": str(draft_id), "refused": str(e)})
        if own:
            conn.commit()
        return results
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        if own and conn is not None:
            conn.close()


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "dry_run"
    for r in run(mode=mode):
        print(r)
