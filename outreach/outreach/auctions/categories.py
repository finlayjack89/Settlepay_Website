"""Auction category vocabulary + value tiers.

Auctioneer profile text is free-form marketing prose, so splitting a description on
commas yields sentence fragments, not categories. Instead we match a curated vocabulary
of real auction specialisms — which gives clean, comparable categories AND the value
signal the score needs (a fine-art / jewellery house is a better SettlePay lead than a
general-clearance one: higher lot values, more remote/phone bidders paying by transfer).

Tiers: 3 = high-value specialist, 2 = mid, 1 = general/clearance. `value_score` maps the
categories found to the 0..1 factor the scorer weights.
"""
from __future__ import annotations

import re

CATEGORY_TIERS: dict[str, int] = {
    # tier 3 — high-value specialist
    "fine art": 3, "antiques": 3, "jewellery": 3, "watches": 3, "silver": 3,
    "gold": 3, "coins": 3, "medals": 3, "militaria": 3, "ceramics": 3,
    "porcelain": 3, "asian art": 3, "clocks": 3, "wine": 3, "whisky": 3,
    "classic cars": 3, "stamps": 3, "glass": 3, "bronzes": 3, "paintings": 3,
    # tier 2 — mid
    "collectables": 2, "memorabilia": 2, "sporting": 2, "books": 2, "art": 2,
    "pictures": 2, "furniture": 2, "toys": 2, "vintage": 2, "textiles": 2,
    "rugs": 2, "musical instruments": 2, "machinery": 2, "plant": 2, "tools": 2,
    "vehicles": 2, "agricultural": 2, "jewelry": 2,
    # tier 1 — general / clearance
    "general": 1, "clearance": 1, "household": 1, "commercial": 1, "surplus": 1,
    "property": 1, "land": 1,
}

# longest phrases first so "fine art" wins over "art", "asian art" over "art"
_ORDERED = sorted(CATEGORY_TIERS, key=len, reverse=True)
_PATTERNS = [(c, re.compile(rf"\b{re.escape(c)}\b", re.I)) for c in _ORDERED]


def detect(*texts: str) -> list[str]:
    """Categories present across the given texts, de-duplicated, highest tier first.
    A phrase already covered by a longer match it is a substring of is dropped
    ('art' when 'fine art' matched)."""
    blob = " ".join(t for t in texts if t)
    found: list[str] = []
    for cat, pat in _PATTERNS:
        if pat.search(blob) and not any(cat in bigger and cat != bigger for bigger in found):
            found.append(cat)
    return sorted(found, key=lambda c: (-CATEGORY_TIERS[c], c))


def value_score(categories: list[str]) -> float:
    """0..1 category-value factor: driven by the highest tier present, nudged up when a
    lead has several specialisms. A house with no recognised category scores 0."""
    if not categories:
        return 0.0
    top = max(CATEGORY_TIERS.get(c, 0) for c in categories)
    base = {3: 1.0, 2: 0.6, 1: 0.3}.get(top, 0.0)
    breadth = min(len([c for c in categories if CATEGORY_TIERS.get(c, 0) >= 2]), 3) * 0.03
    return min(1.0, base + breadth)
