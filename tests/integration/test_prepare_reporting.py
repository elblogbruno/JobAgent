"""Why a CV was or was not prepared has to reach the caller.

The extension polled for an application run that a low match meant would never
appear, waited ninety seconds and reverted to the button with no explanation.
"""

import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from packages.candidate_profile.profile import CandidateProfileLoader
from packages.domain.enums import ApplicationStatus, JobSourceType
from packages.domain.models import CanonicalJob
from packages.job_import.service import BrowserImportService
from packages.llm.base import LLMProvider, LLMResponse
from packages.llm.gateway import LLMGateway
from packages.persistence.database import Base
from packages.persistence.repositories import JobRepository
from packages.persistence.schema_upgrade import apply_additive_migrations


def _scorecard(score: int, recommendation: str) -> str:
    return json.dumps(
        {
            "score": score,
            "recommendation": recommendation,
            "confidence": 0.9,
            "strengths": ["Python"],
            "gaps": ["Seniority"],
            "matched_skills": ["Python"],
        }
    )


class ScoreLLM(LLMProvider):
    def __init__(self, payload: str):
        self.payload = payload

    async def generate(self, messages, temperature=0.2, max_tokens=4096, response_format=None):
        return LLMResponse(content=self.payload, model="stub-provider")


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


async def _seed(session: AsyncSession) -> str:
    job = CanonicalJob(
        dedup_hash="prepare-reporting",
        company="Veltech",
        normalized_company="Veltech",
        role="AI Engineer Junior",
        normalized_role="AI Engineer Junior",
        canonical_url="https://iris-venture.careers.ats.bizneo.cloud/jobs/ai-engineer-junior",
        apply_url="https://iris-venture.careers.ats.bizneo.cloud/jobs/ai-engineer-junior",
        source=JobSourceType.COMPANY_CAREERS,
        source_job_id="ai-engineer-junior",
        description="Junior AI engineering role working in Python.",
        status=ApplicationStatus.NORMALIZED,
    )
    orm = await JobRepository(session).create_or_update(job)
    return orm.id


def _service(session: AsyncSession, payload: str) -> BrowserImportService:
    return BrowserImportService(
        session,
        profile=CandidateProfileLoader.get(),
        llm_gateway=LLMGateway(provider=ScoreLLM(payload)),
    )


@pytest.mark.asyncio
async def test_a_low_match_says_why_the_cv_was_skipped(session: AsyncSession):
    job_id = await _seed(session)
    service = _service(session, _scorecard(30, "IGNORE"))

    result = await service.analyze(job_id, prepare=True)

    assert result.preparation_state == "skipped"
    assert "30/100" in result.preparation_error
    assert "Preparar CV" in result.preparation_error
    assert result.application_run_id is None


@pytest.mark.asyncio
async def test_an_explicit_request_overrides_the_threshold(session: AsyncSession, monkeypatch):
    """The candidate can see the score and still want the CV."""
    job_id = await _seed(session)
    service = _service(session, _scorecard(30, "IGNORE"))

    prepared = {}

    async def fake_prepare(job, scorecard, job_id_arg):
        prepared["called"] = True
        return None

    monkeypatch.setattr(service, "_prepare_application", fake_prepare)
    result = await service.analyze(job_id, prepare=True, forced=True)

    assert prepared.get("called") is True
    assert result.preparation_state == "failed"
    assert result.preparation_error


@pytest.mark.asyncio
async def test_a_good_match_prepares_without_being_forced(session: AsyncSession, monkeypatch):
    job_id = await _seed(session)
    service = _service(session, _scorecard(88, "APPLY"))

    called = {}

    async def fake_prepare(job, scorecard, job_id_arg):
        called["yes"] = True
        return None

    monkeypatch.setattr(service, "_prepare_application", fake_prepare)
    await service.analyze(job_id, prepare=True)

    assert called.get("yes") is True


@pytest.mark.asyncio
async def test_not_asking_for_a_cv_leaves_the_state_alone(session: AsyncSession):
    job_id = await _seed(session)
    service = _service(session, _scorecard(88, "APPLY"))

    result = await service.analyze(job_id, prepare=False)

    assert result.preparation_state == "none"
    assert result.preparation_error == ""


@pytest.mark.asyncio
async def test_the_stored_status_reports_the_same_thing(session: AsyncSession):
    """Polling later must say what the analysis said, not a blank."""
    job_id = await _seed(session)
    service = _service(session, _scorecard(30, "IGNORE"))
    await service.analyze(job_id, prepare=True)

    status = await service.status_for(job_id)

    assert status is not None
    assert status.preparation_state == "none"
    assert status.match_score == 30
