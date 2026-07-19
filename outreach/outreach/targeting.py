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

# vertical -> {sic: label}. Curated ICP: small UK businesses that bill AWAY from a
# fixed till — mobile, remote, appointment- or invoice-based — for whom an online
# branded card page + invoicing is NEW infrastructure. Deliberately EXCLUDES
# fixed-till retail (shops, salons, barbers, cafes): they already take card in person
# at a counter, so an online page is redundant (the ICP-fit gate disqualifies them,
# but we also don't waste discovery/enrich spend finding them).
ICP: dict[str, dict[str, str]] = {
    "Trades & home services": {   # mobile, job-then-invoice — the core ICP
        "43210": "Electricians", "43220": "Plumbing & heating",
        "43390": "Building finishing", "41202": "Domestic builders",
        "43999": "Specialised construction", "81210": "Cleaning services",
    },
    "Clinics & health": {         # appointment/invoice-based private practices
        "86230": "Dental practices", "75000": "Veterinary",
        "86900": "Health practitioners",
    },
    "Professional & advisory": {  # invoice-based services
        "69201": "Accountants", "69202": "Bookkeepers", "69109": "Solicitors",
        "70229": "Consultants", "71111": "Architects", "71129": "Surveyors / engineering",
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

# --- Google Places local discovery grid (town × invoice/mobile vertical) ---
# Deliberately invoice/mobile ICP verticals (no fixed-till retail). Each query is one
# Places call (≤20 businesses). Expand PLACES_TOWNS to widen coverage / spend more credit.
PLACES_VERTICAL_QUERIES: list[str] = [
    "emergency electrician in {town}", "plumber and heating engineer in {town}",
    "builder in {town}", "roofer in {town}", "joiner or carpenter in {town}",
    "private physiotherapy clinic in {town}", "private dental practice in {town}",
    "veterinary practice in {town}", "chiropractor or osteopath in {town}",
    "chartered surveyor in {town}", "accountant in {town}", "bookkeeper in {town}",
    "architect in {town}", "auctioneer near {town}", "mobile mechanic in {town}",
    "commercial cleaning company in {town}",
]
PLACES_TOWNS: list[str] = [
    "Harrogate", "York", "Leeds", "Otley", "Ilkley", "Skipton", "Wetherby", "Ripon",
    "Wakefield", "Bradford", "Halifax", "Huddersfield", "Selby", "Knaresborough",
    "Pontefract", "Castleford", "Keighley", "Northallerton", "Thirsk", "Boroughbridge",
]


def places_queries() -> list[str]:
    """The full town × vertical discovery grid (stable order → a cursor can page it)."""
    return [tpl.format(town=t) for t in PLACES_TOWNS for tpl in PLACES_VERTICAL_QUERIES]

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
