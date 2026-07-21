"""Auction Technology Group platforms: the-saleroom.com, bidspotter.co.uk, i-bidder.com.

All three are the same ATG codebase behind different brands, so they are ONE adapter
parameterised by base URL — not three copy-pasted files. Recon: docs/recon/atg.md.

Two things shape this adapter:

1. **Nothing is reachable over plain HTTP.** Every direct request — robots.txt included —
   returns an AWS WAF challenge (HTTP 202, empty body, `x-amzn-waf-action: challenge`).
   So discovery goes through `PoliteClient.get_rendered` (Firecrawl), and the parser
   works on rendered markdown rather than HTML.

2. **The directory is far richer than Easy Live's.** `/en-gb/auctioneers/all?page=N`
   lists 60 auctioneers a page with name, full postal address (so: postcode AND country),
   logo, and a live "View Auctions (N)" count. The profile page then carries the
   auctioneer's own blurb — their words, which is what categories are read from — and a
   `mailto:` on their own domain, which hands us `own_website` directly. That last part
   matters: it skips the Firecrawl website *search* the enrichment stage would otherwise
   pay for and frequently gets wrong.

Phones are visible in the listing and are deliberately never read (no-phones rule).
"""
from __future__ import annotations

import re
from typing import Iterator, Optional
from urllib.parse import urlsplit

from .. import categories as _cat
from .. import config
from ..models import AuctionLead
from .base import Source

# One directory entry: a level-2 heading linking to the auctioneer's catalogue page.
_ENTRY_RE = re.compile(r"^## \[([^\]]+)\]\((https?://[^)]+/auction-catalogues/[^)?#]+)",
                       re.M)
_VIEW_AUCTIONS_RE = re.compile(r"View Auctions \((\d+)\)", re.I)
_LOGO_RE = re.compile(r"\[!\[[^\]]*\]\((https?://[^)\s]+)\)\]")
_MAILTO_RE = re.compile(r"mailto:([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", re.I)
_MARKUP_RE = re.compile(r"[\[\]()#!]|https?://")
# A UK postcode at the END of the address, with or without its space: the address arrives
# as one run-together string ("...ColneLancashireBB8 8EGUnited Kingdom"). Deliberately
# CASE-SENSITIVE — with re.I the outward code swallows the last letter of the town
# ("LondonW1W 7LT" -> "NW1W 7LT", a district that doesn't exist).
_POSTCODE_TAIL_RE = re.compile(r"([A-Z]{1,2}[0-9][A-Z0-9]?)\s?([0-9][A-Z]{2})\s*$")
_COUNTRY_SUFFIX_RE = re.compile(
    r"(United Kingdom|Ireland|Guernsey|Jersey|Isle of Man|[A-Z][a-z]+(?: [A-Z][a-z]+)*)\s*$")


def _domain(url_or_email: str) -> str:
    host = url_or_email.rpartition("@")[2] if "@" in url_or_email else \
        (urlsplit(url_or_email).netloc or url_or_email)
    host = host.strip().lower()
    return host[4:] if host.startswith("www.") else host


class ATGSource(Source):
    """Shared behaviour; subclasses supply `platform`, `display_name` and `base`."""

    #: e.g. 'https://www.the-saleroom.com'
    base: str = ""
    #: fetch each auctioneer's profile for their blurb + own-domain email
    fetch_profiles: bool = True

    terms_note = ("no robots.txt is served (every path answers with an AWS WAF "
                  "challenge); ATG's Terms reserve automated access — operator-directed.")

    # ------------------------------------------------------------------ discovery
    def directory_url(self, page: int) -> str:
        url = f"{self.base}/en-gb/auctioneers/all"
        return url if page <= 1 else f"{url}?page={page}"

    def iter_auctioneers(self, *, limit: Optional[int] = None) -> Iterator[AuctionLead]:
        seen: set[str] = set()
        count = 0
        for page in range(1, config.MAX_DIRECTORY_PAGES + 1):
            doc = self.client.get_rendered(self.directory_url(page))
            entries = self._entries(doc["markdown"]) if doc else []
            if not entries:
                return                       # a page with no entries is the end of the list
            for entry in entries:
                if limit is not None and count >= limit:
                    return
                if entry["source_id"] in seen:
                    continue
                seen.add(entry["source_id"])
                if config.UK_ONLY and not self._is_uk(entry):
                    continue
                lead = self._lead(entry)
                count += 1
                yield lead

    # ------------------------------------------------------------------ parsing
    @classmethod
    def _entries(cls, markdown: str) -> list[dict]:
        """Split the directory page into one dict per auctioneer."""
        matches = list(_ENTRY_RE.finditer(markdown))
        out = []
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
            block = markdown[m.start():end]
            url = m.group(2)
            address = cls._address(block)
            out.append({
                "business_name": cls._unescape(m.group(1)),
                "listing_url": url,
                "source_id": url.rstrip("/").rsplit("/", 1)[-1],
                "postcode": cls._postcode(address),
                "country": cls._country(address),
                "upcoming_count": cls._upcoming(block),
                "logo_url": cls._logo(block),
            })
        return out

    @staticmethod
    def _unescape(name: str) -> str:
        return " ".join(re.sub(r"\\([\[\]()*_])", r"\1", name).split())

    @staticmethod
    def _address(block: str) -> str:
        """The address is the first genuinely plain-text line of the block — every other
        line is a markdown link or image, or the phone number we refuse to read."""
        for line in block.splitlines()[1:]:
            line = line.strip()
            if not line or _MARKUP_RE.search(line):        # a link, an image, a heading
                continue
            if re.fullmatch(r"[\d\s+()./-]{6,}", line):    # a phone number — never stored
                continue
            return line
        return ""

    @staticmethod
    def _country(address: str) -> Optional[str]:
        m = _COUNTRY_SUFFIX_RE.search(address)
        return m.group(1) if m else None

    @staticmethod
    def _is_uk(entry: dict) -> bool:
        """Explicitly UK, or no country given but a valid UK postcode — an entry that
        merely omits its country must not be silently dropped."""
        return entry["country"] == "United Kingdom" or (
            entry["country"] is None and entry["postcode"] is not None)

    @classmethod
    def _postcode(cls, address: str) -> Optional[str]:
        country = cls._country(address) or ""
        stem = address[:len(address) - len(country)] if country else address
        m = _POSTCODE_TAIL_RE.search(stem.strip())
        return f"{m.group(1).upper()} {m.group(2).upper()}" if m else None

    @staticmethod
    def _upcoming(block: str) -> int:
        m = _VIEW_AUCTIONS_RE.search(block)
        return int(m.group(1)) if m else 0

    @staticmethod
    def _logo(block: str) -> Optional[str]:
        for url in _LOGO_RE.findall(block):
            if "/auctioneers" not in url:      # the placeholder is a link back to the list
                return url
        return None

    # ------------------------------------------------------------------ profile
    def _lead(self, entry: dict) -> AuctionLead:
        description, website = "", None
        if self.fetch_profiles:
            description, website = self._profile(entry["listing_url"],
                                                 entry["business_name"])
        return AuctionLead(
            platform=self.platform,
            business_name=entry["business_name"],
            listing_url=entry["listing_url"],
            source_id=entry["source_id"],
            location=None,                     # the run-together address has no clean town
            postcode=entry["postcode"],
            categories=_cat.detect(description) if description else [],
            upcoming_count=entry["upcoming_count"],
            own_website=website,
            logo_url=entry["logo_url"],
        )

    def _profile(self, url: str, name: str) -> tuple[str, Optional[str]]:
        """Their own blurb (for categories) and their own domain (from a `mailto:` on the
        page). Only the DOMAIN is taken from the address — deciding WHICH mailbox to
        contact stays with the enrichment stage, which owns that policy."""
        doc = self.client.get_rendered(url)
        if not doc:
            return "", None
        markdown = doc.get("markdown") or ""
        website = None
        platform_host = _domain(self.base)
        addresses = _MAILTO_RE.findall(markdown) + \
            [a for link in (doc.get("links") or []) for a in _MAILTO_RE.findall(link)]
        for addr in addresses:
            host = _domain(addr)
            if host and host != platform_host and not host.endswith("atgmedia.com"):
                website = f"https://{host}"
                break
        return self._description(markdown, name), website

    @staticmethod
    def _description(markdown: str, name: str) -> str:
        """ONLY the auctioneer's own blurb — the `## <their name>` section.

        Never the whole page: every ATG profile carries the site-wide category nav
        (Fine Art, Jewellery, Collectibles, …), so reading categories from the full text
        would tag every auctioneer on the platform identically. Same trap as Easy Live's
        og:description; same answer — their words only.
        """
        heading = re.search(rf"^## {re.escape(name)}\s*$", markdown, re.M)
        if not heading:
            return ""                          # no blurb: categories stay empty, not wrong
        rest = markdown[heading.end():]
        end = re.search(r"^#{1,3} ", rest, re.M)
        return " ".join(rest[:end.start() if end else len(rest)].split())


class TheSaleroomSource(ATGSource):
    platform = "saleroom"
    display_name = "the-saleroom.com"
    base = "https://www.the-saleroom.com"


class BidSpotterSource(ATGSource):
    platform = "bidspotter"
    display_name = "BidSpotter"
    base = "https://www.bidspotter.co.uk"


class IBidderSource(ATGSource):
    platform = "ibidder"
    display_name = "i-bidder.com"
    base = "https://www.i-bidder.com"
