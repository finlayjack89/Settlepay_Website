"""Manual send override — "send this one now", with an undo window.

The queue (schedule.py) decides WHEN an approved draft goes out. This module is the
operator's override of that timing: one click moves a draft into the OUTBOX, where it
sits for UNDO_SECONDS before actually being sent. Cancelling inside that window is a
true no-op — the draft keeps the queue slot it already had.

What this override does NOT do is bypass a single compliance guardrail. Every outbox
send still goes through `send.send_one`, so the kill switch, the corporate-subscriber
check, suppression, the risky-tier opt-in, the warm-up daily cap and G-SEND all apply
exactly as they do to a scheduled send. The only thing being overridden is the clock.

Two things drain the outbox, deliberately:
  * OutboxSweeper — a daemon thread in the console process, polling every few seconds.
    This is what makes "30 seconds" mean 30 seconds rather than "some time before the
    next 10-minute tick".
  * the tick (`run._advance_sends`) — the safety net. If the instance is torn down
    between the click and the sweep, the draft is still due and the next tick sends it
    rather than stranding it in the outbox for ever.
"""
from __future__ import annotations

import datetime
import threading
import traceback

from . import audit, config, db

# Long enough to catch the "wrong row" misclick, short enough that the operator isn't
# waiting around. Also the window the tick safety net uses, so keep them in step.
UNDO_SECONDS = 30

# Only an approved draft that has not gone out LIVE can enter the outbox. A dry-run send
# is a test, not a real send, so it must NOT block: otherwise clicking "send now" while
# G-SEND is off (which dry-runs) would permanently burn the draft. Only a live send means
# "already went out".
_SENDABLE = (
    "select d.status from outreach.drafts d "
    "where d.id = %s "
    "and not exists (select 1 from outreach.sends s where s.draft_id = d.id and s.mode = 'live')")


class OutboxRefused(Exception):
    pass


def send_now(draft_id, *, requested_by: str, cur) -> datetime.datetime:
    """Put an approved draft in the outbox. Returns when it will actually send.
    Idempotent: a draft already in the outbox keeps its original countdown, so a
    double-click can't shorten (or restart) the undo window."""
    cur.execute(_SENDABLE, (draft_id,))
    row = cur.fetchone()
    if row is None:
        raise OutboxRefused("draft not found, or it has already been sent")
    if row[0] != "approved":
        raise OutboxRefused(f"only approved drafts can be sent ({row[0]})")

    cur.execute(
        "update outreach.drafts set outbox_at = coalesce(outbox_at, now()) "
        "where id = %s returning company_number, outbox_at", (draft_id,))
    company_number, outbox_at = cur.fetchone()
    audit.record(company_number, "outbox", source="manual",
                 lawful_basis=audit.LEGITIMATE_INTERESTS,
                 reason=f"manual send by {requested_by}; {UNDO_SECONDS}s to cancel", cur=cur)
    return outbox_at + datetime.timedelta(seconds=UNDO_SECONDS)


def cancel(draft_id, *, requested_by: str, cur) -> bool:
    """Take a draft back out of the outbox. False if it was never in one, or the
    window closed and it has already gone — an undo that lost the race must report
    that honestly rather than silently succeeding."""
    cur.execute(
        "update outreach.drafts set outbox_at = null "
        "where id = %s and outbox_at is not null "
        "and not exists (select 1 from outreach.sends s where s.draft_id = drafts.id) "
        "returning company_number", (draft_id,))
    row = cur.fetchone()
    if row is None:
        return False
    audit.record(row[0], "outbox_cancelled", source="manual",
                 lawful_basis=audit.LEGITIMATE_INTERESTS,
                 reason=f"manual send cancelled by {requested_by}", cur=cur)
    return True


DUE_SQL = (
    "select d.id from outreach.drafts d "
    "where d.status = 'approved' and d.outbox_at is not null "
    f"and d.outbox_at + interval '{UNDO_SECONDS} seconds' <= now() "
    # mode-aware: don't re-send in the SAME mode (no dry-run spam), but a prior dry-run
    # never blocks a live send — that is the whole bug fix
    "and not exists (select 1 from outreach.sends s where s.draft_id = d.id and s.mode = %s) "
    "order by d.outbox_at")


def due(cur, *, mode: str = "live") -> list:
    """Draft ids whose undo window has closed and haven't gone out in this mode."""
    cur.execute(DUE_SQL, (mode,))
    return [r[0] for r in cur.fetchall()]


def pending(cur) -> list[dict]:
    """Drafts still counting down — what the console renders as the outbox."""
    cur.execute(
        "select d.id, d.company_number, l.company_name, d.outbox_at, "
        "       coalesce(d.subject_final, d.subject) "
        "from outreach.drafts d join outreach.leads l on l.company_number = d.company_number "
        "where d.status = 'approved' and d.outbox_at is not null "
        "and not exists (select 1 from outreach.sends s where s.draft_id = d.id and s.mode = 'live') "
        "order by d.outbox_at")
    return [{"id": i, "company_number": cn, "company_name": n,
             "outbox_at": at, "subject": subj,
             "sends_at": at + datetime.timedelta(seconds=UNDO_SECONDS)}
            for i, cn, n, at, subj in cur.fetchall()]


def flush(*, dry_run: bool = True, cur=None) -> list[dict]:
    """Send every draft whose undo window has closed. A refusal is recorded and the
    draft leaves the outbox — a manual send that the guardrails reject must not sit
    there being retried every few seconds for ever."""
    from . import send as send_mod

    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    mode = "dry_run" if dry_run else "live"
    out: list[dict] = []
    try:
        for draft_id in due(cur, mode=mode):
            try:
                out.append(send_mod.send_one(draft_id, mode=mode, cur=cur))
            except send_mod.SendRefused as e:
                out.append({"draft_id": str(draft_id), "refused": str(e)})
            cur.execute("update outreach.drafts set outbox_at = null where id = %s", (draft_id,))
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


class OutboxSweeper(threading.Thread):
    """Drains the outbox on a short poll, so the undo window is measured in seconds
    rather than in ticks. Failure is logged and swallowed: a sweeper that dies takes
    manual sending down with it, and the tick safety net is slower than it is."""

    def __init__(self, poll_seconds: float = 5.0):
        super().__init__(name="outbox-sweeper", daemon=True)
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run_once(self) -> list[dict]:
        return flush(dry_run=not config.send_enabled())

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                print(f"outbox sweeper poll failed: {traceback.format_exc()[-500:]}", flush=True)
            self._stop.wait(self.poll_seconds)
