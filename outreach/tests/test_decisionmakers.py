import uuid

import pytest

from outreach import config, decisionmakers as dm

pytestmark = pytest.mark.floor_d


# --------------------------------------------------------------------------- #
#  Name parsing + email inference (pure, no DB)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("SMITH, John Andrew", ("john", "smith")),
    ("O'BRIEN, Mary", ("mary", "obrien")),
    ("VAN DER BERG, Jan", ("jan", "vanderberg")),
    ("COOK, Akleem", ("akleem", "cook")),
    ("SMITH, J", None),                 # initial-only forename — can't build an email
    ("SMITH", None),                    # no comma — not a person record
    ("ACME NOMINEES LIMITED", None),    # corporate officer
    ("", None),
])
def test_parse_name(raw, expected):
    assert dm.parse_name(raw) == expected


def test_email_permutations_are_ranked_and_capped(monkeypatch):
    monkeypatch.setattr(config, "DM_MAX_PATTERNS", 4)
    perms = dm.email_permutations("john", "smith", "acme.co.uk")
    assert perms[0] == "john.smith@acme.co.uk"   # most common pattern first
    assert len(perms) == 4
    assert all(p.endswith("@acme.co.uk") for p in perms)


# --------------------------------------------------------------------------- #
#  Officer storage — minimised, active-only, decision roles only
# --------------------------------------------------------------------------- #
def _lead(cur, cn=None, *, state="enriched"):
    cn = cn or f"DM_{uuid.uuid4().hex[:8]}"
    cur.execute(
        "insert into outreach.leads (company_number, company_name, company_type, "
        "subscriber_class, state) values (%s,%s,'ltd','corporate',%s)", (cn, cn, state))
    return cn


def test_store_officers_keeps_active_decision_makers_only(db_rollback):
    cur = db_rollback.cursor()
    cn = _lead(cur)
    items = [
        {"name": "SMITH, John", "officer_role": "director", "appointed_on": "2019-01-01"},
        {"name": "JONES, Mary", "officer_role": "secretary", "appointed_on": "2019-01-01"},
        {"name": "OLD, Pat", "officer_role": "director", "appointed_on": "2010-01-01",
         "resigned_on": "2015-01-01"},
        {"name": "GREEN, Sam", "officer_role": "llp-member", "appointed_on": "2020-01-01"},
    ]
    kept = dm.store_officers(cn, items, cur=cur)
    assert kept == 2                                     # director + llp-member
    names = {o["name"] for o in dm.get_officers(cn, cur=cur)}
    assert names == {"SMITH, John", "GREEN, Sam"}


def test_store_officers_does_not_persist_dob_or_address(db_rollback):
    """Data minimisation: Companies House returns partial DOB + correspondence address;
    we store neither. The table has no column for them, so this is structural — but the
    test pins the intent so a future 'let's also keep the address' is a conscious change."""
    cur = db_rollback.cursor()
    cols = {c: 1 for c in ("date_of_birth", "address", "dob")}
    cur.execute("select column_name from information_schema.columns "
                "where table_schema='outreach' and table_name='officers'")
    have = {r[0] for r in cur.fetchall()}
    assert not (have & set(cols))


def test_re_storing_officers_is_idempotent(db_rollback):
    cur = db_rollback.cursor()
    cn = _lead(cur)
    items = [{"name": "SMITH, John", "officer_role": "director", "appointed_on": "2019-01-01"}]
    dm.store_officers(cn, items, cur=cur)
    dm.store_officers(cn, items, cur=cur)
    assert len(dm.get_officers(cn, cur=cur)) == 1


# --------------------------------------------------------------------------- #
#  PSC + ranking — spending on the RIGHT person
# --------------------------------------------------------------------------- #
def test_psc_names_reads_only_active_individuals():
    """A holding company is not someone to email, and ceased control is not control."""
    items = [
        {"kind": "individual-person-with-significant-control",
         "name_elements": {"forename": "John", "surname": "Smith", "title": "Mr"},
         "natures_of_control": ["ownership-of-shares-75-to-100-percent"]},
        {"kind": "corporate-entity-person-with-significant-control",
         "name": "ACME HOLDINGS LIMITED"},
        {"kind": "individual-person-with-significant-control", "ceased_on": "2021-04-01",
         "name_elements": {"forename": "Pat", "surname": "Old"}},
        {"kind": "legal-person-person-with-significant-control", "name": "SOME TRUST"},
    ]
    assert dm.psc_names(items) == {("john", "smith")}


def test_psc_names_falls_back_to_the_display_name_without_a_title():
    """Not every filing carries name_elements; a title must not be read as a forename."""
    items = [{"kind": "individual-person-with-significant-control",
              "name": "Mr John Andrew Smith"}]
    assert dm.psc_names(items) == {("john", "smith")}


def test_the_psc_outranks_the_longest_serving_director(db_rollback):
    """The old ordering was `appointed_on` alone, so the retired co-founder won. Every
    downstream cost is spent on whoever ranks first, so this is the ordering that matters."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    items = [
        {"name": "OLD, Pat", "officer_role": "director", "appointed_on": "2001-01-01"},
        {"name": "SMITH, John", "officer_role": "director", "appointed_on": "2019-01-01"},
    ]
    dm.store_officers(cn, items, cur=cur, psc={("john", "smith")}, company_name="Acme Ltd")
    officers = dm.get_officers(cn, cur=cur)
    assert officers[0]["name"] == "SMITH, John"
    assert officers[0]["is_psc"] is True
    assert officers[1]["is_psc"] is False


def test_an_eponymous_surname_outranks_a_plain_director(db_rollback):
    """Family firms — 'J SMITH & SONS' — name their owner in the company name."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    items = [
        {"name": "BLOGGS, Joe", "officer_role": "director", "appointed_on": "2005-01-01"},
        {"name": "SMITH, John", "officer_role": "director", "appointed_on": "2019-01-01"},
    ]
    dm.store_officers(cn, items, cur=cur, company_name="J Smith & Sons Ltd")
    assert dm.get_officers(cn, cur=cur)[0]["name"] == "SMITH, John"


def test_occupation_breaks_a_tie_between_two_plain_directors(db_rollback):
    cur = db_rollback.cursor()
    cn = _lead(cur)
    items = [
        {"name": "BLOGGS, Joe", "officer_role": "director", "appointed_on": "2005-01-01",
         "occupation": "Electrician"},
        {"name": "GREEN, Sam", "officer_role": "director", "appointed_on": "2019-01-01",
         "occupation": "Managing Director"},
    ]
    dm.store_officers(cn, items, cur=cur, company_name="Acme Ltd")
    assert dm.get_officers(cn, cur=cur)[0]["name"] == "GREEN, Sam"


def test_a_corporate_officer_is_never_a_target(db_rollback):
    """An accountancy firm acting as director is not a person to write to."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    items = [
        {"name": "ACME NOMINEES LIMITED", "officer_role": "director",
         "appointed_on": "2019-01-01", "is_corporate_officer": True},
        {"name": "SMITH, John", "officer_role": "director", "appointed_on": "2020-01-01"},
    ]
    assert dm.store_officers(cn, items, cur=cur) == 1
    assert dm.get_officers(cn, cur=cur)[0]["name"] == "SMITH, John"


def test_re_storing_refreshes_the_rank(db_rollback):
    """`on conflict do nothing` would freeze a rank computed before PSC was known."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    items = [{"name": "SMITH, John", "officer_role": "director", "appointed_on": "2019-01-01"}]
    dm.store_officers(cn, items, cur=cur, company_name="Acme Ltd")
    assert dm.get_officers(cn, cur=cur)[0]["is_psc"] is False
    dm.store_officers(cn, items, cur=cur, psc={("john", "smith")}, company_name="Acme Ltd")
    officers = dm.get_officers(cn, cur=cur)
    assert len(officers) == 1 and officers[0]["is_psc"] is True


def test_a_psc_outage_defers_instead_of_freezing_a_wrong_rank(db_rollback):
    """P3 invariant: a stage that could not do its job writes nothing that removes the row
    from its own backlog. Storing officers with is_psc=false during a PSC outage would be
    permanent — _fetch_officers short-circuits on any stored row."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    ch = _FakeCH([{"name": "SMITH, John", "officer_role": "director"}], psc_raises=True)
    assert dm._fetch_officers(cn, cur=cur, ch=ch) is None
    cur.execute("select count(*) from outreach.officers where company_number=%s", (cn,))
    assert cur.fetchone()[0] == 0


def test_a_register_typo_still_matches_the_psc_when_unambiguous():
    """Real case (ABM Electrical Services): director filed "BARNES, Danile", the same human
    filed as PSC "Daniel Barnes"."""
    assert dm.match_psc({("daniel", "barnes")}, ["BARNES, Danile"]) == {"BARNES, Danile"}


def test_an_ambiguous_surname_never_guesses_which_sibling_is_the_psc():
    """Same company also has BARNES, Emma. Two officers sharing a surname is the FAMILY
    FIRM case — our commonest shape — so a surname-only match would routinely pick the
    wrong person. Only a unique (surname, initial) is honoured."""
    assert dm.match_psc({("daniel", "barnes")},
                        ["BARNES, Danile", "BARNES, Dominic"]) == set()
    # different initials — no ambiguity, so the typo fallback is still safe
    assert dm.match_psc({("daniel", "barnes")},
                        ["BARNES, Danile", "BARNES, Emma"]) == {"BARNES, Danile"}


def test_an_exact_match_never_needs_the_fallback():
    assert dm.match_psc({("john", "smith")}, ["SMITH, John", "SMITH, Jane"]) == {"SMITH, John"}


def test_a_places_lead_is_looked_up_by_its_MATCHED_company_number(db_rollback):
    """96% of our corporate leads are Places rows keyed 'PLACE:<place_id>', with the real
    register number in matched_company_number. Calling Companies House with the synthetic
    key 502s — silently, because the failure looks exactly like a CH outage."""
    cur = db_rollback.cursor()
    cn = f"PLACE:{uuid.uuid4().hex[:12]}"
    cur.execute(
        "insert into outreach.leads (company_number, company_name, company_type, "
        "subscriber_class, state, matched_company_number) "
        "values (%s,'Acme Electrical','ltd','corporate','enriched','07795943')", (cn,))
    assert dm.register_number(cn, cur=cur) == "07795943"

    asked = []

    class _Recording(_FakeCH):
        def get_officers(self, company_number, items=35):
            asked.append(company_number)
            return self._officers

        def get_psc(self, company_number, items=25):
            asked.append(company_number)
            return []

    dm._fetch_officers(cn, cur=cur,
                       ch=_Recording([{"name": "SMITH, John", "officer_role": "director"}]))
    assert asked == ["07795943", "07795943"]      # never the PLACE: key
    assert dm.get_officers(cn, cur=cur)[0]["name"] == "SMITH, John"


def test_a_companies_house_lead_is_looked_up_by_its_own_number(db_rollback):
    cur = db_rollback.cursor()
    cn = _lead(cur)                                # a plain, non-synthetic key
    assert dm.register_number(cn, cur=cur) == cn


def test_a_lead_with_no_register_number_completes_rather_than_deferring(db_rollback):
    """No number to ask about is a finished attempt, not an outage — [] not None, so it
    does not spin round the backlog for ever."""
    cur = db_rollback.cursor()
    cn = f"PLACE:{uuid.uuid4().hex[:12]}"
    cur.execute(
        "insert into outreach.leads (company_number, company_name, company_type, "
        "subscriber_class, state) values (%s,'Acme','ltd','corporate','enriched')", (cn,))
    assert dm.register_number(cn, cur=cur) is None
    assert dm._fetch_officers(cn, cur=cur, ch=_FakeCH([])) == []


def test_store_officers_does_not_persist_psc_ownership_detail(db_rollback):
    """Minimisation: is_psc is a BOOLEAN. natures_of_control is ownership-band data we do
    not need to answer 'is this the owner', so there is nowhere to put it."""
    cur = db_rollback.cursor()
    cur.execute("select column_name from information_schema.columns "
                "where table_schema='outreach' and table_name='officers'")
    have = {r[0] for r in cur.fetchall()}
    assert not (have & {"natures_of_control", "nature_of_control", "nationality",
                        "country_of_residence", "date_of_birth", "address"})
    assert "is_psc" in have


# --------------------------------------------------------------------------- #
#  resolve_one — the confirm-or-nothing contract
# --------------------------------------------------------------------------- #
class _FakeCH:
    def __init__(self, officers, psc=None, *, psc_raises=False):
        self._officers = officers
        self._psc = psc or []
        self._psc_raises = psc_raises

    def get_officers(self, company_number, items=35):
        return self._officers

    def get_psc(self, company_number, items=25):
        if self._psc_raises:
            raise RuntimeError("CH 502 on PSC")
        return self._psc


def _enriched(cur, cn, *, domain="acme.co.uk", tier="verified", result="ok",
              email="info@acme.co.uk"):
    cur.execute(
        "insert into outreach.enrichment (company_number, domain, contact_email, "
        "contact_tier, email_verify_result) values (%s,%s,%s,%s,%s)",
        (cn, domain, email, tier, result))


def test_a_confirmed_permutation_is_adopted_as_the_named_contact(db_rollback):
    cur = db_rollback.cursor()
    cn = _lead(cur)
    _enriched(cur, cn)
    ch = _FakeCH([{"name": "SMITH, John", "officer_role": "director"}])
    # verifier says the second permutation (john@) is real
    def verifier(addr):
        return (addr == "john@acme.co.uk", "ok" if addr == "john@acme.co.uk" else "invalid")

    r = dm.resolve_one(cn, "acme.co.uk", cur=cur, ch=ch, verifier=verifier)
    assert r["verified"] and r["named_email"] == "john@acme.co.uk"
    cur.execute("select contact_email, contact_name, contact_tier from outreach.enrichment "
                "where company_number=%s", (cn,))
    assert cur.fetchone() == ("john@acme.co.uk", "SMITH, John", "named")


def test_no_confirmation_leaves_the_role_address_untouched(db_rollback):
    """The whole safety rule: never send to a guess. If nothing verifies, the role
    address stays exactly as it was."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    _enriched(cur, cn)
    ch = _FakeCH([{"name": "SMITH, John", "officer_role": "director"}])
    r = dm.resolve_one(cn, "acme.co.uk", cur=cur, ch=ch, verifier=lambda a: (False, "invalid"))
    assert not r["verified"] and r["named_email"] is None
    cur.execute("select contact_email, contact_tier, contact_name from outreach.enrichment "
                "where company_number=%s", (cn,))
    assert cur.fetchone() == ("info@acme.co.uk", "verified", None)


def test_catch_all_domain_is_skipped_without_spending(db_rollback):
    """On a catch-all domain no permutation can be confirmed, so verifying any is pure
    waste — the lead is skipped before a single MV call."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    _enriched(cur, cn, tier="risky", result="catch_all")
    ch = _FakeCH([{"name": "SMITH, John", "officer_role": "director"}])

    def verifier(addr):
        raise AssertionError("must not verify on a catch-all domain")

    r = dm.resolve_one(cn, "acme.co.uk", cur=cur, ch=ch, verifier=verifier)
    assert r["named_email"] is None and "catch-all" in r["skipped"]


def test_a_verifier_outage_defers_after_one_probe(db_rollback):
    """A dead verifier must not be hammered once per permutation, and its non-answer is
    not 'this person has no email'."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    _enriched(cur, cn)
    ch = _FakeCH([{"name": "SMITH, John", "officer_role": "director"},
                  {"name": "JONES, Mary", "officer_role": "director"}])
    calls = {"n": 0}

    def verifier(addr):
        calls["n"] += 1
        return (False, "error")

    r = dm.resolve_one(cn, "acme.co.uk", cur=cur, ch=ch, verifier=verifier)
    assert r.get("deferred") and calls["n"] == 1     # stopped after the first non-answer
    cur.execute("select contact_tier from outreach.enrichment where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "verified"           # role address preserved


def test_officers_are_stored_even_when_the_email_cannot_be_confirmed(db_rollback):
    """The free CRM win survives a verifier outage — directors on file regardless."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    _enriched(cur, cn)
    ch = _FakeCH([{"name": "SMITH, John", "officer_role": "director"}])
    dm.resolve_one(cn, "acme.co.uk", cur=cur, ch=ch, verifier=lambda a: (False, "error"))
    assert dm.get_officers(cn, cur=cur)[0]["name"] == "SMITH, John"


def test_the_verify_cap_bounds_mv_spend(db_rollback, monkeypatch):
    cur = db_rollback.cursor()
    cn = _lead(cur)
    _enriched(cur, cn)
    monkeypatch.setattr(config, "DM_MAX_VERIFY_PER_LEAD", 3)
    ch = _FakeCH([{"name": "SMITH, John", "officer_role": "director"},
                  {"name": "JONES, Mary", "officer_role": "director"}])
    calls = {"n": 0}

    def verifier(addr):
        calls["n"] += 1
        return (False, "invalid")

    dm.resolve_one(cn, "acme.co.uk", cur=cur, ch=ch, verifier=verifier)
    assert calls["n"] == 3


def test_run_is_off_by_default(db_rollback, monkeypatch):
    monkeypatch.setattr(config, "DM_ENABLED", False)
    assert dm.run(cur=db_rollback.cursor()) == {"skipped": "DECISION_MAKER_ENABLED off"}


def test_a_deferred_lead_is_retried_next_tick(db_rollback):
    """The outage bug: if the verifier is down when officers are first fetched, the
    lookup must NOT be marked done — else the lead is excluded from the backlog for
    ever and its email is never resolved once the verifier recovers."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    _enriched(cur, cn)
    ch = _FakeCH([{"name": "SMITH, John", "officer_role": "director"}])
    dm.resolve_one(cn, "acme.co.uk", cur=cur, ch=ch, verifier=lambda a: (False, "error"))
    cur.execute("select dm_attempted_at from outreach.enrichment where company_number=%s", (cn,))
    assert cur.fetchone()[0] is None                 # deferred -> still eligible
    cur.execute(dm._BACKLOG_SQL, (10,))
    assert cn in {r[0] for r in cur.fetchall()}


def test_a_completed_attempt_is_not_retried(db_rollback):
    """The other half: a lead we genuinely checked and couldn't confirm must be marked
    done, or every tick re-verifies the same permutations and re-bills MillionVerifier."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    _enriched(cur, cn)
    ch = _FakeCH([{"name": "SMITH, John", "officer_role": "director"}])
    dm.resolve_one(cn, "acme.co.uk", cur=cur, ch=ch, verifier=lambda a: (False, "invalid"))
    cur.execute("select dm_attempted_at from outreach.enrichment where company_number=%s", (cn,))
    assert cur.fetchone()[0] is not None             # completed -> excluded
    cur.execute(dm._BACKLOG_SQL, (10,))
    assert cn not in {r[0] for r in cur.fetchall()}


class _BrokenCH:
    def get_officers(self, company_number, items=35):
        raise RuntimeError("CH 502")


def test_companies_house_outage_defers_without_marking_done(db_rollback):
    """A transient CH failure must not be recorded as a completed attempt, or the lead's
    officers are never fetched once CH recovers."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    _enriched(cur, cn)
    r = dm.resolve_one(cn, "acme.co.uk", cur=cur, ch=_BrokenCH(), verifier=lambda a: (True, "ok"))
    assert r.get("deferred") and r["officers"] == 0
    cur.execute("select dm_attempted_at from outreach.enrichment where company_number=%s", (cn,))
    assert cur.fetchone()[0] is None
    cur.execute(dm._BACKLOG_SQL, (10,))
    assert cn in {r[0] for r in cur.fetchall()}


def test_genuinely_no_officers_is_a_completed_attempt(db_rollback):
    """CH answering with an empty list IS terminal — don't retry a company that has no
    listed active officers every tick for ever."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    _enriched(cur, cn)
    r = dm.resolve_one(cn, "acme.co.uk", cur=cur, ch=_FakeCH([]), verifier=lambda a: (True, "ok"))
    assert not r.get("deferred") and r["officers"] == 0
    cur.execute("select dm_attempted_at from outreach.enrichment where company_number=%s", (cn,))
    assert cur.fetchone()[0] is not None
