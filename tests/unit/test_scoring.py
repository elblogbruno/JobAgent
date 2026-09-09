import pytest
from packages.candidate_profile.profile import CandidateProfileLoader
from packages.domain.enums import ApplicationStatus, JobSourceType, Recommendation
from packages.domain.models import CanonicalJob
from packages.match_engine.engine import MatchEngine


@pytest.mark.asyncio
async def test_match_engine_scoring():
    profile = CandidateProfileLoader.get()
    engine = MatchEngine()

    job = CanonicalJob(
        dedup_hash="test-hash-123456",
        company="Meta",
        normalized_company="Meta",
        role="Senior XR Software Engineer",
        normalized_role="Senior Xr Software Engineer",
        canonical_url="https://example.com/job/meta-xr",
        apply_url="https://example.com/job/meta-xr",
        source=JobSourceType.GREENHOUSE,
        source_job_id="meta:xr-1",
        location="Remote, EU",
        is_remote=True,
        description="Looking for an XR engineer with extensive Unity and spatial computing experience.",
        technologies=["Unity", "C#", "OpenXR"],
        status=ApplicationStatus.NORMALIZED,
    )

    scorecard = await engine.evaluate(job, profile)
    assert scorecard.score >= 0 and scorecard.score <= 100
    assert scorecard.recommendation in (Recommendation.APPLY, Recommendation.PREPARE, Recommendation.IGNORE)
    assert isinstance(scorecard.strengths, list)
