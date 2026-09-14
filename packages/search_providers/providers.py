"""Concrete search providers.

Adding a new job site means adding one class here and registering it in
``registry.py``. Nothing else in the system needs to change.
"""

from typing import Optional
from urllib.parse import quote_plus, urlencode

from packages.domain.enums import SearchProviderId
from packages.domain.role_discovery import JobSearchQuerySpec
from packages.search_providers.base import SearchProvider

# Country hints that let providers pick a regional domain or filter id.
_SPAIN_HINTS = ("spain", "españa", "espana", "barcelona", "madrid", "valencia", "sevilla", "bilbao")
_UK_HINTS = ("united kingdom", "uk", "london", "manchester", "england", "scotland")
_GERMANY_HINTS = ("germany", "deutschland", "berlin", "munich", "münchen", "hamburg")
_NETHERLANDS_HINTS = ("netherlands", "amsterdam", "rotterdam", "utrecht")


def _matches(location: Optional[str], hints: tuple) -> bool:
    if not location:
        return False
    lowered = location.lower()
    return any(hint in lowered for hint in hints)


class LinkedInSearchProvider(SearchProvider):
    id = SearchProviderId.LINKEDIN
    name = "LinkedIn"
    home_url = "https://www.linkedin.com/jobs"

    def build_search_url(self, query: JobSearchQuerySpec) -> str:
        params = {"keywords": query.query}
        if query.location:
            params["location"] = query.location
        if query.remote:
            # LinkedIn workplace type: 1 on-site, 2 remote, 3 hybrid.
            params["f_WT"] = "2"
        params["sortBy"] = "R"
        return f"https://www.linkedin.com/jobs/search/?{urlencode(params)}"


class InfoJobsSearchProvider(SearchProvider):
    id = SearchProviderId.INFOJOBS
    name = "InfoJobs"
    home_url = "https://www.infojobs.net"

    def build_search_url(self, query: JobSearchQuerySpec) -> str:
        params = {
            "keyword": query.query,
            "segmentId": "",
            "page": "1",
            "sortBy": "RELEVANCE",
            "onlyForeignCountry": "false",
            "countryIds": "17",  # Spain, the only market InfoJobs covers well.
            "sinceDate": "ANY",
        }
        if query.remote:
            params["teleworkingIds"] = "2"  # fully remote
        if query.location and not _matches(query.location, ("remote", "europe", "worldwide")):
            params["provinceIds"] = ""
            params["keyword"] = f"{query.query} {query.location}".strip()
        return "https://www.infojobs.net/jobsearch/search-results/list.xhtml?" + urlencode(params)

    def supports_location(self, location: Optional[str]) -> bool:
        return _matches(location, _SPAIN_HINTS)


class GoogleJobsSearchProvider(SearchProvider):
    """Opens the Google Jobs widget, which aggregates most ATS postings."""

    id = SearchProviderId.GOOGLE
    name = "Google Jobs"
    home_url = "https://www.google.com"

    def build_search_url(self, query: JobSearchQuerySpec) -> str:
        terms = [query.query]
        if query.remote:
            terms.append("remote")
        if query.location:
            terms.append(query.location)
        phrase = " ".join(term for term in terms if term)
        return f"https://www.google.com/search?q={quote_plus(phrase)}&ibp=htl;jobs"


class IndeedSearchProvider(SearchProvider):
    id = SearchProviderId.INDEED
    name = "Indeed"
    home_url = "https://www.indeed.com"

    def _domain(self, location: Optional[str]) -> str:
        if _matches(location, _SPAIN_HINTS):
            return "https://es.indeed.com"
        if _matches(location, _UK_HINTS):
            return "https://uk.indeed.com"
        if _matches(location, _GERMANY_HINTS):
            return "https://de.indeed.com"
        if _matches(location, _NETHERLANDS_HINTS):
            return "https://nl.indeed.com"
        return "https://www.indeed.com"

    def build_search_url(self, query: JobSearchQuerySpec) -> str:
        params = {"q": query.query}
        if query.remote:
            params["l"] = "Remote"
        elif query.location:
            params["l"] = query.location
        return f"{self._domain(query.location)}/jobs?{urlencode(params)}"


class GenericWebSearchProvider(SearchProvider):
    """A plain web search, used for site-scoped hunts across ATS domains."""

    id = SearchProviderId.GENERIC_WEB
    name = "Web Search"
    home_url = "https://duckduckgo.com"

    def build_search_url(self, query: JobSearchQuerySpec) -> str:
        terms = [query.query]
        if query.remote:
            terms.append("remote")
        if query.location:
            terms.append(query.location)
        phrase = " ".join(term for term in terms if term)
        return f"https://duckduckgo.com/?q={quote_plus(phrase)}&ia=web"
