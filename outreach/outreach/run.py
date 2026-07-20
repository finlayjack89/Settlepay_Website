"""Phase H — operational wiring. One entrypoint advancing every lead one step per
tick (scheduler-, jobs- and /loop-friendly): `python -m outreach run --stage all`.

Full-chain stage order:

    inbound -> classify -> monitor -> [discover -> enrich -> draft -> followup
        -> auto_approve] -> send -> digest

The bracketed stages only join a bare `--stage all` tick when PIPELINE_AUTONOMOUS
is set — without it a tick stays the safe classify+send of the build, plus the
free/safety stages (inbound no-ops on the inline source; monitor; the digest is
date-throttled). Any stage remains independently invocable (`--stage enrich`),
autonomy gate or not — that's how the console's task launcher runs them.

Per-stage error isolation: one stage failing lands in the summary, never kills the
tick (savepoints under a shared test cursor; own connections per stage in
production, so network-heavy stages never hold a transaction open — the pooler
drops idle-in-transaction connections). Paid stages skip cleanly when the monthly
spend cap is hit; classify/inbound/send are never spend-blocked. Live sending
stays gated behind G-SEND regardless of --live.
"""
from __future__ import annotations

from . import config, db, firewall
from . import draft as draft_mod
from . import enrich as enrich_mod
from . import crossref, find_leads, followup, graduation, inbound, monitor, places
from . import report, spend, stats
from . import send as send_mod
from .sequence import in_send_window, load_sequence_config

FULL_CHAIN = ("inbound", "classify", "monitor", "discover_places", "crossref",
              "discover", "enrich", "draft", "followup", "auto_approve", "send", "digest")
AUTONOMOUS_STAGES = ("discover_places", "crossref", "discover", "enrich", "draft",
                     "followup", "auto_approve")


def _advance_sends(cur, *, dry_run: bool) -> list[dict]:
    """One step: send each approved draft whose scheduled slot has arrived.

    The `scheduled_at <= now()` filter is what paces sending. Without it this loop
    fired every approved draft at once, which at the 50/day ceiling is a burst of
    50 cold emails in seconds. Drafts approved before the queue existed have a NULL
    slot and stay eligible immediately, so nothing already approved gets stranded.
    """
    cur.execute(
        "select d.id from outreach.drafts d "
        "join outreach.leads l on l.company_number = d.company_number "
        "where d.status = 'approved' "
        "and (d.scheduled_at is null or d.scheduled_at <= now()) "
        "and not exists (select 1 from outreach.sends s where s.draft_id = d.id) "
        "order by d.scheduled_at nulls first, d.created_at")
    mode = "dry_run" if dry_run else "live"
    out: list[dict] = []
    sent = 0
    for (draft_id,) in cur.fetchall():
        # SEND_PER_TICK smooths catch-up: after downtime several slots are due at
        # once, and firing them together is the burst the queue exists to prevent.
        if sent >= config.SEND_PER_TICK:
            out.append({"deferred": "SEND_PER_TICK reached; remaining slots roll to the next tick"})
            break
        try:
            out.append(send_mod.send_one(draft_id, mode=mode, cur=cur))
            sent += 1
        except send_mod.SendRefused as e:
            out.append({"draft_id": str(draft_id), "refused": str(e)})
    return out


def _own(fn):
    """Run fn(cur) on a short-lived own connection (production path)."""
    conn = db.connect()
    try:
        with conn.cursor() as c:
            out = fn(c)
        conn.commit()
        return out
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run(*, stage: str = "all", dry_run: bool = True, now=None, cur=None) -> dict:
    if send_mod._kill_switch_on(cur):
        return {"halted": "kill switch ON"}

    seq = load_sequence_config()
    summary: dict = {"stage": stage, "dry_run": dry_run, "steps": {}}

    def want(name: str) -> bool:
        if stage == "all":
            return name not in AUTONOMOUS_STAGES or config.PIPELINE_AUTONOMOUS
        return stage == name

    def do(name: str, fn, *, paid: bool = False) -> None:
        if paid:
            try:
                spend.ensure_under_cap(cur=cur)
            except spend.SpendCapExceeded:
                summary["steps"][name] = {"skipped": "monthly spend cap"}
                return
        try:
            if cur is not None:
                cur.execute("savepoint tick_stage")
            summary["steps"][name] = fn()
            if cur is not None:
                cur.execute("release savepoint tick_stage")
        except Exception as e:
            if cur is not None:
                try:
                    cur.execute("rollback to savepoint tick_stage")
                except Exception:
                    pass
            summary["steps"][name] = {"error": f"{type(e).__name__}: {e}"[:300]}

    if want("inbound"):
        if config.INBOUND_SOURCE == "inline":
            summary["steps"]["inbound"] = {"skipped": "inline source (no live mailbox)"}
        else:
            do("inbound", lambda: inbound.run(cur=cur))

    if want("classify"):
        do("classify", lambda: firewall.run(cur=cur))

    if want("monitor"):
        do("monitor", lambda: monitor.check_and_pause(cur=cur))
        # a breach this tick trips the DB kill switch — abort the rest immediately
        if send_mod._kill_switch_on(cur):
            summary["halted"] = "kill switch tripped by monitor"
            return summary

    # Demand-pull reservoir: discover/enrich run only to refill the ready pool
    # toward READY_POOL_TARGET, then idle (£0) when it's full — this is what
    # amortises the expensive stages. Deficit is computed once per tick.
    pool = stats.reservoir_status(cur, config.READY_POOL_TARGET) if cur is not None else None

    if want("discover_places"):  # Google Places (GCP credit) — credit-gated, NOT enriched-pool-gated
        # Discovery is cheap on credit and should build a big classified reservoir, so it
        # is gated by the CREDIT budget + a backlog cap, not the (cash-bound) enriched pool.
        credit = stats.credit_status(cur) if cur is not None else None
        if credit and credit["remaining"] <= config.CREDIT_FLOOR_GBP:
            summary["steps"]["discover_places"] = {"skipped": "credit budget floor reached", **credit}
        elif pool and pool["backlog"] >= config.CLASSIFIED_BACKLOG_MAX:
            summary["steps"]["discover_places"] = {"skipped": "classified backlog full", **pool}
        else:  # credit-billed, not cash — the credit gate above is the control
            do("discover_places",
               lambda: places.discover_grid(count=config.PLACES_PER_TICK, cur=cur))

    if want("crossref"):  # PECR gate for Places leads — classify corporate vs research-only
        do("crossref", lambda: crossref.run(limit=config.CROSSREF_PER_TICK, cur=cur))

    if want("discover"):
        if pool and pool["deficit"] <= 0:
            summary["steps"]["discover"] = {"skipped": "reservoir full", **pool}
        else:
            # only fetch raw leads if the discovered backlog can't cover the deficit
            need = min(config.DISCOVER_PER_TICK,
                       max(0, pool["deficit"] - pool["backlog"])) if pool else config.DISCOVER_PER_TICK
            if need <= 0:
                summary["steps"]["discover"] = {"skipped": "backlog covers deficit", **(pool or {})}
            else:
                do("discover", lambda: find_leads.run(
                    target=need, sic_codes=config.TARGET_SIC_CODES or None))

    if want("enrich"):  # MillionVerifier + Firecrawl are paid
        if pool and pool["deficit"] <= 0:
            summary["steps"]["enrich"] = {"skipped": "reservoir full", **pool}
        else:
            limit = min(config.ENRICH_PER_TICK, pool["deficit"]) if pool else config.ENRICH_PER_TICK
            do("enrich", lambda: enrich_mod.discover_and_run(limit=limit, cur=cur), paid=True)

    if want("draft"):
        backlog = stats.review_backlog(cur) if cur is not None else 0
        if backlog >= config.DRAFT_BACKLOG_MAX:
            # the human gate is the bottleneck; drafting past it just spends credit
            summary["steps"]["draft"] = {"skipped": "review backlog full",
                                         "awaiting_approval": backlog,
                                         "max": config.DRAFT_BACKLOG_MAX}
        else:
            do("draft", lambda: draft_mod.run(
                cur=cur, limit=min(config.DRAFT_PER_TICK,
                                   config.DRAFT_BACKLOG_MAX - backlog)),
               paid=(config.LLM_PROVIDER == "api"))

    if want("followup"):
        do("followup", lambda: followup.run(cur=cur, limit=config.FOLLOWUP_PER_TICK),
           paid=(config.LLM_PROVIDER == "api"))

    if want("auto_approve"):
        do("auto_approve", lambda: graduation.run(cur=cur))

    if want("send"):
        if in_send_window(seq, now):
            do("send", lambda: (_advance_sends(cur, dry_run=dry_run) if cur is not None
                                else _own(lambda c: _advance_sends(c, dry_run=dry_run))))
        else:
            summary["steps"]["send"] = {"skipped": "outside send window"}

    if want("digest"):
        do("digest", lambda: report.send_daily_digest(cur=cur))

    return summary
