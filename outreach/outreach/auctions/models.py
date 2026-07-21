"""The two record shapes that flow through the auction source.

`AuctionLead` is what a Source emits: the raw, per-platform listing facts, nothing
enriched. `EnrichedLead` is what the pipeline produces from it — the same facts plus
everything resolved (website, payment signal, Companies House, decision-maker, score,
brief). Keeping them as plain dataclasses (not dicts) makes the field set the contract
every Source and every output writer agrees on.

Note what is NOT here: a phone number. It is never captured, so there is no field to
hold it — the no-phones rule enforced by construction, exactly as in the Places wrapper.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AuctionLead:
    """Raw output of a Source — one auctioneer as the platform lists them."""
    platform: str                      # 'easylive' | 'saleroom' | ...
    business_name: str
    listing_url: str                   # the platform profile page
    source_id: str                     # stable per-platform id (the slug)
    location: Optional[str] = None
    postcode: Optional[str] = None
    categories: list[str] = field(default_factory=list)  # specialisms / sale categories
    next_auction_date: Optional[str] = None
    upcoming_count: int = 0            # scheduled catalogues visible = activity proxy
    own_website: Optional[str] = None  # if the platform exposes it (ELA does not)
    logo_url: Optional[str] = None     # brand asset for a future branded mock


@dataclass
class EnrichedLead:
    """A fully-worked lead: the raw facts plus everything the pipeline resolved."""
    # --- from the source ---
    platform: str
    business_name: str
    listing_url: str
    source_id: str
    location: Optional[str] = None
    postcode: Optional[str] = None
    categories: list[str] = field(default_factory=list)
    next_auction_date: Optional[str] = None
    upcoming_count: int = 0
    logo_url: Optional[str] = None

    # --- resolved website + payment behaviour (the killer hook) ---
    own_website: Optional[str] = None
    domain: Optional[str] = None
    payment_methods: list[str] = field(default_factory=list)   # detected on their site
    payment_quote: Optional[str] = None                        # the exact sentence
    signal: Optional[str] = None                               # LLM personalisation signal
    icp_fit: Optional[bool] = None

    # --- Companies House ---
    company_number: Optional[str] = None
    company_status: Optional[str] = None
    company_type: Optional[str] = None
    directors: list[str] = field(default_factory=list)          # names only (minimised)
    pecr_class: str = "unknown"        # corporate | individual | unknown

    # --- contact (never a guess: each carries how it was found) ---
    decision_maker_name: Optional[str] = None
    decision_maker_email: Optional[str] = None
    decision_maker_confidence: float = 0.0
    generic_email: Optional[str] = None                          # info@ fallback
    generic_confidence: float = 0.0

    # --- score + brief ---
    score: int = 0
    score_breakdown: dict = field(default_factory=dict)
    email_context: list[str] = field(default_factory=list)      # bullets for the drafter

    # --- provenance ---
    notes: list[str] = field(default_factory=list)              # what happened / why blank

    @classmethod
    def from_raw(cls, raw: AuctionLead) -> "EnrichedLead":
        return cls(
            platform=raw.platform, business_name=raw.business_name,
            listing_url=raw.listing_url, source_id=raw.source_id,
            location=raw.location, postcode=raw.postcode,
            categories=list(raw.categories), next_auction_date=raw.next_auction_date,
            upcoming_count=raw.upcoming_count,
            logo_url=raw.logo_url, own_website=raw.own_website)

    def as_row(self) -> dict:
        """Flat dict for CSV/JSON — lists joined for the CSV reader's sake."""
        d = dataclasses.asdict(self)
        d["categories"] = "; ".join(self.categories)
        d["payment_methods"] = "; ".join(self.payment_methods)
        d["directors"] = "; ".join(self.directors)
        d["email_context"] = " | ".join(self.email_context)
        d["notes"] = "; ".join(self.notes)
        d["score_breakdown"] = "; ".join(f"{k}={v}" for k, v in self.score_breakdown.items())
        return d
