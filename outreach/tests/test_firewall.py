import uuid

import pytest

from outreach import firewall
from outreach.states import SubscriberClass

pytestmark = pytest.mark.floor_c


# ---- classifier fixtures (pure; no DB) ----
@pytest.mark.parametrize("company_type,expected", [
    ("ltd", SubscriberClass.CORPORATE),
    ("plc", SubscriberClass.CORPORATE),
    ("llp", SubscriberClass.CORPORATE),
    ("scottish-partnership", SubscriberClass.CORPORATE),
    ("community-interest-company", SubscriberClass.CORPORATE),
    ("limited-partnership", SubscriberClass.INDIVIDUAL),
    (None, SubscriberClass.UNKNOWN),
    ("", SubscriberClass.UNKNOWN),
    ("sole-trader", SubscriberClass.UNKNOWN),       # not on the allowlist -> fail-safe
    ("something-new-2027", SubscriberClass.UNKNOWN),  # unrecognised -> fail-safe
])
def test_classify(company_type, expected):
    assert firewall.classify(company_type) == expected


def test_individual_and_unknown_are_never_corporate():
    # the only contactable class is corporate; everything else must be suppressed upstream
    for ct in (None, "", "limited-partnership", "mystery"):
        assert firewall.classify(ct) is not SubscriberClass.CORPORATE


# ---- check_suppression (DB, rolled back -> no persistence) ----
def test_suppression_hit_via_suppressions_table(db_rollback):
    cur = db_rollback.cursor()
    email = f"sup-{uuid.uuid4().hex}@example.com"
    assert firewall.check_suppression(email=email, cur=cur) is False
    cur.execute("insert into outreach.suppressions (email, reason) values (%s, 'test')", (email,))
    assert firewall.check_suppression(email=email, cur=cur) is True


def test_existing_enquirer_is_suppressed(db_rollback):
    # seed an inbound enquirer in public.<ENQUIRY_SOURCE_TABLE> within the rolled-back
    # transaction (never committed -> the website's data is untouched)
    from outreach import config
    cur = db_rollback.cursor()
    email = f"enquirer-{uuid.uuid4().hex}@example.com"
    assert firewall.check_suppression(email=email, cur=cur) is False
    cur.execute(
        f"insert into public.{config.ENQUIRY_SOURCE_TABLE} "
        "(business, name, email, message) values ('test co', 'test', %s, 'test')",
        (email,),
    )
    assert firewall.check_suppression(email=email, cur=cur) is True


def test_unknown_email_not_suppressed(db_rollback):
    cur = db_rollback.cursor()
    assert firewall.check_suppression(email=f"nobody-{uuid.uuid4().hex}@example.com", cur=cur) is False


def test_firewall_hard_suppresses_individual_and_unknown(db_rollback):
    # seed one of each class, run the firewall in this rolled-back transaction,
    # and assert individual/unknown are suppressed (never contactable) with audit trail.
    cur = db_rollback.cursor()
    seeds = [("FWT_CORP", "ltd"), ("FWT_INDIV", "limited-partnership"), ("FWT_UNK", None)]
    for cn, ct in seeds:
        cur.execute(
            "insert into outreach.leads (company_number, company_name, company_type, state) "
            "values (%s, %s, %s, 'discovered')",
            (cn, cn, ct),
        )
    firewall.run(cur=cur)
    cur.execute(
        "select company_number, subscriber_class::text, state::text from outreach.leads "
        "where company_number in ('FWT_CORP','FWT_INDIV','FWT_UNK')"
    )
    got = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    assert got["FWT_CORP"] == ("corporate", "discovered")     # contactable
    assert got["FWT_INDIV"] == ("individual", "suppressed")   # never contactable
    assert got["FWT_UNK"] == ("unknown", "suppressed")        # fail-safe
    cur.execute(
        "select count(*) from outreach.suppressions where company_number in ('FWT_INDIV','FWT_UNK')"
    )
    assert cur.fetchone()[0] == 2
    cur.execute(
        "select count(*) from outreach.audit_log "
        "where company_number='FWT_INDIV' and event='suppressed' and lawful_basis='legitimate interests'"
    )
    assert cur.fetchone()[0] == 1
    # db_rollback rolls everything back -> no persistence
