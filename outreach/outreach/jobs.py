"""Task registry + DB-backed job queue + single-worker runner (ops canvas core).

outreach.jobs is both the execution queue and the history the console reads. The
runner claims ONE queued row with FOR UPDATE SKIP LOCKED, commits the claim, then
executes the handler OUTSIDE any transaction — tasks can run for minutes and must
not hold locks or pin a transaction, so JobContext opens its own short connection
per log/progress/cancelled call. Cancellation is cooperative: cancel() flips the
row, handlers poll ctx.cancelled(), and a job cancelled mid-run stays 'cancelled'
regardless of what the handler returns.

tasks.py registers the real pipeline tasks by importing `task` from here; this
module must never import tasks.py (the queue core stays dependency-free).
"""
from __future__ import annotations
import json
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from . import config, db


@dataclass(frozen=True)
class Param:
    name: str
    label: str
    kind: str = "str"  # 'str' | 'int' | 'bool'
    default: Any = None
    required: bool = False


@dataclass(frozen=True)
class TaskSpec:
    kind: str
    title: str
    description: str
    params: tuple[Param, ...]
    handler: Callable[..., Optional[dict]]
    group: str = "pipeline"
    destructive: bool = False


REGISTRY: dict[str, TaskSpec] = {}

_TRUTHY = {"1", "true", "yes", "on"}


def task(kind, title, description="", params=(), group="pipeline", destructive=False):
    def register(fn):
        REGISTRY[kind] = TaskSpec(kind, title, description, tuple(params), fn, group, destructive)
        return fn
    return register


def coerce_params(spec: TaskSpec, raw: dict) -> dict:
    """Cast console/CLI-supplied values to each Param's kind; '' counts as absent
    because HTML forms submit empty strings for blank fields."""
    out: dict[str, Any] = {}
    for p in spec.params:
        value = raw.get(p.name)
        if value is None or value == "":
            if p.required:
                raise ValueError(f"missing required param: {p.name}")
            out[p.name] = p.default
        elif p.kind == "int":
            out[p.name] = int(value)
        elif p.kind == "bool":
            out[p.name] = value if isinstance(value, bool) else str(value).strip().lower() in _TRUTHY
        else:
            out[p.name] = str(value)
    return out


def enqueue(kind, params=None, *, requested_by="system", dedupe=False, cur=None) -> int:
    if kind not in REGISTRY:
        raise ValueError(f"unknown task kind: {kind}")
    own = cur is None
    if own:
        conn = db.connect()
        cur = conn.cursor()
    try:
        if dedupe:
            cur.execute(
                f'select id from "{config.DB_SCHEMA}".jobs '
                "where kind = %s and status in ('queued','running') order by id limit 1",
                (kind,),
            )
            row = cur.fetchone()
            if row is not None:
                return row[0]
        cur.execute(
            f'insert into "{config.DB_SCHEMA}".jobs (kind, params, requested_by) '
            "values (%s, %s, %s) returning id",
            (kind, json.dumps(params or {}), requested_by),
        )
        job_id = cur.fetchone()[0]
        if own:
            conn.commit()
        return job_id
    except Exception:
        if own:
            conn.rollback()
        raise
    finally:
        if own:
            conn.close()


class JobContext:
    """Handed to every task handler. Each method uses its own short connection —
    the runner holds no transaction while a task runs."""

    LOG_CAP = 200

    def __init__(self, job_id: int):
        self.job_id = job_id

    def log(self, msg) -> None:
        entry = {"t": datetime.now(timezone.utc).isoformat(), "msg": str(msg)}
        with db.cursor() as cur:
            cur.execute(
                f'select progress from "{config.DB_SCHEMA}".jobs where id = %s for update',
                (self.job_id,),
            )
            row = cur.fetchone()
            if row is None:
                return
            progress = row[0] or {}
            progress["log"] = (progress.get("log") or [])[-(self.LOG_CAP - 1):] + [entry]
            cur.execute(
                f'update "{config.DB_SCHEMA}".jobs set progress = %s where id = %s',
                (json.dumps(progress), self.job_id),
            )

    def progress(self, done: int, total: int) -> None:
        with db.cursor() as cur:
            cur.execute(
                f'update "{config.DB_SCHEMA}".jobs set progress = progress || %s::jsonb '
                "where id = %s",
                (json.dumps({"done": done, "total": total}), self.job_id),
            )

    def cancelled(self) -> bool:
        with db.cursor(commit=False) as cur:
            cur.execute(
                f'select status from "{config.DB_SCHEMA}".jobs where id = %s',
                (self.job_id,),
            )
            row = cur.fetchone()
            return row is not None and row[0] == "cancelled"


def _claim(job_id: Optional[int] = None):
    """Claim one queued job (a specific one for inline runs) and commit the claim
    so the running status is visible while the handler executes untransacted."""
    conn = db.connect()
    try:
        with conn.cursor() as cur:
            if job_id is None:
                cur.execute(
                    f'select id, kind, params from "{config.DB_SCHEMA}".jobs '
                    "where status = 'queued' order by id limit 1 for update skip locked"
                )
            else:
                cur.execute(
                    f'select id, kind, params from "{config.DB_SCHEMA}".jobs '
                    "where id = %s and status = 'queued' for update skip locked",
                    (job_id,),
                )
            row = cur.fetchone()
            if row is None:
                conn.rollback()
                return None
            cur.execute(
                f'update "{config.DB_SCHEMA}".jobs '
                "set status = 'running', started_at = now() where id = %s",
                (row[0],),
            )
        conn.commit()
        return row
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _finish(job_id: int, status: str, *, result=None, error=None) -> str:
    with db.cursor() as cur:
        cur.execute(
            f'select status from "{config.DB_SCHEMA}".jobs where id = %s for update',
            (job_id,),
        )
        row = cur.fetchone()
        if row is not None and row[0] == "cancelled":
            cur.execute(
                f'update "{config.DB_SCHEMA}".jobs set finished_at = now() where id = %s',
                (job_id,),
            )
            return "cancelled"
        cur.execute(
            f'update "{config.DB_SCHEMA}".jobs '
            "set status = %s, result = %s, error = %s, finished_at = now() where id = %s",
            (status, json.dumps(result) if result is not None else None, error, job_id),
        )
        return status


def _execute(job_id: int, kind: str, params: dict) -> str:
    started = time.monotonic()
    try:
        spec = REGISTRY.get(kind)
        if spec is None:
            raise ValueError(f"unknown task kind: {kind}")
        returned = spec.handler(JobContext(job_id), **coerce_params(spec, params or {}))
        status = _finish(job_id, "succeeded", result=returned if returned is not None else {})
    except Exception:
        status = _finish(job_id, "failed", error=traceback.format_exc()[-2000:])
    duration_ms = int((time.monotonic() - started) * 1000)
    print(json.dumps({
        "severity": "ERROR" if status == "failed" else "INFO",
        "message": f"job {job_id} {kind} {status}",
        "job_id": job_id, "kind": kind, "status": status, "duration_ms": duration_ms,
    }), flush=True)
    return status


class JobRunner(threading.Thread):
    """Single in-process worker. SKIP LOCKED (not this class) is the concurrency
    guard, so an overlapping instance during a deploy cannot double-claim."""

    def __init__(self, poll_seconds: float = 2.0):
        super().__init__(name="job-runner", daemon=True)
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run_once(self) -> bool:
        claimed = _claim()
        if claimed is None:
            return False
        job_id, kind, params = claimed
        _execute(job_id, kind, params)
        return True

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                busy = self.run_once()
            except Exception:
                print(json.dumps({
                    "severity": "ERROR",
                    "message": f"job runner poll failed: {traceback.format_exc()[-500:]}",
                }), flush=True)
                busy = False
            if not busy:
                self._stop.wait(self.poll_seconds)


def recover_stale(cur=None) -> int:
    """Called at app startup: any 'running' row survived an instance restart, so
    its worker thread is gone and it can never finish."""
    own = cur is None
    if own:
        conn = db.connect()
        cur = conn.cursor()
    try:
        cur.execute(
            f'update "{config.DB_SCHEMA}".jobs '
            "set status = 'failed', error = 'instance restarted', finished_at = now() "
            "where status = 'running'"
        )
        count = cur.rowcount
        if own:
            conn.commit()
        return count
    except Exception:
        if own:
            conn.rollback()
        raise
    finally:
        if own:
            conn.close()


def cancel(job_id: int, cur=None) -> bool:
    """Queued jobs never start; running jobs finish their current step and stay
    'cancelled' (cooperative via ctx.cancelled() + the _finish status re-check)."""
    own = cur is None
    if own:
        conn = db.connect()
        cur = conn.cursor()
    try:
        cur.execute(
            f'update "{config.DB_SCHEMA}".jobs '
            "set status = 'cancelled', finished_at = now() "
            "where id = %s and status in ('queued','running')",
            (job_id,),
        )
        hit = cur.rowcount > 0
        if own:
            conn.commit()
        return hit
    except Exception:
        if own:
            conn.rollback()
        raise
    finally:
        if own:
            conn.close()


def run_job_inline(kind, params=None, *, requested_by="cli") -> dict:
    """Enqueue then claim-and-execute that specific job synchronously (CLI/tests);
    shares the runner's claim/execute machinery, returns the final row."""
    job_id = enqueue(kind, params, requested_by=requested_by)
    claimed = _claim(job_id)
    if claimed is not None:
        _execute(claimed[0], claimed[1], claimed[2])
    with db.dict_cursor() as cur:
        cur.execute(f'select * from "{config.DB_SCHEMA}".jobs where id = %s', (job_id,))
        return cur.fetchone()
