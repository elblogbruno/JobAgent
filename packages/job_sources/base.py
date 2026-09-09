from abc import ABC, abstractmethod
from typing import List, Optional
from packages.domain.models import JobSearchQuery, RawJob


class JobSource(ABC):
    @abstractmethod
    async def search(self, query: JobSearchQuery) -> List[RawJob]:
        """Discovers jobs matching query parameters."""
        pass

    @abstractmethod
    async def get_job(self, source_job_id_or_url: str) -> Optional[RawJob]:
        """Fetches a specific job posting by ID or direct URL."""
        pass
