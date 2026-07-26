"""The drafting FACTS block — verified constants, resolved before a word is written.

Why this exists
---------------
`enrichment.signal` is free text: a paragraph the drafter reads and re-asserts. That gave
the model no way to tell a fact from a plausible-sounding guess, and it filled the gaps —
greeting "Hi John," on a lead with no contact on file, and placing businesses in their
registered-office town (usually the accountant's, not where they trade).

A facts block is the same information as typed constants, each carrying WHERE it came from
and WHETHER it is verified:

    {"company_name":   Fact("Adam Partridge Auctioneers", "own_site",       verified=True),
     "contact_name":   Fact(None,           None,                          verified=False),
     "location":       Fact("Macclesfield", "places_listing",              verified=True),
     "vertical":       Fact("auctioneers",  "sic_label",                   verified=True),
     "payment_method": Fact("bank transfer","site_quote",                  verified=True)}

Two rules make it work:

1. **An unknown is explicit.** A field we could not establish is present with value None,
   never absent. The drafter is TOLD "there is no location for this lead" instead of being
   left a hole it will fill with something that sounds right.
2. **Provenance decides admissibility, not availability.** We nearly always *have* a
   locality; it is only admissible if it came from a trading source (their own site, a
   Places listing). A registered office is data we hold but may not assert.

What this is NOT
----------------
This is not a mail-merge template. The constants bound WHICH entities may appear; the
drafter still writes the prose, because byte-similar bodies across a send list are the
clearest bulk-mail fingerprint there is (and the anti-fingerprint rotation in draft.py
exists precisely to avoid it). Constants for facts, generated prose for everything else.
"""
from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

# The fields a draft may name. Adding one here makes it available to the playbook AND
# admissible to the grounding check — those must never drift apart, which is why there is
# a single list rather than a set per call site.
FIELDS = ("company_name", "contact_name", "contact_role", "location", "region", "vertical",
          "payment_method", "established")

# Without this the lead is not draftable at all: you cannot write to a business you cannot
# name. Everything else is optional-but-declared.
REQUIRED = ("company_name",)

# Sources whose locality is where the business TRADES. A Companies House registered office
# is routinely a formation agent or the company's accountant, so it is deliberately absent:
# it is data we hold but may not assert. (See enrich._TRADING_LOCALITY_SOURCES.)
TRADING_LOCATION_SOURCES = frozenset({
    "places_listing", "own_site", "platform_listing",
    # A registered office is admissible ONLY once geo.registered_office_shared() has
    # confirmed it is the company's own premises rather than an accountant's. That check
    # earns a distinct label, so a bare "companies_house" — an address nobody checked —
    # is still rejected here. Belt and braces: the ladder decides, this enforces.
    "companies_house_confirmed",
})


@dataclass(frozen=True)
class Fact:
    """One constant. `value is None` means 'established as unknown', not 'not looked at'."""
    value: Optional[str] = None
    source: Optional[str] = None
    verified: bool = False

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def parse(cls, raw: Any) -> "Fact":
        """Tolerant of a bare string, a partial dict, or junk — a malformed facts blob
        must degrade to 'unknown', never raise into the drafting loop."""
        if isinstance(raw, cls):
            return raw
        if isinstance(raw, str):
            return cls(value=raw.strip() or None, source="unknown", verified=False)
        if isinstance(raw, dict):
            value = raw.get("value")
            value = value.strip() if isinstance(value, str) and value.strip() else None
            return cls(value=value, source=raw.get("source") or None,
                       verified=bool(raw.get("verified")) and value is not None)
        return cls()

    def __bool__(self) -> bool:
        return self.value is not None


def _clean(value: Optional[str]) -> Optional[str]:
    if not value or not str(value).strip():
        return None
    return " ".join(str(value).split())


def build(*, company_name: Optional[str], company_name_source: str = "companies_house",
          contact_name: Optional[str] = None, contact_name_source: Optional[str] = None,
          contact_role: Optional[str] = None, contact_role_source: Optional[str] = None,
          location: Optional[str] = None, location_source: Optional[str] = None,
          region: Optional[str] = None, region_source: Optional[str] = None,
          vertical: Optional[str] = None, vertical_source: Optional[str] = None,
          payment_method: Optional[str] = None,
          payment_method_source: Optional[str] = None,
          established: Optional[str] = None,
          established_source: Optional[str] = None) -> dict[str, Fact]:
    """Assemble a facts block, applying admissibility rules as it goes.

    A location from a non-trading source is DROPPED to unknown rather than carried with
    verified=False, because a value that exists is a value a prompt can leak. The only safe
    representation of an inadmissible fact is its absence.

    `region` is deliberately NOT subject to that rule. A broad geography ("the North
    West") stays true even when the precise town does not — an accountant is almost
    always in the same region as the client — so a lead whose town we cannot claim can
    still be placed, which beats saying nothing at all.
    """
    loc = _clean(location)
    if loc and location_source not in TRADING_LOCATION_SOURCES:
        loc, location_source = None, None

    def fact(value, source):
        cleaned = _clean(value)
        return Fact(cleaned, source if cleaned else None, verified=cleaned is not None)

    return {
        "company_name": fact(company_name, company_name_source),
        "contact_name": fact(contact_name, contact_name_source),
        "contact_role": fact(contact_role, contact_role_source),
        "location": fact(loc, location_source),
        "region": fact(region, region_source),
        "vertical": fact(vertical, vertical_source),
        "payment_method": fact(payment_method, payment_method_source),
        "established": fact(established, established_source),
    }


def loads(raw: Any) -> dict[str, Fact]:
    """DB jsonb (or None) -> a complete block. Missing fields become explicit unknowns, so
    every caller can rely on all FIELDS being present."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    data = raw if isinstance(raw, dict) else {}
    return {name: Fact.parse(data.get(name)) for name in FIELDS}


def dumps(facts: dict[str, Fact]) -> str:
    return json.dumps({name: facts[name].as_dict() for name in FIELDS})


def missing_required(facts: dict[str, Fact]) -> list[str]:
    return [name for name in REQUIRED if not facts.get(name, Fact())]


def is_draftable(facts: dict[str, Fact] | None) -> bool:
    """A lead is draftable once its constants are RESOLVED — not once they are all found.
    A block whose optional fields are known-unknown is complete; the drafter writes around
    them. This is the gate that stops a lead reaching the drafter on free text alone."""
    return bool(facts) and not missing_required(facts)


# --------------------------------------------------------------------------- #
#  The drafter's view
# --------------------------------------------------------------------------- #
def as_prompt_block(facts: dict[str, Fact]) -> str:
    """The facts as the drafter sees them: every field listed, unknowns stated outright.

    Listing the unknowns is load-bearing. Omitting a field reads as "not mentioned" and the
    model supplies its own; "location: UNKNOWN — do not name any place" is an instruction
    it can actually follow.
    """
    lines = ["FACTS (the ONLY company, person or place you may name — all verified):"]
    for name in FIELDS:
        fact = facts.get(name) or Fact()
        if fact.value:
            lines.append(f"- {name}: {fact.value}")
        else:
            lines.append(f"- {name}: UNKNOWN — do not state one, and do not imply one")
    return "\n".join(lines)


def allowed_tokens(facts: dict[str, Fact]) -> set[str]:
    """Every lowercase word appearing in a resolved fact — the vocabulary of named things
    a draft is permitted to use. Used by the grounding check in draft.py."""
    out: set[str] = set()
    for name in FIELDS:
        fact = facts.get(name) or Fact()
        if fact.value:
            for word in re.split(r"[^a-z0-9]+", fact.value.lower()):
                if len(word) >= 2:
                    out.add(word)
    return out


def value(facts: dict[str, Fact] | None, name: str) -> Optional[str]:
    fact = (facts or {}).get(name)
    return fact.value if fact else None


def summarise(facts: dict[str, Fact]) -> str:
    """One-line provenance trail for the audit record."""
    parts: Iterable[str] = (
        f"{name}={facts[name].value!r}({facts[name].source})" if facts[name] else f"{name}=-"
        for name in FIELDS if name in facts)
    return " ".join(parts)
