"""Score & qualify (Phase 5) — one 0..100 number per lead, sortable, with a breakdown.

Weighted from the four things that actually predict a good SettlePay conversation
(weights in config.SCORE_WEIGHTS):
  * manual_payment_signal  — the biggest: literal proof they take payment by hand.
  * category_value         — fine art / jewellery houses > general clearance.
  * auction_activity       — a scheduled/recent sale means an active business.
  * decision_maker_email   — a verified named contact is worth more than info@.

Two dampers reflect reality, not enthusiasm:
  * a lead that ALREADY takes card online is a weaker fit — its payment factor is halved.
  * a non-corporate (PECR individual) lead can't be cold-emailed, so it's capped low
    however good it looks — it's research-only, and the score must say so.
"""
from __future__ import annotations

from . import config
from . import categories as _cat
from .models import EnrichedLead

_W = config.SCORE_WEIGHTS


def score(lead: EnrichedLead) -> tuple[int, dict]:
    factors: dict[str, float] = {}

    # 1. manual-payment signal (0..1)
    if lead.payment_methods:
        manual = any(m in {"bank transfer", "bacs", "cheque", "cash", "card over the phone"}
                     for m in lead.payment_methods)
        online = "online card" in lead.payment_methods
        pay = 1.0 if manual else 0.3
        if online:
            pay *= 0.5            # already has online card -> weaker fit
        factors["manual_payment_signal"] = pay
    else:
        factors["manual_payment_signal"] = 0.0

    # 2. category value (0..1)
    factors["category_value"] = _cat.value_score(lead.categories)

    # 3. auction activity (0..1)
    factors["auction_activity"] = 1.0 if (lead.upcoming_count or lead.next_auction_date) else 0.2

    # 4. decision-maker email (0..1)
    factors["decision_maker_email"] = (
        1.0 if lead.decision_maker_email else (0.4 if lead.generic_email else 0.0))

    raw = sum(_W[k] * v for k, v in factors.items())
    total = raw / sum(_W.values()) * 100.0

    # non-corporate = research-only; cap hard so it can never top the sort
    if lead.pecr_class != "corporate":
        total = min(total, 25.0)
        factors["pecr_cap"] = "research-only (<=25)"

    breakdown = {k: round(v, 2) for k, v in factors.items() if isinstance(v, float)}
    breakdown.update({k: v for k, v in factors.items() if not isinstance(v, float)})
    return round(total), breakdown
