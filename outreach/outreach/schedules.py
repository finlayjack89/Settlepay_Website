"""Recurring tasks, editable from the dashboard.

The only cadence this system had was a Cloud Scheduler cron hitting /tick every ten
minutes. It lives in GCP, so it cannot be seen or changed from the console, and anything
else that ought to happen regularly — calibrate the critic weekly, refresh stale facts
nightly — had nowhere to live at all.

These rows ride the EXISTING tick rather than adding a second cron. Two reasons, and the
second is the one that matters: the schedule then lives in the database where the dashboard
can edit it, and there is still exactly one thing in GCP to keep alive. A second cron would
be a second thing to forget about, drift from, and be surprised by.

`every_minutes` is floored at 10 in the schema because the tick itself only fires every ten
minutes — a smaller number would promise a cadence the scheduler cannot deliver, and a knob
that lies about its own resolution is worse than one that refuses.
"""
from __future__ import annotations
from typing import Optional

from . import audit, db, jobs

MIN_MINUTES = 10


def create(*, kind: str, every_minutes: int, params: Optional[dict] = None,
           by: str = "operator", cur=None) -> int:
    if kind not in jobs.REGISTRY:
        raise ValueError(f"unknown task: {kind}")
    if jobs.REGISTRY[kind].destructive:
        # A destructive task needs a human confirming THIS run, which a schedule by
        # definition cannot do. send_batch and migrate are not things to put on a timer.
        raise ValueError(f"{kind} acts on real data and cannot be scheduled")
    if every_minutes < MIN_MINUTES:
        raise ValueError(f"the tick fires every {MIN_MINUTES} minutes; "
                         f"a shorter interval cannot be honoured")
    # Validate the params against the task's own spec now, so a schedule cannot sit there
    # failing every run because of a typo made once.
    jobs.coerce_params(jobs.REGISTRY[kind], params or {})

    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    try:
        import json
        cur.execute(
            "insert into outreach.schedules (kind, params, every_minutes, created_by) "
            "values (%s, %s::jsonb, %s, %s) returning id",
            (kind, json.dumps(params or {}), every_minutes, by))
        sid = cur.fetchone()[0]
        audit.record(None, "schedule_created", source="schedules",
                     lawful_basis=audit.LEGITIMATE_INTERESTS,
                     reason=f"{kind} every {every_minutes}m by {by}",
                     detail={"schedule_id": sid, "kind": kind,
                             "every_minutes": every_minutes}, cur=cur)
        if own:
            conn.commit()
        return sid
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        if own and conn is not None:
            conn.close()


def listing(cur) -> list[dict]:
    cur.execute(
        "select id, kind, params, every_minutes, enabled, last_run_at, next_run_at "
        "from outreach.schedules order by enabled desc, next_run_at")
    return [{"id": i, "kind": k, "params": p, "every_minutes": m, "enabled": e,
             "last_run_at": lr, "next_run_at": nr}
            for i, k, p, m, e, lr, nr in cur.fetchall()]


def set_enabled(schedule_id: int, on: bool, *, by: str = "operator", cur=None) -> None:
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    try:
        cur.execute("update outreach.schedules set enabled=%s where id=%s",
                    (on, schedule_id))
        audit.record(None, "schedule_toggled", source="schedules",
                     lawful_basis=audit.LEGITIMATE_INTERESTS,
                     reason=f"schedule {schedule_id} {'enabled' if on else 'paused'} by {by}",
                     cur=cur)
        if own:
            conn.commit()
    finally:
        if own and conn is not None:
            conn.close()


def delete(schedule_id: int, *, by: str = "operator", cur=None) -> None:
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    try:
        cur.execute("delete from outreach.schedules where id=%s", (schedule_id,))
        audit.record(None, "schedule_deleted", source="schedules",
                     lawful_basis=audit.LEGITIMATE_INTERESTS,
                     reason=f"schedule {schedule_id} deleted by {by}", cur=cur)
        if own:
            conn.commit()
    finally:
        if own and conn is not None:
            conn.close()


def run_due(*, cur=None, now=None) -> dict:
    """Enqueue whatever is due. Called by the tick as an always-on stage.

    `next_run_at` advances BEFORE the job is enqueued, and enqueue is deduped per kind, so
    a task that takes longer than its own interval cannot pile up behind itself — which is
    the failure mode that turns a five-minute schedule into an unbounded queue.
    """
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    launched: list[dict] = []
    try:
        cur.execute(
            "select id, kind, params, every_minutes from outreach.schedules "
            "where enabled and next_run_at <= coalesce(%s, now()) order by next_run_at",
            (now,))
        for sid, kind, params, minutes in cur.fetchall():
            cur.execute(
                "update outreach.schedules set last_run_at = now(), "
                "  next_run_at = now() + make_interval(mins => %s) where id = %s",
                (minutes, sid))
            if kind not in jobs.REGISTRY:
                # the task was renamed or removed out from under the schedule; say so
                # rather than failing silently every interval for ever
                launched.append({"schedule": sid, "kind": kind, "error": "unknown task"})
                continue
            job_id = jobs.enqueue(kind, params or {}, requested_by=f"schedule:{sid}",
                                  dedupe=True, cur=cur)
            launched.append({"schedule": sid, "kind": kind, "job": job_id})
        if own:
            conn.commit()
        return {"launched": len(launched), "detail": launched}
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        if own and conn is not None:
            conn.close()
