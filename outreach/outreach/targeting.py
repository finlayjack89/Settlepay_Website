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

# --- Google Places local discovery grid (vertical × town) ---
# Deliberately invoice/mobile ICP verticals (no fixed-till retail). Each query is one
# Places call (≤20 businesses), billed per call — so grid SIZE and ORDER are the credit
# levers. The grid is deliberately larger than the credit can consume: the CREDIT_FLOOR
# gate in run.py is the brake, so the grid must never run dry, and the tail simply never
# gets reached. Both lists are therefore ordered best-first.
PLACES_VERTICAL_QUERIES: list[str] = [
    # core trades — mobile, job-priced, invoice-after-the-visit (the sharpest ICP)
    "emergency electrician in {town}", "plumber and heating engineer in {town}",
    "builder in {town}", "roofer in {town}", "joiner or carpenter in {town}",
    "plasterer in {town}", "glazier and window fitter in {town}",
    "landscaping and groundworks company in {town}", "tree surgeon in {town}",
    "driveway and paving contractor in {town}", "scaffolding company in {town}",
    "damp proofing specialist in {town}", "kitchen and bathroom fitter in {town}",
    "flooring contractor in {town}", "solar panel installer in {town}",
    "electric vehicle charger installer in {town}",
    "air conditioning and refrigeration engineer in {town}",
    "locksmith in {town}", "pest control company in {town}",
    "security and alarm installer in {town}", "mobile mechanic in {town}",
    "commercial cleaning company in {town}",
    # professional / advisory — invoice-based B2B, no till at all
    "chartered surveyor in {town}", "accountant in {town}", "bookkeeper in {town}",
    "architect in {town}", "letting agent in {town}", "IT support company in {town}",
    "marketing agency in {town}", "recruitment agency in {town}",
    # private clinics — appointment deposits + private-pay invoicing
    "private physiotherapy clinic in {town}", "private dental practice in {town}",
    "veterinary practice in {town}", "chiropractor or osteopath in {town}",
    "private GP clinic in {town}", "podiatry clinic in {town}",
    # events, logistics and specialist — deposits, hire fees, staged invoices
    "auctioneer near {town}", "funeral director in {town}", "removals company in {town}",
    "skip hire company in {town}", "haulage company in {town}",
    "tool and plant hire in {town}", "event catering company in {town}",
    "marquee and event hire in {town}", "printing company in {town}",
    "sign maker in {town}",
]
PLACES_TOWNS: list[str] = [
    # home patch (Yorkshire) — the original grid, kept first
    "Harrogate", "York", "Leeds", "Otley", "Ilkley", "Skipton", "Wetherby", "Ripon",
    "Wakefield", "Bradford", "Halifax", "Huddersfield", "Selby", "Knaresborough",
    "Pontefract", "Castleford", "Keighley", "Northallerton", "Thirsk", "Boroughbridge",
    # London by borough/town — one "in London" query would return a meaningless 20
    "Croydon", "Bromley", "Ealing", "Richmond upon Thames", "Kingston upon Thames",
    "Wimbledon", "Islington", "Camden", "Hackney", "Greenwich", "Barnet", "Harrow",
    "Enfield", "Romford", "Uxbridge", "Sutton", "Hounslow", "Wandsworth", "Lewisham",
    "Walthamstow", "Ilford", "Watford",
    # major cities
    "Manchester", "Birmingham", "Bristol", "Liverpool", "Sheffield", "Nottingham",
    "Leicester", "Newcastle upon Tyne", "Glasgow", "Edinburgh", "Cardiff", "Belfast",
    "Southampton", "Portsmouth", "Brighton", "Reading", "Milton Keynes", "Coventry",
    "Derby", "Stoke-on-Trent", "Hull", "Plymouth", "Norwich", "Ipswich", "Luton",
    "Northampton", "Oxford", "Cambridge", "Exeter", "Bournemouth", "Swindon",
    "Peterborough", "Aberdeen", "Dundee", "Swansea", "Newport", "Sunderland",
    "Middlesbrough", "Doncaster", "Preston",
    # large towns — North West / North East / Cumbria
    "Warrington", "Bolton", "Stockport", "Oldham", "Rochdale", "Wigan", "Salford",
    "Blackburn", "Blackpool", "Burnley", "Chester", "Crewe", "Macclesfield",
    "Altrincham", "Bury", "Southport", "St Helens", "Birkenhead", "Lancaster",
    "Carlisle", "Kendal", "Barrow-in-Furness", "Darlington", "Durham", "Gateshead",
    "Hartlepool", "Stockton-on-Tees", "Redcar", "Hexham", "Morpeth", "Ashington",
    "Blyth", "Alnwick", "Penrith", "Workington", "Whitehaven",
    # Yorkshire & Humber / East Midlands
    "Scarborough", "Grimsby", "Scunthorpe", "Lincoln", "Chesterfield", "Mansfield",
    "Rotherham", "Barnsley", "Worksop", "Newark-on-Trent", "Loughborough", "Grantham",
    "Boston", "Skegness", "Beverley", "Bridlington", "Goole", "Morley", "Dewsbury",
    "Brighouse", "Todmorden", "Settle", "Malton", "Pickering", "Whitby", "Driffield",
    # West Midlands / Welsh Marches
    "Nuneaton", "Rugby", "Solihull", "Wolverhampton", "Walsall", "Dudley",
    "West Bromwich", "Telford", "Shrewsbury", "Stafford", "Cannock", "Tamworth",
    "Lichfield", "Burton upon Trent", "Redditch", "Worcester", "Kidderminster",
    "Hereford", "Gloucester", "Cheltenham", "Stroud",
    # South West
    "Bath", "Weston-super-Mare", "Taunton", "Yeovil", "Bridgwater", "Trowbridge",
    "Chippenham", "Salisbury", "Truro", "Falmouth", "Penzance", "Newquay",
    "St Austell", "Bodmin", "Barnstaple", "Bideford", "Tiverton", "Torquay",
    "Paignton", "Newton Abbot", "Exmouth", "Weymouth", "Dorchester", "Poole",
    "Christchurch",
    # South East
    "Andover", "Basingstoke", "Winchester", "Eastleigh", "Fareham", "Havant",
    "Chichester", "Worthing", "Crawley", "Horsham", "Guildford", "Woking",
    "Farnborough", "Aldershot", "Camberley", "Epsom", "Redhill", "Sevenoaks",
    "Maidstone", "Ashford", "Canterbury", "Dover", "Folkestone", "Margate",
    "Chatham", "Gillingham", "Dartford", "Gravesend", "Tonbridge",
    "Royal Tunbridge Wells", "Eastbourne", "Hastings", "Bexhill-on-Sea", "Lewes",
    # East of England / Home Counties
    "Colchester", "Chelmsford", "Basildon", "Southend-on-Sea", "Harlow", "Braintree",
    "Clacton-on-Sea", "Bury St Edmunds", "Lowestoft", "Great Yarmouth", "King's Lynn",
    "Thetford", "Huntingdon", "St Neots", "Bedford", "Wellingborough", "Kettering",
    "Corby", "Banbury", "Bicester", "Aylesbury", "High Wycombe", "Slough",
    "Maidenhead", "Bracknell", "Newbury", "Didcot", "Witney", "Stevenage", "Hitchin",
    "Hemel Hempstead", "St Albans", "Hertford", "Bishop's Stortford",
    "Welwyn Garden City", "Dunstable", "Leighton Buzzard",
    # Scotland
    "Paisley", "East Kilbride", "Livingston", "Falkirk", "Stirling", "Perth",
    "Inverness", "Ayr", "Kilmarnock", "Dumfries", "Kirkcaldy", "Dunfermline",
    "Greenock", "Motherwell", "Hamilton", "Cumbernauld", "Elgin", "Oban",
    "Fort William", "St Andrews",
    # Wales
    "Wrexham", "Llandudno", "Rhyl", "Colwyn Bay", "Aberystwyth", "Carmarthen",
    "Llanelli", "Neath", "Port Talbot", "Bridgend", "Merthyr Tydfil", "Pontypridd",
    "Caerphilly", "Cwmbran", "Monmouth", "Haverfordwest", "Brecon",
    # Northern Ireland
    "Lisburn", "Newtownabbey", "Londonderry", "Craigavon", "Newry", "Ballymena",
    "Coleraine", "Omagh", "Enniskillen",
]


def places_queries() -> list[str]:
    """The full vertical × town discovery grid (stable order → a cursor can page it).

    VERTICAL-major, deliberately: the credit runs out long before the grid does, so
    truncation must drop the weakest VERTICALS rather than whole regions. SettlePay
    sells an online payment page — geography barely matters, vertical fit matters a
    lot — so sweeping the whole country for electricians before spending a penny on
    sign makers is the right trade. Towns are de-duplicated (order-preserving) so an
    accidental repeat in the list above can never bill twice.
    """
    towns = list(dict.fromkeys(PLACES_TOWNS))
    return [tpl.format(town=t) for tpl in PLACES_VERTICAL_QUERIES for t in towns]

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
