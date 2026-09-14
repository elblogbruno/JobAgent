from enum import Enum


class ExecutionMode(str, Enum):
    DISCOVERY_ONLY = "DISCOVERY_ONLY"
    PREPARE = "PREPARE"
    REVIEW_BEFORE_SUBMIT = "REVIEW_BEFORE_SUBMIT"
    AUTO_APPLY = "AUTO_APPLY"


class ApplicationStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    NORMALIZED = "NORMALIZED"
    DUPLICATE = "DUPLICATE"
    EVALUATED = "EVALUATED"
    IGNORED = "IGNORED"
    PREPARING = "PREPARING"
    NEEDS_USER_INPUT = "NEEDS_USER_INPUT"
    READY = "READY"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPLYING = "APPLYING"
    SUBMITTED_UNVERIFIED = "SUBMITTED_UNVERIFIED"
    APPLIED = "APPLIED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    INTERVIEW = "INTERVIEW"
    REJECTED = "REJECTED"
    OFFER = "OFFER"
    WITHDRAWN = "WITHDRAWN"


class BlockedReason(str, Enum):
    CAPTCHA = "BLOCKED_CAPTCHA"
    TWO_FACTOR = "BLOCKED_2FA"
    LOGIN_REQUIRED = "BLOCKED_LOGIN"
    RATE_LIMITED = "BLOCKED_RATE_LIMIT"
    UNKNOWN = "BLOCKED_UNKNOWN"


class JobSourceType(str, Enum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    INFOJOBS = "infojobs"
    COMPANY_CAREERS = "company-careers"
    GENERIC_WEB = "generic-web"
    CONFIGURED_FEEDS = "configured-feeds"
    LINKEDIN = "linkedin"
    INDEED = "indeed"
    WORKDAY = "workday"
    WORKABLE = "workable"
    SMARTRECRUITERS = "smartrecruiters"


class RoleCategory(str, Enum):
    """How a discovered role relates to the candidate's trajectory."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    STRETCH = "stretch"
    AVOID = "avoid"


class CapabilityKind(str, Enum):
    """The nine facets the CandidateCapabilityGraph keeps separate."""

    TECHNOLOGY = "technology"
    CAPABILITY = "capability"
    DOMAIN = "domain"
    RESPONSIBILITY = "responsibility"
    SENIORITY = "seniority"
    LEADERSHIP = "leadership"
    PRODUCT_OWNERSHIP = "product-ownership"
    TECHNICAL_DEPTH = "technical-depth"
    TRANSFERABLE = "transferable"


class SearchProviderId(str, Enum):
    LINKEDIN = "linkedin"
    INFOJOBS = "infojobs"
    GOOGLE = "google"
    INDEED = "indeed"
    GENERIC_WEB = "generic-web"


class SearchQueryStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"
    ARCHIVED = "archived"


class DiscoveryChannel(str, Enum):
    """How a job entered the system."""

    BROWSER_EXTENSION = "browser-extension"
    DISCOVERY_CYCLE = "discovery-cycle"
    MANUAL = "manual"


class RoleProposalStatus(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class Recommendation(str, Enum):
    APPLY = "APPLY"
    PREPARE = "PREPARE"
    IGNORE = "IGNORE"


class DocumentKind(str, Enum):
    RESUME = "resume"
    COVER_LETTER = "cover-letter"


class EventSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AnswerSource(str, Enum):
    USER_CONFIRMED = "user"
    PROFILE_DERIVED = "profile"
    INFERRED = "inferred"
