"""Branded HTML rendering for outbound mail (multipart/alternative with send.py).

Mirrors the house style of the site's enquiry/booking emails: grey-blue body
text, ink name, muted wordmark, the hosted SettlePay logo, and the same
trading-name/address footer. Operator decision (2026-07): cold sends carry the
logo + contact block — the one deliverability concession — but still ZERO
anchors: nothing in the email is clickable, the only image is the single
hosted logo, and every piece of body content is escaped. The plain-text body
remains the check_envelope-audited source of truth; the LLM can never add
content here — the signature/footer are static, code-reviewed constants.
"""
from __future__ import annotations
import html as _html

from . import config

# Body text is a deep charcoal — deliberately dark for a cold email to a 45-65 owner who
# reads it once. INK is the near-black used for the body copy and the sign-off name.
INK = "#111827"          # body copy + name (dark charcoal)
BODY = "#111827"         # wrapper fallback — same charcoal, so stray text is never light
MUTED = "#6B7280"        # ONLY the wordmark + a bare unsubscribe line (deliberately quiet)
HAIRLINE = "#E2E8F0"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
LOGO_URL = "https://settlepay.uk/email/logo.png"

# Appended to the PLAIN-TEXT part at the send boundary (post-review, so the
# bare domain here never meets the LLM-copy LINK_RE audit). Mirrors the html.
# Contact line only (operator decision): the trading-name/address disclosure
# lives on the website; the sender's name is already in the sign-off.
TEXT_FOOTER = "\n\n—\nhello@settlepay.uk · settlepay.uk"


# The art. 14 transparency sentence, shown in BOTH the html and text parts of a
# named-individual send (a recipient sees only one). States the source of their details,
# links the privacy notice, and gives the art. 21 way to object.
NAMED_FOOTER_NOTE = (
    "We found your business details through Companies House and public sources. "
    f"How we use them: {config.PRIVACY_NOTICE_URL} — reply 'unsubscribe' and we'll "
    "remove you and not contact you again.")


def named_text_footer() -> str:
    """Plain-text footer for a send to a NAMED individual: the standard contact line plus
    the art. 14 transparency note. Role-address sends use the plain TEXT_FOOTER; this is
    the extra transparency that targeting a person legally requires."""
    return f"{TEXT_FOOTER}\n{NAMED_FOOTER_NOTE}"

_P = f'style="margin:0 0 16px;font-size:16px;line-height:1.7;color:{INK};"'
_P_UNSUB = f'style="margin:0 0 16px;font-size:14px;line-height:1.6;color:{MUTED};"'


def _signature_block(lines: list[str]) -> str:
    out = [f'<div style="margin-top:28px;padding-top:16px;border-top:1px solid {HAIRLINE};">']
    for line in lines:
        esc = _html.escape(line)
        if line.strip().lower() == "settlepay":
            out.append(f'<p style="margin:0 0 14px;font-size:14px;color:{MUTED};">{esc}</p>')
        elif line.strip().lower().startswith("kind regards"):
            out.append(f'<p style="margin:0 0 2px;font-size:16px;line-height:1.6;color:{INK};">{esc}</p>')
        else:
            out.append(f'<p style="margin:0;font-size:16px;line-height:1.5;font-weight:600;color:{INK};">{esc}</p>')
    out.append(
        f'<img src="{LOGO_URL}" width="48" height="48" alt="SettlePay" '
        'style="display:block;border:0;width:48px;height:48px;margin:0 0 14px;">'
        f'<p style="margin:0;font-size:13px;line-height:1.6;color:{MUTED};">'
        "hello@settlepay.uk &middot; settlepay.uk</p>"
    )
    out.append("</div>")
    return "".join(out)


def render_html(text: str, *, footer_note: str | None = None) -> str:
    """Plain-text email body -> house-style HTML. Escapes all content; the only
    markup is what this function emits (no anchors anywhere; one logo image).

    `footer_note` (art. 14 transparency for named sends) is rendered as a final muted
    paragraph AFTER the signature block, so the sign-off/logo stay intact and the notice
    sits below them."""
    # Normalise line endings FIRST. Drafts arrive with Windows CRLF (\r\n), so a
    # paragraph break is "\r\n\r\n" — which split("\n\n") does NOT match (the \r sits
    # between the newlines). The result was the ENTIRE email collapsing into one
    # paragraph: no signature block, no logo, and — because that one blob contains the
    # word "unsubscribe" — the whole thing rendered in the light muted grey. This one
    # line is the fix for "the font is too light".
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    paras = [p for p in (chunk.strip() for chunk in text.split("\n\n")) if p]
    rendered: list[str] = []
    for i, para in enumerate(paras):
        lines = para.splitlines()
        is_last = i == len(paras) - 1
        if is_last and lines and lines[0].strip().lower().startswith("kind regards"):
            rendered.append(_signature_block(lines))
            continue
        # ALL body copy is the dark charcoal — including the opt-out line, which often
        # shares a sentence with the ask. Only the wordmark, the contact line (in the
        # signature block) and the art. 14 footer_note are deliberately muted.
        body = "<br>".join(_html.escape(l) for l in lines)
        rendered.append(f"<p {_P}>{body}</p>")
    if footer_note:
        rendered.append(f'<p {_P_UNSUB}>{_html.escape(footer_note)}</p>')
    return (
        "<!doctype html><html><body style=\"margin:0;padding:0;\">"
        # outer pad gives breathing room on every client (mobile was flush-left);
        # inner max-width centres the column on wide screens.
        f'<div style="padding:28px 24px;font-family:{FONT};color:{BODY};'
        'font-size:16px;line-height:1.7;">'
        '<div style="max-width:560px;margin:0 auto;">'
        + "".join(rendered)
        + "</div></div></body></html>"
    )
