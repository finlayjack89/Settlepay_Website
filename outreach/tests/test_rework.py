"""Rework — returning leads whose FACTS are stale to the enriched pool.

The load-bearing properties: it can never pull a lead back from contact, it never
destroys the paid facts, and an approved draft is retired as a recorded DECISION rather
than silently rewritten.
"""
import uuid

import pytest

from outreach import audit, rework, states

pytestmark = pytest.mark.floor_c


def _lead(cur, *, lead_state="drafted", draft_status="awaiting_approval",
          dm_attempted=False, location="Otley", tier="verified"):
    cn = f"RWK_{uuid.uuid4().hex[:8]}"
    did = uuid.uuid4()
    cur.execute(
        "insert into outreach.leads (company_number, company_name, company_type, "
        "subscriber_class, state) values (%s,%s,'ltd','corporate',%s)",
        (cn, f"Rework Test {cn}", lead_state))
    loc = ('{"value": "%s", "source": "own_site", "verified": true}' % location) \
        if location else '{"value": null, "source": null, "verified": false}'
    cur.execute(
        "insert into outreach.enrichment (company_number, contact_email, contact_tier, "
        " facts, dm_attempted_at, facts_refreshed_at) "
        "values (%s,'info@x.co.uk',%s, jsonb_build_object('location', %s::jsonb), "
        "        case when %s then now() else null end, now())",
        (cn, tier, loc, dm_attempted))
    cur.execute(
        "insert into outreach.drafts (id, company_number, subject, body_original, "
        "prompt_version, status) values (%s,%s,'subj','body','playbook-v3.0',%s)",
        (did, cn, draft_status))
    return cn, did


def _state(cur, cn):
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    return cur.fetchone()[0]


def _draft(cur, did):
    cur.execute("select status, decided_by, reviewer_note from outreach.drafts where id=%s",
                (did,))
    return cur.fetchone()


def _row(cur, cn):
    """The one backlog row for this lead — rework_lead takes what stale() emits, so the
    tests drive it through the same shape production does."""
    return next(r for r in rework.stale(cur, limit=500) if r["company_number"] == cn)


# --------------------------------------------------------------------------- #
#  the state machine authorises the retreat
# --------------------------------------------------------------------------- #
def test_rework_is_a_real_transition_and_only_moves_backwards():
    """drafted/approved -> enriched is a retreat from sending. Everything at or past
    contact stays unreachable, which is what stops a rework widening who gets emailed."""
    S = states.LeadState
    assert states.can_transition(S.DRAFTED, S.ENRICHED)
    assert states.can_transition(S.APPROVED, S.ENRICHED)
    for src in (S.SENT, S.SENDING, S.REPLIED, S.SUPPRESSED, S.BOUNCED, S.REJECTED):
        assert not states.can_transition(src, S.ENRICHED), src


# --------------------------------------------------------------------------- #
#  what it picks up
# --------------------------------------------------------------------------- #
def test_a_lead_never_through_the_waterfall_is_stale(db_rollback):
    cur = db_rollback.cursor()
    cn, _ = _lead(cur, dm_attempted=False)
    assert cn in {r["company_number"] for r in rework.stale(cur, limit=500)}


def test_a_lead_with_no_trading_location_is_stale(db_rollback):
    """Location is the single most-rejected fact — three of the four rejections a human
    has ever written on this pipeline are about it."""
    cur = db_rollback.cursor()
    cn, _ = _lead(cur, dm_attempted=True, location=None)
    assert cn in {r["company_number"] for r in rework.stale(cur, limit=500)}


def test_a_lead_already_worked_is_left_alone(db_rollback):
    cur = db_rollback.cursor()
    cn, _ = _lead(cur, dm_attempted=True, location="Otley")
    assert cn not in {r["company_number"] for r in rework.stale(cur, limit=500)}


def test_a_named_contact_is_left_alone(db_rollback):
    """contact_tier='named' means the waterfall already found a real person. Re-running
    it buys nothing and would spend a Companies House call to learn what we know."""
    cur = db_rollback.cursor()
    cn, _ = _lead(cur, dm_attempted=False, location=None, tier="named")
    assert cn not in {r["company_number"] for r in rework.stale(cur, limit=500)}


@pytest.mark.parametrize("lead_state", ["sent", "suppressed", "bounced", "replied"])
def test_a_contacted_lead_is_never_stale(db_rollback, lead_state):
    cur = db_rollback.cursor()
    cn, _ = _lead(cur, lead_state=lead_state, draft_status="approved", dm_attempted=False)
    assert cn not in {r["company_number"] for r in rework.stale(cur, limit=500)}


# --------------------------------------------------------------------------- #
#  what it does
# --------------------------------------------------------------------------- #
def test_dry_run_writes_nothing(db_rollback):
    cur = db_rollback.cursor()
    cn, did = _lead(cur)
    res = rework.run(limit=500, dry_run=True, cur=cur)
    assert res["stale"] >= 1 and res["reworked"] == 0
    assert _state(cur, cn) == "drafted"
    assert _draft(cur, did)[0] == "awaiting_approval"


def test_an_awaiting_draft_is_superseded_and_the_lead_returns_to_the_pool(db_rollback):
    cur = db_rollback.cursor()
    cn, did = _lead(cur, lead_state="drafted", draft_status="awaiting_approval")
    assert rework.rework_lead(cur, _row(cur, cn)) is True
    assert _draft(cur, did)[0] == "superseded"
    assert _state(cur, cn) == "enriched"


def test_an_approved_draft_is_rejected_with_a_reason_not_rewritten(db_rollback):
    """An approval is a human decision. Superseding it would rewrite history, so it is
    retired as a NEW decision — attributed to the system so it can never be counted as
    human trust by graduation."""
    cur = db_rollback.cursor()
    cn, did = _lead(cur, lead_state="approved", draft_status="approved")
    assert rework.rework_lead(cur, _row(cur, cn)) is True
    status, decided_by, note = _draft(cur, did)
    assert status == "rejected"
    assert decided_by == rework.REWORK_ACTOR and decided_by.startswith("system:")
    assert "rework" in note.lower()
    assert _state(cur, cn) == "enriched"


def test_the_paid_facts_survive_and_only_the_markers_are_cleared(db_rollback):
    """The contact address cost verifier credit and all three verifiers are dry. A
    "clean slate" that cleared it would force a re-verify that can only fail — and
    enrich's unverifiable branch DISCARDS, so it would destroy the lead."""
    cur = db_rollback.cursor()
    cn, _ = _lead(cur)
    rework.rework_lead(cur, _row(cur, cn))
    cur.execute("select contact_email, contact_tier, dm_attempted_at, facts_refreshed_at "
                "from outreach.enrichment where company_number=%s", (cn,))
    email, tier, dm_at, refreshed = cur.fetchone()
    assert email == "info@x.co.uk" and tier == "verified"   # kept
    assert dm_at is None and refreshed is None              # cleared → re-admitted


def test_it_is_idempotent_once_the_draft_is_gone(db_rollback):
    cur = db_rollback.cursor()
    cn, _ = _lead(cur)
    row = _row(cur, cn)
    assert rework.rework_lead(cur, row) is True
    assert rework.rework_lead(cur, row) is False    # nothing left to retire


def test_an_audit_row_records_why(db_rollback):
    cur = db_rollback.cursor()
    cn, _ = _lead(cur, dm_attempted=False)
    rework.rework_lead(cur, _row(cur, cn))
    cur.execute("select event, reason, lawful_basis from outreach.audit_log "
                "where company_number=%s and event='reworked'", (cn,))
    _, reason, basis = cur.fetchone()
    assert "decision-maker" in reason and basis == audit.LEGITIMATE_INTERESTS
