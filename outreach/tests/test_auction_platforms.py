"""The five non-EasyLive adapters, pinned to saved slices of the real rendered pages.

No network: every source is driven by a fake client whose `get_rendered` returns the
fixture markdown, so the parsers are tested against markup the sites actually served
rather than markup we imagined. The traps these cover are the ones that already bit us
once on Easy Live — reading categories from site chrome, and losing a postcode letter.
"""
import json
import pathlib

import pytest

from outreach.auctions.sources.atg import (ATGSource, BidSpotterSource, IBidderSource,
                                           TheSaleroomSource)
from outreach.auctions.sources.invaluable import InvaluableSource
from outreach.auctions.sources.liveauctioneers import LiveAuctioneersSource

pytestmark = pytest.mark.floor_d

FIX = pathlib.Path(__file__).parent / "fixtures" / "auctions"


def _fx(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


class _FakeRenderClient:
    """Serves fixture markdown for a directory URL and a profile URL; None elsewhere."""
    use_cache = False

    def __init__(self, directory: str, profile: str = "", links=(), profile_match=""):
        self.directory, self.profile = directory, profile
        self.links, self.profile_match = list(links), profile_match
        self.calls: list[str] = []

    def get_rendered(self, url, cache=None):
        self.calls.append(url)
        if self.profile_match and self.profile_match in url:
            return {"markdown": self.profile, "links": self.links, "metadata": {}}
        if "page=2" in url or "page=3" in url:
            return {"markdown": "", "links": [], "metadata": {}}   # end of the listing
        return {"markdown": self.directory, "links": [], "metadata": {}}

    def close(self):
        pass


# --------------------------------------------------------------------------- #
#  ATG (the-saleroom / BidSpotter / i-bidder) — one adapter, three brands
# --------------------------------------------------------------------------- #
ATG_DIR = _fx("atg_directory.md")
ATG_PROFILE = _fx("atg_profile.md")
ATG_LINKS = json.loads(_fx("atg_profile_links.json"))


def test_atg_directory_parses_name_postcode_country_and_activity():
    entries = ATGSource._entries(ATG_DIR)
    by_name = {e["business_name"]: e for e in entries}
    assert by_name["1818 Auctioneers"]["postcode"] == "LA7 7FP"
    assert by_name["1818 Auctioneers"]["country"] == "United Kingdom"
    assert by_name["1818 Auctioneers"]["upcoming_count"] == 20
    assert by_name["1818 Auctioneers"]["source_id"] == "1818-auctioneers"
    # a run-together address with no space in the postcode still resolves
    assert by_name["Acreman St. Antiques Auction"]["postcode"] == "DT9 3PH"


def test_atg_postcode_does_not_swallow_the_town_s_last_letter():
    """'...LondonW1W 7LT' must not become 'NW1W 7LT'. Case-insensitive matching used to
    take the 'n' off London and invent a district that doesn't exist."""
    assert ATGSource._postcode("Fitzrovia HouseLondonW1W 7LTUnited Kingdom") == "W1W 7LT"


def test_atg_recognises_non_uk_entries():
    entries = {e["business_name"]: e for e in ATGSource._entries(ATG_DIR)}
    assert entries["Absolute Auction"]["country"] == "Belgium"
    assert not ATGSource._is_uk(entries["Absolute Auction"])
    assert ATGSource._is_uk(entries["1818 Auctioneers"])


def test_atg_treats_a_missing_country_with_a_uk_postcode_as_uk():
    """An entry that just omits its country must not be silently dropped."""
    assert ATGSource._is_uk({"country": None, "postcode": "BB8 8EG"})
    assert not ATGSource._is_uk({"country": None, "postcode": None})


def test_atg_never_reads_the_phone_number():
    """The listing shows a phone right under the address; no field may ever hold it."""
    entries = ATGSource._entries(ATG_DIR)
    assert "01282 863319" not in json.dumps(entries)
    for e in entries:
        assert not any(str(v).strip().replace(" ", "").isdigit() and len(str(v)) > 8
                       for v in e.values())


def test_atg_profile_yields_the_own_website_from_the_mailto():
    """The mailto's DOMAIN is the auctioneer's own site — which skips the Firecrawl
    website search entirely. Only the domain is taken; which mailbox to contact stays
    with the enrichment stage."""
    src = TheSaleroomSource(client=_FakeRenderClient(
        ATG_DIR, ATG_PROFILE, ATG_LINKS, profile_match="auction-catalogues"))
    _, website = src._profile("https://www.the-saleroom.com/en-gb/auction-catalogues/x",
                              "1818 Auctioneers")
    assert website == "https://1818auctioneers.co.uk"


def test_atg_categories_come_from_their_blurb_not_the_site_nav():
    """Every ATG profile carries the platform's category nav. Reading categories from the
    whole page would tag every auctioneer on the platform identically — the exact trap
    Easy Live's og:description set."""
    description = ATGSource._description(ATG_PROFILE, "1818 Auctioneers")
    assert "auction" in description.lower()
    assert "How to Buy" not in description and "Price Guide" not in description


def test_atg_description_is_empty_rather_than_wrong_when_there_is_no_blurb():
    assert ATGSource._description(ATG_PROFILE, "Some Other House") == ""


def test_atg_uk_only_filter_drops_foreign_houses():
    src = TheSaleroomSource(client=_FakeRenderClient(ATG_DIR))
    src.fetch_profiles = False
    names = [ld.business_name for ld in src.iter_auctioneers()]
    assert "1818 Auctioneers" in names
    assert "Absolute Auction" not in names          # Belgium
    assert "1stBid" not in names                    # United States


def test_atg_uk_only_can_be_switched_off(monkeypatch):
    from outreach.auctions import config
    monkeypatch.setattr(config, "UK_ONLY", False)
    src = TheSaleroomSource(client=_FakeRenderClient(ATG_DIR))
    src.fetch_profiles = False
    assert "Absolute Auction" in [ld.business_name for ld in src.iter_auctioneers()]


def test_atg_paging_stops_at_the_first_empty_page():
    """Termination must come from the data, not a hardcoded page count."""
    client = _FakeRenderClient(ATG_DIR)
    src = TheSaleroomSource(client=client)
    src.fetch_profiles = False
    list(src.iter_auctioneers())
    assert any("page=2" in c for c in client.calls)
    assert not any("page=3" in c for c in client.calls)


def test_atg_limit_caps_the_walk():
    src = TheSaleroomSource(client=_FakeRenderClient(ATG_DIR))
    src.fetch_profiles = False
    assert len(list(src.iter_auctioneers(limit=2))) == 2


@pytest.mark.parametrize("cls,host", [
    (TheSaleroomSource, "the-saleroom.com"), (BidSpotterSource, "bidspotter.co.uk"),
    (IBidderSource, "i-bidder.com")])
def test_all_three_atg_brands_share_one_parser_on_their_own_host(cls, host):
    src = cls(client=_FakeRenderClient(ATG_DIR))
    src.fetch_profiles = False
    assert host in src.directory_url(1)
    assert src.directory_url(3).endswith("?page=3")
    assert list(src.iter_auctioneers(limit=1))[0].platform == cls.platform


# --------------------------------------------------------------------------- #
#  LiveAuctioneers — one page, country-grouped
# --------------------------------------------------------------------------- #
LA_DIR = _fx("liveauctioneers_directory.md")
LA_PROFILE = _fx("liveauctioneers_profile.md")


def test_liveauctioneers_takes_only_the_united_kingdom_section():
    """The directory is every country on one page; the section ends at the next country
    heading, and nothing beyond it may leak in."""
    entries = LiveAuctioneersSource._uk_entries(LA_DIR)
    names = [n for n, _, _ in entries]
    assert "1818 Auctioneers" in names
    assert "Somewhere Else" not in names          # sits under 'All Around the World'
    assert entries[0][2] == "8084"                # numeric house id as the source id


def test_liveauctioneers_address_comes_from_the_static_map_url():
    address = LiveAuctioneersSource._address(LA_PROFILE)
    assert LiveAuctioneersSource._postcode(address) == "LA7 7FP"
    assert LiveAuctioneersSource._locality(address) == "Cumbria"


def test_liveauctioneers_categories_come_from_their_own_about_section():
    description = LiveAuctioneersSource._description(LA_PROFILE, "1818 Auctioneers")
    assert "auction" in description.lower()
    assert "Price Results" not in description     # site nav must not bleed in


def test_liveauctioneers_lead_carries_no_website():
    """LiveAuctioneers exposes neither website nor email — enrichment resolves it, and
    the adapter must not pretend otherwise."""
    src = LiveAuctioneersSource(client=_FakeRenderClient(
        LA_DIR, LA_PROFILE, profile_match="/auctioneer/8084/"))
    lead = next(iter(src.iter_auctioneers(limit=1)))
    assert lead.own_website is None
    assert lead.postcode == "LA7 7FP"
    assert lead.platform == "liveauctioneers"


# --------------------------------------------------------------------------- #
#  Invaluable — paginated, server-side country filter
# --------------------------------------------------------------------------- #
IV_DIR = _fx("invaluable_directory.md")
IV_PROFILE = _fx("invaluable_profile.md")


def test_invaluable_uses_the_platforms_own_country_filter():
    """Invaluable is overwhelmingly US; filtering server-side is what stops a sweep
    spending most of its credits on houses the PECR gate can never pass."""
    assert "countryName=United+Kingdom" in InvaluableSource().directory_url(1)


def test_invaluable_country_filter_drops_out_when_uk_only_is_off(monkeypatch):
    from outreach.auctions import config
    monkeypatch.setattr(config, "UK_ONLY", False)
    assert "countryName" not in InvaluableSource().directory_url(1)


def test_invaluable_parses_the_listing_and_profile():
    src = InvaluableSource(client=_FakeRenderClient(
        IV_DIR, IV_PROFILE, profile_match="a-f-brock"))
    lead = next(iter(src.iter_auctioneers(limit=1)))
    assert lead.business_name == "A F Brock and Co Ltd"
    assert lead.source_id == "a-f-brock-and-co-ltd-5m5l8ir4qb"
    assert lead.location == "Stockport"
    assert "coins" in lead.categories and "jewellery" in lead.categories


# --------------------------------------------------------------------------- #
#  Website resolution guard — the thin sources make a wrong guess likely
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name,url", [
    # both of these came back from a real Invaluable sample run
    ("A J Cobern", "https://cascobayauctions.com/"),               # a US auction house
    ("A Victor Powell",
     "https://www.worcesternews.co.uk/news/business/11660752-peter-powell/"),  # a news article
])
def test_a_website_that_does_not_match_the_business_name_is_rejected(name, url):
    """Accepting the resolver's guess verbatim would hand the WRONG company's payment
    signal, domain and email guesses to the drafter."""
    from outreach.auctions.enrich import _name_matches_domain
    assert _name_matches_domain(name, url) is False


@pytest.mark.parametrize("name,url", [
    ("1818 Auctioneers", "https://1818auctioneers.co.uk"),
    ("A & C Auctions of Pendle", "https://pendleauctionhouse.co.uk"),
    ("Adam Partridge Auctioneers & Valuers", "https://adampartridge.co.uk"),
    ("Anglia Car Auctions Ltd", "https://angliacarauctions.co.uk"),
    ("AH CULT TRADITION LTD", "https://cultural-tradition.uk"),
    ("Acreman St. Antiques Auction", "https://acremanstreetantiques.co.uk"),
])
def test_a_genuine_website_survives_the_guard(name, url):
    from outreach.auctions.enrich import _name_matches_domain
    assert _name_matches_domain(name, url) is True


def test_the_guard_abstains_when_the_name_has_nothing_distinctive():
    """'A.S.H Auctions' is all generic words and initials — unjudgeable, so the URL is
    kept with a note rather than silently dropped."""
    from outreach.auctions.enrich import _name_matches_domain
    assert _name_matches_domain("A.S.H Auctions", "https://ashauctions.co.uk") is None


def test_a_platform_supplied_website_skips_the_guard_entirely():
    """ATG hands us the domain from the auctioneer's own mailto — that is a fact, not a
    guess, so it must not be second-guessed by a name heuristic."""
    from outreach.auctions.enrich import _resolve_website
    from outreach.auctions.models import AuctionLead
    raw = AuctionLead(platform="saleroom", business_name="Ationsss",
                      listing_url="x", source_id="y", own_website="https://ationsss.co.uk")
    assert _resolve_website(raw, resolver=None) == ("https://ationsss.co.uk", None)


def test_invaluable_stops_when_a_page_repeats_itself():
    """The listing silently serves page 1 again past the end, so 'nothing new' — not
    'nothing at all' — has to be the stop condition, or paging never terminates."""
    class _Repeating(_FakeRenderClient):
        def get_rendered(self, url, cache=None):
            self.calls.append(url)
            return {"markdown": IV_DIR, "links": [], "metadata": {}}

    client = _Repeating(IV_DIR)
    src = InvaluableSource(client=client)
    src.fetch_profiles = False
    leads = list(src.iter_auctioneers())
    assert len(leads) == len(set(ld.source_id for ld in leads))
    assert len(client.calls) == 2                 # page 1, then page 2 = all duplicates
