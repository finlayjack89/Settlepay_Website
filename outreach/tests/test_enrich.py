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
    assert res["email"] is None and not calls           # fallback never called -> discarded
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "discarded"


def test_enrich_one_no_email_is_discarded(db_rollback, monkeypatch):
    cur = db_rollback.cursor()
    cn = f"ENR_NONE_{uuid.uuid4().hex[:8]}"
    _seed_lead(cur, cn)
    monkeypatch.setattr(enrich, "scrape_emails", lambda url, client=None: [])
    monkeypatch.setattr(enrich.config, "FIRECRAWL_API_KEY", None)  # keep offline (no fallback)
    res = enrich.enrich_one(cn, "https://acme.co.uk", "signal", cur=cur,
                            verifier=lambda e: (True, "ok"), guess_generics=False)
    assert res["email"] is None and res["verified"] is False
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "discarded"


# ---- guess-and-verify info@ (the cheap discovery path) ----
def test_guess_verify_finds_generic_without_scraping(db_rollback, monkeypatch):
    cur = db_rollback.cursor()
    cn = f"ENR_GUESS_{uuid.uuid4().hex[:8]}"
    _seed_lead(cur, cn)
    called = []
    monkeypatch.setattr(enrich, "scrape_emails", lambda url, client=None: called.append(url) or ["x@y.com"])
    # only the guessed info@ on the site domain verifies
    res = enrich.enrich_one(
        cn, "https://acme.co.uk", "sig", cur=cur,
        verifier=lambda e: (e == "info@acme.co.uk", "ok" if e == "info@acme.co.uk" else "invalid"))
    assert res["email"] == "info@acme.co.uk" and res["verified"] is True
    assert not called  # scrape skipped because the guess verified
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
    cur.execute(enrich._BACKLOG_SQL, (500,))
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
