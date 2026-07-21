"""Trading name -> Companies House company, for leads the plain name search can't place.

`crossref.match_company` searches `/search/companies`, which is a RELEVANCE-RANKED
keyword search. That works when the business trades under its registered name, and fails
badly when it doesn't — which is most of the auction market:

    "Adam Partridge Auctioneers & Valuers" -> Aston's, Batemans, Catherine Southon
    "1818 Auctioneers"                     -> a brass band (BESSES O' TH' BARN BAND (1818))

because the generic words ("auctioneers & valuers") dominate the ranking. In a 19-lead
auction sample that left 12 leads unclassified, i.e. never emailable — a far bigger loss
than any enrichment gap.

This module uses `/advanced-search/companies` instead, which does NO ranking:
`company_name_includes` is a literal substring filter and `location` filters on the
registered-office address. So we search on the DISTINCTIVE words of the trading name, then
corroborate each candidate against everything else we know — postcode, the domain we
already resolved, SIC code, town.

The scoring is deliberately conservative and evidence-weighted, because the failure it
guards against is real and specific: two different businesses at the SAME address. The
sample threw one up immediately — 1818 Auctioneers and NORTH WEST AUCTIONS LIMITED both
sit at LA7 7FP (J36 Rural Auction Centre), and they are not the same company. A postcode
alone must never be enough.
"""
from __future__ import annotations

import difflib
import re
from typing import Optional

from .companies_house import CompaniesHouseClient
from .firewall import SubscriberClass, classify

# Words that identify nobody — every auction house has them, so they can neither be
# searched on usefully nor count as evidence of a match.
GENERIC_WORDS = frozenset({
    "auction", "auctions", "auctioneer", "auctioneers", "auctioneering", "saleroom",
    "salerooms", "sale", "sales", "valuer", "valuers", "valuation", "valuations",
    "ltd", "limited", "llp", "plc", "co", "company", "companies", "group", "holdings",
    "the", "and", "of", "for", "at", "services", "service", "trading", "trade",
    "house", "rooms", "room", "online", "uk", "gb", "england", "british", "national",
    "international", "centre", "center", "estate", "estates", "gallery", "galleries",
    "antique", "antiques", "fine", "art", "arts", "bid", "bidding", "live", "com",
})

# SIC codes that corroborate "this is an auction business". From the sector research:
# 47990 other retail not in stores, 47791 antiques incl. auction houses, 47799 other
# second-hand, 69109 legal/other, 82990 other business support (used by several
# auctioneers), 01629 support to animal production (livestock marts).
AUCTION_SIC_CODES = frozenset({"47990", "47791", "47799", "69109", "82990", "01629"})

_SUFFIX_RE = re.compile(r"\b(ltd|limited|llp|plc|co|company|uk|the)\b", re.I)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Enough evidence to act on. Reached by two independent corroborations, or one conclusive
# one (an exact domain identity). A lone postcode hit scores 3 and cannot pass.
ACCEPT_SCORE = 5
# Even a high score can't rescue a name that looks nothing like the candidate — this is
# the co-located-business guard.
MIN_NAME_RATIO = 0.34


def _norm(s: str) -> str:
    return _NON_ALNUM.sub(" ", _SUFFIX_RE.sub(" ", (s or "").lower())).strip()


def _squash(s: str) -> str:
    return _NON_ALNUM.sub("", _norm(s))


def _compare_key(s: str) -> str:
    """Normalised name with the sector's shared vocabulary removed, for similarity.

    Comparing raw names penalises exactly the businesses we care about: 'A F Brock and
    Co Ltd' vs 'A.F. BROCK & CO. LTD' scores 0.82 purely on leftover filler, and
    'Adam Partridge Auctioneers & Valuers' vs 'ADAM PARTRIDGE LIMITED' scores 0.58 —
    both are obviously the same business once the words every auctioneer shares are
    dropped.
    """
    return " ".join(w for w in _norm(s).split() if w not in GENERIC_WORDS) or _norm(s)


def _outward(pc: Optional[str]) -> str:
    flat = re.sub(r"\s+", "", (pc or "").upper())
    return flat[:-3] if len(flat) > 3 else ""


def distinctive_tokens(name: str) -> list[str]:
    """The words that actually identify this business, longest first.

    'Adam Partridge Auctioneers & Valuers' -> ['partridge', 'adam']
    'A & C Auctions of Pendle'             -> ['pendle']
    """
    seen, out = set(), []
    for w in _norm(name).split():
        if len(w) >= 3 and w not in GENERIC_WORDS and w not in seen:
            seen.add(w)
            out.append(w)
    return sorted(out, key=len, reverse=True)


def search_terms(name: str) -> list[str]:
    """Substring queries to try, most specific first.

    `company_name_includes` matches a CONTIGUOUS substring, so an adjacent pair is tried
    before single words ('adam partridge' beats 'partridge' alone, 157-hit 'brock'
    being the cautionary case) — but a pair that spans dropped generic words will not
    match, which is why single tokens follow as the fallback.
    """
    words = [w for w in _norm(name).split() if len(w) >= 3 and w not in GENERIC_WORDS]
    terms = [" ".join(words[i:i + 2]) for i in range(len(words) - 1)]
    terms += distinctive_tokens(name)
    seen, out = set(), []
    for t in terms:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _is_substantive(key: str) -> bool:
    """Does this comparison key actually identify anybody?

    '1818 Auctioneers' reduces to '1818', which matches '1818 LIMITED' perfectly and
    means nothing — any company with those digits in its name would score identically,
    and the domain would appear to agree too. A key needs real length AND a word, not
    just a number, before a perfect similarity score counts as evidence.
    """
    flat = _NON_ALNUM.sub("", key)
    return len(flat) >= 5 and bool(re.search(r"[a-z]{3}", key))


def _domain_agreement(company_name: str, domain: Optional[str]) -> int:
    """How strongly the registered name and the resolved domain agree.

    5 = the domain IS the company name ('adampartridge.co.uk' <- ADAM PARTRIDGE LIMITED).
    3 = every distinctive word of the registered name appears in the domain.
    0 = no agreement, or nothing to compare.

    This is the single best signal available, because the domain was resolved from the
    auctioneer's own mailto/website rather than guessed — two independent routes to the
    same business agreeing is much stronger than either one alone.
    """
    if not domain:
        return 0
    stem = _NON_ALNUM.sub("", domain.split(".")[0].lower())
    company = _squash(company_name)
    if not stem or not company:
        return 0
    if stem == company:
        return 5
    words = [w for w in _norm(company_name).split()
             if len(w) >= 4 and w not in GENERIC_WORDS]
    if words and all(w in stem for w in words):
        return 5 if len(words) > 1 else 3
    if company in stem or stem in company:
        return 3
    return 0


def score_candidate(item: dict, *, name: str, postcode: Optional[str],
                    domain: Optional[str], locality: Optional[str]) -> tuple[int, float, list[str]]:
    """Weigh one Companies House candidate. Returns (score, name_ratio, reasons)."""
    addr = item.get("registered_office_address") or {}
    ch_name = item.get("company_name") or ""
    key = _compare_key(name)
    ratio = difflib.SequenceMatcher(None, key, _compare_key(ch_name)).ratio()
    substantive = _is_substantive(key)

    score, why = 0, []
    if postcode and addr.get("postal_code"):
        want = re.sub(r"\s+", "", postcode.upper())
        got = re.sub(r"\s+", "", (addr["postal_code"] or "").upper())
        if want == got:
            score += 3
            why.append("postcode exact")
        elif _outward(postcode) and _outward(postcode) == _outward(addr["postal_code"]):
            score += 2
            why.append("postcode outward")

    agreement = _domain_agreement(ch_name, domain) if substantive else 0
    if agreement:
        score += agreement
        why.append(f"domain agrees ({agreement})")

    if not substantive:
        # nothing distinctive to compare — the name can corroborate, never carry
        if ratio >= 0.85:
            score += 1
            why.append(f"name {ratio:.2f} (weak key)")
    elif ratio >= 0.92:
        # a near-identical registered name is not a coincidence you meet by chance; it
        # still needs one corroboration to clear ACCEPT_SCORE on its own.
        score += 4
        why.append(f"name {ratio:.2f}")
    elif ratio >= 0.85:
        score += 3
        why.append(f"name {ratio:.2f}")
    elif ratio >= 0.70:
        score += 2
        why.append(f"name {ratio:.2f}")
    elif ratio >= 0.55:
        score += 1
        why.append(f"name {ratio:.2f}")

    if set(item.get("sic_codes") or []) & AUCTION_SIC_CODES:
        score += 1
        why.append("auction SIC")

    if locality and addr.get("locality") and \
            locality.strip().lower() == addr["locality"].strip().lower():
        score += 1
        why.append("town")

    return score, ratio, why


def find_company(ch: CompaniesHouseClient, name: str, *, postcode: Optional[str] = None,
                 domain: Optional[str] = None, locality: Optional[str] = None,
                 max_queries: int = 4) -> Optional[dict]:
    """Best-evidenced active company for this trading name, or None.

    Returns {company_number, company_name, company_type, score, name_ratio, reasons,
    postcode}. `max_queries` bounds the Companies House spend per lead (the API allows
    600 requests per rolling 5 minutes across the whole pipeline).
    """
    passed: dict[str, dict] = {}
    for term in search_terms(name)[:max_queries]:
        try:
            data = ch.advanced_search(company_name_includes=term, size=30)
        except Exception:
            continue
        items = data.get("items") or []
        if len(items) >= 30:
            # too broad to be evidence on its own ('brock' -> 157 hits); narrowing by the
            # registered-office town is what makes a common surname usable.
            if not locality:
                continue
            try:
                data = ch.advanced_search(company_name_includes=term, location=locality,
                                          size=30)
            except Exception:
                continue
            items = data.get("items") or []
            if len(items) >= 30:
                continue                 # still unusably broad
        for item in items:
            number = item.get("company_number")
            if not number:
                continue
            score, ratio, why = score_candidate(
                item, name=name, postcode=postcode, domain=domain, locality=locality)
            if ratio < MIN_NAME_RATIO or score < ACCEPT_SCORE:
                continue
            prior = passed.get(number)
            if prior is None or score > prior["score"]:
                passed[number] = {
                    "company_number": number,
                    "company_name": item.get("company_name"),
                    "company_type": item.get("company_type"),
                    "postcode": (item.get("registered_office_address") or {}).get("postal_code"),
                    "score": score, "name_ratio": ratio, "reasons": why,
                }
        if any(c["score"] >= 8 for c in passed.values()):
            break                        # conclusive; no point spending more queries

    if not passed:
        return None
    ranked = sorted(passed.values(), key=lambda c: (c["score"], c["name_ratio"]), reverse=True)
    if len(ranked) > 1 and ranked[0]["score"] == ranked[1]["score"] \
            and abs(ranked[0]["name_ratio"] - ranked[1]["name_ratio"]) < 0.02:
        # Two companies fit equally well — e.g. a group with sibling entities at one
        # address. Guessing risks emailing the wrong legal person; unknown is recoverable,
        # a wrong match is not.
        return None
    return ranked[0]


def classify_deep(ch: CompaniesHouseClient, name: str, *, postcode: Optional[str] = None,
                  domain: Optional[str] = None, locality: Optional[str] = None
                  ) -> tuple[SubscriberClass, Optional[str], str]:
    """Deep match wrapped in the PECR verdict, same contract as crossref.match_company.

    Fail-closed exactly as the shallow matcher does: only an ACTIVE corporate type is
    sendable. Advanced search is already filtered to active companies, so a match here is
    active by construction.
    """
    found = find_company(ch, name, postcode=postcode, domain=domain, locality=locality)
    if not found:
        return SubscriberClass.UNKNOWN, None, "no confident CH match (deep)"
    cls = classify(found["company_type"])
    detail = (f"{found['company_name']} {found['company_number']} "
              f"[score {found['score']}, {', '.join(found['reasons'])}]")
    if cls is SubscriberClass.CORPORATE:
        return SubscriberClass.CORPORATE, found["company_number"], f"deep match {detail}"
    return SubscriberClass.INDIVIDUAL, found["company_number"], \
        f"deep match {detail}, non-corporate type"
