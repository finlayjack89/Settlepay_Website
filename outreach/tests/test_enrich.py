import uuid

import httpx
import pytest

from outreach import enrich, verify

pytestmark = pytest.mark.floor_d


# ---- pick_contact_email (pure) ----
def test_prefers_generic_over_personal():
    emails = ["john.smith@acme.co.uk", "info@acme.co.uk", "jane@acme.co.uk"]
    assert enrich.pick_contact_email(emails, prefer_domain="acme.co.uk") == "info@acme.co.uk"


def test_prefers_own_domain():
    emails = ["info@aggregator.com", "contact@acme.co.uk"]
    assert enrich.pick_contact_email(emails, prefer_domain="acme.co.uk") == "contact@acme.co.uk"


def test_none_when_no_emails():
    assert enrich.pick_contact_email([], prefer_domain="acme.co.uk") is None


def test_rejects_freemail_scraped_off_page():
    # a font author's gmail leaked in markup must never be picked as the contact
    assert enrich.pick_contact_email(["impallari@gmail.com"], prefer_domain="ellipse.co.uk") is None


def test_rejects_off_domain_contact():
    # an address on a different domain (e.g. a registry) is not the company's own
    assert enrich.pick_contact_email(["info@lursoft.lv"], prefer_domain="acme.co.uk") is None


def test_picks_generic_on_own_domain_only():
    emails = ["ceo@acme.co.uk", "info@acme.co.uk", "info@partner.com"]
    assert enrich.pick_contact_email(emails, prefer_domain="acme.co.uk") == "info@acme.co.uk"


# ---- verify_email maps MillionVerifier result (fake client) ----
class _FakeMVResponse:
    def __init__(self, result):
        self._result = result

    def json(self):
        return {"result": self._result}


class _FakeMVClient:
    def __init__(self, result):
        self._result = result

    def get(self, *a, **k):
        return _FakeMVResponse(self._result)


# the verifier chain normalises each provider to one vocabulary: 'disposable' collapses
# to 'invalid' (both mean discard), the rest pass through.
@pytest.mark.parametrize("result,expected_verified,expected_res", [
    ("ok", True, "ok"), ("catch_all", False, "catch_all"), ("unknown", False, "unknown"),
    ("invalid", False, "invalid"), ("disposable", False, "invalid"),
])
def test_verify_email_mapping(result, expected_verified, expected_res):
    verify.reset_exhausted()
    verified, res = enrich.verify_email("x@y.com", client=_FakeMVClient(result))
    assert verified is expected_verified and res == expected_res


class _TimeoutMVClient:
    def get(self, *a, **k):
        raise httpx.ReadTimeout("boom")


def test_verify_email_timeout_is_not_fatal():
    # a transient verify timeout must degrade to unverifiable, never raise (one slow
    # verify previously aborted an entire enrichment batch)
    verified, res = enrich.verify_email("x@y.com", api_key="k", client=_TimeoutMVClient())
    assert verified is False and res == "verify_error"


# ---- enrich_one verified vs discarded (DB, rolled back) ----
def _seed_lead(cur, company_number):
    cur.execute(
        "insert into outreach.leads (company_number, company_name, company_type, "
        "subscriber_class, state) values (%s,%s,'ltd','corporate','discovered')",
        (company_number, company_number),
    )


def test_enrich_one_verified_advances_to_enriched(db_rollback, monkeypatch):
    cur = db_rollback.cursor()
    cn = f"ENR_OK_{uuid.uuid4().hex[:8]}"
    _seed_lead(cur, cn)
    monkeypatch.setattr(enrich, "scrape_emails", lambda url, client=None: ["info@acme.co.uk"])
    res = enrich.enrich_one(cn, "https://acme.co.uk", "growing local agent",
                            cur=cur, verifier=lambda e: (True, "ok"), guess_generics=False)
    assert res["verified"] is True and res["email"] == "info@acme.co.uk"
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "enriched"
    cur.execute("select website, signal, email_verified from outreach.enrichment where company_number=%s", (cn,))
    site, signal, verified = cur.fetchone()
    assert site and signal and verified is True


def test_enrich_one_unverifiable_is_discarded(db_rollback, monkeypatch):
    cur = db_rollback.cursor()
    cn = f"ENR_BAD_{uuid.uuid4().hex[:8]}"
    _seed_lead(cur, cn)
    monkeypatch.setattr(enrich, "scrape_emails", lambda url, client=None: ["info@acme.co.uk"])
    res = enrich.enrich_one(cn, "https://acme.co.uk", "signal",
                            cur=cur, verifier=lambda e: (False, "invalid"), guess_generics=False)
    assert res["verified"] is False
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "discarded"  # never left contactable


def test_firecrawl_fallback_used_when_httpx_finds_nothing(db_rollback, monkeypatch):
    cur = db_rollback.cursor()
    cn = f"ENR_FC_{uuid.uuid4().hex[:8]}"
    _seed_lead(cur, cn)
    monkeypatch.setattr(enrich, "scrape_emails", lambda url, client=None: [])      # httpx blank
    monkeypatch.setattr(enrich.config, "FIRECRAWL_API_KEY", "fc-test")
    monkeypatch.setattr(enrich, "firecrawl_scrape_emails", lambda url, **kw: ["info@acme.co.uk"])
    res = enrich.enrich_one(cn, "https://acme.co.uk", "sig", cur=cur, verifier=lambda e: (True, "ok"), guess_generics=False)
    assert res["email"] == "info@acme.co.uk" and res["verified"] is True
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "enriched"


def test_firecrawl_fallback_skipped_without_key(db_rollback, monkeypatch):
    cur = db_rollback.cursor()
    cn = f"ENR_NK_{uuid.uuid4().hex[:8]}"
    _seed_lead(cur, cn)
    monkeypatch.setattr(enrich, "scrape_emails", lambda url, client=None: [])
    monkeypatch.setattr(enrich.config, "FIRECRAWL_API_KEY", None)                  # no key
    calls = []
    monkeypatch.setattr(enrich, "firecrawl_scrape_emails",
                        lambda url, **kw: calls.append(url) or ["x@y.com"])
    res = enrich.enrich_one(cn, "https://acme.co.uk", "sig", cur=cur, verifier=lambda e: (True, "ok"), guess_generics=False)
    assert res["email"] is None and not calls           # fallback never called
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "parked"


def test_enrich_one_no_email_is_parked_not_discarded(db_rollback, monkeypatch):
    """'no_email' says OUR SEARCH found nothing — scrape_emails cannot tell "no address
    published" apart from a wrong website, a JS-rendered contact page, or a site that was
    briefly down. Discarding it destroyed 267 leads on the live database, each already
    paid for in Places credit, a Firecrawl resolve and a Gemini call, and each then
    hidden from the retry by the very row that recorded the failure."""
    cur = db_rollback.cursor()
    cn = f"ENR_NONE_{uuid.uuid4().hex[:8]}"
    _seed_lead(cur, cn)
    monkeypatch.setattr(enrich, "scrape_emails", lambda url, client=None: [])
    monkeypatch.setattr(enrich.config, "FIRECRAWL_API_KEY", None)  # keep offline (no fallback)
    res = enrich.enrich_one(cn, "https://acme.co.uk", "signal", cur=cur,
                            verifier=lambda e: (True, "ok"), guess_generics=False)
    assert res["email"] is None and res["verified"] is False
    cur.execute("select state::text, park_count, parked_reason "
                "from outreach.leads where company_number=%s", (cn,))
    state, count, reason = cur.fetchone()
    assert state == "parked" and count == 1 and "no_email" in reason


# ---- guess-and-verify info@ (opt-in: it costs a verifier credit per prefix) ----
def test_guess_verify_finds_generic_when_the_site_publishes_nothing(db_rollback, monkeypatch):
    """Guessing is now a fallback behind ENRICH_GUESS_GENERICS rather than the opening
    move: scraping is free, guessing spends a credit per prefix on an address nobody has
    claimed exists."""
    monkeypatch.setattr(enrich.config, "ENRICH_GUESS_GENERICS", True)
    monkeypatch.setattr(enrich.config, "FIRECRAWL_API_KEY", None)
    cur = db_rollback.cursor()
    cn = f"ENR_GUESS_{uuid.uuid4().hex[:8]}"
    _seed_lead(cur, cn)
    monkeypatch.setattr(enrich, "scrape_emails", lambda url, client=None: [])
    res = enrich.enrich_one(
        cn, "https://acme.co.uk", "sig", cur=cur,
        verifier=lambda e: (e == "info@acme.co.uk", "ok" if e == "info@acme.co.uk" else "invalid"))
    assert res["email"] == "info@acme.co.uk" and res["verified"] is True
    cur.execute("select scraped->>'source' from outreach.enrichment where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "guess"


def test_guess_falls_back_to_scrape_when_generics_fail(db_rollback, monkeypatch):
    cur = db_rollback.cursor()
    cn = f"ENR_GFB_{uuid.uuid4().hex[:8]}"
    _seed_lead(cur, cn)
    monkeypatch.setattr(enrich, "scrape_emails", lambda url, client=None: ["team@acme.co.uk"])
    # generic guesses all fail; only the scraped (non-generic) own-domain address verifies
    res = enrich.enrich_one(
        cn, "https://acme.co.uk", "sig", cur=cur,
        verifier=lambda e: (e == "team@acme.co.uk", "ok" if e == "team@acme.co.uk" else "catch_all"))
    assert res["email"] == "team@acme.co.uk" and res["verified"] is True
    cur.execute("select scraped->>'source' from outreach.enrichment where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "httpx"


# ---- catch-all "risky" tier ----
def test_contact_tier_mapping():
    assert enrich.contact_tier("ok") == "verified"
    assert enrich.contact_tier("catch_all", accept_catch_all=True) == "risky"
    assert enrich.contact_tier("catch_all", accept_catch_all=False) is None
    assert enrich.contact_tier("invalid") is None
    assert enrich.contact_tier("verify_error") is None


def test_catch_all_accepted_as_risky_tier(db_rollback, monkeypatch):
    cur = db_rollback.cursor()
    cn = f"ENR_CA_{uuid.uuid4().hex[:8]}"
    _seed_lead(cur, cn)
    monkeypatch.setattr(enrich, "scrape_emails", lambda url, client=None: ["info@acme.co.uk"])
    monkeypatch.setattr(enrich.config, "ACCEPT_CATCH_ALL", True)
    res = enrich.enrich_one(cn, "https://acme.co.uk", "sig", cur=cur,
                            verifier=lambda e: (False, "catch_all"), guess_generics=False)
    assert res["tier"] == "risky" and res["email"] == "info@acme.co.uk"
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "enriched"  # reachable, kept (not discarded)
    cur.execute("select contact_tier, email_verified from outreach.enrichment where company_number=%s", (cn,))
    tier, verified = cur.fetchone()
    assert tier == "risky" and verified is False  # risky, not full-confidence verified


def test_catch_all_discarded_when_disabled(db_rollback, monkeypatch):
    """Still terminal, deliberately: the verifier ANSWERED, and retrying the same
    address returns the same answer. Only a failure to obtain an address at all
    ('no_email', 'recipient_mismatch') parks."""
    cur = db_rollback.cursor()
    cn = f"ENR_CAX_{uuid.uuid4().hex[:8]}"
    _seed_lead(cur, cn)
    monkeypatch.setattr(enrich, "scrape_emails", lambda url, client=None: ["info@acme.co.uk"])
    monkeypatch.setattr(enrich.config, "ACCEPT_CATCH_ALL", False)
    res = enrich.enrich_one(cn, "https://acme.co.uk", "sig", cur=cur,
                            verifier=lambda e: (False, "catch_all"), guess_generics=False)
    assert res["tier"] is None
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "discarded"


# --------------------------------------------------------------------------- #
#  A verifier OUTAGE is not a verdict about the address
# --------------------------------------------------------------------------- #
def _discovered(cur, cn):
    cur.execute(
        "insert into outreach.leads (company_number, company_name, company_type, "
        "subscriber_class, state) values (%s,%s,'ltd','corporate','discovered')", (cn, cn))


def test_a_verifier_outage_defers_the_lead_instead_of_discarding_it(db_rollback):
    """On 2026-07-20 the MillionVerifier balance went negative, every check returned
    'error', and 178 leads with perfectly good contact addresses were discarded in a
    day. 'The verifier said no' and 'the verifier did not answer' are different facts."""
    import uuid
    from outreach import enrich
    cur = db_rollback.cursor()
    cn = f"DEF_{uuid.uuid4().hex[:8]}"
    _discovered(cur, cn)
    g = {"email": "info@acme.co.uk", "verified": False, "result": "error",
         "scrape_source": "httpx", "candidates": ["info@acme.co.uk"], "fit": None}
    out = enrich._persist(cn, "https://acme.co.uk", "sig", g, cur=cur)

    assert out["deferred"] is True
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "discovered"        # NOT discarded


def test_a_deferred_lead_writes_no_enrichment_row_so_the_backlog_retries_it(db_rollback):
    """The backlog selects leads with no enrichment row. A row saying 'error' would
    both discard the lead and hide it from the retry — permanent loss from a
    temporary outage."""
    import uuid
    from outreach import enrich
    cur = db_rollback.cursor()
    cn = f"DEF_{uuid.uuid4().hex[:8]}"
    _discovered(cur, cn)
    g = {"email": "info@acme.co.uk", "verified": False, "result": "verify_error",
         "scrape_source": "httpx", "candidates": [], "fit": None}
    enrich._persist(cn, "https://acme.co.uk", "sig", g, cur=cur)

    cur.execute("select count(*) from outreach.enrichment where company_number=%s", (cn,))
    assert cur.fetchone()[0] == 0
    cur.execute(enrich._BACKLOG_SQL, (enrich.config.PARK_RETRY_HOURS, 50000))
    assert cn in {r[0] for r in cur.fetchall()}


def test_a_real_negative_verdict_still_discards(db_rollback):
    """The deferral must not become a way for undeliverable addresses to survive."""
    import uuid
    from outreach import enrich
    cur = db_rollback.cursor()
    cn = f"DEF_{uuid.uuid4().hex[:8]}"
    _discovered(cur, cn)
    g = {"email": "info@acme.co.uk", "verified": False, "result": "invalid",
         "scrape_source": "httpx", "candidates": [], "fit": None}
    out = enrich._persist(cn, "https://acme.co.uk", "sig", g, cur=cur)
    assert out["deferred"] is False
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "discarded"


def test_an_icp_disqualification_still_discards_even_if_verification_errored(db_rollback):
    """Fit is decided from the page, not the verifier — a known bad fit shouldn't be
    held for retry just because the mailbox check happened to fail."""
    import uuid
    from outreach import enrich
    cur = db_rollback.cursor()
    cn = f"DEF_{uuid.uuid4().hex[:8]}"
    _discovered(cur, cn)
    g = {"email": "info@acme.co.uk", "verified": False, "result": "error",
         "scrape_source": "httpx", "candidates": [],
         "fit": {"available": True, "icp_fit": False, "payment_context": "fixed_till_retail",
                 "size_band": "micro", "confidence": 0.9}}
    out = enrich._persist(cn, "https://acme.co.uk", "sig", g, cur=cur)
    assert out["deferred"] is False and out["disqualified"] is True
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "discarded"


def test_enrich_stops_the_batch_when_the_verifier_looks_down(db_rollback, monkeypatch):
    """Verification is the LAST step, so a dead verifier means every scrape before it
    was paid for and thrown away."""
    import uuid
    from outreach import enrich
    cur = db_rollback.cursor()
    cns = []
    for _ in range(enrich.VERIFIER_DOWN_AFTER + 4):
        cn = f"DWN_{uuid.uuid4().hex[:8]}"
        cur.execute(
            "insert into outreach.leads (company_number, company_name, company_type, "
            "subscriber_class, state, created_at, registered_address) "
            "values (%s,%s,'ltd','corporate','discovered','1990-01-01',"
            "'{\"website\": \"https://acme.co.uk\"}'::jsonb)", (cn, cn))
        cns.append(cn)

    calls = {"n": 0}

    def _gather_stub(website, **k):
        calls["n"] += 1
        return {"email": "info@acme.co.uk", "verified": False, "result": "error",
                "scrape_source": "httpx", "candidates": []}

    monkeypatch.setattr(enrich, "_gather", _gather_stub)
    monkeypatch.setattr(enrich, "signal_and_fit", lambda *a, **k: {"available": False})
    monkeypatch.setattr(enrich, "page_text", lambda *a, **k: "")
    enrich.discover_and_run(limit=len(cns), cur=cur)
    assert calls["n"] == enrich.VERIFIER_DOWN_AFTER


# --------------------------------------------------------------------------- #
#  Signal grounding — no registered-office town, no raw SIC code
# --------------------------------------------------------------------------- #
def test_a_registered_office_town_is_never_asserted_as_a_trading_location():
    """A Ltd's registered office is usually its accountant. Only a Places locality (a
    real business listing) may seed 'in <town>' — this is why a Cheshire auctioneer was
    being placed in Westbury-on-Severn."""
    assert enrich.trading_town("Westbury-On-Severn", "companies_house_advanced_search") is None
    assert enrich.trading_town("Hull", "places") == "Hull"


def test_a_bare_sic_code_is_not_emitted_as_a_vertical():
    """stats.sic_label falls through to the raw code for unmapped SICs; it must not
    reach a signal as '— 47190 in ...'."""
    assert enrich.usable_vertical("47190") is None
    assert enrich.usable_vertical("Unknown") is None
    assert enrich.usable_vertical("Accountants") == "Accountants"


def test_factual_signal_omits_what_it_cannot_stand_behind():
    # CH lead: no trustworthy town, unmapped SIC -> name only
    assert enrich.factual_signal(
        "MEWS AUCTION ROOMS LIMITED",
        enrich.usable_vertical("47190"),
        enrich.trading_town("Westbury-On-Severn", "companies_house_advanced_search"),
    ) == "MEWS AUCTION ROOMS LIMITED"
    # Places lead: real vertical + real trading town
    assert enrich.factual_signal(
        "24hr Electrical Services Ltd", enrich.usable_vertical("Electricians"),
        enrich.trading_town("Hull", "places"),
    ) == "24hr Electrical Services Ltd — Electricians in Hull"


@pytest.mark.parametrize("address,town", [
    ("21 Cavendish St, Harrogate HG1 4NT, UK", "Harrogate"),
    ("5 Bojea Industrial Estate, St Austell PL25 5RJ, UK", "St Austell"),
    ("Unit 4, Westbury-On-Severn GL14 1PA, United Kingdom", "Westbury-On-Severn"),
    ("Some Street, London, UK", "London"),
    ("HG1 4NT, UK", None),          # nothing but a postcode
    ("", None), (None, None),
])
def test_places_locality_is_parsed_out_of_the_formatted_address(address, town):
    """Places kept the town ONLY inside the formatted string, so leads had no admissible
    locality and their drafts could name no town at all."""
    from outreach import places
    assert places.locality_of(address) == town


def test_a_parsed_locality_is_still_gated_on_a_trading_source():
    """Parsing the town does not make it assertable — provenance still decides."""
    formatted = "21 Cavendish St, Harrogate HG1 4NT, UK"
    assert enrich.trading_town(None, "places", formatted) == "Harrogate"
    assert enrich.trading_town(None, "companies_house_advanced_search", formatted) is None


# --------------------------------------------------------------------------- #
#  Verifier-credit policy — credits belong to named contacts, not to info@ guesses
# --------------------------------------------------------------------------- #
def test_a_published_address_is_verified_but_generics_are_not_guessed(monkeypatch):
    """Blind guessing burns one credit per prefix on addresses nobody claims exist.
    Scraping first means the single credit we do spend is on an address the business
    wrote down itself."""
    monkeypatch.setattr(enrich.config, "ENRICH_GUESS_GENERICS", False)
    monkeypatch.setattr(enrich, "scrape_emails", lambda *a, **k: ["studio@acme.co.uk"])
    calls = []

    def _verifier(addr):
        calls.append(addr)
        return True, "ok"

    out = enrich._gather("https://acme.co.uk", verifier=_verifier)
    assert out["email"] == "studio@acme.co.uk" and out["scrape_source"] == "httpx"
    assert calls == ["studio@acme.co.uk"]            # exactly one credit, on a real address


def test_no_published_address_spends_no_verifier_credits(monkeypatch):
    """The expensive old behaviour: four guesses, four credits, for a lead we end up
    discarding anyway."""
    monkeypatch.setattr(enrich.config, "ENRICH_GUESS_GENERICS", False)
    monkeypatch.setattr(enrich, "scrape_emails", lambda *a, **k: [])
    monkeypatch.setattr(enrich.config, "FIRECRAWL_API_KEY", None)
    calls = []

    out = enrich._gather("https://acme.co.uk",
                         verifier=lambda a: (calls.append(a), (True, "ok"))[1])
    assert out["email"] is None and out["result"] == "no_email"
    assert calls == []


def test_generic_guessing_can_be_switched_back_on(monkeypatch):
    monkeypatch.setattr(enrich.config, "ENRICH_GUESS_GENERICS", True)
    monkeypatch.setattr(enrich, "scrape_emails", lambda *a, **k: [])
    monkeypatch.setattr(enrich.config, "FIRECRAWL_API_KEY", None)
    out = enrich._gather("https://acme.co.uk", verifier=lambda a: (True, "ok"))
    assert out["email"] == "info@acme.co.uk" and out["scrape_source"] == "guess"


# --------------------------------------------------------------------------- #
#  Recipient identity — one wrong domain poisons recipient, place AND pitch
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("company,email", [
    # every one of these was sitting in the live approval queue
    ("1ST ACTIVE ROOFING LIMITED", "info@checkatrade.com"),     # a trade directory
    ("CGH Electrical LTD", "info@checkatrade.com"),
    ("AGS Electrical Services UK LTD", "info@trustmark.org.uk"),  # a government scheme
    ("LUXSTON LTD", "hello@fresha.com"),                        # a booking platform
    ("WILSONLAN LIMITED", "allaffiliationiptr@heartland.com"),  # a US payments company
    ("ORIGINAL GALLERY LTD", "info@clarendonfineart.com"),      # a different gallery
])
def test_an_address_on_another_companys_domain_is_rejected(company, email):
    assert enrich.recipient_mismatch(company, email) is True


@pytest.mark.parametrize("company,email", [
    ("Rotherham Taylor Limited", "info@rtaccountants.co.uk"),   # unjudgeable -> allowed
    ("Acme Joinery Ltd", "info@acmejoinery.co.uk"),
    ("AVO Electrical Contractors LTD", "info@avoltd.co.uk"),
])
def test_a_plausible_address_survives(company, email):
    assert enrich.recipient_mismatch(company, email) is False


def test_a_missing_address_is_not_a_mismatch():
    assert enrich.recipient_mismatch("Acme Ltd", None) is False
    assert enrich.recipient_mismatch("Acme Ltd", "") is False


def test_sector_words_alone_never_match_a_domain():
    """'Electrical' is in every electrician's name — matching on it must not let one
    electrician's site be adopted for another."""
    assert enrich.name_matches_domain("Newton Electrical Contractors",
                                      "https://someoneelseelectrical.co.uk") is False


def test_a_firm_trading_under_its_initials_is_not_called_a_mismatch():
    """Rotherham Taylor -> rtaccountants.co.uk is their real site. Rejecting an acronym
    match would discard the company's own domain."""
    assert enrich.name_matches_domain("Rotherham Taylor Limited",
                                      "https://rtaccountants.co.uk") is None
    # afbrock carries the surname outright, so this is a positive match, not an abstain
    assert enrich.name_matches_domain("A F Brock and Co Ltd",
                                      "https://afbrock.co.uk") is True


def test_a_directory_domain_is_caught_by_the_denylist_regardless_of_the_name():
    """The deterministic list is what makes this class reliable — a directory is never
    the prospect however its name compares."""
    assert enrich.recipient_mismatch("CGH Electrical LTD", "info@checkatrade.com") is True
    assert enrich.recipient_mismatch("Anything At All Ltd", "hello@fresha.com") is True


def test_an_unjudgeable_name_abstains_rather_than_guessing():
    assert enrich.name_matches_domain("The Building Company Ltd", "https://tbc.co.uk") is None


def test_a_mismatched_contact_never_makes_a_lead_contactable(db_rollback):
    """The hard gate: a directory's mailbox must not promote a lead to 'enriched', however
    cleanly it verifies."""
    cur = db_rollback.cursor()
    cn = f"ENR_MM_{uuid.uuid4().hex[:8]}"
    _seed_lead(cur, cn)
    g = {"email": "info@checkatrade.com", "verified": True, "result": "ok",
         "scrape_source": "httpx", "candidates": ["info@checkatrade.com"],
         "company_name": "1ST ACTIVE ROOFING LIMITED"}
    out = enrich._persist(cn, "https://checkatrade.com", "sig", g, cur=cur)
    assert out["email"] is None and out["result"] == "recipient_mismatch"
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] != "enriched"


# --------------------------------------------------------------------------- #
#  PARKED: our failures are recoverable, verdicts are not
# --------------------------------------------------------------------------- #
def test_a_parked_lead_comes_back_to_the_backlog_after_its_cooldown(db_rollback):
    """The whole point of PARKED. The old backlog predicate was `not exists
    (enrichment)`, so writing ANY row — including one whose only content was "we found
    no email" — buried the lead permanently, and the only tool that ever recovered leads
    was a hand-written SQL migration."""
    from outreach import config, enrich
    cur = db_rollback.cursor()
    cn = f"PARK_{uuid.uuid4().hex[:8]}"
    _seed_lead(cur, cn)
    g = {"email": None, "verified": False, "result": "no_email", "scrape_source": "httpx",
         "candidates": [], "fit": None, "company_name": "Acme Ltd"}
    enrich._persist(cn, "https://acme.co.uk", "sig", g, cur=cur)

    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "parked"
    # an enrichment row EXISTS (it holds the candidates a retry needs) and the lead is
    # still findable — the two used to be mutually exclusive
    cur.execute("select count(*) from outreach.enrichment where company_number=%s", (cn,))
    assert cur.fetchone()[0] == 1

    cur.execute(enrich._BACKLOG_SQL, (config.PARK_RETRY_HOURS, 5000))
    assert cn not in {r[0] for r in cur.fetchall()}          # still cooling down

    cur.execute("update outreach.leads set parked_at = now() - interval '48 hours' "
                "where company_number=%s", (cn,))
    cur.execute(enrich._BACKLOG_SQL, (config.PARK_RETRY_HOURS, 5000))
    assert cn in {r[0] for r in cur.fetchall()}              # cooldown elapsed -> retried


def test_parking_is_bounded_and_ends_in_a_real_discard(db_rollback):
    """Parking must not become an infinite requeue: PARK_MAX attempts, then terminal."""
    from outreach import states
    cur = db_rollback.cursor()
    cn = f"PARKMAX_{uuid.uuid4().hex[:8]}"
    _seed_lead(cur, cn)
    seen = [states.park_lead(cur, cn, "enrich: no_email") for _ in range(states.PARK_MAX)]
    assert seen[:-1] == ["parked"] * (states.PARK_MAX - 1)
    assert seen[-1] == "discarded"
    cur.execute("select state::text, park_count from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone() == ("discarded", states.PARK_MAX)


def test_a_rescued_lead_rejoins_the_pipeline_and_its_park_marks_clear(db_rollback, monkeypatch):
    from outreach import enrich
    cur = db_rollback.cursor()
    cn = f"RESCUE_{uuid.uuid4().hex[:8]}"
    _seed_lead(cur, cn)
    monkeypatch.setattr(enrich, "scrape_emails", lambda url, client=None: [])
    monkeypatch.setattr(enrich.config, "FIRECRAWL_API_KEY", None)
    enrich.enrich_one(cn, "https://acme.co.uk", "sig", cur=cur,
                      verifier=lambda e: (True, "ok"), guess_generics=False)
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "parked"

    # a later pass finds the address the first one missed
    monkeypatch.setattr(enrich, "scrape_emails", lambda url, client=None: ["info@acme.co.uk"])
    enrich.enrich_one(cn, "https://acme.co.uk", "sig", cur=cur,
                      verifier=lambda e: (True, "ok"), guess_generics=False)
    cur.execute("select state::text, parked_reason, parked_at "
                "from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone() == ("enriched", None, None)


# --------------------------------------------------------------------------- #
#  vertical: the Places listing already knew, and nobody read it
# --------------------------------------------------------------------------- #
def test_vertical_falls_back_to_the_places_listing_type():
    """`vertical` resolved on 18 of 460 rows because it came only from
    sic_label(sic_codes[1]) — and sic_codes is null for all 14,870 Places leads, while
    the listing's own primary_type sat unread in registered_address."""
    from outreach import enrich
    assert enrich.vertical_from("Accountants", "electrician") == ("Accountants", "sic_label")
    assert enrich.vertical_from(None, "electrician") == ("electrician", "places_listing")
    assert enrich.vertical_from("Unknown", "dental_clinic") == ("dental clinic", "places_listing")
    # a bare unmapped SIC code is not a descriptor, and neither is a generic Places type
    assert enrich.vertical_from("47190", "establishment") == (None, None)
    assert enrich.vertical_from(None, None) == (None, None)


def test_refresh_facts_preserves_constants_it_cannot_rederive(db_rollback, monkeypatch):
    """It used to rebuild the block from scratch, so running it over an auction-ingested
    lead WIPED payment_method — a verbatim quote from the auctioneer's own site, and the
    strongest hook in the corpus — while the docstring claimed it "touches nothing else"."""
    from outreach import enrich, facts, geo
    cur = db_rollback.cursor()
    cn = f"REFRESH_{uuid.uuid4().hex[:8]}"
    cur.execute("insert into outreach.leads (company_number, company_name, company_type, "
                "subscriber_class, state, source, registered_address) "
                "values (%s,%s,'ltd','corporate','enriched','saleroom',%s::jsonb)",
                (cn, "Mews Auctions Ltd", '{"primary_type": "auction house"}'))
    block = facts.build(company_name="Mews Auctions Ltd",
                        payment_method="bank transfer", payment_method_source="site_quote",
                        vertical="auctioneer", vertical_source="platform_listing")
    cur.execute("insert into outreach.enrichment (company_number, website, contact_email, "
                "email_verified, signal, facts) values (%s,null,'info@x.co',true,'sig',%s::jsonb)",
                (cn, facts.dumps(block)))

    monkeypatch.setattr(geo, "resolve_location", lambda **kw: {"town": None, "region": None,
                                                               "source": None})
    monkeypatch.setattr(enrich, "site_identity", lambda *a, **k: {})    # no network
    # Scope the refresh to this one lead. The backlog is shared, so which other rows it
    # would pick is not this test's business — and fetching their sites takes minutes.
    monkeypatch.setattr(enrich, "_REFRESH_SQL", enrich._REFRESH_SQL.replace(
        "where l.state in ('enriched','drafted','parked')",
        f"where l.company_number = '{cn}' and l.state in ('enriched','drafted','parked')"))
    enrich.refresh_facts(limit=5, cur=cur)

    cur.execute("select facts from outreach.enrichment where company_number=%s", (cn,))
    after = facts.loads(cur.fetchone()[0])
    assert facts.value(after, "payment_method") == "bank transfer"
    assert after["payment_method"].source == "site_quote"
    assert facts.value(after, "vertical")            # not blanked by a null SIC


def test_refresh_facts_does_not_spin_on_an_unplaceable_lead(db_rollback, monkeypatch):
    """The starvation bug in its second form. Once the queue drains below one batch, a
    lead we genuinely cannot place still matches "constants missing" for ever, so every
    subsequent run re-fetched the same handful of websites. Observed live: eight
    consecutive batches, all 21 identical rows."""
    from outreach import config, enrich, facts, geo
    cur = db_rollback.cursor()
    cn = f"UNPLACEABLE_{uuid.uuid4().hex[:8]}"
    cur.execute("insert into outreach.leads (company_number, company_name, company_type, "
                "subscriber_class, state) values (%s,%s,'ltd','corporate','enriched')", (cn, cn))
    cur.execute("insert into outreach.enrichment (company_number, contact_email, "
                "email_verified, signal, facts) values (%s,'info@x.co',true,'sig',%s::jsonb)",
                (cn, facts.dumps(facts.build(company_name="Nowhere Ltd"))))

    monkeypatch.setattr(geo, "resolve_location",
                        lambda **kw: {"town": None, "region": None, "source": None})
    monkeypatch.setattr(enrich, "site_identity", lambda *a, **k: {})
    scoped = enrich._REFRESH_SQL.replace(
        "where l.state in ('enriched','drafted','parked')",
        f"where l.company_number = '{cn}' and l.state in ('enriched','drafted','parked')")
    monkeypatch.setattr(enrich, "_REFRESH_SQL", scoped)

    assert enrich.refresh_facts(limit=5, cur=cur)["refreshed"] == 1
    # still unplaceable, so it still matches the shape predicate — but the cooldown
    # keeps it out of the queue rather than letting it spin
    cur.execute(scoped, (config.FACTS_REFRESH_DAYS, 5))
    assert cur.fetchall() == []
    assert enrich.refresh_facts(limit=5, cur=cur)["refreshed"] == 0

    cur.execute("update outreach.enrichment set facts_refreshed_at = now() - interval '60 days' "
                "where company_number=%s", (cn,))
    assert enrich.refresh_facts(limit=5, cur=cur)["refreshed"] == 1   # eligible again


# --------------------------------------------------------------------------- #
#  yield: the address was found and thrown away
# --------------------------------------------------------------------------- #
def test_accepts_the_same_business_on_a_sibling_domain():
    """The single biggest source of lost yield. Of 267 leads discarded as "no email",
    107 had candidates and every one was rejected — most of them the business's own
    address on a different TLD."""
    assert enrich.pick_contact_email(
        ["info@comfortelectrical.co.uk"], prefer_domain="comfortelectrical.com",
        company_name="Comfort Electrical ltd") == "info@comfortelectrical.co.uk"
    # and when the resolved "website" was a booking platform, the real domain was the
    # one being rejected as off-domain
    assert enrich.pick_contact_email(
        ["info@thestationmg.co.uk"], prefer_domain="thestationmg.setmore.com",
        company_name="THE STATION BARBERS COLCHESTER LTD") == "info@thestationmg.co.uk"


def test_still_refuses_another_company_on_a_different_domain():
    """The relaxation must not become a way for a directory or a stranger's mailbox
    back in."""
    assert enrich.pick_contact_email(
        ["info@checkatrade.com"], prefer_domain="dchelectrical.co.uk",
        company_name="DCH Electrical") is None
    assert enrich.pick_contact_email(
        ["enquiries@ellipseaccountants.co.uk"], prefer_domain="harmanhunter.co.uk",
        company_name="HARMAN & HUNTER ACCOUNTANTS") is None


def test_accepts_freemail_only_when_it_carries_the_business_name():
    """A blanket freemail ban was a side effect, not a decision: plenty of small UK Ltds
    publish a gmail/msn address as their business contact. The local part is what
    separates the business's own mailbox from a person's."""
    assert enrich.pick_contact_email(
        ["363electrical@gmail.com"], prefer_domain="363electrical.co.uk",
        company_name="363 Electrical LTD") == "363electrical@gmail.com"
    assert enrich.pick_contact_email(
        ["aandbelectricalservices@msn.com"], prefer_domain="abelectricalbasildon.co.uk",
        company_name="A & B Electrical Services") == "aandbelectricalservices@msn.com"
    # a personal address that happened to be on the page is still refused
    assert enrich.pick_contact_email(
        ["dedaergis7@gmail.com"], prefer_domain="ee-s.co.uk",
        company_name="EES Electrical Engineering Solutions") is None
    # ...and so is a font author's, which is where this rule came from
    assert enrich.pick_contact_email(
        ["impallari@gmail.com"], prefer_domain="ellipse.co.uk",
        company_name="Ellipse Accountants") is None


def test_own_domain_still_wins_over_a_sibling_or_freemail():
    got = enrich.pick_contact_email(
        ["acmeplumbing@gmail.com", "info@acmeplumbing.com", "info@acmeplumbing.co.uk"],
        prefer_domain="acmeplumbing.co.uk", company_name="Acme Plumbing Ltd")
    assert got == "info@acmeplumbing.co.uk"


def test_mx_pregate_fails_open():
    """"We could not ask DNS" must never read as "this domain is dead" — the same
    mistake the verifier chain made with no_verifier. One wasted credit beats a
    silently skipped lead."""
    from outreach import dns_auth

    class _Broken:
        def get(self, *a, **k):
            raise httpx.ConnectError("dns down")

    dns_auth._MX_CACHE.clear()
    assert dns_auth.has_mx("acme.co.uk", client=_Broken()) is True

    class _NxDomain:
        def get(self, *a, **k):
            return type("R", (), {"raise_for_status": lambda s: None,
                                  "json": lambda s: {"Status": 3}})()

    dns_auth._MX_CACHE.clear()
    assert dns_auth.has_mx("no-such-domain-xyz.co.uk", client=_NxDomain()) is False
