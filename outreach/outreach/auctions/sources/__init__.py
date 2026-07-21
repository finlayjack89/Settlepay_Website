"""Source registry — the one line that adds a platform.

Every platform we can currently reach has an adapter. `platform_for_url` lets the console
accept a pasted platform link rather than a key, and reports the only thing that can now
stop a run: no adapter exists for that site yet. That is a CAPABILITY limit, not a policy
one — a scraper is per-site code, so an unknown domain would yield nothing rather than
worse results, and saying so beats failing silently.

Each adapter still carries a `terms_note`, printed into the run log. It does not block
anything; it is the record of what the site's robots/Terms actually said, so the decision
to run anyway stays visible and dated rather than forgotten.
"""
from __future__ import annotations

import re

from .atg import BidSpotterSource, IBidderSource, TheSaleroomSource
from .base import Source
from .easylive import EasyLiveSource
from .invaluable import InvaluableSource
from .liveauctioneers import LiveAuctioneersSource

REGISTRY: dict[str, type[Source]] = {
    EasyLiveSource.platform: EasyLiveSource,
    TheSaleroomSource.platform: TheSaleroomSource,
    BidSpotterSource.platform: BidSpotterSource,
    IBidderSource.platform: IBidderSource,
    LiveAuctioneersSource.platform: LiveAuctioneersSource,
    InvaluableSource.platform: InvaluableSource,
}

# domain fragment -> registered platform key, so a pasted link resolves
DOMAIN_TO_PLATFORM = {
    "easyliveauction": "easylive",
    "the-saleroom": "saleroom",
    "saleroom": "saleroom",
    "bidspotter": "bidspotter",
    "i-bidder": "ibidder",
    "ibidder": "ibidder",
    "liveauctioneers": "liveauctioneers",
    "invaluable": "invaluable",
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
    raise PlatformNotSupported(
        f"No adapter for {url_or_key!r} yet — scraping is per-site code, so an unknown "
        f"platform would return nothing rather than poor results. "
        f"Supported today: {', '.join(sorted(REGISTRY))}.")


def get_source(platform: str, *, client=None) -> Source:
    if platform not in REGISTRY:
        raise ValueError(
            f"unknown platform {platform!r}; known: {', '.join(sorted(REGISTRY)) or '(none)'}")
    return REGISTRY[platform](client=client)


def platforms() -> list[str]:
    return sorted(REGISTRY)
