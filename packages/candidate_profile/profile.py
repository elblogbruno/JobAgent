from pathlib import Path
from typing import Optional
import yaml
from packages.domain.models import CandidateProfileModel


DEFAULT_PROFILE_PATH = Path("config/candidate-profile.yaml")


class CandidateProfileLoader:
    """Loads the candidate profile, keeping one parsed copy per process.

    The cached copy is invalidated by the file's modification time. Without that,
    a long-running Celery worker would keep serving the profile it read at boot,
    so changing the master CV or any preference from the dashboard would have no
    effect on it until the process was restarted.
    """

    _instance: Optional[CandidateProfileModel] = None
    _loaded_path: Optional[Path] = None
    _loaded_mtime: Optional[int] = None

    @classmethod
    def load(cls, config_path: Path = DEFAULT_PROFILE_PATH) -> CandidateProfileModel:
        if not config_path.exists():
            raise FileNotFoundError(f"Candidate profile configuration not found at {config_path.resolve()}")

        with open(config_path, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f)

        cls._instance = CandidateProfileModel.model_validate(raw_data)
        cls._loaded_path = config_path
        cls._loaded_mtime = cls._mtime(config_path)
        return cls._instance

    @classmethod
    def get(cls, config_path: Optional[Path] = None) -> CandidateProfileModel:
        path = config_path or cls._loaded_path or DEFAULT_PROFILE_PATH
        if cls._instance is None or cls._is_stale(path):
            return cls.load(path)
        return cls._instance

    @classmethod
    def _is_stale(cls, config_path: Path) -> bool:
        if config_path != cls._loaded_path:
            return True
        current = cls._mtime(config_path)
        # An unreadable or deleted file keeps the copy already in memory: losing
        # the profile mid-run would be worse than serving a slightly old one.
        if current is None:
            return False
        return current != cls._loaded_mtime

    @staticmethod
    def _mtime(config_path: Path) -> Optional[int]:
        try:
            return config_path.stat().st_mtime_ns
        except OSError:
            return None

    @classmethod
    def reset(cls) -> None:
        """Drops the cached copy. Used by tests."""
        cls._instance = None
        cls._loaded_path = None
        cls._loaded_mtime = None

    @classmethod
    def save(cls, data: dict, config_path: Path = DEFAULT_PROFILE_PATH) -> CandidateProfileModel:
        model = CandidateProfileModel.model_validate(data)
        dump_dict = model.model_dump()

        # Format Enum values to simple strings for yaml
        if "application_preferences" in dump_dict and "execution_mode" in dump_dict["application_preferences"]:
            mode = dump_dict["application_preferences"]["execution_mode"]
            if hasattr(mode, "value"):
                dump_dict["application_preferences"]["execution_mode"] = mode.value

        config_path.parent.mkdir(parents=True, exist_ok=True)
        # Forcing LF keeps the file byte-identical across saves on Windows, so
        # writing the profile does not produce a whole-file diff every time.
        with open(config_path, "w", encoding="utf-8", newline="\n") as f:
            yaml.dump(dump_dict, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        cls._instance = model
        cls._loaded_path = config_path
        cls._loaded_mtime = cls._mtime(config_path)
        return model


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
