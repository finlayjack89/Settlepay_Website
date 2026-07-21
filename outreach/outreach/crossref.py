"""Corporate cross-reference — the PECR send-legality gate for Places-sourced leads.

A Places business arrives without a Companies House number, so we can't yet know if
it's a corporate subscriber (cold-emailable) or a sole trader / individual (NOT
cold-emailable under PECR). This stage searches Companies House by name and matches on
name similarity + postcode:
  - a confident match to an ACTIVE corporate-type company  -> 'corporate'  (sendable)
  - a confident match to a non-corporate type              -> 'individual' (research-only)
  - no confident match (likely a sole trader off-register, or unmatched)
                                                            -> 'unknown'    (research-only)

FAIL-CLOSED: only a confident corporate match becomes sendable; everything else is kept
but never cold-emailed. Research-only leads (individual/unknown) are still valuable —
market intelligence, a re-incorporation watch (crossref_checked_at), and future
consent/postal channels — so we DON'T discard them; the downstream enrich/draft/send
stages simply ignore non-corporate leads (the enrich backlog already filters corporate).
"""
from __future__ import annotations
import difflib
import re
from typing import Optional

from . import audit, db
from .companies_house import CompaniesHouseClient
from .firewall import SubscriberClass, classify

_SUFFIX_RE = re.compile(r"\b(ltd|limited|llp|plc|co|company|uk|the)\b", re.I)

NAME_STRONG = 0.85     # name ratio with a postcode match
NAME_ONLY = 0.94       # name ratio strong enough on its own


def _norm_name(s: str) -> str:
    s = _SUFFIX_RE.sub(" ", (s or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _outward(pc: Optional[str]) -> str:
    """Outward code of a UK postcode (the part before the space)."""
    return re.sub(r"\s+", "", (pc or "").upper())[:-3] if pc and len(re.sub(r"\s+", "", pc)) > 3 else ""


def match_company(ch: CompaniesHouseClient, name: str, postcode: Optional[str]
                  ) -> tuple[SubscriberClass, Optional[str], Optional[str]]:
    """Return (subscriber_class, matched_company_number, reason). Conservative: a
    confident corporate match is required for 'corporate'; else research-only."""
    want_name = _norm_name(name)
    want_out = _outward(postcode)
    try:
        results = ch.search_companies(name, items=5)
    except Exception as e:
        return SubscriberClass.UNKNOWN, None, f"ch search failed: {str(e)[:80]}"

    best = None  # (ratio, item, postcode_match)
    for it in results:
        ratio = difflib.SequenceMatcher(None, want_name, _norm_name(it.get("title", ""))).ratio()
        addr = it.get("address") or {}
        pc_match = bool(want_out) and _outward(addr.get("postal_code")) == want_out
        strong = (ratio >= NAME_STRONG and pc_match) or ratio >= NAME_ONLY
        if strong and (best is None or ratio > best[0]):
            best = (ratio, it, pc_match)

    if best is None:
        return SubscriberClass.UNKNOWN, None, "no confident CH match (sole trader / unmatched)"
    ratio, it, pc_match = best
    number = it.get("company_number")
    status = (it.get("company_status") or "").lower()
    cls = classify(it.get("company_type"))
    if cls is SubscriberClass.CORPORATE and status == "active":
        return SubscriberClass.CORPORATE, number, f"corporate match {number} (name {ratio:.2f}, pc {pc_match})"
    if cls is SubscriberClass.CORPORATE:  # matched but dissolved/inactive → not sendable
        return SubscriberClass.UNKNOWN, number, f"matched {number} but status={status}"
    return SubscriberClass.INDIVIDUAL, number, f"matched {number}, non-corporate type"


def run(*, limit: int = 50, cur=None, ch: Optional[CompaniesHouseClient] = None) -> dict:
    """Classify up to `limit` Places leads awaiting cross-reference. Sets
    subscriber_class + matched_company_number + crossref_checked_at."""
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    owns_ch = ch is None
    counts = {"corporate": 0, "individual": 0, "unknown": 0}
    try:
        cur.execute(
            "select company_number, company_name, registered_address->>'postcode' "
            "from outreach.leads where source='places' and subscriber_class is null "
            "and state='discovered' order by created_at limit %s", (limit,))
        rows = cur.fetchall()
        if rows and ch is None:
            ch = CompaniesHouseClient()
        for company_number, name, postcode in rows:
            cls, matched, reason = match_company(ch, name, postcode)
            counts[cls.value] += 1
            cur.execute(
                "update outreach.leads set subscriber_class=%s, matched_company_number=%s, "
                "crossref_checked_at=now(), updated_at=now() where company_number=%s",
                (cls.value, matched, company_number))
            audit.record(company_number, "crossref", source="crossref",
                         lawful_basis=audit.LEGITIMATE_INTERESTS,
                         reason=f"{cls.value}: {reason}", cur=cur)
        if own:
            conn.commit()
        return counts
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        if owns_ch and ch is not None:
            ch.close()
        if own and conn is not None:
            conn.close()
