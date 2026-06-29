import uuid

import httpx
import pytest

from outreach import enrich

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


@pytest.mark.parametrize("result,expected", [
    ("ok", True), ("catch_all", False), ("unknown", False),
    ("invalid", False), ("disposable", False),
])
def test_verify_email_mapping(result, expected):
    verified, res = enrich.verify_email("x@y.com", api_key="k", client=_FakeMVClient(result))
    assert verified is expected and res == result


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
