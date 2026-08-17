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
import datetime
import json

from . import config, control, db, firewall
from . import critic as critic_mod
from . import decisionmakers, draft as draft_mod
from . import enrich as enrich_mod
from . import crossref, find_leads, followup, graduation, inbound, monitor, outbox, places
from . import report, spend, stats
from . import send as send_mod
from .sequence import in_send_window, load_sequence_config

FULL_CHAIN = ("inbound", "classify", "monitor", "discover_places", "crossref",
              "discover", "enrich", "decision_makers", "draft", "critic", "followup",
              "auto_approve", "send", "digest")
AUTONOMOUS_STAGES = ("discover_places", "crossref", "discover", "enrich",
                     "decision_makers", "draft", "critic", "followup", "auto_approve")


def _advance_sends(cur, *, dry_run: bool) -> list[dict]:
    """One step: send each approved draft whose scheduled slot has arrived.

    The `scheduled_at <= now()` filter is what paces sending. Without it this loop
    fired every approved draft at once, which at the 50/day ceiling is a burst of
    50 cold emails in seconds. Drafts approved before the queue existed have a NULL
    slot and stay eligible immediately, so nothing already approved gets stranded.

    A draft in the OUTBOX (manual "send now", undo window elapsed) is due whatever
    its slot says. The sweeper thread normally gets there first — this is the safety
    net for a manual send whose instance was torn down before the sweep ran, so it
    goes out late rather than sitting in the outbox for ever.
    """
    mode = "dry_run" if dry_run else "live"
    cur.execute(
        "select d.id from outreach.drafts d "
        "join outreach.leads l on l.company_number = d.company_number "
        "where d.status = 'approved' "
        "and (d.scheduled_at is null or d.scheduled_at <= now() "
        f"     or d.outbox_at + interval '{outbox.UNDO_SECONDS} seconds' <= now()) "
        # mode-aware: a prior dry-run must not block the live send (that was the bug that
        # burned a manually-sent draft); the SAME-mode check still prevents dry-run spam.
        "and not exists (select 1 from outreach.sends s where s.draft_id = d.id and s.mode = %s) "
        "order by d.outbox_at nulls last, d.scheduled_at nulls first, d.created_at", (mode,))
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
        # leave the outbox empty either way: a refused manual send that stayed in it
        # would be retried on every tick and every sweep, for ever
        cur.execute("update outreach.drafts set outbox_at = null "
                    "where id = %s and outbox_at is not null", (draft_id,))
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
    # The allowlist is read ONCE per tick, not per stage: a control change landing halfway
    # through would otherwise produce a tick that half-honoured it, which is the kind of
    # result nobody can reproduce afterwards.
    enabled_stages = control.autonomous_stages(cur=cur)
    # Recorded on every tick: 27 days of identical, silent results were only readable
    # in hindsight because nothing in the output said which stages were even eligible.
    summary["autonomous"] = (
        "all" if config.PIPELINE_AUTONOMOUS else (list(enabled_stages) or "none"))

    def want(name: str) -> bool:
        """Which stages this tick runs.

        A NAMED stage always runs — that is how an operator exercises one deliberately.
        On `all`, the non-autonomous stages (inbound, classify, monitor, send, digest)
        always run, and a self-driving stage runs only if it is switched on.

        The switch is an ALLOWLIST, not a boolean. PIPELINE_AUTONOMOUS turned all eight
        expensive stages on together, which is the one change whose effects cannot be
        attributed: if spend or volume moves, you cannot tell which stage moved it. With
        an allowlist a stage is enabled, watched for a day, and the next one added.

        The list now comes from `control`, so it is settable from the dashboard rather
        than only by a Cloud Run revision — which is what left this pipeline idle for a
        fortnight with no way to restart it from the console.
        """
        if stage != "all":
            return stage == name
        if name not in AUTONOMOUS_STAGES:
            return True
        return bool(config.PIPELINE_AUTONOMOUS or "all" in enabled_stages
                    or name in enabled_stages)

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

    def _read(fn):
        """Evaluate a read-only gate query, on the caller's cursor when there is one
        and otherwise on a short-lived own connection.

        These gates used to be written `x = f(cur) if cur is not None else None`, and
        the SCHEDULED TICK — the only caller that matters — passes no cursor. So in
        production the reservoir, the GCP-credit floor and the review-backlog cap all
        evaluated to None and every `if pool and …` guard fell through: unbounded
        Places spend, unbounded enrichment, unbounded drafting. Every test passed a
        cursor, so the suite only ever exercised the branch production never took.
        """
        return fn(cur) if cur is not None else _own(fn)

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

    # Every limit and target below comes from `control`, not `config`, so the operator can
    # retune the pipeline from the dashboard without a Cloud Run revision. The values are
    # read once here for the same reason the allowlist is: a tick that half-honoured a
    # mid-flight change would be unreproducible.
    knob = {name: control.get(name, cur=cur) for name in (
        "READY_POOL_TARGET", "PLACES_PER_TICK", "CROSSREF_PER_TICK", "DISCOVER_PER_TICK",
        "ENRICH_PER_TICK", "DM_PER_TICK", "DRAFT_PER_TICK", "CRITIC_PER_TICK",
        "FOLLOWUP_PER_TICK", "DRAFT_BACKLOG_MAX", "CREDIT_FLOOR_GBP", "DM_ENABLED")}
    summary["controls"] = {k: v for k, v in knob.items()}

    # Demand-pull reservoir: discover/enrich run only to refill the ready pool
    # toward READY_POOL_TARGET, then idle (£0) when it's full — this is what
    # amortises the expensive stages. Deficit is computed once per tick.
    pool = _read(lambda c: stats.reservoir_status(c, knob["READY_POOL_TARGET"]))

    if want("discover_places"):  # Google Places (GCP credit) — credit-gated, NOT enriched-pool-gated
        # Discovery is cheap on credit and should build a big classified reservoir, so it
        # is gated by the CREDIT budget + a backlog cap, not the (cash-bound) enriched pool.
        credit = _read(stats.credit_status)
        if credit and credit["remaining"] <= knob["CREDIT_FLOOR_GBP"]:
            summary["steps"]["discover_places"] = {"skipped": "credit budget floor reached", **credit}
        elif pool and pool["backlog"] >= config.CLASSIFIED_BACKLOG_MAX:
            summary["steps"]["discover_places"] = {"skipped": "classified backlog full", **pool}
        else:  # credit-billed, not cash — the credit gate above is the control
            do("discover_places",
               lambda: places.discover_grid(count=knob["PLACES_PER_TICK"], cur=cur))

    if want("crossref"):  # PECR gate for Places leads — classify corporate vs research-only
        do("crossref", lambda: crossref.run(limit=knob["CROSSREF_PER_TICK"], cur=cur))

    if want("discover"):
        if pool and pool["deficit"] <= 0:
            summary["steps"]["discover"] = {"skipped": "reservoir full", **pool}
        else:
            # only fetch raw leads if the discovered backlog can't cover the deficit
            need = min(knob["DISCOVER_PER_TICK"],
                       max(0, pool["deficit"] - pool["backlog"])) if pool else knob["DISCOVER_PER_TICK"]
            if need <= 0:
                summary["steps"]["discover"] = {"skipped": "backlog covers deficit", **(pool or {})}
            else:
                do("discover", lambda: find_leads.run(
                    target=need, sic_codes=config.TARGET_SIC_CODES or None))

    if want("enrich"):  # MillionVerifier + Firecrawl are paid
        if pool and pool["deficit"] <= 0:
            summary["steps"]["enrich"] = {"skipped": "reservoir full", **pool}
        else:
            limit = min(knob["ENRICH_PER_TICK"], pool["deficit"]) if pool else knob["ENRICH_PER_TICK"]
            do("enrich", lambda: enrich_mod.discover_and_run(limit=limit, cur=cur), paid=True)

    if want("decision_makers"):  # Companies House officers -> inferred named email (MV, paid)
        if not knob["DM_ENABLED"]:
            summary["steps"]["decision_makers"] = {"skipped": "decision-maker lookup switched off"}
        else:
            do("decision_makers",
               lambda: decisionmakers.run(cur=cur, limit=knob["DM_PER_TICK"]), paid=True)

    if want("draft"):
        backlog = _read(stats.review_backlog)
        if backlog >= knob["DRAFT_BACKLOG_MAX"]:
            # the human gate is the bottleneck; drafting past it just spends credit
            summary["steps"]["draft"] = {"skipped": "review backlog full",
                                         "awaiting_approval": backlog,
                                         "max": knob["DRAFT_BACKLOG_MAX"]}
        else:
            do("draft", lambda: draft_mod.run(
                cur=cur, limit=min(knob["DRAFT_PER_TICK"],
                                   knob["DRAFT_BACKLOG_MAX"] - backlog)),
               paid=(config.LLM_PROVIDER == "api"))

    if want("critic"):  # OpenAI, cash-billed — an independent read of each new draft
        # Deliberately AFTER draft and BEFORE auto_approve: it judges what was just
        # written, and in shadow mode auto_approve does not consult it. When it does
        # graduate to 'gate', this ordering is what puts it in front of the approval.
        do("critic", lambda: critic_mod.run(cur=cur, limit=knob["CRITIC_PER_TICK"]),
           paid=True)

    if want("followup"):
        do("followup", lambda: followup.run(cur=cur, limit=knob["FOLLOWUP_PER_TICK"]),
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

    # Keep the last summary where the console can read it. Every stage already records
    # WHY it did nothing ("reservoir full", "outside send window", "credit budget floor
    # reached") — that reasoning was written to a job row nobody opens and then lost. It
    # is the single most useful thing the control room can show, so it is persisted here
    # rather than reconstructed from counters that cannot explain themselves.
    if stage == "all":
        _remember_tick(summary, cur=cur)
    return summary


def _remember_tick(summary: dict, *, cur=None) -> None:
    """Best-effort. A tick that did real work must never fail because the console's
    status cache could not be written."""
    from . import monitor

    try:
        payload = json.dumps({"at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                              "autonomous": summary.get("autonomous"),
                              "controls": summary.get("controls", {}),
                              "steps": summary.get("steps", {})}, default=str)[:20000]
        monitor.set_flag("last_tick_summary", payload,
                         reason="tick status cache", updated_by="tick", cur=cur)
    except Exception:
        pass
