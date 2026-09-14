from typing import Dict, Set
from packages.domain.enums import ApplicationStatus


class InvalidStateTransitionError(Exception):
    def __init__(self, current: ApplicationStatus, target: ApplicationStatus, reason: str = ""):
        message = f"Cannot transition from {current} to {target}"
        if reason:
            message += f": {reason}"
        super().__init__(message)
        self.current = current
        self.target = target


ALLOWED_TRANSITIONS: Dict[ApplicationStatus, Set[ApplicationStatus]] = {
    ApplicationStatus.DISCOVERED: {
        ApplicationStatus.NORMALIZED,
        ApplicationStatus.DUPLICATE,
        ApplicationStatus.FAILED,
    },
    ApplicationStatus.NORMALIZED: {
        ApplicationStatus.EVALUATED,
        ApplicationStatus.DUPLICATE,
        ApplicationStatus.FAILED,
    },
    ApplicationStatus.DUPLICATE: set(), # Terminal
    ApplicationStatus.EVALUATED: {
        ApplicationStatus.PREPARING,
        ApplicationStatus.IGNORED,
        ApplicationStatus.FAILED,
    },
    ApplicationStatus.IGNORED: {
        ApplicationStatus.PREPARING, # Manual override allowed
    },
    ApplicationStatus.PREPARING: {
        ApplicationStatus.READY,
        ApplicationStatus.NEEDS_USER_INPUT,
        ApplicationStatus.FAILED,
    },
    ApplicationStatus.NEEDS_USER_INPUT: {
        ApplicationStatus.PREPARING,
        ApplicationStatus.IGNORED,
    },
    ApplicationStatus.READY: {
        ApplicationStatus.READY_FOR_REVIEW,
        ApplicationStatus.APPLYING,
        ApplicationStatus.IGNORED,
        ApplicationStatus.FAILED,
    },
    ApplicationStatus.READY_FOR_REVIEW: {
        ApplicationStatus.APPLYING, # Upon user confirmation
        ApplicationStatus.IGNORED,  # Upon user dismiss
        ApplicationStatus.FAILED,
    },
    ApplicationStatus.APPLYING: {
        ApplicationStatus.SUBMITTED_UNVERIFIED,
        ApplicationStatus.BLOCKED,
        ApplicationStatus.FAILED,
    },
    ApplicationStatus.SUBMITTED_UNVERIFIED: {
        ApplicationStatus.APPLIED,
        ApplicationStatus.FAILED,
    },
    ApplicationStatus.APPLIED: {
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.BLOCKED: {
        ApplicationStatus.APPLYING, # Manual resume after unblock
        ApplicationStatus.IGNORED,
        ApplicationStatus.FAILED,
    },
    ApplicationStatus.FAILED: {
        ApplicationStatus.PREPARING, # Retry
        ApplicationStatus.APPLYING,
        ApplicationStatus.IGNORED,
    },
    ApplicationStatus.INTERVIEW: {
        ApplicationStatus.OFFER,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.REJECTED: set(),
    ApplicationStatus.OFFER: set(),
    ApplicationStatus.WITHDRAWN: set(),
}


# A person reporting what they did by hand carries more authority than the
# pipeline's own progression. Someone who applied on the company site can say so
# from any pre-submission state, which ALLOWED_TRANSITIONS deliberately forbids
# for the automated path.
MANUALLY_REPORTABLE: Dict[ApplicationStatus, Set[ApplicationStatus]] = {
    ApplicationStatus.APPLIED: {
        ApplicationStatus.DISCOVERED,
        ApplicationStatus.NORMALIZED,
        ApplicationStatus.EVALUATED,
        ApplicationStatus.IGNORED,
        ApplicationStatus.PREPARING,
        ApplicationStatus.NEEDS_USER_INPUT,
        ApplicationStatus.READY,
        ApplicationStatus.READY_FOR_REVIEW,
        ApplicationStatus.APPLYING,
        ApplicationStatus.SUBMITTED_UNVERIFIED,
        ApplicationStatus.BLOCKED,
        ApplicationStatus.FAILED,
    },
    ApplicationStatus.INTERVIEW: {ApplicationStatus.APPLIED, ApplicationStatus.SUBMITTED_UNVERIFIED},
    ApplicationStatus.OFFER: {ApplicationStatus.APPLIED, ApplicationStatus.INTERVIEW},
    ApplicationStatus.REJECTED: {
        ApplicationStatus.APPLIED,
        ApplicationStatus.SUBMITTED_UNVERIFIED,
        ApplicationStatus.INTERVIEW,
    },
    ApplicationStatus.WITHDRAWN: {
        ApplicationStatus.APPLIED,
        ApplicationStatus.SUBMITTED_UNVERIFIED,
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.READY,
        ApplicationStatus.READY_FOR_REVIEW,
    },
}


def can_transition(current: ApplicationStatus, target: ApplicationStatus) -> bool:
    if current == target:
        return True
    return target in ALLOWED_TRANSITIONS.get(current, set())


def validate_transition(current: ApplicationStatus, target: ApplicationStatus, context: str = ""):
    if not can_transition(current, target):
        raise InvalidStateTransitionError(current, target, context)


def can_record_outcome(current: ApplicationStatus, target: ApplicationStatus) -> bool:
    """Whether a human may report `target` on a run currently in `current`."""
    if current == target:
        return True
    if can_transition(current, target):
        return True
    return current in MANUALLY_REPORTABLE.get(target, set())


def validate_outcome(current: ApplicationStatus, target: ApplicationStatus, context: str = ""):
    if not can_record_outcome(current, target):
        raise InvalidStateTransitionError(current, target, context)
