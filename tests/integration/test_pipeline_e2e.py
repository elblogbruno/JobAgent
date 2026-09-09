from pathlib import Path
import pytest
from playwright.async_api import async_playwright
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from packages.application_adapters.greenhouse import GreenhouseAdapter
from packages.candidate_profile.answer_vault import CandidateAnswerVault
from packages.candidate_profile.profile import CandidateProfileLoader
from packages.domain.enums import ApplicationStatus, JobSourceType
from packages.domain.models import CanonicalJob, MatchScorecard, Recommendation
from packages.normalizer.normalizer import JobNormalizer
from packages.persistence.database import Base
from packages.persistence.repositories import ApplicationRunRepository, JobRepository
from packages.preflight.checker import ApplicationPreflight
from packages.verification.verifier import SubmissionVerifier


@pytest.fixture
async def test_db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_end_to_end_local_application(test_db_session: AsyncSession, tmp_path: Path):
    # 1. Load Candidate Profile
    profile = CandidateProfileLoader.get()
    assert profile.identity.name == "Bruno Moya"

    # 2. Canonical Job Creation
    job = CanonicalJob(
        dedup_hash="e2e-test-hash-4821",
        company="Unity Technologies",
        normalized_company="Unity",
        role="XR Software Engineer",
        normalized_role="Xr Software Engineer",
        canonical_url="https://example.com/jobs/xr",
        apply_url="https://example.com/jobs/xr",
        source=JobSourceType.GREENHOUSE,
        source_job_id="test:4821",
        location="Barcelona / Remote",
        is_remote=True,
        description="We are building the future of XR and spatial computing with Unity and C#.",
        technologies=["Unity", "C#", "XR"],
        status=ApplicationStatus.NORMALIZED,
    )

    job_repo = JobRepository(test_db_session)
    job_orm = await job_repo.create_or_update(job)
    job.id = job_orm.id

    # 3. Match Engine Evaluation
    scorecard = MatchScorecard(
        score=91,
        recommendation=Recommendation.APPLY,
        confidence=0.95,
        strengths=["10+ years Unity & XR", "Computer vision background"],
        gaps=["Metal shaders"],
        seniority_fit="Exact fit for Senior XR Engineer",
    )

    # 4. Generate local dummy PDF resume
    fake_pdf = tmp_path / "tailored_resume.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 Fake resume content for end to end test\n%%EOF" + b" " * 600)

    # 5. Create Application Run
    run_repo = ApplicationRunRepository(test_db_session)
    app_run = await run_repo.create(
        job_id=job.id,
        execution_mode="AUTO_APPLY",
        match_score=scorecard.score,
        scorecard=scorecard.model_dump(),
        reactive_resume_application_id="mock-rr-app-4821",
    )
    app_run.tailored_resume_path = str(fake_pdf)
    app_run.status = ApplicationStatus.READY.value
    await test_db_session.commit()

    # 6. Playwright Browser Execution against local Greenhouse fixture
    fixture_path = Path("tests/fixtures/greenhouse_form.html").resolve()
    assert fixture_path.exists()
    fixture_url = fixture_path.as_uri()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(fixture_url)

        # 7. Adapter identification
        adapter = GreenhouseAdapter()
        can_handle = await adapter.can_handle(fixture_url, page)
        assert can_handle is True

        # 8. Fill Form
        answer_vault = CandidateAnswerVault(test_db_session)
        await adapter.fill(
            page=page,
            profile=profile,
            resume_pdf_path=str(fake_pdf),
            cover_letter_text="I am thrilled to apply for the XR Engineer position.",
            answer_vault=answer_vault,
        )

        # Verify fields were populated
        assert await page.input_value("#first_name") == "Bruno"
        assert await page.input_value("#last_name") == "Moya"
        assert await page.input_value("#email") == profile.identity.email
        assert await page.input_value("#phone") == profile.identity.phone

        # 9. Preflight Checks
        preflight = ApplicationPreflight(
            profile=profile,
            job=job,
            tailored_resume_path=str(fake_pdf),
            match_score=scorecard.score,
            snapshots_dir=tmp_path / "snapshots",
        )
        preflight_res = await preflight.run_checks(page)
        assert preflight_res.passed is True

        # 10. Submit Form
        submitted = await adapter.submit(page)
        assert submitted is True

        # 11. Verify Confirmation Evidence
        evidence = await SubmissionVerifier.verify(page)
        assert evidence.verified is True
        assert evidence.evidence_type == "DOM_TEXT"

        # 12. Update State to APPLIED
        await run_repo.update_status(app_run.id, status=ApplicationStatus.APPLIED.value)
        await test_db_session.commit()

        updated_run = await run_repo.get_by_id(app_run.id)
        assert updated_run.status == "APPLIED"

        await browser.close()
