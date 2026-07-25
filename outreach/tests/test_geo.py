"""Where a business actually is — the location ladder.

Every UK business has an address somewhere; the problem was knowing which one we may
call theirs. These tests pin the ranking and, more importantly, the refusals.
"""
import pytest

from outreach import geo

pytestmark = pytest.mark.floor_d


class _FakeCH:
    """Answers the co-location count: how many active companies at this postcode."""

    def __init__(self, hits_by_postcode, fail=False):
        self.hits, self.fail, self.calls = hits_by_postcode, fail, []

    def advanced_search(self, *, location=None, size=1, **_):
        self.calls.append(location)
        if self.fail:
            raise RuntimeError("CH down")
        return {"hits": self.hits.get(location, 0), "items": []}


@pytest.mark.parametrize("raw,expected", [
    ("sk102bd", "SK10 2BD"), ("SK10 2BD", "SK10 2BD"),
    ("Unit 4, Colne BB8 8EG, UK", "BB8 8EG"),
    ("no postcode here", None), ("", None), (None, None),
])
def test_postcode_normalisation(raw, expected):
    assert geo.normalise_postcode(raw) == expected


# --------------------------------------------------------------------------- #
#  Shared-office detection — what makes a registered address usable at all
# --------------------------------------------------------------------------- #
def test_a_real_trading_address_is_not_shared():
    """Observed live: Ashley Waller's own saleroom shares SK11 9DU with 10 companies."""
    ch = _FakeCH({"SK11 9DU": 10})
    assert geo.registered_office_shared(ch, "SK11 9DU") is False


@pytest.mark.parametrize("hits", [417, 9175])
def test_an_accountant_or_virtual_office_is_shared(hits):
    """Observed live: 417 companies at Adam Partridge's registered office, 9,175 at a
    London virtual office. Neither says anything about where the business trades."""
    assert geo.registered_office_shared(_FakeCH({"CH4 9GB": hits}), "CH4 9GB") is True


def test_a_companies_house_outage_is_unknown_not_permission():
    """None must not be read as 'fine, use it'. An unknown location is recoverable; a
    wrong one is a claim the recipient knows is false."""
    assert geo.registered_office_shared(_FakeCH({}, fail=True), "SK11 9DU") is None


def test_no_postcode_is_unknowable():
    assert geo.registered_office_shared(_FakeCH({}), None) is None
    assert geo.registered_office_shared(None, "SK11 9DU") is None


# --------------------------------------------------------------------------- #
#  The ladder
# --------------------------------------------------------------------------- #
def _no_lookup(monkeypatch, info=None):
    """Pin postcodes.io so these tests never touch the network."""
    monkeypatch.setattr(geo, "postcode_info", lambda pc, **k: info)


def test_their_own_website_wins(monkeypatch):
    _no_lookup(monkeypatch, {"town": "Ignored", "region": "North West"})
    out = geo.resolve_location(site_town="Macclesfield", site_postcode="SK11 9DU",
                               listing_town="Somewhere Else",
                               registered_town="Chester", ch=_FakeCH({}))
    assert out["town"] == "Macclesfield" and out["source"] == "own_site"


def test_a_listing_beats_a_registered_office(monkeypatch):
    _no_lookup(monkeypatch, {"town": None, "region": "Yorkshire and The Humber"})
    out = geo.resolve_location(listing_town="Harrogate", listing_postcode="HG1 4NT",
                               registered_town="Leeds", ch=_FakeCH({}))
    assert out["town"] == "Harrogate" and out["source"] == "places_listing"


def test_a_confirmed_registered_office_is_usable(monkeypatch):
    """The user's point: every UK company HAS an address. When it is genuinely theirs,
    we should use it rather than claim we don't know where they are."""
    _no_lookup(monkeypatch, {"town": "Macclesfield", "region": "North West"})
    out = geo.resolve_location(registered_town="Macclesfield",
                               registered_postcode="SK11 9DU",
                               ch=_FakeCH({"SK11 9DU": 10}))
    assert out["town"] == "Macclesfield"
    assert out["source"] == "companies_house_confirmed"   # the label facts.build admits


def test_an_agent_registered_office_yields_the_region_but_never_the_town(monkeypatch):
    """A town we cannot claim still leaves a region we can: an accountant is nearly
    always in the same region, so 'the North West' stays true — better than nothing."""
    _no_lookup(monkeypatch, {"town": "Chester", "region": "North West"})
    out = geo.resolve_location(registered_town="Chester", registered_postcode="CH4 9GB",
                               ch=_FakeCH({"CH4 9GB": 417}))
    assert out["town"] is None
    assert out["region"] == "North West" and out["source"] == "postcodes_io"


def test_an_unverifiable_registered_office_is_treated_as_shared(monkeypatch):
    """CH unreachable => we never learned it was theirs => do not claim the town."""
    _no_lookup(monkeypatch, {"town": "Chester", "region": "North West"})
    out = geo.resolve_location(registered_town="Chester", registered_postcode="CH4 9GB",
                               ch=_FakeCH({}, fail=True))
    assert out["town"] is None


def test_nothing_in_means_nothing_claimed(monkeypatch):
    _no_lookup(monkeypatch, None)
    assert geo.resolve_location(ch=_FakeCH({})) == {
        "town": None, "region": None, "postcode": None, "source": None}


def test_a_postcode_alone_still_places_them(monkeypatch):
    """A lead with only a postcode is not a lead with no location."""
    _no_lookup(monkeypatch, {"town": "Harrogate", "region": "Yorkshire and The Humber"})
    out = geo.resolve_location(site_postcode="HG1 4NT", ch=_FakeCH({}))
    assert out["town"] == "Harrogate" and out["source"] == "own_site"


# --------------------------------------------------------------------------- #
#  postcodes.io parsing — its parish field is not a town name
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("result,town", [
    ({"parish": "Macclesfield", "admin_district": "Cheshire East"}, "Macclesfield"),
    ({"parish": "Harrogate", "admin_district": "North Yorkshire"}, "Harrogate"),
    ({"parish": None, "admin_district": "Pendle"}, "Pendle"),
    # administrative noise stripped
    ({"parish": "Westminster, unparished area", "admin_district": "Westminster"},
     "Westminster"),
    ({"parish": None, "admin_district": "City of Edinburgh"}, "Edinburgh"),
    # a unitary authority is nobody's answer to "where are you based?" — drop to region
    ({"parish": None, "admin_district": "Bath and North East Somerset"}, None),
    ({"parish": "Bournemouth, Christchurch and Poole",
      "admin_district": "Bournemouth, Christchurch and Poole"}, None),
    ({"parish": None, "admin_district": None}, None),
])
def test_town_selection_prefers_a_conversational_name(result, town):
    """Vaguely-right beats precisely-odd: returning None here still leaves the region."""
    assert geo._pick_town(result) == town
