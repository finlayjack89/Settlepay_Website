"""Test database wiring.

The suite talks to a real Postgres. Set **TEST_DATABASE_URL** to point it at a
throwaway database (`python -m outreach migrate` provisions the schema); the whole
suite then runs isolated and every test is deterministic.

Without it the suite falls back to DATABASE_URL — the LIVE Supabase — which is how
it ran for months. `db_rollback` means nothing is written, but reads still see
production rows, so any test whose assertions depend on a global count is decided by
whatever the pipeline happened to do that week. Two schedule tests were failing for
exactly that reason, and the failures had become accepted background noise.

Rather than let that recur silently, tests that need a database to themselves are
marked `needs_isolated_db` and SKIP (loudly, with a reason) when the fallback is in
use. A skip that names its cause is honest; a red baseline everyone learns to ignore
is not.
"""
import os

import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
ISOLATED_DB = bool(TEST_DATABASE_URL)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "needs_isolated_db: assertions depend on global row counts; requires "
        "TEST_DATABASE_URL to point at a database this suite owns")
    if ISOLATED_DB:
        from outreach import config as oc
        oc.DATABASE_URL = TEST_DATABASE_URL


def pytest_collection_modifyitems(config, items):
    if ISOLATED_DB:
        return
    skip = pytest.mark.skip(reason="needs TEST_DATABASE_URL (an isolated database); "
                                   "against the shared DB this asserts on live rows")
    for item in items:
        if "needs_isolated_db" in item.keywords:
            item.add_marker(skip)


def pytest_report_header(config):
    return ("outreach db: ISOLATED (TEST_DATABASE_URL)" if ISOLATED_DB else
            "outreach db: SHARED/LIVE — set TEST_DATABASE_URL to isolate; "
            "`needs_isolated_db` tests will skip")


@pytest.fixture
def db_rollback():
    """A live connection whose work is rolled back at test end (no DB pollution)."""
    from outreach import db

    conn = db.connect()
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
