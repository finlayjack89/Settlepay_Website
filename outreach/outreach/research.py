"""Manual research — one URL in, a full company profile out.

The autonomous pipeline discovers leads itself (Places grid → Companies House
cross-reference → enrich). This module is the operator's manual entry point into the
SAME machinery: paste a website, get the scrape, the corporate check, the local data
and the ICP verdict, persisted as a normal lead so everything downstream — drafting,
the approval queue, the CRM profile — just works.

Order matters, and it is cheapest-first. `find_existing` runs before anything is
fetched or paid for, because the most common manual lookup is a company we already
hold: that returns immediately with a pointer to the record we have, spending nothing.

The PECR gate is NOT relaxed for manual research. A URL researched by hand goes
through the same `crossref.match_company` corporate test as a Places lead, and only a
confident, active, corporate match gets a real company number and becomes emailable.
Everything else is kept as research-only — visible in the CRM, never cold-emailed. A
manual lead that yields no verifiable contact is still persisted (the profile is the
point); `enrich._persist` marks it discarded so it can't be drafted, which is the same
policy the automated path applies, deliberately reused rather than re-implemented.
"""
from __future__ import annotations

import json
import re
from typing import Optional

import httpx

from . import audit, config, crossref, db, enrich, places
from .companies_house import CompaniesHouseClient

# one implementation of the dedupe key, defined next to the scrape that also uses it
normalise_domain = enrich.normalise_domain

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_OG_SITE_RE = re.compile(
    r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)', re.I)
# marketing tails a <title> almost always carries — "Acme Plumbing | Leeds & Bradford"
_TITLE_SPLIT_RE = re.compile(r"\s*[|–—·:>-]\s*")


# Every place a website domain can already be on file. Ordered by how much the hit
# tells us: a full research profile beats an enrichment row beats a raw lead.
_EXISTING_SQL = """
select company_number, matched_on from (
  select company_number, 'profile'    as matched_on, 1 as rank from outreach.profiles   where domain = %(d)s
  union all
  select company_number, 'enrichment' as matched_on, 2 as rank from outreach.enrichment where domain = %(d)s
  union all
  select company_number, 'lead'       as matched_on, 3 as rank from outreach.leads      where domain = %(d)s
  union all
  select company_number, 'lead'       as matched_on, 4 as rank from outreach.leads      where company_number = %(u)s
) x order by rank limit 1
"""


def find_existing(domain: str, *, cur) -> Optional[dict]:
    """Have we already researched this domain? Runs before any network call or spend."""
    if not domain:
        return None
    cur.execute(_EXISTING_SQL, {"d": domain, "u": f"URL:{domain}"})
    row = cur.fetchone()
    return {"company_number": row[0], "matched_on": row[1]} if row else None


def _fetch(url: str, *, client: Optional[httpx.Client] = None) -> tuple[str, str]:
    """(raw html, plain text) for the homepage. Best-effort: ('', '') on any failure."""
    owns = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=True,
                                    headers={"User-Agent": enrich.USER_AGENT})
    try:
        r = client.get(url)
        if r.status_code != 200:
            return "", ""
        raw = r.text
        text = " ".join(enrich._TAG_RE.sub(" ", raw).split())
        return raw, text[:config.ENRICH_PAGE_TEXT_MAX_CHARS]
    except httpx.HTTPError:
        return "", ""
    finally:
        if owns:
            client.close()


def company_name_from_page(raw_html: str, domain: str) -> str:
    """Best guess at the trading name, for the Companies House search. og:site_name
    is the cleanest source; a <title> needs its marketing tail cut off. Falls back to
    the domain's second-level label, which is right more often than it looks."""
    og = _OG_SITE_RE.search(raw_html or "")
    if og and og.group(1).strip():
        return og.group(1).strip()[:120]
    t = _TITLE_RE.search(raw_html or "")
    if t:
        parts = [p.strip() for p in _TITLE_SPLIT_RE.split(html_unescape(t.group(1))) if p.strip()]
        if parts:
            # the shortest leading fragment is usually the name, not the strapline
            return min(parts[:2], key=len)[:120]
    return (domain or "").split(".")[0].replace("-", " ").title()


def html_unescape(s: str) -> str:
    import html as _html
    return " ".join(_html.unescape(s or "").split())


def places_lookup(domain: str, name: str, *, cur=None) -> Optional[dict]:
    """One Places text search for this business, kept only if the result's own website
    matches the domain we were given — a name-only match is as likely to be a different
    company in a different town. Returns None when Places is unconfigured or unsure;
    the caller degrades rather than blocking (address/postcode are nice-to-have, and
    the postcode only sharpens the Companies House match)."""
    try:
        results = places.text_search(f"{name} {domain}", max_results=5, cur=cur)
    except places.PlacesUnavailable:
        return None
    except Exception:
        return None
    for r in results:
        if normalise_domain(r.get("website") or "") == domain:
            return r
    return None


# CRM facts, extracted once at research time. Deliberately NOT free text: these feed
# the drafter's personalisation and the console's profile panels, so they have to be
# addressable fields rather than a paragraph someone has to re-read every time.
_PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "one_liner": {"type": "string"},
        "services": {"type": "array", "items": {"type": "string"}},
        "customers": {"type": "string"},
        "coverage": {"type": "string"},
        "payment_methods": {"type": "array", "items": {"type": "string"}},
        "booking_method": {"type": "string"},
        "roles_mentioned": {"type": "array", "items": {"type": "string"}},
        "hooks": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["one_liner", "services", "payment_methods", "hooks"],
}


def extract_profile(company_name: str, vertical: Optional[str], text: str,
                    *, provider=None) -> dict:
    """Structured CRM facts from the scraped page. Returns {} on any failure — a
    profile is an enrichment of the record, never a precondition for it."""
    if not text:
        return {}
    if provider is None:
        if not config.GEMINI_PROJECT:
            return {}
        from .llm import get_provider
        provider = get_provider("gemini", model=config.GEMINI_FAST_MODEL)
    # roles_mentioned is job TITLES only by default. A named individual on a company
    # website is still personal data under UK GDPR — it pulls in transparency duties
    # (tell them within ~a month) and an absolute right to object that role addresses
    # do not. Capturing names is a posture decision, so it is opt-in, off by default,
    # exactly like the never-persist-phones rule.
    people_rule = (
        "roles_mentioned: job titles of decision-makers named on the site (e.g. "
        "'Managing Director', 'Practice Manager'). Titles ONLY — never personal names."
        if not config.RESEARCH_CAPTURE_PEOPLE else
        "roles_mentioned: decision-makers as 'Name — Title' where the site names them.")
    prompt = (
        "You are building a CRM profile of a small UK business for SettlePay, which "
        "builds branded card-payment pages and invoicing on a business's own domain.\n"
        f"BUSINESS: {company_name}" + (f" — {vertical}" if vertical else "") + "\n"
        f"WEBSITE TEXT (may be partial):\n{text}\n\n"
        "From the text ONLY, in UK English. Never invent: omit a field rather than "
        "guess, and say 'not stated' where the site is silent.\n"
        "- one_liner: what this business does, one sentence.\n"
        "- services: up to 6 specific services they sell.\n"
        "- customers: who they serve (homeowners, landlords, other businesses...).\n"
        "- coverage: the area they cover.\n"
        "- payment_methods: how customers appear to pay — card online, card in "
        "person, bank transfer, cash, cheque, invoice, finance, deposit.\n"
        "- booking_method: how work is booked (phone, contact form, online booking, "
        "third-party platform).\n"
        f"- {people_rule}\n"
        "- hooks: up to 3 SPECIFIC, factual openings a rep could use about taking "
        "card payments on a branded page. Each must cite something concrete from the "
        "site. No flattery, no invented figures.\n"
        "- evidence: short quotes from the page backing the payment_methods you listed."
    )
    from .llm import LLMUnavailable
    try:
        raw = provider.complete(prompt, purpose="profile", schema=_PROFILE_SCHEMA).text.strip()
        data = json.loads(raw)
        return {k: data.get(k) for k in _PROFILE_SCHEMA["properties"] if data.get(k)}
    except (LLMUnavailable, ValueError, KeyError, TypeError):
        return {}
    except Exception:
        return {}


def save_profile(company_number: str, domain: Optional[str], facts: dict,
                 sources: list[dict], *, source: str = "manual", cur) -> None:
    cur.execute(
        "insert into outreach.profiles "
        "(company_number, domain, facts, sources, research_source, researched_at, updated_at) "
        "values (%s,%s,%s::jsonb,%s::jsonb,%s,now(),now()) "
        "on conflict (company_number) do update set "
        "domain=excluded.domain, facts=excluded.facts, sources=excluded.sources, "
        "research_source=excluded.research_source, updated_at=now()",
        (company_number, domain, json.dumps(facts or {}), json.dumps(sources or []), source))


def get_profile(company_number: str, *, cur) -> Optional[dict]:
    cur.execute("select domain, facts, sources, research_source, researched_at, updated_at "
                "from outreach.profiles where company_number=%s", (company_number,))
    row = cur.fetchone()
    if not row:
        return None
    return {"domain": row[0], "facts": row[1] or {}, "sources": row[2] or [],
            "research_source": row[3], "researched_at": row[4], "updated_at": row[5]}


def _upsert_lead(company_number: str, name: str, domain: str, cls, matched: Optional[str],
                 place: Optional[dict], *, cur) -> None:
    addr = {"website": f"https://{domain}", "formatted": (place or {}).get("address"),
            "postcode": (place or {}).get("postcode"),
            "primary_type": (place or {}).get("primary_type"),
            "types": (place or {}).get("types"),
            "business_status": (place or {}).get("business_status"),
            "researched_from": domain}
    cur.execute(
        "insert into outreach.leads (company_number, company_name, registered_address, "
        " subscriber_class, state, source, domain, place_id, matched_company_number, "
        " crossref_checked_at) "
        "values (%s,%s,%s::jsonb,%s,'discovered','manual',%s,%s,%s,now()) "
        "on conflict (company_number) do update set "
        "company_name=excluded.company_name, domain=excluded.domain, "
        # never widen an existing classification: a lead the pipeline already judged
        # keeps that verdict, and a manual re-run can only ever confirm it
        "subscriber_class=coalesce(leads.subscriber_class, excluded.subscriber_class), "
        "matched_company_number=coalesce(leads.matched_company_number, excluded.matched_company_number), "
        "registered_address=coalesce(leads.registered_address, '{}'::jsonb) || excluded.registered_address, "
        "crossref_checked_at=now(), updated_at=now()",
        (company_number, name, json.dumps(addr), cls.value, domain,
         (place or {}).get("place_id"), matched))


def research_url(url: str, *, cur, force: bool = False, ch=None, log=None) -> dict:
    """Full manual research for one website. See the module docstring for ordering.

    Returns {status, company_number, ...}. status is 'existing' (already on file,
    nothing spent), 'researched' (new record written), or 'error'.
    """
    def say(msg):
        if log:
            log(msg)

    domain = normalise_domain(url)
    if not domain:
        return {"status": "error", "error": f"not a usable website address: {url!r}"}

    if not force:
        hit = find_existing(domain, cur=cur)
        if hit:
            say(f"{domain} already on file ({hit['matched_on']}) — nothing spent")
            return {"status": "existing", "domain": domain, **hit}

    website = f"https://{domain}"
    say(f"fetching {website}")
    owns_ch = ch is None   # bound before the try: the finally closes it either way
    http = httpx.Client(timeout=20, follow_redirects=True,
                        headers={"User-Agent": enrich.USER_AGENT})
    try:
        raw, text = _fetch(website, client=http)
        if not raw:
            say("homepage unreachable over plain HTTP — continuing without page text")
        name = company_name_from_page(raw, domain)
        say(f"trading name looks like: {name}")

        place = places_lookup(domain, name, cur=cur)
        if place:
            say(f"Places match: {place.get('address') or 'no address'}")
            name = place.get("name") or name

        # PECR gate — identical to the Places path: corporate + active, or research-only
        if owns_ch:
            try:
                ch = CompaniesHouseClient()
            except Exception as e:
                ch = None
                say(f"Companies House unavailable ({e}) — lead stays research-only")
        if ch is not None:
            cls, matched, reason = crossref.match_company(ch, name, (place or {}).get("postcode"))
        else:
            cls, matched, reason = crossref.SubscriberClass.UNKNOWN, None, "no Companies House client"
        say(f"Companies House: {cls.value} — {reason}")

        # a confident corporate match keys the lead by its REAL company number, so a
        # manual lookup and the automated pipeline converge on one record
        company_number = matched if (cls is crossref.SubscriberClass.CORPORATE and matched) \
            else f"URL:{domain}"
        # ...but crossref does NOT re-key a Places lead when it matches: it records the
        # number in matched_company_number and leaves the row as PLACE:<id>. Keying a
        # manual research by the CH number would then open a SECOND row for a business
        # already on file. Adopt the existing row instead.
        if matched:
            cur.execute("select company_number from outreach.leads "
                        "where matched_company_number = %s and company_number <> %s "
                        "order by created_at limit 1", (matched, company_number))
            prior = cur.fetchone()
            if prior:
                say(f"already held as {prior[0]} (matched {matched}) — updating that record")
                company_number = prior[0]
        if not force:
            cur.execute("select 1 from outreach.leads where company_number=%s", (company_number,))
            if cur.fetchone():
                say(f"already held as {company_number}")
                return {"status": "existing", "company_number": company_number,
                        "domain": domain, "matched_on": "company_number"}

        _upsert_lead(company_number, name, domain, cls, matched, place, cur=cur)
        audit.record(company_number, "researched", source="manual",
                     lawful_basis=audit.LEGITIMATE_INTERESTS,
                     reason=f"manual research of {domain}: {cls.value}; {reason}", cur=cur)

        # Places' primaryType ("plumber", "accounting") is already the vertical label —
        # it is not a SIC code, so it must not go through stats.sic_label
        vertical = ((place or {}).get("primary_type") or "").replace("_", " ") or None
        town = (place or {}).get("address")

        say("scraping + verifying a contact address")
        g = enrich._gather(website, http_client=http)
        fit = enrich.signal_and_fit(name, vertical, town, text) if text else {"available": False}
        g["fit"] = fit
        g["signal_source"] = "llm" if fit.get("available") else "factual"
        signal = fit.get("signal") or f"{name} — researched from {domain}"

        # the same persist the automated path uses: one enrich/discard policy, not two
        result = enrich._persist(company_number, website, signal, g, cur=cur)
        cur.execute("update outreach.enrichment set domain=%s where company_number=%s",
                    (domain, company_number))
        say(f"contact: {result.get('email') or 'none found'} ({result.get('result')})")

        facts = extract_profile(name, vertical, text)
        sources = [{"kind": "website", "ref": website}]
        if place:
            sources.append({"kind": "places", "ref": place.get("place_id")})
        if matched:
            sources.append({"kind": "companies_house", "ref": matched})
        save_profile(company_number, domain, facts, sources, source="manual", cur=cur)
        say(f"profile saved with {len(facts)} fact groups")

        return {"status": "researched", "company_number": company_number, "domain": domain,
                "company_name": name, "subscriber_class": cls.value,
                "sendable": cls is crossref.SubscriberClass.CORPORATE,
                "contact_email": result.get("email"), "contact_tier": result.get("tier"),
                "icp_fit": result.get("icp_fit"), "discarded": result.get("disqualified"),
                "facts": sorted(facts)}
    finally:
        http.close()
        if ch is not None and owns_ch:
            ch.close()


def run(url: str, *, force: bool = False, cur=None, log=None) -> dict:
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    try:
        out = research_url(url, cur=cur, force=force, log=log)
        if own:
            conn.commit()
        return out
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        if own and conn is not None:
            conn.close()
