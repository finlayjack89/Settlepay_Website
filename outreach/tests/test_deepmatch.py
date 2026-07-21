"""Trading-name -> Companies House matching.

Every fixture here is a real record from the register, and every refusal below is a real
false positive the matcher produced during development. The stakes are asymmetric: an
unmatched lead is recoverable (it stays research-only), a WRONGLY matched one gets a
stranger's director emailed about their business. So the tests weight refusals heavily.
"""
import pytest

from outreach import deepmatch
from outreach.firewall import SubscriberClass

pytestmark = pytest.mark.floor_d


class _FakeCH:
    """Serves canned advanced-search results keyed by the substring term."""

    def __init__(self, by_term: dict, broad: set = frozenset()):
        self.by_term, self.broad, self.calls = by_term, set(broad), []

    def advanced_search(self, *, company_name_includes=None, location=None, size=30, **_):
        self.calls.append((company_name_includes, location))
        if company_name_includes in self.broad and not location:
            return {"items": [{"company_number": f"{i:08d}", "company_name": f"NOISE {i} LTD",
                               "company_type": "ltd", "registered_office_address": {}}
                              for i in range(size)]}
        items = self.by_term.get((company_name_includes, location)) \
            or self.by_term.get(company_name_includes) or []
        return {"items": items, "hits": len(items)}


def _co(name, number="01234567", postcode=None, locality=None, sic=(), type_="ltd"):
    return {"company_number": number, "company_name": name, "company_type": type_,
            "sic_codes": list(sic),
            "registered_office_address": {"postal_code": postcode, "locality": locality}}


# --------------------------------------------------------------------------- #
#  Search-term construction
# --------------------------------------------------------------------------- #
def test_distinctive_tokens_drop_the_words_every_auctioneer_shares():
    assert deepmatch.distinctive_tokens("Adam Partridge Auctioneers & Valuers") == \
        ["partridge", "adam"]
    assert deepmatch.distinctive_tokens("A & C Auctions of Pendle") == ["pendle"]


def test_search_terms_try_adjacent_pairs_before_single_words():
    """`company_name_includes` matches a CONTIGUOUS substring, so the pair is the
    precise query and the single word is the fallback — 'brock' alone returns 157."""
    terms = deepmatch.search_terms("Adam Partridge Auctioneers & Valuers")
    assert terms[0] == "adam partridge"
    assert "partridge" in terms


# --------------------------------------------------------------------------- #
#  The comparison key — why the shallow matcher failed
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("trading,registered", [
    ("Adam Partridge Auctioneers & Valuers", "ADAM PARTRIDGE LIMITED"),
    ("A F Brock and Co Ltd", "A.F. BROCK & CO. LTD"),
    ("Ashley Waller Auctioneers", "ASHLEY WALLER AUCTIONS LTD"),
])
def test_shared_sector_vocabulary_is_stripped_before_comparing(trading, registered):
    assert deepmatch._compare_key(trading) == deepmatch._compare_key(registered)


def test_a_number_is_not_an_identity():
    """'1818 Auctioneers' reduces to '1818', which matches '1818 LIMITED' perfectly and
    proves nothing — this produced a real false positive."""
    assert deepmatch._is_substantive(deepmatch._compare_key("Ashley Waller Auctioneers"))
    assert not deepmatch._is_substantive(deepmatch._compare_key("1818 Auctioneers"))


# --------------------------------------------------------------------------- #
#  Domain agreement — the strongest single signal
# --------------------------------------------------------------------------- #
def test_domain_that_is_the_company_name_is_conclusive():
    assert deepmatch._domain_agreement("ADAM PARTRIDGE LIMITED", "adampartridge.co.uk") == 5


def test_domain_containing_every_distinctive_word_is_strong():
    assert deepmatch._domain_agreement("ASHLEY WALLER AUCTIONS LTD", "ashleywaller.co.uk") >= 3


def test_unrelated_domain_does_not_agree():
    assert deepmatch._domain_agreement("NORTH WEST AUCTIONS LIMITED",
                                       "1818auctioneers.co.uk") == 0


# --------------------------------------------------------------------------- #
#  Matching + the refusals that matter
# --------------------------------------------------------------------------- #
def test_finds_the_company_the_keyword_search_could_not():
    ch = _FakeCH({"adam partridge": [
        _co("ADAM PARTRIDGE LIMITED", "06603422", "CH4 9GB", "Chester", ("82990",))]})
    got = deepmatch.find_company(ch, "Adam Partridge Auctioneers & Valuers",
                                 postcode="SK10 2BD", domain="adampartridge.co.uk")
    assert got["company_number"] == "06603422"


def test_a_shared_postcode_alone_is_never_enough():
    """1818 Auctioneers and NORTH WEST AUCTIONS LIMITED both sit at LA7 7FP (J36 Auction
    Centre) and are different companies. Co-location is the classic false positive."""
    ch = _FakeCH({"1818": [
        _co("NORTH WEST AUCTIONS LIMITED", "03950131", "LA7 7FP", "Milnthorpe", ("01629",))]})
    assert deepmatch.find_company(ch, "1818 Auctioneers", postcode="LA7 7FP",
                                  domain="1818auctioneers.co.uk") is None


def test_two_equally_good_candidates_refuse_rather_than_guess():
    """A group with sibling entities at one address — picking one risks emailing the
    wrong legal person, and unknown is the recoverable answer."""
    ch = _FakeCH({"ashley waller": [
        _co("ASHLEY WALLER AUCTIONS LTD", "10753009", "SK11 9DU", "Macclesfield", ("47990",)),
        _co("ASHLEY WALLER AUCTIONS LTD", "10753010", "SK11 9DU", "Macclesfield", ("47990",)),
    ]})
    assert deepmatch.find_company(ch, "Ashley Waller Auctioneers", postcode="SK11 9DU",
                                  domain="ashleywaller.co.uk") is None


def test_a_broad_term_is_narrowed_by_the_registered_office_town():
    """'brock' returns 157 companies; the town is what makes a common surname usable."""
    ch = _FakeCH({("brock", "Stockport"): [
        _co("A.F. BROCK & CO. LTD", "02631207", "SK7 4PL", "Stockport", ("46190",))]},
        broad={"brock"})
    got = deepmatch.find_company(ch, "A F Brock and Co Ltd", locality="Stockport")
    assert got["company_number"] == "02631207"
    assert (("brock", "Stockport") in ch.calls)


def test_a_broad_term_with_no_town_is_abandoned_not_guessed():
    ch = _FakeCH({}, broad={"brock"})
    assert deepmatch.find_company(ch, "A F Brock and Co Ltd") is None


def test_a_companies_house_outage_never_produces_a_match():
    class _Broken:
        def advanced_search(self, **_):
            raise RuntimeError("CH down")
    assert deepmatch.find_company(_Broken(), "Ashley Waller Auctioneers") is None


def test_query_budget_is_bounded_per_lead():
    ch = _FakeCH({})
    deepmatch.find_company(ch, "Some Long Auction House Name Of Many Words",
                           max_queries=2)
    assert len(ch.calls) <= 2


def test_a_conclusive_match_stops_spending_queries():
    ch = _FakeCH({"ashley waller": [
        _co("ASHLEY WALLER AUCTIONS LTD", "10753009", "SK11 9DU", "Macclesfield", ("47990",))]})
    deepmatch.find_company(ch, "Ashley Waller Auctioneers", postcode="SK11 9DU",
                           domain="ashleywaller.co.uk", locality="Macclesfield")
    assert len(ch.calls) == 1


# --------------------------------------------------------------------------- #
#  PECR verdict
# --------------------------------------------------------------------------- #
def test_a_corporate_type_is_sendable_and_carries_its_evidence():
    ch = _FakeCH({"ashley waller": [
        _co("ASHLEY WALLER AUCTIONS LTD", "10753009", "SK11 9DU", "Macclesfield", ("47990",))]})
    cls, number, reason = deepmatch.classify_deep(
        ch, "Ashley Waller Auctioneers", postcode="SK11 9DU", domain="ashleywaller.co.uk")
    assert cls is SubscriberClass.CORPORATE and number == "10753009"
    assert "postcode exact" in reason and "score" in reason


def test_a_non_corporate_type_is_never_sendable():
    """PECR: a partnership is an individual subscriber — matched, but never cold-emailed."""
    ch = _FakeCH({"acreman": [
        _co("ACREMAN ST ANTIQUES LLP", "09724469", "BA7 7PX", "Castle Cary", ("47791",),
            type_="limited-partnership")]})
    cls, number, _ = deepmatch.classify_deep(ch, "Acreman St. Antiques Auction",
                                             domain="acremanstreetantiques.co.uk")
    assert cls is not SubscriberClass.CORPORATE and number == "09724469"


def test_no_match_stays_unknown():
    cls, number, reason = deepmatch.classify_deep(_FakeCH({}), "Nobody At All Auctions")
    assert cls is SubscriberClass.UNKNOWN and number is None and "no confident" in reason
