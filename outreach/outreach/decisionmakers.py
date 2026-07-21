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


def store_officers(company_number: str, items: list[dict], *, cur) -> int:
    """Persist active decision-making officers, minimised. Returns how many were kept."""
    kept = 0
    for it in items:
        if it.get("resigned_on"):                       # active only
            continue
        role = (it.get("officer_role") or "").lower()
        if role not in _DECISION_ROLES:
            continue
        name = it.get("name")
        if not name:
            continue
        cur.execute(
            "insert into outreach.officers (company_number, name, role, appointed_on) "
            "values (%s,%s,%s,%s) on conflict (company_number, name, role) do nothing",
            (company_number, name, role, it.get("appointed_on") or None))
        kept += 1
    return kept


def get_officers(company_number: str, *, cur) -> list[dict]:
    cur.execute("select name, role, appointed_on from outreach.officers "
                "where company_number=%s order by appointed_on nulls last", (company_number,))
    return [{"name": n, "role": r, "appointed_on": a} for n, r, a in cur.fetchall()]


def _domain_is_catch_all(company_number: str, *, cur) -> bool:
    """A catch-all domain answers 'ok' to nothing and 'catch_all' to everything, so no
    permutation can be confirmed on it. If the role-address enrichment already learned
    that, skip the whole company rather than pay to prove it again."""
    cur.execute("select email_verify_result, contact_tier from outreach.enrichment "
                "where company_number=%s", (company_number,))
    row = cur.fetchone()
    return bool(row) and (row[0] == "catch_all" or row[1] == "risky")


def _fetch_officers(company_number: str, *, cur, ch) -> Optional[list[dict]]:
    """Officers from the DB, fetching + storing from Companies House on a cache miss.
    Returns None (not []) when CH itself ERRORED — a transient outage the caller must
    defer, distinct from CH answering with genuinely no active officers ([])."""
    existing = get_officers(company_number, cur=cur)
    if existing:
        return existing
    try:
        items = ch.get_officers(company_number)
    except Exception as e:
        audit.record(company_number, "officers_lookup_failed", source="decisionmakers",
                     lawful_basis=audit.LEGITIMATE_INTERESTS,
                     reason=f"CH officers unavailable: {str(e)[:80]}", cur=cur)
        return None
    kept = store_officers(company_number, items, cur=cur)
    if kept:
        audit.record(company_number, "officers", source="decisionmakers",
                     lawful_basis=audit.LEGITIMATE_INTERESTS,
                     reason=f"{kept} active officer(s) from Companies House", cur=cur)
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
        "contact_tier='named', email_verified=true, email_verify_result='ok' "
        "where company_number=%s", (email, officer_name, company_number))
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
