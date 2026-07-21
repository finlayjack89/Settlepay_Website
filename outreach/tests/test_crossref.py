"""Corporate cross-reference — the PECR gate. Hermetic (fake CH client). The
load-bearing property: only a CONFIDENT ACTIVE-corporate match is sendable; sole
traders / unmatched / dissolved fail-closed to research-only."""
import uuid

import pytest

from outreach import crossref
from outreach.firewall import SubscriberClass

pytestmark = pytest.mark.floor_c


class _FakeCH:
    def __init__(self, items):
        self._items = items

    def search_companies(self, q, *, items=5):
        return self._items

    def close(self):
        pass


def _item(title, number, ctype="ltd", status="active", postcode="LS21 1AA"):
    return {"title": title, "company_number": number, "company_type": ctype,
            "company_status": status, "address": {"postal_code": postcode}}


def test_confident_corporate_match_is_sendable():
    ch = _FakeCH([_item("Ridgeway Plumbing Ltd", "12345678")])
    cls, number, _ = crossref.match_company(ch, "Ridgeway Plumbing", "LS21 1AA")
    assert cls is SubscriberClass.CORPORATE and number == "12345678"


def test_no_match_fails_closed_to_unknown():
    ch = _FakeCH([_item("Completely Different Co Ltd", "99999999", postcode="EC1A 1BB")])
    cls, number, _ = crossref.match_company(ch, "247 Sparky", "LS29 8DE")
    assert cls is SubscriberClass.UNKNOWN and number is None


def test_dissolved_corporate_is_not_sendable():
    ch = _FakeCH([_item("Ridgeway Plumbing Ltd", "12345678", status="dissolved")])
    cls, number, _ = crossref.match_company(ch, "Ridgeway Plumbing", "LS21 1AA")
    assert cls is SubscriberClass.UNKNOWN     # matched but inactive → research-only


def test_name_match_without_postcode_needs_high_similarity():
    # same name, WRONG postcode → only classifies if name ratio clears the higher bar
    ch = _FakeCH([_item("Ridgeway Plumbing Ltd", "12345678", postcode="ZZ99 9ZZ")])
    cls, _, _ = crossref.match_company(ch, "Ridgeway Plumbing Limited", "LS21 1AA")
    assert cls is SubscriberClass.CORPORATE   # near-identical name clears NAME_ONLY


def test_ch_search_error_fails_closed():
    class Boom:
        def search_companies(self, q, *, items=5):
            raise RuntimeError("ch down")
    cls, number, _ = crossref.match_company(Boom(), "Anything", "LS1 1AA")
    assert cls is SubscriberClass.UNKNOWN and number is None


def test_run_updates_places_leads(db_rollback):
    cur = db_rollback.cursor()
    pid = uuid.uuid4().hex[:10]
    # run() takes the oldest `limit` pending Places leads; the live DB holds real ones,
    # so pin this lead as unambiguously oldest and take exactly it — otherwise the batch
    # fills with production rows and this test's assertions describe someone else's data.
    cur.execute("insert into outreach.leads (company_number, company_name, registered_address, "
                "state, source, place_id, created_at) values "
                "(%s,%s,%s::jsonb,'discovered','places',%s,'1990-01-01')",
                (f"PLACE:{pid}", "Norton Plumbing", '{"postcode":"LS21 1AA"}', pid))
    ch = _FakeCH([_item("Norton Plumbing", "09055451")])
    counts = crossref.run(limit=1, cur=cur, ch=ch)
    assert counts["corporate"] == 1
    cur.execute("select subscriber_class::text, matched_company_number from outreach.leads "
                "where place_id=%s", (pid,))
    cls, matched = cur.fetchone()
    assert cls == "corporate" and matched == "09055451"
