"""Per-lead state machine + subscriber classification.

INVARIANT: individual/unknown subscribers are NEVER contactable. Suppression is
allowed from ANY state (fail-safe firewall move) and is terminal.
"""
from __future__ import annotations
import enum


class SubscriberClass(str, enum.Enum):
    CORPORATE = "corporate"
    INDIVIDUAL = "individual"
    UNKNOWN = "unknown"


class LeadState(str, enum.Enum):
    DISCOVERED = "discovered"
    ENRICHED = "enriched"
    DRAFTED = "drafted"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    SENDING = "sending"
    SENT = "sent"
    REPLIED = "replied"
    SUPPRESSED = "suppressed"
    REJECTED = "rejected"
    DISCARDED = "discarded"
    BOUNCED = "bounced"


CONTACTABLE: frozenset[LeadState] = frozenset({
    LeadState.DISCOVERED, LeadState.ENRICHED, LeadState.DRAFTED,
    LeadState.AWAITING_APPROVAL, LeadState.APPROVED, LeadState.SENDING,
    LeadState.SENT, LeadState.REPLIED,
})
TERMINAL: frozenset[LeadState] = frozenset({
    LeadState.SUPPRESSED, LeadState.REJECTED, LeadState.DISCARDED, LeadState.BOUNCED,
})

# allowed forward transitions (the mechanism); suppression handled separately
ALLOWED: dict[LeadState, set[LeadState]] = {
    LeadState.DISCOVERED: {LeadState.ENRICHED, LeadState.DISCARDED},
    LeadState.ENRICHED: {LeadState.DRAFTED, LeadState.DISCARDED},
    LeadState.DRAFTED: {LeadState.APPROVED, LeadState.REJECTED, LeadState.DISCARDED},
    LeadState.AWAITING_APPROVAL: {LeadState.APPROVED, LeadState.REJECTED},
    LeadState.APPROVED: {LeadState.SENDING, LeadState.REJECTED},
    LeadState.SENDING: {LeadState.SENT, LeadState.BOUNCED},
    LeadState.SENT: {LeadState.REPLIED, LeadState.BOUNCED},
    LeadState.REPLIED: set(),
    LeadState.SUPPRESSED: set(),
    LeadState.REJECTED: set(),
    LeadState.DISCARDED: set(),
    LeadState.BOUNCED: set(),
}


class IllegalTransition(Exception):
    pass


def can_transition(src: LeadState, dst: LeadState) -> bool:
    # suppression is always permitted (PECR fail-safe) and is terminal
    if dst is LeadState.SUPPRESSED:
        return True
    return dst in ALLOWED.get(src, set())


def transition(src: LeadState, dst: LeadState) -> LeadState:
    if not can_transition(src, dst):
        raise IllegalTransition(f"{src.value} -> {dst.value} is not an allowed transition")
    return dst


def is_contactable(state: LeadState) -> bool:
    return state in CONTACTABLE
