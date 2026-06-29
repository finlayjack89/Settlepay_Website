import pytest

from outreach import db, enquiries


def test_table_guard_rejects_bad_source(monkeypatch):
    monkeypatch.setattr(enquiries.config, "ENQUIRY_SOURCE_TABLE", "evil; drop table x")
    with pytest.raises(ValueError):
        enquiries._table()


def test_update_rejects_invalid_status():
    class _NoExec:
        def execute(self, *a, **k):
            raise AssertionError("must validate status before touching the DB")
    with pytest.raises(ValueError):
        enquiries.update(_NoExec(), "00000000-0000-0000-0000-000000000000", "bogus", "")


def test_overview_returns_expected_keys():
    with db.dict_cursor() as cur:
        o = enquiries.overview(cur)
    assert {"total", "new", "contacted", "quoted", "won", "client", "lost",
            "this_week"}.issubset(o.keys())


def test_list_enquiries_is_read_only_list():
    with db.dict_cursor() as cur:
        rows = enquiries.list_enquiries(cur)
        counts = enquiries.status_counts(cur)
    assert isinstance(rows, list) and isinstance(counts, dict)
