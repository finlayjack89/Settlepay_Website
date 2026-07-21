"""Companies House Advanced Search client (free API).

Auth is HTTP Basic with the API key as username and an empty password. Stays well
under the 600 req / 5 min ceiling via a per-run request cap + a minimum interval
between calls.
"""
from __future__ import annotations
import time
from typing import Iterator, Optional

import httpx

from . import config

BASE = "https://api.company-information.service.gov.uk"


class RateLimitExceeded(Exception):
    pass


class RateLimiter:
    """Enforce a minimum interval between requests AND a hard per-run cap.

    The cap is the budget brake (build: <=50 req/run); the interval keeps bursts
    well under Companies House's 600 req / 5 min limit.
    """

    def __init__(self, max_requests: int, min_interval: float = 0.6):
        self.max_requests = max_requests
        self.min_interval = min_interval
        self.count = 0
        self._last = 0.0

    def acquire(self) -> None:
        if self.count >= self.max_requests:
            raise RateLimitExceeded(f"per-run Companies House cap reached ({self.max_requests})")
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self.count += 1


class CompaniesHouseClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        max_requests: Optional[int] = None,
        min_interval: float = 0.6,
        transport=None,
    ):
        self.api_key = api_key or config.COMPANIES_HOUSE_API_KEY
        if not self.api_key:
            raise RuntimeError("COMPANIES_HOUSE_API_KEY not set (outreach/.env)")
        self.limiter = RateLimiter(max_requests or config.CH_MAX_REQUESTS_PER_RUN, min_interval)
        self._client = httpx.Client(
            base_url=BASE, auth=(self.api_key, ""), timeout=20, transport=transport
        )

    def advanced_search(self, *, sic_codes: Optional[str] = None,
                        company_status: str = "active", size: int = 50,
                        start_index: int = 0, incorporated_from: Optional[str] = None,
                        incorporated_to: Optional[str] = None,
                        company_name_includes: Optional[str] = None) -> dict:
        self.limiter.acquire()
        params = {"company_status": company_status, "size": size, "start_index": start_index}
        if sic_codes:
            params["sic_codes"] = sic_codes
        if incorporated_from:
            params["incorporated_from"] = incorporated_from
        if incorporated_to:                         # require a trading age (cull fresh shells)
            params["incorporated_to"] = incorporated_to
        if company_name_includes:                   # name-based discovery (e.g. auctioneers)
            params["company_name_includes"] = company_name_includes
        r = self._client.get("/advanced-search/companies", params=params)
        r.raise_for_status()
        return r.json()

    def iter_companies(self, *, sic_codes: Optional[str] = None,
                       company_status: str = "active", target: int, page_size: int = 50,
                       incorporated_from: Optional[str] = None,
                       incorporated_to: Optional[str] = None,
                       company_name_includes: Optional[str] = None) -> Iterator[dict]:
        """Yield up to `target` companies, paging via start_index, honouring the cap."""
        seen = 0
        start = 0
        while seen < target:
            data = self.advanced_search(
                sic_codes=sic_codes, company_status=company_status,
                size=min(page_size, target - seen), start_index=start,
                incorporated_from=incorporated_from, incorporated_to=incorporated_to,
                company_name_includes=company_name_includes,
            )
            items = data.get("items", [])
            if not items:
                break
            for it in items:
                yield it
                seen += 1
                if seen >= target:
                    break
            start += len(items)

    def get_profile(self, company_number: str) -> dict:
        """Fetch the full company profile (for the dormancy gate). Counts against
        the per-run cap, so use sparingly (one extra free call to skip a paid scrape)."""
        self.limiter.acquire()
        r = self._client.get(f"/company/{company_number}")
        r.raise_for_status()
        return r.json()

    def get_officers(self, company_number: str, *, items: int = 35) -> list[dict]:
        """Active officers (directors/members) for the decision-maker lookup. Free,
        but counts against the per-run cap. Returns the raw CH items; the caller
        minimises (keeps name/role/appointed_on, drops DOB + address)."""
        self.limiter.acquire()
        r = self._client.get(f"/company/{company_number}/officers",
                             params={"items_per_page": items, "register_view": "false"})
        r.raise_for_status()
        return r.json().get("items", [])

    def search_companies(self, q: str, *, items: int = 5) -> list[dict]:
        """Search the register by name (used by the Places corporate cross-reference).
        Returns up to `items` matches, each with title, company_number, company_type,
        company_status, and an address dict. Counts against the per-run cap."""
        self.limiter.acquire()
        r = self._client.get("/search/companies",
                             params={"q": q, "items_per_page": items})
        r.raise_for_status()
        return r.json().get("items", [])

    def close(self) -> None:
        self._client.close()
