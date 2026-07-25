"""Phase D — enrich_company.

Website discovery and the LLM 'signal' are INLINE work (the loop agent supplies
them on Max, mirroring the LLMProvider pattern); scraping, contact-email
extraction and MillionVerifier verification are deterministic code. A lead we
can't verifiably reach is DISCARDED (never left contactable).
"""
from __future__ import annotations
import abc
import html as _html
import json
import re
from typing import Optional

import httpx

from . import audit, config, db, facts, geo, stats

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
    # Trade directories, accreditation schemes and booking platforms. Their contact
    # pages are scraped as if they were the prospect's own: three roofers/electricians
    # in the live queue were addressed to info@checkatrade.com, one salon to
    # hello@fresha.com and one electrician to info@trustmark.org.uk.
    "checkatrade.com", "trustmark.org.uk", "fresha.com", "mybuilder.com",
    "ratedpeople.com", "trustatrader.com", "bark.com", "which.co.uk",
    "fcsa.org.uk", "treatwell.co.uk", "booksy.com", "thebestof.co.uk",
    "freeindex.co.uk", "cylex-uk.co.uk", "scoot.co.uk", "hotfrog.co.uk",
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


def recipient_mismatch(company_name: str, email: Optional[str]) -> bool:
    """True when this address demonstrably belongs to somebody else.

    The last line of defence before a draft is written. A scrape can pick up a directory
    or trade-body address from a page (Checkatrade, TrustMark, Fresha) and it will look
    like a perfectly ordinary contact — it verifies, it is on a real domain, it is simply
    not the prospect. Only an address whose domain contradicts the company name is
    rejected; an unjudgeable name (all generic words) passes, because refusing what we
    cannot assess would discard most of the list.
    """
    if not email or "@" not in email:
        return False
    domain = email.rpartition("@")[2].lower()
    # A directory or booking platform is never the prospect, whatever its name looks
    # like next to theirs. Deterministic, so it carries the cases the name heuristic
    # cannot judge — an initialism like "CGH Electrical" has nothing to match on.
    if any(d in domain for d in SKIP_DOMAINS):
        return True
    return name_matches_domain(company_name, domain) is False


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


# Email verification now runs through a provider CHAIN (MillionVerifier -> Reoon ->
# ZeroBounce, config.VERIFIER_CHAIN) so one provider running dry fails over instead of
# stranding leads — the fix the MillionVerifier incident earned. verify_email +
# TRANSIENT_RESULTS live in verify.py; re-exported here so every existing call site
# (enrich, decisionmakers, auctions, tests) keeps working unchanged.
from .verify import verify_email, TRANSIENT_RESULTS  # noqa: E402,F401

RISKY_RESULTS = ("catch_all",)  # deliverable but unconfirmable (M365/Workspace catch-all)
# A verifier failing to ANSWER (all providers out/erroring) is a non-answer, never a
# verdict: on 2026-07-20 MillionVerifier went negative, every check returned 'error', and
# the pipeline discarded 178 good leads in a day. A transient result defers a lead; only a
# real 'invalid' discards it.
# consecutive transient results that mean "verification is down, stop paying to scrape"
VERIFIER_DOWN_AFTER = 3


def contact_tier(result: str, *, accept_catch_all: Optional[bool] = None) -> Optional[str]:
    """Map a MillionVerifier result to a contact tier:
      'verified' = 'ok' (confirmed deliverable) — full-confidence contact
      'risky'    = catch-all (deliverable but unconfirmable), kept only if accepted
      None       = invalid/unknown/no_email/error — not contactable, discard
    """
    if result == "ok":
        return "verified"
    accept = config.ACCEPT_CATCH_ALL if accept_catch_all is None else accept_catch_all
    if result in RISKY_RESULTS and accept:
        return "risky"
    return None


_SCHEME_RE = re.compile(r"^\s*(?:https?:)?/*", re.I)


def normalise_domain(url: Optional[str]) -> Optional[str]:
    """'https://WWW.Acme.co.uk/contact?x=1' -> 'acme.co.uk'.

    THE canonical rule, deliberately in one place: it is both the scrape's
    same-domain test and the key manual research dedupes on, and migration 0009
    backfilled with the SQL equivalent. A bare word with no dot is a typo, not a
    domain, so it returns None rather than a key that would match nothing.
    """
    if not url or not url.strip():
        return None
    host = _SCHEME_RE.sub("", url.strip()).split("/")[0].split("?")[0].split("#")[0]
    host = host.split("@")[-1].split(":")[0].lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host if host and "." in host and " " not in host else None


_domain_of = normalise_domain   # internal alias, kept for the existing call sites


_TAG_RE = re.compile(r"<(script|style)\b.*?</\1>|<[^>]+>", re.S | re.I)


def page_text(url: str, *, client: Optional[httpx.Client] = None) -> str:
    """Homepage text (tags stripped, whitespace collapsed), bounded for the LLM
    signal prompt. Best-effort: any failure returns ''."""
    if not url:
        return ""
    owns = client is None
    client = client or httpx.Client(timeout=15, follow_redirects=True,
                                    headers={"User-Agent": USER_AGENT})
    try:
        r = client.get(url.rstrip("/"))
        if r.status_code != 200:
            return ""
        text = " ".join(_TAG_RE.sub(" ", r.text).split())
        return text[:config.ENRICH_PAGE_TEXT_MAX_CHARS]
    except httpx.HTTPError:
        return ""
    finally:
        if owns:
            client.close()


# A business's own site is the best statement of where it is and who it is — it is the
# company describing itself, not a third party describing it. Three extractable things,
# all deterministic (no LLM, no cost):
_LDJSON_RE = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
_COMPANY_NO_RE = re.compile(
    r"(?:compan(?:y|ies)\s*(?:registration\s*)?(?:no|number|reg)\.?|"
    r"registered\s+in\s+England[^.]{0,60}?no\.?|reg(?:istered)?\s*(?:co|company)\s*no)"
    r"[^0-9A-Z]{0,12}((?:SC|NI|OC|SO|NC|R)?\d{6,8})", re.I)
_VAT_RE = re.compile(r"VAT\s*(?:registration\s*)?(?:no|number|reg)?\.?[^0-9A-Z]{0,10}"
                     r"((?:GB\s*)?\d[\d\s]{7,13})", re.I)
_ESTABLISHED_RE = re.compile(
    r"(?:est(?:ablished|\.)?|since|trading\s+since|founded(?:\s+in)?)\s*:?\s*(19\d{2}|20[0-2]\d)",
    re.I)


# Words that identify nobody — every business in a sector shares them, so they can never
# be what ties a domain to a company.
_GENERIC_NAME_WORDS = frozenset({
    "ltd", "limited", "llp", "plc", "the", "and", "for", "with", "company", "companies",
    "group", "holdings", "services", "service", "solutions", "trading", "trade", "uk",
    "gb", "england", "british", "national", "international", "online", "direct", "co",
    "electrical", "electric", "electricians", "electrician", "plumbing", "plumbers",
    "heating", "roofing", "builders", "building", "construction", "contractors",
    "contracting", "installations", "maintenance", "specialists", "specialist",
    "auction", "auctions", "auctioneers", "auctioneer", "valuers", "saleroom",
    "accountants", "accounting", "accountancy", "dental", "clinic", "estates", "estate",
    "properties", "property", "consultancy", "consultants", "management", "centre",
    "center", "systems", "supplies", "engineering", "engineers", "fine", "art",
})


def name_matches_domain(business_name: str, url_or_domain: str) -> Optional[bool]:
    """Does this domain plausibly belong to this business? None = cannot tell.

    A distinctive word from the name must survive in the domain. Without this the
    resolver's best guess is adopted verbatim — and then the site is scraped for a
    contact, its postcode becomes the lead's location, and its text becomes the signal.
    One wrong domain therefore poisons the recipient, the place and the pitch at once.

    Observed in the live approval queue before this existed: three roofers/electricians
    addressed to info@checkatrade.com, a Cardiff solicitor to a US title insurer, a
    dental lab to Heartland (a payments company), an auction house in Fife given a
    Surrey address, and a Leeds estate agent placed in Blackpool.
    """
    # The first label only. Stripping punctuation from the WHOLE domain glued the TLD on
    # ("candjelectricalservices.co.uk" -> "...servicescouk"), which broke every
    # whole-name comparison against a real company's own site.
    stem = re.sub(r"[^a-z0-9]", "", (normalise_domain(url_or_domain) or "").split(".")[0])
    if not stem:
        return None
    raw_tokens = [w for w in re.split(r"[^a-z0-9]+", (business_name or "").lower()) if w]
    # "C.C Electrical" and "A F Brock" split into single letters that match nothing on
    # their own. Read them the way a person does — as one initialism — so cc-electrical
    # and afbrock are recognised as those companies' own domains.
    tokens: list[str] = []
    for tok in raw_tokens:
        if len(tok) == 1 and tokens and len(tokens[-1]) <= 2 and tokens[-1].isalpha():
            tokens[-1] += tok
        else:
            tokens.append(tok)
    # 2 chars, not 4: for a great many small firms the identifying part IS a short
    # initialism — CC Electrical -> cc-electrical, AKS Electrical (Southern) ->
    # akselectrical, HG Gas -> hggls. Requiring four characters rejected their own
    # websites, because the only long words left ("Southern", "Landlord") are the ones
    # a domain drops.
    distinctive = [w for w in tokens if len(w) >= 2 and w not in _GENERIC_NAME_WORDS]
    # ONE distinctive token is enough. A name has several and a domain keeps only some,
    # so requiring all of them would reject almost every genuine site.
    if any(w in stem for w in distinctive):
        return True
    # The domain may simply BE the name run together, including a spelled-out ampersand:
    # "C & J Electrical Services" -> candjelectricalservices.co.uk. Compare the compacted
    # forms both ways so the domain need not be a perfect copy.
    low = (business_name or "").lower()
    for compact in {re.sub(r"[^a-z0-9]", "", low),
                    re.sub(r"[^a-z0-9]", "", low.replace("&", " and "))}:
        if compact and (stem in compact or compact.startswith(stem)):
            return True
    # Firms also trade under their initials: Rotherham Taylor -> rtaccountants. Treat a
    # matching acronym as unjudgeable rather than a mismatch.
    initials = "".join(t[0] for t in distinctive)
    if len(initials) >= 2 and initials in stem:
        return None
    if not distinctive:
        return None                     # nothing identifying to judge against
    return False


def _unescape(value) -> Optional[str]:
    """Decode entities and collapse whitespace. JSON-LD on real sites is routinely
    hex-encoded ('SK11&#x20;9DU'), which breaks every postcode comparison downstream."""
    if not value or not isinstance(value, str):
        return None
    return " ".join(_html.unescape(value).split()) or None


def _ld_blocks(html_text: str) -> list[dict]:
    out: list[dict] = []
    for block in _LDJSON_RE.findall(html_text or ""):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict):
                out.append(item)
                graph = item.get("@graph")
                if isinstance(graph, list):
                    out.extend(g for g in graph if isinstance(g, dict))
    return out


def site_identity(website: Optional[str], *, client: Optional[httpx.Client] = None,
                  paths: tuple = ("", "/contact", "/contact-us", "/about")) -> dict:
    """What the business says about itself on its own pages.

    Returns {postcode, locality, company_number, vat_number, established, source_url}.
    Everything is best-effort and independently optional — a site that publishes only a
    postcode still moves the location out of "unknown".

    The company number is the prize when it appears: it is a DETERMINISTIC Companies
    House match, no name similarity or co-location heuristics involved. It only turns up
    on a minority of small-business sites (roughly 1 in 6 when sampled), which is exactly
    why it is worth taking for free whenever it does.
    """
    found: dict = {"postcode": None, "locality": None, "company_number": None,
                   "vat_number": None, "established": None, "source_url": None}
    if not website:
        return found
    owns = client is None
    client = client or httpx.Client(timeout=15, follow_redirects=True,
                                    headers={"User-Agent": USER_AGENT})
    base = website.rstrip("/")
    try:
        for path in paths:
            try:
                r = client.get(base + path)
            except httpx.HTTPError:
                continue
            if r.status_code != 200:
                continue
            html_text = r.text
            # 1. schema.org — the structured, unambiguous form when a site publishes it
            for item in _ld_blocks(html_text):
                addr = item.get("address")
                if isinstance(addr, list):
                    addr = addr[0] if addr else None
                if isinstance(addr, dict):
                    # JSON-LD values are routinely hex-entity-encoded ("SK11&#x20;9DU"),
                    # which silently breaks every postcode comparison downstream
                    found["postcode"] = found["postcode"] or _unescape(addr.get("postalCode"))
                    found["locality"] = found["locality"] or _unescape(addr.get("addressLocality"))
            text = " ".join(_TAG_RE.sub(" ", html_text).split())
            # 2. the footer: postcode, company number, VAT, "established 1998"
            if not found["postcode"]:
                from . import geo
                found["postcode"] = geo.normalise_postcode(text)
            for key, pattern in (("company_number", _COMPANY_NO_RE), ("vat_number", _VAT_RE),
                                 ("established", _ESTABLISHED_RE)):
                if not found[key]:
                    m = pattern.search(text)
                    if m:
                        found[key] = " ".join(m.group(1).split())
            if not found["source_url"] and any(
                    found[k] for k in ("postcode", "company_number", "established")):
                found["source_url"] = base + path
            if found["postcode"] and found["company_number"]:
                break                        # nothing better to find; stop fetching
        return found
    finally:
        if owns:
            client.close()


def llm_signal(company_name: str, vertical: Optional[str], town: Optional[str],
               text: str, *, provider=None) -> Optional[str]:
    """LLM-written payment-behaviour signal from scraped page text — the
    personalisation fuel for playbook v1. Returns None on ANY failure (no key,
    spend cap, provider error, empty text): the caller falls back to the factual
    signal, so the pipeline never blocks on the LLM."""
    if not text:
        return None
    if provider is None:
        if not config.ANTHROPIC_API_KEY:
            return None
        from .llm import ApiProvider
        provider = ApiProvider()
    prompt = (
        "You are researching a small UK business for a personalised B2B note.\n"
        f"BUSINESS: {company_name}" + (f" — {vertical}" if vertical else "")
        + (f", {town}" if town else "") + "\n"
        f"WEBSITE TEXT (may be partial):\n{text}\n\n"
        "From the text ONLY, write 2-3 factual sentences in UK English covering: "
        "what the business does; how customers appear to pay or book (card online, "
        "phone, cash, bank transfer, third-party booking site) — say 'not stated' "
        "rather than guessing; and ONE specific hook a rep could open with about "
        "taking card payments through a branded payment page. Plain text, no "
        "markdown, no URLs, under 80 words."
    )
    from .llm import LLMUnavailable
    try:
        out = provider.complete(prompt, purpose="signal", max_words=80).text.strip()
        return " ".join(out.split())[:500] or None
    except LLMUnavailable:
        return None
    except Exception:
        return None


# The ICP-fit gate schema: one structured call does BOTH the personalisation signal
# AND the qualify/disqualify decision. payment_context is the load-bearing field —
# the ICP is businesses that bill AWAY from a fixed till (mobile/remote/invoice), for
# whom an online branded card page is NEW infra, not a fixed-till shop that already
# takes card in person.
_PAYMENT_CONTEXTS = ["invoice_remote", "fixed_till_retail", "online_ecommerce", "mixed", "unclear"]
# contexts that DISQUALIFY: a shop taking card at a till, or an existing online checkout.
_DISQUALIFYING_CONTEXTS = {"fixed_till_retail", "online_ecommerce"}
_FIT_SCHEMA = {
    "type": "object",
    "properties": {
        "icp_fit": {"type": "boolean"},
        "payment_context": {"type": "string", "enum": _PAYMENT_CONTEXTS},
        "size_band": {"type": "string", "enum": ["micro", "small", "medium", "large"]},
        "signal": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["icp_fit", "payment_context", "size_band", "signal", "confidence"],
}


def signal_and_fit(company_name: str, vertical: Optional[str], town: Optional[str],
                   text: str, *, provider=None) -> dict:
    """ICP-fit gate + personalisation signal in ONE structured Gemini call, from
    scraped page text. Returns {available, icp_fit, payment_context, size_band,
    signal, confidence}. `available` is False on no text / no Gemini / any error —
    the caller then falls back to the factual signal and admits the lead flagged
    for human review (fail-open, but the downstream review→approve gate catches it;
    the compliance gates that must fail CLOSED are check_envelope + the firewall).
    A definite not-fit / fixed-till / already-online verdict discards the lead
    cheaply, before any drafting spend."""
    unavailable = {"available": False, "icp_fit": None, "payment_context": None,
                   "size_band": None, "signal": None, "confidence": None}
    if not text:
        return unavailable
    if provider is None:
        if not config.GEMINI_PROJECT:
            return unavailable   # structured fit needs the Gemini/Vertex provider
        from .llm import get_provider
        provider = get_provider("gemini", model=config.GEMINI_FAST_MODEL)
    prompt = (
        "You qualify UK businesses for SettlePay, which builds a branded card-payment "
        "page + invoicing on a business's own domain, with automatic reconciliation. "
        "The KEY question is WHERE money changes hands.\n"
        "IDEAL FIT: small businesses that bill AWAY from a fixed counter — mobile, "
        "remote, appointment- or job-based, or invoice-based — so they take cash, "
        "bank transfer or manual invoices and an online branded card page is NEW, "
        "useful infrastructure. Examples: tradespeople (plumbers, electricians, "
        "builders), auctioneers, clinics and private practices, consultants and "
        "advisers, mobile services (mobile mechanics, mobile physio, mobile grooming), "
        "installers, surveyors.\n"
        "NOT A FIT (disqualify):\n"
        "- fixed_till_retail: a shop/salon/cafe/barber with a physical premises and a "
        "till/card machine — they ALREADY take card in person at the counter, so an "
        "online page is redundant.\n"
        "- online_ecommerce: already sells/takes card online (checkout, basket, "
        "Stripe/PayPal/Shopify/WooCommerce).\n"
        "- medium/large or enterprise-serving firms (banks, big consultancies, ~50+ staff).\n\n"
        f"BUSINESS: {company_name}" + (f" — {vertical}" if vertical else "")
        + (f", {town}" if town else "") + "\n"
        f"WEBSITE TEXT (may be partial):\n{text}\n\n"
        "From the text ONLY decide:\n"
        "- payment_context: invoice_remote (bills away from a till — the ideal) | "
        "fixed_till_retail (counter shop taking card in person) | online_ecommerce "
        "(already online) | mixed | unclear.\n"
        "- icp_fit: true ONLY if this is a small business that bills remotely/by "
        "invoice, for whom an online branded card page is NEW infrastructure.\n"
        "- size_band: micro/small/medium/large.\n"
        "- signal: 2-3 factual UK-English sentences — what they do, how customers "
        "appear to pay (invoice, bank transfer, cash, card in person), and ONE hook "
        "about taking card online via a branded page. Say 'not stated' rather than "
        "guessing. Under 80 words, no URLs.\n"
        "  In the signal, do NOT include any person's name, job title, review score, "
        "star rating, or statistic, and do NOT state a town, city or region unless the "
        "WEBSITE TEXT itself says the business is based or works there. A detail you are "
        "unsure of must be omitted, never guessed — a wrong specific is worse than none.\n"
        "- confidence: 0-1 in your icp_fit call."
    )
    from .llm import LLMUnavailable
    try:
        raw = provider.complete(prompt, purpose="icp_fit", schema=_FIT_SCHEMA).text.strip()
        data = json.loads(raw)
        sig = " ".join(str(data.get("signal") or "").split())[:500] or None
        ctx = data.get("payment_context")
        return {"available": True,
                "icp_fit": bool(data.get("icp_fit")),
                "payment_context": ctx if ctx in _PAYMENT_CONTEXTS else "unclear",
                "size_band": data.get("size_band"),
                "signal": sig,
                "confidence": float(data.get("confidence") or 0.0)}
    except (LLMUnavailable, ValueError, KeyError, TypeError):
        return unavailable
    except Exception:
        return unavailable


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

    # 1. SCRAPE FIRST — a published address is one the business wrote down itself, so a
    #    verifier credit spent on it is spent on an address we already believe exists.
    #    httpx costs nothing; only the Firecrawl fallback costs anything, and neither
    #    costs a VERIFIER credit. This deliberately runs before any guessing.
    httpx_emails = scrape_emails(website, client=http_client) if website else []
    candidates = list(httpx_emails)
    email = pick_contact_email(httpx_emails, prefer_domain=domain)
    if email:
        scrape_source = "httpx"
    elif website and config.FIRECRAWL_API_KEY:   # renders JS where free httpx found none
        fc_emails = firecrawl_scrape_emails(website)
        candidates = fc_emails
        email = pick_contact_email(fc_emails, prefer_domain=domain)
        if email:
            scrape_source = "firecrawl"

    # 2. Blind generic guessing (info@, hello@, …) burns up to len(GUESS_PREFIXES)
    #    verifier credits PER LEAD on addresses nobody has claimed exist, and buys at
    #    best a role mailbox — the weakest contact tier we send to. Off by default: the
    #    credit budget belongs to named decision-makers. Set ENRICH_GUESS_GENERICS=1 to
    #    re-enable when credits are plentiful and coverage matters more than precision.
    if not email and guess_generics and domain and config.ENRICH_GUESS_GENERICS:
        for prefix in GUESS_PREFIXES:
            guess = f"{prefix}@{domain}"
            ok, res = verifier(guess)
            if ok:
                email, verified, result = guess, True, res
                scrape_source, candidates = "guess", [guess]
                break

    if email and not verified:
        verified, result = verifier(email)

    return {"email": email, "verified": verified, "result": result,
            "scrape_source": scrape_source, "candidates": candidates}


def _facts_for(company_number: str, g: dict, *, cur) -> str:
    """The facts block to store. Callers that know the lead's context supply it in
    `g['facts']`; anything else falls back to a minimal block built from the register, so
    EVERY enrichment row carries valid constants no matter which path wrote it — a row
    without them would simply never become draftable."""
    block = g.get("facts")
    if not block:
        cur.execute("select company_name from outreach.leads where company_number=%s",
                    (company_number,))
        row = cur.fetchone()
        block = facts.build(company_name=row[0] if row else None)
    return facts.dumps(block)


def _persist(company_number: str, website: Optional[str], signal: Optional[str],
             g: dict, *, cur) -> dict:
    """The FAST, DB-only half: write enrichment + advance/discard the lead. Holds
    the connection for milliseconds, never across network I/O."""
    email, verified, result = g["email"], g["verified"], g["result"]
    # An address on somebody else's domain is not a contact for THIS lead, however well
    # it verifies. Dropped before the tier is computed, so the lead is never counted as
    # contactable on the strength of a directory's mailbox.
    if email and g.get("company_name") and recipient_mismatch(g["company_name"], email):
        g.setdefault("notes", []).append(f"rejected {email}: belongs to another company")
        email, verified, result = None, False, "recipient_mismatch"
    tier = contact_tier(result) if email else None   # 'verified' | 'risky' | None
    contactable = tier is not None
    # ICP-fit gate: a DEFINITE negative verdict (not fit, or already takes card
    # online) disqualifies the lead here — before any drafting spend. Fit unknown
    # (LLM unavailable) admits-if-contactable but flags for human review.
    fit = g.get("fit") or {}
    fit_available = bool(fit.get("available"))
    disqualified = fit_available and (
        not fit.get("icp_fit") or fit.get("payment_context") in _DISQUALIFYING_CONTEXTS)
    acceptable = contactable and not disqualified
    scraped = json.dumps({  # provenance for the dashboard + CSV export
        "source": g["scrape_source"], "emails_found": len(g["candidates"]),
        "candidates": g["candidates"][:8], "verify_result": result, "tier": tier,
        "signal_source": g.get("signal_source", "factual"),
        "icp_fit": fit.get("icp_fit"), "payment_context": fit.get("payment_context"),
        "size_band": fit.get("size_band"), "fit_confidence": fit.get("confidence"),
        "fit_source": "llm" if fit_available else "unknown",
    })
    # The verifier didn't answer. Write NOTHING and leave the lead 'discovered': the
    # enrich backlog picks up leads that have no enrichment row, so an absent row is
    # what schedules the retry. A row saying 'error' would both discard the lead AND
    # make it invisible to the backlog query — permanent loss from a temporary outage.
    deferred = bool(email) and not disqualified and result in TRANSIENT_RESULTS
    if deferred:
        audit.record(company_number, "verify_deferred", source="enrich",
                     lawful_basis=audit.LEGITIMATE_INTERESTS,
                     reason=f"verifier unavailable ({result}) for {email} — held for retry",
                     cur=cur)
        return {"company_number": company_number, "email": email, "verified": False,
                "result": result, "tier": None, "icp_fit": fit.get("icp_fit"),
                "disqualified": False, "deferred": True}

    cur.execute(
        # `domain` is the dedupe key manual research checks BEFORE spending anything,
        # so every enrichment has to write it, not just the manual path
        "insert into outreach.enrichment "
        "(company_number, website, domain, contact_email, email_verified, email_verify_result, "
        " contact_tier, signal, scraped, facts) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb) "
        "on conflict (company_number) do update set "
        "website=excluded.website, domain=excluded.domain, contact_email=excluded.contact_email, "
        "email_verified=excluded.email_verified, email_verify_result=excluded.email_verify_result, "
        "contact_tier=excluded.contact_tier, signal=excluded.signal, scraped=excluded.scraped, "
        "facts=excluded.facts",
        (company_number, website, _domain_of(website), email, (verified if email else None),
         result, tier, signal, scraped, _facts_for(company_number, g, cur=cur)),
    )
    if acceptable:
        cur.execute(
            "update outreach.leads set state='enriched', updated_at=now() "
            "where company_number=%s and state='discovered'", (company_number,))
        label = "verified" if tier == "verified" else f"risky ({result})"
        audit.record(company_number, "enriched", source="enrich",
                     lawful_basis=audit.LEGITIMATE_INTERESTS,
                     reason=f"{label} {email} via {g['scrape_source']}", cur=cur)
    else:
        cur.execute(
            "update outreach.leads set state='discarded', updated_at=now() "
            "where company_number=%s and state in ('discovered','enriched')", (company_number,))
        if disqualified:
            ctx = fit.get("payment_context")
            why = {"fixed_till_retail": "fixed-till retail (takes card in person)",
                   "online_ecommerce": "already takes card online"}.get(ctx, "not ICP fit")
            reason = f"{why} ({fit.get('size_band')}, conf {fit.get('confidence')})"
        else:
            reason = f"unverifiable contact ({result})"
        audit.record(company_number, "discarded", source="enrich",
                     lawful_basis=audit.LEGITIMATE_INTERESTS, reason=reason, cur=cur)
    return {"company_number": company_number, "email": email, "verified": verified,
            "result": result, "tier": tier, "icp_fit": fit.get("icp_fit"),
            "disqualified": disqualified, "deferred": False}


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


# Re-enrichment: leads that ALREADY have an enrichment row but were worked before the
# constants existed (or whose block is missing a location we can now resolve). Picking
# them by facts state rather than by date means the query stays correct as the block
# gains fields — a lead is stale when its constants are, not when it is old.
_REFRESH_SQL = (
    "select l.company_number, l.company_name, l.registered_address->>'locality', "
    "       l.sic_codes[1], coalesce(e.website, l.registered_address->>'website'), l.source, "
    "       l.registered_address->>'formatted', l.registered_address->>'postcode' "
    "from outreach.leads l join outreach.enrichment e using (company_number) "
    "where l.state in ('enriched','drafted') "
    "  and (e.facts is null "
    "       or e.facts->'location'->>'value' is null "
    "       or e.facts->'region' is null) "
    "order by l.updated_at limit %s")


def refresh_facts(*, limit: int = 25, cur=None) -> dict:
    """Recompute the drafting CONSTANTS for leads already enriched, and nothing else.

    Deliberately NOT `discover_and_run` over the same rows. That path re-gathers and
    re-verifies a contact, and its unverifiable branch DISCARDS the lead — so re-running
    it over a healthy backlog during a verifier outage (all three providers are currently
    dry) would delete good, already-contacted leads. Nothing here touches contact_email,
    contact_tier or lead state; the worst case is a lead whose constants are unchanged.
    """
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    http = httpx.Client(timeout=15, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    from .companies_house import CompaniesHouseClient
    ch = CompaniesHouseClient(max_requests=max(30, limit * 2)) \
        if config.COMPANIES_HOUSE_API_KEY else None
    updated = placed = unchanged = 0
    try:
        cur.execute(_REFRESH_SQL, (limit,))
        rows = cur.fetchall()
        for cn, name, town, sic, website, source, formatted, postcode in rows:
            hint = usable_vertical(stats.sic_label(sic))
            identity = site_identity(website, client=http) if website else {}
            place = geo.resolve_location(
                site_postcode=identity.get("postcode"), site_town=identity.get("locality"),
                listing_town=trading_town(town, source, formatted),
                listing_postcode=postcode,
                registered_town=town if source not in _TRADING_LOCALITY_SOURCES else None,
                registered_postcode=postcode if source not in _TRADING_LOCALITY_SOURCES else None,
                ch=ch, client=http)
            cur.execute("select contact_name from outreach.enrichment where company_number=%s",
                        (cn,))
            row = cur.fetchone()
            block = facts.build(
                company_name=name, company_name_source="companies_house",
                contact_name=row[0] if row else None,
                contact_name_source="ch_officer_verified_email" if (row and row[0]) else None,
                location=place.get("town"), location_source=place.get("source"),
                region=place.get("region"),
                region_source="postcodes_io" if place.get("region") else None,
                vertical=hint, vertical_source="sic_label" if hint else None,
                established=identity.get("established"),
                established_source="own_site" if identity.get("established") else None)
            cur.execute("update outreach.enrichment set facts=%s::jsonb where company_number=%s",
                        (facts.dumps(block), cn))
            updated += 1
            if place.get("town") or place.get("region"):
                placed += 1
            else:
                unchanged += 1
            audit.record(cn, "facts_refreshed", source="enrich",
                         lawful_basis=audit.LEGITIMATE_INTERESTS,
                         reason=facts.summarise(block)[:400], cur=cur)
        if own:
            conn.commit()
    except Exception:
        if own and conn:
            conn.rollback()
        raise
    finally:
        http.close()
        if ch is not None:
            ch.close()
        if own and conn:
            conn.close()
    return {"refreshed": updated, "placed": placed, "unplaceable": unchanged}


def discover_and_run(*, limit: int = 10, resolver=None, cur=None) -> list[dict]:
    """Automated discovery + enrich for up to `limit` not-yet-enriched corporate
    discovered leads: resolve each website via the configured resolver
    (firecrawl/brave/inline), then scrape + verify a contact (httpx -> Firecrawl
    fallback) and enrich or discard."""
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
    # one Companies House client for the batch: used only to ask whether a registered
    # office is a shared agent address, which is one cheap search per distinct postcode
    from .companies_house import CompaniesHouseClient
    ch = CompaniesHouseClient(max_requests=max(30, len(leads) * 2)) \
        if config.COMPANIES_HOUSE_API_KEY else None
    gathered: list[tuple] = []
    consecutive_verify_failures = 0
    try:
        for cn, name, town, sic, known_website, source, formatted, postcode in leads:
            # Circuit breaker. Verification is the LAST step, so a dead verifier means
            # every scrape before it was paid for and thrown away. Stop the batch
            # instead of grinding through the backlog achieving nothing.
            if consecutive_verify_failures >= VERIFIER_DOWN_AFTER:
                break
            hint = usable_vertical(stats.sic_label(sic))  # "Accountants", or None
            if known_website:   # Places already gave us the site — don't pay to re-resolve
                website = known_website
            else:
                try:
                    website = resolver.resolve(company_name=name, address=town or "", hint=hint)
                except Exception:
                    website = None
            # A search result is a GUESS. Adopting the wrong company's site poisons the
            # recipient (its contact page is scraped for an address), the location (its
            # postcode becomes theirs) and the pitch (its text becomes the signal) in one
            # go — which is how drafts ended up addressed to info@checkatrade.com.
            if website and name_matches_domain(name, website) is False:
                website = None

            # WHERE THEY ARE, best source first: what they publish about themselves, then
            # a trading listing, then a registered office proven not to be an agent's.
            # Every UK business has an address somewhere in that ladder.
            identity = site_identity(website, client=http) if website else {}
            place = geo.resolve_location(
                site_postcode=identity.get("postcode"), site_town=identity.get("locality"),
                listing_town=trading_town(town, source, formatted),
                listing_postcode=postcode,
                registered_town=town if source not in _TRADING_LOCALITY_SOURCES else None,
                registered_postcode=postcode if source not in _TRADING_LOCALITY_SOURCES else None,
                ch=ch, client=http)
            signal = factual_signal(name, hint, place.get("town"))
            g = _gather(website, http_client=http)
            if g["email"] and g["result"] in TRANSIENT_RESULTS:
                consecutive_verify_failures += 1
            elif g["result"] not in TRANSIENT_RESULTS:
                consecutive_verify_failures = 0
            g["signal_source"] = "factual"
            g["fit"] = None   # unknown → admitted flagged for review (fail-open)
            if website:  # structured ICP-fit gate + signal in one Gemini call
                fit = signal_and_fit(name, hint, place.get("town"),
                                     page_text(website, client=http))
                g["fit"] = fit
                if fit["available"]:
                    g["signal_source"] = "llm"
                    if fit["signal"]:
                        signal = fit["signal"]
            # The constants the drafter may name. contact_name is filled later by
            # decision-maker resolution; payment_method stays unknown here because the
            # main pipeline only infers a payment CATEGORY, and an inference is not a
            # fact — the auction path sets it from the auctioneer's own quoted sentence.
            g["facts"] = facts.build(
                company_name=name, company_name_source="companies_house",
                location=place.get("town"), location_source=place.get("source"),
                region=place.get("region"),
                region_source="postcodes_io" if place.get("region") else None,
                vertical=hint, vertical_source="sic_label" if hint else None,
                established=identity.get("established"),
                established_source="own_site" if identity.get("established") else None)
            g["identity"] = identity        # postcode/company number/VAT for the record
            g["company_name"] = name        # lets _persist reject another company's address
            gathered.append((cn, website, signal, g))
    finally:
        http.close()
        if ch is not None:
            ch.close()

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
    "select l.company_number, l.company_name, l.registered_address->>'locality', "
    "       l.sic_codes[1], l.registered_address->>'website', l.source, "
    "       l.registered_address->>'formatted', l.registered_address->>'postcode' "
    "from outreach.leads l where l.subscriber_class='corporate' and l.state='discovered' "
    "and not exists (select 1 from outreach.enrichment e where e.company_number=l.company_number) "
    "order by l.company_name limit %s")

# Sources whose locality is the business's TRADING town (a Google/Places listing), not
# a registered-office address. A Ltd's registered office is routinely its accountant or a
# formation agent — asserting it as "based in X" is how a draft ends up placing a
# Cheshire auctioneer in Westbury-on-Severn. Only these may seed a location claim.
_TRADING_LOCALITY_SOURCES = frozenset({"places"})


def usable_vertical(vertical: Optional[str]) -> Optional[str]:
    """A human vertical label fit to put in a signal, or None. 'Unknown' and a bare
    unmapped SIC code (stats.sic_label falls through to the raw digits) are NOT
    descriptors — a signal reading '— 47190 in ...' is the SIC leak we saw in prod."""
    if not vertical or vertical == "Unknown" or vertical.isdigit():
        return None
    return vertical


def trading_town(town: Optional[str], source: Optional[str],
                 formatted: Optional[str] = None) -> Optional[str]:
    """The locality only when it is a trading address (a Places listing), never a
    registered office — so no draft asserts an accountant's town as where they operate.

    Older Places rows kept the town only inside the formatted address string, so it is
    parsed back out when the structured field is absent; without that the lead has no
    admissible location and its draft can name no town at all.
    """
    if source not in _TRADING_LOCALITY_SOURCES:
        return None
    if town:
        return town
    from . import places          # local: places imports normalise_domain from here
    return places.locality_of(formatted)


def factual_signal(name: str, vertical: Optional[str], town: Optional[str]) -> str:
    """The deterministic fallback signal, built only from facts we can stand behind."""
    return name + (f" — {vertical}" if vertical else "") + (f" in {town}" if town else "")


if __name__ == "__main__":
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    for r in discover_and_run(limit=n):
        print(r)
