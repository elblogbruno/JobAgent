"""Downloading the tailored CV, which is the file you attach when applying by hand."""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.routes.applications import download_tailored_resume
from fastapi import HTTPException
from packages.domain.enums import JobSourceType
from packages.domain.models import CanonicalJob
from packages.persistence.database import Base
from packages.persistence.repositories import ApplicationRunRepository, JobRepository
from packages.persistence.schema_upgrade import apply_additive_migrations

PDF_BYTES = b"%PDF-1.4 tailored\n%%EOF"


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


async def _run_with_resume(session: AsyncSession, resume_path: str | None) -> str:
    job = CanonicalJob(
        dedup_hash="download-test",
        company="Studio Alpha",
        normalized_company="Studio Alpha",
        role="Creative Technologist",
        normalized_role="Creative Technologist",
        canonical_url="https://jobs.ashbyhq.com/studio-alpha/1",
        apply_url="https://jobs.ashbyhq.com/studio-alpha/1",
        source=JobSourceType.ASHBY,
        source_job_id="1",
        description="Unity and computer vision.",
    )
    job_orm = await JobRepository(session).create_or_update(job)
    run = await ApplicationRunRepository(session).create(job_id=job_orm.id)
    run.tailored_resume_path = resume_path
    await session.flush()
    return run.id


@pytest.mark.asyncio
async def test_the_prepared_cv_is_served_as_a_pdf(session: AsyncSession, tmp_path, monkeypatch):
    artifacts = tmp_path / "artifacts"
    (artifacts / "resumes").mkdir(parents=True)
    pdf = artifacts / "resumes" / "resume_1.pdf"
    pdf.write_bytes(PDF_BYTES)
    monkeypatch.setattr("apps.api.routes.applications.ARTIFACTS_ROOT", artifacts.resolve())

    run_id = await _run_with_resume(session, str(pdf))
    response = await download_tailored_resume(run_id, db=session)

    assert response.media_type == "application/pdf"
    assert Path(response.path) == pdf
    # Named after the job, so a folder of downloads stays readable.
    assert response.filename == "Studio-Alpha-Creative-Technologist.pdf"


@pytest.mark.asyncio
async def test_an_application_without_a_prepared_cv_says_so(session: AsyncSession):
    run_id = await _run_with_resume(session, None)
    with pytest.raises(HTTPException) as exc:
        await download_tailored_resume(run_id, db=session)
    assert exc.value.status_code == 404
    assert "Prepare it first" in exc.value.detail


@pytest.mark.asyncio
async def test_a_missing_file_is_reported_as_gone(session: AsyncSession, tmp_path, monkeypatch):
    artifacts = tmp_path / "artifacts"
    (artifacts / "resumes").mkdir(parents=True)
    monkeypatch.setattr("apps.api.routes.applications.ARTIFACTS_ROOT", artifacts.resolve())

    run_id = await _run_with_resume(session, str(artifacts / "resumes" / "vanished.pdf"))
    with pytest.raises(HTTPException) as exc:
        await download_tailored_resume(run_id, db=session)
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_paths_outside_the_artifacts_directory_are_refused(
    session: AsyncSession, tmp_path, monkeypatch
):
    """The stored path is data, so it never gets to name an arbitrary file."""
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    secret = tmp_path / "secret.pdf"
    secret.write_bytes(PDF_BYTES)
    monkeypatch.setattr("apps.api.routes.applications.ARTIFACTS_ROOT", artifacts.resolve())

    run_id = await _run_with_resume(session, str(secret))
    with pytest.raises(HTTPException) as exc:
        await download_tailored_resume(run_id, db=session)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_an_unknown_run_is_a_404(session: AsyncSession):
    with pytest.raises(HTTPException) as exc:
        await download_tailored_resume("does-not-exist", db=session)
    assert exc.value.status_code == 404
