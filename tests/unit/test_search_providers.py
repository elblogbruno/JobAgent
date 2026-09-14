from urllib.parse import parse_qs, urlsplit

import pytest

from packages.domain.enums import SearchProviderId
from packages.domain.role_discovery import JobSearchQuerySpec
from packages.search_providers import (
    GenericWebSearchProvider,
    LinkedInSearchProvider,
    all_providers,
    get_provider,
    resolve_search_url,
)


def _spec(**kwargs) -> JobSearchQuerySpec:
    defaults = dict(
        role_id="role_xr_engineer",
        label="XR Engineer + Unity",
        query='"XR Engineer" Unity',
        provider=SearchProviderId.LINKEDIN,
        location="Barcelona",
        remote=True,
        priority=94,
    )
    defaults.update(kwargs)
    return JobSearchQuerySpec(**defaults)


def test_every_provider_builds_an_absolute_url():
    for provider in all_providers():
        url = provider.build_search_url(_spec(provider=provider.id))
        assert url.startswith("https://"), provider.id
        assert "XR+Engineer" in url or "XR%20Engineer" in url, provider.id


def test_linkedin_encodes_query_location_and_remote_filter():
    url = LinkedInSearchProvider().build_search_url(_spec())
    parts = urlsplit(url)
    params = parse_qs(parts.query)

    assert parts.netloc == "www.linkedin.com"
    assert parts.path == "/jobs/search/"
    assert params["keywords"] == ['"XR Engineer" Unity']
    assert params["location"] == ["Barcelona"]
    assert params["f_WT"] == ["2"]


def test_linkedin_omits_remote_filter_when_not_requested():
    url = LinkedInSearchProvider().build_search_url(_spec(remote=None))
    assert "f_WT" not in parse_qs(urlsplit(url).query)


def test_indeed_uses_the_regional_domain_for_the_location():
    indeed = get_provider(SearchProviderId.INDEED)
    assert indeed.build_search_url(_spec(location="Barcelona, Spain")).startswith(
        "https://es.indeed.com"
    )
    assert indeed.build_search_url(_spec(location="London, United Kingdom")).startswith(
        "https://uk.indeed.com"
    )
    assert indeed.build_search_url(_spec(location=None)).startswith("https://www.indeed.com")


def test_google_provider_opens_the_jobs_widget():
    url = get_provider(SearchProviderId.GOOGLE).build_search_url(_spec())
    assert "ibp=htl;jobs" in url
    assert "remote" in url


def test_infojobs_only_claims_spanish_locations():
    infojobs = get_provider(SearchProviderId.INFOJOBS)
    assert infojobs.supports_location("Barcelona, Spain") is True
    assert infojobs.supports_location("Berlin, Germany") is False
    assert "infojobs.net" in infojobs.build_search_url(_spec(provider=SearchProviderId.INFOJOBS))


def test_unknown_provider_falls_back_to_generic_web():
    assert isinstance(get_provider("nope"), GenericWebSearchProvider)  # type: ignore[arg-type]


def test_resolve_search_url_uses_the_specs_provider():
    spec = _spec(provider=SearchProviderId.GENERIC_WEB)
    url = resolve_search_url(spec)
    assert url is not None
    assert url.startswith("https://duckduckgo.com/")


@pytest.mark.parametrize("provider_id", list(SearchProviderId))
def test_site_scoped_queries_survive_encoding(provider_id: SearchProviderId):
    spec = _spec(
        provider=provider_id,
        query='"XR Engineer" (site:jobs.ashbyhq.com OR site:boards.greenhouse.io)',
    )
    url = get_provider(provider_id).build_search_url(spec)
    assert "site%3Ajobs.ashbyhq.com" in url or "site:jobs.ashbyhq.com" in url
