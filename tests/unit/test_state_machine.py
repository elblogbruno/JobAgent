import pytest
from packages.domain.enums import ApplicationStatus
from packages.domain.state_machine import (
    InvalidStateTransitionError,
    can_transition,
    validate_transition,
)


def test_allowed_transitions():
    assert can_transition(ApplicationStatus.DISCOVERED, ApplicationStatus.NORMALIZED) is True
    assert can_transition(ApplicationStatus.NORMALIZED, ApplicationStatus.EVALUATED) is True
    assert can_transition(ApplicationStatus.EVALUATED, ApplicationStatus.PREPARING) is True
    assert can_transition(ApplicationStatus.PREPARING, ApplicationStatus.READY) is True
    assert can_transition(ApplicationStatus.READY, ApplicationStatus.APPLYING) is True
    assert can_transition(ApplicationStatus.APPLYING, ApplicationStatus.SUBMITTED_UNVERIFIED) is True
    assert can_transition(ApplicationStatus.SUBMITTED_UNVERIFIED, ApplicationStatus.APPLIED) is True


def test_disallowed_transitions():
    assert can_transition(ApplicationStatus.DISCOVERED, ApplicationStatus.APPLIED) is False
    assert can_transition(ApplicationStatus.DUPLICATE, ApplicationStatus.APPLYING) is False
    assert can_transition(ApplicationStatus.REJECTED, ApplicationStatus.APPLIED) is False


def test_validate_transition_exception():
    with pytest.raises(InvalidStateTransitionError):
        validate_transition(ApplicationStatus.DISCOVERED, ApplicationStatus.APPLIED)
