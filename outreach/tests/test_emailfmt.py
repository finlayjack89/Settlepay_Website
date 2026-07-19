"""emailfmt: the HTML part must be branding-by-typography only — structurally
incapable of carrying a link, image or unescaped content."""
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


def test_render_has_no_links_or_images():
    out = emailfmt.render_html(BODY)
    for banned in ("href", "src", "<a ", "<img", "http://", "https://"):
        assert banned not in out.lower()


def test_render_escapes_content():
    out = emailfmt.render_html("Hi <script>alert(1)</script> & co,\n\nKind regards,\nFinlay Salisbury\nSettlePay")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out and "&amp; co" in out


def test_signature_and_unsubscribe_styling():
    out = emailfmt.render_html(BODY)
    assert "border-top" in out                       # signature divider
    assert "font-weight:600" in out                  # name
    assert "font-weight:700" in out                  # SettlePay wordmark
    assert "unsubscribe" in out                      # opt-out stays present
    assert out.count("<p") == len([p for p in BODY.split("\n\n")]) + 2  # sig lines


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
    gmail.send_message("s@x.uk", "r@y.uk", "Sub", BODY,
                       html=emailfmt.render_html(BODY), client=FakeClient)
    msg = email.message_from_bytes(base64.urlsafe_b64decode(captured["raw"]))
    assert msg.get_content_type() == "multipart/alternative"
    parts = {p.get_content_type() for p in msg.walk()} - {"multipart/alternative"}
    assert parts == {"text/plain", "text/html"}
    # plain text part is intact — it is the audited source of truth
    plain = next(p for p in msg.walk() if p.get_content_type() == "text/plain")
    assert "Kind regards" in plain.get_payload(decode=True).decode()
