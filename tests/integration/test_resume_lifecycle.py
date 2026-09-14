"""Deleting a CV and rebuilding a tailored one, without leaving orphans behind."""

from typing import List, Optional

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.routes import resumes as resumes_route
from packages.applications.regeneration import ResumeRegenerationService
from packages.candidate_profile.profile import CandidateProfileLoader
from packages.domain.enums import ApplicationStatus, JobSourceType
from packages.domain.models import CanonicalJob
from packages.persistence.database import Base
from packages.persistence.repositories import ApplicationRunRepository, JobRepository
from packages.persistence.schema_upgrade import apply_additive_migrations
from packages.reactive_resume.models import (
    ApplicationResponse,
    ResumeBasics,
    ResumeData,
    ResumeDetail,
)

MASTER_ID = "master-cv"


class FakeReactiveResume:
    """Records what the pipeline asked Reactive Resume to do."""

    def __init__(self):
        self.deleted: List[str] = []
        self.created_resumes = 0
        self.fail_delete = False

    async def get_resume(self, resume_id: str) -> ResumeDetail:
        return ResumeDetail(
            id=resume_id,
            name="Master",
            slug="master",
            data=ResumeData(
                basics=ResumeBasics(name="Test", headline="XR Engineer"),
                sections={
                    "experience": {
                        "items": [
                            {
                                "company": "Glassear",
                                "position": "Founder",
                                "date": "2021",
                                "summary": "Built AR glasses with Unity and OpenCV.",
                            }
                        ]
                    },
                    "skills": {"items": [{"name": "Unity", "keywords": ["C#"]}]},
                },
            ),
        )

    async def list_resumes(self, **_kwargs):
        return []

    async def create_application(self, _request) -> ApplicationResponse:
        return ApplicationResponse(
            id="rr-app-1", company="Studio Beta", role="Mixed Reality Engineer", status="saved"
        )

    async def duplicate_resume(self, resume_id: str, name: str, slug: str, tags=None):
        self.created_resumes += 1
        return ResumeDetail(
            id=f"derived-{self.created_resumes}",
            name=name,
            slug=slug,
            data=(await self.get_resume(resume_id)).data,
        )

    async def patch_resume(self, _resume_id, _operations):
        return None

    async def lock_resume(self, _resume_id):
        return True

    async def download_resume_pdf(self, _resume_id, target="resume") -> bytes:
        return b"%PDF-1.4 regenerated\n%%EOF"

    async def attach_application_document(self, **_kwargs):
        return None

    async def delete_resume(self, resume_id: str) -> bool:
        if self.fail_delete:
            raise RuntimeError("Reactive Resume is down")
        self.deleted.append(resume_id)
        return True


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


@pytest.fixture
def profile(tmp_path):
    base = CandidateProfileLoader.get().model_copy(deep=True)
    base.reactive_resume.master_resume_id = MASTER_ID
    return base


async def _seed_run(session: AsyncSession, resume_id: Optional[str]) -> str:
    job = CanonicalJob(
        dedup_hash="lifecycle-test",
        company="Studio Beta",
        normalized_company="Studio Beta",
        role="Mixed Reality Engineer",
        normalized_role="Mixed Reality Engineer",
        canonical_url="https://jobs.ashbyhq.com/studio-beta/1",
        apply_url="https://jobs.ashbyhq.com/studio-beta/1",
        source=JobSourceType.ASHBY,
        source_job_id="1",
        description="Unity and computer vision for mixed reality.",
        technologies=["Unity"],
        status=ApplicationStatus.EVALUATED,
    )
    job_orm = await JobRepository(session).create_or_update(job)
    job_orm.match_score = 82
    run = await ApplicationRunRepository(session).create(job_id=job_orm.id)
    run.reactive_resume_resume_id = resume_id
    run.tailored_resume_path = "artifacts/resumes/old.pdf"
    await session.flush()
    return run.id


# ---------------------------------------------------------------------------
# Regeneration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regenerating_replaces_the_previous_cv(session: AsyncSession, profile):
    run_id = await _seed_run(session, "derived-old")
    client = FakeReactiveResume()

    result = await ResumeRegenerationService(session, profile=profile, rr_client=client).regenerate(
        run_id
    )

    assert result["resumeId"] == "derived-1"
    assert result["previousResumeDeleted"] is True
    assert client.deleted == ["derived-old"]

    run = await ApplicationRunRepository(session).get_by_id(run_id)
    assert run is not None
    assert run.reactive_resume_resume_id == "derived-1"
    assert run.status == ApplicationStatus.READY.value
    assert run.tailored_resume_path.endswith(".pdf")


@pytest.mark.asyncio
async def test_the_master_cv_is_never_deleted_by_a_rebuild(session: AsyncSession, profile):
    """A run pointing at the master must not lose it when its CV is rebuilt."""
    run_id = await _seed_run(session, MASTER_ID)
    client = FakeReactiveResume()

    result = await ResumeRegenerationService(session, profile=profile, rr_client=client).regenerate(
        run_id
    )

    assert result["previousResumeDeleted"] is False
    assert client.deleted == []


@pytest.mark.asyncio
async def test_a_first_rebuild_has_nothing_to_delete(session: AsyncSession, profile):
    run_id = await _seed_run(session, None)
    client = FakeReactiveResume()

    result = await ResumeRegenerationService(session, profile=profile, rr_client=client).regenerate(
        run_id
    )

    assert result["previousResumeDeleted"] is False
    assert client.deleted == []
    assert result["resumeId"] == "derived-1"


@pytest.mark.asyncio
async def test_a_failed_cleanup_does_not_fail_the_rebuild(session: AsyncSession, profile):
    """A leftover CV is untidy. Losing the rebuild over it would be worse."""
    run_id = await _seed_run(session, "derived-old")
    client = FakeReactiveResume()
    client.fail_delete = True

    result = await ResumeRegenerationService(session, profile=profile, rr_client=client).regenerate(
        run_id
    )

    assert result["resumeId"] == "derived-1"
    assert result["previousResumeDeleted"] is False


@pytest.mark.asyncio
async def test_rebuilding_an_unknown_run_raises(session: AsyncSession, profile):
    service = ResumeRegenerationService(session, profile=profile, rr_client=FakeReactiveResume())
    with pytest.raises(LookupError):
        await service.regenerate("does-not-exist")


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_master_cv_cannot_be_deleted(session: AsyncSession, monkeypatch):
    master_id = CandidateProfileLoader.get().reactive_resume.master_resume_id
    with pytest.raises(HTTPException) as exc:
        await resumes_route.delete_resume(master_id, db=session)

    assert exc.value.status_code == 409
    assert "master CV" in exc.value.detail


@pytest.mark.asyncio
async def test_deleting_detaches_applications_and_clears_the_preview_cache(
    session: AsyncSession, tmp_path, monkeypatch
):
    run_id = await _seed_run(session, "derived-old")
    monkeypatch.setattr(resumes_route, "PREVIEW_CACHE", tmp_path)
    cached = tmp_path / "derived-old_abc123.pdf"
    cached.write_bytes(b"%PDF-1.4")

    client = FakeReactiveResume()
    monkeypatch.setattr(resumes_route, "ReactiveResumeClient", lambda *a, **k: client)

    result = await resumes_route.delete_resume("derived-old", db=session)

    assert result["detachedApplications"] == 1
    assert client.deleted == ["derived-old"]
    assert not cached.exists()

    run = await ApplicationRunRepository(session).get_by_id(run_id)
    assert run is not None
    assert run.reactive_resume_resume_id is None
