"""GeminiProvider (Vertex) — cost maths + metered call via a fake client.
No live Vertex call: the client is faked so the test is hermetic."""
import types as _t

import pytest

from outreach import llm, spend

pytestmark = pytest.mark.floor_d


def test_gemini_cost_gbp_known_and_unknown(capsys):
    # gemini-3.1-flash-lite = $0.25/$1.50 per 1M; USD_TO_GBP applied.
    from outreach import config
    c = spend.gemini_cost_gbp("gemini-3.1-flash-lite", 1_000_000, 1_000_000)
    assert round(c, 4) == round((0.25 + 1.50) * config.USD_TO_GBP, 4)
    # unknown model → max known rate + a printed warning (never silent under-count)
    hi = spend.gemini_cost_gbp("gemini-9-ultra", 1_000_000, 0)
    assert hi > 0 and "WARNING" in capsys.readouterr().out


class _FakeUsage:
    prompt_token_count = 100
    candidates_token_count = 20
    thoughts_token_count = 5   # thinking billed at output rate → units_out = 25


class _FakeResp:
    text = '{"icp_fit": true}'
    usage_metadata = _FakeUsage()


class _FakeModels:
    def __init__(self):
        self.last = None

    def generate_content(self, *, model, contents, config):
        self.last = {"model": model, "config": config}
        return _FakeResp()


class _FakeClient:
    def __init__(self):
        self.models = _FakeModels()


def test_gemini_provider_meters_and_disables_thinking(db_rollback, monkeypatch):
    # record spend against the rolled-back test transaction
    monkeypatch.setattr(spend, "ensure_under_cap", lambda cur=None: None)
    recorded = {}
    monkeypatch.setattr(spend, "record",
                        lambda *a, **k: recorded.update(k) or recorded.update({"provider": a[0]}))

    fake = _FakeClient()
    p = llm.GeminiProvider(model="gemini-3.1-flash-lite", client=fake)
    schema = {"type": "object", "properties": {"icp_fit": {"type": "boolean"}}}
    res = p.complete("classify this", purpose="icp_fit", schema=schema)

    assert res.text == '{"icp_fit": true}'
    assert res.meta["units_in"] == 100
    assert res.meta["units_out"] == 25          # candidates 20 + thinking 5
    assert recorded["provider"] == "gemini"
    assert recorded["units_out"] == 25
    # thinking disabled + schema forwarded to the API config
    cfg = fake.models.last["config"]
    assert cfg.thinking_config.thinking_budget == 0
    assert cfg.response_mime_type == "application/json"
