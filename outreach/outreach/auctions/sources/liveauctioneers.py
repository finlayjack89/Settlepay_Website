"""LiveAuctioneers adapter (liveauctioneers.com). Recon: docs/recon/liveauctioneers.md.

The whole directory is ONE page — `/auctioneer/directory/`, ~4,400 houses grouped under
country headings, of which the "United Kingdom" block (~290) is the only part usable
here: the PECR gate is Companies House, so a non-UK house is spend with no outcome.

The page is client-side rendered, so discovery goes through `get_rendered`. The listing
gives name + profile URL only; the profile adds their own biography (categories) and,
via the static-map URL the page builds, a full address — which is what makes the
Companies House match reliable. It exposes no website and no email, so website discovery
falls back to the enrichment stage, exactly as with Easy Live.
"""
from __future__ import annotations

import re
from typing import Iterator, Optional
from urllib.parse import unquote

from .. import categories as _cat
from ..models import AuctionLead
from .base import Source

DIRECTORY = "https://www.liveauctioneers.com/auctioneer/directory/"

_ENTRY_RE = re.compile(r"^- \[([^\]]+)\]\((https?://[^)]*?/auctioneer/(\d+)/[^)?#]*)", re.M)
_UK_HEADING_RE = re.compile(r"^United Kingdom\s*$", re.M)
_MAP_CENTER_RE = re.compile(r"[?&]center=([^&\s)]+)")
_POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}[0-9][A-Z0-9]?)\s?([0-9][A-Z]{2})\b")


class LiveAuctioneersSource(Source):
    platform = "liveauctioneers"
    display_name = "LiveAuctioneers"
    terms_note = ("robots.txt disallows /auctioneers/ (the legacy path); the directory "
                  "lives at /auctioneer/directory/ and is not disallowed — "
                  "operator-directed.")
    fetch_profiles = True

    def iter_auctioneers(self, *, limit: Optional[int] = None) -> Iterator[AuctionLead]:
        doc = self.client.get_rendered(DIRECTORY)
        if not doc:
            return
        count = 0
        for name, url, house_id in self._uk_entries(doc["markdown"]):
            if limit is not None and count >= limit:
                return
            count += 1
            yield self._lead(name, url, house_id)

    @staticmethod
    def _uk_entries(markdown: str) -> list[tuple[str, str, str]]:
        """Entries under the 'United Kingdom' heading, stopping at the next country.

        Countries are plain lines between list blocks, so the section ends at the first
        non-empty line that is not a list item.
        """
        head = _UK_HEADING_RE.search(markdown)
        if not head:
            return []
        out: list[tuple[str, str, str]] = []
        for line in markdown[head.end():].splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            m = _ENTRY_RE.match(stripped)
            if not m:
                break                          # next country heading: UK section is done
            out.append((" ".join(m.group(1).split()), m.group(2), m.group(3)))
        return out

    def _lead(self, name: str, url: str, house_id: str) -> AuctionLead:
        description, address = "", ""
        if self.fetch_profiles:
            description, address = self._profile(url, name)
        return AuctionLead(
            platform=self.platform,
            business_name=name,
            listing_url=url,
            source_id=house_id,
            location=self._locality(address),
            postcode=self._postcode(address),
            categories=_cat.detect(description) if description else [],
            own_website=None,                  # not exposed; resolved during enrichment
        )

    def _profile(self, url: str, name: str) -> tuple[str, str]:
        doc = self.client.get_rendered(url)
        if not doc:
            return "", ""
        markdown = doc.get("markdown") or ""
        return self._description(markdown, name), self._address(markdown)

    @staticmethod
    def _description(markdown: str, name: str) -> str:
        """Their own 'About <name>' blurb only — never the whole page, which carries
        LiveAuctioneers' site-wide category nav and would tag every house identically."""
        m = re.search(rf"^About {re.escape(name)}\s*$", markdown, re.M)
        if not m:
            return ""
        rest = markdown[m.end():]
        end = re.search(r"^#{1,4} |^\[Read More\]", rest, re.M)
        return " ".join(rest[:end.start() if end else len(rest)].split())

    @staticmethod
    def _address(markdown: str) -> str:
        """The page builds a Google static-map URL whose `center=` is the full address —
        a more reliable read than the visually-split address lines."""
        m = _MAP_CENTER_RE.search(markdown)
        return " ".join(unquote(m.group(1)).replace("+", " ").split()) if m else ""

    @staticmethod
    def _postcode(address: str) -> Optional[str]:
        m = _POSTCODE_RE.search(address.upper())
        return f"{m.group(1)} {m.group(2)}" if m else None

    @classmethod
    def _locality(cls, address: str) -> Optional[str]:
        """The word before the postcode is the county/town — good enough as a locality
        hint, and only ever used to help the Companies House match."""
        m = _POSTCODE_RE.search(address.upper())
        if not m:
            return None
        before = address[:m.start()].split()
        return before[-1] if before else None
