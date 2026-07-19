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

INK = "#0F172A"
BODY = "#475569"
MUTED = "#64748B"
HAIRLINE = "#E2E8F0"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
LOGO_URL = "https://settlepay.uk/email/logo.png"

# Appended to the PLAIN-TEXT part at the send boundary (post-review, so the
# bare domain here never meets the LLM-copy LINK_RE audit). Mirrors the html.
# Contact line only (operator decision): the trading-name/address disclosure
# lives on the website; the sender's name is already in the sign-off.
TEXT_FOOTER = "\n\n—\nhello@settlepay.uk · settlepay.uk"

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


def render_html(text: str) -> str:
    """Plain-text email body -> house-style HTML. Escapes all content; the only
    markup is what this function emits (no anchors anywhere; one logo image)."""
    paras = [p for p in (chunk.strip() for chunk in text.split("\n\n")) if p]
    rendered: list[str] = []
    for i, para in enumerate(paras):
        lines = para.splitlines()
        is_last = i == len(paras) - 1
        if is_last and lines and lines[0].strip().lower().startswith("kind regards"):
            rendered.append(_signature_block(lines))
            continue
        style = _P_UNSUB if "unsubscribe" in para.lower() else _P
        body = "<br>".join(_html.escape(l) for l in lines)
        rendered.append(f"<p {style}>{body}</p>")
    return (
        "<!doctype html><html><body style=\"margin:0;padding:0;\">"
        f'<div style="max-width:560px;font-family:{FONT};color:{BODY};">'
        + "".join(rendered)
        + "</div></body></html>"
    )
