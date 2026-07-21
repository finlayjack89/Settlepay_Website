"""Source registry — the one line that adds a platform.

Each platform's adapter is registered by its `platform` key. Adding the-saleroom /
BidSpotter / i-bidder later is: write the adapter (after its own robots + Terms recon),
import it here, add it to REGISTRY. Everything downstream is platform-agnostic.
"""
from __future__ import annotations

from typing import Optional

from .base import Source
from .easylive import EasyLiveSource

REGISTRY: dict[str, type[Source]] = {
    EasyLiveSource.platform: EasyLiveSource,
    # 'saleroom':  TheSaleroomSource,   # TODO: recon the-saleroom.com robots + ToS first
    # 'bidspotter': BidSpotterSource,   # TODO: recon bidspotter.co.uk robots + ToS first
    # 'ibidder':    IBidderSource,      # TODO: recon i-bidder.com robots + ToS first
}


def get_source(platform: str, *, client=None) -> Source:
    if platform not in REGISTRY:
        raise ValueError(
            f"unknown platform {platform!r}; known: {', '.join(sorted(REGISTRY)) or '(none)'}")
    return REGISTRY[platform](client=client)


def platforms() -> list[str]:
    return sorted(REGISTRY)
