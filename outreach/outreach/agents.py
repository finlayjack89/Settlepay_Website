"""Intent-shaped runs — "go and get me 300 auctioneer leads", not "run enrich, limit 10".

The console could already launch any pipeline stage, which is genuinely useful and stays.
But a stage is not a goal. "Enrich, limit 10" tells you nothing about whether ten was the
right number, when to stop, or what it cost; pursuing a target across several stages meant
a human sitting there launching them in order and watching the counts.

An agent is that human, written down. It has a target, a plan of stages to reach it, a hard
spend ceiling, and it stops when any of the three says so.

Three things make these different from a plain task, and all three are the point:

**They report real progress.** `ctx.progress(done, target)` on every pass. The console has
drawn a progress bar since the ops platform shipped and no task had ever called it, so the
bar was dead code and every long job looked identical to a hung one.

**They can actually be stopped.** `ctx.cancelled()` is checked between passes. Cancel used
to mark the row and let the work run to completion — the operator's "stop" was a label, not
a brake.

**They cannot outspend their brief.** Each run reads the spend ledger before every pass and
halts at its own ceiling, on top of (never instead of) the global monthly cap. An agent is
the one thing here that decides how many times to do a paid thing, so it is the one thing
that needs its own budget.

**The planner seam.** A run's work is `plan: list[Step]`, and `plan_for()` builds it
deterministically today. An LLM planner would return the same shape and change nothing
downstream — every step still goes through the same stage function, so the PECR gate, the
per-tick caps, the spend ledger and the audit trail apply to a planned run exactly as they
do to a fixed one. That is the whole reason the seam is a list of steps rather than a model
holding the loop.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional

from . import audit, db, spend

# A pass does a bounded amount of work and returns; the loop decides whether to go again.
# Bounded matters: an unbounded stage call inside a loop is two throttles fighting.
BATCH = 10

# Stop after this many passes that moved nothing, however much budget is left. Without it
# an agent whose target is unreachable (an exhausted grid, a dry verifier) spins until the
# money runs out and then reports failure, having spent everything to learn nothing.
IDLE_PASSES = 3


@dataclass(frozen=True)
class Step:
    """One stage invocation. `count` reads the stage's result and says how much progress
    it represents, so the loop never has to know what any particular stage returns."""
    stage: str
    run: Callable[..., dict]
    count: Callable[[dict], int] = lambda r: 0


class Budget:
    """A per-run cash ceiling, measured against the same ledger the monthly cap uses.

    Deliberately additive to `spend.ensure_under_cap`, never a replacement: the monthly cap
    protects the card, this protects the operator from a single click costing more than
    they meant. A run with no ceiling is bounded only by its target and IDLE_PASSES.
    """

    def __init__(self, limit_gbp: Optional[float], *, cur=None):
        self.limit = float(limit_gbp) if limit_gbp else None
        self.start = spend.month_total_gbp(cur=cur) if self.limit else 0.0

    def spent(self, *, cur=None) -> float:
        if self.limit is None:
            return 0.0
        return max(0.0, spend.month_total_gbp(cur=cur) - self.start)

    def exhausted(self, *, cur=None) -> bool:
        return self.limit is not None and self.spent(cur=cur) >= self.limit


class Outcome(dict):
    """The result shape every agent returns, so the console renders them all the same."""


def pursue(ctx, *, goal: str, target: int, plan: list[Step], measure: Callable[[], int],
           budget: Budget, cur=None) -> Outcome:
    """Run `plan` repeatedly until `measure()` reaches `target`, or something stops us.

    `measure` is a COUNT OF THE WORLD, not a running total of what the steps returned.
    That distinction is load-bearing: steps double-count (a lead can be discovered and then
    enriched in one pass) and they lie by omission (a lead discarded as not-ICP is work
    done but not progress). Asking the database how many leads are actually in the target
    state is the only measure that cannot drift away from what the operator sees.
    """
    done_at_start = measure()
    out = Outcome(goal=goal, target=target, start=done_at_start, done=0,
                  passes=0, stopped="target reached", steps={})
    idle = 0

    while True:
        done = measure() - done_at_start
        out["done"] = done
        ctx.progress(done, target)
        if done >= target:
            break
        if ctx.cancelled():
            out["stopped"] = "cancelled"
            break
        if budget.exhausted(cur=cur):
            out["stopped"] = f"spend ceiling reached (£{budget.spent(cur=cur):.2f})"
            break
        if idle >= IDLE_PASSES:
            out["stopped"] = f"no progress in {IDLE_PASSES} passes — nothing left to do"
            break

        moved = 0
        for step in plan:
            if ctx.cancelled():
                break
            try:
                res = step.run() or {}
            except Exception as e:
                # One stage failing is not the run failing: the others may still make
                # progress, and the reason belongs in the log where the operator reads it.
                ctx.log(f"{step.stage}: {type(e).__name__}: {e}"[:200])
                out["steps"].setdefault(step.stage, {})["error"] = f"{type(e).__name__}"
                continue
            got = step.count(res)
            moved += got
            tally = out["steps"].setdefault(step.stage, {"runs": 0, "moved": 0})
            tally["runs"] = tally.get("runs", 0) + 1
            tally["moved"] = tally.get("moved", 0) + got
            if res.get("skipped"):
                ctx.log(f"{step.stage}: {res['skipped']}")

        out["passes"] += 1
        idle = idle + 1 if moved == 0 else 0
        ctx.log(f"pass {out['passes']}: {out['done']}/{target} — "
                + ", ".join(f"{k} {v.get('moved', 0)}" for k, v in out["steps"].items()))

    out["spent_gbp"] = round(budget.spent(cur=cur), 2)
    ctx.log(f"{goal}: {out['done']}/{target} in {out['passes']} passes "
            f"(£{out['spent_gbp']:.2f}) — {out['stopped']}")
    audit.record(None, "agent_run", source="agents",
                 lawful_basis=audit.LEGITIMATE_INTERESTS,
                 reason=f"{goal}: {out['done']}/{target} — {out['stopped']}",
                 detail=dict(out), cur=cur)
    return out


# --------------------------------------------------------------------------- #
#  The three goals
# --------------------------------------------------------------------------- #
def _count(cur_factory, sql: str, params: tuple = ()) -> Callable[[], int]:
    """A measure that opens its own short connection each time. The agent's passes are
    long and networked; holding a transaction across them would pin it for minutes."""
    def measure() -> int:
        with cur_factory() as c:
            c.execute(sql, params)
            row = c.fetchone()
            return int(row[0]) if row and row[0] is not None else 0
    return measure


def gather(ctx, *, vertical: str = "all", region: str = "all", target: int = 50,
           max_spend_gbp: float = 5.0, campaign_id: Optional[int] = None) -> Outcome:
    """Find new corporate leads in a named slice of the market.

    Discovery alone is not the goal — a Places result is not a lead we may write to until
    the PECR cross-reference has said it is a company rather than a sole trader. So the
    plan is discover -> crossref, and the measure counts leads that have CLEARED that gate.

    With a `campaign_id` the run reads its slice, cursor and target from the campaign and
    attributes what it finds to it, so progress is a count of reality rather than a tally.
    """
    from . import campaigns, crossref, places

    camp = campaigns.get(campaign_id) if campaign_id else None
    if camp:
        vertical, region, target = camp["vertical"], camp["region"], camp["target"]
        key = camp["cursor_key"]
    group = None if vertical in ("", "all") else vertical
    area = None if region in ("", "all") else region
    if not camp:
        key = f"places_grid_cursor:{group or 'all'}:{area or 'all'}"

    def discover() -> dict:
        with db.cursor() as c:
            res = places.discover_grid(count=BATCH, cur=c, group=group, region=area,
                                       cursor_key=key)
            if camp:
                res["tagged"] = campaigns.tag(c, camp["id"], res.get("created") or [])
            return res

    plan = [
        Step("discover_places", discover, lambda r: int(r.get("inserted") or 0)),
        Step("crossref", lambda: crossref.run(limit=BATCH * 3),
             lambda r: int(r.get("corporate") or 0)),
    ]
    if camp:
        # measured against the CAMPAIGN's own leads, so two campaigns running the same
        # week cannot read each other's progress as their own
        measure = _count(lambda: db.cursor(commit=False),
                         "select count(*) from outreach.leads "
                         "where campaign_id = %s and subscriber_class = 'corporate'",
                         (camp["id"],))
        goal = f"campaign {camp['name']}"
    else:
        measure = _count(lambda: db.cursor(commit=False),
                         "select count(*) from outreach.leads "
                         "where subscriber_class='corporate'")
        goal = f"gather {group or 'all'}/{area or 'all'}"
    ctx.log(f"gathering {target} corporate leads · {group or 'every vertical'}"
            f" · {area or 'all regions'} · ceiling £{max_spend_gbp}")
    out = pursue(ctx, goal=goal, target=target, plan=plan, measure=measure,
                 budget=Budget(max_spend_gbp))
    if camp and out["done"] >= target:
        campaigns.set_status(camp["id"], campaigns.DONE, by="agent")
        ctx.log(f"campaign {camp['name']} reached its target and is marked done")
    return out


def enrich(ctx, *, scope: str = "unenriched", target: int = 50,
           max_spend_gbp: float = 5.0) -> Outcome:
    """Work leads up to the point where they can be written to.

    The three stages are one goal, not three: a lead with an address but no trading town
    still cannot be drafted truthfully, and one with both but no named human is a weaker
    email than it needs to be. Running them together is what "research and enrich this
    lead" actually means.
    """
    from . import decisionmakers
    from . import enrich as enrich_mod

    plan = [
        Step("enrich", lambda: enrich_mod.discover_and_run(limit=BATCH),
             lambda r: sum(1 for x in (r or []) if isinstance(x, dict)
                           and not x.get("disqualified") and not x.get("deferred"))
             if isinstance(r, list) else 0),
        Step("decision_makers", lambda: decisionmakers.run(limit=BATCH),
             lambda r: int(r.get("resolved") or 0) + int(r.get("fao") or 0)),
        Step("refresh_facts", lambda: enrich_mod.refresh_facts(limit=BATCH),
             lambda r: int(r.get("placed") or 0)),
    ]
    # "ready" is the honest target: enriched AND with the constants a truthful draft needs.
    measure = _count(lambda: db.cursor(commit=False),
                     "select count(*) from outreach.leads l "
                     "join outreach.enrichment e on e.company_number = l.company_number "
                     "where l.state = 'enriched' and e.facts is not null")
    ctx.log(f"enriching toward {target} draft-ready leads · scope {scope} "
            f"· ceiling £{max_spend_gbp}")
    return pursue(ctx, goal=f"enrich ({scope})", target=target, plan=plan,
                  measure=measure, budget=Budget(max_spend_gbp))


def write(ctx, *, target: int = 25, max_spend_gbp: float = 3.0) -> Outcome:
    """Draft emails for ready leads, and have the critic read each one.

    The critic is in the plan rather than left to the tick so that a run which produces
    drafts also produces the verdicts on them — a queue of unjudged drafts is exactly the
    state this was built to get out of.
    """
    from . import critic
    from . import draft as draft_mod

    plan = [
        Step("draft", lambda: draft_mod.run(limit=BATCH),
             lambda r: len(r) if isinstance(r, list) else 0),
        Step("critic", lambda: critic.run(limit=BATCH),
             lambda r: int(r.get("judged") or 0)),
    ]
    measure = _count(lambda: db.cursor(commit=False),
                     "select count(*) from outreach.drafts "
                     "where status = 'awaiting_approval'")
    ctx.log(f"drafting toward {target} in the queue · ceiling £{max_spend_gbp}")
    return pursue(ctx, goal="draft", target=target, plan=plan, measure=measure,
                  budget=Budget(max_spend_gbp))
