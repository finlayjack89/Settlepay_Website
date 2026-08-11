"""Send leads whose FACTS predate the current enrichment back to be re-worked.

Every rejection a human has ever written on this pipeline is a facts error, not a prose
error — "Not london based but email says london", "wrong location", "Brand name is
yellowstone, not yellow", "Lead email doesn't match the company". The drafter was doing
its job faithfully; it was fed the wrong constants. So re-drafting alone (draft.redraft_stale)
cannot fix these: it rewrites the copy from the same stale block and reproduces the error
in fresher prose.

This module is the missing step in front of it. It retires the draft, returns the lead to
'enriched', and clears the markers that make the free re-resolution stages pick it up
again — the decision-maker waterfall (officers, PSC, the FAO tier) and the facts refresh
(trading location, region, vertical). The ordinary tick then does the work.

What it deliberately does NOT do:

- **It does not delete the enrichment row, or the contact address.** That address cost
  verifier credit, and all three verifiers are currently dry. Clearing it would force a
  re-verify that can only fail, and enrich._persist's unverifiable branch DISCARDS the
  lead — so a "clean slate" would destroy exactly the leads we had already paid to find.
  Only the DERIVED constants are cleared; the paid facts are kept.
- **It does not return the lead to 'discovered'.** That re-runs website resolution
  (Firecrawl, paid) and re-verification for no gain: the site and the mailbox are not
  what was wrong. 'enriched' is the state where the free stages can reach it.
- **It does not supersede an APPROVED draft.** An approval is a human decision and
  quietly rewriting it would be rewriting history. An approved draft is REJECTED with a
  recorded reason instead — a new decision, visible as one, attributed to the system so
  it can never be mistaken for human trust (see graduation._HUMAN_DECISION).
"""
from __future__ import annotations
from typing import Optional

from . import audit, db, states

REWORK_ACTOR = "system:rework"

# A lead is stale when its enrichment predates the decision-maker pipeline, which is
# checked by SHAPE rather than by date — the same reasoning as enrich._REFRESH_SQL. Two
# markers, either of which is enough:
#
#   dm_attempted_at is null   the decision-maker waterfall has never run on it, so nobody
#                             ever asked the register who runs this business. On the live
#                             database this is true of all 485 enrichment rows and 0
#                             officers are stored — the stage has never run in production.
#   location.value is null    the drafter had no trading town, which is the single most
#                             rejected fact. (0012's backfill deliberately left this null
#                             rather than inheriting the registered-office town.)
#
# Leads already carrying a named contact are excluded: they have been through the
# waterfall and re-running it buys nothing.
_STALE_SQL = """
select d.id, d.status, d.company_number, l.company_name, l.state::text,
       e.dm_attempted_at is null as never_dm,
       e.facts->'location'->>'value' is null as no_location
  from outreach.drafts d
  join outreach.leads l on l.company_number = d.company_number
  join outreach.enrichment e on e.company_number = d.company_number
 where d.status in ('awaiting_approval', 'approved')
   and l.state in ('drafted', 'approved')
   and e.contact_tier is distinct from 'named'
   and (e.dm_attempted_at is null or e.facts->'location'->>'value' is null)
 order by d.created_at
 limit %s
"""


def stale(cur, *, limit: int = 100) -> list[dict]:
    """What rework() would touch, without touching it. The console and the dry run
    both read this, so what is previewed is what happens."""
    cur.execute(_STALE_SQL, (limit,))
    return [{"draft_id": i, "draft_status": st, "company_number": cn, "company_name": nm,
             "lead_state": ls, "never_dm": ndm, "no_location": nloc}
            for i, st, cn, nm, ls, ndm, nloc in cur.fetchall()]


def _why(row: dict) -> str:
    bits = []
    if row["never_dm"]:
        bits.append("never through the decision-maker waterfall")
    if row["no_location"]:
        bits.append("no trading location resolved")
    return "; ".join(bits) or "facts predate the current enrichment"


def rework_lead(cur, row: dict, *, reason: Optional[str] = None) -> bool:
    """Retire one lead's draft and put the lead back in the enriched pool.

    Returns False when the lead moved underneath us (approved and sent between the
    backlog read and now) — the state predicate in each UPDATE is what makes that safe,
    so a race loses the rework, never the send.
    """
    cn, why = row["company_number"], reason or _why(row)

    if row["draft_status"] == "approved":
        cur.execute(
            "update outreach.drafts set status='rejected', decided_by=%s, decided_at=now(), "
            "  reviewer_note=%s "
            # not 'sent': a draft that has gone out is history, and there is no undoing it
            "where id=%s and status='approved'",
            (REWORK_ACTOR, f"reworked — {why}"[:500], row["draft_id"]))
    else:
        cur.execute(
            "update outreach.drafts set status='superseded' "
            "where id=%s and status='awaiting_approval'", (row["draft_id"],))
    if cur.rowcount != 1:
        return False

    cur.execute(
        "update outreach.leads set state='enriched', updated_at=now() "
        # the state list IS the guard: sent, sending, suppressed, bounced and replied are
        # all unreachable from here, so no rework can ever pull a lead back from contact
        "where company_number=%s and state in ('drafted','approved')", (cn,))
    if cur.rowcount != 1:
        return False

    cur.execute(
        # clearing these is the whole mechanism: dm_attempted_at gates the decision-maker
        # backlog and facts_refreshed_at gates the facts refresh, so nulling them is what
        # re-admits the lead to both. contact_email, contact_tier and the verify result
        # are untouched — they are the paid facts.
        "update outreach.enrichment set dm_attempted_at=null, facts_refreshed_at=null "
        "where company_number=%s", (cn,))

    audit.record(cn, "reworked", source="rework", lawful_basis=audit.LEGITIMATE_INTERESTS,
                 reason=f"draft retired and lead returned to the pool — {why}"[:400],
                 cur=cur)
    return True


def run(*, limit: int = 100, dry_run: bool = True, cur=None) -> dict:
    """Rework up to `limit` stale leads. Defaults to a DRY RUN: it reports exactly what
    it would do and writes nothing, so the blast radius is always inspected first."""
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    try:
        rows = stale(cur, limit=limit)
        out = {"stale": len(rows), "reworked": 0, "raced": 0, "dry_run": dry_run,
               "leads": [{"company_name": r["company_name"], "why": _why(r)} for r in rows]}
        if dry_run:
            return out
        for row in rows:
            cur.execute("savepoint rework_lead")
            try:
                if rework_lead(cur, row):
                    out["reworked"] += 1
                else:
                    out["raced"] += 1
                cur.execute("release savepoint rework_lead")
            except Exception:
                # one lead's failure must not roll back the batch — the same savepoint
                # discipline the tick uses per stage
                cur.execute("rollback to savepoint rework_lead")
                cur.execute("release savepoint rework_lead")
                out["raced"] += 1
        if own:
            conn.commit()
        return out
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        if own and conn is not None:
            conn.close()


# states is imported for the transition it authorises (drafted/approved -> enriched);
# referencing it here keeps that dependency explicit rather than implied by raw SQL.
assert states.can_transition(states.LeadState.DRAFTED, states.LeadState.ENRICHED)
assert states.can_transition(states.LeadState.APPROVED, states.LeadState.ENRICHED)
