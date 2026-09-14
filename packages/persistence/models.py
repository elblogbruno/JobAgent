import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship
from packages.persistence.database import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class JobORM(Base):
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    dedup_hash = Column(String(64), unique=True, nullable=False, index=True)
    source = Column(String(50), nullable=False, index=True)
    source_job_id = Column(String(255), nullable=False, index=True)
    company = Column(String(255), nullable=False, index=True)
    normalized_company = Column(String(255), nullable=False, index=True)
    role = Column(String(255), nullable=False)
    normalized_role = Column(String(255), nullable=False, index=True)
    canonical_url = Column(Text, nullable=False)
    apply_url = Column(Text, nullable=False)
    location = Column(String(255), nullable=True)
    is_remote = Column(Boolean, default=False, index=True)
    is_hybrid = Column(Boolean, default=False)
    salary_min = Column(Float, nullable=True)
    salary_max = Column(Float, nullable=True)
    salary_currency = Column(String(10), nullable=True)
    description = Column(Text, nullable=False)
    requirements = Column(JSON, default=list)
    preferred_requirements = Column(JSON, default=list)
    technologies = Column(JSON, default=list)
    status = Column(String(50), default="NORMALIZED", index=True)
    published_at = Column(DateTime, nullable=True)
    discovered_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Provenance: how this job entered the system, so search performance can be
    # attributed back to the query that produced it.
    discovered_by = Column(String(50), default="discovery-cycle", index=True)
    search_query_id = Column(String(36), nullable=True, index=True)
    search_provider = Column(String(50), nullable=True)
    source_url = Column(Text, nullable=True)
    description_fingerprint = Column(String(64), nullable=True, index=True)

    # Cached evaluation, so search performance can be judged without walking runs.
    match_score = Column(Integer, nullable=True, index=True)
    scorecard = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    snapshots = relationship("JobSnapshotORM", back_populates="job", cascade="all, delete-orphan")
    application_runs = relationship("ApplicationRunORM", back_populates="job")


class JobSourceORM(Base):
    __tablename__ = "job_sources"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    source_type = Column(String(50), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    base_url = Column(Text, nullable=False)
    config = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    last_scraped_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class JobSnapshotORM(Base):
    __tablename__ = "job_snapshots"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    job_id = Column(String(36), ForeignKey("jobs.id"), nullable=False, index=True)
    snapshot_type = Column(String(50), nullable=False) # PRE_SUBMIT_DOM, SUBMIT_CONFIRMATION, ERROR
    html_content = Column(Text, nullable=True)
    screenshot_path = Column(Text, nullable=True)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("JobORM", back_populates="snapshots")


class ApplicationRunORM(Base):
    __tablename__ = "application_runs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    job_id = Column(String(36), ForeignKey("jobs.id"), nullable=False, index=True)
    reactive_resume_application_id = Column(String(255), nullable=True, index=True)
    reactive_resume_resume_id = Column(String(255), nullable=True, index=True)
    status = Column(String(50), default="PREPARING", index=True)
    execution_mode = Column(String(50), default="AUTO_APPLY")
    match_score = Column(Integer, nullable=True)
    scorecard = Column(JSON, nullable=True)
    tailored_resume_path = Column(Text, nullable=True)
    cover_letter_text = Column(Text, nullable=True)
    preflight_passed = Column(Boolean, default=False)
    preflight_report = Column(JSON, nullable=True)
    submission_evidence = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    error_category = Column(String(50), nullable=True)

    # Outcomes the candidate reported by hand, including applications they sent
    # themselves on the company site.
    applied_at = Column(DateTime, nullable=True)
    submitted_manually = Column(Boolean, default=False)
    outcome_history = Column(JSON, default=list)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    job = relationship("JobORM", back_populates="application_runs")
    browser_runs = relationship("BrowserRunORM", back_populates="application_run")
    events = relationship("ApplicationEventORM", back_populates="application_run")


class BrowserRunORM(Base):
    __tablename__ = "browser_runs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    application_run_id = Column(String(36), ForeignKey("application_runs.id"), nullable=False, index=True)
    adapter_name = Column(String(100), nullable=False)
    pages_visited = Column(Integer, default=1)
    form_fields_analyzed = Column(JSON, default=list)
    form_fields_filled = Column(JSON, default=dict)
    trace_path = Column(Text, nullable=True)
    start_time = Column(DateTime, default=datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    success = Column(Boolean, default=False)

    application_run = relationship("ApplicationRunORM", back_populates="browser_runs")


class ApplicationEventORM(Base):
    __tablename__ = "application_events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    application_run_id = Column(String(36), ForeignKey("application_runs.id"), nullable=True, index=True)
    job_id = Column(String(36), ForeignKey("jobs.id"), nullable=True, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    severity = Column(String(20), default="INFO")
    message = Column(Text, nullable=False)
    details = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    application_run = relationship("ApplicationRunORM", back_populates="events")


class AgentDecisionORM(Base):
    __tablename__ = "agent_decisions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    run_id = Column(String(36), nullable=False, index=True)
    agent_name = Column(String(100), nullable=False, index=True)
    decision = Column(String(100), nullable=False)
    confidence = Column(Float, default=1.0)
    reason = Column(Text, nullable=False)
    input_summary = Column(JSON, default=dict)
    evidence = Column(JSON, default=list)
    model_used = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AgentRunORM(Base):
    __tablename__ = "agent_runs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    run_type = Column(String(100), nullable=False, index=True) # DISCOVERY, ANALYSIS, SUBMISSION, MONITOR
    status = Column(String(50), default="RUNNING", index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)
    metrics = Column(JSON, default=dict)


class NotificationORM(Base):
    __tablename__ = "notifications"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    application_run_id = Column(String(36), ForeignKey("application_runs.id"), nullable=True)
    notification_type = Column(String(50), nullable=False)
    channel = Column(String(50), default="TELEGRAM")
    status = Column(String(20), default="PENDING")
    payload = Column(JSON, default=dict)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class CandidateAnswerORM(Base):
    __tablename__ = "candidate_answers"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    question_canonical = Column(String(255), unique=True, nullable=False, index=True)
    question_raw = Column(Text, nullable=True)
    answer = Column(JSON, nullable=False)
    answer_type = Column(String(50), default="string") # boolean, string, number, array
    source = Column(String(50), default="user") # user, profile, inferred
    confidence = Column(Float, default=1.0)
    usage_count = Column(Integer, default=0)
    last_confirmed_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


class ManualQuestionORM(Base):
    __tablename__ = "manual_questions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    application_run_id = Column(String(36), ForeignKey("application_runs.id"), nullable=True, index=True)
    question_text = Column(Text, nullable=False)
    context = Column(JSON, default=dict)
    status = Column(String(50), default="PENDING", index=True) # PENDING, ANSWERED, DISMISSED
    answer = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    answered_at = Column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Role discovery
# ---------------------------------------------------------------------------


class CapabilityGraphORM(Base):
    """A versioned snapshot of the CandidateCapabilityGraph."""

    __tablename__ = "capability_graphs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    version = Column(Integer, nullable=False, default=1, index=True)
    generated_by = Column(String(50), default="heuristic")
    summary = Column(Text, default="")
    seniority = Column(JSON, default=dict)
    nodes = Column(JSON, default=list)
    clusters = Column(JSON, default=list)
    constraints = Column(JSON, default=dict)
    notes = Column(Text, default="")
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class RoleMapORM(Base):
    """A versioned RoleMap. Only one row is active at a time."""

    __tablename__ = "role_maps"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    version = Column(Integer, nullable=False, default=1, index=True)
    generated_by = Column(String(50), default="heuristic")
    capability_graph_id = Column(String(36), ForeignKey("capability_graphs.id"), nullable=True)
    role_families = Column(JSON, default=list)
    industries = Column(JSON, default=list)
    company_types = Column(JSON, default=list)
    capability_gaps = Column(JSON, default=list)
    notes = Column(Text, default="")
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    roles = relationship(
        "DiscoveredRoleORM", back_populates="role_map", cascade="all, delete-orphan"
    )


class DiscoveredRoleORM(Base):
    __tablename__ = "discovered_roles"
    __table_args__ = (
        UniqueConstraint("role_map_id", "role_key", name="uq_role_per_map"),
        Index("ix_discovered_roles_category_fit", "category", "fit_score"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    role_map_id = Column(String(36), ForeignKey("role_maps.id"), nullable=False, index=True)
    role_key = Column(String(255), nullable=False, index=True)  # stable slug, e.g. role_xr_engineer
    title = Column(String(255), nullable=False)
    fit_score = Column(Integer, default=0, index=True)
    confidence = Column(Float, default=0.5)
    category = Column(String(20), default="secondary", index=True)
    role_family = Column(String(255), default="")
    reasoning_summary = Column(Text, default="")
    strengths = Column(JSON, default=list)
    gaps = Column(JSON, default=list)
    equivalent_titles = Column(JSON, default=list)
    search_aliases = Column(JSON, default=list)
    seed_queries = Column(JSON, default=list)
    industries = Column(JSON, default=list)
    company_types = Column(JSON, default=list)
    capability_ids = Column(JSON, default=list)
    proposal_status = Column(String(20), default="accepted", index=True)
    discovered_from_job_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    role_map = relationship("RoleMapORM", back_populates="roles")


class SearchQueryORM(Base):
    """A first-class search query the agent can create, retune or retire."""

    __tablename__ = "search_queries"
    __table_args__ = (
        UniqueConstraint("query", "provider", "location", name="uq_query_provider_location"),
        Index("ix_search_queries_status_priority", "status", "priority"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    role_key = Column(String(255), nullable=False, index=True)
    role_title = Column(String(255), default="")
    group_label = Column(String(255), default="")
    label = Column(String(255), nullable=False)
    query = Column(Text, nullable=False)
    provider = Column(String(50), nullable=False, index=True)
    location = Column(String(255), nullable=True)
    remote = Column(Boolean, nullable=True)
    priority = Column(Integer, default=50, index=True)
    status = Column(String(20), default="active", index=True)
    is_exploratory = Column(Boolean, default=False, index=True)
    created_by = Column(String(100), default="role-discovery-agent")
    resolved_url = Column(Text, nullable=True)

    # Performance record. Quality matters more than volume, so both are tracked.
    searches_opened = Column(Integer, default=0)
    jobs_imported = Column(Integer, default=0)
    scored_imports = Column(Integer, default=0)
    high_match_jobs_imported = Column(Integer, default=0)
    applications_generated = Column(Integer, default=0)
    interviews_produced = Column(Integer, default=0)
    total_match_score = Column(Integer, default=0)
    last_used_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ExtensionTokenORM(Base):
    """A paired browser extension. Only the hash of the token is stored."""

    __tablename__ = "extension_tokens"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), default="Browser extension")
    token_prefix = Column(String(16), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    revoked = Column(Boolean, default=False, index=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
