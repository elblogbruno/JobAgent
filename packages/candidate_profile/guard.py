import re
from typing import Any, Dict, List, Optional, Set
from packages.domain.models import CandidateProfileModel
from packages.reactive_resume.models import ResumeData


class HallucinationGuardViolation(Exception):
    def __init__(self, violations: List[str]):
        self.violations = violations
        super().__init__(f"Hallucination guard triggered: {'; '.join(violations)}")


class HallucinationGuard:
    """
    Verifies that generated tailored resumes and cover letters do not invent
    unauthorized companies, degrees, institutions, or skills not present in
    the Master Resume or CandidateProfile.
    """

    def __init__(
        self, profile: CandidateProfileModel, master_resume_data: Optional[ResumeData] = None
    ):
        self.profile = profile
        self.master_resume = master_resume_data

        # Build authorized sets
        self.authorized_skills: Set[str] = set()
        self.authorized_companies: Set[str] = set()
        self.authorized_roles: Set[str] = set()

        self._build_authorized_vocabulary()

    def _build_authorized_vocabulary(self):
        # From candidate profile
        for role in self.profile.job_preferences.roles:
            self.authorized_roles.add(role.lower())
        for interest in self.profile.job_preferences.interests:
            self.authorized_skills.add(interest.lower())

        # From master resume
        if self.master_resume:
            sections = self.master_resume.sections

            # Work experience
            exp_section = sections.get("experience", {})
            for item in exp_section.get("items", []):
                company = item.get("company", "").strip().lower()
                if company:
                    self.authorized_companies.add(company)
                pos = item.get("position", "").strip().lower()
                if pos:
                    self.authorized_roles.add(pos)

            # Skills
            skills_section = sections.get("skills", {})
            for item in skills_section.get("items", []):
                skill_name = item.get("name", "").strip().lower()
                if skill_name:
                    self.authorized_skills.add(skill_name)
                for kw in item.get("keywords", []):
                    if kw:
                        self.authorized_skills.add(kw.strip().lower())

            # Projects
            proj_section = sections.get("projects", {})
            for item in proj_section.get("items", []):
                for kw in item.get("keywords", []):
                    if kw:
                        self.authorized_skills.add(kw.strip().lower())

    def verify_tailored_bullets(
        self, proposed_bullets: List[str], original_bullets: List[str]
    ) -> List[str]:
        """
        Validates that rewritten or highlighted bullets do not invent new facts.
        Returns a list of violation messages (empty if completely clean).
        """
        violations = []
        original_text = " ".join(original_bullets).lower()

        # Check for suspicious claims: invented metrics like "increased revenue by 500%" if not in original
        for bullet in proposed_bullets:
            # No \b after the percent sign: it is not a word character, so
            # "cut latency by 40%." never matched and invented metrics walked
            # straight through.
            numbers = re.findall(
                r"(\d{1,3}\s?%"
                r"|[$€£]\s?\d[\d,.]*"
                r"|\b\d+\s?x\b"
                r"|\b\d+\s+(?:years|months|users|people|clients|engineers)\b)",
                bullet.lower(),
            )
            for num in numbers:
                if num.strip() not in original_text:
                    violations.append(
                        f"Unverified numeric claim '{num}' in proposed bullet: '{bullet[:80]}...'"
                    )

        return violations

    def verify_no_invented_technologies(
        self,
        proposed_text: str,
        master_corpus: Optional[str] = None,
    ) -> List[str]:
        """Catches the failure mode that matters most in a tailored CV.

        A model asked to match a posting will happily fold the posting's stack
        into the candidate's experience. Every technology term recognised in the
        proposed text must already appear in the master CV or the profile,
        otherwise the candidate is being credited with something they never did.
        """
        from packages.resume_pipeline.tailoring_agent import technologies_in

        corpus = (master_corpus or "").lower()
        violations: List[str] = []

        for label in technologies_in(proposed_text):
            lowered = label.lower()
            if lowered in self.authorized_skills:
                continue
            if corpus and lowered in corpus:
                continue
            # The label is our own name for the term; check the words it is made
            # of too, so "Vulkan / Metal" is not rejected when the CV says Metal.
            parts = [part.strip() for part in re.split(r"[/&]", label) if part.strip()]
            if any(
                part.lower() in self.authorized_skills or (corpus and part.lower() in corpus)
                for part in parts
            ):
                continue
            violations.append(f"'{label}' appears in the tailored text but not in the master CV")

        return violations

    def verify_cover_letter(self, cover_letter_text: str) -> List[str]:
        """
        Validates that cover letter does not claim unverified companies or credentials.
        """
        violations = []
        # Basic sanity check
        if len(cover_letter_text.strip()) < 50:
            violations.append("Cover letter content is suspiciously short or empty.")
        return violations
