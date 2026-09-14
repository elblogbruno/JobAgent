from typing import Optional
from packages.candidate_profile.guard import HallucinationGuard
from packages.domain.models import CandidateProfileModel, CanonicalJob
from packages.llm.base import LLMMessage
from packages.llm.gateway import LLMGateway
from packages.reactive_resume.client import ReactiveResumeClient
from packages.reactive_resume.models import CoverLetterCreateRequest

COVER_LETTER_SYSTEM_PROMPT = """You are a professional cover letter writer for senior technology leaders and engineers.
Draft a concise, compelling, 3-4 paragraph cover letter.
CRITICAL RULES:
1. ONLY mention facts, achievements, and experiences true to the candidate profile.
2. DO NOT invent previous employers, degrees, or false metrics.
3. Tone: confident, professional, humble, and value-focused.
4. Output plain text directly, no markdown fences.
"""


class CoverLetterAgent:
    def __init__(
        self,
        profile: CandidateProfileModel,
        llm_gateway: Optional[LLMGateway] = None,
        rr_client: Optional[ReactiveResumeClient] = None,
    ):
        self.profile = profile
        self.gateway = llm_gateway or LLMGateway.get()
        self.rr_client = rr_client

    async def generate(self, job: CanonicalJob, application_id: Optional[str] = None) -> str:
        prompt = f"""
Candidate:
- Name: {self.profile.identity.name}
- Email: {self.profile.identity.email}
- Location: {self.profile.identity.location}
- Roles: {", ".join(self.profile.job_preferences.roles)}
- Tech Interests: {", ".join(self.profile.job_preferences.interests)}

Job Opportunity:
- Company: {job.company}
- Role: {job.role}
- Description Excerpt:
{job.description[:2500]}
"""
        messages = [
            LLMMessage(role="system", content=COVER_LETTER_SYSTEM_PROMPT),
            LLMMessage(role="user", content=prompt),
        ]
        resp = await self.gateway.generate(messages, temperature=0.3)
        cover_letter_text = resp.content.strip()

        # Guard check
        guard = HallucinationGuard(self.profile)
        violations = guard.verify_cover_letter(cover_letter_text)
        if violations:
            # Fallback to standard safe template if issues detected
            cover_letter_text = self._fallback_template(job)

        # Optionally save to Reactive Resume CoverLetters
        if self.rr_client and application_id:
            try:
                await self.rr_client.create_cover_letter(
                    CoverLetterCreateRequest(
                        name=f"Cover Letter — {job.company} — {job.role}",
                        recipient=job.company,
                        content=cover_letter_text,
                        applicationId=application_id,
                    )
                )
            except Exception:
                pass

        return cover_letter_text

    def _fallback_template(self, job: CanonicalJob) -> str:
        return f"""Dear Hiring Team at {job.company},

I am writing to express my enthusiastic interest in the {job.role} position. With my extensive background in spatial computing, real-time graphics, and software engineering, I am confident in my ability to deliver immediate value to your team.

Throughout my career, I have specialized in building robust, performant interactive systems and developer tools. {job.company}'s work aligns closely with my dedication to technical excellence and high-impact engineering.

Thank you for considering my application. I look forward to the possibility of discussing how my experience can contribute to {job.company}'s goals.

Sincerely,
{self.profile.identity.name}
{self.profile.identity.email}
"""
