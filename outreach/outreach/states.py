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
    PARKED = "parked"


CONTACTABLE: frozenset[LeadState] = frozenset({
    LeadState.DISCOVERED, LeadState.ENRICHED, LeadState.DRAFTED,
    LeadState.AWAITING_APPROVAL, LeadState.APPROVED, LeadState.SENDING,
    LeadState.SENT, LeadState.REPLIED,
})
TERMINAL: frozenset[LeadState] = frozenset({
    LeadState.SUPPRESSED, LeadState.REJECTED, LeadState.DISCARDED, LeadState.BOUNCED,
})

# PARKED is in NEITHER set, and that is the point. Not CONTACTABLE, so nothing drafts
# or sends a parked lead; not TERMINAL, so a repair pass can re-admit it. It exists
# because `discarded` was being used for two things it should never mean: "our search
# found no email" and "our own machinery failed" (an over-eager regex, an exhausted
# verifier, a rate-limited API). Those are our failures, not verdicts about the lead,
# and they were destroying leads we had already paid to find and enrich.
#
# `discarded` stays terminal. SUPPRESSED and BOUNCED must be irreversible, and the
# CONTACTABLE/TERMINAL partition is what is_contactable() enforces — loosening it to
# rescue one member would weaken the invariant that matters most.
PARK_MAX = 3        # parks before a lead is genuinely discarded (retry stays bounded)

# allowed forward transitions (the mechanism); suppression handled separately
ALLOWED: dict[LeadState, set[LeadState]] = {
    LeadState.DISCOVERED: {LeadState.ENRICHED, LeadState.DISCARDED, LeadState.PARKED},
    LeadState.ENRICHED: {LeadState.DRAFTED, LeadState.DISCARDED, LeadState.PARKED},
    LeadState.PARKED: {LeadState.DISCOVERED, LeadState.ENRICHED, LeadState.DISCARDED},
    # DRAFTED -> PARKED is for the case where the draft is fine but the DATA under it
    # turned out to be wrong — most often a contact that belongs to another company.
    # The lead has to go back for re-enrichment, and its draft must be superseded in the
    # same breath so no orphan sits in the approval queue.
    LeadState.DRAFTED: {LeadState.APPROVED, LeadState.REJECTED, LeadState.DISCARDED,
                        LeadState.PARKED},
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


def park_lead(cur, company_number: str, reason: str) -> str:
    """Park a lead so a later pass can retry it — or discard it once the retry budget is
    spent. Returns the resulting state ('parked' or 'discarded'), or '' when the lead was
    in a state we must not touch (already sent, suppressed, bounced…).

    This is the write half of the rule the pipeline kept breaking: a stage's "I could not
    do my job" path must never write something that removes the row from its own backlog
    query. Parking stops the lead being worked AND leaves it findable; `discarded` did
    the first and made the second impossible.

    The counter and the new state move in ONE statement, so a crash between them cannot
    strand a lead as parked-forever with a stale count.
    """
    cur.execute(
        "update outreach.leads set "
        "  park_count = park_count + 1, "
        "  state = case when park_count + 1 >= %s then 'discarded'::outreach.lead_state "
        "               else 'parked'::outreach.lead_state end, "
        "  parked_reason = %s, parked_at = now(), updated_at = now() "
        # 'drafted' is included for the wrong-contact case; callers that park a drafted
        # lead must supersede its draft too. Anything past approval is deliberately out
        # of reach — a lead already sent, suppressed or bounced is never re-worked here.
        "where company_number = %s and state in ('discovered','enriched','parked','drafted') "
        "returning state::text",
        (PARK_MAX, reason[:500], company_number))
    row = cur.fetchone()
    return row[0] if row else ""
