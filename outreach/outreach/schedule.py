"""Send queue — assigns each approved draft a specific minute to go out.

Approving a draft puts it in a queue rather than making it immediately sendable.
It gets the next free slot: a jittered minute inside the send window, on the first
day that still has capacity. Overflow rolls to the following send day.

Two things this buys:

1. **No bursts.** `_advance_sends` used to fire every approved draft in one loop.
   At the 50/day ceiling that is 50 cold emails on the wire within seconds, which
   is the exact pattern Google's bulk-sender guidance warns about ("send email at
   a consistent rate; avoid sending email in bursts").
2. **A free timing experiment.** Spreading each day's sends across the whole
   window samples early-morning, mid-morning and lunchtime every day, so
   reply-rate-by-hour can be read straight off the send log later. Opens are not
   measurable here by design — no tracking pixels, no links.

Capacity per day is the warm-up-aware per-inbox cap, projected forward: if nothing
has been sent live yet, the first scheduled day becomes warm-up day 1.

Slot times are deterministic per draft (seeded from its id), so re-running the
scheduler for a draft is stable and the tests do not chase a moving target — while
across drafts the times still look irregular.
"""
from __future__ import annotations

import datetime
import hashlib

from . import config, sequence

# Tick granularity bounds how fine the spacing can actually be: Cloud Scheduler
# runs the tick every 10 minutes, so a slot at 08:03 is sent by the 08:10 tick.
# Scheduling to the minute is still worth it — the varying number of drafts due
# per tick (0, 1, 2) is what makes the outgoing pattern irregular.
JITTER_MARGIN = 0.1   # keep each send inside its own slot, so two can never collide


def _window(seq=None) -> tuple[int, int, list[int]]:
    seq = seq or sequence.load_sequence_config()
    w = seq.get("send_window", {})
    return (int(w.get("start_hour", 8)), int(w.get("end_hour", 15)),
            list(w.get("days", [0, 1, 2, 3, 4])))


def is_send_day(day: datetime.date, seq=None) -> bool:
    return day.weekday() in _window(seq)[2]


def next_send_day(after: datetime.date, seq=None) -> datetime.date:
    """The first send day strictly after `after` (never loops forever: a week is
    enough unless the window is configured with no days at all)."""
    for i in range(1, 8):
        d = after + datetime.timedelta(days=i)
        if is_send_day(d, seq):
            return d
    raise RuntimeError("send_window.days contains no valid weekday")


def warmup_day_for(day: datetime.date, *, cur, inbox: str) -> int:
    """Which warm-up day `day` is: one more than the number of days we have already
    sent on, or are committed to sending on, before it.

    Counted in SENDING days, not calendar days. Calendar days let a weekend advance
    the ramp with no email going out — Friday 25/day would jump to Monday 50/day,
    doubling volume after two days of silence, which is precisely the spike the
    ramp exists to avoid.
    """
    cur.execute(
        "select count(*) from ("
        "  select distinct created_at::date d from outreach.sends "
        "   where from_inbox = %s and mode = 'live' and created_at::date < %s"
        "  union "
        "  select distinct scheduled_at::date d from outreach.drafts "
        "   where status = 'approved' and scheduled_at is not null "
        "     and scheduled_at::date < %s"
        ") x", (inbox, day, day))
    return cur.fetchone()[0] + 1


def daily_capacity(day: datetime.date, *, cur, inbox: str, seq=None) -> int:
    """Warm-up-aware capacity for `day`, projected forward."""
    warmup_day = warmup_day_for(day, cur=cur, inbox=inbox)
    return min(config.PER_INBOX_DAILY_CAP, sequence.warmup_cap(max(warmup_day, 1), seq))


def _slot_time(day: datetime.date, index: int, capacity: int, draft_id, seq=None) -> datetime.datetime:
    """Position `index` of `capacity` within the window, jittered inside its own
    slot. Deterministic per draft, irregular across drafts."""
    start_h, end_h, _ = _window(seq)
    span = max((end_h - start_h) * 60, 1)
    slot = span / max(capacity, 1)
    # 0..1 from the draft id — stable across processes (hash() is salted per run)
    h = hashlib.sha256(str(draft_id).encode()).digest()
    frac = int.from_bytes(h[:4], "big") / 0xFFFFFFFF
    offset = slot * (index + JITTER_MARGIN + frac * (1 - 2 * JITTER_MARGIN))
    # tz-aware in the SEND timezone: the column is timestamptz, and a naive value
    # would be read as the session zone (UTC), shifting every slot by an hour
    # through British Summer Time.
    base = datetime.datetime.combine(day, datetime.time(hour=start_h),
                                     tzinfo=sequence.send_tz(seq))
    return base + datetime.timedelta(minutes=min(offset, span - 1))


def assign_slot(draft_id, *, cur, inbox: str | None = None, now=None) -> datetime.datetime:
    """Give `draft_id` the next free slot and persist it. Idempotent: a draft that
    already has a slot keeps it."""
    cur.execute("select scheduled_at from outreach.drafts where id=%s", (draft_id,))
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"draft {draft_id} not found")
    if row[0] is not None:
        return row[0]

    seq = sequence.load_sequence_config()
    inbox = inbox or config.GMAIL_SENDER or "unset"
    # all window arithmetic happens in the send timezone, never the machine's
    now = sequence.local_now(seq, now)
    if now.tzinfo is None:
        now = now.replace(tzinfo=sequence.send_tz(seq))

    start_h, end_h, _ = _window(seq)
    day = now.date()
    # today only counts if it is a send day and the window has not closed
    if not is_send_day(day, seq) or now.hour >= end_h:
        day = next_send_day(day, seq)

    for _ in range(60):                     # ~12 weeks of send days, then give up
        capacity = daily_capacity(day, cur=cur, inbox=inbox, seq=seq)
        cur.execute("select count(*) from outreach.drafts "
                    "where scheduled_at::date = %s and status <> 'rejected'", (day,))
        taken = cur.fetchone()[0]
        # already-sent messages consume the same daily allowance
        cur.execute("select count(*) from outreach.sends where from_inbox=%s "
                    "and created_at::date = %s and status in ('sent','dry_run_ok')",
                    (inbox, day))
        taken += cur.fetchone()[0]
        if taken < capacity:
            when = _slot_time(day, taken, capacity, draft_id, seq)
            # never schedule in the past on the current day — go to the next slot
            if day == now.date() and when <= now:
                remaining = datetime.datetime.combine(
                    day, datetime.time(hour=end_h),
                    tzinfo=sequence.send_tz(seq)) - now
                if remaining.total_seconds() > 120:
                    when = now + datetime.timedelta(
                        minutes=1 + (int.from_bytes(
                            hashlib.sha256(str(draft_id).encode()).digest()[4:6], "big")
                            % max(int(remaining.total_seconds() // 60) - 1, 1)))
                else:
                    day = next_send_day(day, seq)
                    continue
            cur.execute("update outreach.drafts set scheduled_at=%s where id=%s",
                        (when, draft_id))
            return when
        day = next_send_day(day, seq)
    raise RuntimeError(f"no send slot found for draft {draft_id} within 60 send days")


def queue(cur, *, days: int = 5) -> list[dict]:
    """Upcoming scheduled sends grouped by day — what the console shows."""
    cur.execute(
        "select scheduled_at::date as d, count(*), min(scheduled_at), max(scheduled_at) "
        "from outreach.drafts where status='approved' and scheduled_at is not null "
        "and not exists (select 1 from outreach.sends s where s.draft_id = drafts.id) "
        "group by 1 order by 1 limit %s", (days,))
    return [{"day": d, "count": n, "first": lo, "last": hi}
            for d, n, lo, hi in cur.fetchall()]
