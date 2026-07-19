"""emailfmt: house-style HTML must stay structurally incapable of carrying an
anchor or unescaped content — the ONLY image is the single hosted logo, and the
signature/footer are static constants the LLM can never influence."""
import base64
import email

import pytest

from outreach import emailfmt, gmail

pytestmark = pytest.mark.floor_g

BODY = (
    "Hi Greenway Plumbing,\n\n"
    "Saw you cover boiler work across Ipswich.\n\n"
    "To opt out of future messages, reply with the word unsubscribe.\n\n"
    "Kind regards,\nFinlay Salisbury\nSettlePay"
)


def test_render_has_no_anchors_and_only_the_logo_image():
    out = emailfmt.render_html(BODY)
    low = out.lower()
    for banned in ("<a ", "<a>", "href", "mailto:"):
        assert banned not in low
    assert low.count("<img") == 1 and emailfmt.LOGO_URL in out
    assert low.count("src=") == 1


def test_render_escapes_content():
    out = emailfmt.render_html(
        'Hi <script>alert(1)</script> & <a href="http://x">co</a>,\n\n'
        "Kind regards,\nFinlay Salisbury\nSettlePay")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out and "&lt;a href=" in out


def test_house_signature_and_footer():
    out = emailfmt.render_html(BODY)
    assert "border-top" in out                       # signature divider
    assert "font-weight:600" in out                  # name in ink
    assert "trading name of Finlay Salisbury" in out
    assert "2b Rodney Street" in out
    assert "hello@settlepay.uk" in out
    assert "unsubscribe" in out                      # opt-out stays present
    # text footer mirrors the html one
    for line in ("trading name", "2b Rodney Street", "hello@settlepay.uk"):
        assert line in emailfmt.TEXT_FOOTER


def test_send_message_builds_multipart_alternative(monkeypatch):
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"id": "m1"}

    class FakeClient:
        @staticmethod
        def post(url, headers=None, json=None, timeout=None):
            captured["raw"] = json["raw"]
            return FakeResp()

    monkeypatch.setattr(gmail.google_oauth, "access_token", lambda client=None: "tok")
    gmail.send_message("s@x.uk", "r@y.uk", "Sub", BODY + emailfmt.TEXT_FOOTER,
                       html=emailfmt.render_html(BODY), client=FakeClient)
    msg = email.message_from_bytes(base64.urlsafe_b64decode(captured["raw"]))
    assert msg.get_content_type() == "multipart/alternative"
    parts = {p.get_content_type() for p in msg.walk()} - {"multipart/alternative"}
    assert parts == {"text/plain", "text/html"}
    # plain text part is intact and carries the mirrored footer
    plain = next(p for p in msg.walk() if p.get_content_type() == "text/plain")
    text = plain.get_payload(decode=True).decode()
    assert "Kind regards" in text and "2b Rodney Street" in text
