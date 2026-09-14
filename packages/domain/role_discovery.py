"""Domain models for role discovery, search strategy and browser imports.

These models are the vocabulary shared by the RoleDiscoveryAgent, the search
strategy generator, the REST API and the browser extension.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from packages.domain.enums import (
    CapabilityKind,
    DiscoveryChannel,
    RoleCategory,
    RoleProposalStatus,
    SearchProviderId,
    SearchQueryStatus,
)


def slugify(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_")


# ---------------------------------------------------------------------------
# Candidate Capability Graph
# ---------------------------------------------------------------------------


class CapabilityNode(BaseModel):
    """One facet of what the candidate can actually do, with its evidence."""

    id: str
    label: str
    kind: CapabilityKind
    strength: float = Field(default=0.5, ge=0.0, le=1.0)
    years: Optional[float] = None
    last_used_year: Optional[int] = None
    evidence: List[str] = Field(default_factory=list)
    related: List[str] = Field(default_factory=list)

    @classmethod
    def build(cls, label: str, kind: CapabilityKind, **kwargs: Any) -> "CapabilityNode":
        return cls(id=f"{kind.value}:{slugify(label)}", label=label, kind=kind, **kwargs)


class CapabilityCluster(BaseModel):
    """A combination of capabilities that together imply roles no single node does.

    This is what stops role inference collapsing into keyword matching: a cluster
    of Unity plus XR plus computer vision plus hardware integration points somewhere
    very different from any of its members read alone.
    """

    id: str
    label: str
    node_ids: List[str] = Field(default_factory=list)
    strength: float = Field(default=0.5, ge=0.0, le=1.0)
    rationale: str = ""


class SeniorityAssessment(BaseModel):
    level: str = "mid"  # junior | mid | senior | staff | lead | principal | executive
    years_experience: Optional[float] = None
    leads_people: bool = False
    owns_product: bool = False
    rationale: str = ""


class CandidateCapabilityGraph(BaseModel):
    """Semantic representation of the candidate, built from profile plus master CV."""

    version: int = 1
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    generated_by: str = "heuristic"  # llm | heuristic
    summary: str = ""
    seniority: SeniorityAssessment = Field(default_factory=SeniorityAssessment)
    nodes: List[CapabilityNode] = Field(default_factory=list)
    clusters: List[CapabilityCluster] = Field(default_factory=list)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    notes: str = ""

    def by_kind(self, kind: CapabilityKind) -> List[CapabilityNode]:
        return [node for node in self.nodes if node.kind == kind]

    def labels(self, kind: Optional[CapabilityKind] = None) -> List[str]:
        nodes = self.nodes if kind is None else self.by_kind(kind)
        return [node.label for node in nodes]

    def node(self, node_id: str) -> Optional[CapabilityNode]:
        return next((n for n in self.nodes if n.id == node_id), None)


# ---------------------------------------------------------------------------
# Role Map
# ---------------------------------------------------------------------------


class DiscoveredRole(BaseModel):
    """A professional role the candidate should consider, with its reasoning."""

    id: str
    title: str
    fit_score: int = Field(default=0, ge=0, le=100)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    category: RoleCategory = RoleCategory.SECONDARY
    role_family: str = ""
    reasoning_summary: str = ""
    strengths: List[str] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list)
    equivalent_titles: List[str] = Field(default_factory=list)
    search_aliases: List[str] = Field(default_factory=list)
    search_queries: List[str] = Field(default_factory=list)
    industries: List[str] = Field(default_factory=list)
    company_types: List[str] = Field(default_factory=list)
    capability_ids: List[str] = Field(default_factory=list)
    proposal_status: RoleProposalStatus = RoleProposalStatus.ACCEPTED
    discovered_from_job_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @classmethod
    def make_id(cls, title: str) -> str:
        return f"role_{slugify(title)}"

    def to_api_dict(self) -> Dict[str, Any]:
        """The camelCase shape the extension and dashboard consume."""
        return {
            "id": self.id,
            "title": self.title,
            "fitScore": self.fit_score,
            "confidence": self.confidence,
            "category": self.category.value,
            "roleFamily": self.role_family,
            "reasoningSummary": self.reasoning_summary,
            "strengths": self.strengths,
            "gaps": self.gaps,
            "equivalentTitles": self.equivalent_titles,
            "searchAliases": self.search_aliases,
            "searchQueries": self.search_queries,
            "industries": self.industries,
            "companyTypes": self.company_types,
            "proposalStatus": self.proposal_status.value,
            "discoveredFromJobId": self.discovered_from_job_id,
        }


class RoleFamily(BaseModel):
    id: str
    label: str
    description: str = ""
    role_ids: List[str] = Field(default_factory=list)


class CapabilityGap(BaseModel):
    capability: str
    severity: str = "medium"  # low | medium | high
    why_it_matters: str = ""
    blocks_roles: List[str] = Field(default_factory=list)


class RoleMap(BaseModel):
    version: int = 1
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    generated_by: str = "heuristic"  # llm | heuristic
    roles: List[DiscoveredRole] = Field(default_factory=list)
    role_families: List[RoleFamily] = Field(default_factory=list)
    industries: List[str] = Field(default_factory=list)
    company_types: List[str] = Field(default_factory=list)
    capability_gaps: List[CapabilityGap] = Field(default_factory=list)
    notes: str = ""

    def in_category(self, category: RoleCategory) -> List["DiscoveredRole"]:
        return sorted(
            (r for r in self.roles if r.category == category),
            key=lambda r: r.fit_score,
            reverse=True,
        )

    @property
    def primary(self) -> List["DiscoveredRole"]:
        return self.in_category(RoleCategory.PRIMARY)

    @property
    def secondary(self) -> List["DiscoveredRole"]:
        return self.in_category(RoleCategory.SECONDARY)

    @property
    def stretch(self) -> List["DiscoveredRole"]:
        return self.in_category(RoleCategory.STRETCH)

    @property
    def avoid(self) -> List["DiscoveredRole"]:
        return self.in_category(RoleCategory.AVOID)

    @property
    def searchable(self) -> List["DiscoveredRole"]:
        """Roles worth generating searches for: everything except roles to avoid."""
        return [
            r
            for r in self.roles
            if r.category != RoleCategory.AVOID and r.proposal_status != RoleProposalStatus.REJECTED
        ]

    def role(self, role_id: str) -> Optional["DiscoveredRole"]:
        return next((r for r in self.roles if r.id == role_id), None)


# ---------------------------------------------------------------------------
# Search queries
# ---------------------------------------------------------------------------


class SearchQueryStats(BaseModel):
    """Outcome counters used to judge whether a query earns its place."""

    searches_opened: int = 0
    jobs_imported: int = 0
    scored_imports: int = 0
    high_match_jobs_imported: int = 0
    applications_generated: int = 0
    interviews_produced: int = 0
    total_match_score: int = 0
    last_used_at: Optional[datetime] = None

    @property
    def average_match_score(self) -> float:
        # Averaged over imports that were actually scored, so a failed analysis
        # never drags a good query's average down.
        if not self.scored_imports:
            return 0.0
        return round(self.total_match_score / self.scored_imports, 1)

    @property
    def high_match_ratio(self) -> float:
        if not self.scored_imports:
            return 0.0
        return round(self.high_match_jobs_imported / self.scored_imports, 3)


class JobSearchQuerySpec(BaseModel):
    """A first-class, mutable search query owned by the RoleDiscoveryAgent."""

    model_config = ConfigDict(populate_by_name=True)

    id: Optional[str] = None
    role_id: str
    role_title: str = ""
    group_label: str = ""
    label: str
    query: str
    provider: SearchProviderId = SearchProviderId.LINKEDIN
    location: Optional[str] = None
    remote: Optional[bool] = None
    priority: int = Field(default=50, ge=0, le=100)
    status: SearchQueryStatus = SearchQueryStatus.ACTIVE
    is_exploratory: bool = False
    created_by: str = "role-discovery-agent"
    resolved_url: Optional[str] = None
    stats: SearchQueryStats = Field(default_factory=SearchQueryStats)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def to_api_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "roleId": self.role_id,
            "roleTitle": self.role_title,
            "groupLabel": self.group_label,
            "label": self.label,
            "query": self.query,
            "provider": self.provider.value,
            "location": self.location,
            "remote": self.remote,
            "priority": self.priority,
            "status": self.status.value,
            "isExploratory": self.is_exploratory,
            "createdBy": self.created_by,
            "url": self.resolved_url,
            "stats": {
                "searchesOpened": self.stats.searches_opened,
                "jobsImported": self.stats.jobs_imported,
                "scoredImports": self.stats.scored_imports,
                "highMatchJobsImported": self.stats.high_match_jobs_imported,
                "applicationsGenerated": self.stats.applications_generated,
                "interviewsProduced": self.stats.interviews_produced,
                "averageMatchScore": self.stats.average_match_score,
                "highMatchRatio": self.stats.high_match_ratio,
            },
        }


class SearchStrategy(BaseModel):
    """The full set of queries generated from a role map, budget already applied."""

    generated_at: datetime = Field(default_factory=datetime.utcnow)
    generated_by: str = "role-discovery-agent"
    queries: List[JobSearchQuerySpec] = Field(default_factory=list)
    notes: str = ""


class ExplorationBudget(BaseModel):
    """How the search slate is split between exploiting and exploring."""

    primary_share: float = 0.7
    secondary_share: float = 0.2
    exploratory_share: float = 0.1
    total_queries: int = 24

    def slots(self) -> Dict[RoleCategory, int]:
        primary = max(1, round(self.total_queries * self.primary_share))
        secondary = max(1, round(self.total_queries * self.secondary_share))
        stretch = max(1, self.total_queries - primary - secondary)
        return {
            RoleCategory.PRIMARY: primary,
            RoleCategory.SECONDARY: secondary,
            RoleCategory.STRETCH: stretch,
        }


# ---------------------------------------------------------------------------
# Browser import
# ---------------------------------------------------------------------------


class BrowserJobCapture(BaseModel):
    """What the extension sends when the user clicks Import Job."""

    model_config = ConfigDict(populate_by_name=True)

    url: str
    title: str = ""
    hostname: str = ""
    visible_text: str = Field(default="", alias="visibleText")
    structured_data: Optional[Any] = Field(default=None, alias="structuredData")
    cleaned_html: str = Field(default="", alias="cleanedHtml")
    captured_at: Optional[datetime] = Field(default=None, alias="capturedAt")
    extracted: Dict[str, Any] = Field(default_factory=dict)
    canonical_url_hint: Optional[str] = Field(default=None, alias="canonicalUrlHint")
    search_query_id: Optional[str] = Field(default=None, alias="searchQueryId")
    search_provider: Optional[str] = Field(default=None, alias="searchProvider")
    discovered_by: DiscoveryChannel = Field(
        default=DiscoveryChannel.BROWSER_EXTENSION, alias="discoveredBy"
    )
    prepare_application: bool = Field(default=False, alias="prepareApplication")
    extraction_strategy: str = Field(default="", alias="extractionStrategy")


class JobProvenance(BaseModel):
    """Where a job came from, so search performance can be attributed."""

    source: str
    discovered_by: DiscoveryChannel = DiscoveryChannel.DISCOVERY_CYCLE
    search_query_id: Optional[str] = None
    search_provider: Optional[str] = None
    source_url: Optional[str] = None
    canonical_url: Optional[str] = None


class JobImportResult(BaseModel):
    """Immediate answer to an import, before the heavy analysis has finished."""

    status: str  # imported | duplicate | rejected
    job_id: Optional[str] = None
    company: str = ""
    role: str = ""
    location: Optional[str] = None
    canonical_url: Optional[str] = None
    apply_url: Optional[str] = None
    match_score: Optional[int] = None
    recommendation: Optional[str] = None
    primary_role: Optional[str] = None
    strengths: List[str] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list)
    application_run_id: Optional[str] = None
    job_status: Optional[str] = None
    analysis_state: str = "pending"  # pending | complete | failed | skipped
    prepare_requested: bool = False
    #: none | ready | skipped | failed. Says why a CV is or is not there.
    preparation_state: str = "none"
    preparation_error: str = ""
    message: str = ""
    dashboard_url: Optional[str] = None

    def to_api_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "jobId": self.job_id,
            "company": self.company,
            "role": self.role,
            "location": self.location,
            "canonicalUrl": self.canonical_url,
            "applyUrl": self.apply_url,
            "matchScore": self.match_score,
            "recommendation": self.recommendation,
            "primaryRole": self.primary_role,
            "strengths": self.strengths,
            "gaps": self.gaps,
            "applicationRunId": self.application_run_id,
            "jobStatus": self.job_status,
            "analysisState": self.analysis_state,
            "prepareRequested": self.prepare_requested,
            "preparationState": self.preparation_state,
            "preparationError": self.preparation_error,
            "message": self.message,
            "dashboardUrl": self.dashboard_url,
        }
