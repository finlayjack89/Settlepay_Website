"""An independent read of every draft — starting in SHADOW mode, where it decides nothing.

The reviewer is the bottleneck. Drafts have sat unapproved for a fortnight while
DRAFT_BACKLOG_MAX quietly throttled the whole pipeline behind them, which is the review
gate working exactly as designed against a reviewer who has run out of hours. The way out
is not to remove the gate but to give it a second reader whose agreement with the first
can be measured.

Two design decisions carry this module:

**The critic is not the drafter's family.** Drafting is Gemini, so the critic is OpenAI.
A judge drawn from the generator's own family shares its blind spots and returns confident,
correlated verdicts — the drafting bench had to be re-run once for exactly that reason
(LLM_MODELS.md, round 1). config.CRITIC_PROVIDER enforces the split and
llm.critic_provider is kept separate from llm.draft_provider so the two cannot quietly
converge on one model.

**The rubric is built from real rejections, not from what a good email looks like.** Every
substantive note a human has written on this pipeline is a FACTS error:

    "Brand name is yellowstone, not yellow. Not london based but email says london"
    "wrong location"          "US-bAsed"
    "Lead email doesn't match the company or terminology in the email."

None is about prose. A critic scoring tone and brevity would have passed all four. So
grounding, recipient fit and ICP fit are the hard dimensions here, and copy quality is the
soft one — the reverse of the obvious weighting.

In shadow mode the verdict is written to the draft and read by NOTHING. That is not
timidity; it is the only way to find out whether the critic is right before it is allowed
to matter.
"""
from __future__ import annotations
import json
import re
from typing import Optional

from . import audit, config, control, db, facts, llm

# Hard dimensions can fail a draft on their own; a soft one only moves the score. The
# split is the rubric's opinion about this corpus: a wrong town is fatal, a clumsy
# sentence is not.
HARD_DIMENSIONS = ("grounding", "recipient", "icp", "compliance")
SOFT_DIMENSIONS = ("copy",)
DIMENSIONS = HARD_DIMENSIONS + SOFT_DIMENSIONS

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "verdict": {"type": "string", "enum": ["pass", "fail"]},
        "reasons": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "dimension": {"type": "string", "enum": list(DIMENSIONS)},
                    "severity": {"type": "string", "enum": ["hard", "soft"]},
                    "detail": {"type": "string"},
                },
                "required": ["dimension", "severity", "detail"],
            },
        },
    },
    "required": ["score", "verdict", "reasons"],
}

RUBRIC = """You are reviewing a cold outreach email before it is sent to a small UK
business. You are the second reader. Your job is to catch what the writer could not see —
not to rewrite the email, and not to admire it.

You cannot browse and you have no knowledge of this business beyond the FACTS block below.
That is deliberate. The FACTS block is the ONLY thing the email is permitted to assert.
If the email states something that is not in the block, that is a grounding failure even
if it sounds plausible and even if it might be true. "Plausible" is precisely the failure
mode you exist to catch.

Score each dimension, then give one overall score out of 100.

HARD dimensions — any real failure here means verdict "fail", whatever the prose is like:

1. grounding — every specific claim about this business traces to the FACTS block.
   Check the TOWN and the COMPANY NAME above all: the most common real-world failure is
   an email confidently naming a city the business is not in, or calling the business by
   a name close to but not actually its trading name. A fact listed as "unknown" in the
   block must not appear in the email at all.
2. recipient — the recipient address plausibly belongs to THIS business (its domain
   matches the business's own website/name) and the greeting matches who we hold. An
   email addressed to a person we cannot name, or sent to a mailbox at some other
   company's domain, fails.
3. icp — this is a small UK business that takes payment from its own customers and could
   use a branded payment page. A wholesaler, a US-based company, a franchise of a national
   chain, or a business whose payments are obviously handled by a platform is not our
   customer, and writing to them is the mistake — not the wording.
4. compliance — the email must NOT: claim SettlePay is FCA authorised/regulated or PCI DSS
   compliant (payments are handled by FCA-regulated partners); call SettlePay a limited
   company or give a company number (it is a trading name of a sole trader); name any
   client other than Lockdales Auctioneers; quote invented statistics, results or case
   studies; or manufacture urgency ("only 3 slots left", a deadline nobody set).

SOFT dimension — lowers the score, does not on its own fail:

5. copy — UK English, no emoji, plain and specific rather than salesy, a single clear ask,
   and it reads like one person writing to another. Note it if it is weak. Do not fail a
   factually sound email for being ordinary.

Return JSON only:
{"score": <0-100>, "verdict": "pass"|"fail",
 "reasons": [{"dimension": "...", "severity": "hard"|"soft", "detail": "<one specific sentence>"}]}

Give a reason for every dimension you are marking down. If nothing is wrong, return an
empty reasons list and say so with the score. Be concrete: "says London, facts say Otley"
is useful; "some inaccuracies" is not."""


def build_prompt(*, company_name: str, subject: Optional[str], body: str,
                 fact_block: dict, contact_email: Optional[str],
                 website: Optional[str], vertical: Optional[str]) -> str:
    """The critic sees exactly what the drafter was given plus what it produced, and the
    recipient it is aimed at — which the drafter never sees and cannot check."""
    return "\n\n".join([
        RUBRIC,
        "--- FACTS (the only permitted source of assertions) ---\n"
        + facts.as_prompt_block(fact_block),
        "--- RECIPIENT ---\n"
        f"business: {company_name}\n"
        f"website: {website or '(unknown)'}\n"
        f"vertical: {vertical or '(unknown)'}\n"
        f"sending to: {contact_email or '(unknown)'}",
        f"--- EMAIL ---\nSubject: {subject or '(none)'}\n\n{body}",
    ])


_JSON_RE = re.compile(r"\{.*\}", re.S)


def parse_verdict(text: str) -> dict:
    """Tolerant parse. A critic that returns prose around its JSON must not crash the
    stage — an unreadable verdict is an 'error', which is a fact about the critic, not a
    judgement about the draft."""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
    m = _JSON_RE.search(raw)
    if not m:
        raise ValueError("no JSON object in critic response")
    data = json.loads(m.group(0))
    score = data.get("score")
    if not isinstance(score, int) or not 0 <= score <= 100:
        raise ValueError(f"bad score: {score!r}")
    reasons = [r for r in (data.get("reasons") or []) if isinstance(r, dict)]
    hard_fail = any(r.get("severity") == "hard" for r in reasons)
    verdict = data.get("verdict")
    if verdict not in ("pass", "fail"):
        verdict = "fail" if hard_fail else "pass"
    # The model does not get the last word on its own consistency: a hard reason IS a
    # failure by definition, and a score under the bar is a failure whatever it called it.
    if hard_fail or score < config.CRITIC_PASS_SCORE:
        verdict = "fail"
    return {"score": score, "verdict": verdict, "reasons": reasons}


_SELECT = """
select d.id, d.company_number, l.company_name, d.subject, d.subject_final,
       d.body_original, e.facts, e.contact_email, e.website,
       e.facts->'vertical'->>'value'
  from outreach.drafts d
  join outreach.leads l on l.company_number = d.company_number
  left join outreach.enrichment e on e.company_number = d.company_number
 where d.critic_at is null
"""

_BACKLOG_SQL = _SELECT + "   and d.status = 'awaiting_approval' order by d.created_at limit %s"

# Drafts a HUMAN has already decided — the answer key.
#
# Shadow mode measures agreement against decisions made AFTER the critic starts running,
# which means weeks before there is anything to judge it on. These rows already carry the
# answer. Judging them gives a reading immediately, and it is the only way to test the
# critic against the failures that actually happened: all four real rejections are here,
# and a critic that cannot catch "says London when they are not in London" should fail
# that test now rather than after it has been trusted with anything.
#
# system:/auto: rows are excluded for the same reason agreement() excludes them — 352 of
# the 357 decided rows on this database are one bulk migration, and calibrating against a
# script measures nothing at all.
#
# 'sent' counts as an APPROVAL. An approved draft that went out is still a human saying
# yes — it simply moved on afterwards. Excluding it left a calibration set of 4 rejections
# and 0 approvals on this database, and a set with no approvals cannot detect the failure
# mode that matters most in the other direction: a critic that fails EVERYTHING scores
# 100% agreement against nothing but rejections.
_CALIBRATE_SQL = _SELECT + """
   and d.status in ('approved', 'rejected', 'sent')
   and d.decided_by is not null
   and d.decided_by not like 'system:%%'
   and d.decided_by not like 'auto:%%'
 order by d.decided_at desc
 limit %s
"""

# What a human APPROVING looks like in the status column, wherever the draft ended up.
HUMAN_APPROVED = ("approved", "sent")


def judge_one(row: tuple, *, provider) -> dict:
    """Judge one draft. Never raises: an unreachable critic yields verdict 'error' so the
    draft is marked as seen-and-unjudged rather than silently retried for ever."""
    (draft_id, cn, company_name, subject, subject_final, body,
     raw_facts, contact_email, website, vertical) = row
    prompt = build_prompt(
        company_name=company_name, subject=subject_final or subject, body=body,
        fact_block=facts.loads(raw_facts), contact_email=contact_email,
        website=website, vertical=vertical)
    try:
        result = provider.complete(prompt, purpose="critic", schema=VERDICT_SCHEMA)
        out = parse_verdict(result.text)
        out["model"] = (result.meta or {}).get("model")
    except Exception as e:
        out = {"score": None, "verdict": "error", "model": None,
               "reasons": [{"dimension": "critic", "severity": "soft",
                            "detail": f"{type(e).__name__}: {e}"[:300]}]}
    out["draft_id"], out["company_number"] = draft_id, cn
    return out


def record(cur, verdict: dict) -> None:
    cur.execute(
        "update outreach.drafts set critic_verdict=%s, critic_score=%s, "
        "  critic_reasons=%s::jsonb, critic_model=%s, critic_at=now() where id=%s",
        (verdict["verdict"], verdict["score"], json.dumps(verdict["reasons"]),
         verdict.get("model"), verdict["draft_id"]))
    if verdict["verdict"] == "fail":
        worst = next((r for r in verdict["reasons"] if r.get("severity") == "hard"),
                     (verdict["reasons"] or [{}])[0])
        audit.record(verdict["company_number"], "critic_failed", source="critic",
                     lawful_basis=audit.LEGITIMATE_INTERESTS,
                     reason=f"{worst.get('dimension')}: {worst.get('detail')}"[:400],
                     detail={"score": verdict["score"], "mode": control.get("CRITIC_MODE", cur=cur)},
                     cur=cur)


def run(*, limit: Optional[int] = None, cur=None, provider=None,
        calibrate: bool = False) -> dict:
    """Judge up to `limit` unjudged drafts.

    In shadow mode (the default) this writes verdicts and changes nothing else — no draft
    is approved, rejected or held because of what it says. Read the agreement report
    before changing that.

    `calibrate=True` judges drafts a HUMAN has ALREADY decided instead of the live queue,
    so agreement can be measured now rather than after weeks of new decisions. It writes
    only to the critic_* columns, which nothing reads in shadow mode, so it cannot disturb
    a decision that has already been made.
    """
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    # Read the switches on the CALLER's cursor — see the same note in decisionmakers.run:
    # a control.get with no cursor opens its own connection and reads outside the caller's
    # transaction, so a switch set moments earlier is invisible.
    if not control.get("CRITIC_ENABLED", cur=cur):
        if own and conn is not None:
            conn.close()
        return {"skipped": "critic switched off"}
    limit = limit or control.get("CRITIC_PER_TICK", cur=cur)
    provider = provider or llm.critic_provider()
    out = {"judged": 0, "passed": 0, "failed": 0, "errored": 0,
           "mode": control.get("CRITIC_MODE", cur=cur), "calibrate": calibrate}
    try:
        cur.execute(_CALIBRATE_SQL if calibrate else _BACKLOG_SQL, (limit,))
        for row in cur.fetchall():
            verdict = judge_one(row, provider=provider)
            record(cur, verdict)
            out["judged"] += 1
            out[{"pass": "passed", "fail": "failed"}.get(verdict["verdict"], "errored")] += 1
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


# --------------------------------------------------------------------------- #
#  Does it agree with the human? — the only number that licenses handing over
# --------------------------------------------------------------------------- #
def agreement(cur, *, prompt_version: Optional[str] = None) -> dict:
    """Compare the critic's verdicts against the decisions a HUMAN actually made.

    Only genuine human decisions count. 352 of the 357 rows carrying decided_by on this
    database are a single bulk migration (`system:v2.0-migration`), so any metric that
    treats decided_by as evidence of human judgement is reading its own exhaust — the
    same defect this fixes in graduation.

    The asymmetry matters more than the headline rate. A false PASS is a bad email sent;
    a false FAIL is a good email held for a human. Only the first is a reason not to hand
    over, so they are reported separately rather than averaged into an accuracy figure
    that hides which way the errors fall.
    """
    where = "and d.prompt_version = %s" if prompt_version else ""
    params = (prompt_version,) if prompt_version else ()
    # 'sent' is an approval that went further — see HUMAN_APPROVED. Counting only
    # 'approved' left 17 of this database's 21 human decisions invisible, and all four
    # survivors were rejections.
    approved = "d.status = any(%s)"
    cur.execute(
        "select count(*), "
        f"  count(*) filter (where {approved} and d.critic_verdict='pass'), "
        "  count(*) filter (where d.status='rejected' and d.critic_verdict='fail'), "
        "  count(*) filter (where d.status='rejected' and d.critic_verdict='pass'), "
        f"  count(*) filter (where {approved} and d.critic_verdict='fail') "
        "from outreach.drafts d "
        "where d.critic_verdict in ('pass','fail') "
        f"  and (d.status = 'rejected' or {approved}) "
        "  and d.decided_by is not null "
        "  and d.decided_by not like 'system:%%' and d.decided_by not like 'auto:%%' "
        + where, (list(HUMAN_APPROVED),) * 3 + params)
    total, agree_pass, agree_fail, false_pass, false_fail = cur.fetchone()
    total = total or 0
    approvals = (agree_pass or 0) + (false_fail or 0)
    rejections = (agree_fail or 0) + (false_pass or 0)
    return {
        "compared": total,
        "agreed": (agree_pass or 0) + (agree_fail or 0),
        "agreement_rate": ((agree_pass or 0) + (agree_fail or 0)) / total if total else 0.0,
        # the critic passed something the human rejected — the dangerous direction
        "false_pass": false_pass or 0,
        "false_pass_rate": (false_pass or 0) / total if total else 0.0,
        # the critic failed something the human approved — costs reach, not safety
        "false_fail": false_fail or 0,
        # both sides of the answer key, so a lopsided sample is visible rather than
        # flattering: a critic that fails EVERYTHING scores 100% against rejections alone
        "human_approvals": approvals,
        "human_rejections": rejections,
        "ready_to_gate": (total >= 30 and (false_pass or 0) == 0
                          and approvals >= 10 and rejections >= 5),
    }
