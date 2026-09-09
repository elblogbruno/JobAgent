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


def can_transition(current: ApplicationStatus, target: ApplicationStatus) -> bool:
    if current == target:
        return True
    return target in ALLOWED_TRANSITIONS.get(current, set())


def validate_transition(current: ApplicationStatus, target: ApplicationStatus, context: str = ""):
    if not can_transition(current, target):
        raise InvalidStateTransitionError(current, target, context)
