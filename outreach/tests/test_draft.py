import uuid

import pytest

from outreach import draft
from outreach.llm import InlineProvider

pytestmark = pytest.mark.floor_e


# ---- playbook is versioned (the value itself changes with copy revisions) ----
def test_playbook_loads_and_is_versioned():
    text = draft.load_playbook()
    m = draft.VERSION_RE.search(text)
    assert m and m.group(1).lower().startswith("v")
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
    assert pv == draft.PROMPT_VERSION and pv.startswith("playbook-v")
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "drafted"


# ---- one bad lead must not abort the batch (per-lead savepoint isolation) ----
class _ScriptedProvider:
    """Returns a fixed body per COMPANY name; used to force one bad draft."""
    name = "scripted"

    def __init__(self, by_company):
        self.by_company = by_company

    def complete(self, prompt, *, purpose, max_words=None):
        from outreach.llm import LLMResult
        for name, body in self.by_company.items():
            if f"COMPANY: {name}" in prompt:
                return LLMResult(body, self.name, {"purpose": purpose})
        return LLMResult("(none)", self.name, {"purpose": purpose})


def test_run_isolates_a_bad_draft_and_keeps_the_good_ones(db_rollback):
    cur = db_rollback.cursor()
    good = f"GOOD_{uuid.uuid4().hex[:8]}"
    bad = f"BAD_{uuid.uuid4().hex[:8]}"
    for cn, nm in ((good, "Good Co Ltd"), (bad, "Bad Co Ltd")):
        cur.execute(
            "insert into outreach.leads (company_number, company_name, company_type, "
            "subscriber_class, state) values (%s,%s,'ltd','corporate','enriched')", (cn, nm))
        cur.execute(
            "insert into outreach.enrichment (company_number, website, contact_email, "
            "email_verified, signal) values (%s,'https://x.co','info@x.co',true,'sig')", (cn,))

    compliant = ("Hi Good Co, a note from SettlePay. Payments are handled by "
                 "FCA-regulated partners. Reply unsubscribe to opt out. "
                 "Kind regards, Finlay Salisbury SettlePay")
    overlong = ("SettlePay FCA-regulated partners unsubscribe " + "word " * 130)
    provider = _ScriptedProvider({"Good Co Ltd": compliant, "Bad Co Ltd": overlong})

    res = draft.run(provider=provider, cur=cur)

    # good lead drafted; bad lead discarded — batch not aborted
    cur.execute("select state::text from outreach.leads where company_number=%s", (good,))
    assert cur.fetchone()[0] == "drafted"
    cur.execute("select state::text from outreach.leads where company_number=%s", (bad,))
    assert cur.fetchone()[0] == "discarded"
    cur.execute("select count(*) from outreach.drafts where company_number=%s", (good,))
    assert cur.fetchone()[0] == 1
    cur.execute("select count(*) from outreach.drafts where company_number=%s", (bad,))
    assert cur.fetchone()[0] == 0
