"""Reviewer notes, turned into a signal the pipeline can act on.

`reviewer_note` has existed since migration 0001 and until now nothing has ever read it.
Five notes exist on this database. Every substantive one names a FACTS error:

    "Brand name is yellowstone, not yellow. Not london based but email says london"
    "wrong location"
    "US-bAsed"
    "Lead email doesn't match the company or terminology in the email."

Taken together that is a complete indictment of the enrichment stage and an acquittal of
the drafter — and it sat in a text column nobody aggregated, while effort went into
rewriting copy that was never the problem. This module is the fix: classify the note,
name the stage that owns it, and let a rejection do two things instead of one.

The classifier is DETERMINISTIC on purpose. It costs nothing, it is auditable, and a
reviewer can read the rules and predict the outcome — none of which is true of a model
call. It is also honest about its limits: anything it cannot place becomes 'other'
rather than being forced into a category, because a misfiled note is worse than an
unfiled one. It reports its confidence so the console can ask the reviewer to confirm
instead of guessing on their behalf.
"""
from __future__ import annotations
import re
from typing import Optional

from . import audit, db

# category -> the stage that owns the fix. Stored alongside the category (migration 0019)
# rather than computed at read time, so changing this map later cannot silently rewrite
# what past reviews were about.
STAGE_FOR = {
    "facts_wrong": "enrich",         # a constant was wrong — location, brand name, age
    "wrong_recipient": "enrich",     # the address does not belong to this business
    "not_icp": "discover",           # we should never have written to them at all
    "copy": "draft",                 # the prose itself
    "other": "review",               # unplaced — a human decides where it belongs
}

# Ordered: the first family to match wins, so the more specific patterns come first. Each
# pattern is drawn from a note a human actually wrote, not from what a note might say.
_RULES: tuple[tuple[str, re.Pattern], ...] = (
    # "Not london based but email says london", "wrong location", "US-bAsed"
    ("facts_wrong", re.compile(
        r"\b(wrong|incorrect|not)\b[^.]{0,30}\b(location|based|town|city|address|area|region)\b"
        r"|\blocation\b[^.]{0,20}\bwrong\b"
        r"|\b(us|usa|american|not uk|non-uk|overseas)[- ]?based\b"
        # "Brand name is yellowstone, not yellow"
        r"|\b(brand|company|business|trading)\s*name\b[^.]{0,40}\b(is|not|wrong|isn'?t)\b"
        r"|\b(wrong|incorrect)\b[^.]{0,20}\b(name|company)\b"
        r"|\bmade up\b|\bhallucinat|\binvented\b|\bfabricat", re.I)),
    # "Lead email doesn't match the company or terminology in the email."
    ("wrong_recipient", re.compile(
        r"\b(email|address|domain|mailbox|contact)\b[^.]{0,40}"
        r"\b(doesn'?t|does not|not)\s+match\b"
        r"|\bwrong\s+(person|contact|email|address|recipient|company)\b"
        r"|\b(different|another)\s+(company|business)\b", re.I)),
    ("not_icp", re.compile(
        r"\bnot\b[^.]{0,20}\b(icp|fit|target|customer|relevant)\b"
        r"|\b(wholesale|wholesaler|franchise|chain|charity|too big|enterprise)\b"
        r"|\bdon'?t take payments?\b|\bno online payments?\b", re.I)),
    ("copy", re.compile(
        r"\b(too\s+(long|short|salesy|pushy|formal|casual))\b"
        r"|\b(tone|wording|phrasing|reads?\s+(badly|oddly)|clunky|waffle|typo|spelling"
        r"|grammar|subject\s*line)\b"
        r"|\bdoesn'?t\s+(read|sound)\b", re.I)),
)


def classify(note: Optional[str]) -> tuple[Optional[str], Optional[str], bool]:
    """(category, stage, confident). An empty note classifies as nothing at all — the
    absence of a note is not evidence about anything."""
    text = (note or "").strip()
    if not text:
        return None, None, False
    for category, pattern in _RULES:
        if pattern.search(text):
            return category, STAGE_FOR[category], True
    # Said something, but not in a shape we recognise. 'other' is a real answer here:
    # it means "a human wrote a reason and we could not place it", which is exactly the
    # thing worth surfacing so the rules can learn a new family.
    return "other", STAGE_FOR["other"], False


def record_note(cur, draft_id, company_number: str, note: Optional[str]) -> Optional[str]:
    """Classify one decision's note and store it. Returns the category, or None."""
    category, stage, confident = classify(note)
    if category is None:
        return None
    cur.execute("update outreach.drafts set note_category=%s, note_stage=%s where id=%s",
                (category, stage, draft_id))
    audit.record(company_number, "review_feedback", source="review",
                 lawful_basis=audit.LEGITIMATE_INTERESTS,
                 reason=f"{category} -> {stage}: {(note or '')[:200]}",
                 detail={"category": category, "stage": stage, "confident": confident},
                 cur=cur)
    return category


def backfill(*, cur=None, limit: int = 1000) -> dict:
    """Classify notes written before this module existed. Idempotent — it only touches
    rows with no category yet, so re-running it is free and safe."""
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    counts: dict[str, int] = {}
    try:
        cur.execute(
            "select id, company_number, reviewer_note from outreach.drafts "
            "where reviewer_note is not null and reviewer_note <> '' "
            "  and note_category is null "
            # a bulk migration's boilerplate is not review feedback and must not be
            # counted as any stage's fault
            "  and (decided_by is null or decided_by not like 'system:%%') "
            "order by decided_at limit %s", (limit,))
        for draft_id, cn, note in cur.fetchall():
            category = record_note(cur, draft_id, cn, note)
            if category:
                counts[category] = counts.get(category, 0) + 1
        if own:
            conn.commit()
        return {"classified": sum(counts.values()), "by_category": counts}
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        if own and conn is not None:
            conn.close()


def summary(cur, *, days: int = 90) -> dict:
    """Which stage the reviewer's rejections are actually about.

    This is the number that should decide what gets worked on next. Only genuine human
    decisions count — `system:%`/`auto:%` rows are machinery, and a bulk migration's
    boilerplate note would otherwise swamp the real signal 70 to 1.
    """
    cur.execute(
        "select note_category, note_stage, count(*) "
        "from outreach.drafts "
        "where note_category is not null and decided_at > now() - make_interval(days => %s) "
        "  and decided_by is not null "
        "  and decided_by not like 'system:%%' and decided_by not like 'auto:%%' "
        "group by 1,2 order by 3 desc", (days,))
    rows = [{"category": c, "stage": s, "count": n} for c, s, n in cur.fetchall()]
    by_stage: dict[str, int] = {}
    for r in rows:
        by_stage[r["stage"]] = by_stage.get(r["stage"], 0) + r["count"]
    total = sum(by_stage.values())
    worst = max(by_stage.items(), key=lambda kv: kv[1])[0] if by_stage else None
    return {"days": days, "total": total, "by_category": rows, "by_stage": by_stage,
            # the stage to fix next, by the reviewer's own account
            "worst_stage": worst,
            "worst_share": (by_stage[worst] / total) if worst and total else 0.0}
