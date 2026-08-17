"""Google Places API (New) — local ICP business discovery. THE credit lever.

ONE instrumented wrapper for every Places call (doctrine: no raw calls elsewhere).
The field mask is PINNED per call-site because Places bills at the highest-tier field
in the mask — a stray field silently upgrades the SKU. Phone fields are NEVER
requested: it keeps us off the pricier tier AND honours the no-phones-persisted rule
by construction. Every call is metered into outreach.spend before the results return.

Billing note: one searchText CALL returns up to 20 businesses and bills as ONE Text
Search SKU unit — so discovery is cheap per lead. Cost is driven by call COUNT, paced
by the credit budget.
"""
from __future__ import annotations
import json
import re
from typing import Optional

import httpx

from . import audit, config, db, spend
from .enrich import normalise_domain

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Discovery mask: id, name, address (+ components for postcode → Companies House match),
# location, types, website, trading status. websiteUri makes this the Enterprise SKU.
# NO phone fields — compliance + keeps us off the reviews/atmosphere tier.
_DISCOVERY_MASK = ",".join(
    "places." + f for f in (
        "id", "displayName", "formattedAddress", "addressComponents",
        "location", "primaryType", "types", "websiteUri", "businessStatus"))
_DISCOVERY_SKU = "text_search_enterprise"


class PlacesUnavailable(Exception):
    """No key configured, or the Places API errored — callers degrade (skip the
    Places source), they never hard-block the pipeline."""


def _postcode(components: list[dict]) -> Optional[str]:
    for c in components or []:
        if "postal_code" in (c.get("types") or []):
            return c.get("longText") or c.get("shortText")
    return None


_POSTCODE_TAIL_RE = re.compile(r"\s*[A-Z]{1,2}[0-9][A-Z0-9]?\s*[0-9][A-Z]{2}\s*$", re.I)
_COUNTRY_PARTS = frozenset({"uk", "united kingdom", "gb", "great britain", "england",
                            "scotland", "wales", "northern ireland"})


def locality_of(address: Optional[str]) -> Optional[str]:
    """The town from a Places formatted address: '21 Cavendish St, Harrogate HG1 4NT, UK'
    -> 'Harrogate'.

    Worth the parse rather than skipping: this is a TRADING address from a maintained
    business listing, which is the one location source a draft is allowed to assert. The
    postcode is already stored as its own field but the town was only ever inside this
    string, so leads had no admissible locality at all and drafts could name no town.
    """
    if not address:
        return None
    parts = [p.strip() for p in address.split(",") if p.strip()]
    while parts and parts[-1].lower() in _COUNTRY_PARTS:
        parts.pop()
    if not parts:
        return None
    town = _POSTCODE_TAIL_RE.sub("", parts[-1]).strip()
    # a bare postcode segment leaves nothing; fall back to the segment before it
    if not town and len(parts) > 1:
        town = _POSTCODE_TAIL_RE.sub("", parts[-2]).strip()
    # a street line ("21 Cavendish St") is not a town — reject anything starting numeric
    if not town or town[0].isdigit() or len(town) < 3:
        return None
    return town


def _normalise(p: dict) -> dict:
    """Places record → the pipeline's lead shape. Deliberately drops phone."""
    return {
        "place_id": p.get("id"),
        "name": (p.get("displayName") or {}).get("text"),
        "website": p.get("websiteUri"),
        "address": p.get("formattedAddress"),
        "postcode": _postcode(p.get("addressComponents") or []),
        "primary_type": p.get("primaryType"),
        "types": p.get("types") or [],
        "business_status": p.get("businessStatus"),
    }


def text_search(query: str, *, max_results: int = 20, cur=None, client=None) -> list[dict]:
    """One Text Search call for `query` (e.g. 'emergency plumber in Otley'). Returns
    up to `max_results` normalised businesses (phone dropped). Metered as one
    Enterprise Text Search SKU unit. Raises PlacesUnavailable on no key / API error."""
    if not config.GOOGLE_MAPS_API_KEY:
        raise PlacesUnavailable("GOOGLE_MAPS_API_KEY not configured")
    spend.ensure_under_cap(cur=cur)   # the cash cap still applies as a backstop
    post = (client or httpx).post
    try:
        r = post(SEARCH_URL,
                 headers={"Content-Type": "application/json",
                          "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY,
                          "X-Goog-FieldMask": _DISCOVERY_MASK},
                 json={"textQuery": query, "maxResultCount": min(max_results, 20)},
                 timeout=30)
        r.raise_for_status()
    except Exception as e:
        raise PlacesUnavailable(f"Places text search failed: {e}") from e
    # meter the call (one SKU unit) regardless of result count
    try:
        spend.record("places", purpose="text_search", model=_DISCOVERY_SKU,
                     cost_gbp=spend.places_cost_gbp(_DISCOVERY_SKU, 1),
                     detail={"query": query}, cur=cur)
    except Exception:
        pass  # metering never fails the call that already succeeded
    return [_normalise(p) for p in r.json().get("places", [])]


# Google's own category for a business, which is structured, maintained, and a far better
# classifier than an LLM's read of the page text. The ICP gate in enrich.py is that LLM
# read, and it let `7 Core Electrical Wholesale Ltd` through — a trade wholesaler whose
# site is full of the word "electrical", scored as an electrician. Google had it filed
# under `wholesaler` the whole time.
#
# Deliberately tiny, and it should stay that way: only categories that are structurally
# never our customer belong here, because this refuses a lead outright with no appeal.
# A wholesaler bills trade accounts on credit terms; the LLM gate still handles the
# genuinely arguable cases (a shop with a till, a firm already selling online).
NEVER_ICP_TYPES = frozenset({
    "wholesaler",           # sells to trade on account, not to consumers with a card
    "corporate_office",     # a head office, not a business that takes payments
    "government_office",
    "local_government_office",
    "bank", "atm", "insurance_agency",   # regulated payments firms, not our customers
})


def never_icp(business: dict) -> bool:
    """True when Google's own categories put this business structurally outside the ICP.

    Checked at DISCOVERY, before a penny of Firecrawl, verifier or LLM credit is spent on
    it — a lead refused here costs one row we never wrote, where the same lead refused at
    enrichment has already cost a resolve, up to three scrapes and a model call.
    """
    types = {str(t).lower() for t in (business.get("types") or []) if t}
    primary = str(business.get("primary_type") or "").lower()
    if primary:
        types.add(primary)
    return bool(types & NEVER_ICP_TYPES)


def discover_to_leads(queries: list[str], *, max_results: int = 20, cur=None) -> dict:
    """Run each Text Search query and insert new businesses into outreach.leads as
    Places-sourced, UNCLASSIFIED leads (subscriber_class stays null → the corporate
    cross-reference sets it before any of them can be sent). Dedup by place_id.
    company_number is the stable synthetic id 'PLACE:<place_id>'; the Places website,
    postcode and types are kept in registered_address for downstream enrichment +
    market intelligence. Phones are never stored (the wrapper drops them)."""
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    inserted = duplicates = skipped = 0
    failed: list[str] = []
    # Exactly which leads THIS call created. A campaign attributes what its own run found,
    # and a timestamp watermark cannot do that job: Postgres freezes now() at transaction
    # start, so every row a tick inserts shares one created_at and no comparison can tell
    # them apart. The ids are the only honest answer.
    created: list[str] = []
    try:
        for q in queries:
            # Per-query isolation. text_search raises PlacesUnavailable on any API error,
            # and one raise used to escape the whole function: every insert made earlier
            # in the batch was rolled back AND discover_grid never reached its cursor
            # write, so the next tick replayed the same failing query. A single malformed
            # town or a quota blip wedged discovery indefinitely, looking alive the whole
            # time. One bad query now costs one query.
            try:
                results = text_search(q, max_results=max_results, cur=cur)
            except PlacesUnavailable as e:
                failed.append(f"{q}: {str(e)[:80]}")
                continue
            for b in results:
                pid, name = b.get("place_id"), b.get("name")
                if not pid or not name:
                    skipped += 1
                    continue
                if never_icp(b):
                    skipped += 1
                    continue
                cur.execute("select 1 from outreach.leads where place_id=%s", (pid,))
                if cur.fetchone():
                    duplicates += 1
                    continue
                addr = {"postcode": b.get("postcode"), "formatted": b.get("address"),
                        # the trading town, stored as its own field: it is the only
                        # location a draft may assert, so it has to be addressable
                        # rather than buried in the formatted string
                        "locality": locality_of(b.get("address")),
                        "website": b.get("website"), "primary_type": b.get("primary_type"),
                        "types": b.get("types"), "business_status": b.get("business_status"),
                        "query": q}
                cur.execute(
                    # domain is the manual-research dedupe key: without it, pasting the
                    # URL of a business Places already found would re-research it
                    "insert into outreach.leads (company_number, company_name, "
                    "registered_address, state, source, place_id, domain) "
                    "values (%s,%s,%s::jsonb,'discovered','places',%s,%s) "
                    "on conflict (company_number) do nothing returning company_number",
                    (f"PLACE:{pid}", name, json.dumps(addr), pid,
                     normalise_domain(b.get("website"))))
                if cur.fetchone():
                    inserted += 1
                    created.append(f"PLACE:{pid}")
                    audit.record(f"PLACE:{pid}", "discovered", source="places",
                                 lawful_basis=audit.LEGITIMATE_INTERESTS,
                                 reason=f"places: {q}", cur=cur)
                else:
                    duplicates += 1
        if own:
            conn.commit()
        out = {"inserted": inserted, "duplicates": duplicates, "skipped": skipped,
               "created": created}
        if failed:
            # surfaced, never silent: a run that quietly covered less than it was asked
            # to reads as "nothing to find" when it means "we could not look"
            out["failed_queries"] = failed
        return out
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        if own and conn is not None:
            conn.close()


GRID_CURSOR = "places_grid_cursor"


def discover_grid(*, count: int = 10, cur=None, group: str | None = None,
                  region: str | None = None, cursor_key: str | None = None) -> dict:
    """Run the next `count` queries from the town×vertical grid, paged by a cursor in
    ops_flags — so successive runs sweep the grid rather than re-hitting the same
    queries. The pacing lever for the Places credit spend.

    `group`/`region` narrow the grid to an aimed slice (auctioneers in Yorkshire), and
    `cursor_key` gives that slice its OWN cursor. Both matter: a targeted run sharing the
    global cursor would either skip most of its own slice or drag the scheduled sweep off
    course, and the operator would see neither happen.
    """
    from . import monitor, targeting
    grid = targeting.places_queries(group=group, region=region)
    if not grid:
        return {"inserted": 0, "note": "empty grid"}
    key = cursor_key or GRID_CURSOR
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    try:
        start = int(monitor.get_flag(key, cur=cur) or 0) % len(grid)
        n = min(count, len(grid))
        batch = [grid[(start + i) % len(grid)] for i in range(n)]
        res = discover_to_leads(batch, cur=cur)
        # The cursor advances by the number of queries ATTEMPTED, not the number that
        # succeeded — discover_to_leads now absorbs a failing query rather than raising
        # past this line, which is what used to leave the cursor frozen and replay the
        # same broken query every tick for ever.
        new_cursor = (start + n) % len(grid)
        monitor.set_flag(key, str(new_cursor),
                         reason="places discovery paging", cur=cur)
        res.update({"queries_run": n, "grid_cursor": new_cursor, "grid_size": len(grid),
                    "cursor_key": key})
        if own:
            conn.commit()
        return res
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        if own and conn is not None:
            conn.close()
