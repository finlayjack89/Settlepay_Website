"""Auction source — parser / dedupe / scoring / payment / brief, against saved fixtures.

No network: the EasyLive source is driven by a fake client that returns the saved
sitemap + profile HTML, so the JSON-LD parse is pinned to a real ELA page.
"""
import pathlib

import pytest

from outreach.auctions import brief, categories, dedupe, payment, score
from outreach.auctions.models import AuctionLead, EnrichedLead
from outreach.auctions.sources.easylive import EasyLiveSource

pytestmark = pytest.mark.floor_d

FIX = pathlib.Path(__file__).parent / "fixtures" / "auctions"
PROFILE = (FIX / "easylive_profile.html").read_text(encoding="utf-8", errors="replace")
SITEMAP = (FIX / "easylive_sitemap.xml").read_text(encoding="utf-8", errors="replace")


class _FakeClient:
    """Returns the saved fixtures for the sitemap + one profile; 404-equivalent (None)
    for anything else, so iter_auctioneers walks exactly one real profile."""
    use_cache = False

    def __init__(self):
        self.calls = []

    def get(self, url, cache=None):
        self.calls.append(url)
        if url.endswith("sitemap-auctioneers.xml"):
            return SITEMAP
        if "1888auctioneers" in url:
            return PROFILE
        return None

    def close(self):
        pass


# --------------------------------------------------------------------------- #
#  Source parser (JSON-LD)
# --------------------------------------------------------------------------- #
def test_sitemap_yields_the_auctioneer_urls():
    src = EasyLiveSource(client=_FakeClient())
    # only the 1888 profile resolves (others -> None), so exactly one lead comes back
    leads = list(src.iter_auctioneers())
    assert len(leads) == 1
    assert leads[0].business_name == "1888 Auctioneers"


def test_profile_json_ld_fields():
    src = EasyLiveSource(client=_FakeClient())
    lead = src._profile("https://www.easyliveauction.com/auctioneers/1888auctioneers/")
    assert lead.postcode == "B33 0SG"
    assert lead.source_id == "1888auctioneers"
    assert lead.logo_url and lead.logo_url.startswith("https://content.easyliveauction.com")
    # categories come from the auctioneer's OWN description, not ELA's site-wide nav
    assert "sporting" in lead.categories and "memorabilia" in lead.categories
    assert "classic cars" not in lead.categories        # would be ELA chrome bleed-through


def test_phone_is_never_captured():
    """The JSON-LD carries a telephone; no field on the model can hold it."""
    src = EasyLiveSource(client=_FakeClient())
    lead = src._profile("https://www.easyliveauction.com/auctioneers/1888auctioneers/")
    assert not hasattr(lead, "telephone") and not hasattr(lead, "phone")


def test_limit_caps_the_walk():
    src = EasyLiveSource(client=_FakeClient())
    assert list(src.iter_auctioneers(limit=0)) == []


# --------------------------------------------------------------------------- #
#  Categories
# --------------------------------------------------------------------------- #
def test_category_detection_prefers_longest_match():
    cats = categories.detect("We sell fine art, antiques and jewellery")
    assert "fine art" in cats and "antiques" in cats and "jewellery" in cats
    assert "art" not in cats                            # subsumed by 'fine art'


def test_category_value_ranks_specialist_over_clearance():
    fine = categories.value_score(["fine art", "jewellery"])
    general = categories.value_score(["general", "clearance"])
    assert fine > general
    assert categories.value_score([]) == 0.0


# --------------------------------------------------------------------------- #
#  Payment detection (the wedge)
# --------------------------------------------------------------------------- #
def test_payment_detects_manual_methods_and_quote():
    text = ("Payment terms. Winning bidders must pay by bank transfer or cheque within "
            "three working days of the sale. We do not accept online card payments.")
    r = payment.detect(text)
    assert r["manual"] is True
    assert "bank transfer" in r["methods"] and "cheque" in r["methods"]
    assert "bank transfer" in r["quote"].lower()


def test_payment_flags_existing_online_card():
    r = payment.detect("Pay online by card at secure checkout via Stripe.")
    assert r["online"] is True and "online card" in r["methods"]


def test_payment_empty_when_silent():
    assert payment.detect("Welcome to our auction house.")["methods"] == []


# --------------------------------------------------------------------------- #
#  Scoring
# --------------------------------------------------------------------------- #
def _lead(**kw) -> EnrichedLead:
    base = dict(platform="easylive", business_name="Test Auctions",
                listing_url="u", source_id="s", pecr_class="corporate")
    base.update(kw)
    return EnrichedLead(**base)


def test_manual_payment_dominates_the_score():
    manual = _lead(payment_methods=["bank transfer", "cheque"], categories=["antiques"],
                   upcoming_count=2, decision_maker_email="a@b.co")
    online = _lead(payment_methods=["online card"], categories=["antiques"],
                   upcoming_count=2, decision_maker_email="a@b.co")
    s_manual, _ = score.score(manual)
    s_online, _ = score.score(online)
    assert s_manual > s_online


def test_non_corporate_is_capped_research_only():
    strong = _lead(pecr_class="individual", payment_methods=["bank transfer"],
                   categories=["fine art", "jewellery"], upcoming_count=5,
                   decision_maker_email="a@b.co")
    s, breakdown = score.score(strong)
    assert s <= 25 and "pecr_cap" in breakdown


def test_score_is_zero_to_one_hundred():
    s, _ = score.score(_lead())
    assert 0 <= s <= 100


# --------------------------------------------------------------------------- #
#  Dedupe
# --------------------------------------------------------------------------- #
def test_dedupe_collapses_same_domain_keeps_highest_score():
    a = _lead(business_name="Acme (saleroom)", platform="saleroom", domain="acme.co.uk", score=40)
    b = _lead(business_name="Acme (easylive)", platform="easylive", domain="acme.co.uk", score=70)
    out = dedupe.dedupe([a, b])
    assert len(out) == 1 and out[0].score == 70
    assert "deduped 2" in " ".join(out[0].notes)


def test_dedupe_collapses_via_company_number_chain():
    # A~B share a domain; B~C share a CH number -> all one auctioneer
    a = _lead(business_name="A", domain="x.co.uk", score=10)
    b = _lead(business_name="B", domain="x.co.uk", company_number="123", score=20)
    c = _lead(business_name="C", company_number="123", score=30)
    out = dedupe.dedupe([a, b, c])
    assert len(out) == 1 and out[0].score == 30


def test_distinct_leads_are_not_merged():
    a = _lead(business_name="A", domain="a.co.uk", postcode="AB1 2CD")
    b = _lead(business_name="B", domain="b.co.uk", postcode="XY9 8ZW")
    assert len(dedupe.dedupe([a, b])) == 2


# --------------------------------------------------------------------------- #
#  Brief
# --------------------------------------------------------------------------- #
def test_brief_leads_with_the_payment_quote():
    lead = _lead(payment_quote="Winners pay by bank transfer within 3 days",
                 categories=["antiques"], decision_maker_name="SMITH, John",
                 decision_maker_email="j@acme.co.uk")
    bullets = brief.build(lead)
    assert bullets[0].startswith("Says on their site")
    assert any("John Smith" in b for b in bullets)      # human-first, not CH surname-first


def test_brief_flags_research_only_for_non_corporate():
    bullets = brief.build(_lead(pecr_class="individual"))
    assert any("research-only" in b for b in bullets)


# --------------------------------------------------------------------------- #
#  Platform resolution from a pasted link (the console's entry point)
# --------------------------------------------------------------------------- #
from outreach.auctions.sources import (  # noqa: E402
    PlatformNotSupported, platform_for_url)


@pytest.mark.parametrize("value", [
    "easylive", "easyliveauction.com", "www.easyliveauction.com",
    "https://www.easyliveauction.com/auctioneers/", "HTTPS://EasyLiveAuction.com/x?y=1"])
def test_platform_resolves_from_any_link_form(value):
    assert platform_for_url(value) == "easylive"


@pytest.mark.parametrize("value,needle", [
    ("the-saleroom.com", "no adapter"), ("bidspotter.co.uk", "no adapter"),
    ("i-bidder.com", "no adapter")])
def test_known_platform_without_adapter_says_recon_needed(value, needle):
    """A platform we recognise but haven't reconned must refuse with a reason — never
    silently scrape a site whose robots/Terms we've not read."""
    with pytest.raises(PlatformNotSupported) as e:
        platform_for_url(value)
    assert needle in str(e.value) and "recon" in str(e.value).lower()


def test_unrelated_url_is_refused():
    with pytest.raises(PlatformNotSupported):
        platform_for_url("https://example.com")


def test_the_adapter_carries_its_terms_verdict():
    """The ToS position travels with the adapter so it shows in the console + job log."""
    from outreach.auctions.sources import get_source
    note = get_source("easylive").terms_note
    assert "Terms" in note and "consent" in note
