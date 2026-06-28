import uuid

import pytest

from outreach import review

pytestmark = pytest.mark.floor_f

BODY = "Hello Co, FCA-regulated partners handle payments. Reply unsubscribe to opt out. SettlePay"


def _seed_drafted(cur, body=BODY):
    cn = f"REV_{uuid.uuid4().hex[:8]}"
    cur.execute(
        "insert into outreach.leads (company_number, company_name, company_type, "
        "subscriber_class, state) values (%s,%s,'ltd','corporate','drafted')", (cn, cn))
    cur.execute(
        "insert into outreach.drafts (company_number, body_original, prompt_version, status) "
        "values (%s,%s,'placeholder-v0','awaiting_approval') returning id", (cn, body))
    return cn, cur.fetchone()[0]


def test_approve_as_is_copies_body_original(db_rollback):
    cur = db_rollback.cursor()
    cn, did = _seed_drafted(cur)
    review.approve(did, "Finlay", cur=cur)
    cur.execute("select body_original, body_final, status, decided_by, decided_at from outreach.drafts where id=%s", (did,))
    bo, bf, status, by, at = cur.fetchone()
    assert bf == bo and bo == BODY          # copied, original intact
    assert status == "approved" and by == "Finlay" and at is not None
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "approved"   # only approved drafts advance


def test_approve_with_edit_writes_body_final_keeps_original(db_rollback):
    cur = db_rollback.cursor()
    cn, did = _seed_drafted(cur, body="ORIGINAL. FCA-regulated partners. unsubscribe. SettlePay")
    edited = "EDITED by human. FCA-regulated partners. unsubscribe. SettlePay"
    review.approve(did, "Finlay", edited=edited, note="tightened opener", cur=cur)
    cur.execute("select body_original, body_final, reviewer_note, status from outreach.drafts where id=%s", (did,))
    bo, bf, note, status = cur.fetchone()
    assert bo == "ORIGINAL. FCA-regulated partners. unsubscribe. SettlePay"  # IMMUTABLE
    assert bf == edited and note == "tightened opener" and status == "approved"


def test_reject_sets_rejected_and_no_body_final(db_rollback):
    cur = db_rollback.cursor()
    cn, did = _seed_drafted(cur)
    review.reject(did, "Finlay", note="not a fit", cur=cur)
    cur.execute("select status, body_final from outreach.drafts where id=%s", (did,))
    status, bf = cur.fetchone()
    assert status == "rejected" and bf is None
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "rejected"


def test_decision_requires_reviewer(db_rollback):
    cur = db_rollback.cursor()
    cn, did = _seed_drafted(cur)
    with pytest.raises(ValueError):
        review.approve(did, "", cur=cur)          # no recorded human -> refused


def test_cannot_decide_twice(db_rollback):
    cur = db_rollback.cursor()
    cn, did = _seed_drafted(cur)
    review.approve(did, "Finlay", cur=cur)
    with pytest.raises(ValueError):
        review.approve(did, "Finlay", cur=cur)    # already decided


def test_nothing_advances_without_a_decision(db_rollback):
    # a freshly-seeded draft (no decision) leaves the lead non-advanced + body_final null
    cur = db_rollback.cursor()
    cn, did = _seed_drafted(cur)
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "drafted"          # not approved
    cur.execute("select body_final, decided_by from outreach.drafts where id=%s", (did,))
    assert cur.fetchone() == (None, None)
