"""The cached profile must follow the file, not the process lifetime."""

import time
from pathlib import Path

import pytest
import yaml

from packages.candidate_profile.profile import CandidateProfileLoader

BASE_PROFILE = {
    "identity": {
        "name": "Test Candidate",
        "email": "test@example.com",
        "phone": "+34 600 000 000",
        "location": "Barcelona, Spain",
    },
    "job_preferences": {},
    "application_preferences": {},
    "reactive_resume": {"master_resume_id": "resume-one", "master_resume_name": "First CV"},
}


@pytest.fixture
def profile_file(tmp_path: Path):
    """Isolates the class-level cache so the real profile is untouched."""
    saved = (
        CandidateProfileLoader._instance,
        CandidateProfileLoader._loaded_path,
        CandidateProfileLoader._loaded_mtime,
    )
    CandidateProfileLoader.reset()

    path = tmp_path / "candidate-profile.yaml"
    path.write_text(yaml.safe_dump(BASE_PROFILE), encoding="utf-8")
    yield path

    (
        CandidateProfileLoader._instance,
        CandidateProfileLoader._loaded_path,
        CandidateProfileLoader._loaded_mtime,
    ) = saved


def _rewrite(path: Path, master_id: str) -> None:
    data = dict(BASE_PROFILE)
    data["reactive_resume"] = {"master_resume_id": master_id, "master_resume_name": master_id}
    # Filesystem timestamps are coarse enough that a same-millisecond rewrite can
    # look unchanged, so the test makes the change unambiguous.
    time.sleep(0.01)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_a_change_on_disk_is_picked_up(profile_file: Path):
    """A worker that cached the profile at boot must see a new master CV."""
    assert CandidateProfileLoader.get(profile_file).reactive_resume.master_resume_id == "resume-one"

    _rewrite(profile_file, "resume-two")

    assert CandidateProfileLoader.get().reactive_resume.master_resume_id == "resume-two"


def test_an_unchanged_file_is_not_reparsed(profile_file: Path):
    first = CandidateProfileLoader.get(profile_file)
    second = CandidateProfileLoader.get()
    assert first is second


def test_saving_updates_the_cache_without_a_reparse(profile_file: Path):
    CandidateProfileLoader.get(profile_file)

    data = dict(BASE_PROFILE)
    data["reactive_resume"] = {"master_resume_id": "resume-three", "master_resume_name": "Third"}
    saved = CandidateProfileLoader.save(data, config_path=profile_file)

    assert CandidateProfileLoader.get() is saved
    assert saved.reactive_resume.master_resume_id == "resume-three"


def test_a_deleted_file_keeps_the_copy_in_memory(profile_file: Path):
    """Losing the profile mid-run would be worse than serving a slightly old one."""
    loaded = CandidateProfileLoader.get(profile_file)
    profile_file.unlink()

    assert CandidateProfileLoader.get() is loaded


def test_pointing_at_a_different_file_reloads(profile_file: Path, tmp_path: Path):
    CandidateProfileLoader.get(profile_file)

    other = tmp_path / "other-profile.yaml"
    data = dict(BASE_PROFILE)
    data["reactive_resume"] = {"master_resume_id": "resume-other", "master_resume_name": "Other"}
    other.write_text(yaml.safe_dump(data), encoding="utf-8")

    assert CandidateProfileLoader.get(other).reactive_resume.master_resume_id == "resume-other"


def test_a_missing_file_on_first_load_still_raises(tmp_path: Path):
    CandidateProfileLoader.reset()
    try:
        with pytest.raises(FileNotFoundError):
            CandidateProfileLoader.get(tmp_path / "nope.yaml")
    finally:
        CandidateProfileLoader.reset()
