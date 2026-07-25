"""Where a business actually is — resolved from free sources, ranked by trustworthiness.

Every UK business has a location; the problem was never availability, it was knowing
which address we are allowed to call theirs. A registered office is public for every
limited company, but it is routinely the accountant's or a formation agent's — asserting
it as "based in X" is what put a Cheshire auctioneer in Westbury-on-Severn.

So this module supplies the two things that make an address usable:

1. `registered_office_shared()` — is this registered office a real trading address or a
   shared agent one? Measured, not guessed: count the ACTIVE companies registered at the
   same postcode via Companies House advanced search. Real premises come back in single
   figures; an accountant's office or a virtual-office provider comes back in the
   hundreds or thousands. Observed while building:

       SK11 9DU  Ashley Waller (their own saleroom)          10
       SK7 4PL   A F Brock (their own shop)                  10
       CH4 9GB   Adam Partridge's registered office         417   <- accountant
       W1W 7LT   365 Consultancy's registered office       9175   <- virtual office

2. `postcode_info()` — postcodes.io, a free keyless UK API over ONS open data, for the
   region and a fallback town. Its `region` ("North West") is a safe, broad geography
   that is almost always assertable; its parish field is NOT a reliable town name
   ("Preston Patrick" for Milnthorpe, "King's Lynn and West Norfolk" for King's Lynn),
   so a real locality from Companies House or a listing always wins over it.

Both are free. Neither needs a key. The point of the ranking is that a location we state
should be one the business itself would recognise as theirs.
"""
from __future__ import annotations

import re
from typing import Optional

import httpx

POSTCODES_IO = "https://api.postcodes.io/postcodes/"

# Above this many active companies at one postcode, the address is a shared service
# (accountant, formation agent, virtual office) and says nothing about where they trade.
# Set well clear of the observed real-premises band (0-10) so a genuine business park or
# a shared industrial estate is not misread as an agent.
SHARED_OFFICE_THRESHOLD = 25

_POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}[0-9][A-Z0-9]?)\s*([0-9][A-Z]{2})\b")

# Administrative labels that are not what anyone calls their town. Unitary authorities
# and combined districts read badly in a sentence — "firms in Bath and North East
# Somerset" is nobody's idea of a local reference, and "Bournemouth, Christchurch and
# Poole" is three towns at once. When the only name available is one of these we drop to
# the region instead, which at least reads like something a person would say.
_ADMIN_NOISE = ("unparished", " and ", ",", "/")
_ADMIN_PREFIXES = ("city of ", "borough of ", "royal borough of ", "county of ")

_cache: dict[str, Optional[dict]] = {}


def normalise_postcode(value: Optional[str]) -> Optional[str]:
    """'sk102bd' -> 'SK10 2BD'. None when there is no valid UK postcode in the string."""
    if not value:
        return None
    m = _POSTCODE_RE.search(value.upper().replace(" ", " "))
    return f"{m.group(1)} {m.group(2)}" if m else None


def _tidy_admin_name(value: str) -> Optional[str]:
    """An administrative name reduced to something sayable, or None if it never was.

    'City of Edinburgh' -> 'Edinburgh'. 'Bath and North East Somerset' -> None, because
    no local would answer "where are you based?" with a unitary authority.
    """
    name = (value or "").strip()
    low = name.lower()
    for prefix in _ADMIN_PREFIXES:
        if low.startswith(prefix):
            name, low = name[len(prefix):].strip(), low[len(prefix):].strip()
    if not name or any(n in low for n in _ADMIN_NOISE):
        return None
    return name


def _pick_town(result: dict) -> Optional[str]:
    """The most conversational town name postcodes.io offers, or None.

    Deliberately conservative: this is only ever a fallback, because an administrative
    parish is often not what the business would call home. Returning None is a perfectly
    good answer — the region still places them, and vaguely-right beats precisely-odd.
    """
    district_raw = (result.get("admin_district") or "").strip()
    parish = _tidy_admin_name(result.get("parish") or "")
    if parish and parish.lower() != district_raw.lower():
        return parish
    return _tidy_admin_name(district_raw)


def postcode_info(postcode: Optional[str], *, client: Optional[httpx.Client] = None
                  ) -> Optional[dict]:
    """{postcode, town, district, region, country, lat, lon} or None.

    Free and keyless, but memoised per process anyway: enrichment re-reads the same
    postcodes across a batch and there is no reason to re-ask a public service for an
    answer that cannot change.
    """
    pc = normalise_postcode(postcode)
    if not pc:
        return None
    if pc in _cache:
        return _cache[pc]
    owns = client is None
    client = client or httpx.Client(timeout=15)
    try:
        r = client.get(POSTCODES_IO + pc.replace(" ", ""))
        result = (r.json() or {}).get("result") if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None                       # never cache a transient failure as "no data"
    finally:
        if owns:
            client.close()
    info = None
    if result:
        info = {"postcode": result.get("postcode") or pc,
                "town": _pick_town(result),
                "district": result.get("admin_district"),
                "region": result.get("region") or result.get("country"),
                "country": result.get("country"),
                "lat": result.get("latitude"), "lon": result.get("longitude")}
    _cache[pc] = info
    return info


def registered_office_shared(ch, postcode: Optional[str]) -> Optional[bool]:
    """True when this registered office is a shared/agent address, None if unknowable.

    None matters as much as the booleans: a Companies House outage must not be read as
    "it's fine, use the address" — an unknown location is recoverable, a wrong one is a
    claim the recipient knows is false.
    """
    pc = normalise_postcode(postcode)
    if not pc or ch is None:
        return None
    try:
        data = ch.advanced_search(location=pc, size=1)
    except Exception:
        return None
    hits = data.get("hits")
    if hits is None:
        return None
    return hits > SHARED_OFFICE_THRESHOLD


def resolve_location(*, site_postcode: Optional[str] = None,
                     site_town: Optional[str] = None,
                     listing_town: Optional[str] = None,
                     listing_postcode: Optional[str] = None,
                     registered_town: Optional[str] = None,
                     registered_postcode: Optional[str] = None,
                     ch=None, client: Optional[httpx.Client] = None) -> dict:
    """Best assertable location, with the source that earned it.

    Returns {town, region, postcode, source} — town/region may be None, source is None
    when nothing was admissible. Ranked by how close the source is to the business's own
    account of itself:

        own_site                   they published this address themselves
        places_listing             a maintained trading listing
        companies_house_confirmed  a registered office CHECKED not to be an agent's
        postcodes_io               a region derived from a postcode we hold

    The `_confirmed` suffix is deliberate: facts.build only admits a location from that
    label, so an unchecked registered office cannot reach a draft even by mistake.

    The region is filled from whichever postcode we ended up trusting, so even a lead
    whose town is unusable can still be placed in "the North West" — broad, safe, and
    true, which beats saying nothing.
    """
    for town, postcode, source in (
        (site_town, site_postcode, "own_site"),
        (listing_town, listing_postcode, "places_listing"),
    ):
        if town or postcode:
            info = postcode_info(postcode, client=client) or {}
            return {"town": town or info.get("town"),
                    "region": info.get("region"),
                    "postcode": normalise_postcode(postcode),
                    "source": source if (town or info.get("town")) else None}

    # A registered office is admissible only once we have checked it is theirs.
    if registered_town or registered_postcode:
        shared = registered_office_shared(ch, registered_postcode)
        if shared is False:
            info = postcode_info(registered_postcode, client=client) or {}
            return {"town": registered_town or info.get("town"),
                    "region": info.get("region"),
                    "postcode": normalise_postcode(registered_postcode),
                    "source": "companies_house_confirmed"}
        # Shared, or unknown: the TOWN is not ours to claim, but the region still is —
        # an accountant in the same region is the normal case, and "the North West" is
        # broad enough to stay true either way.
        info = postcode_info(registered_postcode, client=client) or {}
        return {"town": None, "region": info.get("region"),
                "postcode": normalise_postcode(registered_postcode),
                "source": "postcodes_io" if info.get("region") else None}
    return {"town": None, "region": None, "postcode": None, "source": None}
