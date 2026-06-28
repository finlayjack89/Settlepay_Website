"""Phase G — send (Microsoft Graph). HARD-GATED, OFF by default.

Live cold sending is DISABLED until a human clears gate G-SEND
(`config.send_enabled()` == G_SEND truthy). The loop can NEVER set G_SEND. Until
then this runs dry-run / test-mailbox only and records nothing as a live send.

EVERY send (dry-run or live) passes ALL guardrails first, in order:
  1. global kill switch          (config.KILL_SWITCH)
  2. individual/unknown block    (only corporate subscribers may be contacted)
  3. check_suppression           (outreach.suppressions ∪ inbound enquirers)
  4. per-inbox daily cap         (config.PER_INBOX_DAILY_CAP, 3-5)
What gets sent is body_final (the human-approved text), never body_original.
"""
from __future__ import annotations
from typing import Optional

from . import audit, config, db
from .firewall import check_suppression
from .states import LeadState, SubscriberClass


class SendRefused(Exception):
    pass


def _kill_switch_on() -> bool:
    return str(config.KILL_SWITCH).strip().lower() in {"1", "true", "yes", "on"}


def _graph_send(inbox: str, to_email: str, subject: str, body: str) -> str:
    """Real Microsoft Graph sendMail (app-only). Only ever reached on a LIVE send,
    which itself requires G-SEND cleared — so it never runs during the build.
    Returns a provider message id."""
    import httpx

    tenant, client_id, secret = config.GRAPH_TENANT_ID, config.GRAPH_CLIENT_ID, config.GRAPH_CLIENT_SECRET
    if not all([tenant, client_id, secret, inbox]):
        raise SendRefused("Microsoft Graph credentials not configured")
    tok = httpx.post(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data={"client_id": client_id, "client_secret": secret,
              "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"},
        timeout=30,
    )
    tok.raise_for_status()
    access = tok.json()["access_token"]
    r = httpx.post(
        f"https://graph.microsoft.com/v1.0/users/{inbox}/sendMail",
        headers={"Authorization": f"Bearer {access}"},
        json={"message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to_email}}],
        }, "saveToSentItems": True},
        timeout=30,
    )
    r.raise_for_status()
    return r.headers.get("request-id", "graph-accepted")


def send_one(draft_id, *, mode: str = "dry_run", inbox: Optional[str] = None, cur) -> dict:
    inbox = inbox or config.GRAPH_SENDER or "test@settlepayhq.uk"

    cur.execute(
        "select d.company_number, d.subject, d.body_final, d.status, "
        "       l.subscriber_class::text, l.state::text, e.contact_email "
        "from outreach.drafts d "
        "join outreach.leads l on l.company_number = d.company_number "
        "left join outreach.enrichment e on e.company_number = d.company_number "
        "where d.id = %s", (draft_id,))
    row = cur.fetchone()
    if not row:
        raise SendRefused(f"draft {draft_id} not found")
    cn, subject, body_final, status, sub, lead_state, email = row

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
    cur.execute(
        "select count(*) from outreach.sends "
        "where from_inbox = %s and created_at::date = current_date "
        "and status in ('sent', 'dry_run_ok')", (inbox,))
    if cur.fetchone()[0] >= config.PER_INBOX_DAILY_CAP:
        raise SendRefused(f"per-inbox daily cap reached ({config.PER_INBOX_DAILY_CAP})")

    # ---- LIVE gate: never send live unless a human cleared G-SEND ----
    if mode == "live":
        if not config.send_enabled():
            raise SendRefused("live send disabled — gate G-SEND not cleared (G_SEND unset)")
        provider_id = _graph_send(inbox, email, subject or "", body_final)
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
