"""Repositories for the capability graph, role map, search queries and pairing tokens."""

import hashlib
import secrets
from datetime import datetime
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.enums import (
    RoleCategory,
    RoleProposalStatus,
    SearchProviderId,
    SearchQueryStatus,
)
from packages.domain.role_discovery import (
    CandidateCapabilityGraph,
    CapabilityCluster,
    CapabilityGap,
    CapabilityNode,
    DiscoveredRole,
    JobSearchQuerySpec,
    RoleFamily,
    RoleMap,
    SearchQueryStats,
    SeniorityAssessment,
)
from packages.persistence.models import (
    CapabilityGraphORM,
    DiscoveredRoleORM,
    ExtensionTokenORM,
    RoleMapORM,
    SearchQueryORM,
)

# Statuses a regenerated strategy must not silently overwrite: the agent or the
# user already decided these queries are not worth running.
_STICKY_STATUSES = {SearchQueryStatus.DISABLED, SearchQueryStatus.PAUSED}


class CapabilityGraphRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_active(self) -> Optional[Tuple[str, CandidateCapabilityGraph]]:
        result = await self.session.execute(
            select(CapabilityGraphORM)
            .where(CapabilityGraphORM.is_active.is_(True))
            .order_by(desc(CapabilityGraphORM.created_at))
            .limit(1)
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return orm.id, _graph_from_orm(orm)

    async def next_version(self) -> int:
        latest = await self.session.scalar(
            select(CapabilityGraphORM.version).order_by(desc(CapabilityGraphORM.version)).limit(1)
        )
        return int(latest or 0) + 1

    async def save(self, graph: CandidateCapabilityGraph) -> CapabilityGraphORM:
        await self.session.execute(
            update(CapabilityGraphORM)
            .where(CapabilityGraphORM.is_active.is_(True))
            .values(is_active=False)
        )
        orm = CapabilityGraphORM(
            version=graph.version,
            generated_by=graph.generated_by,
            summary=graph.summary,
            seniority=graph.seniority.model_dump(),
            nodes=[node.model_dump(mode="json") for node in graph.nodes],
            clusters=[cluster.model_dump(mode="json") for cluster in graph.clusters],
            constraints=graph.constraints,
            notes=graph.notes,
            is_active=True,
        )
        self.session.add(orm)
        await self.session.flush()
        return orm


class RoleMapRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_active_orm(self) -> Optional[RoleMapORM]:
        result = await self.session.execute(
            select(RoleMapORM)
            .where(RoleMapORM.is_active.is_(True))
            .order_by(desc(RoleMapORM.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_active(self) -> Optional[RoleMap]:
        orm = await self.get_active_orm()
        if orm is None:
            return None
        roles = await self.list_roles(orm.id)
        return _role_map_from_orm(orm, roles)

    async def list_roles(self, role_map_id: str) -> List[DiscoveredRoleORM]:
        result = await self.session.execute(
            select(DiscoveredRoleORM)
            .where(DiscoveredRoleORM.role_map_id == role_map_id)
            .order_by(desc(DiscoveredRoleORM.fit_score))
        )
        return list(result.scalars().all())

    async def next_version(self) -> int:
        latest = await self.session.scalar(
            select(RoleMapORM.version).order_by(desc(RoleMapORM.version)).limit(1)
        )
        return int(latest or 0) + 1

    async def save(
        self,
        role_map: RoleMap,
        capability_graph_id: Optional[str] = None,
    ) -> RoleMapORM:
        """Stores a new active role map version, retiring the previous one."""
        await self.session.execute(
            update(RoleMapORM).where(RoleMapORM.is_active.is_(True)).values(is_active=False)
        )
        orm = RoleMapORM(
            version=role_map.version,
            generated_by=role_map.generated_by,
            capability_graph_id=capability_graph_id,
            role_families=[family.model_dump(mode="json") for family in role_map.role_families],
            industries=role_map.industries,
            company_types=role_map.company_types,
            capability_gaps=[gap.model_dump(mode="json") for gap in role_map.capability_gaps],
            notes=role_map.notes,
            is_active=True,
        )
        self.session.add(orm)
        await self.session.flush()

        for role in role_map.roles:
            self.session.add(_role_to_orm(role, orm.id))
        await self.session.flush()
        return orm

    async def add_role(self, role: DiscoveredRole) -> Optional[DiscoveredRoleORM]:
        """Adds a single role (typically a proposal) to the active map."""
        active = await self.get_active_orm()
        if active is None:
            return None
        existing = await self.session.execute(
            select(DiscoveredRoleORM).where(
                DiscoveredRoleORM.role_map_id == active.id,
                DiscoveredRoleORM.role_key == role.id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            return None
        orm = _role_to_orm(role, active.id)
        self.session.add(orm)
        await self.session.flush()
        return orm

    async def get_role(self, role_key: str) -> Optional[DiscoveredRoleORM]:
        active = await self.get_active_orm()
        if active is None:
            return None
        result = await self.session.execute(
            select(DiscoveredRoleORM).where(
                DiscoveredRoleORM.role_map_id == active.id,
                DiscoveredRoleORM.role_key == role_key,
            )
        )
        return result.scalar_one_or_none()

    async def update_role(
        self,
        role_key: str,
        category: Optional[RoleCategory] = None,
        proposal_status: Optional[RoleProposalStatus] = None,
    ) -> Optional[DiscoveredRoleORM]:
        orm = await self.get_role(role_key)
        if orm is None:
            return None
        if category is not None:
            orm.category = category.value
        if proposal_status is not None:
            orm.proposal_status = proposal_status.value
        orm.updated_at = datetime.utcnow()
        await self.session.flush()
        return orm


class SearchQueryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, query_id: str) -> Optional[SearchQueryORM]:
        result = await self.session.execute(
            select(SearchQueryORM).where(SearchQueryORM.id == query_id)
        )
        return result.scalar_one_or_none()

    async def list_all(
        self,
        statuses: Optional[Sequence[SearchQueryStatus]] = None,
        role_key: Optional[str] = None,
    ) -> List[SearchQueryORM]:
        stmt = select(SearchQueryORM).order_by(desc(SearchQueryORM.priority))
        if statuses:
            stmt = stmt.where(SearchQueryORM.status.in_([s.value for s in statuses]))
        if role_key:
            stmt = stmt.where(SearchQueryORM.role_key == role_key)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_specs(
        self,
        statuses: Optional[Sequence[SearchQueryStatus]] = None,
        role_key: Optional[str] = None,
    ) -> List[JobSearchQuerySpec]:
        return [_query_from_orm(orm) for orm in await self.list_all(statuses, role_key)]

    async def sync(self, specs: Sequence[JobSearchQuerySpec]) -> Tuple[int, int, int]:
        """Reconciles generated queries with what is stored.

        Returns (created, updated, archived). Performance history is never lost,
        and queries the agent previously disabled are not silently revived.
        """
        existing = {
            (_key(orm.query, orm.provider, orm.location)): orm for orm in await self.list_all()
        }
        seen: set = set()
        created = updated = 0

        for spec in specs:
            key = _key(spec.query, spec.provider.value, spec.location)
            seen.add(key)
            orm = existing.get(key)
            if orm is None:
                self.session.add(_query_to_orm(spec))
                created += 1
                continue

            orm.role_key = spec.role_id
            orm.role_title = spec.role_title
            orm.group_label = spec.group_label
            orm.label = spec.label
            orm.is_exploratory = spec.is_exploratory
            orm.resolved_url = spec.resolved_url
            if SearchQueryStatus(orm.status) not in _STICKY_STATUSES:
                orm.priority = spec.priority
                orm.status = SearchQueryStatus.ACTIVE.value
            orm.updated_at = datetime.utcnow()
            updated += 1

        archived = 0
        for key, orm in existing.items():
            if key in seen or orm.status == SearchQueryStatus.ARCHIVED.value:
                continue
            # A query that has proven itself stays, even out of the current slate.
            if orm.jobs_imported > 0 or orm.created_by != "role-discovery-agent":
                continue
            orm.status = SearchQueryStatus.ARCHIVED.value
            orm.updated_at = datetime.utcnow()
            archived += 1

        await self.session.flush()
        return created, updated, archived

    async def create(self, spec: JobSearchQuerySpec) -> SearchQueryORM:
        orm = _query_to_orm(spec)
        self.session.add(orm)
        await self.session.flush()
        return orm

    async def update_query(
        self,
        query_id: str,
        priority: Optional[int] = None,
        status: Optional[SearchQueryStatus] = None,
        label: Optional[str] = None,
        resolved_url: Optional[str] = None,
    ) -> Optional[SearchQueryORM]:
        orm = await self.get_by_id(query_id)
        if orm is None:
            return None
        if priority is not None:
            orm.priority = max(1, min(99, priority))
        if status is not None:
            orm.status = status.value
        if label is not None:
            orm.label = label
        if resolved_url is not None:
            orm.resolved_url = resolved_url
        orm.updated_at = datetime.utcnow()
        await self.session.flush()
        return orm

    async def record_opened(self, query_id: str) -> Optional[SearchQueryORM]:
        orm = await self.get_by_id(query_id)
        if orm is None:
            return None
        orm.searches_opened = (orm.searches_opened or 0) + 1
        orm.last_used_at = datetime.utcnow()
        await self.session.flush()
        return orm

    async def record_import(self, query_id: str) -> Optional[SearchQueryORM]:
        orm = await self.get_by_id(query_id)
        if orm is None:
            return None
        orm.jobs_imported = (orm.jobs_imported or 0) + 1
        orm.last_used_at = datetime.utcnow()
        await self.session.flush()
        return orm

    async def record_match_score(
        self,
        query_id: str,
        match_score: int,
        high_match_threshold: int,
    ) -> Optional[SearchQueryORM]:
        orm = await self.get_by_id(query_id)
        if orm is None:
            return None
        orm.scored_imports = (orm.scored_imports or 0) + 1
        orm.total_match_score = (orm.total_match_score or 0) + int(match_score)
        if match_score >= high_match_threshold:
            orm.high_match_jobs_imported = (orm.high_match_jobs_imported or 0) + 1
        await self.session.flush()
        return orm

    async def record_application(self, query_id: str) -> Optional[SearchQueryORM]:
        orm = await self.get_by_id(query_id)
        if orm is None:
            return None
        orm.applications_generated = (orm.applications_generated or 0) + 1
        await self.session.flush()
        return orm

    async def record_interview(self, query_id: str) -> Optional[SearchQueryORM]:
        orm = await self.get_by_id(query_id)
        if orm is None:
            return None
        orm.interviews_produced = (orm.interviews_produced or 0) + 1
        await self.session.flush()
        return orm


class ExtensionTokenRepository:
    """Pairing tokens for the browser extension.

    Only a SHA-256 hash is persisted, so a database dump never yields a usable
    credential. The plaintext token is returned once, at pairing time.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def create(self, name: str = "Browser extension") -> Tuple[str, ExtensionTokenORM]:
        token = f"ja_{secrets.token_urlsafe(32)}"
        orm = ExtensionTokenORM(
            name=name,
            token_prefix=token[:12],
            token_hash=self.hash_token(token),
        )
        self.session.add(orm)
        await self.session.flush()
        return token, orm

    async def verify(self, token: str) -> Optional[ExtensionTokenORM]:
        result = await self.session.execute(
            select(ExtensionTokenORM).where(
                ExtensionTokenORM.token_hash == self.hash_token(token),
                ExtensionTokenORM.revoked.is_(False),
            )
        )
        orm = result.scalar_one_or_none()
        if orm is not None:
            orm.last_used_at = datetime.utcnow()
        return orm

    async def list_tokens(self) -> List[ExtensionTokenORM]:
        result = await self.session.execute(
            select(ExtensionTokenORM).order_by(desc(ExtensionTokenORM.created_at))
        )
        return list(result.scalars().all())

    async def revoke(self, token_id: str) -> bool:
        result = await self.session.execute(
            select(ExtensionTokenORM).where(ExtensionTokenORM.id == token_id)
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            return False
        orm.revoked = True
        await self.session.flush()
        return True


# ---------------------------------------------------------------------------
# ORM <-> domain mapping
# ---------------------------------------------------------------------------


def _key(query: str, provider: str, location: Optional[str]) -> str:
    return f"{query.strip().lower()}|{provider}|{(location or '').strip().lower()}"


def _graph_from_orm(orm: CapabilityGraphORM) -> CandidateCapabilityGraph:
    nodes: List[CapabilityNode] = []
    for raw in orm.nodes or []:
        try:
            nodes.append(CapabilityNode.model_validate(raw))
        except Exception:
            continue
    clusters: List[CapabilityCluster] = []
    for raw in orm.clusters or []:
        try:
            clusters.append(CapabilityCluster.model_validate(raw))
        except Exception:
            continue
    try:
        seniority = SeniorityAssessment.model_validate(orm.seniority or {})
    except Exception:
        seniority = SeniorityAssessment()

    return CandidateCapabilityGraph(
        version=orm.version,
        generated_at=orm.created_at or datetime.utcnow(),
        generated_by=orm.generated_by or "heuristic",
        summary=orm.summary or "",
        seniority=seniority,
        nodes=nodes,
        clusters=clusters,
        constraints=orm.constraints or {},
        notes=orm.notes or "",
    )


def _role_to_orm(role: DiscoveredRole, role_map_id: str) -> DiscoveredRoleORM:
    return DiscoveredRoleORM(
        role_map_id=role_map_id,
        role_key=role.id,
        title=role.title,
        fit_score=role.fit_score,
        confidence=role.confidence,
        category=role.category.value,
        role_family=role.role_family,
        reasoning_summary=role.reasoning_summary,
        strengths=role.strengths,
        gaps=role.gaps,
        equivalent_titles=role.equivalent_titles,
        search_aliases=role.search_aliases,
        seed_queries=role.search_queries,
        industries=role.industries,
        company_types=role.company_types,
        capability_ids=role.capability_ids,
        proposal_status=role.proposal_status.value,
        discovered_from_job_id=role.discovered_from_job_id,
    )


def role_from_orm(orm: DiscoveredRoleORM) -> DiscoveredRole:
    try:
        category = RoleCategory(orm.category)
    except ValueError:
        category = RoleCategory.SECONDARY
    try:
        proposal_status = RoleProposalStatus(orm.proposal_status)
    except ValueError:
        proposal_status = RoleProposalStatus.ACCEPTED

    return DiscoveredRole(
        id=orm.role_key,
        title=orm.title,
        fit_score=orm.fit_score or 0,
        confidence=orm.confidence or 0.5,
        category=category,
        role_family=orm.role_family or "",
        reasoning_summary=orm.reasoning_summary or "",
        strengths=orm.strengths or [],
        gaps=orm.gaps or [],
        equivalent_titles=orm.equivalent_titles or [],
        search_aliases=orm.search_aliases or [],
        search_queries=orm.seed_queries or [],
        industries=orm.industries or [],
        company_types=orm.company_types or [],
        capability_ids=orm.capability_ids or [],
        proposal_status=proposal_status,
        discovered_from_job_id=orm.discovered_from_job_id,
        created_at=orm.created_at or datetime.utcnow(),
        updated_at=orm.updated_at or datetime.utcnow(),
    )


def _role_map_from_orm(orm: RoleMapORM, roles: Sequence[DiscoveredRoleORM]) -> RoleMap:
    families: List[RoleFamily] = []
    for raw in orm.role_families or []:
        try:
            families.append(RoleFamily.model_validate(raw))
        except Exception:
            continue
    gaps: List[CapabilityGap] = []
    for raw in orm.capability_gaps or []:
        try:
            gaps.append(CapabilityGap.model_validate(raw))
        except Exception:
            continue

    return RoleMap(
        version=orm.version,
        generated_at=orm.created_at or datetime.utcnow(),
        generated_by=orm.generated_by or "heuristic",
        roles=[role_from_orm(role) for role in roles],
        role_families=families,
        industries=orm.industries or [],
        company_types=orm.company_types or [],
        capability_gaps=gaps,
        notes=orm.notes or "",
    )


def _query_to_orm(spec: JobSearchQuerySpec) -> SearchQueryORM:
    return SearchQueryORM(
        role_key=spec.role_id,
        role_title=spec.role_title,
        group_label=spec.group_label,
        label=spec.label,
        query=spec.query,
        provider=spec.provider.value,
        location=spec.location,
        remote=spec.remote,
        priority=spec.priority,
        status=spec.status.value,
        is_exploratory=spec.is_exploratory,
        created_by=spec.created_by,
        resolved_url=spec.resolved_url,
    )


def _query_from_orm(orm: SearchQueryORM) -> JobSearchQuerySpec:
    try:
        provider = SearchProviderId(orm.provider)
    except ValueError:
        provider = SearchProviderId.GENERIC_WEB
    try:
        status = SearchQueryStatus(orm.status)
    except ValueError:
        status = SearchQueryStatus.ACTIVE

    return JobSearchQuerySpec(
        id=orm.id,
        role_id=orm.role_key,
        role_title=orm.role_title or "",
        group_label=orm.group_label or "",
        label=orm.label,
        query=orm.query,
        provider=provider,
        location=orm.location,
        remote=orm.remote,
        priority=orm.priority or 50,
        status=status,
        is_exploratory=bool(orm.is_exploratory),
        created_by=orm.created_by or "role-discovery-agent",
        resolved_url=orm.resolved_url,
        stats=SearchQueryStats(
            searches_opened=orm.searches_opened or 0,
            jobs_imported=orm.jobs_imported or 0,
            scored_imports=orm.scored_imports or 0,
            high_match_jobs_imported=orm.high_match_jobs_imported or 0,
            applications_generated=orm.applications_generated or 0,
            interviews_produced=orm.interviews_produced or 0,
            total_match_score=orm.total_match_score or 0,
            last_used_at=orm.last_used_at,
        ),
        created_at=orm.created_at or datetime.utcnow(),
        updated_at=orm.updated_at or datetime.utcnow(),
    )


query_from_orm = _query_from_orm
