from datetime import datetime
from typing import List, Optional
import httpx
from packages.domain.enums import JobSourceType
from packages.domain.models import JobSearchQuery, RawJob
from packages.job_sources.base import JobSource


class LeverSource(JobSource):
    BASE_URL = "https://api.lever.co/v0/postings"

    def __init__(self, sites: Optional[List[str]] = None, timeout: float = 30.0):
        self.sites = sites or ["palantir", "netflix", "spotify", "datadog", "figma"]
        self.timeout = timeout

    async def search(self, query: JobSearchQuery) -> List[RawJob]:
        results: List[RawJob] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for site in self.sites:
                url = f"{self.BASE_URL}/{site}?mode=json"
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue
                    postings = resp.json()
                    for p in postings:
                        raw = self._parse_lever_posting(site, p)
                        if self._matches_query(raw, query):
                            results.append(raw)
                            if len(results) >= query.limit:
                                return results
                except Exception:
                    continue
        return results

    async def get_job(self, source_job_id_or_url: str) -> Optional[RawJob]:
        return None

    def _parse_lever_posting(self, site: str, p: dict) -> RawJob:
        posting_id = p.get("id", "")
        title = p.get("text", "")
        categories = p.get("categories", {})
        location = categories.get("location", "")
        description_plain = p.get("descriptionPlain", "")
        hosted_url = p.get("hostedUrl", "")
        apply_url = p.get("applyUrl", hosted_url)

        created_at_ms = p.get("createdAt")
        published_at = None
        if created_at_ms:
            try:
                published_at = datetime.utcfromtimestamp(created_at_ms / 1000.0)
            except Exception:
                pass

        workplace_type = p.get("workplaceType", "")
        is_remote = workplace_type.lower() == "remote" or "remote" in location.lower()

        return RawJob(
            source=JobSourceType.LEVER,
            source_job_id=f"{site}:{posting_id}",
            canonical_url=hosted_url,
            apply_url=apply_url,
            company=site.capitalize(),
            role=title,
            location=location,
            remote_policy="Remote" if is_remote else None,
            description=description_plain or p.get("description", ""),
            published_at=published_at,
            raw_payload=p,
        )

    def _matches_query(self, job: RawJob, query: JobSearchQuery) -> bool:
        if query.query:
            q = query.query.lower()
            if q not in job.role.lower() and q not in job.description.lower():
                return False
        return True
