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

import difflib
import re
from typing import Optional

import httpx

from .. import crossref, decisionmakers, deepmatch, places
from .. import enrich as _enrich
from ..companies_house import CompaniesHouseClient
from ..firewall import SubscriberClass
from . import config, payment
from .models import AuctionLead, EnrichedLead

_UA = {"User-Agent": config.USER_AGENT}

# A resolved URL on one of these is NOT the auctioneer's own website — it's another
# auction platform / aggregator, or a video/marketplace page. Rejecting them also stops
# dedupe collapsing every unresolved lead onto a shared platform domain. (facebook/
# linkedin/twitter/instagram etc. are already handled by enrich.SKIP_DOMAINS.)
_REJECT_DOMAINS = (
    "easyliveauction.com", "the-saleroom.com", "saleroom.com", "bidspotter.co.uk",
    "bidspotter.com", "i-bidder.com", "the-auctioncollective.com", "liveauctioneers.com",
    "invaluable.com", "the-saleroom", "auctionet.com", "bidsquare.com", "the-auction",
    "youtube.com", "youtu.be", "vimeo.com", "ebay.co.uk", "ebay.com", "etsy.com",
    "the-saleroom.com")


# Words that carry no identity — every auction house has them, so they can never be the
# thing that matches a domain to a business.
_GENERIC_NAME_WORDS = frozenset({
    "auction", "auctions", "auctioneer", "auctioneers", "auctioneering", "saleroom",
    "salerooms", "sale", "sales", "valuer", "valuers", "valuation", "valuations",
    "ltd", "limited", "llp", "plc", "the", "and", "for", "with", "company", "group",
    "holdings", "services", "trading", "house", "online", "uk", "gb", "london", "fine",
    "art", "arts", "antique", "antiques", "estate", "estates", "gallery", "galleries",
    "international", "consultancy", "solutions", "centre", "center", "bid", "bidding"})


def _name_matches_domain(business_name: str, url: str) -> Optional[bool]:
    """Does this domain plausibly belong to this business? None = can't tell.

    A distinctive word from the name must survive in the domain. Without this the
    resolver's best guess is accepted verbatim, and on thin sources (Invaluable gives no
    postcode at all) that guess is regularly a different company or a newspaper article
    about them — which would then supply the payment signal, the domain and the email
    guesses for the WRONG business.
    """
    stem = re.sub(r"[^a-z0-9]", "", _enrich.normalise_domain(url) or "")
    if not stem:
        return None
    words = [w for w in re.split(r"[^a-z0-9]+", business_name.lower())
             if len(w) >= 4 and w not in _GENERIC_NAME_WORDS]
    if not words:
        return None                     # nothing distinctive to check against
    return any(w in stem for w in words)


def places_fill(raw: AuctionLead, *, cur=None) -> Optional[dict]:
    """Google Places lookup for a lead the platform under-described.

    Only called when the platform left a gap (no website, or no postcode) — Places bills
    GCP credit per search, and the ATG platforms already supply both. It is the better
    source than a web search when it answers: the website comes from a maintained
    business listing rather than a search result that happened to rank first.

    Guarded on the business NAME matching the listing: a name-only Places hit is as
    likely to be a different company in a different town, which is exactly the failure
    that put a Maine auction house and a newspaper article into the last sample.
    """
    if not (raw.business_name and config._oc.GOOGLE_MAPS_API_KEY):
        return None
    where = raw.postcode or raw.location or ""
    try:
        results = places.text_search(f"{raw.business_name} {where}".strip(),
                                     max_results=5, cur=cur)
    except Exception:
        return None                     # Places is nice-to-have; never block the lead
    want = deepmatch._norm(raw.business_name)
    for r in results:
        got = deepmatch._norm(r.get("name") or "")
        if not got:
            continue
        ratio = difflib.SequenceMatcher(None, want, got).ratio()
        if ratio < 0.6:
            continue
        if (r.get("business_status") or "OPERATIONAL") != "OPERATIONAL":
            continue                    # closed premises: not a lead, and not our postcode
        site = r.get("website")
        if site and (any(p in site.lower() for p in _REJECT_DOMAINS)
                     or _name_matches_domain(raw.business_name, site) is False):
            site = None                 # a listing pointing at a platform/other company
        return {"website": site, "postcode": r.get("postcode"),
                "locality": (r.get("address") or "").split(",")[-2].strip()
                if (r.get("address") or "").count(",") >= 2 else None,
                "name_ratio": round(ratio, 2)}
    return None


def _resolve_website(raw: AuctionLead, resolver, places_hit: Optional[dict] = None
                     ) -> tuple[Optional[str], Optional[str]]:
    """Returns (url, note). The note explains a rejection so a blank website is never
    just an unexplained gap in the output."""
    if raw.own_website:
        return raw.own_website, None    # the platform told us — no guessing involved
    if places_hit and places_hit.get("website"):
        return places_hit["website"], None   # a maintained listing beats a search result
    if resolver is None:
        return None, None
    hint = "auctioneer " + (raw.categories[0] if raw.categories else "auction house")
    try:
        url = resolver.resolve(company_name=raw.business_name,
                               address=raw.postcode or raw.location or "", hint=hint)
    except Exception:
        return None, None
    if not url:
        return None, None
    if any(p in url.lower() for p in _REJECT_DOMAINS):
        return None, None               # a platform / aggregator / video page, not their site
    match = _name_matches_domain(raw.business_name, url)
    if match is False:
        return None, f"website candidate {url} rejected: name does not match the domain"
    if match is None:
        return url, f"website {url} unverified: no distinctive word in the business name"
    return url, None


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
        # 0. fill the platform's gaps from Places, but only where there IS a gap —
        #    the ATG platforms already supply both website and postcode.
        places_hit = None
        if not raw.own_website or not raw.postcode:
            places_hit = places_fill(raw)
            if places_hit:
                if not raw.postcode and places_hit.get("postcode"):
                    lead.postcode = places_hit["postcode"]
                    lead.notes.append(f"postcode {places_hit['postcode']} from Places")
                if not raw.location and places_hit.get("locality"):
                    lead.location = places_hit["locality"]

        # 1. website + payment behaviour + ICP signal
        website, note = _resolve_website(raw, resolver, places_hit)
        if note:
            lead.notes.append(note)
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

        # 2. Companies House PECR gate + entity facts.
        #    The shallow (relevance-ranked) search resolves a business trading under its
        #    registered name. When it can't — the common case for auctioneers, whose
        #    trading name rarely matches the register — fall through to the deep matcher,
        #    which searches on distinctive words and corroborates against the postcode,
        #    the domain we just resolved, the SIC code and the town. Deep only ever
        #    UPGRADES an unknown: a shallow match that already succeeded is left alone.
        if ch is not None:
            cls, number, reason = crossref.match_company(ch, raw.business_name,
                                                         lead.postcode or raw.postcode)
            if cls is SubscriberClass.UNKNOWN and number is None:
                d_cls, d_number, d_reason = deepmatch.classify_deep(
                    ch, raw.business_name, postcode=lead.postcode or raw.postcode,
                    domain=lead.domain, locality=lead.location or raw.location)
                if d_number:
                    cls, number, reason = d_cls, d_number, d_reason
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
