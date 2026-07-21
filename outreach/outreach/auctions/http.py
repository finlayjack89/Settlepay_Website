"""A polite HTTP client for auction sources.

Everything a considerate scraper owes a site, in one place so every Source inherits it:
an honest identifying User-Agent, a minimum gap between requests, retry-with-backoff on
transient failures, and an on-disk cache so a re-run (or a crash-resume) never re-hits a
page it already fetched. The cache is also what makes runs idempotent and cheap to
iterate on while building.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Optional

import httpx

from . import config


def _cache_path(url: str, *, kind: str = "raw"):
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # raw keeps the bare-URL key so an existing warm cache stays valid
    seed = url if kind == "raw" else f"{kind}:{url}"
    key = hashlib.sha256(seed.encode()).hexdigest()[:24]
    return config.CACHE_DIR / (f"{key}.html" if kind == "raw" else f"{key}.json")


def _meter(url: str) -> None:
    """One rendered page = one Firecrawl credit. Metered so a big directory sweep shows
    up in the ledger rather than as a silent card charge."""
    try:
        from .. import spend
        spend.record("firecrawl", purpose="auction_render", units_in=1,
                     cost_gbp=config.RENDER_COST_GBP, detail={"url": url})
    except Exception:
        pass                                    # metering never fails a fetch


class PoliteClient:
    """One min-interval-throttled, cached, retrying HTTP client. Not thread-safe by
    design — a single worker is the rate-limit discipline (same reasoning as the
    pipeline's single JobRunner)."""

    def __init__(self, *, rate_limit: Optional[float] = None,
                 user_agent: Optional[str] = None, use_cache: bool = True,
                 client: Optional[httpx.Client] = None):
        self.rate_limit = config.RATE_LIMIT_SECONDS if rate_limit is None else rate_limit
        self.user_agent = user_agent or config.USER_AGENT
        self.use_cache = use_cache
        self._last = 0.0
        self._own = client is None
        self._client = client or httpx.Client(
            timeout=config.TIMEOUT_SECONDS, follow_redirects=True,
            headers={"User-Agent": self.user_agent})

    def _throttle(self) -> None:
        wait = self.rate_limit - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def get(self, url: str, *, cache: Optional[bool] = None) -> Optional[str]:
        """Return the response text, or None on a hard failure. Served from the on-disk
        cache when present and fresh — so no throttle, no network, no re-hit."""
        use_cache = self.use_cache if cache is None else cache
        path = _cache_path(url)
        if use_cache and path.exists() and \
                (time.time() - path.stat().st_mtime) < config.CACHE_TTL_SECONDS:
            return path.read_text(encoding="utf-8", errors="replace")

        last_err = None
        for attempt in range(config.MAX_RETRIES + 1):
            self._throttle()
            try:
                r = self._client.get(url)
                if r.status_code == 200:
                    if use_cache:
                        path.write_text(r.text, encoding="utf-8")
                    return r.text
                # 429 / 5xx are transient — back off and retry; 4xx (else) is terminal
                if r.status_code not in (429, 500, 502, 503, 504):
                    return None
                last_err = f"HTTP {r.status_code}"
            except httpx.HTTPError as e:
                last_err = str(e)
            time.sleep(min(2 ** attempt, 30))   # exponential backoff, capped
        print(f"auction fetch gave up on {url}: {last_err}", flush=True)
        return None

    def get_rendered(self, url: str, *, cache: Optional[bool] = None) -> Optional[dict]:
        """Fetch a page through Firecrawl's browser renderer; returns
        `{"markdown": str, "links": [...], "metadata": {...}}` or None.

        Needed because plain HTTP cannot reach most of these platforms at all: the three
        ATG sites (the-saleroom / BidSpotter / i-bidder) answer every direct request with
        an AWS WAF challenge — HTTP 202 and an empty body, robots.txt included — and
        LiveAuctioneers / Invaluable render their directories client-side. Firecrawl is
        already the pipeline's renderer for exactly this class of site.

        Cached to disk like `get()`, so re-runs and crash-resumes cost no credits; the
        cache is what makes iterating on a parser free.
        """
        use_cache = self.use_cache if cache is None else cache
        path = _cache_path(url, kind="render")
        if use_cache and path.exists() and \
                (time.time() - path.stat().st_mtime) < config.CACHE_TTL_SECONDS:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                pass                                   # corrupt cache entry: refetch

        api_key = config._oc.FIRECRAWL_API_KEY
        if not api_key:
            print(f"auction render needs FIRECRAWL_API_KEY, skipping {url}", flush=True)
            return None

        last_err = None
        for attempt in range(config.MAX_RETRIES + 1):
            self._throttle()
            try:
                r = self._client.post(
                    "https://api.firecrawl.dev/v1/scrape",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"url": url, "formats": ["markdown", "links"],
                          "onlyMainContent": False},
                    timeout=config.RENDER_TIMEOUT_SECONDS)
                if r.status_code == 200:
                    data = (r.json() or {}).get("data") or {}
                    out = {"markdown": data.get("markdown") or "",
                           "links": data.get("links") or [],
                           "metadata": data.get("metadata") or {}}
                    _meter(url)
                    if use_cache:
                        path.write_text(json.dumps(out), encoding="utf-8")
                    return out
                if r.status_code not in (429, 500, 502, 503, 504):
                    return None
                last_err = f"HTTP {r.status_code}"
            except (httpx.HTTPError, ValueError) as e:
                last_err = str(e)
            time.sleep(min(2 ** attempt, 30))
        print(f"auction render gave up on {url}: {last_err}", flush=True)
        return None

    def close(self) -> None:
        if self._own:
            self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
