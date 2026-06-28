import pytest

# the web UI is an optional extra; skip cleanly if fastapi isn't installed
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from outreach.web import app  # noqa: E402

client = TestClient(app)


def test_queue_renders():
    r = client.get("/")
    assert r.status_code == 200
    assert "Approval queue" in r.text


def test_dashboard_renders():
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "Leads by state" in r.text
    assert "Graduation thresholds" in r.text


def test_missing_draft_404s():
    r = client.get("/draft/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
