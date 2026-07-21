import datetime
import uuid

import pytest

from outreach import outbox

pytestmark = pytest.mark.floor_g


def _draft(cur, status="approved", *, sent=False, sent_mode="live"):
    cn = f"OBX_{uuid.uuid4().hex[:8]}"
    did = uuid.uuid4()
    cur.execute(
        "insert into outreach.leads (company_number, company_name, company_type, "
        "subscriber_class, state) values (%s,%s,'ltd','corporate','approved')", (cn, cn))
    cur.execute(
        "insert into outreach.drafts (id, company_number, subject, body_original, "
        "body_final, prompt_version, status, scheduled_at) "
        "values (%s,%s,'a subject','body','body','t',%s, now() + interval '2 days')",
        (did, cn, status))
    if sent:
        cur.execute("insert into outreach.sends (draft_id, company_number, to_email, "
                    "mode, status) values (%s,%s,'x@y.uk',%s,%s)",
                    (did, cn, sent_mode, "sent" if sent_mode == "live" else "dry_run_ok"))
    return did, cn


def _age(cur, draft_id, seconds):
    cur.execute("update outreach.drafts set outbox_at = now() - make_interval(secs => %s) "
                "where id = %s", (seconds, draft_id))


def test_send_now_puts_an_approved_draft_in_the_outbox(db_rollback):
    cur = db_rollback.cursor()
    did, _ = _draft(cur)
    sends_at = outbox.send_now(did, requested_by="test", cur=cur)
    cur.execute("select outbox_at from outreach.drafts where id=%s", (did,))
    at = cur.fetchone()[0]
    assert at is not None
    assert (sends_at - at).total_seconds() == outbox.UNDO_SECONDS


def test_only_approved_drafts_can_be_sent_manually(db_rollback):
    cur = db_rollback.cursor()
    did, _ = _draft(cur, status="awaiting_approval")
    with pytest.raises(outbox.OutboxRefused):
        outbox.send_now(did, requested_by="test", cur=cur)


def test_an_already_live_sent_draft_cannot_be_re_sent(db_rollback):
    cur = db_rollback.cursor()
    did, _ = _draft(cur, sent=True, sent_mode="live")
    with pytest.raises(outbox.OutboxRefused):
        outbox.send_now(did, requested_by="test", cur=cur)


def test_a_dry_run_send_does_not_burn_the_draft_for_live(db_rollback):
    """The bug behind 'I clicked send and nothing arrived': clicking 'send now' while
    G-SEND is off dry-runs and records a send row. That must NOT stop the real live send
    once G-SEND is on — only a LIVE send means 'already gone'."""
    cur = db_rollback.cursor()
    did, cn = _draft(cur, sent=True, sent_mode="dry_run")   # a prior dry-run
    # still enters the outbox
    outbox.send_now(did, requested_by="test", cur=cur)
    cur.execute("select outbox_at from outreach.drafts where id=%s", (did,))
    assert cur.fetchone()[0] is not None
    _age(cur, did, outbox.UNDO_SECONDS + 1)
    assert did in outbox.due(cur, mode="live")             # live-eligible despite the dry-run
    assert did not in outbox.due(cur, mode="dry_run")      # ...but no dry-run spam


def test_a_second_click_does_not_restart_the_undo_window(db_rollback):
    """Otherwise an impatient double-click silently buys another 30 seconds — or,
    worse, reads as 'it didn't work' and gets clicked again."""
    cur = db_rollback.cursor()
    did, _ = _draft(cur)
    first = outbox.send_now(did, requested_by="test", cur=cur)
    _age(cur, did, 10)
    again = outbox.send_now(did, requested_by="test", cur=cur)
    assert again < first


def test_cancel_takes_it_back_out_and_keeps_the_original_slot(db_rollback):
    cur = db_rollback.cursor()
    did, _ = _draft(cur)
    cur.execute("select scheduled_at from outreach.drafts where id=%s", (did,))
    slot = cur.fetchone()[0]
    outbox.send_now(did, requested_by="test", cur=cur)
    assert outbox.cancel(did, requested_by="test", cur=cur) is True
    cur.execute("select outbox_at, scheduled_at, status from outreach.drafts where id=%s", (did,))
    at, still, status = cur.fetchone()
    assert at is None and still == slot and status == "approved"


def test_cancelling_something_not_in_the_outbox_reports_failure(db_rollback):
    cur = db_rollback.cursor()
    did, _ = _draft(cur)
    assert outbox.cancel(did, requested_by="test", cur=cur) is False


def test_nothing_is_due_until_the_undo_window_closes(db_rollback):
    cur = db_rollback.cursor()
    did, _ = _draft(cur)
    outbox.send_now(did, requested_by="test", cur=cur)
    assert did not in outbox.due(cur)
    _age(cur, did, outbox.UNDO_SECONDS + 1)
    assert did in outbox.due(cur)


def test_flush_sends_the_due_draft_and_empties_the_outbox(db_rollback):
    cur = db_rollback.cursor()
    did, cn = _draft(cur)
    cur.execute("insert into outreach.enrichment (company_number, contact_email, "
                "email_verified, contact_tier) values (%s,'ops@example.co.uk',true,'verified')",
                (cn,))
    outbox.send_now(did, requested_by="test", cur=cur)
    _age(cur, did, outbox.UNDO_SECONDS + 1)
    out = outbox.flush(dry_run=True, cur=cur)
    assert out and out[0].get("status") == "dry_run_ok"
    cur.execute("select outbox_at from outreach.drafts where id=%s", (did,))
    assert cur.fetchone()[0] is None


def test_a_refused_send_still_leaves_the_outbox(db_rollback):
    """A manual send the guardrails reject must not sit in the outbox being retried
    every few seconds for the rest of the instance's life."""
    cur = db_rollback.cursor()
    did, cn = _draft(cur)          # no enrichment row -> send_one refuses: no contact email
    outbox.send_now(did, requested_by="test", cur=cur)
    _age(cur, did, outbox.UNDO_SECONDS + 1)
    out = outbox.flush(dry_run=True, cur=cur)
    assert "refused" in out[0]
    cur.execute("select outbox_at from outreach.drafts where id=%s", (did,))
    assert cur.fetchone()[0] is None


def test_pending_reports_what_is_still_counting_down(db_rollback):
    cur = db_rollback.cursor()
    did, cn = _draft(cur)
    outbox.send_now(did, requested_by="test", cur=cur)
    rows = [r for r in outbox.pending(cur) if r["id"] == did]
    assert len(rows) == 1
    assert rows[0]["company_name"] == cn
    assert rows[0]["sends_at"] - rows[0]["outbox_at"] == \
        datetime.timedelta(seconds=outbox.UNDO_SECONDS)


def test_the_manual_override_still_obeys_the_kill_switch(db_rollback, monkeypatch):
    """'Send now' overrides the TIMING only. Every compliance guardrail send_one
    enforces has to survive it, or the button becomes a way around them."""
    from outreach import send as send_mod
    cur = db_rollback.cursor()
    did, cn = _draft(cur)
    cur.execute("insert into outreach.enrichment (company_number, contact_email, "
                "email_verified, contact_tier) values (%s,'ops@example.co.uk',true,'verified')",
                (cn,))
    monkeypatch.setattr(send_mod, "_kill_switch_on", lambda cur=None: True)
    outbox.send_now(did, requested_by="test", cur=cur)
    _age(cur, did, outbox.UNDO_SECONDS + 1)
    out = outbox.flush(dry_run=True, cur=cur)
    assert "kill switch" in out[0]["refused"]


def test_the_manual_override_still_obeys_suppression(db_rollback):
    cur = db_rollback.cursor()
    did, cn = _draft(cur)
    cur.execute("insert into outreach.enrichment (company_number, contact_email, "
                "email_verified, contact_tier) values (%s,'ops@example.co.uk',true,'verified')",
                (cn,))
    cur.execute("insert into outreach.suppressions (email, reason) "
                "values ('ops@example.co.uk','opt-out')")
    outbox.send_now(did, requested_by="test", cur=cur)
    _age(cur, did, outbox.UNDO_SECONDS + 1)
    out = outbox.flush(dry_run=True, cur=cur)
    assert "suppressed" in out[0]["refused"]


def test_the_tick_is_the_safety_net_for_a_stranded_outbox_draft(db_rollback):
    """If the instance is torn down between the click and the sweep, the draft must
    still go out on the next tick rather than sitting in the outbox for ever — even
    though its scheduled slot is days away."""
    from outreach import run as run_mod
    cur = db_rollback.cursor()
    did, cn = _draft(cur)
    cur.execute("insert into outreach.enrichment (company_number, contact_email, "
                "email_verified, contact_tier) values (%s,'ops@example.co.uk',true,'verified')",
                (cn,))
    outbox.send_now(did, requested_by="test", cur=cur)
    _age(cur, did, outbox.UNDO_SECONDS + 1)
    out = run_mod._advance_sends(cur, dry_run=True)
    assert any(r.get("draft_id") == str(did) and r.get("status") == "dry_run_ok" for r in out)
    cur.execute("select outbox_at from outreach.drafts where id=%s", (did,))
    assert cur.fetchone()[0] is None


def test_a_future_slot_alone_is_not_due(db_rollback):
    """The counterpart: without the outbox the same draft must stay unsent, or the
    manual path would just be a way of sending everything immediately."""
    from outreach import run as run_mod
    cur = db_rollback.cursor()
    did, cn = _draft(cur)
    cur.execute("insert into outreach.enrichment (company_number, contact_email, "
                "email_verified, contact_tier) values (%s,'ops@example.co.uk',true,'verified')",
                (cn,))
    out = run_mod._advance_sends(cur, dry_run=True)
    assert not any(r.get("draft_id") == str(did) for r in out)
