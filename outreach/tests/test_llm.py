import pytest

from outreach.llm import (
    get_provider, InlineProvider, ApiProvider, InlineResponseRequired, LLMResult,
)

pytestmark = pytest.mark.floor_a


def test_default_provider_is_inline():
    assert isinstance(get_provider("inline"), InlineProvider)


def test_inline_records_agent_supplied_output():
    p = InlineProvider(responder=lambda prompt: "agent drafted this")
    r = p.complete("a prompt", purpose="draft")
    assert isinstance(r, LLMResult)
    assert r.text == "agent drafted this"
    assert r.provider == "inline"


def test_inline_requires_agent_when_no_responder():
    # never silently fabricates: it raises so the loop knows to supply the text
    with pytest.raises(InlineResponseRequired):
        InlineProvider().complete("a prompt", purpose="draft")


def test_api_provider_constructible_and_callable_without_real_spend():
    p = get_provider("api")
    assert isinstance(p, ApiProvider) and p.name == "api"

    class _Block:
        type = "text"
        text = "api drafted this"

    class _Msg:
        content = [_Block()]

    class _FakeClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                return _Msg()

    r = ApiProvider(client=_FakeClient()).complete("a prompt", purpose="draft")
    assert r.text == "api drafted this" and r.provider == "api"
