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


def test_a_register_outage_leaves_the_row_untouched_for_a_retry(db_rollback):
    """Fail-closed and fail-PERMANENT are not the same thing. A CH 429/timeout returned
    UNKNOWN, and run() wrote it along with crossref_checked_at — but the backlog selects
    on `subscriber_class is null`, so the row was never revisited. At 50 leads a tick,
    one bad minute condemned thousands of perfectly good leads to research-only with
    nothing surfaced anywhere."""
    import uuid

    from outreach import crossref

    cur = db_rollback.cursor()
    cn = f"PLACE:xref{uuid.uuid4().hex[:8]}"
    cur.execute("insert into outreach.leads (company_number, company_name, source, state) "
                "values (%s,'Acme Ltd','places','discovered')", (cn,))

    class _DeadCH:
        def search_companies(self, *a, **k):
            raise RuntimeError("429 Too Many Requests")

        def close(self):
            pass

    res = crossref.run(limit=5, cur=cur, ch=_DeadCH())
    assert res["deferred"] >= 1 and res["unknown"] == 0

    cur.execute("select subscriber_class, crossref_checked_at "
                "from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone() == (None, None)       # untouched, so the backlog retries it


def test_only_a_lookup_failure_is_flagged_unavailable():
    """The deferral must not become a way for genuinely unmatched leads to be re-checked
    for ever — "we asked and found nothing" is a conclusion and stays recorded.

    Asserted on match_company directly: run() draws from a shared backlog of ~10k rows,
    so which leads it happens to pick is not this test's business."""
    from outreach import crossref

    class _DeadCH:
        def search_companies(self, *a, **k):
            raise RuntimeError("429 Too Many Requests")

    class _EmptyCH:
        def search_companies(self, *a, **k):
            return []

    dead_cls, _, dead = crossref.match_company(_DeadCH(), "Acme Ltd", "LS1 1AA")
    empty_cls, _, empty = crossref.match_company(_EmptyCH(), "Acme Ltd", "LS1 1AA")

    assert crossref.unavailable(dead) is True
    assert crossref.unavailable(empty) is False
    # both still classify UNKNOWN — fail-closed is correct for a PECR gate. The only
    # difference is whether run() is allowed to make that verdict permanent.
    assert dead_cls.value == "unknown" and empty_cls.value == "unknown"


def test_run_records_a_genuine_no_match(db_rollback):
    """A register that answers "no such company" is a VERDICT and must be persisted;
    only an unavailable register defers.

    Seeds its own lead and pins it oldest. It used to run against whatever the shared
    backlog happened to hold, so it was really asserting on production data — and it
    duly broke the day crossref finished the backlog and there was nothing left to
    classify. A test about a code path has to supply its own input for that path.
    """
    from outreach import crossref

    class _EmptyCH:
        def search_companies(self, *a, **k):
            return []

        def close(self):
            pass

    cur = db_rollback.cursor()
    pid = uuid.uuid4().hex[:10]
    cur.execute("insert into outreach.leads (company_number, company_name, registered_address, "
                "state, source, place_id, created_at) values "
                "(%s,%s,%s::jsonb,'discovered','places',%s,'1990-01-01')",
                (f"PLACE:{pid}", "Nowhere Registered Ltd", '{"postcode":"LS21 1AA"}', pid))

    res = crossref.run(limit=1, cur=cur, ch=_EmptyCH())
    assert res["deferred"] == 0
    assert res["unknown"] == 1
    cur.execute("select subscriber_class::text, crossref_checked_at is not null "
                "from outreach.leads where place_id=%s", (pid,))
    cls, checked = cur.fetchone()
    assert cls == "unknown" and checked      # the verdict is written, not left to retry
