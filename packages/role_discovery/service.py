"""Orchestrates role discovery: profile in, clickable searches out.

This is the seam between the agents and the database. Everything the API and the
worker need goes through here, so the learning loop has exactly one implementation.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from packages.candidate_profile.profile import CandidateProfileLoader
from packages.domain.enums import (
    DiscoveryChannel,
    RoleCategory,
    RoleProposalStatus,
    SearchQueryStatus,
)
from packages.domain.models import CandidateProfileModel
from packages.domain.role_discovery import (
    CandidateCapabilityGraph,
    DiscoveredRole,
    JobSearchQuerySpec,
    RoleMap,
    SearchStrategy,
)
from packages.llm.gateway import LLMGateway
from packages.persistence.models import JobORM
from packages.persistence.repositories import EventRepository, JobRepository
from packages.persistence.role_repositories import (
    CapabilityGraphRepository,
    RoleMapRepository,
    SearchQueryRepository,
)
from packages.reactive_resume.client import ReactiveResumeClient
from packages.role_discovery.agent import RoleDiscoveryAgent
from packages.role_discovery.capability_graph import CapabilityGraphBuilder
from packages.role_discovery.feedback import (
    MarketFeedbackReport,
    build_job_signal,
    evaluate_query_performance,
    select_auto_accepted,
    summarise_market_feedback,
)
from packages.role_discovery.resume_digest import build_resume_digest
from packages.role_discovery.search_strategy import SearchStrategyGenerator
from packages.search_providers.registry import resolve_search_url


class RoleDiscoveryService:
    def __init__(
        self,
        session: AsyncSession,
        profile: Optional[CandidateProfileModel] = None,
        rr_client: Optional[ReactiveResumeClient] = None,
        llm_gateway: Optional[LLMGateway] = None,
    ):
        self.session = session
        self.profile = profile or CandidateProfileLoader.get()
        self.rr_client = rr_client
        gateway = llm_gateway or LLMGateway.get()

        self.graph_builder = CapabilityGraphBuilder(gateway)
        self.agent = RoleDiscoveryAgent(gateway)
        self.strategy = SearchStrategyGenerator(gateway)

        self.graph_repo = CapabilityGraphRepository(session)
        self.role_repo = RoleMapRepository(session)
        self.query_repo = SearchQueryRepository(session)
        self.job_repo = JobRepository(session)
        self.event_repo = EventRepository(session)

    # -- reads -------------------------------------------------------------

    async def get_capability_graph(self) -> Optional[CandidateCapabilityGraph]:
        active = await self.graph_repo.get_active()
        return active[1] if active else None

    async def get_role_map(self) -> Optional[RoleMap]:
        return await self.role_repo.get_active()

    async def list_search_queries(
        self,
        include_inactive: bool = False,
        role_key: Optional[str] = None,
    ) -> List[JobSearchQuerySpec]:
        statuses = (
            None if include_inactive else [SearchQueryStatus.ACTIVE, SearchQueryStatus.PAUSED]
        )
        specs = await self.query_repo.list_specs(statuses=statuses, role_key=role_key)
        for spec in specs:
            if not spec.resolved_url:
                spec.resolved_url = resolve_search_url(spec)
        specs.sort(key=lambda s: s.priority, reverse=True)
        return specs

    # -- full refresh ------------------------------------------------------

    async def refresh(self, use_llm: Optional[bool] = None) -> Dict[str, Any]:
        """Rebuilds the capability graph, the role map and the search slate."""
        config = self.profile.role_discovery
        allow_llm = config.use_llm if use_llm is None else use_llm

        resume_digest = await self._load_resume_digest()

        graph = await self.graph_builder.build(
            self.profile,
            resume_digest=resume_digest,
            use_llm=allow_llm,
            version=await self.graph_repo.next_version(),
        )
        graph_orm = await self.graph_repo.save(graph)

        previous_map = await self.role_repo.get_active()
        market_feedback = await self._market_feedback_text()

        role_map = await self.agent.discover(
            self.profile,
            graph,
            market_feedback=market_feedback,
            use_llm=allow_llm,
            version=await self.role_repo.next_version(),
        )
        if previous_map is not None:
            _carry_over_decisions(previous_map, role_map)

        await self.role_repo.save(role_map, capability_graph_id=graph_orm.id)

        strategy = await self.strategy.generate(
            self.profile,
            role_map,
            seniority_level=graph.seniority.level,
            use_llm=allow_llm,
        )
        created, updated, archived = await self.query_repo.sync(strategy.queries)

        await self.event_repo.log(
            event_type="ROLE_MAP_REFRESHED",
            message=(
                f"Role map v{role_map.version} ({role_map.generated_by}): "
                f"{len(role_map.primary)} primary, {len(role_map.secondary)} secondary, "
                f"{len(role_map.stretch)} exploratory roles; "
                f"{created} new searches, {updated} updated, {archived} archived"
            ),
            details={
                "capability_nodes": len(graph.nodes),
                "capability_clusters": len(graph.clusters),
                "generated_by": role_map.generated_by,
                "roles": [role.title for role in role_map.searchable],
            },
        )

        return {
            "capability_graph_version": graph.version,
            "capability_graph_generated_by": graph.generated_by,
            "capability_nodes": len(graph.nodes),
            "capability_clusters": len(graph.clusters),
            "role_map_version": role_map.version,
            "role_map_generated_by": role_map.generated_by,
            "roles": len(role_map.roles),
            "primary_roles": len(role_map.primary),
            "secondary_roles": len(role_map.secondary),
            "exploratory_roles": len(role_map.stretch),
            "queries_created": created,
            "queries_updated": updated,
            "queries_archived": archived,
            "notes": role_map.notes,
        }

    async def regenerate_searches(self, use_llm: Optional[bool] = None) -> SearchStrategy:
        """Rebuilds the search slate from the stored role map, leaving roles alone."""
        role_map = await self.role_repo.get_active()
        if role_map is None:
            raise ValueError("No role map exists yet. Run a role discovery refresh first.")

        graph = await self.get_capability_graph()
        allow_llm = self.profile.role_discovery.use_llm if use_llm is None else use_llm

        strategy = await self.strategy.generate(
            self.profile,
            role_map,
            seniority_level=graph.seniority.level if graph else "mid",
            use_llm=allow_llm,
        )
        await self.query_repo.sync(strategy.queries)
        return strategy

    # -- learning loop -----------------------------------------------------

    async def learn_from_market(self, use_llm: Optional[bool] = None) -> MarketFeedbackReport:
        """Retunes queries and proposes new roles from what the user imported."""
        config = self.profile.role_discovery
        allow_llm = config.use_llm if use_llm is None else use_llm

        specs = await self.query_repo.list_specs()
        adjustments = evaluate_query_performance(specs, config)
        for adjustment in adjustments:
            await self.query_repo.update_query(
                adjustment.query_id,
                priority=adjustment.new_priority,
                status=adjustment.new_status,
            )

        role_map = await self.role_repo.get_active()
        graph = await self.get_capability_graph()
        proposals: List[DiscoveredRole] = []
        auto_accepted: List[str] = []

        if role_map is not None and graph is not None:
            signals = await self._job_signals()
            proposals = await self.agent.propose_roles_from_jobs(
                self.profile, graph, role_map, signals, use_llm=allow_llm
            )
            auto_accepted = select_auto_accepted(proposals, config)

            for proposal in proposals:
                if proposal.id in auto_accepted:
                    proposal.proposal_status = RoleProposalStatus.ACCEPTED
                await self.role_repo.add_role(proposal)

            if auto_accepted:
                await self._add_searches_for_roles(
                    [p for p in proposals if p.id in auto_accepted], graph
                )

        summary = (
            f"{len(adjustments)} search queries retuned, {len(proposals)} new roles proposed, "
            f"{len(auto_accepted)} accepted automatically."
        )
        await self.event_repo.log(
            event_type="ROLE_DISCOVERY_FEEDBACK",
            message=summary,
            details={
                "adjustments": [a.model_dump(mode="json") for a in adjustments],
                "proposed_roles": [p.title for p in proposals],
                "auto_accepted": auto_accepted,
            },
        )

        return MarketFeedbackReport(
            adjustments=adjustments,
            proposed_roles=proposals,
            auto_accepted_role_ids=auto_accepted,
            summary=summary,
        )

    async def accept_role(self, role_key: str) -> bool:
        """Adopts a proposed role and generates its searches immediately."""
        orm = await self.role_repo.update_role(
            role_key, proposal_status=RoleProposalStatus.ACCEPTED
        )
        if orm is None:
            return False
        role_map = await self.role_repo.get_active()
        role = role_map.role(role_key) if role_map else None
        if role is not None:
            graph = await self.get_capability_graph()
            await self._add_searches_for_roles([role], graph)
        return True

    async def reject_role(self, role_key: str) -> bool:
        orm = await self.role_repo.update_role(
            role_key,
            proposal_status=RoleProposalStatus.REJECTED,
            category=RoleCategory.AVOID,
        )
        if orm is None:
            return False
        for spec in await self.query_repo.list_specs(role_key=role_key):
            if spec.id:
                await self.query_repo.update_query(spec.id, status=SearchQueryStatus.DISABLED)
        return True

    # -- attribution -------------------------------------------------------

    async def record_search_opened(self, query_id: str) -> bool:
        return await self.query_repo.record_opened(query_id) is not None

    async def record_job_imported(self, query_id: Optional[str]) -> None:
        if query_id:
            await self.query_repo.record_import(query_id)

    async def record_match_score(self, query_id: Optional[str], match_score: int) -> None:
        if query_id:
            await self.query_repo.record_match_score(
                query_id, match_score, self.profile.role_discovery.high_match_threshold
            )

    async def record_application_created(self, query_id: Optional[str]) -> None:
        if query_id:
            await self.query_repo.record_application(query_id)

    async def record_interview(self, query_id: Optional[str]) -> None:
        if query_id:
            await self.query_repo.record_interview(query_id)

    # -- internals ---------------------------------------------------------

    async def _add_searches_for_roles(
        self,
        roles: Sequence[DiscoveredRole],
        graph: Optional[CandidateCapabilityGraph],
    ) -> int:
        if not roles:
            return 0
        partial_map = RoleMap(roles=list(roles))
        strategy = await self.strategy.generate(
            self.profile,
            partial_map,
            seniority_level=graph.seniority.level if graph else "mid",
            use_llm=False,
        )
        created, _, _ = await self.query_repo.sync(strategy.queries)
        return created

    async def _load_resume_digest(self) -> str:
        """Fetches the master CV. Role discovery still works without it."""
        client = self.rr_client
        if client is None:
            try:
                client = ReactiveResumeClient()
            except Exception:
                return ""

        resume_id = self.profile.reactive_resume.master_resume_id
        try:
            if resume_id:
                resume = await client.get_resume(resume_id)
            else:
                resumes = await client.list_resumes()
                if not resumes:
                    return ""
                resume = await client.get_resume(resumes[0].id)
            return build_resume_digest(resume)
        except Exception:
            return ""

    async def _imported_jobs(self, limit: int = 60) -> List[JobORM]:
        return await self.job_repo.list_jobs(
            limit=limit, discovered_by=DiscoveryChannel.BROWSER_EXTENSION.value
        )

    async def _job_signals(self) -> List[Dict[str, Any]]:
        signals = []
        for job in await self._imported_jobs():
            signals.append(
                build_job_signal(
                    title=job.role,
                    company=job.company,
                    match_score=job.match_score,
                    technologies=job.technologies or [],
                    description=job.description or "",
                    job_id=job.id,
                    search_query_id=job.search_query_id,
                )
            )
        return signals

    async def _market_feedback_text(self) -> str:
        try:
            specs = await self.query_repo.list_specs()
            signals = await self._job_signals()
        except Exception:
            return ""
        if not specs and not signals:
            return ""
        return summarise_market_feedback(
            specs, signals, self.profile.role_discovery.high_match_threshold
        )


def _carry_over_decisions(previous: RoleMap, current: RoleMap) -> None:
    """Preserves the user's verdicts across a regeneration.

    Roles the user rejected stay rejected, and roles adopted from real market
    postings survive even when the fresh map does not rediscover them.
    """
    current_ids = {role.id for role in current.roles}

    for role in previous.roles:
        if role.proposal_status == RoleProposalStatus.REJECTED:
            match = current.role(role.id)
            if match is not None:
                match.proposal_status = RoleProposalStatus.REJECTED
                match.category = RoleCategory.AVOID
            continue

        learned_from_market = role.discovered_from_job_id is not None
        if learned_from_market and role.id not in current_ids:
            carried = role.model_copy(deep=True)
            carried.updated_at = datetime.utcnow()
            current.roles.append(carried)
            current_ids.add(carried.id)
