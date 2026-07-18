import datetime
import sys
import types
import uuid

import pytest

from outreach import config, monitor, report


def _unconfigured_send(sender, to_email, subject, body, *, client=None):
    raise RuntimeError("gmail not configured (stub)")


def _ensure_module(name: str, **attrs):
    """gmail.py / spend.py are built in parallel — stub them into sys.modules if
    absent so monitor/report's lazy imports resolve and monkeypatching works."""
    mod_name = f"outreach.{name}"
    try:
        __import__(mod_name)
    except Exception:
        mod = types.ModuleType(mod_name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[mod_name] = mod
        import outreach
        setattr(outreach, name, mod)
    return sys.modules[mod_name]


gmail = _ensure_module("gmail", send_message=_unconfigured_send)
spend = _ensure_module("spend", month_total_gbp=lambda *a, **k: 0.0)


@pytest.fixture
def operator(monkeypatch):
    monkeypatch.setattr(config, "OPERATOR_EMAIL", "operator@example.com")
    monkeypatch.setattr(config, "GMAIL_SENDER", "digest-bot@example.com")


@pytest.fixture
def sent_mail(monkeypatch):
    calls = []

    def fake(sender, to_email, subject, body, *, client=None):
        calls.append({"sender": sender, "to": to_email, "subject": subject, "body": body})
        return f"fake-msg-{len(calls)}"

    monkeypatch.setattr(gmail, "send_message", fake)
    return calls


def _seed_vertical(cur, *, sends=25, bounced_state=0, bounced_reply=0, complaints=0):
    """Seed a unique fake vertical so per-vertical assertions are independent of
    whatever committed data the live DB holds."""
    sic = f"TEST{uuid.uuid4().hex[:8]}"
    cns = []
    for _ in range(sends):
        cn = f"MON{uuid.uuid4().hex[:9]}"
        cur.execute(
            "insert into outreach.leads (company_number, company_name, company_type, "
            "subscriber_class, state, sic_codes) values (%s,%s,'ltd','corporate','sent',%s)",
            (cn, cn, [sic]))
        cur.execute(
            "insert into outreach.sends (company_number, to_email, mode, status) "
            "values (%s,%s,'live','sent')", (cn, f"info@{cn.lower()}.example"))
        cns.append(cn)
    for cn in cns[:bounced_state]:
        cur.execute(
            "update outreach.leads set state='bounced', updated_at=now() "
            "where company_number=%s", (cn,))
    for cn in cns[bounced_state:bounced_state + bounced_reply]:
        cur.execute(
            "insert into outreach.replies (company_number, from_email, kind) "
            "values (%s,'mailer-daemon@example.com','bounce')", (cn,))
    for cn in cns[:complaints]:
        cur.execute(
            "insert into outreach.replies (company_number, from_email, kind) "
            "values (%s,%s,'complaint')", (cn, f"info@{cn.lower()}.example"))
    return sic, cns


def _stats(sent, bounced=0, complaints=0):
    return {"sent": sent, "bounced": bounced, "complaints": complaints,
            "bounce_rate": (bounced / sent) if sent else 0.0,
            "complaint_rate": (complaints / sent) if sent else 0.0,
            "window_days": 14, "verticals": {}}


# ---- kill switch (ops_flags) ----
def test_kill_switch_roundtrip(db_rollback):
    cur = db_rollback.cursor()
    monitor.set_kill_switch(False, cur=cur)
    assert monitor.db_kill_switch(cur=cur) is False
    monitor.set_kill_switch(True, reason="test breach", updated_by="pytest", cur=cur)
    assert monitor.db_kill_switch(cur=cur) is True
    cur.execute("select value, reason, updated_by from outreach.ops_flags where key='kill_switch'")
    assert cur.fetchone() == ("1", "test breach", "pytest")
    monitor.set_kill_switch(False, cur=cur)
    assert monitor.db_kill_switch(cur=cur) is False


def test_kill_switch_fails_open_on_db_error():
    class BrokenCur:
        def execute(self, *a, **k):
            raise RuntimeError("db down")

    assert monitor.db_kill_switch(cur=BrokenCur()) is False


# ---- bounce_stats / breaches ----
def test_bounce_stats_counts_seeded_vertical(db_rollback):
    cur = db_rollback.cursor()
    sic, _ = _seed_vertical(cur, sends=25, bounced_state=2, bounced_reply=1, complaints=1)
    stats = monitor.bounce_stats(cur)
    v = stats["verticals"][sic]
    assert v["sent"] == 25
    assert v["bounced"] == 3
    assert v["complaints"] == 1
    assert v["bounce_rate"] == pytest.approx(3 / 25)
    assert v["complaint_rate"] == pytest.approx(1 / 25)
    assert v["label"] == sic
    assert stats["sent"] >= 25 and stats["bounced"] >= 3


def test_breaches_flags_only_bad_verticals(db_rollback):
    cur = db_rollback.cursor()
    bad, _ = _seed_vertical(cur, sends=25, bounced_state=3)
    good, _ = _seed_vertical(cur, sends=25)
    tiny, _ = _seed_vertical(cur, sends=10, bounced_state=5)
    text = "\n".join(monitor.breaches(monitor.bounce_stats(cur)))
    assert bad in text
    assert good not in text
    assert tiny not in text


def test_breach_thresholds_exact():
    assert monitor.breaches(_stats(100, bounced=2)) == []
    assert monitor.breaches(_stats(100, bounced=3))
    assert monitor.breaches(_stats(1000, complaints=1)) == []
    assert monitor.breaches(_stats(1000, complaints=2))
    assert monitor.breaches(_stats(19, bounced=19)) == []


# ---- check_and_pause ----
def test_check_and_pause_pauses_and_alerts_on_breach(db_rollback, operator, sent_mail):
    cur = db_rollback.cursor()
    monitor.set_kill_switch(False, cur=cur)
    _seed_vertical(cur, sends=30, bounced_state=4)
    out = monitor.check_and_pause(cur=cur)
    assert out["paused"] is True
    assert out["breaches"]
    assert monitor.db_kill_switch(cur=cur) is True
    assert len(sent_mail) == 1
    assert sent_mail[0]["to"] == "operator@example.com"
    assert "paused" in sent_mail[0]["subject"].lower()


def test_check_and_pause_clean_run_does_nothing(db_rollback, operator, sent_mail, monkeypatch):
    cur = db_rollback.cursor()
    monitor.set_kill_switch(False, cur=cur)
    monkeypatch.setattr(monitor, "bounce_stats", lambda cur, **k: _stats(100))
    out = monitor.check_and_pause(cur=cur)
    assert out == {"stats": _stats(100), "breaches": [], "paused": False}
    assert monitor.db_kill_switch(cur=cur) is False
    assert sent_mail == []


def test_check_and_pause_survives_alert_failure(db_rollback, operator, monkeypatch):
    cur = db_rollback.cursor()
    monitor.set_kill_switch(False, cur=cur)
    monkeypatch.setattr(gmail, "send_message", _unconfigured_send)
    _seed_vertical(cur, sends=30, bounced_state=4)
    out = monitor.check_and_pause(cur=cur)
    assert out["paused"] is True
    assert monitor.db_kill_switch(cur=cur) is True


# ---- daily digest ----
HEADERS = ["SENT", "REPLIES / BOUNCES / OPT-OUTS (7d)", "NEW LEADS / DRAFTS",
           "SPEND", "FLAGS", "FAILED JOBS"]


def test_daily_digest_renders_every_section(db_rollback, monkeypatch):
    cur = db_rollback.cursor()
    monkeypatch.setattr(spend, "month_total_gbp", lambda *a, **k: 12.34)
    text = report.daily_digest_text(cur)
    for header in HEADERS:
        assert header in text
    assert "12.34" in text
    assert "SECTION UNAVAILABLE" not in text


def test_daily_digest_survives_broken_section(db_rollback, monkeypatch):
    cur = db_rollback.cursor()

    def boom(*a, **k):
        raise RuntimeError("spend ledger offline")

    monkeypatch.setattr(spend, "month_total_gbp", boom)
    text = report.daily_digest_text(cur)
    for header in HEADERS:
        assert header in text
    assert "SECTION UNAVAILABLE (spend ledger offline)" in text


def test_send_daily_digest_throttles_per_day(db_rollback, operator, sent_mail, monkeypatch):
    cur = db_rollback.cursor()
    cur.execute("delete from outreach.ops_flags where key=%s", (report.DIGEST_FLAG,))
    monkeypatch.setattr(spend, "month_total_gbp", lambda *a, **k: 0.0)
    first = report.send_daily_digest(cur=cur)
    assert first == {"sent": "operator@example.com",
                     "date": datetime.date.today().isoformat()}
    second = report.send_daily_digest(cur=cur)
    assert second == {"skipped": "already sent"}
    assert len(sent_mail) == 1


def test_send_daily_digest_skips_without_operator(db_rollback, sent_mail, monkeypatch):
    cur = db_rollback.cursor()
    cur.execute("delete from outreach.ops_flags where key=%s", (report.DIGEST_FLAG,))
    monkeypatch.setattr(config, "OPERATOR_EMAIL", None)
    out = report.send_daily_digest(cur=cur)
    assert out == {"skipped": "OPERATOR_EMAIL unset"}
    assert sent_mail == []
    assert monitor.get_flag(report.DIGEST_FLAG, cur=cur) != datetime.date.today().isoformat()


def test_send_daily_digest_sends_even_when_kill_switch_on(db_rollback, operator, sent_mail, monkeypatch):
    cur = db_rollback.cursor()
    cur.execute("delete from outreach.ops_flags where key=%s", (report.DIGEST_FLAG,))
    monitor.set_kill_switch(True, reason="test", cur=cur)
    monkeypatch.setattr(spend, "month_total_gbp", lambda *a, **k: 0.0)
    out = report.send_daily_digest(cur=cur)
    assert "sent" in out
    assert len(sent_mail) == 1
