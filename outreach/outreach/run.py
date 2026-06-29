"""Phase H — operational wiring. One entrypoint advancing each lead one step per
tick (cron- and /loop-friendly): `python -m outreach run --stage all --dry-run`.

A tick is SAFE and idempotent: it checks the kill switch, classifies any
unclassified leads (PECR firewall), and dry-run-sends approved drafts that haven't
been sent — but only inside the configured send window (timing is config-driven via
sequence_config, never hardcoded). The spend/loop-agent stages (find_leads, enrich,
draft) are deliberately NOT auto-run in a blind tick: discovery + enrichment cost
money and drafting needs the inline loop agent; those are invoked explicitly.
Live sending stays gated behind G-SEND regardless of --live.
"""
from __future__ import annotations
from typing import Optional

from . import db, firewall
from . import send as send_mod
from .sequence import in_send_window, load_sequence_config


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


def run(*, stage: str = "all", dry_run: bool = True, now=None, cur=None) -> dict:
    if send_mod._kill_switch_on():
        return {"halted": "kill switch ON"}

    seq = load_sequence_config()
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    summary: dict = {"stage": stage, "dry_run": dry_run, "steps": {}}
    try:
        if stage in ("all", "classify"):
            summary["steps"]["classify"] = firewall.run(cur=cur)
        if stage in ("all", "send"):
            if in_send_window(seq, now):
                summary["steps"]["send"] = _advance_sends(cur, dry_run=dry_run)
            else:
                summary["steps"]["send"] = {"skipped": "outside send window"}
        if own:
            conn.commit()
        return summary
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        if own and conn is not None:
            conn.close()
