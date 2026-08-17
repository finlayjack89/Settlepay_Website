"""Per-vertical graduation auto-approve (drafts -> 'approved'; NEVER sends).

Once a vertical (leads.sic_codes[1]) has PROVEN itself against the graduation
thresholds in sequence_config.json, its touch-1 drafts may be auto-approved —
but every approval is routed through review.approve, so the compliance envelope,
lead state machine and recorded-decision invariants apply unchanged, and live
sending stays behind the human-only G_SEND gate in send.py.

Non-obvious invariants:
- DOUBLE HUMAN GATE: config.AUTO_APPROVE_ENABLED (env) AND
  graduation.per_vertical_auto_send (config file) must BOTH be true; either off
  means fully dormant. Missing thresholds fail closed the same way.
- Review metrics are WINDOWED PER prompt_version, so a new playbook version
  starts from zero trust and must re-prove itself before auto-approval resumes.
  Bounce/complaint rates are live per-vertical deliverability (replies are not
  draft-linked) and gate every version alike.
- A deterministic sha256(company_number) spot-check holds ~1-in-N drafts
  (N from spot_check_ratio) in the human queue, so a graduated vertical is
  never entirely unwatched; the same company always lands on the same side.
- Only drafts whose lead is still in 'drafted'/'awaiting_approval' are picked
  up — a lead suppressed after drafting is silently left alone rather than
  tripping the state machine.
"""
from __future__ import annotations
import hashlib
import json

from . import audit, config, control, db, review, sequence
from .draft import PROMPT_VERSION

AUTO_REVIEWER = "auto:graduation"
EVIDENCE_MAX_CHARS = 400

# The vertical a lead is graded under: Companies House SIC first, then the Places
# listing's own category.
#
# Keying on sic_codes[1] alone made graduation structurally DEAD. sic_codes is null for
# all 14,870 Places leads — 99.2% of the corpus — so the only route to lights-out
# operation could never see almost any of it. The listing's `primary_type` was sitting
# in registered_address the whole time; the same gap left `vertical` resolved on 18 of
# 460 enrichment rows.
_VERTICAL = "coalesce(l.sic_codes[1], l.registered_address->>'primary_type')"

# What counts as a HUMAN having reviewed a draft. `decided_by is not null` was doing this
# job and is not up to it: 352 of the 357 decided rows on this database are a single bulk
# migration (`system:v2.0-migration`), and graduation was reading them as 352 acts of human
# trust. The real number of human decisions ever made is 24. A gate that can be opened by
# its own maintenance script is not a gate.
_HUMAN_DECISION = ("d.decided_by is not null "
                   "and d.decided_by not like 'system:%%' "
                   "and d.decided_by not like 'auto:%%'")

_METRICS_SQL = f"""
with vertical_drafts as (
  select {_VERTICAL} as vertical, d.status, d.body_original, d.body_final,
         ({_HUMAN_DECISION}) as human_decided
  from outreach.drafts d
  join outreach.leads l on l.company_number = d.company_number
  where d.prompt_version = %s and {_VERTICAL} is not null
),
reviewed as (
  select vertical,
         count(*) filter (where status in ('approved','rejected') and human_decided) as reviewed,
         -- approvals are counted on the same footing as the reviews they are drawn from,
         -- or the rate is a fraction of two different populations
         count(*) filter (where status = 'approved' and human_decided) as approved,
         count(*) filter (where status = 'approved' and human_decided
                          and (body_final is null or body_final = body_original)) as approved_unedited
  from vertical_drafts group by vertical
),
live as (
  select {_VERTICAL} as vertical, count(*) as live_sends
  from outreach.sends s join outreach.leads l on l.company_number = s.company_number
  where s.mode = 'live' and {_VERTICAL} is not null
  group by 1
),
signals as (
  select {_VERTICAL} as vertical,
         count(*) filter (where r.kind = 'bounce') as bounces,
         count(*) filter (where r.kind = 'complaint') as complaints
  from outreach.replies r join outreach.leads l on l.company_number = r.company_number
  where {_VERTICAL} is not null
  group by 1
)
select r.vertical, r.reviewed, r.approved, r.approved_unedited,
       coalesce(li.live_sends, 0), coalesce(s.bounces, 0), coalesce(s.complaints, 0)
from reviewed r
left join live li on li.vertical = r.vertical
left join signals s on s.vertical = r.vertical
order by r.vertical
"""


def vertical_metrics(cur, *, prompt_version=None) -> list[dict]:
    pv = prompt_version or PROMPT_VERSION
    cur.execute(_METRICS_SQL, (pv,))
    out: list[dict] = []
    for vertical, reviewed, approved, unedited, live_sends, bounces, complaints in cur.fetchall():
        out.append({
            "vertical": vertical,
            "prompt_version": pv,
            "reviewed": reviewed,
            "approved": approved,
            "approved_unedited": unedited,
            "approved_unedited_rate": (unedited / approved) if approved else 0.0,
            "live_sends": live_sends,
            "bounces": bounces,
            "complaints": complaints,
            "bounce_rate": (bounces / live_sends) if live_sends else 0.0,
            "complaint_rate": (complaints / live_sends) if live_sends else 0.0,
        })
    return out


def _gates_open() -> bool:
    return bool(config.AUTO_APPROVE_ENABLED) and \
        sequence.graduation_thresholds().get("per_vertical_auto_send") is True


def _meets(m: dict, t: dict) -> bool:
    required = ("min_reviewed_drafts_per_vertical", "min_approved_unedited_rate",
                "max_bounce_rate", "max_complaint_rate")
    if any(t.get(k) is None for k in required):
        return False
    return (m["reviewed"] >= t["min_reviewed_drafts_per_vertical"]
            and m["approved_unedited_rate"] >= t["min_approved_unedited_rate"]
            and m["bounce_rate"] <= t["max_bounce_rate"]
            and m["complaint_rate"] <= t["max_complaint_rate"])


def eligible_verticals(cur) -> list[str]:
    if not _gates_open():
        return []
    t = sequence.graduation_thresholds()
    return [m["vertical"] for m in vertical_metrics(cur) if _meets(m, t)]


def _spot_check_modulus(t: dict) -> int:
    ratio = t.get("spot_check_ratio") or 0
    return int(round(1 / ratio)) if ratio > 0 else 0


def held_for_spot_check(company_number: str, modulus: int) -> bool:
    if modulus <= 0:
        return False
    return int(hashlib.sha256(company_number.encode()).hexdigest(), 16) % modulus == 0


def run(*, cur=None, limit=None) -> list[dict]:
    if not _gates_open():
        return []
    thresholds = sequence.graduation_thresholds()
    modulus = _spot_check_modulus(thresholds)
    own = cur is None
    conn = None
    if own:
        conn = db.connect()
        cur = conn.cursor()
    try:
        actions: list[dict] = []
        # read once, on the caller's cursor: a mode change mid-batch would make
        # half the drafts obey one rule and half another
        critic_mode = control.get("CRITIC_MODE", cur=cur)
        metrics = {m["vertical"]: m for m in vertical_metrics(cur) if _meets(m, thresholds)}
        if metrics:
            sql = (
                f"select d.id, d.company_number, {_VERTICAL}, d.critic_verdict "
                "from outreach.drafts d join outreach.leads l on l.company_number = d.company_number "
                "where d.status = 'awaiting_approval' and d.touch = 1 "
                f"and d.prompt_version = %s and {_VERTICAL} = any(%s) "
                "and l.state in ('drafted','awaiting_approval') "
                "order by d.created_at"
            )
            params: tuple = (PROMPT_VERSION, list(metrics))
            if limit is not None:
                sql += " limit %s"
                params += (limit,)
            cur.execute(sql, params)
            for draft_id, company_number, vertical, critic_verdict in cur.fetchall():
                # In 'gate' mode a draft the critic failed is never auto-approved — it
                # falls through to the human queue, which is the whole point of having a
                # second reader. In shadow mode this is inert by construction: the critic
                # writes verdicts and nothing consults them, so its agreement with real
                # human decisions can be measured before it is allowed to matter.
                if critic_mode == "gate" and critic_verdict == "fail":
                    audit.record(company_number, "critic_held", source="graduation",
                                 lawful_basis=audit.LEGITIMATE_INTERESTS,
                                 reason=f"critic failed this draft ({vertical}, "
                                        f"{PROMPT_VERSION}) — held for a human", cur=cur)
                    actions.append({"draft_id": str(draft_id), "company_number": company_number,
                                    "vertical": vertical, "action": "critic_held"})
                    continue
                if held_for_spot_check(company_number, modulus):
                    audit.record(company_number, "spot_check_held", source="graduation",
                                 lawful_basis=audit.LEGITIMATE_INTERESTS,
                                 reason=f"deterministic 1-in-{modulus} human spot-check "
                                        f"({vertical}, {PROMPT_VERSION})", cur=cur)
                    actions.append({"draft_id": str(draft_id), "company_number": company_number,
                                    "vertical": vertical, "action": "spot_check_held"})
                    continue
                evidence = json.dumps(metrics[vertical], separators=(",", ":"))[:EVIDENCE_MAX_CHARS]
                note = f"graduated {vertical}: {evidence}"
                review.approve(draft_id, AUTO_REVIEWER, note=note, cur=cur)
                audit.record(company_number, "auto_approved", source="graduation",
                             lawful_basis=audit.LEGITIMATE_INTERESTS,
                             reason=note, cur=cur)
                actions.append({"draft_id": str(draft_id), "company_number": company_number,
                                "vertical": vertical, "action": "auto_approved"})
        if own:
            conn.commit()
        return actions
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        if own and conn is not None:
            conn.close()


if __name__ == "__main__":
    print(run())
