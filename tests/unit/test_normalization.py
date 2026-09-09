import pytest
from packages.domain.enums import JobSourceType
from packages.domain.models import RawJob
from packages.normalizer.normalizer import JobNormalizer


def test_normalize_company_clean():
    assert JobNormalizer.normalize_company("Google Inc.") == "Google"
    assert JobNormalizer.normalize_company("Unity Technologies LLC") == "Unity"
    assert JobNormalizer.normalize_company("Acme Corp") == "Acme"


def test_normalize_role():
    assert JobNormalizer.normalize_role("Senior XR Engineer (Remote - Europe)") == "Senior Xr Engineer"
    assert JobNormalizer.normalize_role("Staff Software Engineer - Remote EMEA") == "Staff Software Engineer"


def test_extract_salary():
    min_sal, max_sal, curr = JobNormalizer.extract_salary("€90,000 - €120,000")
    assert min_sal == 90000
    assert max_sal == 120000
    assert curr == "EUR"

    min_sal, max_sal, curr = JobNormalizer.extract_salary("$140k - $180k")
    assert min_sal == 140000
    assert max_sal == 180000
    assert curr == "USD"


def test_extract_technologies():
    desc = "We need an engineer experienced with Unity, C#, C++, shaders, and OpenCV."
    techs = JobNormalizer.extract_technologies(desc)
    assert "Unity" in techs
    assert "C#" in techs
    assert "C++" in techs
    assert "OpenCV" in techs


def test_full_normalization():
    raw = RawJob(
        source=JobSourceType.GREENHOUSE,
        source_job_id="test:123",
        canonical_url="https://example.com/job/123",
        apply_url="https://example.com/job/123",
        company="Unity Technologies Inc.",
        role="XR Software Engineer (Remote)",
        location="Remote, Spain",
        salary="€95,000 - €115,000",
        description="Developing next-generation spatial computing tools using Unity, C#, and OpenXR.",
    )
    canonical = JobNormalizer.normalize(raw)
    assert canonical.normalized_company == "Unity"
    assert canonical.normalized_role == "Xr Software Engineer"
    assert canonical.is_remote is True
    assert canonical.salary_min == 95000
    assert canonical.salary_max == 115000
    assert "Unity" in canonical.technologies
    assert "OpenXR" in canonical.technologies
    assert len(canonical.dedup_hash) == 64
