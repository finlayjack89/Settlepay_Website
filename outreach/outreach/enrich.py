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
        " contact_tier, signal, scraped) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) "
        "on conflict (company_number) do update set "
        "website=excluded.website, domain=excluded.domain, contact_email=excluded.contact_email, "
        "email_verified=excluded.email_verified, email_verify_result=excluded.email_verify_result, "
        "contact_tier=excluded.contact_tier, signal=excluded.signal, scraped=excluded.scraped",
        (company_number, website, _domain_of(website), email, (verified if email else None),
         result, tier, signal, scraped),
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
    consecutive_verify_failures = 0
    try:
        for cn, name, town, sic, known_website in leads:
            # Circuit breaker. Verification is the LAST step, so a dead verifier means
            # every scrape before it was paid for and thrown away. Stop the batch
            # instead of grinding through the backlog achieving nothing.
            if consecutive_verify_failures >= VERIFIER_DOWN_AFTER:
                break
            vertical = stats.sic_label(sic)  # e.g. "Accountants", "Estate agents"
            hint = vertical if vertical and vertical != "Unknown" else None
            if known_website:   # Places already gave us the site — don't pay to re-resolve
                website = known_website
            else:
                try:
                    website = resolver.resolve(company_name=name, address=town or "", hint=hint)
                except Exception:
                    website = None
            signal = name + (f" — {vertical}" if hint else "") + (f" in {town}" if town else "")
            g = _gather(website, http_client=http)
            if g["email"] and g["result"] in TRANSIENT_RESULTS:
                consecutive_verify_failures += 1
            elif g["result"] not in TRANSIENT_RESULTS:
                consecutive_verify_failures = 0
            g["signal_source"] = "factual"
            g["fit"] = None   # unknown → admitted flagged for review (fail-open)
            if website:  # structured ICP-fit gate + signal in one Gemini call
                fit = signal_and_fit(name, hint, town, page_text(website, client=http))
                g["fit"] = fit
                if fit["available"]:
                    g["signal_source"] = "llm"
                    if fit["signal"]:
                        signal = fit["signal"]
            gathered.append((cn, website, signal, g))
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
    "select l.company_number, l.company_name, l.registered_address->>'locality', l.sic_codes[1], "
    "       l.registered_address->>'website' "
    "from outreach.leads l where l.subscriber_class='corporate' and l.state='discovered' "
    "and not exists (select 1 from outreach.enrichment e where e.company_number=l.company_number) "
    "order by l.company_name limit %s")


if __name__ == "__main__":
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    for r in discover_and_run(limit=n):
        print(r)
