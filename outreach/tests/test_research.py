import json
import uuid

import pytest

from outreach import research

pytestmark = pytest.mark.floor_d


def _lead(cur, *, domain=None, company_number=None, name=None):
    cn = company_number or f"RES_{uuid.uuid4().hex[:8]}"
    cur.execute(
        "insert into outreach.leads (company_number, company_name, company_type, "
        "subscriber_class, state, domain) values (%s,%s,'ltd','corporate','discovered',%s)",
        (cn, name or cn, domain))
    return cn


@pytest.mark.parametrize("raw,expected", [
    ("https://WWW.Acme.co.uk/contact?x=1", "acme.co.uk"),
    ("http://acme.co.uk", "acme.co.uk"),
    ("acme.co.uk/", "acme.co.uk"),
    ("//acme.co.uk", "acme.co.uk"),
    ("https://shop.acme.co.uk/a/b#frag", "shop.acme.co.uk"),
    ("https://acme.co.uk:8443/x", "acme.co.uk"),
    ("ACME.CO.UK.", "acme.co.uk"),
    ("acme", None),          # a bare word is a typo, not a domain
    ("", None),
    ("   ", None),
])
def test_normalise_domain(raw, expected):
    assert research.normalise_domain(raw) == expected


def test_normalise_domain_is_the_same_rule_the_migration_backfilled(db_rollback):
    """0009 backfilled `domain` in SQL and every write since uses this Python. If the
    two drift, half the table stops matching the dedupe lookup."""
    cur = db_rollback.cursor()
    for url in ("https://www.Acme.co.uk/contact", "http://acme.co.uk", "https://acme.co.uk/"):
        cur.execute("select lower(split_part(regexp_replace(%s, '^https?://(www\\.)?', '', 'i'), "
                    "'/', 1))", (url,))
        assert cur.fetchone()[0] == research.normalise_domain(url)


def test_find_existing_matches_a_lead_by_domain(db_rollback):
    cur = db_rollback.cursor()
    dom = f"{uuid.uuid4().hex[:10]}.co.uk"
    cn = _lead(cur, domain=dom)
    assert research.find_existing(dom, cur=cur) == {"company_number": cn, "matched_on": "lead"}


def test_find_existing_matches_an_enrichment_by_domain(db_rollback):
    cur = db_rollback.cursor()
    dom = f"{uuid.uuid4().hex[:10]}.co.uk"
    cn = _lead(cur)
    cur.execute("insert into outreach.enrichment (company_number, website, domain) "
                "values (%s,%s,%s)", (cn, f"https://{dom}", dom))
    assert research.find_existing(dom, cur=cur) == {"company_number": cn,
                                                    "matched_on": "enrichment"}


def test_find_existing_prefers_the_richest_record(db_rollback):
    """Lead, enrichment and profile can all carry the domain. The profile is the one
    worth landing on, so it has to win the tie."""
    cur = db_rollback.cursor()
    dom = f"{uuid.uuid4().hex[:10]}.co.uk"
    cn = _lead(cur, domain=dom)
    cur.execute("insert into outreach.enrichment (company_number, website, domain) "
                "values (%s,%s,%s)", (cn, f"https://{dom}", dom))
    research.save_profile(cn, dom, {"one_liner": "x"}, [], cur=cur)
    assert research.find_existing(dom, cur=cur)["matched_on"] == "profile"


def test_find_existing_matches_the_synthetic_url_key(db_rollback):
    """A manually-researched company with no Companies House match is keyed
    URL:<domain>, and re-pasting its URL must still find it."""
    cur = db_rollback.cursor()
    dom = f"{uuid.uuid4().hex[:10]}.co.uk"
    cn = _lead(cur, company_number=f"URL:{dom}")
    assert research.find_existing(dom, cur=cur)["company_number"] == cn


def test_find_existing_returns_none_for_an_unknown_domain(db_rollback):
    cur = db_rollback.cursor()
    assert research.find_existing(f"{uuid.uuid4().hex}.co.uk", cur=cur) is None


def test_research_of_a_known_domain_spends_nothing(db_rollback, monkeypatch):
    """The dedupe check runs before any fetch. If it didn't, the commonest manual
    lookup — a company we already hold — would pay to rediscover it every time."""
    cur = db_rollback.cursor()
    dom = f"{uuid.uuid4().hex[:10]}.co.uk"
    cn = _lead(cur, domain=dom)

    def _boom(*a, **k):
        raise AssertionError("nothing should be fetched for a known domain")
    monkeypatch.setattr(research, "_fetch", _boom)
    monkeypatch.setattr(research, "places_lookup", _boom)

    out = research.research_url(f"https://www.{dom}/contact", cur=cur)
    assert out == {"status": "existing", "domain": dom,
                   "company_number": cn, "matched_on": "lead"}


def test_a_bad_url_is_refused_before_anything_happens(db_rollback, monkeypatch):
    cur = db_rollback.cursor()
    monkeypatch.setattr(research, "_fetch", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    out = research.research_url("not a website", cur=cur)
    assert out["status"] == "error"


@pytest.mark.parametrize("raw,expected", [
    ('<meta property="og:site_name" content="Acme Plumbing">', "Acme Plumbing"),
    ("<title>Acme Plumbing | Emergency plumbers in Leeds</title>", "Acme Plumbing"),
    ("<title>Acme Plumbing</title>", "Acme Plumbing"),
    ("", "Acme-Plumbing".replace("-", " ").title()),
])
def test_company_name_from_page(raw, expected):
    assert research.company_name_from_page(raw, "acme-plumbing.co.uk") == expected


def test_profile_round_trips_as_structured_data(db_rollback):
    """Facts are stored as jsonb, not rendered HTML — so they stay queryable and can
    be re-rendered when the layout changes."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    facts = {"one_liner": "Mobile mechanic", "services": ["servicing", "MOT prep"],
             "payment_methods": ["cash", "bank transfer"], "hooks": ["Invoices by email"]}
    research.save_profile(cn, "acme.co.uk", facts, [{"kind": "website", "ref": "x"}], cur=cur)
    got = research.get_profile(cn, cur=cur)
    assert got["facts"] == facts and got["domain"] == "acme.co.uk"
    assert got["sources"][0]["kind"] == "website"


def test_saving_a_profile_twice_updates_rather_than_duplicates(db_rollback):
    cur = db_rollback.cursor()
    cn = _lead(cur)
    research.save_profile(cn, "acme.co.uk", {"one_liner": "before"}, [], cur=cur)
    research.save_profile(cn, "acme.co.uk", {"one_liner": "after"}, [], cur=cur)
    cur.execute("select count(*) from outreach.profiles where company_number=%s", (cn,))
    assert cur.fetchone()[0] == 1
    assert research.get_profile(cn, cur=cur)["facts"]["one_liner"] == "after"


def test_profile_facts_stay_queryable(db_rollback):
    cur = db_rollback.cursor()
    cn = _lead(cur)
    research.save_profile(cn, "acme.co.uk",
                          {"payment_methods": ["cash", "bank transfer"]}, [], cur=cur)
    cur.execute("select company_number from outreach.profiles "
                "where facts->'payment_methods' ? 'cash' and company_number = %s", (cn,))
    assert cur.fetchone()[0] == cn


def test_places_lookup_ignores_a_result_on_a_different_domain(monkeypatch):
    """A name-only Places match is as likely to be a different company in a different
    town, and it would then supply the postcode that decides the Companies House match."""
    monkeypatch.setattr(research.places, "text_search",
                        lambda *a, **k: [{"name": "Acme", "website": "https://other.co.uk"}])
    assert research.places_lookup("acme.co.uk", "Acme") is None


def test_places_lookup_keeps_a_result_on_the_same_domain(monkeypatch):
    monkeypatch.setattr(research.places, "text_search",
                        lambda *a, **k: [{"name": "Acme", "website": "https://www.acme.co.uk/"}])
    assert research.places_lookup("acme.co.uk", "Acme")["name"] == "Acme"


def test_places_unavailable_degrades_rather_than_raising(monkeypatch):
    def _down(*a, **k):
        raise research.places.PlacesUnavailable("no key")
    monkeypatch.setattr(research.places, "text_search", _down)
    assert research.places_lookup("acme.co.uk", "Acme") is None


def test_extract_profile_returns_empty_without_page_text():
    assert research.extract_profile("Acme", None, "") == {}


def test_profile_prompt_asks_for_titles_not_names_by_default(monkeypatch):
    """A named individual is personal data under UK GDPR in a way a role address is
    not, so capturing names is opt-in — off unless RESEARCH_CAPTURE_PEOPLE is set."""
    seen = {}

    class _P:
        def complete(self, prompt, **k):
            seen["prompt"] = prompt
            return type("R", (), {"text": json.dumps({"one_liner": "x", "services": [],
                                                      "payment_methods": [], "hooks": []})})()

    monkeypatch.setattr(research.config, "RESEARCH_CAPTURE_PEOPLE", False)
    research.extract_profile("Acme", "plumber", "some page text", provider=_P())
    assert "never personal names" in seen["prompt"].lower()

    monkeypatch.setattr(research.config, "RESEARCH_CAPTURE_PEOPLE", True)
    research.extract_profile("Acme", "plumber", "some page text", provider=_P())
    assert "never personal names" not in seen["prompt"].lower()


def test_extract_profile_survives_a_broken_provider(monkeypatch):
    class _P:
        def complete(self, *a, **k):
            raise RuntimeError("model down")
    assert research.extract_profile("Acme", None, "text", provider=_P()) == {}
