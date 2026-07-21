"""Phase H — touch-2 follow-up drafting.

A follow-up is just a NEW outreach.drafts row (touch=2, parent_draft_id -> the
touch-1 draft, status 'awaiting_approval') that flows through the EXISTING
review -> approve -> send path — this module writes zero send code, so every
send guardrail (G-SEND, kill switch, suppression, caps) applies unchanged.

Eligibility is deliberately narrow: only leads whose touch-1 draft was LIVE-sent
at least follow_up_delay_days(seq, 0) WORKING days ago (sequence_config.json —
timing is never hardcoded), still in state 'sent' (a reply/bounce/unsubscribe
moves them out of it), with no touch-2 draft yet, and a suppression-clean
contact. Dry-run sends never qualify: a follow-up to a message that was never
really sent would be a first touch wearing a follow-up's clothes.
"""
from __future__ import annotations
import datetime
import json

from . import audit, config, db, draft, sequence
from .firewall import check_suppression
from .llm import draft_provider


def working_days_between(a, b) -> int:
    """Working days (Mon-Fri) strictly after `a` up to and including `b`;
    0 when b <= a. Accepts dates or datetimes."""
    if isinstance(a, datetime.datetime):
        a = a.date()
    if isinstance(b, datetime.datetime):
        b = b.date()
    days = 0
    while a < b:
        a += datetime.timedelta(days=1)
        if a.weekday() < 5:
            days += 1
    return days


def provisional_followup(company_name: str, signal: str) -> str:
    """A minimal, compliant, explicitly-provisional touch-2 body — NOT conversion
    copy. The playbook's FOLLOW-UP section (via a real model) replaces this; it
    exists only to exercise the mechanism."""
    company = (company_name or "there").strip()
    sig = " ".join((signal or "").split()[:8])
    return (
        f"Hello {company},\n\n"
        "Following up on my earlier note — this is a PROVISIONAL PLACEHOLDER from "
        "SettlePay's drafting mechanism, not for sending.\n\n"
        "The angle this touch adds is admin saved: branded invoices out, every "
        "payment reconciled automatically, no manual bookkeeping. You keep your "
        "bank; the money is handled by FCA-regulated partners.\n\n"
        f"Context on file: {sig}\n\n"
        "Reply if you'd like a look. To opt out, reply with the word unsubscribe.\n\n"
        "Finlay Salisbury — SettlePay"
    )


def provisional_followup_responder(prompt: str) -> str:
    return json.dumps({
        "subject": "following up on payments",
        "body": provisional_followup(draft._extract(prompt, "COMPANY:"),
                                     draft._extract(prompt, "SIGNAL:")),
    })


def eligible(cur, *, limit=None) -> list[tuple]:
    """Leads due a touch-2: live-sent touch-1 at least the configured number of
    working days ago, still 'sent', no touch-2 draft yet, suppression-clean.
    Returns (company_number, company_name, signal, contact_email, parent_draft_id)."""
    seq = sequence.load_sequence_config()
    delay = sequence.follow_up_delay_days(seq, 0)
    if delay is None or seq.get("max_follow_ups", 0) < 1:
        return []
    cur.execute(
        "select distinct on (l.company_number) "
        "       l.company_number, l.company_name, e.signal, e.contact_email, d.id, s.created_at "
        "from outreach.sends s "
        "join outreach.drafts d on d.id = s.draft_id and d.touch = 1 "
        "join outreach.leads l on l.company_number = s.company_number "
        "left join outreach.enrichment e on e.company_number = l.company_number "
        "where s.mode = 'live' and s.status = 'sent' and l.state = 'sent' "
        "and not exists (select 1 from outreach.drafts d2 "
        "                where d2.company_number = l.company_number and d2.touch = 2) "
        "order by l.company_number, s.created_at"
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    out: list[tuple] = []
    for cn, name, signal, email, parent_id, sent_at in cur.fetchall():
        if working_days_between(sent_at, now) < delay:
            continue
        if not email or check_suppression(email=email, company_number=cn, cur=cur):
            continue
        out.append((cn, name, signal, email, parent_id))
        if limit is not None and len(out) >= limit:
            break
    return out


def followup_one(company_number: str, company_name: str, signal: str, parent_draft_id, *,
                 provider, cur, playbook: str | None = None) -> dict:
    playbook = playbook or draft.load_playbook()
    prompt = (
        f"{playbook}\n\n"
        "TOUCH: 2 — write the FOLLOW-UP email described in the FOLLOW-UP section "
        "above (~60-80 words, admin-saved angle, same envelope).\n"
        f"COMPANY: {company_name}\nSIGNAL: {signal or ''}\n"
    )
    r = provider.complete(prompt, purpose="followup", max_words=80,
                          schema=draft.DRAFT_SCHEMA)
    try:
        subject, body = draft.parse_payload(r.text)
    except draft.DraftFormatError as e:
        # same reason as in draft_one: run() isolates EnvelopeViolation per lead
        raise draft.EnvelopeViolation(company_number, [f"unparseable draft: {e}"]) from e

    violations = draft.check_envelope(body) + [
        f"subject: {s}" for s in draft.check_subject(subject)]
    if violations:
        raise draft.EnvelopeViolation(company_number, violations)

    cur.execute(
        "insert into outreach.drafts (company_number, subject, body_original, "
        "prompt_version, status, touch, parent_draft_id) "
        "values (%s, %s, %s, %s, 'awaiting_approval', 2, %s) returning id",
        (company_number, subject, body, draft.PROMPT_VERSION, parent_draft_id),
    )
    followup_id = cur.fetchone()[0]
    audit.record(company_number, "followup_drafted", source="followup",
                 lawful_basis=audit.LEGITIMATE_INTERESTS,
                 reason=(f"touch-2 draft {followup_id} (parent {parent_draft_id}, "
                         f"{draft.PROMPT_VERSION}); envelope ok"), cur=cur)
    return {"company_number": company_number, "draft_id": str(followup_id),
            "parent_draft_id": str(parent_draft_id), "touch": 2,
            "subject": subject, "words": len(body.split())}


def run(*, provider=None, cur=None, limit=None) -> list[dict]:
    if provider is None:
        # gemini/api when configured (real unattended drafts); otherwise the safe
        # provisional fallback so a bare run never fabricates a real-looking email.
        provider = draft_provider(responder=provisional_followup_responder)
    own = cur is None
    conn = None
    if own:
        conn = db.connect()
        cur = conn.cursor()
    playbook = draft.load_playbook()
    results: list[dict] = []
    try:
        for cn, name, signal, _email, parent_id in eligible(cur, limit=limit):
            results.append(followup_one(cn, name, signal, parent_id,
                                        provider=provider, cur=cur, playbook=playbook))
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
    print(run())
