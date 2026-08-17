"""Runtime controls — precedence, the ratchet, and the fail direction.

The load-bearing properties: a dashboard override can retune the pipeline but can never
loosen a spend bound, can never touch G-SEND, and a database problem falls back to the
DEPLOYED value rather than to something permissive.
"""
import pytest

from outreach import config, control, monitor

pytestmark = pytest.mark.floor_h


@pytest.fixture
def clean(db_rollback):
    """Every test runs on a rolled-back cursor, so overrides never leak to the live DB."""
    return db_rollback.cursor()


# --------------------------------------------------------------------------- #
#  Precedence
# --------------------------------------------------------------------------- #
def test_the_deployed_value_is_used_when_nothing_is_set(clean):
    assert control.get("ENRICH_PER_TICK", cur=clean) == config.ENRICH_PER_TICK


def test_an_override_wins_over_the_deployed_value(clean):
    control.set("ENRICH_PER_TICK", 25, by="finlay", reason="clearing the backlog", cur=clean)
    assert control.get("ENRICH_PER_TICK", cur=clean) == 25
    assert control.is_overridden("ENRICH_PER_TICK", cur=clean)


def test_clearing_returns_to_the_deployed_value(clean):
    control.set("ENRICH_PER_TICK", 25, by="finlay", cur=clean)
    control.clear("ENRICH_PER_TICK", by="finlay", cur=clean)
    assert control.get("ENRICH_PER_TICK", cur=clean) == config.ENRICH_PER_TICK


def test_controls_are_namespaced_away_from_the_kill_switch(clean):
    """ops_flags also holds kill_switch, places_grid_cursor and the digest throttle. A
    control called 'kill_switch' must not be able to reach any of them."""
    control.set("ENRICH_PER_TICK", 7, by="t", cur=clean)
    assert monitor.get_flag("control:ENRICH_PER_TICK", cur=clean) == "7"
    assert monitor.get_flag("ENRICH_PER_TICK", cur=clean) is None


def test_every_change_records_who_and_why(clean):
    control.set("DM_ENABLED", True, by="finlay", reason="turning the waterfall on", cur=clean)
    clean.execute("select updated_by, reason from outreach.ops_flags where key=%s",
                  ("control:DM_ENABLED",))
    by, reason = clean.fetchone()
    assert by == "finlay" and "waterfall" in reason
    clean.execute("select count(*) from outreach.audit_log "
                  "where event='control_changed' and reason like %s", ("%DM_ENABLED%",))
    assert clean.fetchone()[0] >= 1


def test_a_change_must_name_someone(clean):
    with pytest.raises(ValueError):
        control.set("ENRICH_PER_TICK", 5, by="", cur=clean)


# --------------------------------------------------------------------------- #
#  The fail direction — opposite to the kill switch, on purpose
# --------------------------------------------------------------------------- #
def test_a_database_problem_falls_back_to_the_deployed_value(monkeypatch):
    """monitor.db_kill_switch fails OPEN, which is right for a kill switch — one that
    jams on is its own outage. An autonomy allowlist failing open would do the reverse:
    a database blip would start running paid stages unattended. So this falls CLOSED."""
    def boom(*a, **k):
        raise RuntimeError("db unreachable")

    # control imports monitor lazily inside get(), so patching the module attribute is
    # what the resolver will actually reach
    monkeypatch.setattr(monitor, "get_flag", boom)
    assert control.get("AUTONOMOUS_STAGES") == config.AUTONOMOUS_STAGES_ENABLED
    assert control.get("ENRICH_PER_TICK") == config.ENRICH_PER_TICK


def test_unparseable_stored_value_falls_back_rather_than_crashing(clean):
    monitor.set_flag("control:ENRICH_PER_TICK", "not-a-number", cur=clean)
    assert control.get("ENRICH_PER_TICK", cur=clean) == config.ENRICH_PER_TICK


# --------------------------------------------------------------------------- #
#  The ratchet — tighten only
# --------------------------------------------------------------------------- #
def test_a_spend_cap_can_be_lowered(clean):
    lower = config.MONTHLY_SPEND_CAP_GBP - 10
    control.set("MONTHLY_SPEND_CAP_GBP", lower, by="finlay", cur=clean)
    assert control.get("MONTHLY_SPEND_CAP_GBP", cur=clean) == lower


def test_a_spend_cap_cannot_be_raised(clean):
    """The deploy is the outer bound. No amount of clicking can spend more than it allowed."""
    with pytest.raises(control.NotSettable):
        control.set("MONTHLY_SPEND_CAP_GBP", config.MONTHLY_SPEND_CAP_GBP + 100,
                    by="finlay", cur=clean)


def test_a_credit_floor_can_only_be_raised(clean):
    """Higher is safer here — discovery stops sooner and leaves more credit — so the
    ratchet runs the other way. A knob whose safe direction is assumed rather than
    declared is a knob that will eventually be wrong."""
    control.set("CREDIT_FLOOR_GBP", config.CREDIT_FLOOR_GBP + 5, by="finlay", cur=clean)
    with pytest.raises(control.NotSettable):
        control.set("CREDIT_FLOOR_GBP", max(0, config.CREDIT_FLOOR_GBP - 5),
                    by="finlay", cur=clean)


def test_a_hand_written_loosening_is_still_ignored_on_read(clean):
    """Belt and braces: even a value poked straight into the table cannot loosen the bound."""
    monitor.set_flag("control:MONTHLY_SPEND_CAP_GBP", "99999", cur=clean)
    assert control.get("MONTHLY_SPEND_CAP_GBP", cur=clean) == config.MONTHLY_SPEND_CAP_GBP


# --------------------------------------------------------------------------- #
#  env_only — the ones the browser may never touch
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["G_SEND", "KILL_SWITCH", "AUTO_APPROVE_ENABLED"])
def test_the_protected_gates_cannot_be_set_from_here(clean, name):
    with pytest.raises(control.NotSettable):
        control.set(name, True, by="finlay", cur=clean)
    with pytest.raises(control.NotSettable):
        control.clear(name, by="finlay", cur=clean)


def test_a_protected_gate_ignores_a_planted_override(clean):
    """G-SEND is human-only by standing rule. Even if a row appeared in ops_flags, the
    read path must not honour it."""
    monitor.set_flag("control:G_SEND", "1", cur=clean)
    assert control.get("G_SEND", cur=clean) == config.G_SEND


# --------------------------------------------------------------------------- #
#  Bounds
# --------------------------------------------------------------------------- #
def test_values_outside_the_declared_bounds_are_refused(clean):
    with pytest.raises(ValueError):
        control.set("ENRICH_PER_TICK", -1, by="t", cur=clean)
    with pytest.raises(ValueError):
        control.set("ENRICH_PER_TICK", 10_000, by="t", cur=clean)


def test_a_choice_control_refuses_an_unknown_value(clean):
    control.set("CRITIC_MODE", "gate", by="t", cur=clean)
    with pytest.raises(ValueError):
        control.set("CRITIC_MODE", "whatever", by="t", cur=clean)


def test_an_unknown_control_is_refused(clean):
    with pytest.raises(KeyError):
        control.set("NOT_A_CONTROL", 1, by="t", cur=clean)


# --------------------------------------------------------------------------- #
#  Stage autonomy — one row at a time
# --------------------------------------------------------------------------- #
def test_toggling_one_stage_leaves_the_others_alone(clean):
    control.set("AUTONOMOUS_STAGES", ("crossref",), by="t", cur=clean)
    control.set_stage("enrich", True, by="finlay", reason="clearing the backlog", cur=clean)
    stages = control.autonomous_stages(cur=clean)
    assert "crossref" in stages and "enrich" in stages

    control.set_stage("crossref", False, by="finlay", cur=clean)
    stages = control.autonomous_stages(cur=clean)
    assert "crossref" not in stages and "enrich" in stages


def test_turning_a_stage_off_works_even_when_the_list_says_all(clean):
    """"all" is a wildcard, so removing one name from it does nothing unless it is
    expanded first — the toggle would silently fail to switch the stage off."""
    from outreach.run import AUTONOMOUS_STAGES

    control.set("AUTONOMOUS_STAGES", ("all",), by="t", cur=clean)
    control.set_stage("enrich", False, by="finlay", cur=clean)
    stages = control.autonomous_stages(cur=clean)
    assert "enrich" not in stages
    assert "draft" in stages          # everything else survived the expansion
    assert set(stages) == set(AUTONOMOUS_STAGES) - {"enrich"}


def test_stage_enabled_reads_the_override(clean):
    control.set("AUTONOMOUS_STAGES", ("enrich",), by="t", cur=clean)
    assert control.stage_enabled("enrich", cur=clean)
    assert not control.stage_enabled("draft", cur=clean)


def test_the_tick_honours_a_dashboard_allowlist(db_rollback, monkeypatch):
    """The whole point: switching a stage on from the console changes what the scheduled
    tick does, with no redeploy."""
    from outreach import run as run_mod

    cur = db_rollback.cursor()
    monkeypatch.setattr(run_mod.config, "PIPELINE_AUTONOMOUS", False)
    control.set("AUTONOMOUS_STAGES", ("crossref",), by="t", cur=cur)

    summary = run_mod.run(stage="all", dry_run=True, cur=cur)
    assert summary["autonomous"] == ["crossref"]
    assert "enrich" not in summary["steps"]

    control.set_stage("enrich", True, by="finlay", cur=cur)
    summary = run_mod.run(stage="all", dry_run=True, cur=cur)
    assert "enrich" in summary["steps"]


def test_the_snapshot_shows_effective_and_deployed_side_by_side(clean):
    """The control room has to show both, or an operator cannot tell what they changed."""
    control.set("ENRICH_PER_TICK", 33, by="t", cur=clean)
    row = next(r for r in control.snapshot(cur=clean) if r["name"] == "ENRICH_PER_TICK")
    assert row["value"] == 33
    assert row["default"] == config.ENRICH_PER_TICK
    assert row["overridden"] is True
