"""Lead targeting policy — which companies are worth spending discovery credits on.

Two free levers (see docs/system-assessment.md), applied BEFORE we pay for website
discovery:
  1. Pull SIC verticals that correlate with a real web presence + card/invoice
     payments (the SettlePay ICP), rather than SPV-heavy sectors like estate agents.
  2. Reject obvious non-trading shells (property SPVs, holding/nominee/topco
     companies, dormant accounts) up front.

Auctioneers have no clean dedicated SIC, so they're discovered by company-name match
("auction") rather than by SIC — see find_leads.
"""
from __future__ import annotations
import re

# vertical -> {sic: label}. Curated ICP: small UK businesses that take card/invoice
# payments and tend to run their own website.
ICP: dict[str, dict[str, str]] = {
    "Professional services": {
        "69201": "Accountants", "69202": "Bookkeepers", "69109": "Solicitors",
        "70229": "Consultants", "73110": "Advertising agencies", "71111": "Architects",
    },
    "Clinics & health": {
        "86230": "Dental practices", "75000": "Veterinary",
        "86900": "Health practitioners", "96040": "Physical well-being",
    },
    "Trades & home services": {
        "43210": "Electricians", "43220": "Plumbing & heating",
        "43390": "Building finishing", "41202": "Domestic builders",
    },
    "In-person services": {  # salons, barbers, mobile hairdressers
        "96020": "Hair & beauty", "96090": "Personal services",
    },
}

# auctioneers: discovered by name, not SIC; labels still shown on the dashboard
AUCTIONEER_LABELS = {"47791": "Antiques / auctioneers", "47990": "Auctioneers (retail)"}

# all SIC -> label, including legacy estate-agent rows already in the DB
SIC_LABELS: dict[str, str] = {sic: lbl for v in ICP.values() for sic, lbl in v.items()}
SIC_LABELS.update(AUCTIONEER_LABELS)
SIC_LABELS.setdefault("68310", "Estate agents")

# the default SIC sweep for discovery (the ICP verticals)
TARGET_SICS: list[str] = list({sic for v in ICP.values() for sic in v})

# names that signal a non-trading shell / SPV / holding entity — skip pre-spend
EXCLUDE_NAME_RE = re.compile(
    r"\b(PROPERT(Y|IES)|HOLDING(S)?|INVESTMENT(S)?|SPV|NOMINEE(S)?|VENTURES?|"
    r"CAPITAL|TOPCO|BIDCO|MIDCO|HOLDCO|GROUP\s+HOLDINGS|TRUSTEE(S)?|"
    r"DORMANT|ESTATES?\s+OF|MANAGEMENT\s+COMPANY|RTM\b|FREEHOLD)\b",
    re.I,
)

# CH last-accounts types that indicate a non-trading / no-substance company
DORMANT_ACCOUNT_TYPES = frozenset({"dormant", "no-accounts", "null", "none"})


def is_excluded_name(name: str | None) -> bool:
    """True if the company name looks like an SPV / holding / non-trading shell."""
    return bool(name) and bool(EXCLUDE_NAME_RE.search(name))


def is_dormant(last_accounts_type: str | None) -> bool:
    """True if CH last-accounts type marks the company as non-trading/dormant."""
    return (last_accounts_type or "").strip().lower() in DORMANT_ACCOUNT_TYPES
