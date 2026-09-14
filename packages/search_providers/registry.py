"""Provider registry and URL resolution."""

from typing import Dict, List, Optional

from packages.domain.enums import SearchProviderId
from packages.domain.role_discovery import JobSearchQuerySpec
from packages.search_providers.base import SearchProvider
from packages.search_providers.providers import (
    GenericWebSearchProvider,
    GoogleJobsSearchProvider,
    IndeedSearchProvider,
    InfoJobsSearchProvider,
    LinkedInSearchProvider,
)

_PROVIDERS: Dict[SearchProviderId, SearchProvider] = {
    provider.id: provider
    for provider in (
        LinkedInSearchProvider(),
        InfoJobsSearchProvider(),
        GoogleJobsSearchProvider(),
        IndeedSearchProvider(),
        GenericWebSearchProvider(),
    )
}


def register_provider(provider: SearchProvider) -> None:
    """Adds or replaces a provider at runtime."""
    _PROVIDERS[provider.id] = provider


def get_provider(provider_id: SearchProviderId) -> SearchProvider:
    provider = _PROVIDERS.get(provider_id)
    if provider is None:
        return _PROVIDERS[SearchProviderId.GENERIC_WEB]
    return provider


def all_providers() -> List[SearchProvider]:
    return list(_PROVIDERS.values())


def resolve_search_url(query: JobSearchQuerySpec) -> Optional[str]:
    """Builds the target URL for a stored query, or None if the provider fails."""
    try:
        return get_provider(query.provider).build_search_url(query)
    except Exception:
        return None
