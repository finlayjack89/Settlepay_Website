import pytest

# the web UI is an optional extra; skip cleanly if fastapi isn't installed
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from outreach.web import app  # noqa: E402

client = TestClient(app)


def test_root_redirects_to_dashboard():
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (307, 308)
    assert r.headers["location"] == "/dashboard"


def test_dashboard_renders():
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "Conversion funnel" in r.text
    assert "Graduation to auto-send" in r.text
    assert "Yield by vertical" in r.text


def test_queue_renders():
    r = client.get("/queue")
    assert r.status_code == 200
    assert "awaiting" in r.text


def test_leads_renders():
    r = client.get("/leads")
    assert r.status_code == 200
    assert "CRM view" in r.text


def test_leads_state_filter_renders():
    r = client.get("/leads?state=approved")
    assert r.status_code == 200


def test_settings_renders():
    r = client.get("/settings")
    assert r.status_code == 200
    assert "Send safety" in r.text
    assert "gated" in r.text  # G-SEND off by default


def test_missing_draft_404s():
    r = client.get("/draft/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
