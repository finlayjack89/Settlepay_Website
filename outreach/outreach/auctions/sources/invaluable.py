"""Invaluable adapter (invaluable.com). Recon: docs/recon/invaluable.md.

Invaluable sits behind Cloudflare — a direct request is refused outright — so, like the
ATG sites, discovery runs through `get_rendered`.

The directory is `/auction-house?countryName=United Kingdom&page=N`: the platform's own
country filter does the UK narrowing server-side, 100 names a page. That filter is worth
using rather than fetching everything and discarding — Invaluable is overwhelmingly US,
so an unfiltered sweep would spend most of its credits on houses the PECR gate can never
pass.

The listing is name + URL only; the profile adds their own biography (categories) and a
town/country, but no postcode, no website and no email. So this is a thinner source than
the ATG platforms — the Companies House match leans on the name alone.
"""
from __future__ import annotations

import re
from typing import Iterator, Optional
from urllib.parse import quote_plus

from .. import categories as _cat
from .. import config
from ..models import AuctionLead
from .base import Source

_ENTRY_RE = re.compile(r"- \[([^\]]+)\]\((https?://[^)]*?/auction-house/([^)/?#]+)/?)\)")
_LOCALITY_RE = re.compile(r"^#### (.+)$", re.M)


class InvaluableSource(Source):
    platform = "invaluable"
    display_name = "Invaluable"
    terms_note = ("Cloudflare-protected, no robots.txt served to non-browser clients; "
                  "Invaluable's Terms reserve automated access — operator-directed.")
    fetch_profiles = True

    def directory_url(self, page: int) -> str:
        url = f"https://www.invaluable.com/auction-house?page={page}"
        if config.UK_ONLY:
            url += f"&countryName={quote_plus('United Kingdom')}"
        return url

    def iter_auctioneers(self, *, limit: Optional[int] = None) -> Iterator[AuctionLead]:
        seen: set[str] = set()
        count = 0
        for page in range(1, config.MAX_DIRECTORY_PAGES + 1):
            doc = self.client.get_rendered(self.directory_url(page))
            entries = _ENTRY_RE.findall(doc["markdown"]) if doc else []
            fresh = [e for e in entries if e[2] not in seen]
            if not fresh:
                return                 # no page, or nothing new: the end of the listing
            for name, url, slug in fresh:
                if limit is not None and count >= limit:
                    return
                seen.add(slug)
                count += 1
                yield self._lead(" ".join(name.split()), url, slug)

    def _lead(self, name: str, url: str, slug: str) -> AuctionLead:
        description, locality = "", None
        if self.fetch_profiles:
            description, locality = self._profile(url, name)
        return AuctionLead(
            platform=self.platform,
            business_name=name,
            listing_url=url,
            source_id=slug,
            location=locality,
            postcode=None,                     # Invaluable shows town + country only
            categories=_cat.detect(description) if description else [],
            own_website=None,                  # resolved during enrichment
        )

    def _profile(self, url: str, name: str) -> tuple[str, Optional[str]]:
        doc = self.client.get_rendered(url)
        if not doc:
            return "", None
        markdown = doc.get("markdown") or ""
        return self._description(markdown, name), self._locality(markdown)

    @staticmethod
    def _description(markdown: str, name: str) -> str:
        """Their own bio only — the block under the `# <name>` heading, stopping at the
        address (`####`) or the Read More cut. Never the whole page: Invaluable's
        category nav would otherwise tag every house with the same specialisms."""
        m = re.search(rf"^# {re.escape(name)}\s*$", markdown, re.M)
        if not m:
            return ""
        rest = markdown[m.end():]
        end = re.search(r"^#{2,4} |^\[Read More\]", rest, re.M)
        return " ".join(rest[:end.start() if end else len(rest)].split())

    @staticmethod
    def _locality(markdown: str) -> Optional[str]:
        """The address renders as `#### <street>` then `#### <town>, <country>`."""
        lines = _LOCALITY_RE.findall(markdown)
        for line in lines:
            if "," in line:
                return line.split(",")[0].strip() or None
        return lines[-1].strip() if lines else None
