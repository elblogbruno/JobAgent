import asyncio
from typing import Dict, List, Optional
from packages.domain.models import (
    DiscoveryConfig,
    JobSearchQuery,
    RawJob,
    SearchPlan,
    SearchPlanEntry,
)
from packages.job_sources.ashby import AshbySource
from packages.job_sources.base import JobSource
from packages.job_sources.company_careers import CompanyCareersSource
from packages.job_sources.greenhouse import GreenhouseSource
from packages.job_sources.infojobs import InfoJobsClient, InfoJobsSource
from packages.job_sources.lever import LeverSource


class ConfiguredFeedsSource(JobSource):
    """
    Coordinates multi-source discovery across Greenhouse, Lever, Ashby, InfoJobs
    and direct company career pages.
    """

    SNAPSHOT_LIMIT = 100_000

    def __init__(
        self,
        discovery: Optional[DiscoveryConfig] = None,
        allowed_sources: Optional[List[str]] = None,
        greenhouse_tokens: Optional[List[str]] = None,
        lever_sites: Optional[List[str]] = None,
        ashby_boards: Optional[List[str]] = None,
        company_career_urls: Optional[List[str]] = None,
        infojobs_client: Optional[InfoJobsClient] = None,
    ):
        config = discovery or DiscoveryConfig()
        greenhouse_tokens = greenhouse_tokens or config.greenhouse_boards or None
        lever_sites = lever_sites or config.lever_sites or None
        ashby_boards = ashby_boards or config.ashby_boards or None
        company_career_urls = company_career_urls or config.company_career_urls or []

        candidates: Dict[str, JobSource] = {
            "greenhouse": GreenhouseSource(board_tokens=greenhouse_tokens),
            "lever": LeverSource(sites=lever_sites),
            "ashby": AshbySource(boards=ashby_boards),
        }
        if company_career_urls:
            candidates["company-careers"] = CompanyCareersSource(target_urls=company_career_urls)

        # InfoJobs only joins the rotation once the application credentials are present.
        infojobs = InfoJobsSource(
            client=infojobs_client,
            provinces=config.infojobs_provinces,
            detail_limit=config.infojobs_detail_limit,
        )
        if infojobs.client.is_configured:
            candidates["infojobs"] = infojobs

        if allowed_sources is not None:
            allowed = {s.lower() for s in allowed_sources}
            candidates = {key: src for key, src in candidates.items() if key in allowed}

        self.sources_by_name = candidates
        self.sources: List[JobSource] = list(candidates.values())

    async def search(self, query: JobSearchQuery) -> List[RawJob]:
        """Queries every configured source and merges the results."""
        merged = await self._search_sources(self.sources, query)
        return self._deduplicate(merged)[: query.limit]

    async def _search_sources(
        self,
        sources: List[JobSource],
        query: JobSearchQuery,
    ) -> List[RawJob]:
        results = await asyncio.gather(
            *(src.search(query) for src in sources),
            return_exceptions=True,
        )

        merged: List[RawJob] = []
        for result in results:
            if isinstance(result, Exception):
                continue
            merged.extend(result)
        return merged

    async def search_plan(self, plan: SearchPlan, limit: int, per_query_limit: int = 25) -> List[RawJob]:
        """
        Runs a full search plan. Board listings are fetched once and every plan entry is
        applied to that snapshot, so N queries cost N times fewer requests than N searches.
        Keyword APIs such as InfoJobs cannot be filtered locally, so they receive each query.
        """
        board_sources = [src for src in self.sources if not src.requires_query_parameter]
        keyword_sources = [src for src in self.sources if src.requires_query_parameter]

        snapshot = await self._search_sources(
            board_sources, JobSearchQuery(limit=self.SNAPSHOT_LIMIT)
        )

        per_entry: List[List[RawJob]] = []
        for entry in plan.entries:
            matches = [job for job in snapshot if self._matches_entry(job, entry)]
            if keyword_sources:
                matches.extend(
                    await self._search_sources(
                        keyword_sources, entry.to_search_query(limit=per_query_limit)
                    )
                )
            per_entry.append(self._rank_matches(matches, entry)[:per_query_limit])

        # Interleave the entries so no single query monopolises the cycle budget.
        collected: List[RawJob] = []
        for rank in range(per_query_limit):
            for matches in per_entry:
                if rank < len(matches):
                    collected.append(matches[rank])
            if len(self._deduplicate(collected)) >= limit:
                break

        return self._deduplicate(collected)[:limit]

    async def get_job(self, source_job_id_or_url: str) -> Optional[RawJob]:
        for src in self.sources:
            try:
                job = await src.get_job(source_job_id_or_url)
                if job:
                    return job
            except Exception:
                continue
        return None

    @staticmethod
    def _matches_entry(job: RawJob, entry: SearchPlanEntry) -> bool:
        phrase = entry.query.strip().lower()
        if not phrase:
            return True
        return phrase in job.role.lower() or phrase in job.description.lower()

    @staticmethod
    def _is_remote(job: RawJob) -> bool:
        return "remote" in f"{job.remote_policy or ''} {job.location or ''}".lower()

    @classmethod
    def _rank_matches(cls, jobs: List[RawJob], entry: SearchPlanEntry) -> List[RawJob]:
        """
        Ranks postings whose title carries the query terms above description-only matches,
        and, when the entry asks for remote work, remote postings above the rest.
        Remote stays a ranking signal rather than a filter: the match engine still judges
        location fit, and hard filtering here would drop hybrid and onsite roles the
        candidate would accept.
        """
        tokens = [token for token in entry.query.lower().split() if len(token) > 2]

        def rank(job: RawJob) -> tuple:
            role = job.role.lower()
            title_hits = sum(1 for token in tokens if token in role)
            remote_bonus = 1 if entry.remote is True and cls._is_remote(job) else 0
            return (title_hits, remote_bonus)

        return sorted(jobs, key=rank, reverse=True)

    @staticmethod
    def _deduplicate(jobs: List[RawJob]) -> List[RawJob]:
        seen: set[str] = set()
        unique: List[RawJob] = []
        for job in jobs:
            key = job.canonical_url or f"{job.source.value}:{job.source_job_id}"
            if key in seen:
                continue
            seen.add(key)
            unique.append(job)
        return unique
