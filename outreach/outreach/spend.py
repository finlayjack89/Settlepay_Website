"""Provider-agnostic spend ledger + monthly cap gate.

One outreach.spend row per paid unit of work (Anthropic tokens, MillionVerifier
verifies, whatever comes next), so the cap gate has a single number to check
regardless of provider. The month window is a calendar month on the DB clock
(date_trunc('month', now())), keeping every process's view of the total
consistent. config.MONTHLY_SPEND_CAP_GBP is read at call time, not import time,
so an env change (or a test monkeypatch) takes effect without a restart; a cap
<= 0 disables the gate entirely, and a month total exactly at the cap already
blocks further paid work.
"""
from __future__ import annotations
import json
from typing import Any, Optional

from . import config, db


class SpendCapExceeded(Exception):
    """Raised when this month's recorded spend has reached the monthly cap."""


def record(
    provider: str,
    *,
    purpose: Optional[str] = None,
    model: Optional[str] = None,
    units_in: int = 0,
    units_out: int = 0,
    cost_gbp: float = 0.0,
    detail: Optional[dict[str, Any]] = None,
    job_id: Optional[int] = None,
    company_number: Optional[str] = None,
    cur=None,
) -> None:
    """Insert one spend row. If `cur` is given, use the caller's transaction
    (so it commits/rolls back atomically with their work); otherwise open one."""
    sql = (
        f'insert into "{config.DB_SCHEMA}".spend '
        "(provider, purpose, model, units_in, units_out, cost_gbp, detail, job_id, company_number) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    params = (
        provider, purpose, model, units_in, units_out, cost_gbp,
        json.dumps(detail) if detail is not None else None,
        job_id, company_number,
    )
    if cur is not None:
        cur.execute(sql, params)
    else:
        with db.cursor() as c:
            c.execute(sql, params)


def month_total_gbp(cur=None) -> float:
    """Total recorded spend (GBP) for the current calendar month."""
    sql = (
        f'select coalesce(sum(cost_gbp), 0) from "{config.DB_SCHEMA}".spend '
        "where created_at >= date_trunc('month', now())"
    )
    if cur is not None:
        cur.execute(sql)
        return float(cur.fetchone()[0])
    with db.cursor(commit=False) as c:
        c.execute(sql)
        return float(c.fetchone()[0])


def ensure_under_cap(cur=None) -> None:
    """Raise SpendCapExceeded when the month's spend has reached the cap.
    Call before any paid provider work; a cap <= 0 disables the gate."""
    cap = config.MONTHLY_SPEND_CAP_GBP
    if cap <= 0:
        return
    total = month_total_gbp(cur=cur)
    if total >= cap:
        raise SpendCapExceeded(
            f"monthly spend cap reached: £{total:.2f} recorded this month, cap £{cap:.2f} "
            "(MONTHLY_SPEND_CAP_GBP) — refusing further paid work until the new month"
        )


def anthropic_cost_gbp(units_in: int, units_out: int) -> float:
    """Convert Anthropic token counts to GBP at the config-pinned list prices."""
    usd = (
        units_in / 1_000_000 * config.ANTHROPIC_INPUT_USD_PER_MTOK
        + units_out / 1_000_000 * config.ANTHROPIC_OUTPUT_USD_PER_MTOK
    )
    return usd * config.USD_TO_GBP


# Gemini list prices (USD per 1M tokens, in/out), verified live on Vertex 2026-07-19.
# Thinking tokens are billed at the OUTPUT rate, so callers pass units_out =
# candidates + thoughts. Update in the same change as ~/.claude/LLM_MODELS.md.
_GEMINI_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "gemini-3-flash-preview": (0.50, 3.00),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.1-pro-preview": (2.00, 12.00),
}


def gemini_cost_gbp(model: str, units_in: int, units_out: int) -> float:
    """Convert Gemini token counts to GBP. `units_out` must already include
    thinking tokens (billed at the output rate). Unknown models fall back to the
    most expensive known rate and are flagged — never silently under-priced."""
    rate = _GEMINI_USD_PER_MTOK.get(model)
    if rate is None:
        rate = max(_GEMINI_USD_PER_MTOK.values())  # conservative: never undercount
        print(f"[spend] WARNING: unpriced Gemini model {model!r} — using max known rate {rate}")
    usd = units_in / 1_000_000 * rate[0] + units_out / 1_000_000 * rate[1]
    return usd * config.USD_TO_GBP
