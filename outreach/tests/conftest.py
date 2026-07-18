import pytest


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
