"""Minimal HTML rendering for outbound mail (multipart/alternative with send.py).

Cold email from a young domain must not look like campaign mail: images (logos),
buttons and links are the bulk-mail fingerprint that routes to Promotions/spam,
and most clients block remote images anyway. So branding here is TYPOGRAPHY ONLY —
the site's navy palette and a styled text signature ("SettlePay" as a styled
wordmark, not an image). The plain-text body stays the check_envelope-audited
source of truth; this renderer derives the HTML from it deterministically and
escapes everything, so it can never introduce a link, image or claim of its own.
Full branded templates (logo, preview links) belong to reply-stage mail to people
who have already engaged — never to a cold touch.
"""
from __future__ import annotations
import html as _html

NAVY = "#0F172A"
MUTED = "#475569"
HAIRLINE = "#E2E8F0"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

_P = f'style="margin:0 0 16px;font-size:16px;line-height:1.6;"'
_P_UNSUB = f'style="margin:0 0 16px;font-size:14px;line-height:1.6;color:{MUTED};"'


def _signature_block(lines: list[str]) -> str:
    out = [f'<div style="margin-top:28px;padding-top:14px;border-top:1px solid {HAIRLINE};">']
    for i, line in enumerate(lines):
        esc = _html.escape(line)
        if i == 0:
            out.append(f'<p style="margin:0;font-size:16px;line-height:1.5;">{esc}</p>')
        elif line.strip().lower() == "settlepay":
            out.append(f'<p style="margin:2px 0 0;font-size:16px;font-weight:700;'
                       f'letter-spacing:.01em;color:{NAVY};">{esc}</p>')
        else:
            out.append(f'<p style="margin:6px 0 0;font-size:16px;font-weight:600;">{esc}</p>')
    out.append("</div>")
    return "".join(out)


def render_html(text: str) -> str:
    """Plain-text email body -> minimal branded HTML. Escapes all content; the
    only markup is what this function emits (no href/src anywhere)."""
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
        f'<div style="max-width:560px;font-family:{FONT};color:{NAVY};">'
        + "".join(rendered)
        + "</div></body></html>"
    )
