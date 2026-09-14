"""The full role discovery loop, end to end, against an in-memory database.

Profile and master CV in, role map out, searches persisted, a job imported from a
captured browser page, scored, attributed back to the search that produced it,
and finally a new role discovered from what the user chose to import.
"""

import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from packages.candidate_profile.profile import CandidateProfileLoader
from packages.domain.enums import RoleProposalStatus, SearchQueryStatus
from packages.domain.role_discovery import BrowserJobCapture
from packages.job_import.service import BrowserImportService
from packages.llm.base import LLMProvider, LLMResponse
from packages.llm.gateway import LLMGateway
from packages.persistence.database import Base
from packages.persistence.schema_upgrade import apply_additive_migrations
from packages.reactive_resume.models import ResumeBasics, ResumeData, ResumeDetail
from packages.role_discovery.service import RoleDiscoveryService

SCORECARD = json.dumps(
    {
        "score": 88,
        "recommendation": "APPLY",
        "confidence": 0.9,
        "strengths": ["Unity", "Computer vision", "Interactive installations"],
        "gaps": ["TouchDesigner"],
        "hard_requirements": ["Unity", "Real-time graphics"],
        "preferred_requirements": ["TouchDesigner"],
        "matched_skills": ["Unity", "OpenCV"],
        "missing_skills": ["TouchDesigner"],
        "seniority_fit": "Strong fit for a senior individual contributor",
        "location_fit": "Remote within the EU",
        "salary_fit": "Above the minimum",
        "domain_fit": "Interactive installations and real-time graphics",
        "why_this_is_interesting": "Combines prototyping with perception work.",
        "risks": [],
    }
)


class ScorecardLLM(LLMProvider):
    """Answers every JSON request with a match scorecard."""

    async def generate(self, messages, temperature=0.2, max_tokens=4096, response_format=None):
        return LLMResponse(content=SCORECARD, model="stub-provider")


class FakeReactiveResume:
    """Serves the master CV without touching the network."""

    def __init__(self):
        self.resume = ResumeDetail(
            id="master",
            name="Master CV",
            slug="master-cv",
            data=ResumeData(
                basics=ResumeBasics(name="Bruno Moya", headline="XR Engineer and Founder"),
                sections={
                    "experience": {
                        "items": [
                            {
                                "company": "Glassear",
                                "position": "Founder & CTO",
                                "date": "2021 - present",
                                "summary": (
                                    "Led a team of four engineers building AR smart glasses. "
                                    "Owned the product end-to-end from hardware prototypes to a "
                                    "Unity SDK. Built computer vision hand tracking with OpenCV "
                                    "and depth camera calibration."
                                ),
                                "keywords": ["Unity", "C#", "OpenXR", "computer vision"],
                            },
                            {
                                "company": "Studio X",
                                "position": "Interactive Installations Developer",
                                "date": "2019 - 2021",
                                "summary": (
                                    "Real-time graphics installations for museums and live events "
                                    "in Unity with shaders. Rapid prototyping of interactive "
                                    "exhibits driven by sensors and projection mapping."
                                ),
                                "keywords": ["Unity", "HLSL", "sensor", "exhibition"],
                            },
                        ]
                    },
                    "skills": {
                        "items": [
                            {"name": "Unity", "keywords": ["C#", "shader", "profiling"]},
                            {"name": "Computer Vision", "keywords": ["OpenCV", "SLAM"]},
                        ]
                    },
                },
            ),
        )

    async def get_resume(self, resume_id: str) -> ResumeDetail:
        return self.resume

    async def list_resumes(self, **_kwargs):
        return [self.resume]

    async def list_applications(self, **_kwargs):
        return []


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await apply_additive_migrations(conn)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


def _capture(
    role: str, company: str, job_id: str, search_query_id: str | None
) -> BrowserJobCapture:
    return BrowserJobCapture.model_validate(
        {
            "url": f"https://www.linkedin.com/jobs/view/{job_id}/?refId=abc",
            "title": f"{company} hiring {role} in Barcelona | LinkedIn",
            "hostname": "www.linkedin.com",
            "visibleText": f"{role}\n{company}\nBarcelona",
            "structuredData": [
                {
                    "@type": "JobPosting",
                    "title": role,
                    "hiringOrganization": {"name": company},
                    "jobLocation": {
                        "address": {"addressLocality": "Barcelona", "addressCountry": "ES"}
                    },
                    "jobLocationType": "TELECOMMUTE",
                    "description": (
                        "<p>Build interactive installations with Unity, computer vision, "
                        "real-time graphics and hardware prototypes for live AR experiences. "
                        f"This is the {company} posting for {role}.</p>"
                    ),
                    "skills": "Unity, OpenCV, AR",
                }
            ],
            "cleanedHtml": (
                '<a href="https://jobs.ashbyhq.com/'
                + company.lower().replace(" ", "-")
                + "/"
                + job_id
                + '">Apply</a>'
            ),
            "extracted": {},
            "searchQueryId": search_query_id,
            "searchProvider": "linkedin",
            "prepareApplication": False,
        }
    )


@pytest.mark.asyncio
async def test_role_discovery_to_import_to_learning(session: AsyncSession):
    profile = CandidateProfileLoader.get()
    gateway = LLMGateway(provider=ScorecardLLM())
    rr_client = FakeReactiveResume()

    role_service = RoleDiscoveryService(
        session, profile=profile, rr_client=rr_client, llm_gateway=gateway
    )

    # 1. Role discovery produces a map and a slate of resolvable searches.
    summary = await role_service.refresh(use_llm=False)
    assert summary["roles"] >= 3
    assert summary["primary_roles"] >= 1
    assert summary["queries_created"] > 0
    assert summary["capability_nodes"] > 5
    assert summary["capability_clusters"] >= 1

    role_map = await role_service.get_role_map()
    assert role_map is not None
    titles = [role.title for role in role_map.roles]
    assert "Spatial Computing Engineer" in titles

    searches = await role_service.list_search_queries()
    assert searches
    assert all(spec.resolved_url and spec.resolved_url.startswith("https://") for spec in searches)
    assert any(spec.is_exploratory for spec in searches)

    # 2. The user opens one of the searches.
    chosen = searches[0]
    assert chosen.id is not None
    assert await role_service.record_search_opened(chosen.id) is True

    # 3. The user imports a job from that search.
    import_service = BrowserImportService(
        session, profile=profile, rr_client=rr_client, llm_gateway=gateway
    )
    first = await import_service.import_job(
        _capture("Experience Design Engineer", "Studio Alpha", "3912345678", chosen.id),
        allow_llm=False,
    )

    assert first.status == "imported"
    assert first.job_id
    assert first.company == "Studio Alpha"
    assert first.role == "Experience Design Engineer"
    assert first.analysis_state == "pending"
    # The company ATS link behind the LinkedIn listing becomes the canonical URL.
    assert first.canonical_url is not None
    assert "ashbyhq.com" in first.canonical_url

    # 4. Analysis scores the job without blocking the import.
    analysed = await import_service.analyze(first.job_id, prepare=False)
    assert analysed.match_score == 88
    assert analysed.recommendation == "APPLY"
    assert analysed.analysis_state == "complete"
    assert analysed.strengths

    job = await import_service.job_repo.get_by_id(first.job_id)
    assert job is not None
    assert job.match_score == 88
    assert job.discovered_by == "browser-extension"
    assert job.search_query_id == chosen.id
    assert job.search_provider == "linkedin"
    assert job.source_url == "https://www.linkedin.com/jobs/view/3912345678/"
    assert job.description_fingerprint

    # 5. Search performance is attributed back to the query that produced the job.
    stats = next(
        spec.stats
        for spec in await role_service.list_search_queries(include_inactive=True)
        if spec.id == chosen.id
    )
    assert stats.searches_opened == 1
    assert stats.jobs_imported == 1
    assert stats.scored_imports == 1
    assert stats.high_match_jobs_imported == 1
    assert stats.average_match_score == 88.0

    # 6. The extension can tell the page is already imported, even though the job is
    # stored under the company ATS URL rather than the LinkedIn one the user is on.
    looked_up = await import_service.lookup("https://www.linkedin.com/jobs/view/3912345678/")
    assert looked_up is not None
    assert looked_up.job_id == first.job_id
    assert looked_up.match_score == 88

    # 7. Clicking import twice never creates a second job.
    again = await import_service.import_job(
        _capture("Experience Design Engineer", "Studio Alpha", "3912345678", chosen.id),
        allow_llm=False,
    )
    assert again.status == "duplicate"
    assert again.job_id == first.job_id
    assert again.match_score == 88
    assert "Already imported" in again.message

    # 8. A second posting with the same unknown title is market signal.
    second = await import_service.import_job(
        _capture("Experience Design Engineer", "Studio Beta", "3998765432", chosen.id),
        allow_llm=False,
    )
    assert second.status == "imported"
    assert second.job_id != first.job_id
    await import_service.analyze(second.job_id, prepare=False)

    # 9. The agent learns a role it did not start with.
    report = await role_service.learn_from_market(use_llm=False)
    proposed_titles = [role.title for role in report.proposed_roles]
    assert "Experience Design Engineer" in proposed_titles

    updated_map = await role_service.get_role_map()
    assert updated_map is not None
    proposal = updated_map.role("role_experience_design_engineer")
    assert proposal is not None
    assert proposal.proposal_status == RoleProposalStatus.PROPOSED
    assert proposal.discovered_from_job_id in (first.job_id, second.job_id)

    # 10. Accepting the role puts its searches in front of the user immediately.
    assert await role_service.accept_role("role_experience_design_engineer") is True
    new_searches = await role_service.list_search_queries(
        role_key="role_experience_design_engineer"
    )
    assert new_searches
    assert all(spec.resolved_url for spec in new_searches)

    accepted = (await role_service.get_role_map()).role("role_experience_design_engineer")
    assert accepted is not None
    assert accepted.proposal_status == RoleProposalStatus.ACCEPTED


@pytest.mark.asyncio
async def test_rejecting_a_role_disables_its_searches(session: AsyncSession):
    profile = CandidateProfileLoader.get()
    service = RoleDiscoveryService(
        session,
        profile=profile,
        rr_client=FakeReactiveResume(),
        llm_gateway=LLMGateway(provider=ScorecardLLM()),
    )
    await service.refresh(use_llm=False)

    role_map = await service.get_role_map()
    assert role_map is not None
    target = role_map.searchable[0]
    assert await service.list_search_queries(role_key=target.id)

    assert await service.reject_role(target.id) is True

    remaining = await service.list_search_queries(role_key=target.id)
    assert remaining == [] or all(spec.status != SearchQueryStatus.ACTIVE for spec in remaining)

    # A rejected role survives a regeneration as rejected.
    await service.refresh(use_llm=False)
    refreshed = (await service.get_role_map()).role(target.id)
    assert refreshed is not None
    assert refreshed.proposal_status == RoleProposalStatus.REJECTED


@pytest.mark.asyncio
async def test_regenerating_searches_keeps_performance_history(session: AsyncSession):
    profile = CandidateProfileLoader.get()
    service = RoleDiscoveryService(
        session,
        profile=profile,
        rr_client=FakeReactiveResume(),
        llm_gateway=LLMGateway(provider=ScorecardLLM()),
    )
    await service.refresh(use_llm=False)

    specs = await service.list_search_queries()
    tracked = specs[0]
    assert tracked.id is not None
    await service.record_job_imported(tracked.id)
    await service.record_match_score(tracked.id, 91)

    await service.regenerate_searches(use_llm=False)

    after = next(
        spec
        for spec in await service.list_search_queries(include_inactive=True)
        if spec.id == tracked.id
    )
    assert after.stats.jobs_imported == 1
    assert after.stats.high_match_jobs_imported == 1
    assert after.stats.average_match_score == 91.0


@pytest.mark.asyncio
async def test_the_discovery_cycle_plans_from_the_role_map(session: AsyncSession):
    """The automated board sweep uses the role map too, not just the extension."""
    from packages.agents.pipeline_agent import JobAgentPipeline

    profile = CandidateProfileLoader.get()
    rr_client = FakeReactiveResume()
    service = RoleDiscoveryService(
        session,
        profile=profile,
        rr_client=rr_client,
        llm_gateway=LLMGateway(provider=ScorecardLLM()),
    )
    await service.refresh(use_llm=False)

    pipeline = JobAgentPipeline(session, profile=profile, rr_client=rr_client)  # type: ignore[arg-type]
    plan = await pipeline.plan_from_role_map()

    assert plan is not None
    assert plan.generated_by == "role-map"
    assert plan.entries
    # Board sources match plain keywords, so no quotes or boolean operators here.
    assert all('"' not in entry.query and "site:" not in entry.query for entry in plan.entries)
    assert len(plan.entries) <= profile.discovery.max_queries_per_cycle
