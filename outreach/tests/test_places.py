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
