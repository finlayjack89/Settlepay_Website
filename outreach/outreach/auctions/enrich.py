"""Enrichment — turn an `AuctionLead` into an `EnrichedLead`, REUSING the outreach
pipeline's primitives rather than re-implementing them.

Every hard part here is an existing, tested function:
  * website discovery          -> outreach.enrich.get_website_resolver (Firecrawl)
  * page text + email scrape    -> outreach.enrich.page_text / scrape_emails / verify_email
  * ICP-fit + personalisation   -> outreach.enrich.signal_and_fit (Gemini)
  * corporate PECR gate         -> outreach.crossref.match_company (Companies House)
  * directors                   -> CompaniesHouseClient.get_officers
  * named-email inference        -> outreach.decisionmakers.parse_name / email_permutations
Only the payment-signal extraction (payment.py) and the assembly are new. This keeps the
compliance behaviour (no phones, verify-before-claim, corporate-only) identical to the
live pipeline by construction.

A verifier outage (MillionVerifier out of credits) DEFERS the email step with a note —
it never guesses and never records a non-answer as "no email", the same discipline the
pipeline uses.
"""
from __future__ import annotations

from typing import Optional

import httpx

from .. import crossref, decisionmakers
from .. import enrich as _enrich
from ..companies_house import CompaniesHouseClient
from ..firewall import SubscriberClass
from . import config, payment
from .models import AuctionLead, EnrichedLead

_UA = {"User-Agent": config.USER_AGENT}

# The auction platforms themselves — a search often returns the platform's OWN directory
# page for the auctioneer, which is NOT their own website. Rejecting these also stops
# dedupe collapsing every unresolved lead onto a shared platform domain.
_PLATFORM_DOMAINS = ("easyliveauction.com", "the-saleroom.com", "saleroom.com",
                     "bidspotter.co.uk", "bidspotter.com", "i-bidder.com", "the-auctioncollective.com")


def _resolve_website(raw: AuctionLead, resolver) -> Optional[str]:
    if raw.own_website:
        return raw.own_website
    if resolver is None:
        return None
    hint = "auctioneer " + (raw.categories[0] if raw.categories else "auction house")
    try:
        url = resolver.resolve(company_name=raw.business_name,
                               address=raw.postcode or raw.location or "", hint=hint)
    except Exception:
        return None
    if url and any(p in url.lower() for p in _PLATFORM_DOMAINS):
        return None                     # a platform directory page is not their own site
    return url


def _payment_scan(website: str, http: httpx.Client) -> dict:
    """Fetch the pages where 'how to pay' lives and run the payment detector over the
    combined text. Stops early once a manual signal is found (fewest fetches)."""
    combined, best = "", {"methods": [], "manual": False, "online": False, "quote": None}
    base = website.rstrip("/")
    for path in payment.PAYMENT_PATHS:
        try:
            r = http.get(base + path)
        except httpx.HTTPError:
            continue
        if r.status_code != 200:
            continue
        text = " ".join(_enrich._TAG_RE.sub(" ", r.text).split())   # strip tags, collapse ws
        combined += " " + text
        found = payment.detect(combined)
        if found["methods"]:
            best = found
        if found["manual"]:
            break
    return best


def _decision_maker(company_number: Optional[str], domain: Optional[str],
                    ch: Optional[CompaniesHouseClient], verifier) -> dict:
    """Directors (names only), then try to CONFIRM one named work email. Never a guess:
    only a MillionVerifier 'ok' is adopted. Returns names + best email + confidence +
    a note if the verifier was unavailable."""
    out = {"directors": [], "name": None, "email": None, "confidence": 0.0, "note": None}
    if not company_number or ch is None:
        return out
    try:
        officers = ch.get_officers(company_number)
    except Exception as e:
        out["note"] = f"officers lookup failed: {str(e)[:60]}"
        return out
    for o in officers:
        if o.get("resigned_on") or (o.get("officer_role") or "").lower() not in \
                decisionmakers._DECISION_ROLES:
            continue
        nm = o.get("name")
        if nm:
            out["directors"].append(nm)

    if not domain or not out["directors"]:
        return out
    checked = 0
    for nm in out["directors"]:
        parsed = decisionmakers.parse_name(nm)
        if not parsed:
            continue
        for addr in decisionmakers.email_permutations(*parsed, domain):
            if checked >= config._oc.DM_MAX_VERIFY_PER_LEAD:
                return out
            ok, res = verifier(addr)
            checked += 1
            if res in _enrich.TRANSIENT_RESULTS:
                out["note"] = f"email verifier unavailable ({res}) — not attempted"
                return out
            if ok:
                out.update({"name": nm, "email": addr, "confidence": 0.9})
                return out
    return out


def _generic_email(domain: Optional[str], verifier) -> tuple[Optional[str], float]:
    """A verified generic mailbox (info@/enquiries@…) as the fallback contact. Verified,
    never guessed."""
    if not domain:
        return None, 0.0
    for prefix in _enrich.GUESS_PREFIXES:
        addr = f"{prefix}@{domain}"
        ok, res = verifier(addr)
        if res in _enrich.TRANSIENT_RESULTS:
            return None, 0.0
        if ok:
            return addr, 0.7
    return None, 0.0


def enrich_lead(raw: AuctionLead, *, http: Optional[httpx.Client] = None,
                ch: Optional[CompaniesHouseClient] = None, resolver=None,
                verifier=None, provider=None) -> EnrichedLead:
    lead = EnrichedLead.from_raw(raw)
    verifier = verifier or _enrich.verify_email
    own_http = http is None
    http = http or httpx.Client(timeout=20, follow_redirects=True, headers=_UA)
    try:
        # 1. website + payment behaviour + ICP signal
        website = _resolve_website(raw, resolver)
        lead.own_website = website
        lead.domain = _enrich.normalise_domain(website) if website else None
        if website:
            pay = _payment_scan(website, http)
            lead.payment_methods = pay["methods"]
            lead.payment_quote = pay["quote"]
            text = _enrich.page_text(website, client=http)
            fit = _enrich.signal_and_fit(raw.business_name,
                                         raw.categories[0] if raw.categories else "auctioneer",
                                         raw.location or raw.postcode, text, provider=provider)
            if fit.get("available"):
                lead.icp_fit = fit.get("icp_fit")
                lead.signal = fit.get("signal")
        else:
            lead.notes.append("own website not resolved")

        # 2. Companies House PECR gate + entity facts
        if ch is not None:
            cls, number, reason = crossref.match_company(ch, raw.business_name, raw.postcode)
            lead.pecr_class = cls.value
            lead.company_number = number
            if number:
                try:
                    prof = ch.get_profile(number)
                    lead.company_status = prof.get("company_status")
                    lead.company_type = prof.get("type")
                except Exception:
                    pass
            if cls is not SubscriberClass.CORPORATE:
                lead.notes.append(f"PECR: {cls.value} — research-only ({reason})")

        # 3. decision-maker (only for a confirmed corporate lead — never email a
        #    sole trader, and never a lead we couldn't identify)
        if lead.pecr_class == "corporate" and lead.company_number:
            dm = _decision_maker(lead.company_number, lead.domain, ch, verifier)
            lead.directors = dm["directors"]
            lead.decision_maker_name = dm["name"]
            lead.decision_maker_email = dm["email"]
            lead.decision_maker_confidence = dm["confidence"]
            if dm["note"]:
                lead.notes.append(dm["note"])
            g_email, g_conf = _generic_email(lead.domain, verifier)
            lead.generic_email = g_email
            lead.generic_confidence = g_conf
        return lead
    finally:
        if own_http:
            http.close()
