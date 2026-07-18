import datetime

import pytest

from outreach import run as run_mod
from outreach import spend

pytestmark = pytest.mark.floor_h

IN_WINDOW = datetime.datetime(2026, 6, 30, 10, 0)  # Tue 10:00


def _stub_stages(monkeypatch, order):
    def rec(name, ret=None):
        def _f(*a, **k):
            order.append(name)
            return ret if ret is not None else {"stub": name}
        return _f
    monkeypatch.setattr(run_mod.find_leads, "run", rec("discover"))
    monkeypatch.setattr(run_mod.enrich_mod, "discover_and_run", rec("enrich"))
    monkeypatch.setattr(run_mod.draft_mod, "run", rec("draft", ret=[]))
    monkeypatch.setattr(run_mod.followup, "run", rec("followup", ret=[]))
    monkeypatch.setattr(run_mod.graduation, "run", rec("auto_approve", ret=[]))
    monkeypatch.setattr(run_mod.monitor, "check_and_pause",
                        rec("monitor", ret={"paused": False}))
    monkeypatch.setattr(run_mod.report, "send_daily_digest",
                        rec("digest", ret={"skipped": "no operator email"}))


def test_bare_tick_excludes_autonomous_stages(db_rollback, monkeypatch):
    order = []
    _stub_stages(monkeypatch, order)
    monkeypatch.setattr(run_mod.config, "PIPELINE_AUTONOMOUS", False)
    res = run_mod.run(stage="all", dry_run=True, now=IN_WINDOW, cur=db_rollback.cursor())
    assert "discover" not in res["steps"] and "enrich" not in res["steps"]
    assert "classify" in res["steps"] and "send" in res["steps"]
    assert "monitor" in res["steps"] and "digest" in res["steps"]


def test_autonomous_tick_runs_full_chain_in_order(db_rollback, monkeypatch):
    order = []
    _stub_stages(monkeypatch, order)
    monkeypatch.setattr(run_mod.config, "PIPELINE_AUTONOMOUS", True)
    res = run_mod.run(stage="all", dry_run=True, now=IN_WINDOW, cur=db_rollback.cursor())
    for s in ("discover", "enrich", "draft", "followup", "auto_approve"):
        assert s in res["steps"], s
    assert order.index("monitor") < order.index("discover") < order.index("enrich") \
        < order.index("draft") < order.index("followup") < order.index("auto_approve")


def test_single_stage_runs_without_autonomy_gate(db_rollback, monkeypatch):
    order = []
    _stub_stages(monkeypatch, order)
    monkeypatch.setattr(run_mod.config, "PIPELINE_AUTONOMOUS", False)
    res = run_mod.run(stage="enrich", cur=db_rollback.cursor())
    assert res["steps"] == {"enrich": {"stub": "enrich"}}


def test_stage_error_is_isolated(db_rollback, monkeypatch):
    order = []
    _stub_stages(monkeypatch, order)
    monkeypatch.setattr(run_mod.config, "PIPELINE_AUTONOMOUS", True)

    def _boom(*a, **k):
        raise RuntimeError("enrich exploded")
    monkeypatch.setattr(run_mod.enrich_mod, "discover_and_run", _boom)
    res = run_mod.run(stage="all", dry_run=True, now=IN_WINDOW, cur=db_rollback.cursor())
    assert "enrich exploded" in res["steps"]["enrich"]["error"]
    assert "draft" in res["steps"] and "send" in res["steps"]  # tick carried on


def test_spend_cap_skips_paid_stage(db_rollback, monkeypatch):
    order = []
    _stub_stages(monkeypatch, order)
    monkeypatch.setattr(run_mod.config, "PIPELINE_AUTONOMOUS", True)

    def _capped(cur=None):
        raise spend.SpendCapExceeded("over")
    monkeypatch.setattr(run_mod.spend, "ensure_under_cap", _capped)
    res = run_mod.run(stage="all", dry_run=True, now=IN_WINDOW, cur=db_rollback.cursor())
    assert res["steps"]["enrich"] == {"skipped": "monthly spend cap"}
    assert "classify" in res["steps"] and "send" in res["steps"]  # never spend-blocked


def test_monitor_trip_halts_tick(db_rollback, monkeypatch):
    order = []
    _stub_stages(monkeypatch, order)
    monkeypatch.setattr(run_mod.config, "PIPELINE_AUTONOMOUS", True)
    flags = iter([False, True])  # pre-tick check clean; post-monitor check tripped
    monkeypatch.setattr(run_mod.send_mod, "_kill_switch_on", lambda cur=None: next(flags))
    res = run_mod.run(stage="all", dry_run=True, now=IN_WINDOW, cur=db_rollback.cursor())
    assert res.get("halted") == "kill switch tripped by monitor"
    assert "discover" not in res["steps"]  # nothing after the trip
