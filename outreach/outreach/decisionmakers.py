"""Decision-maker sourcing — Companies House officers, then infer + verify the
named director's work email.

Two stages, deliberately decoupled by cost and by risk:

1. **Officers (free, low-risk).** Companies House `/officers` is public-register data.
   We store the directors' names and roles, minimised — no DOB, no address. This alone
   improves the CRM and the drafting ("I saw you and your co-director run…") even if we
   never email a named person.

2. **Named email (paid, GDPR-loaded).** From the company's own domain we derive the
   likely email pattern, permute the director's name across a small ranked set, and
   verify each with MillionVerifier. ONLY a MillionVerifier-confirmed ('ok') address is
   ever adopted — never an unverified guess, because sending to guesses bounces and
   bouncing wrecks warm-up. On a catch-all domain nothing can be confirmed, so we skip
   it rather than burn credits proving nothing.

Compliance posture (the price of targeting a named person, baked in, not optional):
- Lawful basis is legitimate interests, recorded on every officer row via audit_log.
- The art. 14 transparency duty — tell the person where we got their details — is
  discharged at first contact by the named-send email footer (emailfmt.TEXT_FOOTER_NAMED).
- The art. 21 right to object is the existing unsubscribe → suppression path; a named
  email is just an email, so an opt-out suppresses it like any other.
- OFF by default (config.DECISION_MAKER_ENABLED). Turning it on is the operator's
  explicit, knowing act — the same posture as never-persist-phones and capture-people.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from . import audit, config, db
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


def match_psc(psc: set[tuple[str, str]], officer_names: list[str]) -> set[str]:
    """Which of these officer names are also a PSC. Returns the raw names, so the caller
    does not have to re-parse.

    Exact (first, last) is the primary key. The guarded fallback exists because the
    register disagrees with ITSELF: ABM Electrical Services files its director as
    "BARNES, Danile" and the same human as PSC "Daniel Barnes" — a typo in one filing,
    not two people.

    Surname alone would be unsafe: that same company also has "BARNES, Emma", and family
    firms (our commonest shape) routinely have several officers sharing a surname. So the
    fallback key is (surname, first initial) and it is honoured ONLY when it picks out
    exactly one officer and one PSC — ambiguity means no match, never a guess.
    """
    parsed = {n: parse_name(n) for n in officer_names}
    hit = {n for n, p in parsed.items() if p and p in psc}
    unmatched_psc = {p for p in psc if p not in {parsed[n] for n in hit if parsed[n]}}
    if not unmatched_psc:
        return hit
    for want in unmatched_psc:
        key = (want[1], want[0][0])
        cands = [n for n, p in parsed.items()
                 if n not in hit and p and (p[1], p[0][0]) == key]
        rivals = [p for p in psc if (p[1], p[0][0]) == key]
        if len(cands) == 1 and len(rivals) == 1:
            hit.add(cands[0])
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
                     reason=f"{kept} active officer(s) from Companies House; "
                            f"{len(psc)} individual PSC(s) matched for ranking", cur=cur)
    return get_officers(company_number, cur=cur)


def resolve_one(company_number: str, domain: Optional[str], *, cur,
                ch: CompaniesHouseClient, verifier=None) -> dict:
    """Fetch + store officers, then try to confirm ONE named work email for the
    longest-serving director. Adopts it as the lead's contact (tier 'named') only on a
    MillionVerifier 'ok'. Never invents an address; never sends to a guess."""
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
    for off in officers:                                # longest-serving first
        parsed = parse_name(off["name"])
        if not parsed:
            continue
        for addr in email_permutations(*parsed, domain):
            if checked >= config.DM_MAX_VERIFY_PER_LEAD:
                result["checked"] = checked
                result["skipped"] = "per-lead verify cap reached"
                return result
            ok, res = verifier(addr)
            checked += 1
            if res in TRANSIENT_RESULTS:
                # the verifier didn't answer (out of credits / rate-limited). Don't keep
                # guessing against a dead verifier, and don't read the non-answer as "this
                # person has no email" — defer the whole lead (dm_attempted_at stays null,
                # so it's retried next tick), officers already stored.
                result.update({"checked": checked, "deferred": True,
                               "skipped": f"verifier unavailable ({res})"})
                return result
            if ok:
                _adopt_named_contact(company_number, off["name"], addr, cur=cur)
                result.update({"named_email": addr, "verified": True,
                               "officer": off["name"], "role": off.get("role"),
                               "checked": checked})
                return result
    # every permutation checked, none confirmed — a completed attempt, don't re-bill it
    _mark_attempted(company_number, cur=cur)
    result["checked"] = checked
    return result


def _mark_attempted(company_number: str, *, cur) -> None:
    cur.execute("update outreach.enrichment set dm_attempted_at = now() "
                "where company_number = %s", (company_number,))


def _adopt_named_contact(company_number: str, officer_name: str, email: str, *, cur) -> None:
    """Promote a confirmed named address to the lead's contact. tier 'named' ranks above
    'verified' (role), so send.py prefers it; contact_name records who it is."""
    cur.execute(
        "update outreach.enrichment set contact_email=%s, contact_name=%s, "
        "contact_tier='named', email_verified=true, email_verify_result='ok', "
        # keep the drafting constants in step: a name the drafter may greet by is exactly
        # a name we have CONFIRMED (officer on the register + a verified work address).
        # Without this the facts block would still say contact_name UNKNOWN and the draft
        # would open "Dear <business>," despite our knowing who runs it.
        "facts = jsonb_set(coalesce(facts, '{}'::jsonb), '{contact_name}', %s::jsonb, true) "
        "where company_number=%s",
        (email, officer_name,
         json.dumps({"value": officer_name, "source": "ch_officer_verified_email",
                     "verified": True}),
         company_number))
    audit.record(company_number, "decision_maker", source="decisionmakers",
                 lawful_basis=audit.LEGITIMATE_INTERESTS,
                 reason=f"named contact {email} ({officer_name}) — verified, art.14 notice on send",
                 cur=cur)


_BACKLOG_SQL = (
    "select l.company_number, e.domain from outreach.leads l "
    "join outreach.enrichment e on e.company_number = l.company_number "
    "where l.subscriber_class = 'corporate' and l.state = 'enriched' "
    "and e.domain is not null and e.contact_tier is distinct from 'named' "
    # dm_attempted_at gates the retry, NOT the presence of officers: a lead whose officers
    # were fetched during a verifier outage has null dm_attempted_at and must be retried.
    "and e.dm_attempted_at is null "
    "order by l.updated_at desc limit %s")


def run(*, limit: int = 10, cur=None) -> dict:
    """Resolve decision-makers for up to `limit` enriched corporate leads that don't yet
    have a named contact. Paid (MillionVerifier); gated by DECISION_MAKER_ENABLED in the
    tick. A verifier outage defers cleanly — nothing is confirmed, so nothing changes."""
    if not config.DM_ENABLED:
        return {"skipped": "DECISION_MAKER_ENABLED off"}
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    ch = None
    out = {"resolved": 0, "officers_only": 0, "deferred": 0, "processed": 0}
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
