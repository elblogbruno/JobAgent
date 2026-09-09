from datetime import datetime
from typing import List, Optional
import httpx
from packages.domain.enums import JobSourceType
from packages.domain.models import JobSearchQuery, RawJob
from packages.job_sources.base import JobSource


class GreenhouseSource(JobSource):
    BASE_URL = "https://boards-api.greenhouse.io/v1/boards"

    def __init__(self, board_tokens: Optional[List[str]] = None, timeout: float = 30.0):
        self.board_tokens = board_tokens or [
            "unity3d",
            "automattic",
            "gitlab",
            "cloudflare",
            "figma",
            "stripe",
            "github",
            "discord",
        ]
        self.timeout = timeout

    async def search(self, query: JobSearchQuery) -> List[RawJob]:
        discovered_jobs: List[RawJob] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for token in self.board_tokens:
                url = f"{self.BASE_URL}/{token}/jobs?content=true"
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    jobs = data.get("jobs", [])
                    for j in jobs:
                        raw = self._parse_greenhouse_job(token, j)
                        if self._matches_query(raw, query):
                            discovered_jobs.append(raw)
                            if len(discovered_jobs) >= query.limit:
                                return discovered_jobs
                except Exception:
                    continue
        return discovered_jobs

    async def get_job(self, source_job_id_or_url: str) -> Optional[RawJob]:
        # If full greenhouse URL or token:id
        return None

    def _parse_greenhouse_job(self, board_token: str, item: dict) -> RawJob:
        job_id = str(item.get("id"))
        title = item.get("title", "")
        location_obj = item.get("location", {})
        location_name = location_obj.get("name") if isinstance(location_obj, dict) else str(location_obj)
        content = item.get("content", "")
        canonical_url = item.get("absolute_url", f"https://boards.greenhouse.io/{board_token}/jobs/{job_id}")

        updated_at = item.get("updated_at")
        published_at = None
        if updated_at:
            try:
                published_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            except Exception:
                pass

        return RawJob(
            source=JobSourceType.GREENHOUSE,
            source_job_id=f"{board_token}:{job_id}",
            canonical_url=canonical_url,
            apply_url=canonical_url,
            company=board_token.capitalize(),
            role=title,
            location=location_name,
            remote_policy="Remote" if "remote" in (location_name or "").lower() or "remote" in title.lower() else None,
            description=content,
            published_at=published_at,
            raw_payload=item,
        )

    def _matches_query(self, job: RawJob, query: JobSearchQuery) -> bool:
        if query.query:
            q = query.query.lower()
            if q not in job.role.lower() and q not in job.description.lower():
                return False
        if query.remote is True and not (job.remote_policy and "remote" in job.remote_policy.lower()):
            if not ("remote" in (job.location or "").lower()):
                return False
        return True
