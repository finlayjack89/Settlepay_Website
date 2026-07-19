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
from typing import Optional

import httpx

from . import audit, config, db, spend

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
    try:
        for q in queries:
            for b in text_search(q, max_results=max_results, cur=cur):
                pid, name = b.get("place_id"), b.get("name")
                if not pid or not name:
                    skipped += 1
                    continue
                cur.execute("select 1 from outreach.leads where place_id=%s", (pid,))
                if cur.fetchone():
                    duplicates += 1
                    continue
                addr = {"postcode": b.get("postcode"), "formatted": b.get("address"),
                        "website": b.get("website"), "primary_type": b.get("primary_type"),
                        "types": b.get("types"), "business_status": b.get("business_status"),
                        "query": q}
                cur.execute(
                    "insert into outreach.leads (company_number, company_name, "
                    "registered_address, state, source, place_id) "
                    "values (%s,%s,%s::jsonb,'discovered','places',%s) "
                    "on conflict (company_number) do nothing returning company_number",
                    (f"PLACE:{pid}", name, json.dumps(addr), pid))
                if cur.fetchone():
                    inserted += 1
                    audit.record(f"PLACE:{pid}", "discovered", source="places",
                                 lawful_basis=audit.LEGITIMATE_INTERESTS,
                                 reason=f"places: {q}", cur=cur)
                else:
                    duplicates += 1
        if own:
            conn.commit()
        return {"inserted": inserted, "duplicates": duplicates, "skipped": skipped}
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        if own and conn is not None:
            conn.close()


def discover_grid(*, count: int = 10, cur=None) -> dict:
    """Run the next `count` queries from the town×vertical grid, paged by a cursor in
    ops_flags — so successive runs sweep the grid rather than re-hitting the same
    queries. The pacing lever for the Places credit spend."""
    from . import monitor, targeting
    grid = targeting.places_queries()
    if not grid:
        return {"inserted": 0, "note": "empty grid"}
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    try:
        start = int(monitor.get_flag("places_grid_cursor", cur=cur) or 0) % len(grid)
        n = min(count, len(grid))
        batch = [grid[(start + i) % len(grid)] for i in range(n)]
        res = discover_to_leads(batch, cur=cur)
        new_cursor = (start + n) % len(grid)
        monitor.set_flag("places_grid_cursor", str(new_cursor),
                         reason="places discovery paging", cur=cur)
        res.update({"queries_run": n, "grid_cursor": new_cursor, "grid_size": len(grid)})
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
