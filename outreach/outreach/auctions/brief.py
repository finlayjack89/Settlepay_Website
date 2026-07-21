"""email_context (Phase 6) — 2-4 factual bullets the drafter hooks the email on.

Not prose, not the email itself: just the concrete facts, so whoever/whatever writes the
message (the existing draft playbook, or a human) opens on something true and specific.
The payment quote is always first when present — it is the whole reason to write.
"""
from __future__ import annotations

from .models import EnrichedLead


def build(lead: EnrichedLead) -> list[str]:
    bullets: list[str] = []

    if lead.payment_quote:
        bullets.append(f'Says on their site: "{lead.payment_quote}"')
    elif lead.payment_methods:
        manual = [m for m in lead.payment_methods if m != "online card"]
        if manual:
            bullets.append("Takes payment by " + ", ".join(manual) +
                           " — no online card page.")

    if lead.categories:
        top = ", ".join(lead.categories[:3])
        bullets.append(f"Specialises in {top}.")

    if lead.next_auction_date:
        bullets.append(f"Next sale: {lead.next_auction_date}.")
    elif lead.upcoming_count:
        bullets.append(f"{lead.upcoming_count} catalogue(s) currently live — actively trading.")

    if lead.decision_maker_name:
        name = lead.decision_maker_name
        # CH format is "SURNAME, First" — show it human-first and not shouting
        if "," in name:
            surname, _, forenames = name.partition(",")
            name = f"{forenames.strip().title()} {surname.strip().title()}".strip()
        bullets.append(f"Decision-maker: {name}"
                       + (f" ({lead.decision_maker_email})" if lead.decision_maker_email else ""))
    elif lead.directors:
        bullets.append(f"{len(lead.directors)} director(s) on Companies House; "
                       "no email confirmed yet.")

    if lead.pecr_class != "corporate":
        bullets.append("PECR: not a confirmed corporate subscriber — research-only, "
                       "do not cold-email.")
    return bullets[:5]
