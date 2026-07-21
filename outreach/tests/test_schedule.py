import datetime
import uuid

import pytest

from outreach import schedule

pytestmark = pytest.mark.floor_g

MON = datetime.date(2026, 7, 20)      # Monday
SAT = datetime.date(2026, 7, 25)      # Saturday


def _approved(cur, n=1):
    out = []
    for _ in range(n):
        cn = f"SCH_{uuid.uuid4().hex[:8]}"
        did = uuid.uuid4()
        cur.execute(
            "insert into outreach.leads (company_number, company_name, company_type, "
            "subscriber_class, state) values (%s,%s,'ltd','corporate','approved')", (cn, cn))
        cur.execute(
            "insert into outreach.drafts (id, company_number, subject, body_original, "
            "prompt_version, status) values (%s,%s,'a subject','body','t','approved')",
            (did, cn))
        out.append(did)
    return out


def test_send_days_exclude_the_weekend():
    assert schedule.is_send_day(MON)
    assert not schedule.is_send_day(SAT)
    assert schedule.next_send_day(datetime.date(2026, 7, 24)) == datetime.date(2026, 7, 27)


def test_slots_spread_across_the_window_without_a_fixed_cadence():
    ids = [uuid.uuid4() for _ in range(50)]
    ts = sorted(schedule._slot_time(MON, i, 50, ids[i]) for i in range(50))
    start_h, end_h, _ = schedule._window()
    assert ts[0].hour >= start_h and ts[-1].hour < end_h
    gaps = {int((ts[i + 1] - ts[i]).total_seconds() // 60) for i in range(len(ts) - 1)}
    # a single repeated gap would be a fixed cadence — the thing jitter exists to avoid
    assert len(gaps) > 5


def test_slot_time_is_deterministic_per_draft():
    did = uuid.uuid4()
    assert schedule._slot_time(MON, 3, 20, did) == schedule._slot_time(MON, 3, 20, did)


def test_warmup_counts_sending_days_not_calendar_days(db_rollback):
    """A weekend must not advance the ramp. Calendar counting turned Friday's cap
    into Monday's cap+2 — a volume jump after two days of silence."""
    cur = db_rollback.cursor()
    inbox = f"warm-{uuid.uuid4().hex[:6]}@x.uk"
    ids = _approved(cur, 3)
    for did, day in zip(ids, (datetime.date(2026, 7, 22), datetime.date(2026, 7, 23),
                              datetime.date(2026, 7, 24))):
        cur.execute("update outreach.drafts set scheduled_at=%s where id=%s",
                    (datetime.datetime.combine(day, datetime.time(9)), did))
    # Monday 27th follows a weekend: 3 sending days done, so it is day 4 — not day 6
    assert schedule.warmup_day_for(datetime.date(2026, 7, 27), cur=cur, inbox=inbox) == 4


def test_approval_queue_respects_daily_capacity_and_rolls_over(db_rollback, monkeypatch):
    cur = db_rollback.cursor()
    monkeypatch.setattr(schedule.config, "PER_INBOX_DAILY_CAP", 50)
    inbox = f"q-{uuid.uuid4().hex[:6]}@x.uk"
    now = datetime.datetime(2026, 7, 20, 8, 0)     # Monday, window open
    days = {}
    for did in _approved(cur, 30):
        t = schedule.assign_slot(did, cur=cur, inbox=inbox, now=now)
        days.setdefault(t.date(), []).append(t)
    # warm-up day 1 caps at 5, so the rest must roll forward rather than pile up
    assert len(days[MON]) == 5
    assert len(days[datetime.date(2026, 7, 21)]) == 8
    assert sum(len(v) for v in days.values()) == 30
    assert SAT not in days                          # never lands on a weekend


def test_slot_assignment_is_idempotent(db_rollback):
    cur = db_rollback.cursor()
    (did,) = _approved(cur)
    first = schedule.assign_slot(did, cur=cur, inbox="i@x.uk",
                                 now=datetime.datetime(2026, 7, 20, 8, 0))
    again = schedule.assign_slot(did, cur=cur, inbox="i@x.uk",
                                 now=datetime.datetime(2026, 7, 20, 9, 0))
    assert first == again


def test_never_schedules_into_the_past(db_rollback):
    cur = db_rollback.cursor()
    now = datetime.datetime(2026, 7, 20, 13, 30, tzinfo=schedule.sequence.send_tz())
    for did in _approved(cur, 3):
        assert schedule.assign_slot(did, cur=cur, inbox="p@x.uk", now=now) > now


def test_slots_are_uk_wall_clock_not_container_time(db_rollback):
    """The container runs UTC. A naive slot would be stored as UTC and land an hour
    late for the whole of British Summer Time."""
    cur = db_rollback.cursor()
    (did,) = _approved(cur)
    t = schedule.assign_slot(did, cur=cur, inbox="tz@x.uk",
                             now=datetime.datetime(2026, 7, 20, 6, 0,
                                                   tzinfo=datetime.timezone.utc))
    assert t.tzinfo is not None
    london = t.astimezone(schedule.sequence.send_tz())
    start_h, end_h, _ = schedule._window()
    assert start_h <= london.hour < end_h
    # July is BST (UTC+1), so the stored UTC hour must be one BEHIND the local hour
    assert t.astimezone(datetime.timezone.utc).hour == london.hour - 1


def test_after_the_window_closes_it_rolls_to_the_next_send_day(db_rollback):
    cur = db_rollback.cursor()
    (did,) = _approved(cur)
    t = schedule.assign_slot(did, cur=cur, inbox="l@x.uk",
                             now=datetime.datetime(2026, 7, 24, 18, 0))   # Fri evening
    assert t.date() == datetime.date(2026, 7, 27)                          # Monday


def test_slots_never_fall_after_the_days_last_tick():
    """A slot past the final in-window tick would never fire: the tick that would
    send it lands outside the window."""
    ids = [uuid.uuid4() for _ in range(50)]
    ts = sorted(schedule._slot_time(MON, i, 50, ids[i]) for i in range(50))
    _, end_h, _ = schedule._window()
    close = datetime.datetime.combine(MON, datetime.time(hour=end_h),
                                      tzinfo=schedule.sequence.send_tz())
    assert (close - ts[-1]).total_seconds() / 60 >= schedule.TICK_INTERVAL_MIN
