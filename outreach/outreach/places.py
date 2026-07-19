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
from typing import Optional

import httpx

from . import config, spend

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
