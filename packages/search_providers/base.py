"""The SearchProvider abstraction.

A provider turns a stored search query plus the candidate's location and remote
preferences into a URL that opens real results on a job site. The backend is the
source of truth for these URLs so the extension never has to know how a site
encodes its filters.
"""

from abc import ABC, abstractmethod
from typing import Optional

from packages.domain.enums import SearchProviderId
from packages.domain.role_discovery import JobSearchQuerySpec


class SearchProvider(ABC):
    """Builds a ready-to-open results URL for one job site or search engine."""

    id: SearchProviderId
    name: str
    #: Shown in the extension so the user knows where the search will land.
    home_url: str = ""

    @abstractmethod
    def build_search_url(self, query: JobSearchQuerySpec) -> str:
        """Returns an absolute URL that opens the results for this query."""

    def supports_location(self, location: Optional[str]) -> bool:
        """Whether this provider can meaningfully filter by the given location."""
        return bool(location)

    def describe(self) -> dict:
        return {"id": self.id.value, "name": self.name, "homeUrl": self.home_url}
