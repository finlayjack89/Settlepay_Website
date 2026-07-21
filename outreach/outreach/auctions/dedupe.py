"""Dedupe (Phase 3) — the same auctioneer appears across platforms and, once we add
the-saleroom / BidSpotter, will appear more than once. Collapse on the strongest key
available: resolved website domain first, then Companies House number, then a normalised
name+postcode as a last resort. Built now so multi-source later is trivial.

Keeps the HIGHEST-scored instance of each duplicate (best enrichment wins), and records
on the survivor which platforms it was seen on.
"""
from __future__ import annotations

import re

from .models import EnrichedLead


def _name_key(name: str, postcode: str | None) -> str:
    n = re.sub(r"[^a-z0-9]+", "", (name or "").lower())
    pc = re.sub(r"\s+", "", (postcode or "").lower())
    return f"name:{n}|{pc}"


def _keys(lead: EnrichedLead) -> list[str]:
    keys = []
    if lead.domain:
        keys.append(f"domain:{lead.domain}")
    if lead.company_number:
        keys.append(f"cn:{lead.company_number}")
    keys.append(_name_key(lead.business_name, lead.postcode))   # always present
    return keys


def dedupe(leads: list[EnrichedLead]) -> list[EnrichedLead]:
    """Collapse duplicates by any shared key, keeping the highest-scored. Union-find so a
    chain (A shares a domain with B, B shares a CH number with C) collapses to one."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    # link every key of a lead together, and each key to the lead's index
    key_to_leads: dict[str, list[int]] = {}
    for i, lead in enumerate(leads):
        ks = _keys(lead)
        for k in ks:
            find(k)
            key_to_leads.setdefault(k, []).append(i)
        for k in ks[1:]:
            union(ks[0], k)

    # group lead indices by their key's root
    groups: dict[str, set[int]] = {}
    for k, idxs in key_to_leads.items():
        root = find(k)
        groups.setdefault(root, set()).update(idxs)

    seen: set[int] = set()
    out: list[EnrichedLead] = []
    for idxs in groups.values():
        idxs = {i for i in idxs if i not in seen}
        if not idxs:
            continue
        members = [leads[i] for i in idxs]
        seen.update(idxs)
        winner = max(members, key=lambda ld: ld.score)
        if len(members) > 1:
            platforms = sorted({m.platform for m in members})
            winner.notes.append(f"deduped {len(members)} listings across {', '.join(platforms)}")
        out.append(winner)
    return sorted(out, key=lambda ld: -ld.score)
