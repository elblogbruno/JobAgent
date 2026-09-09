from datetime import datetime
from typing import List, Optional
import httpx
from packages.domain.enums import JobSourceType
from packages.domain.models import JobSearchQuery, RawJob
from packages.job_sources.base import JobSource


class AshbySource(JobSource):
    BASE_URL = "https://api.ashbyhq.com/posting-api/job-board"

    def __init__(self, boards: Optional[List[str]] = None, timeout: float = 30.0):
        self.boards = boards or ["linear", "replit", "perplexity", "scale"]
        self.timeout = timeout

    async def search(self, query: JobSearchQuery) -> List[RawJob]:
        results: List[RawJob] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for board in self.boards:
                url = f"{self.BASE_URL}/{board}"
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    jobs = data.get("jobs", [])
                    for j in jobs:
                        raw = self._parse_ashby_job(board, j)
                        if self._matches_query(raw, query):
                            results.append(raw)
                            if len(results) >= query.limit:
                                return results
                except Exception:
                    continue
        return results

    async def get_job(self, source_job_id_or_url: str) -> Optional[RawJob]:
        return None

    def _parse_ashby_job(self, board: str, item: dict) -> RawJob:
        job_id = item.get("id", "")
        title = item.get("title", "")
        location = item.get("location", "")
        description_html = item.get("descriptionHtml", "")
        job_url = item.get("jobUrl", f"https://jobs.ashbyhq.com/{board}/{job_id}")
        is_remote = item.get("isRemote", False) or "remote" in location.lower()

        published_str = item.get("publishedAt")
        published_at = None
        if published_str:
            try:
                published_at = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
            except Exception:
                pass

        compensation = item.get("compensation", {})
        comp_summary = compensation.get("compensationSummary") if isinstance(compensation, dict) else None

        return RawJob(
            source=JobSourceType.ASHBY,
            source_job_id=f"{board}:{job_id}",
            canonical_url=job_url,
            apply_url=job_url,
            company=board.capitalize(),
            role=title,
            location=location,
            remote_policy="Remote" if is_remote else None,
            salary=comp_summary,
            description=description_html or item.get("descriptionPlain", ""),
            published_at=published_at,
            raw_payload=item,
        )

    def _matches_query(self, job: RawJob, query: JobSearchQuery) -> bool:
        if query.query:
            q = query.query.lower()
            if q not in job.role.lower() and q not in job.description.lower():
                return False
        return True
