from typing import List, Optional
from packages.domain.models import JobSearchQuery, RawJob
from packages.job_sources.ashby import AshbySource
from packages.job_sources.base import JobSource
from packages.job_sources.greenhouse import GreenhouseSource
from packages.job_sources.lever import LeverSource


class ConfiguredFeedsSource(JobSource):
    """
    Coordinates multi-source discovery across Greenhouse, Lever, and Ashby feeds.
    """

    def __init__(
        self,
        greenhouse_tokens: Optional[List[str]] = None,
        lever_sites: Optional[List[str]] = None,
        ashby_boards: Optional[List[str]] = None,
    ):
        self.sources: List[JobSource] = [
            GreenhouseSource(board_tokens=greenhouse_tokens),
            LeverSource(sites=lever_sites),
            AshbySource(boards=ashby_boards),
        ]

    async def search(self, query: JobSearchQuery) -> List[RawJob]:
        all_jobs: List[RawJob] = []
        for src in self.sources:
            try:
                jobs = await src.search(query)
                all_jobs.extend(jobs)
                if len(all_jobs) >= query.limit:
                    return all_jobs[: query.limit]
            except Exception:
                continue
        return all_jobs

    async def get_job(self, source_job_id_or_url: str) -> Optional[RawJob]:
        for src in self.sources:
            try:
                job = await src.get_job(source_job_id_or_url)
                if job:
                    return job
            except Exception:
                continue
        return None
