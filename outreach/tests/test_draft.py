import json
import uuid

import pytest

from outreach import draft, facts
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
    """Returns a fixed body per company name; used to force one bad draft. Keys off the
    company_name CONSTANT, which is how the drafter now identifies the lead."""
    name = "scripted"

    def __init__(self, by_company):
        self.by_company = by_company

    def complete(self, prompt, *, purpose, max_words=None, schema=None):
        from outreach.llm import LLMResult
        for name, body in self.by_company.items():
            if f"company_name: {name}" in prompt:
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
            "email_verified, signal, facts) "
            "values (%s,'https://x.co','info@x.co',true,'sig',%s::jsonb)",
            (cn, facts.dumps(facts.build(company_name=nm))))

    compliant = _payload("payments at good co",
                         "Hi Good Co, a note from SettlePay. Payments are handled by "
                         "FCA-regulated partners. Reply unsubscribe to opt out. "
                         "Kind regards, Finlay Salisbury SettlePay")
    overlong = _payload("payments at bad co",
                        "SettlePay FCA-regulated partners unsubscribe " + "word " * 130)
    provider = _ScriptedProvider({"Good Co Ltd": compliant, "Bad Co Ltd": overlong})

    res = draft.run(provider=provider, cur=cur)

    # good lead drafted; bad lead PARKED — batch not aborted, and the bad lead survives.
    # An envelope violation is our writing failing, not a verdict about the business:
    # three of the five real discards on the live database were a subject line 51
    # characters long, and `discarded` is terminal, so each destroyed an enriched,
    # verified, ICP-fit lead. Parking still keeps it out of the draft backlog (which
    # reads state='enriched') while leaving it recoverable.
    cur.execute("select state::text from outreach.leads where company_number=%s", (good,))
    assert cur.fetchone()[0] == "drafted"
    cur.execute("select state::text, park_count from outreach.leads where company_number=%s",
                (bad,))
    assert cur.fetchone() == ("parked", 1)
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


# --------------------------------------------------------------------------- #
#  check_grounding — the hard anti-hallucination gate for invented names
# --------------------------------------------------------------------------- #
def test_grounding_rejects_an_invented_name_when_no_contact_is_on_file():
    """The exact production failure: 'Hi John,' on a lead with no contact name."""
    body = "Hi John,\n\nYour firm handles a lot of invoicing. Kind regards, Finlay"
    v = draft.check_grounding(body, contact_name=None, company_name="Bond Electrics Ltd")
    assert v and "invented name" in v[0]


def test_grounding_rejects_a_name_that_is_not_the_verified_contact():
    body = "Dear Robert,\n\nYour roofing work is well regarded. Kind regards, Finlay"
    v = draft.check_grounding(body, contact_name="SMITH, John Andrew",
                              company_name="1st Active Roofing Limited")
    assert v and "not the contact" in v[0]


def test_grounding_accepts_the_verified_contact_first_name():
    body = "Dear John,\n\nYour firm handles a lot of invoicing. Kind regards, Finlay"
    assert draft.check_grounding(body, contact_name="SMITH, John Andrew",
                                 company_name="Bond Electrics Ltd") == []


def test_grounding_accepts_greeting_the_business_by_a_word_of_its_own_name():
    """'Dear Adam,' for 'Adam Partridge Auctioneers' is greeting the business, not a
    person — the token is a word of the company name, so it is grounded."""
    assert draft.check_grounding("Dear Adam,\n\nYour salerooms... Kind regards, Finlay",
                                 contact_name=None,
                                 company_name="Adam Partridge Auctioneers & Valuers") == []


def test_grounding_accepts_the_business_greeting_and_generic_openers():
    assert draft.check_grounding("Dear Acme Joinery,\n\nYou... Kind regards, Finlay",
                                 contact_name=None, company_name="ACME JOINERY LTD") == []
    assert draft.check_grounding("Hi there,\n\nYou... Kind regards, Finlay",
                                 contact_name=None, company_name="Acme Ltd") == []


# --- place + statistic claims, checked against the FACTS constants ---------- #
def _facts(**kw):
    from outreach import facts as f
    kw.setdefault("company_name", "Acme Joinery")
    return f.build(**kw)


def test_grounding_rejects_a_place_that_is_not_the_resolved_location():
    """The wrong-location failure: a town nobody verified, asserted as fact."""
    body = ("Dear Acme Joinery,\n\nMost firms in Westbury-On-Severn still wait on "
            "bank transfers. Kind regards, Finlay")
    v = draft.check_grounding(body, contact_name=None, company_name="Acme Joinery",
                              lead_facts=_facts())
    assert v and "Westbury-On-Severn" in v[0]


def test_grounding_accepts_the_resolved_location():
    body = ("Dear Acme Joinery,\n\nMost firms in Hull still wait on bank transfers. "
            "Kind regards, Finlay")
    assert draft.check_grounding(
        body, contact_name=None, company_name="Acme Joinery",
        lead_facts=_facts(location="Hull", location_source="places_listing")) == []


@pytest.mark.parametrize("phrase", [
    "across the UK", "in England", "around the county", "in your area"])
def test_grounding_allows_generic_geography(phrase):
    """These assert nothing specific about this lead, so they are not location claims."""
    body = f"Dear Acme Joinery,\n\nTrades {phrase} wait on transfers. Kind regards, Finlay"
    assert draft.check_grounding(body, contact_name=None, company_name="Acme Joinery",
                                 lead_facts=_facts()) == []


def test_grounding_rejects_a_partially_matching_place():
    """'Greater Manchester' must not pass just because 'Manchester' was resolved — the
    claim is a different, larger area."""
    body = ("Dear Acme Joinery,\n\nFirms across Greater Manchester wait on transfers. "
            "Kind regards, Finlay")
    v = draft.check_grounding(
        body, contact_name=None, company_name="Acme Joinery",
        lead_facts=_facts(location="Manchester", location_source="places_listing"))
    assert v and "Greater Manchester" in v[0]


@pytest.mark.parametrize("claim", [
    "Your 9.9 rating on Checkatrade speaks for itself.",
    "With 500 five-star reviews behind you, ",
    "After 20 years in the trade, "])
def test_grounding_rejects_an_unverifiable_statistic(claim):
    """A scraped number about the recipient — the '9.9 on Checkatrade' that reached a
    real draft came from a signal that had read the wrong website entirely."""
    body = f"Dear Acme Joinery,\n\n{claim}Kind regards, Finlay"
    v = draft.check_grounding(body, contact_name=None, company_name="Acme Joinery",
                              lead_facts=_facts())
    assert any("statistic" in x for x in v)


def test_grounding_does_not_flag_ordinary_prose_numbers():
    body = ("Dear Acme Joinery,\n\nIt takes about ten minutes to set up, and I can show "
            "you 1 example. Kind regards, Finlay")
    assert not any("statistic" in x for x in draft.check_grounding(
        body, contact_name=None, company_name="Acme Joinery", lead_facts=_facts()))


def test_grounding_uses_the_facts_contact_not_the_stale_argument():
    """When a facts block is supplied it is authoritative — decision-maker resolution
    writes the contact there, so a draft may greet by it."""
    body = "Dear Robert,\n\nYour joinery work... Kind regards, Finlay"
    assert draft.check_grounding(
        body, contact_name=None, company_name="Acme Joinery",
        lead_facts=_facts(contact_name="Robert", contact_name_source="ch_officer")) == []


def test_a_lead_without_resolved_facts_is_not_drafted(db_rollback):
    """The readiness gate: drafting waits on enrichment resolving the constants rather
    than proceeding from a free-text signal. This is what forces enrichment to do its
    job instead of the drafter guessing."""
    import uuid
    cur = db_rollback.cursor()
    cn = f"NOFACTS_{uuid.uuid4().hex[:8]}"
    cur.execute("insert into outreach.leads (company_number, company_name, company_type, "
                "subscriber_class, state) values (%s,'Nofacts Ltd','ltd','corporate','enriched')",
                (cn,))
    cur.execute("insert into outreach.enrichment (company_number, website, contact_email, "
                "email_verified, signal) values (%s,'https://x.co','info@x.co',true,'sig')",
                (cn,))

    class _MustNotRun:
        """Fires only for THIS lead: the backlog is shared, so other rows legitimately
        get drafted in the same batch and are not what this test is about."""

        def complete(self, prompt, **k):
            if "Nofacts Ltd" in prompt:
                raise AssertionError("drafted a lead whose constants were never resolved")
            return type("R", (), {"text": _payload(
                "a subject", "Hi there, a note from SettlePay. Payments are handled by "
                "FCA-regulated partners. Reply unsubscribe to opt out. "
                "Kind regards, Finlay Salisbury SettlePay")})()

    draft.run(provider=_MustNotRun(), cur=cur, limit=50)
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "enriched"        # still waiting, not discarded


def test_grounding_is_wired_into_the_hard_gate(monkeypatch, db_rollback):
    """A model that invents a greeting must not be able to persist a draft — even if
    every compliance element is present. This is the retry+reject path end to end."""
    import uuid

    from outreach.llm import LLMResult

    cn = f"TEST-{uuid.uuid4().hex[:8]}"
    payload = json.dumps({"subject": "getting paid faster",
                          "body": ("Hi John,\n\nMost trades wait on bank transfers. "
                                   "SettlePay gives you a branded card page; funds are held "
                                   "by FCA-regulated partners. Reply unsubscribe to opt out.\n\n"
                                   "Kind regards,\nFinlay Salisbury\nSettlePay")})

    class _Invents:
        def complete(self, *a, **k):
            return LLMResult(text=payload, provider="test")

    with pytest.raises(draft.EnvelopeViolation) as e:
        draft.draft_one(cn, "Bond Electrics Ltd", "electricians", provider=_Invents(),
                        cur=db_rollback, contact_name=None)
    assert any("invented name" in v for v in e.value.violations)


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
                "contact_name, contact_tier, email_verified, signal, facts) "
                "values (%s,'https://x.co','j.smith@x.co','SMITH, John','named',true,'sig',"
                "%s::jsonb)",
                (cn, facts.dumps(facts.build(
                    company_name="Acme Ltd", contact_name="SMITH, John",
                    contact_name_source="ch_officer_verified_email"))))
    seen = {}

    class _P:
        def complete(self, prompt, **k):
            # capture only THIS lead's prompt — the backlog is shared, so the batch may
            # legitimately contain other rows before it
            if "Acme Ltd" in prompt:
                seen["prompt"] = prompt
            import json as _j
            return type("R", (), {"text": _j.dumps({
                "subject": "payments at acme",
                "body": ("Dear John,\n\nA note from SettlePay. Payments are handled by "
                         "FCA-regulated partners. Reply unsubscribe to opt out.\n\n"
                         "Kind regards,\nFinlay Salisbury\nSettlePay")})})()

    draft.run(provider=_P(), cur=cur, limit=50)
    # the name reaches the model as a resolved CONSTANT plus the greeting instruction
    assert 'Dear John,' in seen["prompt"]
    assert "contact_name: SMITH, John" in seen["prompt"]


def test_a_lead_parked_by_drafting_retries_drafting_not_enrichment(db_rollback):
    """Its contact and constants are already good — it was our writing that failed.
    Sending it back through enrichment would spend verifier credits to re-learn what we
    already know."""
    import uuid

    from outreach import config, enrich

    cur = db_rollback.cursor()
    cn = f"DRAFTPARK_{uuid.uuid4().hex[:8]}"
    cur.execute("insert into outreach.leads (company_number, company_name, company_type, "
                "subscriber_class, state) values (%s,%s,'ltd','corporate','enriched')", (cn, cn))
    cur.execute("insert into outreach.enrichment (company_number, website, contact_email, "
                "email_verified, signal, facts) "
                "values (%s,'https://x.co','info@x.co',true,'sig',%s::jsonb)",
                (cn, facts.dumps(facts.build(company_name="Park Co Ltd"))))

    overlong = _payload("payments at park co",
                        "SettlePay FCA-regulated partners unsubscribe " + "word " * 130)
    draft.run(provider=_ScriptedProvider({"Park Co Ltd": overlong}), cur=cur)
    cur.execute("select state::text, parked_reason from outreach.leads where company_number=%s",
                (cn,))
    state, reason = cur.fetchone()
    assert state == "parked" and reason.startswith("draft ")

    cur.execute("update outreach.leads set parked_at = now() - interval '48 hours' "
                "where company_number=%s", (cn,))
    cur.execute(enrich._BACKLOG_SQL, (config.PARK_RETRY_HOURS, 5000))
    assert cn not in {r[0] for r in cur.fetchall()}      # enrichment leaves it alone

    compliant = _payload("payments at park co",
                         "Hi Park Co, a note from SettlePay. Payments are handled by "
                         "FCA-regulated partners. Reply unsubscribe to opt out. "
                         "Kind regards, Finlay Salisbury SettlePay")
    draft.run(provider=_ScriptedProvider({"Park Co Ltd": compliant}), cur=cur)
    cur.execute("select state::text, parked_at from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone() == ("drafted", None)


def test_a_catch_all_contact_is_not_drafted_until_we_decide_to_send_to_it(db_rollback,
                                                                          monkeypatch):
    """'risky' leads were enriched, drafted (paid), human-reviewed, approved, scheduled —
    and then permanently refused at send.py because RISKY_SEND_ENABLED is off. Full cost,
    zero possibility of delivery."""
    import uuid

    from outreach import config, draft

    cur = db_rollback.cursor()
    cn = f"RISKY_{uuid.uuid4().hex[:8]}"
    cur.execute("insert into outreach.leads (company_number, company_name, company_type, "
                "subscriber_class, state) values (%s,'Risky Co Ltd','ltd','corporate','enriched')",
                (cn,))
    cur.execute("insert into outreach.enrichment (company_number, website, contact_email, "
                "contact_tier, email_verified, signal, facts) "
                "values (%s,'https://x.co','info@x.co','risky',true,'sig',%s::jsonb)",
                (cn, facts.dumps(facts.build(company_name="Risky Co Ltd"))))

    compliant = _payload("payments at risky co",
                         "Hi Risky Co, a note from SettlePay. Payments are handled by "
                         "FCA-regulated partners. Reply unsubscribe to opt out. "
                         "Kind regards, Finlay Salisbury SettlePay")
    monkeypatch.setattr(config, "RISKY_SEND_ENABLED", False)
    draft.run(provider=_ScriptedProvider({"Risky Co Ltd": compliant}), cur=cur)
    cur.execute("select count(*) from outreach.drafts where company_number=%s", (cn,))
    assert cur.fetchone()[0] == 0
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "enriched"      # waiting on the decision, not discarded

    # ...and it is drafted the moment that decision is made
    monkeypatch.setattr(config, "RISKY_SEND_ENABLED", True)
    draft.run(provider=_ScriptedProvider({"Risky Co Ltd": compliant}), cur=cur)
    cur.execute("select count(*) from outreach.drafts where company_number=%s", (cn,))
    assert cur.fetchone()[0] == 1
