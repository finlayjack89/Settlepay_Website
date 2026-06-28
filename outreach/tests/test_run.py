import datetime
import uuid

import pytest

from outreach import run as run_mod
from outreach import sequence

pytestmark = pytest.mark.floor_h

# a Monday inside / outside the placeholder send window (09-17, Mon-Thu)
IN_WINDOW = datetime.datetime(2026, 6, 29, 10, 0)   # Mon 10:00
OUT_WINDOW = datetime.datetime(2026, 6, 29, 22, 0)  # Mon 22:00
WEEKEND = datetime.datetime(2026, 7, 4, 10, 0)      # Sat 10:00


# ---- config-driven timing (no hardcoded delays) ----
def test_send_window_is_config_driven():
    seq = sequence.load_sequence_config()
    assert sequence.in_send_window(seq, IN_WINDOW) is True
    assert sequence.in_send_window(seq, OUT_WINDOW) is False
    assert sequence.in_send_window(seq, WEEKEND) is False


def test_follow_up_delays_come_from_config():
    seq = {"follow_up_delays_days": [3, 7]}
    assert sequence.follow_up_delay_days(seq, 0) == 3
    assert sequence.follow_up_delay_days(seq, 1) == 7
    assert sequence.follow_up_delay_days(seq, 2) is None  # no more follow-ups


def test_graduation_thresholds_present():
    g = sequence.graduation_thresholds()
    assert g["min_reviewed_drafts_per_vertical"] == 50
    assert g["max_bounce_rate"] == 0.02
    assert 0 < g["min_approved_unedited_rate"] <= 1
    assert g["spot_check_ratio"] == 0.05


# ---- one step per tick ----
def test_tick_classifies_discovered(db_rollback):
    cur = db_rollback.cursor()
    cn = f"RUN_{uuid.uuid4().hex[:8]}"
    cur.execute(
        "insert into outreach.leads (company_number, company_name, company_type, state) "
        "values (%s,%s,'ltd','discovered')", (cn, cn))
    run_mod.run(stage="all", dry_run=True, now=IN_WINDOW, cur=cur)
    cur.execute("select subscriber_class::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "corporate"   # advanced one step (classified)


def test_tick_dry_run_sends_in_window(db_rollback):
    cur = db_rollback.cursor()
    cn = f"RUN_{uuid.uuid4().hex[:8]}"
    body = "Hi. FCA-regulated partners. unsubscribe. SettlePay"
    cur.execute(
        "insert into outreach.leads (company_number, company_name, company_type, "
        "subscriber_class, state) values (%s,%s,'ltd','corporate','approved')", (cn, cn))
    cur.execute(
        "insert into outreach.enrichment (company_number, contact_email, email_verified, signal) "
        "values (%s,%s,true,'s')", (cn, f"info-{uuid.uuid4().hex[:6]}@example.com"))
    cur.execute(
        "insert into outreach.drafts (company_number, body_original, body_final, prompt_version, "
        "status, decided_by, decided_at) values (%s,%s,%s,'placeholder-v0','approved','F',now())",
        (cn, body, body))
    run_mod.run(stage="send", dry_run=True, now=IN_WINDOW, cur=cur)
    cur.execute("select mode, status from outreach.sends where company_number=%s", (cn,))
    assert cur.fetchone() == ("dry_run", "dry_run_ok")


def test_tick_skips_send_outside_window(db_rollback):
    cur = db_rollback.cursor()
    res = run_mod.run(stage="send", dry_run=True, now=OUT_WINDOW, cur=cur)
    assert res["steps"]["send"] == {"skipped": "outside send window"}


def test_kill_switch_halts_tick(db_rollback, monkeypatch):
    monkeypatch.setattr(run_mod.send_mod.config, "KILL_SWITCH", "1")
    res = run_mod.run(stage="all", dry_run=True, now=IN_WINDOW, cur=db_rollback.cursor())
    assert res == {"halted": "kill switch ON"}
