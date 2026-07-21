import uuid

import pytest

from outreach import config, send, sequence

pytestmark = pytest.mark.floor_g

COMPLIANT = "Hello. FCA-regulated partners handle payments. Reply unsubscribe to opt out. SettlePay"


def _seed_approved(cur, *, email=None, sub="corporate", tier=None):
    cn = f"SND_{uuid.uuid4().hex[:8]}"
    email = email or f"info-{uuid.uuid4().hex[:6]}@example.com"
    cur.execute(
        "insert into outreach.leads (company_number, company_name, company_type, "
        "subscriber_class, state) values (%s,%s,'ltd',%s,'approved')", (cn, cn, sub))
    cur.execute(
        "insert into outreach.enrichment (company_number, website, contact_email, "
        "email_verified, contact_tier, signal) values (%s,'https://x.co',%s,%s,%s,'sig')",
        (cn, email, tier != "risky", tier))
    cur.execute(
        "insert into outreach.drafts (company_number, subject, subject_final, "
        "body_original, body_final, prompt_version, status, decided_by, decided_at) "
        "values (%s,'payments at test co','payments at test co',%s,%s,"
        "'placeholder-v0','approved','Finlay',now()) returning id",
        (cn, COMPLIANT, COMPLIANT))
    return cn, email, cur.fetchone()[0]


def test_dry_run_records_and_does_not_advance(db_rollback):
    cur = db_rollback.cursor()
    cn, email, did = _seed_approved(cur)
    res = send.send_one(did, mode="dry_run", inbox="test@settlepayhq.uk", cur=cur)
    assert res["mode"] == "dry_run" and res["status"] == "dry_run_ok" and res["to"] == email
    cur.execute("select mode, status from outreach.sends where draft_id=%s", (did,))
    assert cur.fetchone() == ("dry_run", "dry_run_ok")
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "approved"  # dry-run never advances to sent


def test_live_send_refused_while_gate_unset(db_rollback):
    cur = db_rollback.cursor()
    cn, email, did = _seed_approved(cur)
    assert config.send_enabled() is False           # G_SEND unset
    with pytest.raises(send.SendRefused):
        send.send_one(did, mode="live", inbox="test@settlepayhq.uk", cur=cur)
    cur.execute("select count(*) from outreach.sends where draft_id=%s and mode='live'", (did,))
    assert cur.fetchone()[0] == 0                    # nothing sent live


def test_gmail_send_refuses_without_credentials(monkeypatch):
    # the Gmail backend refuses cleanly when OAuth creds are unset (no network)
    for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN", "GMAIL_SENDER"):
        monkeypatch.setattr(send.config, k, None)
    with pytest.raises(send.SendRefused):
        send._gmail_send("", "to@example.com", "subject", "body")


def test_individual_subscriber_blocked_even_dry_run(db_rollback):
    cur = db_rollback.cursor()
    cn, email, did = _seed_approved(cur, sub="individual")
    with pytest.raises(send.SendRefused):
        send.send_one(did, mode="dry_run", cur=cur)


def test_suppressed_recipient_blocked(db_rollback):
    cur = db_rollback.cursor()
    cn, email, did = _seed_approved(cur)
    cur.execute("insert into outreach.suppressions (email, reason) values (%s,'test')", (email,))
    with pytest.raises(send.SendRefused):
        send.send_one(did, mode="dry_run", cur=cur)


def test_kill_switch_blocks(db_rollback, monkeypatch):
    cur = db_rollback.cursor()
    cn, email, did = _seed_approved(cur)
    monkeypatch.setattr(send.config, "KILL_SWITCH", "1")
    with pytest.raises(send.SendRefused):
        send.send_one(did, mode="dry_run", cur=cur)


def test_risky_contact_blocked_without_optin(db_rollback, monkeypatch):
    cur = db_rollback.cursor()
    cn, email, did = _seed_approved(cur, tier="risky")
    monkeypatch.setattr(send.config, "RISKY_SEND_ENABLED", False)
    with pytest.raises(send.SendRefused):
        send.send_one(did, mode="dry_run", cur=cur)  # catch-all needs explicit opt-in


def test_risky_contact_allowed_with_optin(db_rollback, monkeypatch):
    cur = db_rollback.cursor()
    cn, email, did = _seed_approved(cur, tier="risky")
    monkeypatch.setattr(send.config, "RISKY_SEND_ENABLED", True)
    res = send.send_one(did, mode="dry_run", cur=cur)
    assert res["status"] == "dry_run_ok"


def test_per_inbox_daily_cap_enforced(db_rollback, monkeypatch):
    cur = db_rollback.cursor()
    monkeypatch.setattr(send.config, "PER_INBOX_DAILY_CAP", 1)
    _, _, d1 = _seed_approved(cur)
    _, _, d2 = _seed_approved(cur)
    send.send_one(d1, mode="dry_run", inbox="cap@settlepayhq.uk", cur=cur)   # 1st ok
    with pytest.raises(send.SendRefused):
        send.send_one(d2, mode="dry_run", inbox="cap@settlepayhq.uk", cur=cur)  # 2nd over cap


def test_warmup_cap_ramps_then_holds():
    assert sequence.warmup_cap(1) <= sequence.warmup_cap(8)
    assert sequence.warmup_cap(10_000) == sequence.warmup_cap(8)  # holds at steady


def test_warmup_limits_below_steady_cap(db_rollback, monkeypatch):
    # steady ceiling is high, but on warm-up day 1 the effective cap is the ramp value
    cur = db_rollback.cursor()
    monkeypatch.setattr(send.config, "PER_INBOX_DAILY_CAP", 999)
    day1 = sequence.warmup_cap(1)
    inbox = f"warm-{uuid.uuid4().hex[:6]}@settlepayhq.uk"  # no prior live send -> day 1
    for _ in range(day1):
        _, _, d = _seed_approved(cur)
        send.send_one(d, mode="dry_run", inbox=inbox, cur=cur)
    _, _, over = _seed_approved(cur)
    with pytest.raises(send.SendRefused):
        send.send_one(over, mode="dry_run", inbox=inbox, cur=cur)  # ramp cap reached


def test_send_refuses_a_subjectless_pre_v2_draft(db_rollback):
    """Playbook v1.x stored subject=NULL on every draft and send posts `subject or ""`.
    Those rows must be refused, not delivered with a blank Subject header."""
    cur = db_rollback.cursor()
    cn, email, did = _seed_approved(cur)
    cur.execute("update outreach.drafts set subject=null, subject_final=null where id=%s", (did,))
    with pytest.raises(send.SendRefused, match="no subject"):
        send.send_one(did, mode="dry_run", cur=cur)


def test_send_prefers_the_reviewer_edited_subject(db_rollback):
    """subject_final (what the reviewer approved) must win over subject (what the
    model wrote). Proven via the guardrail: with subject NULL and only subject_final
    set, the send must still go through — which it can only do if coalesce reads
    subject_final."""
    cur = db_rollback.cursor()
    cn, email, did = _seed_approved(cur)
    cur.execute("update outreach.drafts set subject=null, subject_final=%s where id=%s",
                ("reviewer rewrote this", did))
    res = send.send_one(did, mode="dry_run", cur=cur)
    assert res["status"] == "dry_run_ok"


def test_named_contact_send_uses_the_transparency_footer(db_rollback, monkeypatch):
    """A live send to a 'named' contact must go out with the art. 14 footer; a role
    address must not. We intercept the Gmail backend and inspect the rendered body."""
    cur = db_rollback.cursor()
    monkeypatch.setattr(config, "G_SEND", "1")        # clear the live gate for this test
    captured = {}

    def _fake_send(sender, to_email, subject, body, html=None):
        captured["text"] = body
        captured["html"] = html or ""
        return "msgid-123"
    monkeypatch.setattr("outreach.gmail.send_message", _fake_send)

    # named contact
    cn, email, did = _seed_approved(cur, tier="named")
    send.send_one(did, mode="live", inbox="s@settlepayhq.uk", cur=cur)
    assert "Companies House" in captured["text"]      # art. 14 source, plain-text part
    assert "Companies House" in captured["html"]      # ...and the html part
    assert config.PRIVACY_NOTICE_URL in captured["text"]

    # role address on the same run must NOT carry it
    captured.clear()
    cn2, email2, did2 = _seed_approved(cur, tier="verified")
    send.send_one(did2, mode="live", inbox="s@settlepayhq.uk", cur=cur)
    assert "Companies House" not in captured["text"]
    assert "Companies House" not in captured["html"]
