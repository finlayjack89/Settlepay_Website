"""Phase F — approval queue (the human gate before any send).

Drafts sit in `awaiting_approval` until a human approves / edits / rejects via the
CLI below. An EDIT writes the revised text to body_final + a reviewer_note,
leaving body_original IMMUTABLE (the body_original/body_final diff is the training
signal for playbook v2). Approve-without-edit copies body_original -> body_final.
ONLY approved drafts advance, and nothing advances without a recorded human
decision (decided_by + decided_at).

CLI:
  python -m outreach.review list
  python -m outreach.review approve <draft_id> --by "Name" [--edit "new text"] [--note "..."]
  python -m outreach.review reject  <draft_id> --by "Name" [--note "..."]
"""
from __future__ import annotations
import argparse
import sys

from . import audit, db
from .draft import check_envelope
from .states import LeadState, transition


def list_pending(cur) -> list[tuple]:
    cur.execute(
        "select d.id, d.company_number, l.company_name, d.body_original "
        "from outreach.drafts d join outreach.leads l on l.company_number = d.company_number "
        "where d.status = 'awaiting_approval' order by d.created_at"
    )
    return cur.fetchall()


def _decide(draft_id, *, new_status, lead_target, event, reviewer, body_final, note, cur) -> str:
    if not reviewer:
        raise ValueError("a reviewer name is required (recorded human decision)")
    cur.execute(
        "select d.company_number, d.status, l.state "
        "from outreach.drafts d join outreach.leads l on l.company_number = d.company_number "
        "where d.id = %s", (draft_id,))
    row = cur.fetchone()
    if not row:
        raise ValueError(f"draft {draft_id} not found")
    company_number, status, lead_state = row
    if status != "awaiting_approval":
        raise ValueError(f"draft {draft_id} already decided ({status})")

    transition(LeadState(lead_state), lead_target)  # enforce the state machine

    cur.execute(
        "update outreach.drafts set status=%s, body_final=%s, reviewer_note=%s, "
        "decided_by=%s, decided_at=now() where id=%s",
        (new_status, body_final, note, reviewer, draft_id))
    cur.execute(
        "update outreach.leads set state=%s, updated_at=now() where company_number=%s",
        (lead_target.value, company_number))
    audit.record(company_number, event, source="approval",
                 lawful_basis=audit.LEGITIMATE_INTERESTS,
                 reason=f"{event} by {reviewer}" + (f"; note: {note}" if note else ""), cur=cur)
    return company_number


def approve(draft_id, reviewer, *, edited: str | None = None, note: str | None = None, cur=None) -> str:
    """Approve a draft. With `edited`, body_final = the revised text (+ reviewer_note),
    body_original untouched; without, body_final = a copy of body_original."""
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    try:
        cur.execute("select body_original from outreach.drafts where id=%s", (draft_id,))
        r = cur.fetchone()
        if not r:
            raise ValueError(f"draft {draft_id} not found")
        body_final = edited if edited is not None else r[0]
        if not body_final or not body_final.strip():
            raise ValueError("approved draft body_final cannot be empty")
        # a human edit must not break compliance — the envelope is non-negotiable
        violations = check_envelope(body_final)
        if violations:
            raise ValueError(f"approved draft violates compliance envelope: {violations}")
        cn = _decide(draft_id, new_status="approved", lead_target=LeadState.APPROVED,
                     event="approved", reviewer=reviewer, body_final=body_final, note=note, cur=cur)
        if own:
            conn.commit()
        return cn
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        if own and conn is not None:
            conn.close()


def reject(draft_id, reviewer, *, note: str | None = None, cur=None) -> str:
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    try:
        cn = _decide(draft_id, new_status="rejected", lead_target=LeadState.REJECTED,
                     event="rejected", reviewer=reviewer, body_final=None, note=note, cur=cur)
        if own:
            conn.commit()
        return cn
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        if own and conn is not None:
            conn.close()


def _cli(argv=None):
    p = argparse.ArgumentParser(prog="outreach.review")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    a = sub.add_parser("approve"); a.add_argument("draft_id"); a.add_argument("--by", required=True)
    a.add_argument("--edit", default=None); a.add_argument("--note", default=None)
    r = sub.add_parser("reject"); r.add_argument("draft_id"); r.add_argument("--by", required=True)
    r.add_argument("--note", default=None)
    args = p.parse_args(argv)

    if args.cmd == "list":
        with db.cursor(commit=False) as cur:
            rows = list_pending(cur)
        if not rows:
            print("no drafts awaiting approval")
        for did, cn, name, body in rows:
            print(f"\n=== draft {did}  |  {name} ({cn}) ===\n{body}\n")
        print(f"\n{len(rows)} awaiting approval")
    elif args.cmd == "approve":
        cn = approve(args.draft_id, args.by, edited=args.edit, note=args.note)
        print(f"approved draft {args.draft_id} ({cn}){' [edited]' if args.edit else ''}")
    elif args.cmd == "reject":
        cn = reject(args.draft_id, args.by, note=args.note)
        print(f"rejected draft {args.draft_id} ({cn})")


if __name__ == "__main__":
    _cli(sys.argv[1:])
