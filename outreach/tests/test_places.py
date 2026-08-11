"""Places wrapper — normalisation (phone dropped), pinned field mask, credit
metering. Hermetic: the HTTP client is faked, no live Places call."""
import pytest

from outreach import places, spend

pytestmark = pytest.mark.floor_b


def test_places_cost_is_credit_not_cash():
    # a Places call must be priced as credit-billed, and its provider must be in
    # the CREDIT set so it never counts toward the cash cap.
    assert "places" in spend.CREDIT_PROVIDERS and "places" not in spend.CASH_PROVIDERS
    c = spend.places_cost_gbp("text_search_enterprise", 1000)
    assert round(c, 2) == round(35.0 * spend.config.USD_TO_GBP, 2)


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload
        self.last = None

    def post(self, url, headers=None, json=None, timeout=None):
        self.last = {"headers": headers, "json": json}
        return _FakeResp(self._payload)


_PAYLOAD = {"places": [{
    "id": "abc123",
    "displayName": {"text": "Ridgeway Plumbing"},
    "websiteUri": "https://ridgeway.example",
    "formattedAddress": "1 High St, Otley LS21 1AA",
    "addressComponents": [{"types": ["postal_code"], "longText": "LS21 1AA"}],
    "primaryType": "plumber",
    "types": ["plumber", "point_of_interest"],
    "nationalPhoneNumber": "01943 000000",   # present in fake, must NOT survive
    "businessStatus": "OPERATIONAL",
}]}


def test_text_search_normalises_and_drops_phone(monkeypatch):
    monkeypatch.setattr(places.config, "GOOGLE_MAPS_API_KEY", "AIza-test")
    monkeypatch.setattr(spend, "ensure_under_cap", lambda cur=None: None)
    recorded = {}
    monkeypatch.setattr(spend, "record", lambda *a, **k: recorded.update(k) or recorded.update({"provider": a[0]}))

    fake = _FakeClient(_PAYLOAD)
    out = places.text_search("plumber in Otley", client=fake)

    assert len(out) == 1
    b = out[0]
    assert b["name"] == "Ridgeway Plumbing" and b["website"] == "https://ridgeway.example"
    assert b["postcode"] == "LS21 1AA" and b["primary_type"] == "plumber"
    # phone must not appear anywhere in the normalised record
    assert "01943 000000" not in str(b) and "phone" not in b
    # the pinned field mask must not request phone fields
    assert "phone" not in fake.last["headers"]["X-Goog-FieldMask"].lower()
    assert "websiteUri" in fake.last["headers"]["X-Goog-FieldMask"]
    # metered as credit-billed places spend
    assert recorded["provider"] == "places"


def test_text_search_raises_without_key(monkeypatch):
    monkeypatch.setattr(places.config, "GOOGLE_MAPS_API_KEY", None)
    with pytest.raises(places.PlacesUnavailable):
        places.text_search("x")


def test_one_failing_query_costs_one_query_not_the_whole_batch(db_rollback, monkeypatch):
    """A raise used to escape discover_to_leads entirely: every insert made earlier in
    the batch was rolled back AND discover_grid never reached its cursor write, so the
    next tick replayed the same failing query. One malformed town or a quota blip wedged
    discovery indefinitely while still looking alive."""
    import uuid

    from outreach import places

    good = f"good-{uuid.uuid4().hex[:8]}"

    def fake_search(q, *, max_results=20, cur=None):
        if "bad" in q:
            raise places.PlacesUnavailable("quota exceeded")
        return [{"place_id": f"pid-{uuid.uuid4().hex[:10]}", "name": "Acme Electrical",
                 "address": "1 High St, Otley LS21 1AA, UK", "postcode": "LS21 1AA",
                 "website": "https://acme.co.uk", "primary_type": "electrician",
                 "types": ["electrician"], "business_status": "OPERATIONAL"}]

    monkeypatch.setattr(places, "text_search", fake_search)
    res = places.discover_to_leads([f"{good}-1", "bad-query", f"{good}-2"],
                                   cur=db_rollback.cursor())
    assert res["inserted"] == 2                       # the two good queries survived
    assert len(res["failed_queries"]) == 1            # and the failure is surfaced, not silent
    assert "bad-query" in res["failed_queries"][0]


def test_the_grid_cursor_advances_past_a_failing_query(db_rollback, monkeypatch):
    from outreach import monitor, places, targeting

    grid = [f"q{i}" for i in range(10)]
    grid[1] = "bad-q1"
    monkeypatch.setattr(targeting, "places_queries", lambda: grid)
    monkeypatch.setattr(places, "text_search",
                        lambda q, **k: (_ for _ in ()).throw(places.PlacesUnavailable("boom"))
                        if "bad" in q else [])
    cur = db_rollback.cursor()
    monitor.set_flag("places_grid_cursor", "0", reason="test", cur=cur)

    res = places.discover_grid(count=3, cur=cur)
    assert res["grid_cursor"] == 3          # advanced by queries ATTEMPTED, not succeeded
    assert monitor.get_flag("places_grid_cursor", cur=cur) == "3"


# --------------------------------------------------------------------------- #
#  Grid ORDER is the targeting — the tail is never reached
# --------------------------------------------------------------------------- #
def test_auctioneers_are_swept_first():
    """The grid is vertical-major and the credit runs out long before the grid does, so
    the ORDER decides what is ever discovered. Auctioneers — the one vertical with a real
    client — sat at position 37 of 46 while the cursor crawled through the trades: 6.6%
    of the grid swept in a fortnight, still on 'roofer', which put them ~7 months out.
    They were not de-prioritised; they were unreachable by construction."""
    from outreach import targeting
    q = targeting.PLACES_VERTICAL_QUERIES
    assert "auction" in q[0].lower()
    assert sum(1 for x in q[:3] if "auction" in x.lower()) == 3


def test_named_contact_verticals_outrank_the_trades():
    """Measured on our own corpus: professional services publish a named personal address
    15.9% of the time vs 1.4% for the trades. The trades remain the sharpest ICP and stay
    in the grid — they just buy less per query, so they come after."""
    from outreach import targeting
    q = [x.lower() for x in targeting.PLACES_VERTICAL_QUERIES]
    first_trade = next(i for i, x in enumerate(q) if "electrician" in x)
    for named in ("accountant", "chartered surveyor", "private dental practice"):
        assert next(i for i, x in enumerate(q) if named in x) < first_trade, named


def test_the_grid_has_no_duplicate_queries():
    """A repeat is a query billed twice for the same result."""
    from outreach import targeting
    q = targeting.PLACES_VERTICAL_QUERIES
    assert len(q) == len(set(q))
    grid = targeting.places_queries()
    assert len(grid) == len(set(grid))


# --------------------------------------------------------------------------- #
#  Google's own category beats an LLM's read of the page text
# --------------------------------------------------------------------------- #
def test_a_wholesaler_is_refused_at_discovery():
    """The ICP gate is an LLM reading scraped page text, and it let `7 Core Electrical
    Wholesale Ltd` through — a trade wholesaler whose site is full of the word
    "electrical", scored as an electrician. Google had it filed under `wholesaler` the
    whole time. Refusing it HERE costs one row we never wrote; refusing it at enrichment
    costs a resolve, up to three scrapes and a model call first."""
    from outreach import places
    assert places.never_icp({"primary_type": "wholesaler", "types": ["wholesaler"]})
    assert places.never_icp({"primary_type": "electrician",
                             "types": ["electrician", "wholesaler"]})
    assert not places.never_icp({"primary_type": "electrician", "types": ["electrician"]})
    assert not places.never_icp({})


def test_the_never_icp_list_stays_small(db_rollback, monkeypatch):
    """It refuses a lead outright with no appeal, so only categories that are
    STRUCTURALLY never our customer belong in it. The arguable cases — a shop with a
    till, a firm already selling online — stay with the LLM gate, which can weigh them."""
    from outreach import places
    assert len(places.NEVER_ICP_TYPES) <= 10
    for allowed in ("electrician", "plumber", "auction_house", "dentist", "accounting"):
        assert allowed not in places.NEVER_ICP_TYPES


def test_a_never_icp_business_is_never_inserted(db_rollback, monkeypatch):
    import uuid

    from outreach import places

    def fake_search(q, *, max_results=20, cur=None):
        return [{"place_id": f"pid-{uuid.uuid4().hex[:10]}", "name": "Trade Supplies Ltd",
                 "address": "1 Depot Rd, Skegness PE25 3TB, UK", "postcode": "PE25 3TB",
                 "website": "https://supplies.example", "primary_type": "wholesaler",
                 "types": ["wholesaler"], "business_status": "OPERATIONAL"}]

    monkeypatch.setattr(places, "text_search", fake_search)
    res = places.discover_to_leads(["trade supplies"], cur=db_rollback.cursor())
    assert res["inserted"] == 0 and res["skipped"] == 1
