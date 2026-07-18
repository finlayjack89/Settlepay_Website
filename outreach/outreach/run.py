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
from . import find_leads, followup, graduation, inbound, monitor, report, spend
from . import send as send_mod
from .sequence import in_send_window, load_sequence_config

FULL_CHAIN = ("inbound", "classify", "monitor", "discover", "enrich", "draft",
              "followup", "auto_approve", "send", "digest")
AUTONOMOUS_STAGES = ("discover", "enrich", "draft", "followup", "auto_approve")


def _advance_sends(cur, *, dry_run: bool) -> list[dict]:
    """One step: send each approved draft that has no send row yet."""
    cur.execute(
        "select d.id from outreach.drafts d "
        "join outreach.leads l on l.company_number = d.company_number "
        "where d.status = 'approved' "
        "and not exists (select 1 from outreach.sends s where s.draft_id = d.id) "
        "order by d.created_at")
    mode = "dry_run" if dry_run else "live"
    out: list[dict] = []
    for (draft_id,) in cur.fetchall():
        try:
            out.append(send_mod.send_one(draft_id, mode=mode, cur=cur))
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

    if want("discover"):
        do("discover", lambda: find_leads.run(
            target=config.DISCOVER_PER_TICK,
            sic_codes=config.TARGET_SIC_CODES or None))

    if want("enrich"):  # MillionVerifier + Firecrawl are paid
        do("enrich", lambda: enrich_mod.discover_and_run(
            limit=config.ENRICH_PER_TICK, cur=cur), paid=True)

    if want("draft"):
        do("draft", lambda: draft_mod.run(cur=cur, limit=config.DRAFT_PER_TICK),
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
