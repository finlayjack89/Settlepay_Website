"""Decision-maker sourcing — who runs this business, and the safest way to reach them.

The goal is NOT "a personal email address". It is **a named human to address, and the
safest inbox that reaches them**. Those are different targets, and conflating them is what
made the first version of this module throw away its cheapest asset.

The waterfall, cheapest and safest first:

1. **Who (free).** Companies House `/officers` + `/persons-with-significant-control`.
   Officers are stored minimised — name, role, occupation, and a BOOLEAN "is also a PSC".
   Never a DOB, an address, a nationality or an ownership percentage. Ranked so the
   owner-operator wins, because every cost downstream is spent on whoever ranks first.

2. **SOURCED address.** An address for that person which the business PUBLISHED on its own
   site (already captured in `enrichment.scraped.candidates` and, until now, never read
   again). Verified before use, but it is the address they chose to make public.

3. **DERIVED address, pattern-confirmed only.** If the site publishes a personal address
   that matches a known officer, the domain's convention is proven — `sarah.jones@` shows
   `{first}.{last}` — and applying a proven rule to a director named on the public register
   costs ONE verifier call. With no such proof we derive NOTHING. Blind permutation of four
   guesses per person was removed: it is speculative rather than necessary, and on a
   20-lead sample of the live corpus it would have spent ~80 credits to confirm nothing.

4. **FAO.** No personal address? Then the shared mailbox we already hold, addressed
   "FAO John Smith, Director". Not a failure state — on that same sample it covered 18 of
   20 leads at zero cost, and role inboxes addressed to a named person avoid the 2-4x
   complaint rate of an anonymous blast.

Only a verifier-confirmed address is ever adopted. A catch-all domain confirms nothing, so
it is skipped rather than billed. A verifier that does not ANSWER defers the lead; it never
reads as "this person has no email".

Compliance posture (the price of targeting a named person, baked in, not optional):
- Lawful basis is legitimate interests, assessed and recorded BEFORE processing in
  `docs/LIA-decision-makers.md` — audit rows carry `detail.lia` pointing at it.
- The art. 14 duty — tell the person where we got their details — is discharged at first
  contact by the named-send footer (`emailfmt.NAMED_FOOTER_NOTE`), which links the privacy
  notice section "Information We Collect From Public Sources".
- The art. 21 right to object is the existing unsubscribe -> suppression path.
- `contact_method` records `sourced` vs `derived` per address, because the two are not the
  same act and only the second is the one a regulator asks about first.
- OFF by default (config.DECISION_MAKER_ENABLED). Turning it on is the operator's
  explicit, knowing act — the same posture as never-persist-phones and capture-people.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from . import audit, config, control, db
from .companies_house import CompaniesHouseClient

# Roles that actually decide. Secretaries and nominee/corporate officers are neither the
# person nor a useful contact, so they never become an email target.
_DECISION_ROLES = ("director", "llp-member", "llp-designated-member", "member",
                   "managing-officer", "partner")

# Ranked email patterns for a UK SME. First that VERIFIES wins, so order is by how common
# the pattern is — the list is short on purpose because each entry is a paid MV check.
_PATTERNS = (
    "{first}.{last}", "{first}", "{f}{last}", "{first}{last}", "{f}.{last}", "{last}",
)

_NAME_CLEAN = re.compile(r"[^a-z]")
# Everything from the first character that cannot be part of a name onwards. Hyphens and
# apostrophes stay (Parry-Williams, O'Brien); stray commas and full stops from the register
# do not.
_DISPLAY_TRIM = re.compile(r"[^A-Za-z'\-].*$")

# Occupations that say "this person runs the business" rather than "this person is on the
# board". Matched as substrings of a lowercased occupation, so "Managing Director" and
# "Company Director / Owner" both hit.
_PRINCIPAL_OCCUPATIONS = ("managing", "owner", "proprietor", "principal", "founder",
                          "chief executive", "ceo", "partner")

# Rank weights. Deliberately spread so no combination of weaker signals outranks PSC: the
# question "who owns this company" beats every proxy for it.
_W_PSC = 8          # active director AND person with significant control
_W_EPONYM = 4       # surname is in the company name — "J SMITH & SONS"
_W_OCCUPATION = 2   # self-declared as running it


def psc_names(items: list[dict]) -> set[tuple[str, str]]:
    """(first, last) for each ACTIVE INDIVIDUAL person with significant control.

    Corporate and legal-person PSCs are filtered out — a holding company is not someone to
    email. `ceased_on` present means the control has ended.

    Only the name is read. natures_of_control, address, DOB and nationality are left in the
    response object and never persisted (migration 0016).

    PSC and officer names arrive in DIFFERENT shapes: officers are surname-first
    ("SMITH, John Andrew"), PSCs are natural order with a `name_elements` sub-object. Using
    name_elements avoids re-parsing a title ("Mr", "Dr") as a forename.
    """
    out: set[tuple[str, str]] = set()
    for it in items:
        if it.get("ceased_on"):
            continue
        if not str(it.get("kind") or "").startswith("individual"):
            continue
        el = it.get("name_elements") or {}
        first = _NAME_CLEAN.sub("", str(el.get("forename") or "").lower())
        last = _NAME_CLEAN.sub("", str(el.get("surname") or "").lower())
        if not (first and last):
            # no name_elements: fall back to the display name, dropping a leading title
            parts = [p for p in str(it.get("name") or "").split() if p]
            parts = [p for p in parts if _NAME_CLEAN.sub("", p.lower()) not in
                     ("mr", "mrs", "ms", "miss", "dr", "sir", "prof")]
            if len(parts) < 2:
                continue
            first = _NAME_CLEAN.sub("", parts[0].lower())
            last = _NAME_CLEAN.sub("", parts[-1].lower())
        if len(first) >= 2 and len(last) >= 2:
            out.add((first, last))
    return out


def display_name(ch_name: str) -> Optional[str]:
    """'SMITH, John Andrew' -> 'John Smith', as a human would write it.

    Companies House shouts the surname and properly-cases the forenames, so only the
    surname is re-cased — the forename is left exactly as filed. Getting someone's own
    name wrong in the first line of a cold email is worse than not naming them at all,
    which is why 'Mc' is special-cased (McDonald, McBride, McKenzie are always capitalised
    after the prefix) while 'Mac' deliberately is NOT: Mackie and MacDonald are both real
    and nothing in the string tells them apart, so we leave what the register gave us.

    Middle names are dropped: nobody is addressed as "John Andrew Smith".
    """
    parsed_raw = ch_name.partition(",") if ch_name and "," in ch_name else None
    if not parsed_raw:
        return None
    surname_raw, _, rest = parsed_raw
    forenames = [t for t in rest.split() if t]
    if not forenames or not surname_raw.strip():
        return None
    # Trim anything that is not part of a name. Real filings carry a SECOND comma —
    # "THOMSON, James, Noble" — and partition() only splits the first, so the forename
    # arrived as "James," and the FAO line read "FAO James, Thomson". A mangled name in
    # the first line of a cold email is worse than no name at all.
    first = _DISPLAY_TRIM.sub("", forenames[0])
    surname_raw = _DISPLAY_TRIM.sub("", surname_raw.strip())
    if len(first) < 2 or len(surname_raw) < 2:   # an initial is not a name to greet
        return None
    surname = surname_raw.strip()
    if surname.isupper() or surname.islower():
        surname = surname.title()
        if surname.startswith("Mc") and len(surname) > 2:
            surname = "Mc" + surname[2:].capitalize()
    if first.isupper():
        first = first.title()
    return f"{first} {surname}"


_ROLE_LABELS = {
    "director": "Director",
    "llp-member": "Member",
    "llp-designated-member": "Designated Member",
    "member": "Member",
    "managing-officer": "Managing Officer",
    "partner": "Partner",
}


def display_role(officer: dict) -> Optional[str]:
    """How to describe their position. The self-declared occupation wins when it is a real
    job title ("Managing Director") because it is how they describe themselves; otherwise
    fall back to the register's officer_role."""
    occ = (officer.get("occupation") or "").strip()
    if occ and 2 < len(occ) <= 40 and not occ.lower() in ("none", "n/a", "unknown"):
        return occ if not occ.isupper() else occ.title()
    return _ROLE_LABELS.get((officer.get("role") or "").lower())


def match_psc(psc: set[tuple[str, str]], officer_names: list[str]
              ) -> dict[str, Optional[tuple[str, str]]]:
    """Which officer names are also a PSC. Maps officer name -> the PSC name it matched,
    but ONLY where the two filings disagree; an exact match maps to None.

    Exact (first, last) is the primary key. The guarded fallback exists because the
    register disagrees with ITSELF: ABM Electrical Services files its director as
    "BARNES, Danile" and the same human as PSC "Daniel Barnes" — a typo in one filing,
    not two people.

    Surname alone would be unsafe: that same company also has "BARNES, Emma", and family
    firms (our commonest shape) routinely have several officers sharing a surname. So the
    fallback key is (surname, first initial) and it is honoured ONLY when it picks out
    exactly one officer and one PSC — ambiguity means no match, never a guess.

    The returned PSC name matters because it is the better SPELLING. The officers endpoint
    files a name as one shouted string; the PSC endpoint files forename and surname as
    separate structured fields, so it is less prone to a transposition. "Danile" is not a
    name and "Daniel" is — and this string is printed in the first line of a cold email.
    """
    parsed = {n: parse_name(n) for n in officer_names}
    hit: dict[str, Optional[tuple[str, str]]] = {
        n: None for n, p in parsed.items() if p and p in psc}
    unmatched_psc = {p for p in psc if p not in {parsed[n] for n in hit if parsed[n]}}
    for want in unmatched_psc:
        key = (want[1], want[0][0])
        cands = [n for n, p in parsed.items()
                 if n not in hit and p and (p[1], p[0][0]) == key]
        rivals = [p for p in psc if (p[1], p[0][0]) == key]
        if len(cands) == 1 and len(rivals) == 1:
            hit[cands[0]] = want          # same human, better spelling
    return hit


def rank_officer(*, name: str, occupation: Optional[str], is_psc: bool,
                 company_name: Optional[str]) -> int:
    """Score one officer as a decision-maker. Higher wins; ties break on earliest
    appointment (the founder), which the SQL ordering applies.

    Ordering matters more than it looks: every downstream cost — a verifier credit, a
    drafted email, an actual message to a human — is spent on whoever ranks first. Picking
    the longest-serving director alone (the old behaviour) spends it on a retired
    co-founder as readily as on the owner.
    """
    score = 0
    if is_psc:
        score += _W_PSC
    parsed = parse_name(name)
    if parsed and company_name:
        # Reused rather than re-implemented: the same stem matcher that decides whether a
        # freemail local part belongs to the business.
        from .enrich import stem_matches_name
        if stem_matches_name(parsed[1], company_name) is True:
            score += _W_EPONYM
    if occupation:
        low = occupation.lower()
        if any(w in low for w in _PRINCIPAL_OCCUPATIONS):
            score += _W_OCCUPATION
    return score


def parse_name(ch_name: str) -> Optional[tuple[str, str]]:
    """Companies House holds officer names surname-first: 'SMITH, John Andrew'. Return
    (first, last) lowercased and stripped to letters, or None if it can't be split into a
    usable given + family name (initials-only, corporate officers, etc.)."""
    if not ch_name or "," not in ch_name:
        return None
    last_part, _, rest = ch_name.partition(",")
    last = _NAME_CLEAN.sub("", last_part.lower())
    firsts = [t for t in (_NAME_CLEAN.sub("", t.lower()) for t in rest.split()) if t]
    if not last or not firsts:
        return None
    first = firsts[0]
    # a single-letter forename is an initial — not enough to build {first}.{last} from
    if len(first) < 2 or len(last) < 2:
        return None
    return first, last


def local_matches(local: str, first: str, last: str) -> bool:
    """Does this email local part belong to this person?

    Matched against the SAME pattern set we would derive from, so "does this address
    belong to Sarah Jones" and "what would Sarah Jones's address be" can never disagree.
    """
    cleaned = _NAME_CLEAN.sub("", local.lower())
    return any(cleaned == _NAME_CLEAN.sub("", pat.format(first=first, last=last,
                                                         f=first[0]).lower())
               for pat in _PATTERNS)


def infer_pattern(published: list[str], officers: list[dict], domain: str) -> Optional[str]:
    """The domain's email convention, learned from an address it PUBLISHED.

    Seeing `sarah.jones@acme.co.uk` next to officer "JONES, Sarah" proves this domain uses
    `{first}.{last}`. That turns a guess into an application of a known rule: one verifier
    call instead of four, at a much higher confirm rate.

    A GENERIC address reveals nothing — `info@` is true of every convention — so generic
    local parts are excluded explicitly rather than incidentally (research doc §4).

    Returns the pattern string, or None when nothing on this domain identifies a person we
    can name.
    """
    from .enrich import GENERIC_PREFIXES
    people = [(p, o) for o in officers if (p := parse_name(o.get("name") or ""))]
    for addr in published:
        addr_domain = addr.rpartition("@")[2].lower()
        if not domain or addr_domain != domain.lower():
            continue
        local = addr.partition("@")[0].lower()
        if any(local == g or local.startswith(g) for g in GENERIC_PREFIXES):
            continue                      # a shared mailbox proves nothing about the rule
        cleaned = _NAME_CLEAN.sub("", local)
        for (first, last), _ in people:
            for pat in _PATTERNS:
                built = _NAME_CLEAN.sub(
                    "", pat.format(first=first, last=last, f=first[0]).lower())
                if cleaned == built:
                    return pat
    return None


def email_permutations(first: str, last: str, domain: str) -> list[str]:
    """Ranked candidate addresses for one person on one domain, capped by config so a
    catch-all-looking domain can't run up the MV bill."""
    seen: list[str] = []
    for pat in _PATTERNS[:config.DM_MAX_PATTERNS]:
        local = pat.format(first=first, last=last, f=first[0])
        addr = f"{local}@{domain}"
        if addr not in seen:
            seen.append(addr)
    return seen


def store_officers(company_number: str, items: list[dict], *, cur,
                   psc: Optional[set[tuple[str, str]]] = None,
                   company_name: Optional[str] = None) -> int:
    """Persist active decision-making officers, minimised and RANKED. Returns how many
    were kept.

    `psc` is the set of (first, last) for active individual PSCs, from psc_names(). An
    officer in that set is flagged is_psc — a boolean, never the ownership detail.

    The upsert UPDATES rather than doing nothing on conflict: re-fetching a company has to
    be able to refresh a rank, or an officer stored before PSC existed would keep a stale
    score for ever and never be reconsidered.
    """
    psc = psc or set()
    # Matched over the WHOLE officer list, not per row: the typo fallback in match_psc has
    # to see every officer to know whether an initial match is unambiguous.
    eligible = [it for it in items
                if not it.get("resigned_on") and not it.get("is_corporate_officer")
                and (it.get("officer_role") or "").lower() in _DECISION_ROLES
                and it.get("name")]
    psc_hits = match_psc(psc, [it["name"] for it in eligible])
    kept = 0
    for it in items:
        if it.get("resigned_on"):                       # active only
            continue
        # A corporate director (an accountancy firm acting as director) is not a person and
        # not someone to write to. The role filter catches 'corporate-director'; this catches
        # the flag on an otherwise normal-looking role.
        if it.get("is_corporate_officer"):
            continue
        role = (it.get("officer_role") or "").lower()
        if role not in _DECISION_ROLES:
            continue
        name = it.get("name")
        if not name:
            continue
        occupation = it.get("occupation") or None
        is_psc = name in psc_hits
        # Where the two filings disagree, keep the PSC's spelling. The officers endpoint
        # gives one shouted string; the PSC endpoint files forename and surname as separate
        # structured fields, so it is the less error-prone of the two. The live case is
        # "BARNES, Danile" vs PSC "Daniel Barnes" — and this name goes in the first line of
        # a real email, where "Danile" is worse than not naming them at all.
        better = psc_hits.get(name)
        if better:
            name = f"{better[1].title()}, {better[0].title()}"
        rank = rank_officer(name=name, occupation=occupation, is_psc=is_psc,
                            company_name=company_name)
        cur.execute(
            "insert into outreach.officers "
            "  (company_number, name, role, appointed_on, occupation, is_psc, rank) "
            "values (%s,%s,%s,%s,%s,%s,%s) "
            "on conflict (company_number, name, role) do update set "
            "  appointed_on = excluded.appointed_on, occupation = excluded.occupation, "
            "  is_psc = excluded.is_psc, rank = excluded.rank",
            (company_number, name, role, it.get("appointed_on") or None,
             occupation, is_psc, rank))
        kept += 1
    return kept


def get_officers(company_number: str, *, cur) -> list[dict]:
    """Officers best-first. Rank decides; earliest appointment (the founder) breaks ties."""
    cur.execute("select name, role, appointed_on, occupation, is_psc, rank "
                "from outreach.officers where company_number=%s "
                "order by rank desc, appointed_on nulls last", (company_number,))
    return [{"name": n, "role": r, "appointed_on": a, "occupation": o,
             "is_psc": p, "rank": k} for n, r, a, o, p, k in cur.fetchall()]


def _domain_is_catch_all(company_number: str, *, cur) -> bool:
    """A catch-all domain answers 'ok' to nothing and 'catch_all' to everything, so no
    permutation can be confirmed on it. If the role-address enrichment already learned
    that, skip the whole company rather than pay to prove it again."""
    cur.execute("select email_verify_result, contact_tier from outreach.enrichment "
                "where company_number=%s", (company_number,))
    row = cur.fetchone()
    return bool(row) and (row[0] == "catch_all" or row[1] == "risky")


def register_number(company_number: str, *, cur) -> Optional[str]:
    """The number to call Companies House WITH — which is not the lead's key for most leads.

    crossref deliberately does NOT re-key a Places lead when it matches the register: it
    writes `matched_company_number` and leaves `company_number` as the synthetic
    'PLACE:<place_id>' (the reasoning is at research.py:298 — re-keying would open a second
    row for a business already on file).

    **2,689 of our 2,803 corporate leads are that shape.** Calling the register with the
    lead's own key returns 502/404 for 96% of the corpus — and it fails silently in the
    shape that matters: officers simply never arrive, the audit line reads "CH unavailable",
    and every backlog query still looks healthy. This is the same failure class as
    graduation keying on sic_codes[1] (null for 14,870 of 14,984 leads).

    Returns None when the lead has no register number at all.
    """
    cur.execute("select company_number, matched_company_number from outreach.leads "
                "where company_number = %s", (company_number,))
    row = cur.fetchone()
    if not row:
        return None
    own, matched = row
    if own and not own.startswith(("PLACE:", "URL:")):
        return own
    return matched or None


def _fetch_officers(company_number: str, *, cur, ch) -> Optional[list[dict]]:
    """Officers from the DB, fetching + storing from Companies House on a cache miss.
    Returns None (not []) when CH itself ERRORED — a transient outage the caller must
    defer, distinct from CH answering with genuinely no active officers ([])."""
    existing = get_officers(company_number, cur=cur)
    if existing:
        return existing
    reg = register_number(company_number, cur=cur)
    if not reg:
        # No register number to ask about. A completed, empty attempt — not an outage, so
        # [] (the caller marks it attempted) rather than None (retry next tick).
        return []
    try:
        items = ch.get_officers(reg)
        # PSC is the heaviest rank signal, so a transient failure here must NOT be written
        # as "nobody is a PSC": _fetch_officers short-circuits on any stored row, so a rank
        # computed during a PSC outage would be frozen in for ever and never reconsidered.
        # Deferring the whole lead is the P3 invariant — a stage that could not do its job
        # writes nothing that removes the row from its own backlog.
        psc = psc_names(ch.get_psc(reg))
    except Exception as e:
        audit.record(company_number, "officers_lookup_failed", source="decisionmakers",
                     lawful_basis=audit.LEGITIMATE_INTERESTS,
                     detail={"lia": audit.LIA_DECISION_MAKERS},
                     reason=f"CH officers/PSC unavailable: {str(e)[:80]}", cur=cur)
        return None
    cur.execute("select company_name from outreach.leads where company_number=%s",
                (company_number,))
    row = cur.fetchone()
    kept = store_officers(company_number, items, cur=cur, psc=psc,
                          company_name=row[0] if row else None)
    if kept:
        audit.record(company_number, "officers", source="decisionmakers",
                     lawful_basis=audit.LEGITIMATE_INTERESTS,
                     detail={"lia": audit.LIA_DECISION_MAKERS},
                     reason=f"{kept} active officer(s) from Companies House; "
                            f"{len(psc)} individual PSC(s) matched for ranking", cur=cur)
    return get_officers(company_number, cur=cur)


def resolve_one(company_number: str, domain: Optional[str], *, cur,
                ch: CompaniesHouseClient, verifier=None) -> dict:
    """Resolve the best contact we can justify for this lead, cheapest and safest first.

    Two outcomes, and the SECOND is not a failure:

      1. a personal work address for the top-ranked officer, adopted only on a verifier
         'ok' — never invented, never sent to as a guess; or
      2. the shared mailbox we already hold, now addressed FAO the named director.

    Outcome 2 costs nothing, needs no address we had to infer, and per the research doc
    (§6) frequently outperforms outcome 1 on both reply rate and risk for the smallest
    firms. It applies on every path that does not reach outcome 1 — no officers usable for
    an email, no domain, a catch-all domain, the verify cap, a verifier outage, or every
    candidate coming back unconfirmed.
    """
    result = _resolve_named_email(company_number, domain, cur=cur, ch=ch, verifier=verifier)
    if not result.get("verified") and result.get("officers"):
        officers = get_officers(company_number, cur=cur)
        if officers and adopt_fao_contact(company_number, officers[0], cur=cur):
            result["fao"] = officers[0]["name"]
            result["fao_applied"] = True
    return result


def _resolve_named_email(company_number: str, domain: Optional[str], *, cur,
                         ch: CompaniesHouseClient, verifier=None) -> dict:
    """Fetch + store officers, then try to confirm ONE named work email for the
    top-ranked officer. Adopts it as the lead's contact (tier 'named') only on a
    verifier 'ok'. Never invents an address; never sends to a guess."""
    from .enrich import verify_email
    verifier = verifier or verify_email

    officers = _fetch_officers(company_number, cur=cur, ch=ch)
    if officers is None:      # CH itself errored — a transient outage, retry next tick
        return {"company_number": company_number, "officers": 0, "named_email": None,
                "verified": False, "checked": 0, "deferred": True,
                "skipped": "Companies House unavailable"}
    result = {"company_number": company_number, "officers": len(officers),
              "named_email": None, "verified": False, "checked": 0}
    # CH answered with no usable officers, or we have no domain to build an email on — a
    # completed, empty attempt (don't retry).
    if not officers or not domain:
        _mark_attempted(company_number, cur=cur)
        return result
    if _domain_is_catch_all(company_number, cur=cur):
        _mark_attempted(company_number, cur=cur)
        result["skipped"] = "catch-all domain — no permutation can be confirmed"
        return result

    from .enrich import TRANSIENT_RESULTS
    checked = 0

    def attempt(addr: str, off: dict, method: str):
        """Verify one candidate. Returns ('adopted'|'defer'|'no', result-updates)."""
        nonlocal checked
        parsed = parse_name(off.get("name") or "")
        addr_domain = addr.rpartition("@")[2].lower()
        if parsed:
            cached = lookup_cached(*parsed, addr_domain, cur=cur)
            if cached == "miss":
                # asked before, no such mailbox — do not re-bill for the same answer
                return "no", {}
            if cached == "hit":
                _adopt_named_contact(company_number, off["name"], addr, cur=cur,
                                     method=method)
                return "adopted", {"named_email": addr, "verified": True, "method": method,
                                   "officer": off["name"], "role": off.get("role"),
                                   "checked": checked, "cached": True}
        ok, res = verifier(addr)
        checked += 1
        if parsed and res not in TRANSIENT_RESULTS:
            # only a real ANSWER is cacheable: caching a non-answer would turn one outage
            # into 90 days of skipped lookups, the same mistake TRANSIENT_RESULTS exists
            # to prevent
            remember_lookup(*parsed, addr_domain,
                            "hit" if ok else ("catch_all" if res == "catch_all" else "miss"),
                            cur=cur, address=addr)
        if res in TRANSIENT_RESULTS:
            # the verifier didn't answer (out of credits / rate-limited). Don't keep
            # trying against a dead verifier, and don't read the non-answer as "this
            # person has no email" — defer the whole lead (dm_attempted_at stays null,
            # so it's retried next tick), officers already stored.
            return "defer", {"checked": checked, "deferred": True,
                             "skipped": f"verifier unavailable ({res})"}
        if ok:
            _adopt_named_contact(company_number, off["name"], addr, cur=cur, method=method)
            return "adopted", {"named_email": addr, "verified": True, "method": method,
                               "officer": off["name"], "role": off.get("role"),
                               "checked": checked}
        return "no", {}

    # 1. SOURCED — an address the business published for this person. Preferred over
    #    anything we could infer: they chose to make it public, so using it is not the
    #    speculative act §7 warns about. Still verified before use — a published address
    #    can be stale — but it is one call, and it is theirs.
    for off in officers:                                # best-ranked first
        addr = sourced_address(company_number, off, domain, cur=cur)
        if not addr:
            continue
        state, upd = attempt(addr, off, "sourced")
        result.update(upd)
        if state in ("adopted", "defer"):
            return result
        break        # their published address does not verify; inventing another is worse

    # 2. DERIVED, but only from a CONFIRMED pattern. Blind permutation is gone: it tried
    #    up to four addresses per person, none of which anyone had published, and it is
    #    exactly the derive-and-email practice the research doc (§7) says has drawn ICO
    #    complaints. A personal address published on this domain proves the convention;
    #    applying a proven rule to a director named on the public register is a different
    #    act from guessing, and it costs ONE verifier call instead of four.
    published = published_candidates(company_number, cur=cur)
    pattern = infer_pattern(published, officers, domain or "")
    if not pattern:
        _mark_attempted(company_number, cur=cur)
        result["checked"] = checked
        result["skipped"] = "no confirmed email pattern for this domain"
        return result
    result["pattern"] = pattern
    for off in officers:
        if checked >= config.DM_MAX_VERIFY_PER_LEAD:
            result["checked"] = checked
            result["skipped"] = "per-lead verify cap reached"
            return result
        parsed = parse_name(off["name"])
        if not parsed:
            continue
        first, last = parsed
        addr = f"{pattern.format(first=first, last=last, f=first[0])}@{domain}"
        state, upd = attempt(addr, off, "derived")
        result.update(upd)
        if state in ("adopted", "defer"):
            return result

    # the pattern held for nobody we can name — a completed attempt, don't re-bill it
    _mark_attempted(company_number, cur=cur)
    result["checked"] = checked
    return result


def published_candidates(company_number: str, *, cur) -> list[str]:
    """Every address the business itself published that we hold — the chosen contact AND
    the ones the contact picker passed over.

    enrichment.scraped.candidates has been recorded all along and never read again. At
    enrichment time preferring info@ over sarah@ is CORRECT — we have no idea whether
    Sarah is the owner or the receptionist. Once the register has told us who runs the
    firm that changes, and the answer is already on disk: no scrape, no credit, no call.

    contact_email is included, and that is not a technicality. `candidates` only exists on
    rows enriched after it was added, so on every older row this returned [] and no
    officer could ever be matched — while the chosen address sat right there, published,
    plainly theirs. BURNAP + ABEL is the case in point: contact damianabel@…, register
    says ABEL, Damian Nicholas, and the lead still came out with no name on it. That is
    the best outcome the waterfall can reach — a real personal mailbox nobody had to
    infer — missed for want of reading a column we already had.
    """
    cur.execute("select scraped, contact_email from outreach.enrichment "
                "where company_number=%s", (company_number,))
    row = cur.fetchone()
    if not row:
        return []
    raw, chosen = (row[0] or {}), row[1]
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    cands = (raw.get("candidates") if isinstance(raw, dict) else None) or []
    out = [c for c in cands if isinstance(c, str) and "@" in c]
    if chosen and "@" in chosen and chosen.lower() not in {c.lower() for c in out}:
        out.append(chosen)
    return out


def sourced_address(company_number: str, officer: dict, domain: Optional[str], *,
                    cur) -> Optional[str]:
    """An address for THIS officer that the business itself published, or None.

    Preferred over anything derived: they chose to publish it, so using it is not the
    speculative act §7 of the research doc warns about, and it needs no inference at all.
    """
    parsed = parse_name(officer.get("name") or "")
    if not parsed:
        return None
    first, last = parsed
    for addr in published_candidates(company_number, cur=cur):
        addr_domain = addr.rpartition("@")[2].lower()
        if domain and addr_domain != domain.lower():
            continue
        if local_matches(addr.partition("@")[0], first, last):
            return addr.lower()
    return None


def lookup_cached(first: str, last: str, domain: str, *, cur,
                  provider: str = "chain") -> Optional[str]:
    """A previous outcome for this exact question, or None if we have never asked.

    The question is "does <first> <last> exist at <domain>", not "is this lead done" —
    `dm_attempted_at` answers the latter and cannot stop a second lead on the same domain
    re-billing for the first lead's answer.
    """
    cur.execute(
        "select outcome from outreach.lookup_attempts "
        "where provider=%s and first_name=%s and last_name=%s and domain=%s "
        "  and created_at > now() - make_interval(days => %s)",
        (provider, first, last, domain.lower(), config.DM_CACHE_DAYS))
    row = cur.fetchone()
    return row[0] if row else None


def remember_lookup(first: str, last: str, domain: str, outcome: str, *, cur,
                    address: Optional[str] = None, provider: str = "chain") -> None:
    """Record what a paid lookup told us. Upserts, so a later re-check refreshes the age
    rather than raising on the primary key."""
    cur.execute(
        "insert into outreach.lookup_attempts "
        "  (provider, first_name, last_name, domain, outcome, address) "
        "values (%s,%s,%s,%s,%s,%s) "
        "on conflict (provider, first_name, last_name, domain) do update set "
        "  outcome = excluded.outcome, address = excluded.address, created_at = now()",
        (provider, first, last, domain.lower(), outcome, address))


def _mark_attempted(company_number: str, *, cur) -> None:
    cur.execute("update outreach.enrichment set dm_attempted_at = now() "
                "where company_number = %s", (company_number,))


def _adopt_named_contact(company_number: str, officer_name: str, email: str, *, cur,
                         method: str = "derived") -> None:
    """Promote a confirmed named address to the lead's contact. tier 'named' ranks above
    'verified' (role), so send.py prefers it; contact_name records who it is.

    The name is stored as a human writes it ("John Smith"), not as the register shouts it
    ("SMITH, John Andrew") — it is read by the drafter, shown in the console and, in the
    FAO case, printed in the email itself.
    """
    shown = display_name(officer_name) or officer_name
    src = ("ch_officer_published_email" if method == "sourced"
           else "ch_officer_verified_email")
    cur.execute(
        "update outreach.enrichment set contact_email=%s, contact_name=%s, "
        "contact_tier='named', email_verified=true, email_verify_result='ok', "
        "contact_method=%s, "
        # keep the drafting constants in step: a name the drafter may greet by is exactly
        # a name we have CONFIRMED (officer on the register + a verified work address).
        # Without this the facts block would still say contact_name UNKNOWN and the draft
        # would open "Dear <business>," despite our knowing who runs it.
        "facts = jsonb_set(coalesce(facts, '{}'::jsonb), '{contact_name}', %s::jsonb, true) "
        "where company_number=%s",
        (email, shown, method,
         json.dumps({"value": shown, "source": src, "verified": True}),
         company_number))
    audit.record(company_number, "decision_maker", source="decisionmakers",
                 lawful_basis=audit.LEGITIMATE_INTERESTS,
                 reason=f"named contact {email} ({shown}) — {method}, verified, "
                        f"art.14 notice on send",
                 cur=cur)


# Applied only to a mailbox that is BOTH deliverable and generic. 'risky' (catch-all) is
# already gated out of drafting, and 'named' is a personal mailbox that needs no FAO line.
_FAO_ELIGIBLE_TIERS = ("verified",)


def adopt_fao_contact(company_number: str, officer: dict, *, cur) -> bool:
    """Record WHO to address at a shared mailbox. Returns True if applied.

    The register tells us who runs the firm for FREE. Until now that name was discarded
    unless a paid, derived, verifier-confirmed personal address happened to land — so the
    cheap, low-risk asset was thrown away precisely when the expensive, higher-risk one
    failed. This is the inversion the research doc (§6) argues against: small personalised
    sends reply at 5.8% vs 2.1%, and a role inbox addressed to a named director gets that
    lift without ever emailing a personal address we had to guess.

    Applied only where there is a deliverable GENERIC mailbox to address. A name with
    nowhere to send it changes nothing, and overwriting a 'named' tier would replace a real
    personal mailbox with a shared one.
    """
    shown = display_name(officer.get("name") or "")
    if not shown:
        return False
    # Reused, not re-listed: GENERIC_PREFIXES is the pipeline's single definition of "a
    # shared mailbox", and a second copy here would drift from it silently.
    from .enrich import GENERIC_PREFIXES
    cur.execute("select contact_email, contact_tier from outreach.enrichment "
                "where company_number=%s", (company_number,))
    row = cur.fetchone()
    if not row or not row[0] or row[1] not in _FAO_ELIGIBLE_TIERS:
        return False
    local = row[0].partition("@")[0].lower()
    if not any(local == g or local.startswith(g) for g in GENERIC_PREFIXES):
        return False                       # a personal mailbox needs no FAO line
    role = display_role(officer)
    cur.execute(
        "update outreach.enrichment set contact_name=%s, contact_tier='role_fao', "
        "facts = jsonb_set("
        "  jsonb_set(coalesce(facts, '{}'::jsonb), '{contact_name}', %s::jsonb, true), "
        "  '{contact_role}', %s::jsonb, true) "
        "where company_number=%s",
        (shown,
         json.dumps({"value": shown, "source": "companies_house_officer", "verified": True}),
         json.dumps({"value": role, "source": "companies_house_officer", "verified": True}
                    if role else {"value": None, "source": None, "verified": False}),
         company_number))
    if cur.rowcount:
        audit.record(company_number, "fao_contact", source="decisionmakers",
                     lawful_basis=audit.LEGITIMATE_INTERESTS,
                     detail={"lia": audit.LIA_DECISION_MAKERS},
                     reason=f"shared mailbox addressed FAO {shown}"
                            f"{' (' + role + ')' if role else ''} — officer on the public "
                            f"register; no personal address held or inferred",
                     cur=cur)
        return True
    return False


_BACKLOG_SQL = (
    "select l.company_number, e.domain from outreach.leads l "
    "join outreach.enrichment e on e.company_number = l.company_number "
    "where l.subscriber_class = 'corporate' and l.state = 'enriched' "
    # a domain is what an EMAIL is built on, but the FAO outcome needs only a mailbox we
    # already hold — so a lead with a contact and no resolved domain still has work to do
    "and (e.domain is not null or e.contact_email is not null) "
    "and e.contact_tier is distinct from 'named' "
    # dm_attempted_at gates the retry, NOT the presence of officers: a lead whose officers
    # were fetched during a verifier outage has null dm_attempted_at and must be retried.
    "and e.dm_attempted_at is null "
    "order by l.updated_at desc limit %s")


def run(*, limit: int = 10, cur=None) -> dict:
    """Resolve decision-makers for up to `limit` enriched corporate leads that don't yet
    have a named contact. Paid (MillionVerifier); gated by DECISION_MAKER_ENABLED in the
    tick. A verifier outage defers cleanly — nothing is confirmed, so nothing changes."""
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    # Read the switch on the CALLER's cursor. Letting control.get open its own connection
    # would both waste one per call and — worse — read outside the caller's transaction,
    # so a switch set moments earlier in the same unit of work would be invisible.
    if not control.get("DM_ENABLED", cur=cur):
        if own and conn is not None:
            conn.close()
        return {"skipped": "decision-maker lookup switched off"}
    ch = None
    # `fao` is a RESULT, not a consolation: a shared mailbox addressed to the named
    # director. officers_only means we learned who runs it but had no mailbox to use.
    out = {"resolved": 0, "fao": 0, "officers_only": 0, "deferred": 0, "processed": 0}
    try:
        cur.execute(_BACKLOG_SQL, (limit,))
        rows = cur.fetchall()
        if rows:
            ch = CompaniesHouseClient()
        for company_number, domain in rows:
            # officers are fetched + stored even when the verifier is down (they're the
            # free CRM win), so we keep processing the batch rather than bailing early —
            # a deferred lead cost one cheap probe and gained its directors.
            r = resolve_one(company_number, domain, cur=cur, ch=ch)
            out["processed"] += 1
            if r.get("verified"):
                out["resolved"] += 1
            elif r.get("fao_applied"):
                out["fao"] += 1
            elif r.get("deferred"):
                out["deferred"] += 1
            elif r.get("officers"):
                out["officers_only"] += 1
        if own:
            conn.commit()
        return out
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        if ch is not None:
            ch.close()
        if own and conn is not None:
            conn.close()
