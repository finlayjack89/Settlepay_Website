"""Agents — a goal, a plan, a budget, and a brake.

Hermetic: the steps and the measure are fakes, so no stage runs and nothing is spent.
What is being tested is the LOOP, because the loop is what decides how many times a paid
thing happens.
"""
import pytest

from outreach import agents, jobs, targeting
from outreach import tasks as _tasks  # noqa: F401 — importing populates jobs.REGISTRY

pytestmark = pytest.mark.floor_h


class _Ctx:
    """Stands in for jobs.JobContext, and records what it was told."""

    def __init__(self, cancel_after=None):
        self.logs, self.progress_calls = [], []
        self._cancel_after, self._checks = cancel_after, 0

    def log(self, msg):
        self.logs.append(str(msg))

    def progress(self, done, total):
        self.progress_calls.append((done, total))

    def cancelled(self):
        self._checks += 1
        return self._cancel_after is not None and self._checks > self._cancel_after


class _Budget(agents.Budget):
    """A budget with a dial instead of a ledger."""

    def __init__(self, spent=0.0, limit=None):
        self.limit, self.start, self._spent = limit, 0.0, spent

    def spent(self, *, cur=None):
        return self._spent

    def exhausted(self, *, cur=None):
        return self.limit is not None and self._spent >= self.limit


def _counter(values):
    """A measure that walks a scripted sequence, then holds the last value."""
    seq = list(values)

    def measure():
        return seq.pop(0) if len(seq) > 1 else seq[0]
    return measure


def _step(name, moved=1, boom=False):
    def run():
        if boom:
            raise RuntimeError("stage exploded")
        return {"n": moved}
    return agents.Step(name, run, lambda r: int(r.get("n", 0)))


# --------------------------------------------------------------------------- #
#  Stopping conditions — the entire safety story
# --------------------------------------------------------------------------- #
def test_it_stops_when_the_target_is_reached():
    ctx = _Ctx()
    out = agents.pursue(ctx, goal="g", target=3, plan=[_step("a")],
                        measure=_counter([0, 1, 2, 3]), budget=_Budget())
    assert out["done"] == 3 and out["stopped"] == "target reached"


def test_it_stops_when_cancelled():
    """Cancel used to mark the row and let the work run to completion — the operator's
    stop was a label, not a brake."""
    ctx = _Ctx(cancel_after=1)
    out = agents.pursue(ctx, goal="g", target=1000, plan=[_step("a")],
                        measure=_counter([0]), budget=_Budget())
    assert out["stopped"] == "cancelled"
    assert out["passes"] < 5          # it stopped promptly, not after grinding on


def test_it_stops_at_its_own_spend_ceiling():
    """On top of the monthly cap, never instead of it: the monthly cap protects the card,
    this protects the operator from one click costing more than they meant."""
    ctx = _Ctx()
    out = agents.pursue(ctx, goal="g", target=1000, plan=[_step("a")],
                        measure=_counter([0]), budget=_Budget(spent=5.0, limit=5.0))
    assert "spend ceiling" in out["stopped"]
    assert out["passes"] == 0         # refused before doing any paid work


def test_it_gives_up_when_nothing_is_moving():
    """An unreachable target — an exhausted grid, a dry verifier — must not spin until the
    money runs out and then report failure having spent everything to learn nothing."""
    ctx = _Ctx()
    out = agents.pursue(ctx, goal="g", target=1000, plan=[_step("a", moved=0)],
                        measure=_counter([0]), budget=_Budget())
    assert "no progress" in out["stopped"]
    assert out["passes"] == agents.IDLE_PASSES


def test_progress_is_actually_reported():
    """The console has drawn a progress bar since the ops platform shipped and no task had
    ever called ctx.progress, so the bar was dead code and every long job looked exactly
    like a hung one."""
    ctx = _Ctx()
    # the first value is the BASELINE (progress is measured as movement from where the
    # run started, not from zero), so the script needs a repeat to report an opening 0
    agents.pursue(ctx, goal="g", target=2, plan=[_step("a")],
                  measure=_counter([0, 0, 1, 2]), budget=_Budget())
    assert ctx.progress_calls[0] == (0, 2)
    assert ctx.progress_calls[-1] == (2, 2)


# --------------------------------------------------------------------------- #
#  Resilience
# --------------------------------------------------------------------------- #
def test_one_failing_stage_does_not_end_the_run():
    """The other stages may still make progress, and the reason belongs in the log where
    the operator reads it."""
    ctx = _Ctx()
    out = agents.pursue(ctx, goal="g", target=2,
                        plan=[_step("bad", boom=True), _step("good")],
                        measure=_counter([0, 1, 2]), budget=_Budget())
    assert out["done"] == 2 and out["stopped"] == "target reached"
    assert out["steps"]["bad"]["error"] == "RuntimeError"
    assert any("stage exploded" in line for line in ctx.logs)


def test_a_skipped_stage_says_why_in_the_log():
    ctx = _Ctx()
    plan = [agents.Step("s", lambda: {"skipped": "reservoir full"}, lambda r: 0)]
    agents.pursue(ctx, goal="g", target=5, plan=plan, measure=_counter([0]),
                  budget=_Budget())
    assert any("reservoir full" in line for line in ctx.logs)


def test_progress_is_measured_from_the_world_not_from_step_returns():
    """Steps double-count (one lead is discovered AND enriched in a pass) and lie by
    omission (a lead discarded as not-ICP is work done but not progress). Only asking the
    database how many leads are in the target state cannot drift from what the operator
    sees."""
    ctx = _Ctx()
    out = agents.pursue(ctx, goal="g", target=2,
                        plan=[_step("a", moved=99)],          # claims a lot
                        measure=_counter([0, 1, 2]),          # world says otherwise
                        budget=_Budget())
    assert out["done"] == 2


# --------------------------------------------------------------------------- #
#  Aiming
# --------------------------------------------------------------------------- #
def test_a_named_slice_is_far_smaller_than_the_whole_grid():
    """The point of aiming. The full grid is ~14,700 queries and the credit runs out long
    before it does, so "auctioneers in Yorkshire" has to be a reachable 60."""
    aimed = targeting.places_queries(group="auctioneers", region="Yorkshire")
    assert 0 < len(aimed) < 200
    assert all("auction" in q.lower() or "saleroom" in q.lower() or "valuers" in q.lower()
               for q in aimed)
    assert all(any(t in q for t in targeting.places_towns_in("Yorkshire")) for q in aimed)


def test_an_unknown_slice_falls_back_to_everything_not_nothing():
    """An agent that quietly searched for zero things would report success having done
    nothing at all."""
    assert targeting.verticals_matching("nonsense") == list(targeting.PLACES_VERTICAL_QUERIES)
    assert targeting.places_towns_in("Atlantis") == list(dict.fromkeys(targeting.PLACES_TOWNS))


def test_a_region_cannot_invent_a_town_that_is_not_in_the_grid():
    for region in targeting.PLACES_REGIONS:
        for town in targeting.places_towns_in(region):
            assert town in targeting.PLACES_TOWNS


def test_an_aimed_run_uses_its_own_cursor(db_rollback, monkeypatch):
    """Sharing the global cursor would either skip most of the aimed slice or drag the
    scheduled sweep off course — and the operator would see neither happen."""
    import uuid

    from outreach import monitor, places

    cur = db_rollback.cursor()
    monkeypatch.setattr(places, "text_search", lambda q, **k: [])
    monitor.set_flag(places.GRID_CURSOR, "500", cur=cur)

    key = f"places_grid_cursor:test-{uuid.uuid4().hex[:6]}"
    res = places.discover_grid(count=2, cur=cur, group="auctioneers",
                               region="Yorkshire", cursor_key=key)
    assert res["cursor_key"] == key
    assert res["grid_size"] < 200                                   # the aimed slice
    assert monitor.get_flag(places.GRID_CURSOR, cur=cur) == "500"   # global untouched
    assert monitor.get_flag(key, cur=cur) == "2"


# --------------------------------------------------------------------------- #
#  Registration
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("kind", ["agent_gather", "agent_enrich", "agent_draft"])
def test_the_agents_are_launchable_from_the_console(kind):
    spec = jobs.REGISTRY[kind]
    assert spec.params and spec.description
    assert any(p.name == "max_spend_gbp" for p in spec.params), "every agent needs a ceiling"
    assert any(p.name == "target" for p in spec.params), "every agent needs a target"


def test_a_choice_param_refuses_a_value_the_form_would_never_offer():
    """Validated at coercion so a hand-rolled POST cannot smuggle one past the <select>."""
    spec = jobs.REGISTRY["agent_gather"]
    assert jobs.coerce_params(spec, {"vertical": "auctioneers"})["vertical"] == "auctioneers"
    with pytest.raises(ValueError):
        jobs.coerce_params(spec, {"vertical": "'; drop table leads--"})


def test_a_choice_param_renders_as_a_select():
    from outreach import web

    rendered = web._param_input(jobs.REGISTRY["agent_gather"].params[0])
    assert "<select" in rendered and 'value="auctioneers"' in rendered
