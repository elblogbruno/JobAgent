import re
from typing import Any, Dict, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from packages.domain.models import CandidateProfileModel
from packages.persistence.repositories import CandidateAnswerRepository


CANONICAL_PATTERNS = [
    # EU Work authorization & sponsorship
    (
        r"(legally\s+authorized|authorized\s+to\s+work|eligible\s+to\s+work).*(spain|eu|europe|european|bcn|barcelona)",
        "authorized_to_work_eu",
    ),
    (
        r"(require|need|will\s+you\s+require).*(sponsorship|visa).*(spain|eu|europe|european)",
        "requires_sponsorship_eu",
    ),
    # US Work authorization & sponsorship
    (
        r"(legally\s+authorized|authorized\s+to\s+work|eligible\s+to\s+work).*(united\s+states|u\.s\.|us|usa)",
        "authorized_to_work_us",
    ),
    (
        r"(require|need|will\s+you\s+require).*(sponsorship|visa).*(united\s+states|u\.s\.|us|usa|h-?1b)",
        "requires_sponsorship_us",
    ),
    # Generic sponsorship / authorization (defaults to EU candidate context)
    (
        r"(require|will\s+you\s+require).*(sponsorship|work\s+visa|visa\s+support)",
        "requires_sponsorship_general",
    ),
    (
        r"(legally\s+authorized|eligible\s+to\s+work|work\s+authorization)",
        "authorized_to_work_general",
    ),
    # Salary
    (
        r"(expected\s+salary|desired\s+salary|salary\s+expectation|compensation\s+expectation|target\s+salary)",
        "expected_salary",
    ),
    # Relocation
    (
        r"(willing\s+to\s+relocate|open\s+to\s+relocation|relocate\s+for\s+this\s+role)",
        "willing_to_relocate",
    ),
    # Notice period / availability
    (
        r"(notice\s+period|how\s+soon\s+can\s+you\s+start|availability\s+to\s+start|start\s+date)",
        "notice_period",
    ),
    # Remote preference
    (
        r"(comfortable\s+working\s+remotely|remote\s+work|prefer\s+remote)",
        "comfortable_remote",
    ),
    # Gender / Diversity / EEO disclosure (default: decline to self-identify if asked)
    (
        r"(gender|race|ethnicity|veteran|disability)",
        "eeo_decline",
    ),
]


class CandidateAnswerVault:
    def __init__(self, session: Optional[AsyncSession] = None):
        self.session = session
        self.repo = CandidateAnswerRepository(session) if session else None

    @classmethod
    def identify_canonical_key(cls, question_text: str) -> Optional[str]:
        cleaned = question_text.strip().lower()
        for pattern, canonical_key in CANONICAL_PATTERNS:
            if re.search(pattern, cleaned):
                return canonical_key
        return None

    async def resolve(
        self,
        question_text: str,
        profile: CandidateProfileModel,
    ) -> Tuple[Optional[Any], float, str]:
        """
        Resolves a question against:
        1. Stored verified database answers.
        2. Deterministic CandidateProfile rules.
        Returns: (answer_value, confidence, canonical_key_or_empty)
        """
        canonical_key = self.identify_canonical_key(question_text)
        if not canonical_key:
            return None, 0.0, ""

        # Check DB repository if session is present
        if self.repo:
            db_record = await self.repo.get_by_canonical(canonical_key)
            if db_record and db_record.confidence >= 0.9:
                return db_record.answer, db_record.confidence, canonical_key

        # Fallback to deterministic profile logic
        answer, confidence = self._resolve_from_profile(canonical_key, profile)
        if answer is not None:
            # Upsert into answer vault for future fast recall
            if self.repo:
                await self.repo.upsert_answer(
                    canonical_key=canonical_key,
                    answer=answer,
                    source="profile",
                    confidence=confidence,
                    raw_question=question_text,
                )
            return answer, confidence, canonical_key

        return None, 0.0, canonical_key

    def _resolve_from_profile(
        self,
        canonical_key: str,
        profile: CandidateProfileModel
    ) -> Tuple[Optional[Any], float]:
        visa = profile.job_preferences.visa_requirements

        if canonical_key == "authorized_to_work_eu":
            return visa.authorized_eu, 1.0
        elif canonical_key == "requires_sponsorship_eu":
            return visa.requires_sponsorship_eu, 1.0
        elif canonical_key == "authorized_to_work_us":
            return visa.authorized_us, 1.0
        elif canonical_key == "requires_sponsorship_us":
            return visa.requires_sponsorship_us, 1.0
        elif canonical_key == "requires_sponsorship_general":
            # In EU market context, candidate does not require sponsorship
            return visa.requires_sponsorship_eu, 0.95
        elif canonical_key == "authorized_to_work_general":
            return visa.authorized_eu, 0.95
        elif canonical_key == "expected_salary":
            if profile.job_preferences.preferred_salary:
                return f"€{int(profile.job_preferences.preferred_salary):,}", 0.95
            elif profile.job_preferences.minimum_salary:
                return f"€{int(profile.job_preferences.minimum_salary):,}", 0.95
            return None, 0.0
        elif canonical_key == "willing_to_relocate":
            return profile.job_preferences.relocation, 1.0
        elif canonical_key == "notice_period":
            return "Immediate / 2 weeks", 0.95
        elif canonical_key == "comfortable_remote":
            return True, 1.0
        elif canonical_key == "eeo_decline":
            return "I decline to self-identify", 0.99

        return None, 0.0
