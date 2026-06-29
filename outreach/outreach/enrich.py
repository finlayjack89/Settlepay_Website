"""Phase D — enrich_company.

Website discovery and the LLM 'signal' are INLINE work (the loop agent supplies
them on Max, mirroring the LLMProvider pattern); scraping, contact-email
extraction and MillionVerifier verification are deterministic code. A lead we
can't verifiably reach is DISCARDED (never left contactable).
"""
from __future__ import annotations
import abc
import json
import re
from typing import Optional

import httpx

from . import audit, config, db, stats

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
GENERIC_PREFIXES = ("info", "contact", "enquiries", "enquiry", "hello", "sales", "admin", "office", "mail")
# generic mailboxes to guess-and-verify on a company's own domain before scraping
GUESS_PREFIXES = ("info", "enquiries", "hello", "contact")
# free-mail / third-party domains a scraped address may belong to (font authors,
# theme devs, registries) — never a valid cold-B2B contact for the company itself
FREEMAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "hotmail.co.uk",
    "yahoo.com", "yahoo.co.uk", "ymail.com", "icloud.com", "me.com", "aol.com",
    "live.com", "live.co.uk", "msn.com", "mail.com", "gmx.com", "protonmail.com",
    "proton.me", "lursoft.lv", "sentry.io", "wix.com", "squarespace.com",
})
JUNK_SUBSTR = ("example.com", "sentry", "@2x", ".png", ".jpg", ".gif", "wixpress",
               "godaddy", "domain.com", "yourdomain", "email@", "sentry.io")
SCRAPE_PATHS = ("", "/contact", "/contact-us", "/about", "/about-us")
USER_AGENT = "SettlePayOutreach/0.1 (+https://settlepay.uk; contact info@settlepay.uk)"
# directories / portals / socials to skip when resolving a company's OWN website
SKIP_DOMAINS = (
    "rightmove.co.uk", "zoopla.co.uk", "onthemarket.com", "primelocation.com",
    "yell.com", "thomsonlocal.com", "trustpilot.com", "yelp.", "facebook.com",
    "linkedin.com", "instagram.com", "twitter.com", "x.com", "gov.uk",
    "companieshouse", "company-information.service.gov.uk", "find-and-update",
    "endole.co.uk", "checkcompany", "opencorporates.com", "192.com",
    # property / business directories + ombudsman + data aggregators (not own sites)
    "tpos.co.uk", "allagents.co.uk", "getagent.co.uk", "netanagent.co.uk",
    "home.co.uk", "cylex", "centralindex", "opendi", "estateagentdb",
    "estate-agents.directory", "indieyork", "solicitor.info", "wheree.com",
    "rocketreach", "zoominfo", "brightdata", "the-property-ombudsman",
    "housesimple", "nethouseprices", "globrix",
    # company registries / data aggregators (not a company's own site)
    "lursoft.lv", "company-information", "datanyze", "dnb.com", "creditsafe",
    "bizdb", "companycheck", "ukbusinessdirectory", "freeindex",
)


# ---- website discovery (pluggable; inline default, tavily stub for later) ----
class WebsiteResolver(abc.ABC):
    @abc.abstractmethod
    def resolve(self, *, company_name: str, address: Optional[str] = None,
                hint: Optional[str] = None) -> Optional[str]:
        ...


class InlineWebsiteResolver(WebsiteResolver):
    """Default: the loop agent (Max) finds each URL via its own search tools and
    pre-fills a {company_name|company_number: url} mapping it passes in."""

    def __init__(self, mapping: Optional[dict] = None):
        self._mapping = mapping or {}

    def resolve(self, *, company_name, address=None, hint=None):
        return self._mapping.get(company_name)


class FirecrawlWebsiteResolver(WebsiteResolver):
    """Runtime discovery via Firecrawl /search (free tier: 1,000 credits/mo, NO
    card; search = 2 credits/10 results). Needs FIRECRAWL_API_KEY. Per-run capped."""

    ENDPOINT = "https://api.firecrawl.dev/v1/search"

    def __init__(self, api_key: Optional[str] = None, *, max_requests: Optional[int] = None, client=None):
        self.api_key = api_key or config.FIRECRAWL_API_KEY
        self.max_requests = max_requests or config.SEARCH_MAX_REQUESTS_PER_RUN
        self.count = 0
        self._client = client

    def resolve(self, *, company_name, address=None, hint=None):
        if not self.api_key:
            raise RuntimeError("FIRECRAWL_API_KEY not set")
        if self.count >= self.max_requests:
            raise RuntimeError(f"search per-run cap reached ({self.max_requests})")
        client = self._client or httpx.Client(timeout=30)
        query = " ".join(filter(None, [company_name, address, hint]))
        try:
            self.count += 1
            r = client.post(self.ENDPOINT,
                            headers={"Authorization": f"Bearer {self.api_key}"},
                            json={"query": query, "limit": 5})
            r.raise_for_status()
            return _first_company_url(r.json().get("data", []))
        finally:
            if self._client is None:
                client.close()


class BraveWebsiteResolver(WebsiteResolver):
    """Alternative discovery via the Brave Search API 'Search Plan' ($5/1k, ~1,000
    free credits/mo, card required). Needs BRAVE_SEARCH_API_KEY. A result is used
    transiently to resolve the company URL — Brave result SETS are never cached."""

    ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: Optional[str] = None, *, max_requests: Optional[int] = None, client=None):
        self.api_key = api_key or config.BRAVE_SEARCH_API_KEY
        self.max_requests = max_requests or config.SEARCH_MAX_REQUESTS_PER_RUN
        self.count = 0
        self._client = client

    def resolve(self, *, company_name, address=None, hint=None):
        if not self.api_key:
            raise RuntimeError("BRAVE_SEARCH_API_KEY not set")
        if self.count >= self.max_requests:
            raise RuntimeError(f"search per-run cap reached ({self.max_requests})")
        client = self._client or httpx.Client(timeout=30)
        query = " ".join(filter(None, [company_name, address, hint]))
        try:
            self.count += 1
            r = client.get(self.ENDPOINT,
                           headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"},
                           params={"q": query, "count": 5})
            r.raise_for_status()
            return _first_company_url(r.json().get("web", {}).get("results", []))
        finally:
            if self._client is None:
                client.close()


def _first_company_url(results: list[dict]) -> Optional[str]:
    """First result that looks like the company's OWN site (skip portals/directories).
    Returns None if every result is a portal/directory — better to find no site
    than to scrape a portal that can't yield the company's own-domain email."""
    for res in results:
        url = res.get("url") or ""
        if url and not any(b in url for b in SKIP_DOMAINS):
            return url
    return None


def get_website_resolver(name: Optional[str] = None, **kwargs) -> WebsiteResolver:
    name = name or config.WEBSITE_RESOLVER
    if name == "inline":
        return InlineWebsiteResolver(**kwargs)
    if name == "firecrawl":
        return FirecrawlWebsiteResolver(**kwargs)
    if name == "brave":
        return BraveWebsiteResolver(**kwargs)
    raise ValueError(f"unknown website resolver: {name!r}")


# ---- deterministic scrape / pick / verify ----
def scrape_emails(url: str, *, client: Optional[httpx.Client] = None) -> list[str]:
    owns = client is None
    client = client or httpx.Client(timeout=15, follow_redirects=True,
                                    headers={"User-Agent": USER_AGENT})
    found: list[str] = []
    try:
        base = url.rstrip("/")
        for p in SCRAPE_PATHS:
            try:
                r = client.get(base + p)
            except httpx.HTTPError:
                continue
            if r.status_code != 200:
                continue
            for m in EMAIL_RE.findall(r.text):
                e = m.lower()
                if not any(j in e for j in JUNK_SUBSTR) and e not in found:
                    found.append(e)
        return found
    finally:
        if owns:
            client.close()


def firecrawl_scrape_emails(url: str, *, api_key: Optional[str] = None, client=None,
                            paths=("", "/contact", "/contact-us")) -> list[str]:
    """Fallback scraper for sites plain httpx can't crack (JS-rendered / blocked):
    Firecrawl /v1/scrape renders the page to markdown, from which we regex emails.
    No-op (returns []) without FIRECRAWL_API_KEY. Stops at the first page that
    yields an email, to spend the fewest credits."""
    api_key = api_key or config.FIRECRAWL_API_KEY
    if not api_key or not url:
        return []
    owns = client is None
    client = client or httpx.Client(timeout=60)
    found: list[str] = []
    try:
        base = url.rstrip("/")
        for p in paths:
            try:
                r = client.post(
                    "https://api.firecrawl.dev/v1/scrape",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"url": base + p, "formats": ["markdown"], "onlyMainContent": False},
                )
            except httpx.HTTPError:
                continue
            if r.status_code != 200:
                continue
            data = (r.json() or {}).get("data", {}) or {}
            text = f"{data.get('markdown') or ''} {data.get('metadata') or ''}"
            for m in EMAIL_RE.findall(text):
                e = m.lower()
                if not any(j in e for j in JUNK_SUBSTR) and e not in found:
                    found.append(e)
            if found:
                break
        return found
    finally:
        if owns:
            client.close()


def pick_contact_email(emails: list[str], *, prefer_domain: Optional[str] = None) -> Optional[str]:
    """Pick the best cold-B2B contact: a generic mailbox (info@/contact@…) on the
    company's OWN domain. Free-mail / third-party addresses are rejected outright
    (a page often leaks a font author's gmail or a registry address), and when the
    company's domain is known we accept ONLY that domain — better no contact than a
    wrong one. Returns None if nothing qualifies."""
    if not emails:
        return None
    pool = [e for e in emails if e.partition("@")[2].lower() not in FREEMAIL_DOMAINS]
    if prefer_domain:
        pd = prefer_domain.lower()
        pool = [e for e in pool if pd in e.partition("@")[2].lower()]
    if not pool:
        return None

    def score(e: str) -> tuple:
        local = e.partition("@")[0]
        generic = any(local == g or local.startswith(g) for g in GENERIC_PREFIXES)
        return (0 if generic else 1, e)

    return sorted(pool, key=score)[0]


def verify_email(email: str, *, api_key: Optional[str] = None,
                 client: Optional[httpx.Client] = None, retries: int = 1) -> tuple[bool, str]:
    """MillionVerifier single-email check -> (verified, result_string).
    Verified only when result == 'ok' (conservative: catch_all/unknown are not).
    A transient HTTP/parse failure is retried once, then returns (False,
    'verify_error') rather than raising — one slow verify must never abort a batch."""
    api_key = api_key or config.MILLIONVERIFIER_API_KEY
    owns = client is None
    client = client or httpx.Client(timeout=25)
    try:
        for attempt in range(retries + 1):
            try:
                r = client.get("https://api.millionverifier.com/api/v3/",
                               params={"api": api_key, "email": email})
                data = r.json()
                result = str(data.get("result", "error"))
                return (result == "ok", result)
            except (httpx.HTTPError, ValueError):
                if attempt >= retries:
                    return (False, "verify_error")
        return (False, "verify_error")
    finally:
        if owns:
            client.close()


def _domain_of(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    return re.sub(r"^https?://(www\.)?", "", url).split("/")[0].lower() or None


def _gather(website: Optional[str], *, http_client: Optional[httpx.Client] = None,
            verifier=None, guess_generics: bool = True) -> dict:
    """The SLOW, networked half of enrichment (guess/scrape + verify), with NO
    database handle held. Kept separate so a long Firecrawl/HTTP call never sits
    inside an open DB transaction (the pooler drops idle connections)."""
    verifier = verifier or verify_email
    domain = _domain_of(website)
    scrape_source = None
    candidates: list[str] = []
    email = None
    verified, result = False, "no_email"

    # 1. cheap path: guess a generic mailbox on the company's OWN domain and verify
    #    it directly. Recovers contact-form-only sites and avoids a paid scrape when
    #    info@ is deliverable. Stops at the first verified address.
    if guess_generics and domain:
        for prefix in GUESS_PREFIXES:
            guess = f"{prefix}@{domain}"
            ok, res = verifier(guess)
            if ok:
                email, verified, result, scrape_source, candidates = guess, True, res, "guess", [guess]
                break

    # 2. fall back to scraping the site for a published address
    if not email:
        httpx_emails = scrape_emails(website, client=http_client) if website else []
        candidates = list(httpx_emails)
        email = pick_contact_email(httpx_emails, prefer_domain=domain)
        if email:
            scrape_source = "httpx"
        # Firecrawl renders JS / extracts where free httpx found nothing
        elif website and config.FIRECRAWL_API_KEY:
            fc_emails = firecrawl_scrape_emails(website)
            candidates = fc_emails
            email = pick_contact_email(fc_emails, prefer_domain=domain)
            if email:
                scrape_source = "firecrawl"
        verified, result = verifier(email) if email else (False, "no_email")

    return {"email": email, "verified": verified, "result": result,
            "scrape_source": scrape_source, "candidates": candidates}


def _persist(company_number: str, website: Optional[str], signal: Optional[str],
             g: dict, *, cur) -> dict:
    """The FAST, DB-only half: write enrichment + advance/discard the lead. Holds
    the connection for milliseconds, never across network I/O."""
    email, verified, result = g["email"], g["verified"], g["result"]
    scraped = json.dumps({  # provenance for the dashboard
        "source": g["scrape_source"], "emails_found": len(g["candidates"]),
        "candidates": g["candidates"][:8], "verify_result": result,
    })
    cur.execute(
        "insert into outreach.enrichment "
        "(company_number, website, contact_email, email_verified, email_verify_result, signal, scraped) "
        "values (%s,%s,%s,%s,%s,%s,%s::jsonb) "
        "on conflict (company_number) do update set "
        "website=excluded.website, contact_email=excluded.contact_email, "
        "email_verified=excluded.email_verified, email_verify_result=excluded.email_verify_result, "
        "signal=excluded.signal, scraped=excluded.scraped",
        (company_number, website, email, (verified if email else None), result, signal, scraped),
    )
    if verified:
        cur.execute(
            "update outreach.leads set state='enriched', updated_at=now() "
            "where company_number=%s and state='discovered'", (company_number,))
        audit.record(company_number, "enriched", source="enrich",
                     lawful_basis=audit.LEGITIMATE_INTERESTS,
                     reason=f"verified {email} ({result}) via {g['scrape_source']}", cur=cur)
    else:
        cur.execute(
            "update outreach.leads set state='discarded', updated_at=now() "
            "where company_number=%s and state in ('discovered','enriched')", (company_number,))
        audit.record(company_number, "discarded", source="enrich",
                     lawful_basis=audit.LEGITIMATE_INTERESTS,
                     reason=f"unverifiable contact ({result})", cur=cur)
    return {"company_number": company_number, "email": email, "verified": verified, "result": result}


def enrich_one(company_number: str, website: Optional[str], signal: Optional[str], *,
               cur, http_client: Optional[httpx.Client] = None, verifier=None,
               guess_generics: bool = True) -> dict:
    """Guess/scrape + verify a contact email for `website`, store enrichment, and
    advance the lead to 'enriched' (verified) or 'discarded' (unverifiable)."""
    g = _gather(website, http_client=http_client, verifier=verifier, guess_generics=guess_generics)
    return _persist(company_number, website, signal, g, cur=cur)


def run(items: list[dict], *, cur=None) -> list[dict]:
    """items: [{company_number, website, signal}] supplied by the inline resolver
    + provider (the loop agent on Max)."""
    own = cur is None
    conn = None
    if own:
        conn = db.connect()
        cur = conn.cursor()
    http = httpx.Client(timeout=15, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    results = []
    try:
        for it in items:
            results.append(enrich_one(it["company_number"], it.get("website"), it.get("signal"),
                                      cur=cur, http_client=http))
        if own:
            conn.commit()
        return results
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        http.close()
        if own and conn is not None:
            conn.close()


def discover_and_run(*, limit: int = 10, resolver=None, cur=None) -> list[dict]:
    """Automated discovery + enrich for up to `limit` not-yet-enriched corporate
    discovered leads: resolve each website via the configured resolver
    (firecrawl/brave/inline), then scrape + verify a contact (httpx -> Firecrawl
    fallback) and enrich or discard. Signal is a factual placeholder for now
    (a real LLM signal arrives with the api provider — deferred)."""
    resolver = resolver or get_website_resolver()
    own = cur is None

    # phase 1 — pick the backlog (short DB read)
    if own:
        conn = db.connect(); c = conn.cursor()
        try:
            c.execute(_BACKLOG_SQL, (limit,)); leads = c.fetchall()
        finally:
            conn.close()
    else:
        cur.execute(_BACKLOG_SQL, (limit,)); leads = cur.fetchall()

    # phase 2 — slow networked work (resolve + scrape + verify), NO DB connection held
    http = httpx.Client(timeout=15, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    gathered: list[tuple] = []
    try:
        for cn, name, town, sic in leads:
            vertical = stats.sic_label(sic)  # e.g. "Accountants", "Estate agents"
            hint = vertical if vertical and vertical != "Unknown" else None
            try:
                website = resolver.resolve(company_name=name, address=town or "", hint=hint)
            except Exception:
                website = None
            signal = name + (f" — {vertical}" if hint else "") + (f" in {town}" if town else "")
            gathered.append((cn, website, signal, _gather(website, http_client=http)))
    finally:
        http.close()

    # phase 3 — fast DB writes (connection open only for the persists)
    if own:
        conn = db.connect(); c = conn.cursor()
        try:
            results = [_persist(cn, w, sig, g, cur=c) for cn, w, sig, g in gathered]
            conn.commit()
            return results
        except Exception:
            conn.rollback(); raise
        finally:
            conn.close()
    return [_persist(cn, w, sig, g, cur=cur) for cn, w, sig, g in gathered]


_BACKLOG_SQL = (
    "select l.company_number, l.company_name, l.registered_address->>'locality', l.sic_codes[1] "
    "from outreach.leads l where l.subscriber_class='corporate' and l.state='discovered' "
    "and not exists (select 1 from outreach.enrichment e where e.company_number=l.company_number) "
    "order by l.company_name limit %s")


if __name__ == "__main__":
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    for r in discover_and_run(limit=n):
        print(r)
