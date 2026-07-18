import pytest

from outreach.states import (
    LeadState, SubscriberClass, transition, can_transition,
    IllegalTransition, CONTACTABLE, TERMINAL, is_contactable,
)

pytestmark = pytest.mark.floor_a


def test_forward_path():
    assert transition(LeadState.DISCOVERED, LeadState.ENRICHED) is LeadState.ENRICHED
    assert transition(LeadState.ENRICHED, LeadState.DRAFTED) is LeadState.DRAFTED
    assert transition(LeadState.AWAITING_APPROVAL, LeadState.APPROVED) is LeadState.APPROVED


def test_illegal_transition_rejected():
    with pytest.raises(IllegalTransition):
        transition(LeadState.DISCOVERED, LeadState.SENT)
    with pytest.raises(IllegalTransition):
        transition(LeadState.SENT, LeadState.APPROVED)


def test_suppression_allowed_from_any_state():
    for s in LeadState:
        assert can_transition(s, LeadState.SUPPRESSED) is True


def test_suppressed_is_terminal_and_not_contactable():
    assert LeadState.SUPPRESSED in TERMINAL
    assert LeadState.SUPPRESSED not in CONTACTABLE
    assert is_contactable(LeadState.SUPPRESSED) is False
    assert can_transition(LeadState.SUPPRESSED, LeadState.SENT) is False


def test_individual_unknown_never_contactable_by_design():
    # subscriber_class drives the firewall (phase C); the state machine guarantees
    # SUPPRESSED (the firewall's destination for individual/unknown) is non-contactable.
    assert {c.value for c in SubscriberClass} == {"corporate", "individual", "unknown"}
    assert not is_contactable(LeadState.SUPPRESSED)
