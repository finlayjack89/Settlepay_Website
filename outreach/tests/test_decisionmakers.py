import json
import uuid

import pytest

from outreach import config, decisionmakers as dm, facts

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
#  Display formatting — this name is printed in the email itself
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("SMITH, John Andrew", "John Smith"),          # middle names dropped
    ("PARRY-WILLIAMS, Jamie", "Jamie Parry-Williams"),
    ("O'BRIEN, Mary", "Mary O'Brien"),
    ("MCDONALD, Ian", "Ian McDonald"),             # Mc is always capitalised after
    # 'Mac' is deliberately NOT special-cased: Mackie and MacDonald are both real and
    # nothing in the string tells them apart, so we keep what the register filed
    ("MACKIE, David", "David Mackie"),
    # REAL filing (1314 Electrical Services): a SECOND comma. partition() splits only the
    # first, so the forename arrived as "James," and the line read "FAO James, Thomson".
    ("THOMSON, James, Noble", "James Thomson"),
    ("SMITH, J", None),                            # an initial is not a name to greet
    ("ACME NOMINEES LIMITED", None),
    ("", None),
])
def test_display_name(raw, expected):
    assert dm.display_name(raw) == expected


def test_display_role_prefers_how_they_describe_themselves():
    assert dm.display_role({"occupation": "Managing Director", "role": "director"}) \
        == "Managing Director"
    assert dm.display_role({"occupation": None, "role": "director"}) == "Director"
    assert dm.display_role({"occupation": "N/A", "role": "llp-member"}) == "Member"
    assert dm.display_role({"occupation": None, "role": "unknown-role"}) is None


# --------------------------------------------------------------------------- #
#  The FAO tier — a shared mailbox is a RESULT, not a failure
# --------------------------------------------------------------------------- #
def test_fao_is_not_applied_to_a_personal_mailbox(db_rollback):
    """Someone whose own address we hold needs no 'FAO' line."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    _enriched(cur, cn, email="sarah@acme.co.uk")
    assert dm.adopt_fao_contact(cn, {"name": "SMITH, John", "role": "director"},
                                cur=cur) is False


def test_fao_is_not_applied_to_a_catch_all_mailbox(db_rollback):
    """A 'risky' address is refused at send, so naming an addressee on it changes
    nothing and would overstate what we have."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    _enriched(cur, cn, tier="risky", result="catch_all")
    assert dm.adopt_fao_contact(cn, {"name": "SMITH, John", "role": "director"},
                                cur=cur) is False


def test_fao_records_the_name_and_role_as_verified_constants(db_rollback):
    """The drafter may only name what the FACTS block resolved, so the FAO line is only
    writable if it lands there with provenance."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    _enriched(cur, cn)
    assert dm.adopt_fao_contact(
        cn, {"name": "SMITH, John", "role": "director",
             "occupation": "Managing Director"}, cur=cur) is True
    cur.execute("select facts from outreach.enrichment where company_number=%s", (cn,))
    block = facts.loads(cur.fetchone()[0])
    assert block["contact_name"].value == "John Smith"
    assert block["contact_name"].source == "companies_house_officer"
    assert block["contact_name"].verified is True
    assert block["contact_role"].value == "Managing Director"


def test_fao_uses_the_top_ranked_officer(db_rollback):
    """The owner, not whoever the register listed first."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    _enriched(cur, cn)
    ch = _FakeCH(
        [{"name": "OLD, Pat", "officer_role": "director", "appointed_on": "2001-01-01"},
         {"name": "SMITH, John", "officer_role": "director", "appointed_on": "2019-01-01"}],
        psc=[{"kind": "individual-person-with-significant-control",
              "name_elements": {"forename": "John", "surname": "Smith"}}])
    r = dm.resolve_one(cn, "acme.co.uk", cur=cur, ch=ch,
                       verifier=lambda a: (False, "invalid"))
    assert r["fao_applied"] is True
    cur.execute("select contact_name from outreach.enrichment where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "John Smith"


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
    filed as PSC "Daniel Barnes". The PSC spelling comes back so it can be preferred."""
    assert dm.match_psc({("daniel", "barnes")}, ["BARNES, Danile"]) == {
        "BARNES, Danile": ("daniel", "barnes")}


def test_an_ambiguous_surname_never_guesses_which_sibling_is_the_psc():
    """Same company also has BARNES, Emma. Two officers sharing a surname is the FAMILY
    FIRM case — our commonest shape — so a surname-only match would routinely pick the
    wrong person. Only a unique (surname, initial) is honoured."""
    assert dm.match_psc({("daniel", "barnes")},
                        ["BARNES, Danile", "BARNES, Dominic"]) == {}
    # different initials — no ambiguity, so the typo fallback is still safe
    assert dm.match_psc({("daniel", "barnes")},
                        ["BARNES, Danile", "BARNES, Emma"]) == {
        "BARNES, Danile": ("daniel", "barnes")}


def test_an_exact_match_never_needs_the_fallback():
    """An exact match maps to None — there is no better spelling to prefer."""
    assert dm.match_psc({("john", "smith")}, ["SMITH, John", "SMITH, Jane"]) == {
        "SMITH, John": None}


def test_the_psc_spelling_wins_when_the_register_contradicts_itself(db_rollback):
    """"Danile" is not a name and "Daniel" is, and this string is printed in the first
    line of a cold email. Caught by running the real chain on ABM Electrical Services."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    dm.store_officers(cn, [{"name": "BARNES, Danile", "officer_role": "director"}],
                      cur=cur, psc={("daniel", "barnes")}, company_name="ABM Electrical")
    off = dm.get_officers(cn, cur=cur)[0]
    assert off["name"] == "Barnes, Daniel" and off["is_psc"] is True
    assert dm.display_name(off["name"]) == "Daniel Barnes"


def test_an_officer_who_is_not_a_psc_keeps_the_register_spelling(db_rollback):
    """We only overrule a filing when a SECOND filing about the same person disagrees."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    dm.store_officers(cn, [{"name": "SMYTHE, Jhon", "officer_role": "director"}],
                      cur=cur, company_name="Acme")
    assert dm.get_officers(cn, cur=cur)[0]["name"] == "SMYTHE, Jhon"


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
              email="info@acme.co.uk", candidates=None):
    """`candidates` are the addresses the scraper found on the site. A PERSONAL one is
    what proves the domain's email convention — without it there is no confirmed pattern
    and, by design, no derivation at all."""
    cur.execute(
        "insert into outreach.enrichment (company_number, domain, contact_email, "
        "contact_tier, email_verify_result, scraped) values (%s,%s,%s,%s,%s,%s)",
        (cn, domain, email, tier, result,
         json.dumps({"candidates": candidates}) if candidates is not None else None))


# a published personal address on the same domain: proves the pattern is {first}.{last}
_PATTERN_PROOF = ["info@acme.co.uk", "mary.jones@acme.co.uk"]
_PROOF_OFFICERS = [{"name": "SMITH, John", "officer_role": "director",
                    "appointed_on": "2019-01-01"},
                   {"name": "JONES, Mary", "officer_role": "director",
                    "appointed_on": "2020-01-01"}]


def test_a_pattern_confirmed_address_is_adopted_as_the_named_contact(db_rollback):
    """mary.jones@ published next to officer JONES, Mary proves {first}.{last}, so
    john.smith@ is an application of a known rule rather than a guess."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    _enriched(cur, cn, candidates=_PATTERN_PROOF)
    ch = _FakeCH(_PROOF_OFFICERS)
    tried = []

    def verifier(addr):
        tried.append(addr)
        return (addr == "john.smith@acme.co.uk",
                "ok" if addr == "john.smith@acme.co.uk" else "invalid")

    r = dm.resolve_one(cn, "acme.co.uk", cur=cur, ch=ch, verifier=verifier)
    assert r["verified"] and r["named_email"] == "john.smith@acme.co.uk"
    assert r["pattern"] == "{first}.{last}" and r["method"] == "derived"
    cur.execute("select contact_email, contact_name, contact_tier, contact_method "
                "from outreach.enrichment where company_number=%s", (cn,))
    # the name is stored as a human writes it, not as the register shouts it: it is read
    # by the drafter, shown in the console, and printed in the email in the FAO case
    assert cur.fetchone() == ("john.smith@acme.co.uk", "John Smith", "named", "derived")


def test_no_pattern_means_no_derivation_and_no_spend(db_rollback):
    """The policy change: with only info@ published, nothing proves the convention, so we
    do not try four guesses — we try none, and fall to the FAO tier."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    _enriched(cur, cn, candidates=["info@acme.co.uk"])
    ch = _FakeCH(_PROOF_OFFICERS)

    def verifier(addr):
        raise AssertionError(f"must not verify without a confirmed pattern: {addr}")

    r = dm.resolve_one(cn, "acme.co.uk", cur=cur, ch=ch, verifier=verifier)
    assert r["checked"] == 0 and "no confirmed email pattern" in r["skipped"]
    assert r["fao_applied"] is True          # not a failure — a different, safer outcome


def test_a_published_personal_address_is_preferred_over_deriving_one(db_rollback):
    """§7: an address they published is not the speculative act. It is still verified
    before use, but it is theirs — so it is tried first and costs one call."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    _enriched(cur, cn, candidates=["info@acme.co.uk", "j.smith@acme.co.uk"])
    ch = _FakeCH([{"name": "SMITH, John", "officer_role": "director"}])
    tried = []

    def verifier(addr):
        tried.append(addr)
        return (True, "ok")

    r = dm.resolve_one(cn, "acme.co.uk", cur=cur, ch=ch, verifier=verifier)
    assert r["method"] == "sourced" and r["named_email"] == "j.smith@acme.co.uk"
    assert tried == ["j.smith@acme.co.uk"]           # one call, and never a guess
    cur.execute("select contact_method from outreach.enrichment where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "sourced"


def test_a_second_lead_on_the_same_domain_is_not_re_billed(db_rollback):
    """dm_attempted_at marks a LEAD done, but what we buy is 'does <name> exist at
    <domain>'. Two leads can share a domain — a group, a franchise, the same business
    found twice — and each would otherwise pay for the same answer."""
    cur = db_rollback.cursor()
    calls = []

    def verifier(addr):
        calls.append(addr)
        return (False, "invalid")

    for _ in range(2):
        cn = _lead(cur)
        _enriched(cur, cn, candidates=_PATTERN_PROOF)
        dm.resolve_one(cn, "acme.co.uk", cur=cur, ch=_FakeCH(_PROOF_OFFICERS),
                       verifier=verifier)
    # lead 1 asks two distinct questions (Mary's published address, then John by pattern);
    # lead 2 asks none, because both answers are already on file
    assert calls == ["mary.jones@acme.co.uk", "john.smith@acme.co.uk"]


def test_a_cached_hit_is_adopted_without_paying_again(db_rollback):
    cur = db_rollback.cursor()
    cn = _lead(cur)
    _enriched(cur, cn, candidates=_PATTERN_PROOF)
    # both answers already known: Mary's published address is dead, John's works
    dm.remember_lookup("mary", "jones", "acme.co.uk", "miss", cur=cur)
    dm.remember_lookup("john", "smith", "acme.co.uk", "hit", cur=cur,
                       address="john.smith@acme.co.uk")

    def verifier(addr):
        raise AssertionError("must not re-verify a cached answer")

    r = dm.resolve_one(cn, "acme.co.uk", cur=cur, ch=_FakeCH(_PROOF_OFFICERS),
                       verifier=verifier)
    assert r["verified"] and r.get("cached") is True
    cur.execute("select contact_email from outreach.enrichment where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "john.smith@acme.co.uk"


def test_a_verifier_outage_is_never_cached(db_rollback):
    """Caching a non-answer would turn one outage into 90 days of skipped lookups — the
    same mistake TRANSIENT_RESULTS exists to prevent."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    _enriched(cur, cn, candidates=_PATTERN_PROOF)
    dm.resolve_one(cn, "acme.co.uk", cur=cur,
                   ch=_FakeCH([{"name": "SMITH, John", "officer_role": "director"}]),
                   verifier=lambda a: (False, "error"))
    assert dm.lookup_cached("john", "smith", "acme.co.uk", cur=cur) is None


def test_decision_maker_status_counts_a_shared_mailbox_as_addressed(db_rollback):
    """addressed_rate is the metric that matters: can we name a human in the email. A
    shared mailbox addressed to the named director counts; an anonymous one does not."""
    from outreach import stats
    cur = db_rollback.cursor()
    before = stats.decision_maker_status(cur)
    cn = _lead(cur)
    _enriched(cur, cn)
    dm.adopt_fao_contact(cn, {"name": "SMITH, John", "role": "director"}, cur=cur)
    after = stats.decision_maker_status(cur)
    assert after["fao"] == before["fao"] + 1
    assert after["role_only"] == before["role_only"]        # reclassified, not added
    assert after["named"] == before["named"]                # still not a personal mailbox


def test_the_buy_thresholds_are_computed_not_asserted(db_rollback):
    """The doc's thresholds only mean something against our own numbers."""
    from outreach import stats
    d = stats.decision_maker_status(db_rollback.cursor())
    assert d["buy_catch_all_resolver"] is (d["catch_all_rate"] > 60)
    assert 0 <= d["addressed_rate"] <= 100


def test_a_generic_address_never_proves_a_pattern():
    """info@ is true of every convention, so it must reveal nothing (research doc §4)."""
    assert dm.infer_pattern(["info@acme.co.uk", "sales@acme.co.uk"],
                            _PROOF_OFFICERS, "acme.co.uk") is None
    assert dm.infer_pattern(["mary.jones@acme.co.uk"],
                            _PROOF_OFFICERS, "acme.co.uk") == "{first}.{last}"


def test_a_pattern_on_someone_elses_domain_is_ignored():
    """A supplier's address on the page says nothing about THIS domain's convention."""
    assert dm.infer_pattern(["mary.jones@supplier.co.uk"],
                            _PROOF_OFFICERS, "acme.co.uk") is None


def test_no_confirmation_leaves_the_role_ADDRESS_untouched_but_names_the_addressee(db_rollback):
    """The whole safety rule: never send to a guess. If nothing verifies, the address we
    send TO is byte-for-byte what it was.

    What changes is only WHO it is addressed to. The register told us who runs the firm
    for free, and discarding that because a paid inference failed is the inversion this
    phase exists to correct — the mailbox is unchanged, the envelope is not a guess, and
    the draft can now say FAO John Smith."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    _enriched(cur, cn)
    ch = _FakeCH([{"name": "SMITH, John", "officer_role": "director"}])
    r = dm.resolve_one(cn, "acme.co.uk", cur=cur, ch=ch, verifier=lambda a: (False, "invalid"))
    assert not r["verified"] and r["named_email"] is None
    assert r["fao_applied"] is True
    cur.execute("select contact_email, contact_tier, contact_name from outreach.enrichment "
                "where company_number=%s", (cn,))
    assert cur.fetchone() == ("info@acme.co.uk", "role_fao", "John Smith")


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
    _enriched(cur, cn, candidates=_PATTERN_PROOF)
    ch = _FakeCH(_PROOF_OFFICERS)
    calls = {"n": 0}

    def verifier(addr):
        calls["n"] += 1
        return (False, "error")

    r = dm.resolve_one(cn, "acme.co.uk", cur=cur, ch=ch, verifier=verifier)
    assert r.get("deferred") and calls["n"] == 1     # stopped after the first non-answer
    cur.execute("select contact_email, contact_tier from outreach.enrichment "
                "where company_number=%s", (cn,))
    email, tier = cur.fetchone()
    # The MAILBOX is preserved — nothing was adopted from a verifier that never answered.
    # The FAO name is free register data, independent of the outage, so the lead still
    # gains an addressee while it waits to be retried.
    assert email == "info@acme.co.uk" and tier == "role_fao"


def test_officers_are_stored_even_when_the_email_cannot_be_confirmed(db_rollback):
    """The free CRM win survives a verifier outage — directors on file regardless."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    _enriched(cur, cn)
    ch = _FakeCH([{"name": "SMITH, John", "officer_role": "director"}])
    dm.resolve_one(cn, "acme.co.uk", cur=cur, ch=ch, verifier=lambda a: (False, "error"))
    assert dm.get_officers(cn, cur=cur)[0]["name"] == "SMITH, John"


def test_the_verify_cap_bounds_mv_spend(db_rollback, monkeypatch):
    """One call per officer now, not one per permutation — but the cap is still the hard
    ceiling on what a single lead can spend."""
    cur = db_rollback.cursor()
    cn = _lead(cur)
    _enriched(cur, cn, candidates=_PATTERN_PROOF)
    monkeypatch.setattr(config, "DM_MAX_VERIFY_PER_LEAD", 3)
    ch = _FakeCH([{"name": "SMITH, John", "officer_role": "director",
                   "appointed_on": "2001-01-01"},
                  {"name": "JONES, Mary", "officer_role": "director",
                   "appointed_on": "2002-01-01"},
                  {"name": "GREEN, Sam", "officer_role": "director",
                   "appointed_on": "2003-01-01"}])
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
    _enriched(cur, cn, candidates=_PATTERN_PROOF)
    ch = _FakeCH(_PROOF_OFFICERS)
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


def test_the_chosen_contact_counts_as_a_published_address(db_rollback):
    """`candidates` only exists on rows enriched after it was added, so on every older row
    published_candidates returned [] and no officer could be matched — while the address
    we had already chosen sat there, published, plainly theirs. Live case: contact
    damianabel@burnapandabel.co.uk, register says ABEL, Damian Nicholas, lead came out
    with no name on it."""
    import uuid

    from outreach import decisionmakers

    cur = db_rollback.cursor()
    cn = f"PUB_{uuid.uuid4().hex[:8]}"
    cur.execute("insert into outreach.leads (company_number, company_name, company_type, "
                "subscriber_class, state) values (%s,'Burnap Test Ltd','ltd','corporate',"
                "'enriched')", (cn,))
    cur.execute("insert into outreach.enrichment (company_number, domain, contact_email, "
                "contact_tier, scraped) values (%s,'burnaptest.co.uk',"
                "'damianabel@burnaptest.co.uk','verified',%s::jsonb)",
                (cn, '{"candidates": null}'))

    assert decisionmakers.published_candidates(cn, cur=cur) == ["damianabel@burnaptest.co.uk"]
    officer = {"name": "ABEL, Damian Nicholas"}
    assert decisionmakers.sourced_address(cn, officer, "burnaptest.co.uk", cur=cur) == \
        "damianabel@burnaptest.co.uk"


def test_the_chosen_contact_is_not_duplicated_when_already_a_candidate(db_rollback):
    import uuid

    from outreach import decisionmakers

    cur = db_rollback.cursor()
    cn = f"PUB_{uuid.uuid4().hex[:8]}"
    cur.execute("insert into outreach.leads (company_number, company_name, company_type, "
                "subscriber_class, state) values (%s,'Dup Test Ltd','ltd','corporate',"
                "'enriched')", (cn,))
    cur.execute("insert into outreach.enrichment (company_number, domain, contact_email, "
                "contact_tier, scraped) values (%s,'dup.co.uk','info@dup.co.uk','verified',"
                "%s::jsonb)", (cn, '{"candidates": ["info@dup.co.uk", "sam@dup.co.uk"]}'))

    got = decisionmakers.published_candidates(cn, cur=cur)
    assert sorted(got) == ["info@dup.co.uk", "sam@dup.co.uk"]
