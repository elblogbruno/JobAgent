from abc import ABC, abstractmethod
from typing import List, Optional
from packages.domain.models import JobSearchQuery, RawJob


class JobSource(ABC):
    # Board-style sources publish a full listing that can be fetched once and filtered
    # locally. Keyword-style sources (a search API) must receive every query instead.
    requires_query_parameter: bool = False

    @abstractmethod
    async def search(self, query: JobSearchQuery) -> List[RawJob]:
        """Discovers jobs matching query parameters."""
        pass

    @abstractmethod
    async def get_job(self, source_job_id_or_url: str) -> Optional[RawJob]:
        """Fetches a specific job posting by ID or direct URL."""
        pass
