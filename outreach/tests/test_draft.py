import uuid

import pytest

from outreach import draft
from outreach.llm import InlineProvider

pytestmark = pytest.mark.floor_e


# ---- playbook is a versioned, real v1 ----
def test_playbook_loads_and_is_versioned():
    text = draft.load_playbook()
    m = draft.VERSION_RE.search(text)
    assert m and m.group(1).lower() == "v1"     # declares PLAYBOOK VERSION: v1
    # the mechanism must refuse an unversioned / garbage file
    import tempfile, pathlib
    p = pathlib.Path(tempfile.mkdtemp()) / "x.md"
    p.write_text("real copy, no version marker")
    with pytest.raises(RuntimeError):
        draft.load_playbook(p)


# ---- envelope enforcement ----
def test_envelope_accepts_a_compliant_draft():
    body = draft.provisional_draft("Acme Lettings Ltd", "independent agent in Leeds")
    assert draft.check_envelope(body) == []


def test_envelope_flags_each_violation():
    assert "no unsubscribe line" in draft.check_envelope("Hello, from SettlePay, FCA-regulated partners.")
    assert "no SettlePay sender id" in draft.check_envelope("Hello, unsubscribe anytime, FCA-regulated partners.")
    assert "missing 'FCA-regulated partners'" in draft.check_envelope("Hello from SettlePay, unsubscribe anytime.")
    assert any("link" in v for v in draft.check_envelope(
        "SettlePay, FCA-regulated partners, unsubscribe, https://x.com"))
    assert any(">=125" in v for v in draft.check_envelope(
        "SettlePay FCA-regulated partners unsubscribe " + "word " * 130))
    assert any("self-claim" in v for v in draft.check_envelope(
        "SettlePay is FCA authorised; unsubscribe; FCA-regulated partners"))


def test_provisional_draft_has_no_links_and_is_short():
    body = draft.provisional_draft("NAISH ESTATE AGENTS LIMITED", "70-year family agency in York")
    assert draft.LINK_RE.search(body) is None
    assert len(body.split()) < draft.MAX_WORDS
    assert "settlepay" in body.lower() and "unsubscribe" in body.lower()


# ---- draft_one writes body_original + advances the lead (DB, rolled back) ----
def test_draft_one_writes_body_original_and_advances(db_rollback):
    cur = db_rollback.cursor()
    cn = f"DRAFT_{uuid.uuid4().hex[:8]}"
    cur.execute(
        "insert into outreach.leads (company_number, company_name, company_type, "
        "subscriber_class, state) values (%s,%s,'ltd','corporate','enriched')", (cn, "Test Agents Ltd"))
    cur.execute(
        "insert into outreach.enrichment (company_number, website, contact_email, "
        "email_verified, signal) values (%s,'https://x.co','info@x.co',true,'a test agency')", (cn,))

    provider = InlineProvider(responder=draft.provisional_responder)
    res = draft.draft_one(cn, "Test Agents Ltd", "a test agency", provider=provider, cur=cur)

    cur.execute("select body_original, body_final, status, prompt_version from outreach.drafts where company_number=%s", (cn,))
    body_original, body_final, status, pv = cur.fetchone()
    assert body_original and draft.check_envelope(body_original) == []  # compliant
    assert body_final is None            # human edit comes later (phase F)
    assert status == "awaiting_approval"
    assert pv == "playbook-v1"
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "drafted"
