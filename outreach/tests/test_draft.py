import json
import uuid

import pytest

from outreach import draft
from outreach.llm import InlineProvider

pytestmark = pytest.mark.floor_e


def _payload(subject: str, body: str) -> str:
    """Providers return the {subject, body} JSON contract (playbook v2.0)."""
    return json.dumps({"subject": subject, "body": body})


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

    def complete(self, prompt, *, purpose, max_words=None, schema=None):
        from outreach.llm import LLMResult
        for name, body in self.by_company.items():
            if f"COMPANY: {name}" in prompt:
                return LLMResult(body, self.name, {"purpose": purpose})
        return LLMResult(_payload("no match", "(none)"), self.name, {"purpose": purpose})


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

    compliant = _payload("payments at good co",
                         "Hi Good Co, a note from SettlePay. Payments are handled by "
                         "FCA-regulated partners. Reply unsubscribe to opt out. "
                         "Kind regards, Finlay Salisbury SettlePay")
    overlong = _payload("payments at bad co",
                        "SettlePay FCA-regulated partners unsubscribe " + "word " * 130)
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


# ---- v2.0: the copywriting-skill contract (subject, craft modules, variation) ----
def test_playbook_compiles_in_the_vendored_craft_modules():
    text = draft.load_playbook()
    # the craft guidance must actually reach the model, not just sit in the repo
    assert "Cold email to UK SMEs" in text
    assert "compliance layer" in text.lower()
    # ...and the SettlePay brief must come after it, so the brief wins on conflict
    assert text.index("Cold email to UK SMEs") < text.index("SettlePay cold-email drafting playbook")


def test_missing_craft_module_is_fatal(monkeypatch, tmp_path):
    monkeypatch.setattr(draft, "CRAFT_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="missing vendored craft module"):
        draft.load_playbook()


def test_check_subject_rejects_the_v1_failure_and_the_spam_tells():
    assert draft.check_subject("") == ["empty subject"]          # v1.x stored NULL
    assert draft.check_subject(None) == ["empty subject"]
    assert not draft.check_subject("getting paid at greenway")
    assert any("Re:" in v for v in draft.check_subject("Re: your invoices"))
    assert any("ALL CAPS" in v for v in draft.check_subject("URGENT PAYMENT NOTICE"))
    assert any("merge tag" in v for v in draft.check_subject("hello {FirstName} there"))
    assert any("chars" in v for v in draft.check_subject("a " * 40))
    assert any("link" in v for v in draft.check_subject("see www.example.com now"))


def test_check_style_flags_banned_openers_and_flat_rhythm():
    assert any("came across" in v for v in
               draft.check_style("I came across your website and thought I'd write."))
    assert any("following up" in v for v in draft.check_style("Just following up on this."))
    # five sentences of identical length == the clearest machine-prose tell
    flat = " ".join(["One two three four five six seven."] * 5)
    assert any("rhythm" in v for v in draft.check_style(flat))
    # a varied one should pass the rhythm check
    varied = ("Saw you cover call-outs in Otley. That usually means invoicing after "
              "the job, then chasing it for a fortnight while the work piles up. "
              "Worth a look? It takes ten minutes.")
    assert not any("rhythm" in v for v in draft.check_style(varied))


def test_check_style_flags_drift_to_the_hard_word_cap():
    assert any("tighten" in v for v in draft.check_style("word " * 120))
    assert not any("tighten" in v for v in draft.check_style("word " * 60))


def test_parse_payload_handles_json_fenced_json_and_junk():
    assert draft.parse_payload('{"subject":"s","body":"b"}') == ("s", "b")
    assert draft.parse_payload('```json\n{"subject":"s","body":"b"}\n```') == ("s", "b")
    with pytest.raises(draft.DraftFormatError):
        draft.parse_payload("hi, please buy things")
    with pytest.raises(draft.DraftFormatError):
        draft.parse_payload('{"body":"b"}')


def test_draft_angle_is_deterministic_and_varies_across_leads():
    assert draft.draft_angle("SC123456") == draft.draft_angle("SC123456")
    angles = {draft.draft_angle(f"PLACE:{i}") for i in range(60)}
    # rotation must actually rotate, or every draft shares one middle paragraph
    assert len(angles) > 3


def test_draft_persists_the_subject(db_rollback):
    cur = db_rollback.cursor()
    cn = f"SUBJ_{uuid.uuid4().hex[:8]}"
    cur.execute(
        "insert into outreach.leads (company_number, company_name, company_type, "
        "subscriber_class, state) values (%s,'Subj Co Ltd','ltd','corporate','enriched')", (cn,))
    cur.execute(
        "insert into outreach.enrichment (company_number, website, contact_email, "
        "email_verified, signal) values (%s,'https://x.co','info@x.co',true,'sig')", (cn,))
    body = ("Hi Subj Co, a note from SettlePay. Payments are handled by "
            "FCA-regulated partners. Reply unsubscribe to opt out. "
            "Kind regards, Finlay Salisbury SettlePay")
    provider = InlineProvider(responder=lambda p: _payload("payments at subj co", body))
    res = draft.draft_one(cn, "Subj Co Ltd", "sig", provider=provider, cur=cur)
    assert res["subject"] == "payments at subj co"
    cur.execute("select subject from outreach.drafts where id=%s", (res["draft_id"],))
    assert cur.fetchone()[0] == "payments at subj co"


# ---- greeting: always "Dear <business name>," or "Dear <first name>," ----
def test_first_name_reduces_ch_and_plain_names():
    assert draft.first_name("SMITH, John Andrew") == "John"
    assert draft.first_name("John Smith") == "John"
    assert draft.first_name("COOK, Akleem") == "Akleem"
    assert draft.first_name(None) is None
    assert draft.first_name("   ") is None


def test_clean_business_name_drops_suffix_and_stops_shouting():
    assert draft._clean_business_name("ACME JOINERY LTD") == "Acme Joinery"
    assert draft._clean_business_name("Acme Lettings Ltd") == "Acme Lettings"
    assert draft._clean_business_name("NAISH ESTATE AGENTS LIMITED") == "Naish Estate Agents"
    assert draft._clean_business_name("C & S Electrical Wholesale") == "C & S Electrical Wholesale"
    # short initialisms keep shouting rather than becoming 'Dc'
    assert draft._clean_business_name("DC SERVICES ELECTRICAL CONTRACTOR LTD") == \
        "DC Services Electrical Contractor"


def test_greeting_regex_wants_dear_and_rejects_the_old_forms():
    assert draft.GREETING_RE.match("Dear Acme Joinery,\n")
    assert draft.GREETING_RE.match("Dear John,\n")
    assert not draft.GREETING_RE.match("Hi John,\n")
    assert not draft.GREETING_RE.match("Hello,\n")
    assert any("greeting" in v for v in draft.check_style(
        "Hello, a note from SettlePay. FCA-regulated partners. unsubscribe. "
        "Kind regards, Finlay Salisbury SettlePay"))


def test_provisional_draft_greets_the_business_by_clean_name():
    assert draft.provisional_draft("ACME JOINERY LTD", "x").startswith("Dear Acme Joinery,")


def test_draft_passes_the_contacts_first_name_into_the_prompt(db_rollback):
    """A named contact must reach the drafter as a 'Dear <first name>,' instruction —
    the whole point of resolving a decision-maker."""
    cur = db_rollback.cursor()
    import uuid
    cn = f"GRT_{uuid.uuid4().hex[:8]}"
    cur.execute("insert into outreach.leads (company_number, company_name, company_type, "
                "subscriber_class, state) values (%s,'Acme Ltd','ltd','corporate','enriched')", (cn,))
    cur.execute("insert into outreach.enrichment (company_number, website, contact_email, "
                "contact_name, contact_tier, email_verified, signal) "
                "values (%s,'https://x.co','j.smith@x.co','SMITH, John','named',true,'sig')", (cn,))
    seen = {}

    class _P:
        def complete(self, prompt, **k):
            seen["prompt"] = prompt
            import json as _j
            return type("R", (), {"text": _j.dumps({
                "subject": "payments at acme",
                "body": ("Dear John,\n\nA note from SettlePay. Payments are handled by "
                         "FCA-regulated partners. Reply unsubscribe to opt out.\n\n"
                         "Kind regards,\nFinlay Salisbury\nSettlePay")})})()

    draft.run(provider=_P(), cur=cur, limit=1)
    assert 'Dear John,' in seen["prompt"] and "CONTACT NAME: John" in seen["prompt"]
