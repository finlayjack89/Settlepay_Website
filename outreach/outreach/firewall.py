"""Phase C — the PECR compliance firewall.

UK PECR lets you cold-email *corporate subscribers* (companies, LLPs, Scottish
partnerships) under legitimate interests with an opt-out, but NOT *individual
subscribers* (sole traders, ordinary partnerships). Companies House only lists
incorporated bodies, but we still classify FAIL-SAFE: only an explicit allowlist
of corporate company_types is contactable; anything individual, ambiguous, empty,
or unrecognised becomes `unknown` and is hard-suppressed.

The firewall processes the ENTIRE unclassified backlog each run (the floor only
fails on leads LEFT contactable, so we never sample). check_suppression consults
BOTH outreach.suppressions AND the website's inbound enquiry source, so an
existing enquirer is never cold-contacted.
"""
from __future__ import annotations
import re

from . import audit, config, db
from .states import LeadState, SubscriberClass

SUPPRESS_REASON = "PECR individual subscriber"

# Explicit allowlist of incorporated / corporate-subscriber company types.
CORPORATE_TYPES = frozenset({
    "ltd", "plc", "llp", "old-public-company",
    "private-unlimited", "private-unlimited-nsc",
    "private-limited-guarant-nsc", "private-limited-guarant-nsc-limited-exemption",
    "community-interest-company",
    "charitable-incorporated-organisation", "scottish-charitable-incorporated-organisation",
    "industrial-and-provident-society", "registered-society-non-jurisdictional",
    "royal-charter", "icvc", "investment-company-with-variable-capital",
    "protected-cell-company", "further-education-or-sixth-form-college-corporation",
    "uk-establishment", "scottish-partnership", "eeig", "ukeig",
    "united-kingdom-economic-interest-grouping",
    "european-public-limited-liability-company-se",
})
# Types treated as individual subscribers (fail-safe: suppressed).
INDIVIDUAL_TYPES = frozenset({
    "limited-partnership",  # E/W/NI partnership ~ individual; Scottish LPs are rare here
})


def classify(company_type: str | None) -> SubscriberClass:
    if company_type and company_type in CORPORATE_TYPES:
        return SubscriberClass.CORPORATE
    if company_type and company_type in INDIVIDUAL_TYPES:
        return SubscriberClass.INDIVIDUAL
    return SubscriberClass.UNKNOWN  # fail-safe: empty / unrecognised -> suppressed


def _safe_ident(name: str) -> str:
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", name or ""):
        raise ValueError(f"unsafe table identifier: {name!r}")
    return name


def check_suppression(email: str | None = None, domain: str | None = None,
                      company_number: str | None = None, *, cur=None) -> bool:
    """True if this contact must NOT be cold-emailed — present in
    outreach.suppressions OR an existing enquirer in public.<ENQUIRY_SOURCE_TABLE>."""
    src = _safe_ident(config.ENQUIRY_SOURCE_TABLE)
    own = cur is None
    conn = None
    if own:
        conn = db.connect()
        cur = conn.cursor()
    try:
        cur.execute(
            "select 1 from outreach.suppressions where "
            "(%s::text is not null and lower(email) = lower(%s::text)) or "
            "(%s::text is not null and lower(domain) = lower(%s::text)) or "
            "(%s::text is not null and company_number = %s::text) limit 1",
            (email, email, domain, domain, company_number, company_number),
        )
        if cur.fetchone():
            return True
        if email:  # existing inbound enquirer (website form) — never cold-contact
            cur.execute(f"select 1 from public.{src} where lower(email) = lower(%s) limit 1", (email,))
            if cur.fetchone():
                return True
        return False
    finally:
        if own and conn is not None:
            conn.close()


def run(*, cur=None) -> dict:
    """Classify every unclassified lead; hard-suppress individual/unknown."""
    own = cur is None
    conn = None
    if own:
        conn = db.connect()
        cur = conn.cursor()
    counts = {"corporate": 0, "individual": 0, "unknown": 0, "suppressed": 0}
    try:
        # Places-sourced leads carry no company_type — the corporate cross-reference
        # (crossref.py) classifies them instead. Skip them here.
        cur.execute(
            "select company_number, company_type from outreach.leads "
            "where subscriber_class is null and source <> 'places'"
        )
        for company_number, company_type in cur.fetchall():
            cls = classify(company_type)
            counts[cls.value] += 1
            cur.execute(
                "update outreach.leads set subscriber_class = %s, updated_at = now() "
                "where company_number = %s",
                (cls.value, company_number),
            )
            if cls in (SubscriberClass.INDIVIDUAL, SubscriberClass.UNKNOWN):
                cur.execute(
                    "update outreach.leads set state = %s, updated_at = now() "
                    "where company_number = %s",
                    (LeadState.SUPPRESSED.value, company_number),
                )
                cur.execute(
                    "insert into outreach.suppressions (company_number, reason) values (%s, %s)",
                    (company_number, SUPPRESS_REASON),
                )
                counts["suppressed"] += 1
                audit.record(
                    company_number, "suppressed", source="firewall",
                    lawful_basis=audit.LEGITIMATE_INTERESTS,
                    reason=f"{SUPPRESS_REASON} (company_type={company_type!r} -> {cls.value})",
                    cur=cur,
                )
            else:
                audit.record(
                    company_number, "classified", source="firewall",
                    lawful_basis=audit.LEGITIMATE_INTERESTS,
                    reason=f"corporate (company_type={company_type!r})", cur=cur,
                )
        if own:
            conn.commit()
        return counts
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        if own and conn is not None:
            conn.close()


if __name__ == "__main__":
    print(run())
