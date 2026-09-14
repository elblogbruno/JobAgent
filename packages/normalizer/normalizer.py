from datetime import timezone
import hashlib
import re
from typing import List, Optional, Tuple
from packages.domain.enums import ApplicationStatus
from packages.domain.models import CanonicalJob, RawJob

KNOWN_TECH = [
    "Unity",
    "Unreal Engine",
    "C#",
    "C++",
    "Python",
    "OpenCV",
    "Computer Vision",
    "Metal",
    "Vulkan",
    "OpenGL",
    "DirectX",
    "visionOS",
    "ARKit",
    "ARCore",
    "OpenXR",
    "WebXR",
    "Three.js",
    "Spatial Computing",
    "Machine Learning",
    "PyTorch",
    "TensorFlow",
    "CUDA",
    "Shader",
    "HLSL",
    "GLSL",
]


class JobNormalizer:
    @classmethod
    def normalize_company(cls, company: str) -> str:
        c = company.strip()
        c = re.sub(
            r"[\s,]+(inc|llc|ltd|corp|gmbh|s\.l|s\.a|technologies|corporation)[\.]*$",
            "",
            c,
            flags=re.IGNORECASE,
        )
        c = re.sub(
            r"\b(inc|llc|ltd|corp|gmbh|technologies|corporation)\b",
            "",
            c,
            flags=re.IGNORECASE,
        )
        c = c.rstrip(" .,-")
        c = re.sub(r"\s+", " ", c).strip()
        return c.title()

    @classmethod
    def normalize_role(cls, role: str) -> str:
        r = role.strip()
        # Strip trailing location or work policy in parentheses or after hyphens
        r = re.sub(r"\s*[\(\[].*?[\)\]]", "", r)
        r = re.sub(r"\s*-\s*(remote|hybrid|onsite|emea|latam|us|europe).*", "", r, flags=re.IGNORECASE)
        r = re.sub(r"\s+", " ", r).strip()
        return r.title()

    @classmethod
    def detect_work_policy(cls, location_str: Optional[str], title_str: str, remote_policy_str: Optional[str]) -> Tuple[bool, bool]:
        text = f"{location_str or ''} {title_str} {remote_policy_str or ''}".lower()
        is_remote = "remote" in text or "telecommute" in text or "anywhere" in text
        is_hybrid = "hybrid" in text
        return is_remote, is_hybrid

    @classmethod
    def extract_salary(cls, salary_str: Optional[str]) -> Tuple[Optional[float], Optional[float], Optional[str]]:
        if not salary_str:
            return None, None, None

        currency = None
        if "€" in salary_str or "EUR" in salary_str.upper():
            currency = "EUR"
        elif "$" in salary_str or "USD" in salary_str.upper():
            currency = "USD"
        elif "£" in salary_str or "GBP" in salary_str.upper():
            currency = "GBP"

        # Find numbers
        clean = salary_str.replace(",", "")
        matches = re.findall(r"\b(\d+)(?:k)?\b", clean, flags=re.IGNORECASE)
        if not matches:
            return None, None, currency

        nums = []
        for m in matches:
            val = float(m)
            if val < 1000: # Handled 'k' notation
                val *= 1000
            nums.append(val)

        if len(nums) == 1:
            return nums[0], nums[0], currency
        elif len(nums) >= 2:
            return min(nums[:2]), max(nums[:2]), currency

        return None, None, currency

    @classmethod
    def extract_technologies(cls, text: str) -> List[str]:
        found = []
        text_lower = text.lower()
        for tech in KNOWN_TECH:
            escaped = re.escape(tech.lower())
            if tech in ("C#", "C++"):
                pattern = rf"(?:^|[\s,;./(]){escaped}(?:$|[\s,;./)])"
            else:
                pattern = rf"\b{escaped}\b"
            if re.search(pattern, text_lower):
                found.append(tech)
        return found

    @classmethod
    def description_fingerprint(cls, description: str) -> Optional[str]:
        """A content hash used to spot the same posting republished elsewhere.

        Only alphanumeric words are kept, so formatting, boilerplate whitespace and
        the board's own decoration do not change the fingerprint.
        """
        if not description:
            return None
        words = re.findall(r"[a-z0-9]+", description.lower())
        if len(words) < 25:
            return None
        return hashlib.sha256(" ".join(words[:400]).encode("utf-8")).hexdigest()

    @classmethod
    def compute_hash(cls, normalized_company: str, normalized_role: str, source_job_id: str) -> str:
        key = f"{normalized_company.lower()}:{normalized_role.lower()}:{source_job_id.lower()}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    @classmethod
    def normalize(cls, raw: RawJob) -> CanonicalJob:
        norm_company = cls.normalize_company(raw.company)
        norm_role = cls.normalize_role(raw.role)
        is_remote, is_hybrid = cls.detect_work_policy(raw.location, raw.role, raw.remote_policy)
        sal_min, sal_max, sal_curr = cls.extract_salary(raw.salary)
        technologies = cls.extract_technologies(f"{raw.role} {raw.description}")

        dedup_hash = cls.compute_hash(norm_company, norm_role, raw.source_job_id)

        return CanonicalJob(
            dedup_hash=dedup_hash,
            company=raw.company,
            normalized_company=norm_company,
            role=raw.role,
            normalized_role=norm_role,
            canonical_url=raw.canonical_url,
            apply_url=raw.apply_url,
            source=raw.source,
            source_job_id=raw.source_job_id,
            location=raw.location,
            is_remote=is_remote,
            is_hybrid=is_hybrid,
            salary_min=sal_min,
            salary_max=sal_max,
            salary_currency=sal_curr or raw.currency,
            description=raw.description,
            requirements=raw.requirements,
            preferred_requirements=raw.preferred_requirements,
            technologies=technologies,
            status=ApplicationStatus.NORMALIZED,
            published_at=(
                raw.published_at.astimezone(timezone.utc).replace(tzinfo=None)
                if raw.published_at and raw.published_at.tzinfo
                else raw.published_at
            ),
            discovered_at=(
                raw.discovered_at.astimezone(timezone.utc).replace(tzinfo=None)
                if raw.discovered_at and raw.discovered_at.tzinfo
                else raw.discovered_at
            ),
        )
