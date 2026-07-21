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


# Which providers hit the CARD (cash — gated by MONTHLY_SPEND_CAP_GBP) vs the GCP
# CREDIT (tracked against the 90-day $300, not the cash cap). Gemini/Places/Geocoding
# bill the credit; MillionVerifier + the Anthropic API bill cash.
CASH_PROVIDERS = ("millionverifier", "anthropic")
CREDIT_PROVIDERS = ("gemini", "places", "geocoding")


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


def month_total_gbp(cur=None, *, providers: Optional[tuple[str, ...]] = None) -> float:
    """Recorded spend (GBP) this calendar month, optionally filtered to `providers`."""
    where = "where created_at >= date_trunc('month', now())"
    params: tuple = ()
    if providers is not None:
        where += " and provider = any(%s)"
        params = (list(providers),)
    sql = f'select coalesce(sum(cost_gbp), 0) from "{config.DB_SCHEMA}".spend {where}'
    if cur is not None:
        cur.execute(sql, params)
        return float(cur.fetchone()[0])
    with db.cursor(commit=False) as c:
        c.execute(sql, params)
        return float(c.fetchone()[0])


def credit_spent_gbp(cur=None) -> float:
    """Total GCP-credit-billed spend recorded (Gemini + Places + Geocoding), all-time —
    the burn-down against the $300 90-day credit. Separate from the cash cap."""
    sql = (f'select coalesce(sum(cost_gbp), 0) from "{config.DB_SCHEMA}".spend '
           "where provider = any(%s)")
    params = (list(CREDIT_PROVIDERS),)
    if cur is not None:
        cur.execute(sql, params)
        return float(cur.fetchone()[0])
    with db.cursor(commit=False) as c:
        c.execute(sql, params)
        return float(c.fetchone()[0])


def ensure_under_cap(cur=None) -> None:
    """Raise SpendCapExceeded when this month's CASH spend has reached the cap.
    Only cash-billed providers count (credit-billed Gemini/Places don't hit the card).
    Call before any paid provider work; a cap <= 0 disables the gate."""
    cap = config.MONTHLY_SPEND_CAP_GBP
    if cap <= 0:
        return
    total = month_total_gbp(cur=cur, providers=CASH_PROVIDERS)
    if total >= cap:
        raise SpendCapExceeded(
            f"monthly CASH spend cap reached: £{total:.2f} this month, cap £{cap:.2f} "
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


# Places API (New) SKU prices — USD per 1,000 CALLS (not per result; one search
# returns up to 20 businesses and bills as one call). Verified live 2026-07-19.
# Billed at the HIGHEST-tier field in the request's mask — the Places wrapper pins
# the mask per call-site so the tier is deterministic.
_PLACES_USD_PER_1K: dict[str, float] = {
    "text_search_pro": 32.0,          # name, address, location, types, photos
    "text_search_enterprise": 35.0,   # + websiteUri / ratings / hours / price
    "text_search_reviews": 40.0,      # + reviews / atmosphere (we avoid this tier)
    "place_details_pro": 17.0,
    "geocoding": 5.0,
}


def places_cost_gbp(sku: str, calls: int = 1) -> float:
    """GBP for `calls` Places API calls at the given SKU tier. Unknown SKU → the
    most expensive tier + a flag (never silently under-priced)."""
    rate = _PLACES_USD_PER_1K.get(sku)
    if rate is None:
        rate = max(_PLACES_USD_PER_1K.values())
        print(f"[spend] WARNING: unpriced Places SKU {sku!r} — using max rate {rate}")
    return calls / 1000.0 * rate * config.USD_TO_GBP


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
