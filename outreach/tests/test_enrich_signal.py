from outreach import config, enrich
from outreach.llm import LLMUnavailable


class _Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status


class _FakeHttp:
    def __init__(self, text, status=200):
        self._r = _Resp(text, status)

    def get(self, url, **kw):
        return self._r


class _FakeProvider:
    def __init__(self, out=None, exc=None):
        self._out, self._exc = out, exc

    def complete(self, prompt, *, purpose, max_words=None):
        if self._exc:
            raise self._exc

        class R:
            text = self._out
        return R()


def test_page_text_strips_tags_and_bounds(monkeypatch):
    monkeypatch.setattr(config, "ENRICH_PAGE_TEXT_MAX_CHARS", 40)
    html = "<html><head><style>x{}</style><script>var a=1;</script></head>" \
           "<body><h1>Salon  Luxe</h1><p>Book by  phone.</p>" + "pad " * 50 + "</body></html>"
    out = enrich.page_text("https://x.co", client=_FakeHttp(html))
    assert out.startswith("Salon Luxe Book by phone.")
    assert len(out) <= 40 and "<" not in out


def test_page_text_failure_returns_empty():
    assert enrich.page_text("https://x.co", client=_FakeHttp("nope", status=500)) == ""
    assert enrich.page_text("", client=_FakeHttp("x")) == ""


def test_llm_signal_happy_path():
    s = enrich.llm_signal("Luxe Ltd", "Hair & beauty", "Leeds",
                          "We are a salon. Call to book.",
                          provider=_FakeProvider(out="  A salon in Leeds.\nBookings by phone.  "))
    assert s == "A salon in Leeds. Bookings by phone."


def test_llm_signal_failures_fall_back_to_none(monkeypatch):
    assert enrich.llm_signal("X", None, None, "", provider=_FakeProvider(out="y")) is None
    assert enrich.llm_signal("X", None, None, "text",
                             provider=_FakeProvider(exc=LLMUnavailable("cap"))) is None
    assert enrich.llm_signal("X", None, None, "text",
                             provider=_FakeProvider(exc=RuntimeError("boom"))) is None
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", None)
    assert enrich.llm_signal("X", None, None, "text") is None  # no key, no provider
