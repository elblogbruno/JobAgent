"""Reporting outcomes by hand, and how they feed back into role discovery."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from packages.applications.outcomes import ApplicationOutcomeService, UnknownOutcomeError
from packages.candidate_profile.profile import CandidateProfileLoader
from packages.domain.enums import ApplicationStatus, JobSourceType, SearchProviderId
from packages.domain.models import CanonicalJob
from packages.domain.role_discovery import JobProvenance, JobSearchQuerySpec
from packages.domain.state_machine import InvalidStateTransitionError
from packages.persistence.database import Base
from packages.persistence.repositories import ApplicationRunRepository, JobRepository
from packages.persistence.role_repositories import SearchQueryRepository
from packages.persistence.schema_upgrade import apply_additive_migrations


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


async def _seed(session: AsyncSession, query_id: str | None = None) -> str:
    """Creates an imported job with no application run, as the extension leaves it."""
    job = CanonicalJob(
        dedup_hash="outcome-test-hash",
        company="Studio Alpha",
        normalized_company="Studio Alpha",
        role="Creative Technologist",
        normalized_role="Creative Technologist",
        canonical_url="https://jobs.ashbyhq.com/studio-alpha/123",
        apply_url="https://jobs.ashbyhq.com/studio-alpha/123",
        source=JobSourceType.ASHBY,
        source_job_id="123",
        description="Interactive installations with Unity and computer vision.",
        status=ApplicationStatus.EVALUATED,
    )
    orm = await JobRepository(session).create_or_update(
        job,
        provenance=JobProvenance(
            source="ashby",
            search_query_id=query_id,
            search_provider="linkedin",
            source_url="https://www.linkedin.com/jobs/view/1",
        ),
    )
    orm.match_score = 88
    await session.flush()
    return orm.id


async def _seed_query(session: AsyncSession) -> str:
    spec = JobSearchQuerySpec(
        role_id="role_creative_technologist",
        label="Creative Technologist",
        query='"Creative Technologist"',
        provider=SearchProviderId.LINKEDIN,
        priority=80,
    )
    orm = await SearchQueryRepository(session).create(spec)
    return orm.id


@pytest.mark.asyncio
async def test_marking_a_job_as_applied_creates_the_run(session: AsyncSession):
    job_id = await _seed(session)
    service = ApplicationOutcomeService(session, profile=CandidateProfileLoader.get())

    result = await service.record_for_job(job_id, "applied", note="Applied on the company site.")

    assert result["status"] == ApplicationStatus.APPLIED.value
    assert result["submittedManually"] is True
    assert result["appliedAt"]

    run = await ApplicationRunRepository(session).get_by_job_id(job_id)
    assert run is not None
    assert run.status == ApplicationStatus.APPLIED.value
    assert run.submitted_manually is True
    assert run.submission_evidence["evidence_type"] == "MANUAL_CONFIRMATION"
    assert run.submission_evidence["details"] == "Applied on the company site."

    job = await JobRepository(session).get_by_id(job_id)
    assert job is not None
    assert job.status == ApplicationStatus.APPLIED.value


@pytest.mark.asyncio
async def test_outcomes_credit_the_search_that_produced_the_job(session: AsyncSession):
    query_id = await _seed_query(session)
    job_id = await _seed(session, query_id=query_id)
    service = ApplicationOutcomeService(session, profile=CandidateProfileLoader.get())
    repo = SearchQueryRepository(session)

    await service.record_for_job(job_id, "applied")
    stats = (await repo.list_specs())[0].stats
    assert stats.applications_generated == 1
    assert stats.interviews_produced == 0

    await service.record_for_job(job_id, "interview", note="First call next Tuesday.")
    stats = (await repo.list_specs())[0].stats
    assert stats.interviews_produced == 1


@pytest.mark.asyncio
async def test_reporting_the_same_outcome_twice_does_not_double_count(session: AsyncSession):
    query_id = await _seed_query(session)
    job_id = await _seed(session, query_id=query_id)
    service = ApplicationOutcomeService(session, profile=CandidateProfileLoader.get())

    await service.record_for_job(job_id, "applied")
    await service.record_for_job(job_id, "applied", note="Confirmation email arrived.")

    stats = (await SearchQueryRepository(session).list_specs())[0].stats
    assert stats.applications_generated == 1

    run = await ApplicationRunRepository(session).get_by_job_id(job_id)
    assert run is not None
    # Both reports are kept in the history, only the counter is guarded.
    assert len(run.outcome_history) == 2


@pytest.mark.asyncio
async def test_the_full_outcome_chain_is_recorded(session: AsyncSession):
    job_id = await _seed(session)
    service = ApplicationOutcomeService(session, profile=CandidateProfileLoader.get())

    await service.record_for_job(job_id, "applied")
    await service.record_for_job(job_id, "interview")
    result = await service.record_for_job(job_id, "offer")

    assert result["status"] == ApplicationStatus.OFFER.value
    assert [entry["outcome"] for entry in result["history"]] == ["applied", "interview", "offer"]
    assert result["history"][0]["previous_status"] == ApplicationStatus.EVALUATED.value


@pytest.mark.asyncio
async def test_an_interview_cannot_be_reported_before_applying(session: AsyncSession):
    job_id = await _seed(session)
    service = ApplicationOutcomeService(session, profile=CandidateProfileLoader.get())

    with pytest.raises(InvalidStateTransitionError):
        await service.record_for_job(job_id, "interview")


@pytest.mark.asyncio
async def test_an_unknown_outcome_is_rejected(session: AsyncSession):
    job_id = await _seed(session)
    service = ApplicationOutcomeService(session, profile=CandidateProfileLoader.get())

    with pytest.raises(UnknownOutcomeError):
        await service.record_for_job(job_id, "ghosted")


@pytest.mark.asyncio
async def test_reporting_against_a_missing_job_raises(session: AsyncSession):
    service = ApplicationOutcomeService(session, profile=CandidateProfileLoader.get())
    with pytest.raises(LookupError):
        await service.record_for_job("does-not-exist", "applied")


# ---------------------------------------------------------------------------
# Undo, which is what makes automatic detection safe to have at all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_undoing_restores_the_previous_status(session: AsyncSession):
    query_id = await _seed_query(session)
    job_id = await _seed(session, query_id=query_id)
    service = ApplicationOutcomeService(session, profile=CandidateProfileLoader.get())

    await service.record_for_job(job_id, "applied", note="Detectado en la página")
    run = await ApplicationRunRepository(session).get_by_job_id(job_id)
    assert run is not None
    assert run.status == ApplicationStatus.APPLIED.value

    result = await service.undo_last(run.id)

    assert result["undone"] == "applied"
    assert result["status"] == ApplicationStatus.EVALUATED.value
    assert result["history"] == []

    run = await ApplicationRunRepository(session).get_by_id(run.id)
    assert run is not None
    assert run.status == ApplicationStatus.EVALUATED.value
    assert run.applied_at is None
    assert run.submitted_manually is False
    assert run.submission_evidence is None

    job = await JobRepository(session).get_by_id(job_id)
    assert job is not None
    assert job.status == ApplicationStatus.EVALUATED.value


@pytest.mark.asyncio
async def test_undo_only_removes_the_last_outcome(session: AsyncSession):
    job_id = await _seed(session)
    service = ApplicationOutcomeService(session, profile=CandidateProfileLoader.get())

    await service.record_for_job(job_id, "applied")
    await service.record_for_job(job_id, "interview")
    run = await ApplicationRunRepository(session).get_by_job_id(job_id)
    assert run is not None

    result = await service.undo_last(run.id)

    assert result["undone"] == "interview"
    assert result["status"] == ApplicationStatus.APPLIED.value
    assert [entry["outcome"] for entry in result["history"]] == ["applied"]


@pytest.mark.asyncio
async def test_undoing_with_nothing_reported_raises(session: AsyncSession):
    job_id = await _seed(session)
    run = await ApplicationRunRepository(session).create(job_id=job_id)
    await session.flush()

    service = ApplicationOutcomeService(session, profile=CandidateProfileLoader.get())
    with pytest.raises(LookupError):
        await service.undo_last(run.id)
