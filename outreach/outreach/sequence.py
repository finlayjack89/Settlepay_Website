"""sequence_config loader + timing helpers (phase H).

ALL cadence / follow-up / send-window timing is read from sequence_config.json —
the pipeline never hardcodes delays. Those values are the real v1 timing (from
drafting playbook v1); the `graduation` thresholds are real operational policy.
"""
from __future__ import annotations
import datetime
import json
import pathlib
from typing import Optional

from . import config

SEQ_PATH = config.PROJECT_ROOT / "sequence_config.json"


def load_sequence_config(path=None) -> dict:
    return json.loads((pathlib.Path(path) if path else SEQ_PATH).read_text())


def in_send_window(seq: dict, now: Optional[datetime.datetime] = None) -> bool:
    """True if `now` falls inside the configured send window (config-driven, no
    hardcoded hours/days)."""
    now = now or datetime.datetime.now()
    w = seq.get("send_window", {})
    days = w.get("days")
    if days is not None and now.weekday() not in days:
        return False
    return w.get("start_hour", 0) <= now.hour < w.get("end_hour", 24)


def follow_up_delay_days(seq: dict, n: int) -> Optional[int]:
    """Delay (days) before follow-up #n, from config; None if no more follow-ups."""
    delays = seq.get("follow_up_delays_days", [])
    return delays[n] if 0 <= n < len(delays) else None


def graduation_thresholds(seq: Optional[dict] = None) -> dict:
    return (seq or load_sequence_config()).get("graduation", {})


def warmup_cap(day: int, seq: Optional[dict] = None) -> int:
    """Per-inbox daily send ceiling on warm-up `day` (1-indexed). Ramps up a new
    sending mailbox to protect deliverability, then holds at the steady ceiling.
    Config-driven (sequence_config.json `warmup`); never hardcoded in send logic."""
    w = (seq or load_sequence_config()).get("warmup", {})
    caps = w.get("daily_caps") or [w.get("steady", 50)]
    idx = max(1, day) - 1
    return caps[idx] if idx < len(caps) else (w.get("steady") or caps[-1])
