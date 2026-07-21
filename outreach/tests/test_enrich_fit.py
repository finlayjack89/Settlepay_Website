"""ICP-fit gate: signal_and_fit parsing + _persist disqualification. Hermetic —
the LLM provider is faked, no live Vertex call."""
import json
import uuid

import pytest

from outreach import enrich as E
from outreach.llm import LLMResult

pytestmark = pytest.mark.floor_d


class _FakeProvider:
    def __init__(self, payload):
        self._payload = payload

    def complete(self, prompt, *, purpose, max_words=None, schema=None):
        return LLMResult(json.dumps(self._payload), "gemini", {"purpose": purpose})


def test_signal_and_fit_parses_verdict():
    v = E.signal_and_fit("Ridgeway Plumbing", "Plumbing", "Leeds", "mobile plumber, invoices after jobs",
                         provider=_FakeProvider({
                             "icp_fit": True, "payment_context": "invoice_remote",
                             "size_band": "micro", "signal": "A mobile plumber.",
                             "confidence": 0.9}))
    assert v["available"] and v["icp_fit"] is True
    assert v["payment_context"] == "invoice_remote" and v["size_band"] == "micro"
    assert v["signal"] == "A mobile plumber."


def test_signal_and_fit_unavailable_on_no_text():
    v = E.signal_and_fit("X", None, None, "", provider=_FakeProvider({}))
    assert v["available"] is False


def test_signal_and_fit_unavailable_on_bad_json():
    class Bad:
        def complete(self, *a, **k):
            return LLMResult("not json", "gemini", {})
    v = E.signal_and_fit("X", None, None, "some text", provider=Bad())
    assert v["available"] is False


def _seed(cur, cn, name):
    cur.execute("insert into outreach.leads (company_number, company_name, company_type, "
                "subscriber_class, state) values (%s,%s,'ltd','corporate','discovered')", (cn, name))


def test_persist_disqualifies_non_icp_even_with_verified_contact(db_rollback):
    cur = db_rollback.cursor()
    cn = f"FIT_{uuid.uuid4().hex[:8]}"
    _seed(cur, cn, "Big Consultancy Ltd")
    g = {"email": "info@x.co", "verified": True, "result": "ok",
         "candidates": ["info@x.co"], "scrape_source": "guess",
         "fit": {"available": True, "icp_fit": False, "payment_context": "unclear",
                 "size_band": "large", "confidence": 1.0}}
    res = E._persist(cn, "https://x.co", "sig", g, cur=cur)
    assert res["disqualified"] is True
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "discarded"


def test_persist_admits_invoice_remote_lead(db_rollback):
    cur = db_rollback.cursor()
    cn = f"FIT_{uuid.uuid4().hex[:8]}"
    _seed(cur, cn, "Ridgeway Plumbing Ltd")
    g = {"email": "info@x.co", "verified": True, "result": "ok",
         "candidates": ["info@x.co"], "scrape_source": "guess",
         "fit": {"available": True, "icp_fit": True, "payment_context": "invoice_remote",
                 "size_band": "micro", "confidence": 0.9}}
    E._persist(cn, "https://x.co", "sig", g, cur=cur)
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "enriched"


def test_persist_disqualifies_fixed_till_retail(db_rollback):
    # the reframe: a barber/shop with a till takes card in person → online page redundant.
    # Even if the model says icp_fit=True, fixed_till_retail disqualifies deterministically.
    cur = db_rollback.cursor()
    cn = f"FIT_{uuid.uuid4().hex[:8]}"
    _seed(cur, cn, "Bob's Barbers Ltd")
    g = {"email": "info@x.co", "verified": True, "result": "ok",
         "candidates": ["info@x.co"], "scrape_source": "guess",
         "fit": {"available": True, "icp_fit": True, "payment_context": "fixed_till_retail",
                 "size_band": "micro", "confidence": 0.9}}
    res = E._persist(cn, "https://x.co", "sig", g, cur=cur)
    assert res["disqualified"] is True
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "discarded"


def test_persist_fit_unknown_admits_if_contactable(db_rollback):
    # LLM unavailable → fit unknown → admit-if-contactable (fail-open, review gate downstream)
    cur = db_rollback.cursor()
    cn = f"FIT_{uuid.uuid4().hex[:8]}"
    _seed(cur, cn, "Ambiguous Ltd")
    g = {"email": "info@x.co", "verified": True, "result": "ok",
         "candidates": ["info@x.co"], "scrape_source": "guess",
         "fit": {"available": False}}
    E._persist(cn, "https://x.co", "sig", g, cur=cur)
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "enriched"
