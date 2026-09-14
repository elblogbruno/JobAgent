import json
import pytest
from packages.agents.search_planner import SearchPlannerAgent
from packages.candidate_profile.profile import CandidateProfileLoader
from packages.domain.enums import JobSourceType
from packages.domain.models import RawJob, SearchPlan, SearchPlanEntry
from packages.job_sources.feeds import ConfiguredFeedsSource
from packages.llm.base import LLMProvider, LLMResponse
from packages.llm.gateway import LLMGateway


class StubLLMProvider(LLMProvider):
    def __init__(self, payload: str):
        self.payload = payload

    async def generate(self, messages, temperature=0.2, max_tokens=4096, response_format=None):
        return LLMResponse(content=self.payload, model="stub-provider")


def _raw_job(role: str, description: str = "", location: str = "Barcelona", job_id: str = "1") -> RawJob:
    return RawJob(
        source=JobSourceType.GREENHOUSE,
        source_job_id=job_id,
        canonical_url=f"https://example.com/jobs/{job_id}",
        apply_url=f"https://example.com/jobs/{job_id}/apply",
        company="Example",
        role=role,
        location=location,
        description=description,
    )


@pytest.mark.asyncio
async def test_planner_parses_llm_queries():
    profile = CandidateProfileLoader.get()
    payload = json.dumps({
        "queries": [
            {"query": "XR Engineer", "locations": ["Barcelona"], "remote": True, "rationale": "core fit"},
            {"query": "xr engineer", "locations": [], "remote": True, "rationale": "duplicate"},
            {"query": "Computer Vision", "locations": [], "remote": False, "rationale": "adjacent"},
        ],
        "notes": "focus on spatial computing",
    })
    planner = SearchPlannerAgent(llm_gateway=LLMGateway(provider=StubLLMProvider(payload)))

    plan = await planner.plan(profile)

    assert plan.generated_by == "llm"
    assert [entry.query for entry in plan.entries] == ["XR Engineer", "Computer Vision"]
    assert plan.entries[1].locations == profile.job_preferences.locations


@pytest.mark.asyncio
async def test_planner_falls_back_on_unusable_llm_output():
    profile = CandidateProfileLoader.get()
    planner = SearchPlannerAgent(llm_gateway=LLMGateway(provider=StubLLMProvider('{"score": 88}')))

    plan = await planner.plan(profile)

    assert plan.generated_by == "fallback"
    assert plan.entries
    assert len(plan.entries) <= profile.discovery.max_queries_per_cycle


@pytest.mark.asyncio
async def test_planner_respects_disabled_llm_planner():
    profile = CandidateProfileLoader.get().model_copy(deep=True)
    profile.discovery.use_llm_planner = False
    profile.discovery.seed_queries = ["Spatial Computing"]
    planner = SearchPlannerAgent(llm_gateway=LLMGateway(provider=StubLLMProvider("{}")))

    plan = await planner.plan(profile)

    assert plan.generated_by == "fallback"
    assert plan.entries[0].query == "Spatial Computing"


def test_allowed_sources_filter_configured_feeds():
    feeds = ConfiguredFeedsSource(allowed_sources=["greenhouse", "generic-web"])
    assert list(feeds.sources_by_name) == ["greenhouse"]


def test_entry_matching_covers_title_and_description():
    entry = SearchPlanEntry(query="Computer Vision")
    assert ConfiguredFeedsSource._matches_entry(_raw_job("Computer Vision Engineer"), entry)
    assert ConfiguredFeedsSource._matches_entry(_raw_job("Perception Engineer", "computer vision stack"), entry)
    assert not ConfiguredFeedsSource._matches_entry(_raw_job("Account Executive", "sales quota"), entry)


def test_ranking_prefers_title_then_remote():
    entry = SearchPlanEntry(query="Unity Developer", remote=True)
    jobs = [
        _raw_job("Backend Developer", "unity developer collaboration", "Madrid", "a"),
        _raw_job("Unity Developer", "", "Berlin", "b"),
        _raw_job("Unity Developer", "", "Remote, EU", "c"),
    ]

    ranked = ConfiguredFeedsSource._rank_matches(jobs, entry)

    assert [job.source_job_id for job in ranked] == ["c", "b", "a"]


@pytest.mark.asyncio
async def test_search_plan_interleaves_queries(monkeypatch):
    feeds = ConfiguredFeedsSource(allowed_sources=[])
    snapshot = [
        _raw_job("XR Engineer", job_id="xr-1"),
        _raw_job("XR Engineer", job_id="xr-2"),
        _raw_job("XR Engineer", job_id="xr-3"),
        _raw_job("Computer Vision Engineer", job_id="cv-1"),
    ]

    async def fake_search_sources(sources, query):
        return snapshot

    monkeypatch.setattr(feeds, "_search_sources", fake_search_sources)
    plan = SearchPlan(entries=[
        SearchPlanEntry(query="XR Engineer"),
        SearchPlanEntry(query="Computer Vision"),
    ])

    results = await feeds.search_plan(plan, limit=4, per_query_limit=3)
    ids = [job.source_job_id for job in results]

    assert ids[:2] == ["xr-1", "cv-1"]
    assert len(ids) == len(set(ids))
