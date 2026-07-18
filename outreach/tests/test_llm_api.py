import pytest

from outreach import config, llm, spend


class _Usage:
    input_tokens, output_tokens = 120, 45


class _Block:
    type, text = "text", "Hello from the model."


class _Msg:
    content, usage = [_Block()], _Usage()


class _FakeClient:
    class messages:  # noqa: N801 — mirrors the SDK surface
        @staticmethod
        def create(**kwargs):
            _FakeClient.last = kwargs
            return _Msg()


class _FailingClient:
    class messages:  # noqa: N801
        @staticmethod
        def create(**kwargs):
            raise RuntimeError("boom")


def test_api_refuses_without_key(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", None)
    with pytest.raises(llm.LLMUnavailable):
        llm.ApiProvider().complete("hi", purpose="draft")


def test_api_happy_path_meters_spend(monkeypatch):
    recorded = {}
    monkeypatch.setattr(spend, "ensure_under_cap", lambda cur=None: None)
    monkeypatch.setattr(spend, "record", lambda *a, **k: recorded.update(k, provider=a[0]))
    res = llm.ApiProvider(client=_FakeClient()).complete("hi", purpose="draft")
    assert res.text == "Hello from the model."
    assert res.meta["units_in"] == 120 and res.meta["units_out"] == 45
    assert recorded["provider"] == "anthropic" and recorded["units_in"] == 120
    assert recorded["cost_gbp"] == pytest.approx(spend.anthropic_cost_gbp(120, 45))
    assert _FakeClient.last["model"] == config.ANTHROPIC_MODEL


def test_api_cap_hit_becomes_unavailable(monkeypatch):
    def _raise(cur=None):
        raise spend.SpendCapExceeded("cap")
    monkeypatch.setattr(spend, "ensure_under_cap", _raise)
    with pytest.raises(llm.LLMUnavailable):
        llm.ApiProvider(client=_FakeClient()).complete("hi", purpose="draft")


def test_api_provider_error_becomes_unavailable(monkeypatch):
    monkeypatch.setattr(spend, "ensure_under_cap", lambda cur=None: None)
    with pytest.raises(llm.LLMUnavailable):
        llm.ApiProvider(client=_FailingClient()).complete("hi", purpose="draft")


def test_metering_failure_never_fails_the_call(monkeypatch):
    monkeypatch.setattr(spend, "ensure_under_cap", lambda cur=None: None)

    def _boom(*a, **k):
        raise RuntimeError("ledger down")
    monkeypatch.setattr(spend, "record", _boom)
    res = llm.ApiProvider(client=_FakeClient()).complete("hi", purpose="signal")
    assert res.text  # the successful completion is returned regardless
