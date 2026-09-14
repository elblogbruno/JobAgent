from pathlib import Path

import pytest

from apps.api.routes.resumes import PREVIEW_CACHE, _cache_path, _safe_name, _section_summary
from packages.reactive_resume.models import ResumeBasics, ResumeData, ResumeDetail


def _resume(sections: dict) -> ResumeDetail:
    return ResumeDetail(
        id="r1",
        name="Master CV",
        slug="master-cv",
        data=ResumeData(basics=ResumeBasics(name="Test"), sections=sections),
    )


def test_section_summary_counts_visible_entries():
    summary = _section_summary(
        _resume(
            {
                "experience": {
                    "name": "Experience",
                    "items": [
                        {"company": "A", "visible": True},
                        {"company": "B"},
                        {"company": "C", "visible": False},
                    ],
                },
                "skills": {"items": [{"name": "Unity"}]},
                "summary": {"content": "<p>hi</p>"},
            }
        )
    )
    by_key = {entry["key"]: entry for entry in summary}

    assert by_key["experience"]["items"] == 2
    assert by_key["experience"]["name"] == "Experience"
    assert by_key["skills"]["items"] == 1
    assert by_key["summary"]["items"] == 0
    # Richest sections first, so the card shows substance before empty scaffolding.
    assert summary[0]["key"] == "experience"


def test_section_summary_marks_hidden_sections():
    summary = _section_summary(_resume({"awards": {"visible": False, "items": [{"title": "x"}]}}))
    assert summary[0]["visible"] is False


def test_section_summary_ignores_the_picture_section():
    summary = _section_summary(_resume({"picture": {"url": "x"}, "skills": {"items": []}}))
    assert [entry["key"] for entry in summary] == ["skills"]


@pytest.mark.parametrize(
    "resume_id",
    ["../../../etc/passwd", "..\\..\\windows\\system32", "id with spaces", "a/b/c"],
)
def test_cache_paths_cannot_escape_the_cache_directory(resume_id):
    """Resume ids arrive from the URL, so they never reach the filesystem raw."""
    path = _cache_path(resume_id, "v1")
    assert PREVIEW_CACHE.resolve() == path.resolve().parent
    assert path.name.endswith(".pdf")


def test_the_cache_key_follows_the_resume_version():
    first = _cache_path("resume-1", "2024-01-01T00:00:00Z")
    second = _cache_path("resume-1", "2024-06-01T00:00:00Z")
    assert first != second
    # Same version, same file: a revisited grid does not re-render the PDF.
    assert first == _cache_path("resume-1", "2024-01-01T00:00:00Z")


def test_an_unversioned_request_still_gets_a_stable_path():
    assert _cache_path("resume-1", None) == _cache_path("resume-1", None)


def test_safe_name_is_bounded():
    assert Path(_safe_name("x" * 500)).name == "x" * 80
    assert _safe_name("") == "resume"
