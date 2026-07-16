#!/usr/bin/env python3
"""Generate the per-page OG cards (1200x630) in the site's navy-stage language.

Regenerate after copy changes:  python3 scripts/generate-og-cards.py
Requires Python Playwright (used by the repo's QA scripts). Output goes to
public/og/<key>.png and is committed — the cards are build artefacts only in
the loose sense; they change rarely and reviewing them in the PR is useful.
"""
import pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / 'public' / 'og'
OUT.mkdir(parents=True, exist_ok=True)
MONOGRAM = (ROOT / 'public' / 'assets' / 'logos' / 'monogram-mark-light.svg').read_text()

CARDS = {
    'home':      ('Bespoke Payment Pages for UK Businesses',
                  'Branded checkout, built for you — funds settle straight to your bank.'),
    'work':      ('Our Work — Branded Payment Pages',
                  'One live client and six fictional demo builds, pattern by pattern.'),
    'about':     ('About SettlePay',
                  'A founder-led UK payment-page developer. No lock-in, never holding your money.'),
    'faq':       ('Frequently Asked Questions',
                  'Who holds the money, FCA and PCI, what it costs — straight answers.'),
    'book':      ('Book a Free Consultation',
                  'Thirty minutes, online, no obligation — pick a time that suits you.'),
    'preview':   ('See Your Payment Page, In Your Brand',
                  'Paste your website address and preview your own branded checkout.'),
    'lockdales': ('Lockdales Auctioneers — Live Client',
                  'A branded "Pay Your Invoice" page, live and taking real payments.'),
}

TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><style>
  * {{ margin: 0; box-sizing: border-box; }}
  body {{
    width: 1200px; height: 630px; overflow: hidden;
    font-family: -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    background: radial-gradient(130% 90% at 50% -10%, #1E2B45 0%, #0F172A 62%);
    color: #fff; padding: 72px 84px; display: flex; flex-direction: column;
  }}
  .mark {{ width: 84px; height: 84px; margin-bottom: 48px; }}
  .mark svg {{ width: 100%; height: 100%; }}
  h1 {{ font-size: 64px; line-height: 1.12; letter-spacing: -0.02em; font-weight: 700; max-width: 20ch; }}
  p {{ margin-top: 26px; font-size: 30px; line-height: 1.4; color: rgba(255,255,255,0.72); max-width: 44ch; }}
  .foot {{ margin-top: auto; display: flex; justify-content: space-between; align-items: center;
           font-size: 26px; font-weight: 600; color: rgba(255,255,255,0.6); }}
  .dot {{ width: 10px; height: 10px; border-radius: 50%; background: #10B981; display: inline-block; margin-right: 12px; }}
</style></head><body>
  <div class="mark">{mark}</div>
  <h1>{title}</h1>
  <p>{sub}</p>
  <div class="foot"><span>settlepay.uk</span><span><span class="dot"></span>Payments processed by FCA-regulated partners</span></div>
</body></html>"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1200, 'height': 630})
    for key, (title, sub) in CARDS.items():
        page.set_content(TEMPLATE.format(mark=MONOGRAM, title=title, sub=sub))
        page.wait_for_timeout(120)
        page.screenshot(path=str(OUT / f'{key}.png'))
        print(f'og/{key}.png')
    browser.close()
