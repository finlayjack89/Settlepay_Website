import uuid

import pytest

from outreach import config, send

pytestmark = pytest.mark.floor_g

COMPLIANT = "Hello. FCA-regulated partners handle payments. Reply unsubscribe to opt out. SettlePay"


def _seed_approved(cur, *, email=None, sub="corporate"):
    cn = f"SND_{uuid.uuid4().hex[:8]}"
    email = email or f"info-{uuid.uuid4().hex[:6]}@example.com"
    cur.execute(
        "insert into outreach.leads (company_number, company_name, company_type, "
        "subscriber_class, state) values (%s,%s,'ltd',%s,'approved')", (cn, cn, sub))
    cur.execute(
        "insert into outreach.enrichment (company_number, website, contact_email, "
        "email_verified, signal) values (%s,'https://x.co',%s,true,'sig')", (cn, email))
    cur.execute(
        "insert into outreach.drafts (company_number, body_original, body_final, "
        "prompt_version, status, decided_by, decided_at) "
        "values (%s,%s,%s,'placeholder-v0','approved','Finlay',now()) returning id",
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


def test_per_inbox_daily_cap_enforced(db_rollback, monkeypatch):
    cur = db_rollback.cursor()
    monkeypatch.setattr(send.config, "PER_INBOX_DAILY_CAP", 1)
    _, _, d1 = _seed_approved(cur)
    _, _, d2 = _seed_approved(cur)
    send.send_one(d1, mode="dry_run", inbox="cap@settlepayhq.uk", cur=cur)   # 1st ok
    with pytest.raises(send.SendRefused):
        send.send_one(d2, mode="dry_run", inbox="cap@settlepayhq.uk", cur=cur)  # 2nd over cap
