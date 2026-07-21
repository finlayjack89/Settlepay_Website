"""Easy Live Auction adapter (easyliveauction.com).

Recon: docs/recon/easyliveauction.md. Discovery is the sanctioned sitemap
(`sitemap-auctioneers.xml`, ~448 auctioneers at `/auctioneers/<slug>/`); each profile is
static server-rendered HTML carrying a clean `localBusiness` JSON-LD block. So this is a
static fetch + JSON-LD parse — no internal API (robots-disallowed), no headless browser
(content is not JS-rendered).

Fields ELA exposes per auctioneer: name, postcode, specialism/categories, logo. It does
NOT expose the auctioneer's own website (it keeps bidders on-platform) — that is resolved
downstream by the enrichment stage. The `telephone` in the JSON-LD is deliberately NOT
read: no phone is ever captured.

TERMS: ELA's Site Usage Terms prohibit automated collection without written consent
(recon doc §1). This adapter exists and runs at the operator's direction; `terms_note`
carries the caveat so it is never forgotten in the run log.
"""
from __future__ import annotations

import html as _html
import json
import re
from typing import Iterator, Optional

from .. import categories as _cat
from ..models import AuctionLead
from .base import Source

SITEMAP_INDEX = "https://www.easyliveauction.com/sitemap-index.xml"
AUCTIONEERS_SITEMAP = "https://www.easyliveauction.com/sitemaps/sitemap-auctioneers.xml"

_LOC_RE = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.I)
_LDJSON_RE = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
_SLUG_RE = re.compile(r"/auctioneers/([^/]+)/?$", re.I)
_UPCOMING_RE = re.compile(
    r"(\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
    r"(?:\s+\d{4})?)", re.I)


def _unescape(s: Optional[str]) -> Optional[str]:
    """ELA hex-encodes JSON-LD values (&#x20; etc). Decode, collapse whitespace."""
    if not s:
        return s
    return " ".join(_html.unescape(str(s)).split()) or None


_CATALOGUE_RE = re.compile(r"/catalogue/|catalogue-id|/lot/", re.I)


class EasyLiveSource(Source):
    platform = "easylive"
    display_name = "Easy Live Auction"
    terms_note = ("robots permits /auctioneers/; Site Usage Terms prohibit automated "
                  "collection without written consent (operator-directed).")

    def iter_auctioneers(self, *, limit: Optional[int] = None) -> Iterator[AuctionLead]:
        sitemap = self.client.get(AUCTIONEERS_SITEMAP)
        if not sitemap:
            return
        urls = _LOC_RE.findall(sitemap)
        count = 0
        for url in urls:
            if limit is not None and count >= limit:
                return
            lead = self._profile(url)
            if lead is not None:
                count += 1
                yield lead

    def _profile(self, url: str) -> Optional[AuctionLead]:
        html_text = self.client.get(url)
        if not html_text:
            return None
        biz = self._local_business(html_text)
        slug_m = _SLUG_RE.search(url)
        slug = slug_m.group(1) if slug_m else url.rstrip("/").rsplit("/", 1)[-1]
        name = _unescape(biz.get("name")) if biz else None
        if not name:                                   # a profile with no business name is unusable
            return None
        description = _unescape(biz.get("description")) if biz else None
        addr = (biz.get("address") or [{}])[0] if biz else {}
        # Categories from the auctioneer's OWN description only (their words). NOT the
        # og:description or the full page — those carry ELA's site-wide category nav +
        # generic "Antiques, Fine Art, Classic Cars" tagline, which would tag every
        # auctioneer identically. Fall back to visible text only if they wrote no blurb.
        cats = _cat.detect(description or "") or _cat.detect(self._visible(html_text))
        return AuctionLead(
            platform=self.platform,
            business_name=name,
            listing_url=url,
            source_id=slug,
            location=_unescape(addr.get("addressLocality")) or None,
            postcode=_unescape(addr.get("postalCode")),
            categories=cats,
            next_auction_date=self._next_auction(html_text),
            upcoming_count=len(_CATALOGUE_RE.findall(html_text)),  # catalogue links = activity
            own_website=None,                          # ELA does not expose it
            logo_url=_unescape(biz.get("logo")) if biz else None,
        )

    @staticmethod
    def _local_business(html_text: str) -> Optional[dict]:
        for block in _LDJSON_RE.findall(html_text):
            try:
                data = json.loads(block.strip())
            except ValueError:
                continue
            if isinstance(data, dict) and str(data.get("@type", "")).lower() == "localbusiness":
                return data
        return None

    _TAG_RE = re.compile(r"<(script|style)\b.*?</\1>|<[^>]+>", re.S | re.I)

    @classmethod
    def _visible(cls, html_text: str) -> str:
        """Tag-stripped page text, bounded — the body copy category keywords hide in."""
        return " ".join(cls._TAG_RE.sub(" ", html_text).split())[:6000]

    @staticmethod
    def _meta(html_text: str, prop: str) -> Optional[str]:
        m = re.search(rf'<meta[^>]+property=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)',
                      html_text, re.I)
        return m.group(1) if m else None

    @staticmethod
    def _next_auction(html_text: str) -> Optional[str]:
        """Best-effort next-auction date from an 'Upcoming' block. Often absent (no sale
        scheduled) — that is fine, it just lowers the activity score."""
        idx = re.search(r"upcoming", html_text, re.I)
        if not idx:
            return None
        window = html_text[idx.start(): idx.start() + 2000]
        m = _UPCOMING_RE.search(window)
        return m.group(1) if m else None
