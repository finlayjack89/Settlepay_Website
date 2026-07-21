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
    # These gates read LIVE reservoir/credit state from the shared database, so
    # production data decides whether discover/enrich run at all — a full reservoir
    # legitimately skips discovery and made this order assertion fail. Pin them:
    # the subject here is stage ORDER, not the demand-pull arithmetic (covered in
    # test_reservoir.py).
    monkeypatch.setattr(run_mod.stats, "reservoir_status",
                        lambda *a, **k: {"ready": 0, "backlog": 0, "deficit": 50,
                                         "target": 50})
    monkeypatch.setattr(run_mod.stats, "credit_status",
                        lambda *a, **k: {"spent": 0.0, "budget": 237.0,
                                         "remaining": 237.0, "pct": 0.0,
                                         "days_left": 90})
    monkeypatch.setattr(run_mod.places, "discover_grid", rec("discover_places"))
    monkeypatch.setattr(run_mod.crossref, "run", rec("crossref"))
    monkeypatch.setattr(run_mod.decisionmakers, "run", rec("decision_makers", ret={}))


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
    monkeypatch.setattr(run_mod.config, "DM_ENABLED", True)
    res = run_mod.run(stage="all", dry_run=True, now=IN_WINDOW, cur=db_rollback.cursor())
    for s in ("discover", "enrich", "draft", "followup", "auto_approve"):
        assert s in res["steps"], s
    # decision_makers runs AFTER enrich (needs a domain) and BEFORE draft (so the send
    # can go to the named contact)
    assert order.index("monitor") < order.index("enrich") \
        < order.index("decision_makers") < order.index("draft") \
        < order.index("followup") < order.index("auto_approve")


def test_decision_makers_stage_is_skipped_when_disabled(db_rollback, monkeypatch):
    order = []
    _stub_stages(monkeypatch, order)
    monkeypatch.setattr(run_mod.config, "PIPELINE_AUTONOMOUS", True)
    monkeypatch.setattr(run_mod.config, "DM_ENABLED", False)
    res = run_mod.run(stage="all", dry_run=True, now=IN_WINDOW, cur=db_rollback.cursor())
    assert res["steps"]["decision_makers"] == {"skipped": "DECISION_MAKER_ENABLED off"}
    assert "decision_makers" not in order


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


def test_draft_stops_when_the_review_backlog_is_full(db_rollback, monkeypatch):
    """Drafting is the last credit-spending stage before the manual gate. Without a
    cap the pipeline pays to write email nobody has read yet, indefinitely."""
    order = []
    _stub_stages(monkeypatch, order)
    monkeypatch.setattr(run_mod.config, "PIPELINE_AUTONOMOUS", True)
    monkeypatch.setattr(run_mod.config, "DRAFT_BACKLOG_MAX", 10)
    monkeypatch.setattr(run_mod.stats, "review_backlog", lambda *a, **k: 10)
    res = run_mod.run(stage="all", dry_run=True, now=IN_WINDOW, cur=db_rollback.cursor())
    assert "skipped" in res["steps"]["draft"]
    assert "draft" not in order


def test_draft_runs_and_is_limited_by_remaining_backlog_room(db_rollback, monkeypatch):
    order = []
    _stub_stages(monkeypatch, order)
    monkeypatch.setattr(run_mod.config, "PIPELINE_AUTONOMOUS", True)
    monkeypatch.setattr(run_mod.config, "DRAFT_BACKLOG_MAX", 10)
    monkeypatch.setattr(run_mod.config, "DRAFT_PER_TICK", 10)
    monkeypatch.setattr(run_mod.stats, "review_backlog", lambda *a, **k: 7)
    captured = {}
    monkeypatch.setattr(run_mod.draft_mod, "run",
                        lambda **k: captured.update(k) or [])
    run_mod.run(stage="all", dry_run=True, now=IN_WINDOW, cur=db_rollback.cursor())
    assert captured["limit"] == 3      # only room for 3 more before the cap
