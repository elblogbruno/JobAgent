import pytest

from packages.applications.outcomes import OUTCOMES
from packages.domain.enums import ApplicationStatus as S
from packages.domain.state_machine import (
    InvalidStateTransitionError,
    can_record_outcome,
    can_transition,
    validate_outcome,
)


def test_every_outcome_maps_to_a_status():
    assert set(OUTCOMES) == {"applied", "interview", "offer", "rejected", "withdrawn"}
    assert OUTCOMES["applied"] is S.APPLIED
    assert OUTCOMES["interview"] is S.INTERVIEW


@pytest.mark.parametrize(
    "current",
    [S.EVALUATED, S.PREPARING, S.READY, S.READY_FOR_REVIEW, S.BLOCKED, S.FAILED, S.IGNORED],
)
def test_a_person_can_report_applying_by_hand_from_any_pre_submission_state(current):
    """The pipeline may not jump to APPLIED, but the candidate reporting it may."""
    assert can_transition(current, S.APPLIED) is False
    assert can_record_outcome(current, S.APPLIED) is True


def test_the_automated_path_is_unchanged():
    assert can_transition(S.APPLYING, S.SUBMITTED_UNVERIFIED) is True
    assert can_transition(S.SUBMITTED_UNVERIFIED, S.APPLIED) is True
    assert can_transition(S.EVALUATED, S.APPLIED) is False


def test_progress_after_applying_is_reportable():
    assert can_record_outcome(S.APPLIED, S.INTERVIEW) is True
    assert can_record_outcome(S.INTERVIEW, S.OFFER) is True
    assert can_record_outcome(S.INTERVIEW, S.REJECTED) is True
    assert can_record_outcome(S.APPLIED, S.WITHDRAWN) is True


def test_terminal_outcomes_cannot_be_walked_back():
    assert can_record_outcome(S.REJECTED, S.APPLIED) is False
    assert can_record_outcome(S.OFFER, S.INTERVIEW) is False
    with pytest.raises(InvalidStateTransitionError):
        validate_outcome(S.REJECTED, S.APPLIED)


def test_reporting_the_same_outcome_twice_is_allowed():
    assert can_record_outcome(S.APPLIED, S.APPLIED) is True


def test_an_interview_cannot_be_reported_before_applying():
    assert can_record_outcome(S.EVALUATED, S.INTERVIEW) is False
