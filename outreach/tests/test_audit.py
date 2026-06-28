import pytest

from outreach import audit

pytestmark = pytest.mark.floor_a


def test_audit_writer_inserts_row(db_rollback):
    cur = db_rollback.cursor()
    audit.record(
        "TESTCO_AUDIT_0001",
        "classified",
        source="unit-test",
        lawful_basis=audit.LEGITIMATE_INTERESTS,
        reason="phase A audit writer test",
        detail={"k": "v"},
        cur=cur,
    )
    cur.execute(
        "select company_number, event, lawful_basis, reason "
        "from outreach.audit_log where company_number = %s",
        ("TESTCO_AUDIT_0001",),
    )
    row = cur.fetchone()
    assert row == (
        "TESTCO_AUDIT_0001", "classified",
        "legitimate interests", "phase A audit writer test",
    )
    # db_rollback fixture rolls back -> no pollution of the live DB
