import hashlib
import uuid

import pytest

from outreach import config, draft, graduation, sequence

pytestmark = pytest.mark.floor_h

BODY = "Hello Co, FCA-regulated partners handle payments. Reply unsubscribe to opt out. SettlePay"


def _sic() -> str:
    return f"GSIC{uuid.uuid4().hex[:8]}"


def _cn(*, held: bool) -> str:
    """A company number that lands on (held=True) or off the 1-in-20 sha256 slot."""
    while True:
        cn = f"GRAD_{uuid.uuid4().hex[:10]}"
        if (int(hashlib.sha256(cn.encode()).hexdigest(), 16) % 20 == 0) is held:
            return cn


def _seed_lead(cur, cn, sic, state="drafted"):
    cur.execute(
        "insert into outreach.leads (company_number, company_name, company_type, "
        "subscriber_class, state, sic_codes) values (%s,%s,'ltd','corporate',%s,%s)",
        (cn, cn, state, [sic]))


def _seed_awaiting(cur, sic, *, held=False, prompt_version=draft.PROMPT_VERSION):
    cn = _cn(held=held)
    _seed_lead(cur, cn, sic)
    cur.execute(
        "insert into outreach.drafts (company_number, body_original, prompt_version, status) "
        "values (%s,%s,%s,'awaiting_approval') returning id", (cn, BODY, prompt_version))
    return cn, cur.fetchone()[0]


def _seed_proven_vertical(cur, sic, *, reviewed=52, rejected=2,
                          prompt_version=draft.PROMPT_VERSION):
    """A LOOP of decided drafts: `reviewed` human decisions, all approvals unedited."""
    leads, drafts = [], []
    for i in range(reviewed):
        cn = _cn(held=False)
        status = "rejected" if i < rejected else "approved"
        body_final = None if status == "rejected" else BODY
        leads.append((cn, cn, status, [sic]))
        drafts.append((cn, BODY, body_final, prompt_version, status))
    cur.executemany(
        "insert into outreach.leads (company_number, company_name, company_type, "
        "subscriber_class, state, sic_codes) values (%s,%s,'ltd','corporate',%s,%s)", leads)
    cur.executemany(
        "insert into outreach.drafts (company_number, body_original, body_final, "
        "prompt_version, status, decided_by, decided_at) values (%s,%s,%s,%s,%s,'Finlay',now())",
        drafts)
    return [l[0] for l in leads]


@pytest.fixture
def gates_on(monkeypatch):
    monkeypatch.setattr(config, "AUTO_APPROVE_ENABLED", True)
    grads = dict(sequence.graduation_thresholds(), per_vertical_auto_send=True)
    monkeypatch.setattr(sequence, "graduation_thresholds", lambda seq=None: grads)
    return grads


def _draft_row(cur, did):
    cur.execute(
        "select status, body_original, body_final, decided_by, reviewer_note "
        "from outreach.drafts where id=%s", (did,))
    return cur.fetchone()


def _audit_events(cur, cn):
    cur.execute("select event from outreach.audit_log where company_number=%s", (cn,))
    return [r[0] for r in cur.fetchall()]


def test_both_gates_off_nothing_happens(db_rollback, monkeypatch):
    cur = db_rollback.cursor()
    sic = _sic()
    _seed_proven_vertical(cur, sic)
    cn, did = _seed_awaiting(cur, sic)
    monkeypatch.setattr(config, "AUTO_APPROVE_ENABLED", False)
    grads = dict(sequence.graduation_thresholds(), per_vertical_auto_send=False)
    monkeypatch.setattr(sequence, "graduation_thresholds", lambda seq=None: grads)
    assert graduation.eligible_verticals(cur) == []
    assert graduation.run(cur=cur) == []
    assert _draft_row(cur, did)[0] == "awaiting_approval"


def test_either_single_gate_stays_dormant(db_rollback, monkeypatch):
    cur = db_rollback.cursor()
    sic = _sic()
    _seed_proven_vertical(cur, sic)
    _seed_awaiting(cur, sic)

    monkeypatch.setattr(config, "AUTO_APPROVE_ENABLED", True)
    grads_off = dict(sequence.graduation_thresholds(), per_vertical_auto_send=False)
    monkeypatch.setattr(sequence, "graduation_thresholds", lambda seq=None: grads_off)
    assert graduation.eligible_verticals(cur) == []
    assert graduation.run(cur=cur) == []

    monkeypatch.setattr(config, "AUTO_APPROVE_ENABLED", False)
    grads_on = dict(grads_off, per_vertical_auto_send=True)
    monkeypatch.setattr(sequence, "graduation_thresholds", lambda seq=None: grads_on)
    assert graduation.eligible_verticals(cur) == []
    assert graduation.run(cur=cur) == []


def test_vertical_below_thresholds_untouched(db_rollback, gates_on):
    cur = db_rollback.cursor()
    sic = _sic()
    _seed_proven_vertical(cur, sic, reviewed=10)   # < min_reviewed_drafts_per_vertical
    cn, did = _seed_awaiting(cur, sic)
    assert sic not in graduation.eligible_verticals(cur)
    graduation.run(cur=cur)
    row = _draft_row(cur, did)
    assert row[0] == "awaiting_approval" and row[3] is None


def test_bad_bounce_rate_blocks_graduation(db_rollback, gates_on):
    cur = db_rollback.cursor()
    sic = _sic()
    cns = _seed_proven_vertical(cur, sic)
    cur.executemany(
        "insert into outreach.sends (company_number, to_email, mode, status) "
        "values (%s,'x@example.com','live','sent')", [(c,) for c in cns[:10]])
    cur.execute(
        "insert into outreach.replies (company_number, from_email, kind) "
        "values (%s,'x@example.com','bounce')", (cns[0],))
    m = next(m for m in graduation.vertical_metrics(cur) if m["vertical"] == sic)
    assert m["bounce_rate"] == pytest.approx(0.1)  # > max_bounce_rate 0.02
    assert sic not in graduation.eligible_verticals(cur)


def test_proven_vertical_auto_approves_via_review(db_rollback, gates_on):
    cur = db_rollback.cursor()
    sic = _sic()
    _seed_proven_vertical(cur, sic, reviewed=52, rejected=2)
    cn1, did1 = _seed_awaiting(cur, sic, held=False)
    cn2, did2 = _seed_awaiting(cur, sic, held=False)

    m = next(m for m in graduation.vertical_metrics(cur) if m["vertical"] == sic)
    assert m["reviewed"] == 52 and m["approved"] == 50
    assert m["approved_unedited_rate"] == pytest.approx(1.0)
    assert sic in graduation.eligible_verticals(cur)

    assert len(graduation.run(cur=cur, limit=1)) == 1
    actions = graduation.run(cur=cur)
    ours = {a["draft_id"]: a for a in actions if a["company_number"] in (cn1, cn2)}
    assert all(a["action"] == "auto_approved" for a in ours.values())

    for cn, did in ((cn1, did1), (cn2, did2)):
        status, bo, bf, by, note = _draft_row(cur, did)
        assert status == "approved" and bf == bo == BODY
        assert by == graduation.AUTO_REVIEWER
        assert note.startswith(f"graduated {sic}:") and '"reviewed":' in note
        cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
        assert cur.fetchone()[0] == "approved"
        assert "auto_approved" in _audit_events(cur, cn)


def test_spot_check_hold_is_deterministic(db_rollback, gates_on):
    cur = db_rollback.cursor()
    sic = _sic()
    _seed_proven_vertical(cur, sic)
    cn, did = _seed_awaiting(cur, sic, held=True)
    assert int(hashlib.sha256(cn.encode()).hexdigest(), 16) % 20 == 0

    for _ in range(2):  # re-runs land the same company on the same side
        actions = graduation.run(cur=cur)
        held = [a for a in actions if a["company_number"] == cn]
        assert held and held[0]["action"] == "spot_check_held"
        row = _draft_row(cur, did)
        assert row[0] == "awaiting_approval" and row[3] is None
    assert "spot_check_held" in _audit_events(cur, cn)


def test_prompt_version_isolation(db_rollback, gates_on):
    cur = db_rollback.cursor()
    sic = _sic()
    _seed_proven_vertical(cur, sic, prompt_version=draft.PROMPT_VERSION)
    cn_v1, did_v1 = _seed_awaiting(cur, sic, held=False)
    cn_v2, did_v2 = _seed_awaiting(cur, sic, held=False, prompt_version="playbook-v2-test")

    v2 = [m for m in graduation.vertical_metrics(cur, prompt_version="playbook-v2-test")
          if m["vertical"] == sic]
    assert not v2 or v2[0]["reviewed"] == 0   # v2 inherits NO trust from v1

    graduation.run(cur=cur)
    assert _draft_row(cur, did_v1)[0] == "approved"
    v2_row = _draft_row(cur, did_v2)
    assert v2_row[0] == "awaiting_approval" and v2_row[3] is None
