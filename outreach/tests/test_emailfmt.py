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
    assert "hello@settlepay.uk" in out
    assert "unsubscribe" in out                      # opt-out stays present
    # operator decision: no trading-name/address block in the email
    assert "trading name" not in out and "Rodney Street" not in out
    # text footer mirrors the html contact line
    assert "hello@settlepay.uk" in emailfmt.TEXT_FOOTER
    assert "Rodney Street" not in emailfmt.TEXT_FOOTER


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
    assert "Kind regards" in text and "hello@settlepay.uk" in text


# --------------------------------------------------------------------------- #
#  Article 14 transparency footer for NAMED-individual sends
# --------------------------------------------------------------------------- #
from outreach import config  # noqa: E402


def test_named_footer_carries_source_privacy_link_and_objection():
    note = emailfmt.NAMED_FOOTER_NOTE
    assert "Companies House" in note                  # art. 14 source disclosure
    assert config.PRIVACY_NOTICE_URL in note          # link to the privacy notice
    assert "unsubscribe" in note.lower()              # art. 21 right to object


def test_named_footer_note_appears_in_both_html_and_text():
    """A recipient sees only one part of the multipart mail, so the transparency has to
    be in both — not just the plain-text alternative."""
    html_out = emailfmt.render_html(BODY, footer_note=emailfmt.NAMED_FOOTER_NOTE)
    assert "Companies House" in html_out
    assert "hello@settlepay.uk" in html_out           # signature still intact
    assert "border-top" in html_out                   # signature block preserved
    text = BODY + emailfmt.named_text_footer()
    assert "Companies House" in text and config.PRIVACY_NOTICE_URL in text


def test_role_address_footer_has_no_transparency_note():
    """A role mailbox (info@) is not personal data — it must NOT carry the named-person
    disclosure, or every cold email would over-claim a source it didn't use."""
    assert "Companies House" not in emailfmt.render_html(BODY)
    assert "Companies House" not in emailfmt.TEXT_FOOTER


def test_named_footer_still_has_no_anchor():
    """The privacy URL is bare text, like every other link in these emails — the
    zero-anchor rule holds even for the transparency line."""
    out = emailfmt.render_html(BODY, footer_note=emailfmt.NAMED_FOOTER_NOTE)
    assert "<a " not in out.lower() and "href" not in out.lower()
