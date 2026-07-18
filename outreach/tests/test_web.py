import pytest

# the web UI is an optional extra; skip cleanly if fastapi isn't installed
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from outreach.web import app  # noqa: E402

client = TestClient(app)


def test_landing_combines_inbound_and_outbound():
    r = client.get("/")
    assert r.status_code == 200
    assert "Inbound — Enquiries" in r.text
    assert "Outbound — Outreach" in r.text


def test_outreach_dashboard_renders():
    r = client.get("/outreach")
    assert r.status_code == 200
    assert "Conversion funnel" in r.text
    assert "Graduation to auto-send" in r.text
    assert "Yield by vertical" in r.text


def test_outreach_queue_renders():
    r = client.get("/outreach/queue")
    assert r.status_code == 200
    assert "awaiting" in r.text


def test_outreach_leads_renders():
    r = client.get("/outreach/leads")
    assert r.status_code == 200
    assert "CRM view" in r.text


def test_outreach_leads_state_filter_renders():
    r = client.get("/outreach/leads?state=approved")
    assert r.status_code == 200


def test_enquiries_renders():
    r = client.get("/enquiries")
    assert r.status_code == 200
    assert "your CRM" in r.text


def test_schedule_renders():
    r = client.get("/schedule")
    assert r.status_code == 200
    # both the connected view and the "no bookings yet" fallback mention consultations
    assert "Consultations" in r.text


def test_schedule_in_sidebar():
    r = client.get("/")
    assert "/schedule" in r.text  # Schedule nav entry present under Inbound


def test_settings_renders():
    r = client.get("/settings")
    assert r.status_code == 200
    assert "Send safety" in r.text
    assert "Inbound enquiries (CRM)" in r.text
    assert "gated" in r.text  # G-SEND off by default


def test_grouped_sidebar_present():
    r = client.get("/")
    assert "Inbound" in r.text and "Outbound" in r.text  # nav groups


def test_missing_draft_404s():
    r = client.get("/outreach/draft/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_missing_enquiry_404s():
    r = client.get("/enquiry/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
