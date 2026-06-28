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

    def advanced_search(self, *, sic_codes: str, company_status: str = "active",
                        size: int = 50, start_index: int = 0) -> dict:
        self.limiter.acquire()
        r = self._client.get(
            "/advanced-search/companies",
            params={"sic_codes": sic_codes, "company_status": company_status,
                    "size": size, "start_index": start_index},
        )
        r.raise_for_status()
        return r.json()

    def iter_companies(self, *, sic_codes: str, company_status: str = "active",
                       target: int, page_size: int = 50) -> Iterator[dict]:
        """Yield up to `target` companies, paging via start_index, honouring the cap."""
        seen = 0
        start = 0
        while seen < target:
            data = self.advanced_search(
                sic_codes=sic_codes, company_status=company_status,
                size=min(page_size, target - seen), start_index=start,
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

    def close(self) -> None:
        self._client.close()
