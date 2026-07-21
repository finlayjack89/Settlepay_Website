"""Source registry — the one line that adds a platform.

Each platform's adapter is registered by its `platform` key. Adding the-saleroom /
BidSpotter / i-bidder later is: write the adapter (after its own robots + Terms recon),
import it here, add it to REGISTRY. Everything downstream is platform-agnostic.

`platform_for_url` lets the console accept a pasted platform link rather than a key, and
— importantly — distinguishes "not an auction platform I know" from "a platform I know
but have no adapter for yet, because it needs its own recon first".
"""
from __future__ import annotations

import re

from .base import Source
from .easylive import EasyLiveSource

REGISTRY: dict[str, type[Source]] = {
    EasyLiveSource.platform: EasyLiveSource,
    # 'saleroom':  TheSaleroomSource,   # TODO: recon the-saleroom.com robots + ToS first
    # 'bidspotter': BidSpotterSource,   # TODO: recon bidspotter.co.uk robots + ToS first
    # 'ibidder':    IBidderSource,      # TODO: recon i-bidder.com robots + ToS first
}

# domain fragment -> registered platform key, so a pasted link resolves
DOMAIN_TO_PLATFORM = {"easyliveauction": "easylive"}

# Recognised platforms with NO adapter yet. Each needs its own robots.txt + Terms of Use
# recon before any scraping — one site's answer never carries to another.
PLANNED = {
    "the-saleroom": "the-saleroom.com", "saleroom": "the-saleroom.com",
    "bidspotter": "bidspotter.co.uk", "i-bidder": "i-bidder.com",
    "ibidder": "i-bidder.com", "invaluable": "invaluable.com",
    "liveauctioneers": "liveauctioneers.com",
}


class PlatformNotSupported(Exception):
    """No adapter for this platform — the message is shown to the operator."""


def _host(value: str) -> str:
    s = re.sub(r"^\s*(?:https?:)?/*", "", (value or "").strip().lower()).split("/")[0]
    return s[4:] if s.startswith("www.") else s


def platform_for_url(url_or_key: str) -> str:
    """Resolve a pasted platform link (or bare key) to a registered platform key."""
    raw = (url_or_key or "").strip().lower()
    if raw in REGISTRY:
        return raw
    host = _host(raw)
    for fragment, platform in DOMAIN_TO_PLATFORM.items():
        if fragment in host or fragment in raw:
            return platform
    for fragment, domain in PLANNED.items():
        if fragment in host or fragment in raw:
            raise PlatformNotSupported(
                f"{domain} is a known auction platform, but there's no adapter for it yet — "
                f"it needs its own robots.txt + Terms of Use recon first. "
                f"Supported today: {', '.join(sorted(REGISTRY))}.")
    raise PlatformNotSupported(
        f"Not a supported auction platform: {url_or_key!r}. "
        f"Supported today: {', '.join(sorted(REGISTRY))}.")


def get_source(platform: str, *, client=None) -> Source:
    if platform not in REGISTRY:
        raise ValueError(
            f"unknown platform {platform!r}; known: {', '.join(sorted(REGISTRY)) or '(none)'}")
    return REGISTRY[platform](client=client)


def platforms() -> list[str]:
    return sorted(REGISTRY)
