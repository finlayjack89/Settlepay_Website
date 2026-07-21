"""The Source interface — one adapter per auction platform.

A Source turns a platform into a stream of `AuctionLead`s and nothing more; all
enrichment, dedupe, scoring and output are platform-agnostic and live outside. That
split is the whole point: adding the-saleroom / BidSpotter / i-bidder later is a new
Source subclass and a registry line, touching no other code.

Each Source MUST, before doing anything, have had its robots.txt AND Terms of Use
checked (see docs/recon/<platform>.md). The `terms_note` field carries that verdict so
it travels with the adapter and shows up in the run log — a Source whose terms forbid
automated access is not silently run.
"""
from __future__ import annotations

import abc
from typing import Iterator, Optional

from ..http import PoliteClient
from ..models import AuctionLead


class Source(abc.ABC):
    #: short platform key, e.g. 'easylive'
    platform: str = ""
    #: human name
    display_name: str = ""
    #: one line on what the robots.txt + Terms recon concluded (travels with the adapter)
    terms_note: str = ""

    def __init__(self, client: Optional[PoliteClient] = None):
        self.client = client or PoliteClient()

    @abc.abstractmethod
    def iter_auctioneers(self, *, limit: Optional[int] = None) -> Iterator[AuctionLead]:
        """Yield auctioneers as `AuctionLead`s, newest/most-relevant first where the
        platform allows it. `limit` caps the count for a sample run. Must be resumable
        and idempotent: re-running yields the same records, and the cached HTTP layer
        means it does not re-hit the site."""
        raise NotImplementedError

    def close(self) -> None:
        self.client.close()
