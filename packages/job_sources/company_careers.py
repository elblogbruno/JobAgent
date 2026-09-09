import json
from typing import List, Optional
from bs4 import BeautifulSoup
import httpx
from packages.domain.enums import JobSourceType
from packages.domain.models import JobSearchQuery, RawJob
from packages.job_sources.base import JobSource


class CompanyCareersSource(JobSource):
    """
    Discovers jobs from direct company career URLs by extracting
    standard Schema.org 'JobPosting' JSON-LD tags.
    """

    def __init__(self, target_urls: Optional[List[str]] = None, timeout: float = 30.0):
        self.target_urls = target_urls or []
        self.timeout = timeout

    async def search(self, query: JobSearchQuery) -> List[RawJob]:
        discovered: List[RawJob] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for url in self.target_urls:
                try:
                    resp = await client.get(url, follow_redirects=True)
                    if resp.status_code != 200:
                        continue
                    jobs = self._extract_jsonld_jobs(url, resp.text)
                    for j in jobs:
                        discovered.append(j)
                        if len(discovered) >= query.limit:
                            return discovered
                except Exception:
                    continue
        return discovered

    async def get_job(self, source_job_id_or_url: str) -> Optional[RawJob]:
        return None

    def _extract_jsonld_jobs(self, page_url: str, html: str) -> List[RawJob]:
        results = []
        soup = BeautifulSoup(html, "html.parser")
        scripts = soup.find_all("script", type="application/ld+json")
        for s in scripts:
            try:
                data = json.loads(s.string or "")
                if isinstance(data, dict) and data.get("@type") == "JobPosting":
                    results.append(self._parse_single_posting(page_url, data))
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("@type") == "JobPosting":
                            results.append(self._parse_single_posting(page_url, item))
            except Exception:
                continue
        return results

    def _parse_single_posting(self, page_url: str, d: dict) -> RawJob:
        company_obj = d.get("hiringOrganization", {})
        company_name = company_obj.get("name") if isinstance(company_obj, dict) else str(company_obj)
        title = d.get("title", "")
        desc = d.get("description", "")
        job_id = str(d.get("identifier", hash(page_url + title)))

        return RawJob(
            source=JobSourceType.COMPANY_CAREERS,
            source_job_id=job_id,
            canonical_url=page_url,
            apply_url=page_url,
            company=company_name or "Unknown Company",
            role=title,
            location=str(d.get("jobLocation", "")),
            description=desc,
            raw_payload=d,
        )
