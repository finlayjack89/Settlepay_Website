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


# ---- ops canvas (tasks / jobs / health / tick) ----
def test_healthz():
    assert client.get("/healthz").json() == {"ok": True}


def test_home_shows_operations_panel():
    r = client.get("/")
    assert "Operations" in r.text and "Spend MTD" in r.text


def test_tasks_page_lists_registry():
    r = client.get("/tasks")
    assert r.status_code == 200
    assert "Pipeline tick" in r.text and "Discover leads" in r.text


def test_jobs_page_renders():
    assert client.get("/jobs").status_code == 200


def test_tick_enqueues_and_dedupes():
    from outreach import db
    a = client.post("/tick").json()["job_id"]
    b = client.post("/tick").json()["job_id"]
    assert a == b  # second call deduped onto the queued job
    with db.cursor() as cur:  # tidy the queued row
        cur.execute("delete from outreach.jobs where id=%s and status='queued'", (a,))


def test_vertical_drilldown_renders():
    r = client.get("/outreach/vertical/96020")
    assert r.status_code == 200
    assert "Graduation to auto-send" in r.text


def test_settings_shows_operational_controls():
    r = client.get("/settings")
    assert "Operational controls" in r.text and "Kill switch" in r.text


# ---- auth (open locally; enforced once configured) ----
def test_login_redirects_home_in_open_mode():
    r = client.get("/login", follow_redirects=False)
    assert r.status_code == 303


def _configure_auth(monkeypatch, password="pw"):
    from outreach import config, webauth
    monkeypatch.setattr(config, "SESSION_SECRET", "test-secret")
    monkeypatch.setattr(config, "CONSOLE_PASSWORD_HASH", webauth.hash_password(password))


def test_auth_enforced_when_configured(monkeypatch):
    _configure_auth(monkeypatch)
    from outreach import web
    web._login_limiter.reset("testclient")
    c = TestClient(app)
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/login")
    assert c.get("/login").status_code == 200          # login page reachable
    assert c.post("/login", data={"password": "nope"}).status_code == 401
    ok = c.post("/login", data={"password": "pw"}, follow_redirects=False)
    assert ok.status_code == 303 and "ops_session" in ok.headers.get("set-cookie", "")
    assert c.get("/", follow_redirects=False).status_code == 200  # session accepted
    # authed POST without a CSRF token is refused before any work happens
    bad = c.post("/outreach/approve/00000000-0000-0000-0000-000000000000",
                 data={"reviewer": "x"})
    assert bad.status_code == 403


def test_healthz_and_tick_bypass_session_auth(monkeypatch):
    _configure_auth(monkeypatch)
    c = TestClient(app)
    assert c.get("/healthz").status_code == 200          # exempt from session gate
    assert c.post("/tick").status_code == 401            # but tick needs OIDC now


def test_prefix_links_rewrites_under_base_path(monkeypatch):
    from outreach import config, web
    monkeypatch.setattr(config, "BASE_PATH", "/dashboard")
    out = web._prefix_links('<a href="/enquiries">x</a><form action="/login">'
                            "<tr onclick=\"location.href='/jobs/1'\">"
                            '<a href="https://x.co/">ext</a>')
    assert 'href="/dashboard/enquiries"' in out
    assert 'action="/dashboard/login"' in out
    assert "location.href='/dashboard/jobs/1'" in out
    assert 'href="https://x.co/"' in out  # absolute externals untouched
