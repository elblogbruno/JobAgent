from pathlib import Path
from typing import Optional
import yaml
from packages.domain.models import CandidateProfileModel


class CandidateProfileLoader:
    _instance: Optional[CandidateProfileModel] = None

    @classmethod
    def load(cls, config_path: Path = Path("config/candidate-profile.yaml")) -> CandidateProfileModel:
        if not config_path.exists():
            raise FileNotFoundError(f"Candidate profile configuration not found at {config_path.resolve()}")

        with open(config_path, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f)

        cls._instance = CandidateProfileModel.model_validate(raw_data)
        return cls._instance

    @classmethod
    def get(cls) -> CandidateProfileModel:
        if cls._instance is None:
            return cls.load()
        return cls._instance


def is_role_allowed(profile: CandidateProfileModel, role_title: str) -> bool:
    title_lower = role_title.lower()
    for excluded in profile.application_preferences.excluded_roles:
        if excluded.lower() in title_lower:
            return False
    return True


def is_company_allowed(profile: CandidateProfileModel, company_name: str) -> bool:
    comp_lower = company_name.lower()
    for excluded in profile.application_preferences.excluded_companies:
        if excluded.lower() in comp_lower:
            return False
    return True


def matches_remote_preference(profile: CandidateProfileModel, is_remote: bool, is_hybrid: bool) -> bool:
    if not profile.application_preferences.require_remote_match:
        return True
    if is_remote and profile.job_preferences.remote:
        return True
    if is_hybrid and profile.job_preferences.hybrid:
        return True
    if not is_remote and not is_hybrid and profile.job_preferences.onsite:
        return True
    return False
