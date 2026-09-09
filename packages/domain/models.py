from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, HttpUrl
from packages.domain.enums import (
    AnswerSource,
    ApplicationStatus,
    BlockedReason,
    DocumentKind,
    ExecutionMode,
    JobSourceType,
    Recommendation,
)


class JobSearchQuery(BaseModel):
    query: Optional[str] = None
    locations: List[str] = Field(default_factory=list)
    remote: Optional[bool] = None
    sources: List[JobSourceType] = Field(default_factory=list)
    limit: int = 50
    offset: int = 0


class RawJob(BaseModel):
    source: JobSourceType
    source_job_id: str
    canonical_url: str
    apply_url: str
    company: str
    role: str
    location: Optional[str] = None
    remote_policy: Optional[str] = None
    salary: Optional[str] = None
    currency: Optional[str] = None
    description: str
    requirements: List[str] = Field(default_factory=list)
    preferred_requirements: List[str] = Field(default_factory=list)
    technologies: List[str] = Field(default_factory=list)
    employment_type: Optional[str] = None
    published_at: Optional[datetime] = None
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    raw_payload: Dict[str, Any] = Field(default_factory=dict)


class CanonicalJob(BaseModel):
    id: Optional[str] = None
    dedup_hash: str
    company: str
    normalized_company: str
    role: str
    normalized_role: str
    canonical_url: str
    apply_url: str
    source: JobSourceType
    source_job_id: str
    location: Optional[str] = None
    is_remote: bool = False
    is_hybrid: bool = False
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    description: str
    requirements: List[str] = Field(default_factory=list)
    preferred_requirements: List[str] = Field(default_factory=list)
    technologies: List[str] = Field(default_factory=list)
    status: ApplicationStatus = ApplicationStatus.NORMALIZED
    published_at: Optional[datetime] = None
    discovered_at: datetime = Field(default_factory=datetime.utcnow)


class MatchScorecard(BaseModel):
    score: int = Field(ge=0, le=100)
    recommendation: Recommendation
    confidence: float = Field(ge=0.0, le=1.0)
    strengths: List[str] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list)
    hard_requirements: List[str] = Field(default_factory=list)
    preferred_requirements: List[str] = Field(default_factory=list)
    matched_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    seniority_fit: str = ""
    location_fit: str = ""
    salary_fit: str = ""
    domain_fit: str = ""
    why_this_is_interesting: str = ""
    risks: List[str] = Field(default_factory=list)


class CandidateIdentity(BaseModel):
    name: str
    email: str
    phone: str
    location: str
    linkedin: Optional[str] = None
    github: Optional[str] = None
    website: Optional[str] = None


class CandidateVisaRequirements(BaseModel):
    authorized_eu: bool = True
    authorized_us: bool = False
    requires_sponsorship_us: bool = True
    requires_sponsorship_eu: bool = False


class CandidateJobPreferences(BaseModel):
    locations: List[str] = Field(default_factory=list)
    remote: bool = True
    hybrid: bool = True
    onsite: bool = False
    roles: List[str] = Field(default_factory=list)
    interests: List[str] = Field(default_factory=list)
    minimum_salary: Optional[float] = None
    preferred_salary: Optional[float] = None
    currencies: List[str] = Field(default_factory=lambda: ["EUR", "USD"])
    relocation: bool = False
    visa_requirements: CandidateVisaRequirements = Field(default_factory=CandidateVisaRequirements)


class ApplicationPreferences(BaseModel):
    execution_mode: ExecutionMode = ExecutionMode.AUTO_APPLY
    auto_apply_threshold: int = 82
    prepare_threshold: int = 65
    maximum_daily_applications: int = 10
    allowed_sources: List[str] = Field(
        default_factory=lambda: ["greenhouse", "lever", "ashby", "company-careers"]
    )
    excluded_companies: List[str] = Field(default_factory=list)
    excluded_roles: List[str] = Field(default_factory=list)
    require_salary_match: bool = False
    require_remote_match: bool = True
    follow_up_days: int = 7


class ReactiveResumeConfig(BaseModel):
    master_resume_id: str = ""
    master_resume_name: str = "Bruno Moya — Master CV"


class CandidateProfileModel(BaseModel):
    identity: CandidateIdentity
    job_preferences: CandidateJobPreferences
    application_preferences: ApplicationPreferences
    reactive_resume: ReactiveResumeConfig = Field(default_factory=ReactiveResumeConfig)


class PreflightCheckItem(BaseModel):
    name: str
    passed: bool
    details: str = ""


class PreflightResult(BaseModel):
    passed: bool
    checks: List[PreflightCheckItem] = Field(default_factory=list)
    failure_reasons: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    dom_snapshot_id: Optional[str] = None


class SubmissionEvidence(BaseModel):
    verified: bool
    evidence_type: str # DOM_TEXT | URL_REDIRECT | CONFIRMATION_ID | HTTP_STATUS
    details: str
    confirmation_id: Optional[str] = None
    redirect_url: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class FormFieldDescriptor(BaseModel):
    name: str
    label: str
    field_type: str # text, email, phone, file, select, radio, checkbox, textarea
    required: bool = False
    options: List[str] = Field(default_factory=list)
    current_value: Optional[str] = None
    assigned_value: Optional[str] = None
