import datetime
import uuid

import pytest

from outreach import draft, followup
from outreach.llm import InlineProvider

pytestmark = pytest.mark.floor_h

COMPLIANT = "Hello. FCA-regulated partners handle payments. Reply unsubscribe to opt out. SettlePay"


def _seed_sent(cur, *, days_ago=7, email=None, mode="live", status="sent"):
    """A lead whose touch-1 draft was sent `days_ago` days ago (backdated send row)."""
    cn = f"FUP_{uuid.uuid4().hex[:8]}"
    email = email or f"info-{uuid.uuid4().hex[:6]}@example.com"
    cur.execute(
        "insert into outreach.leads (company_number, company_name, company_type, "
        "subscriber_class, state) values (%s,%s,'ltd','corporate','sent')", (cn, cn))
    cur.execute(
        "insert into outreach.enrichment (company_number, website, contact_email, "
        "email_verified, signal) values (%s,'https://x.co',%s,true,'a test agency in York')",
        (cn, email))
    cur.execute(
        "insert into outreach.drafts (company_number, body_original, body_final, "
        "prompt_version, status, touch, decided_by, decided_at) "
        "values (%s,%s,%s,'playbook-v1','sent',1,'Finlay',now()) returning id",
        (cn, COMPLIANT, COMPLIANT))
    did = cur.fetchone()[0]
    cur.execute(
        "insert into outreach.sends (draft_id, company_number, to_email, from_inbox, "
        "mode, status, created_at) "
        "values (%s,%s,%s,'test@settlepayhq.uk',%s,%s, now() - make_interval(days => %s))",
        (did, cn, email, mode, status, days_ago))
    return cn, email, did


# ---- working_days_between ----
def test_working_days_between_counts_weekdays_only():
    mon, fri = datetime.date(2026, 7, 13), datetime.date(2026, 7, 17)
    assert followup.working_days_between(mon, fri) == 4      # Tue..Fri
    assert followup.working_days_between(fri, datetime.date(2026, 7, 20)) == 1  # Fri->Mon
    assert followup.working_days_between(
        datetime.date(2026, 7, 18), datetime.date(2026, 7, 19)) == 0  # Sat->Sun


def test_working_days_between_zero_and_full_week():
    d = datetime.date(2026, 7, 15)
    assert followup.working_days_between(d, d) == 0
    assert followup.working_days_between(d, d - datetime.timedelta(days=3)) == 0  # reversed
    for offset in range(7):  # any 7-calendar-day span contains exactly 5 working days
        start = d + datetime.timedelta(days=offset)
        assert followup.working_days_between(start, start + datetime.timedelta(days=7)) == 5


def test_working_days_between_accepts_datetimes():
    a = datetime.datetime(2026, 7, 13, 9, 0, tzinfo=datetime.timezone.utc)
    b = datetime.datetime(2026, 7, 17, 15, 0, tzinfo=datetime.timezone.utc)
    assert followup.working_days_between(a, b) == 4


# ---- provisional follow-up body ----
def test_provisional_followup_is_compliant_and_short():
    body = followup.provisional_followup("Acme Lettings Ltd", "independent agent in Leeds")
    assert draft.check_envelope(body) == []
    assert 40 <= len(body.split()) <= 95            # ~60-80 word touch-2, well under touch-1 cap
    low = body.lower()
    assert "following up" in low and "invoices" in low       # references touch 1 + admin angle
    assert "Finlay Salisbury — SettlePay" in body
    assert draft.LINK_RE.search(body) is None


# ---- eligibility ----
def test_eligibility_respects_working_day_delay(db_rollback):
    cur = db_rollback.cursor()
    due_cn, _, due_did = _seed_sent(cur, days_ago=7)     # 7 calendar days = 5 working >= 4
    fresh_cn, _, _ = _seed_sent(cur, days_ago=1)         # too recent
    rows = {r[0]: r for r in followup.eligible(cur)}
    assert due_cn in rows
    assert fresh_cn not in rows
    cn, name, signal, email, parent_id = rows[due_cn]
    assert (name, parent_id) == (due_cn, due_did) and email and signal


def test_existing_touch2_draft_excludes(db_rollback):
    cur = db_rollback.cursor()
    cn, _, did = _seed_sent(cur, days_ago=7)
    cur.execute(
        "insert into outreach.drafts (company_number, body_original, prompt_version, "
        "status, touch, parent_draft_id) values (%s,%s,'playbook-v1','awaiting_approval',2,%s)",
        (cn, COMPLIANT, did))
    assert cn not in [r[0] for r in followup.eligible(cur)]


def test_suppressed_contact_excluded(db_rollback):
    cur = db_rollback.cursor()
    cn, email, _ = _seed_sent(cur, days_ago=7)
    cur.execute("insert into outreach.suppressions (email, reason) values (%s,'test')", (email,))
    assert cn not in [r[0] for r in followup.eligible(cur)]


def test_dry_run_only_send_does_not_qualify(db_rollback):
    cur = db_rollback.cursor()
    cn, _, _ = _seed_sent(cur, days_ago=7, mode="dry_run", status="dry_run_ok")
    assert cn not in [r[0] for r in followup.eligible(cur)]


def test_eligible_respects_limit(db_rollback):
    cur = db_rollback.cursor()
    _seed_sent(cur, days_ago=7)
    _seed_sent(cur, days_ago=7)
    assert len(followup.eligible(cur, limit=1)) == 1


# ---- run() writes a compliant touch-2 draft into the normal approval path ----
def test_run_writes_touch2_draft_awaiting_approval(db_rollback):
    cur = db_rollback.cursor()
    cn, _, did = _seed_sent(cur, days_ago=7)
    provider = InlineProvider(responder=followup.provisional_followup_responder)
    results = followup.run(provider=provider, cur=cur)
    mine = [r for r in results if r["company_number"] == cn]
    assert mine and mine[0]["touch"] == 2 and mine[0]["parent_draft_id"] == str(did)

    cur.execute(
        "select body_original, body_final, status, prompt_version, touch, parent_draft_id "
        "from outreach.drafts where company_number=%s and touch=2", (cn,))
    body, body_final, status, pv, touch, parent = cur.fetchone()
    assert draft.check_envelope(body) == []          # envelope-compliant
    assert body_final is None                        # human edit comes at review
    assert (status, pv, touch, parent) == ("awaiting_approval", draft.PROMPT_VERSION, 2, did)
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "sent"               # lead state untouched
    cur.execute(
        "select count(*) from outreach.audit_log where company_number=%s "
        "and event='followup_drafted'", (cn,))
    assert cur.fetchone()[0] == 1


def test_run_is_idempotent_per_company(db_rollback):
    cur = db_rollback.cursor()
    cn, _, _ = _seed_sent(cur, days_ago=7)
    provider = InlineProvider(responder=followup.provisional_followup_responder)
    followup.run(provider=provider, cur=cur)
    followup.run(provider=provider, cur=cur)         # second pass: touch-2 already exists
    cur.execute("select count(*) from outreach.drafts where company_number=%s and touch=2", (cn,))
    assert cur.fetchone()[0] == 1


def test_envelope_enforced_on_followup(db_rollback):
    cur = db_rollback.cursor()
    cn, _, did = _seed_sent(cur, days_ago=7)
    bad = InlineProvider(responder=lambda prompt: "hi, please buy things")
    with pytest.raises(draft.EnvelopeViolation):
        followup.followup_one(cn, cn, "sig", did, provider=bad, cur=cur)
    cur.execute("select count(*) from outreach.drafts where company_number=%s and touch=2", (cn,))
    assert cur.fetchone()[0] == 0                    # nothing stored on violation
