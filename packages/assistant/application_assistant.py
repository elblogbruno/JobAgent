"""Answering the questions an application form asks, grounded in the candidate.

This is not a general chatbot. It answers as the candidate, from the candidate's
own CV, profile and the job on screen, and it says plainly when it is guessing.
Facts it cannot support are refused rather than invented, because the answer goes
into a real application under the candidate's name.
"""

import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from packages.candidate_profile.answer_vault import CandidateAnswerVault
from packages.candidate_profile.guard import HallucinationGuard
from packages.candidate_profile.profile import CandidateProfileLoader
from packages.domain.models import CandidateProfileModel
from packages.llm.base import LLMMessage
from packages.llm.gateway import LLMGateway
from packages.persistence.repositories import JobRepository
from packages.reactive_resume.client import ReactiveResumeClient
from packages.role_discovery.resume_digest import build_resume_digest

ASSISTANT_SYSTEM_PROMPT = """You help one candidate fill in a job application. You are given their
CV, their stated preferences, and the posting they are applying to. You answer as their assistant,
drafting text they will paste into a form.

RULES:
1. Only use what the candidate's CV and profile actually say. Never invent an employer, a
   technology, a qualification, a date or a number. If the form asks for something not in the
   material, say what is missing and ask them for it rather than making it up.
2. Draft answers in the first person, as the candidate, ready to paste. No preamble, no "here is
   a possible answer", no closing offer.
3. Match the length the form implies. A one-line field gets one line. "Why do you want to work
   here" gets a short paragraph, not an essay.
4. Keep their register: direct, concrete, no corporate filler. Never write "passionate",
   "synergy", "world-class" or "rockstar".
5. Where the honest answer is weak, say so in `caveats` rather than dressing it up. The candidate
   decides what to send.

Output MUST be valid JSON matching the schema exactly.

JSON OUTPUT SCHEMA:
{
  "answer": "<the text to paste, or the explanation if no answer is possible>",
  "confidence": <0.0-1.0>,
  "caveats": ["<anything the candidate should check or fill in themselves>"],
  "missing": ["<facts the material does not contain>"]
}
"""


class AssistantAnswer(BaseModel):
    answer: str
    source: str = "model"  # vault | model | error
    confidence: float = 0.5
    caveats: List[str] = Field(default_factory=list)
    missing: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    canonical_key: str = ""
    grounded_on: List[str] = Field(default_factory=list)

    def to_api_dict(self) -> Dict[str, Any]:
        return {
            "answer": self.answer,
            "source": self.source,
            "confidence": round(self.confidence, 2),
            "caveats": self.caveats,
            "missing": self.missing,
            "warnings": self.warnings,
            "canonicalKey": self.canonical_key,
            "groundedOn": self.grounded_on,
        }


class ChatTurn(BaseModel):
    role: str  # user | assistant
    content: str


class ApplicationAssistant:
    def __init__(
        self,
        session: AsyncSession,
        profile: Optional[CandidateProfileModel] = None,
        rr_client: Optional[ReactiveResumeClient] = None,
        llm_gateway: Optional[LLMGateway] = None,
    ):
        self.session = session
        self.profile = profile or CandidateProfileLoader.get()
        self.rr_client = rr_client
        self.gateway = llm_gateway or LLMGateway.get()
        self.vault = CandidateAnswerVault(session)
        self.job_repo = JobRepository(session)

    async def answer(
        self,
        question: str,
        job_id: Optional[str] = None,
        page_context: str = "",
        history: Optional[List[ChatTurn]] = None,
    ) -> AssistantAnswer:
        question = (question or "").strip()
        if not question:
            return AssistantAnswer(
                answer="Ask me about a field on the form and I will draft it.",
                source="error",
                confidence=0.0,
            )

        # A question the vault already knows is answered the same way every time,
        # which is both faster and more consistent than asking a model again.
        stored = await self._from_vault(question)
        if stored is not None:
            return stored

        resume_digest = await self._resume_digest()
        job = await self.job_repo.get_by_id(job_id) if job_id else None
        grounded = ["candidate profile"]
        if resume_digest:
            grounded.append("master CV")
        if job is not None:
            grounded.append(f"{job.company} — {job.role}")

        try:
            response = await self.gateway.generate(
                [
                    LLMMessage(role="system", content=ASSISTANT_SYSTEM_PROMPT),
                    *[
                        LLMMessage(role=turn.role, content=turn.content)
                        for turn in (history or [])[-6:]
                    ],
                    LLMMessage(
                        role="user",
                        content=self._prompt(question, resume_digest, job, page_context),
                    ),
                ],
                temperature=0.3,
                response_format="json",
            )
            parsed = json.loads(response.content)
        except Exception as exc:
            return AssistantAnswer(
                answer=f"I could not reach the model: {exc}",
                source="error",
                confidence=0.0,
                grounded_on=grounded,
            )

        if not isinstance(parsed, dict) or not str(parsed.get("answer", "")).strip():
            return AssistantAnswer(
                answer="I could not draft an answer for that. Try rephrasing the field.",
                source="error",
                confidence=0.0,
                grounded_on=grounded,
            )

        answer = AssistantAnswer(
            answer=str(parsed["answer"]).strip(),
            source="model",
            confidence=_clamp(parsed.get("confidence"), 0.6),
            caveats=[str(c) for c in (parsed.get("caveats") or [])][:5],
            missing=[str(m) for m in (parsed.get("missing") or [])][:5],
            grounded_on=grounded,
        )

        # The draft goes into a real application, so the same guard that protects
        # the CV checks it for technologies the candidate cannot claim.
        if resume_digest:
            guard = HallucinationGuard(profile=self.profile, master_resume_data=None)
            corpus = f"{resume_digest} {_profile_corpus(self.profile)}".lower()
            answer.warnings = guard.verify_no_invented_technologies(answer.answer, corpus)

        return answer

    async def _from_vault(self, question: str) -> Optional[AssistantAnswer]:
        try:
            value, confidence, key = await self.vault.resolve(question, self.profile)
        except Exception:
            return None
        if value is None or not key:
            return None

        rendered = value
        if isinstance(value, bool):
            rendered = "Yes" if value else "No"

        return AssistantAnswer(
            answer=str(rendered),
            source="vault",
            confidence=confidence,
            canonical_key=key,
            grounded_on=["answer vault"],
            caveats=[]
            if confidence >= 0.95
            else ["Derived from your profile rather than a confirmed answer."],
        )

    async def save_answer(self, question: str, answer: str) -> Optional[str]:
        """Stores a confirmed answer so the same field is instant next time."""
        key = CandidateAnswerVault.identify_canonical_key(question)
        if not key or self.vault.repo is None:
            return None
        await self.vault.repo.upsert_answer(
            canonical_key=key,
            answer=answer,
            source="user",
            confidence=1.0,
            raw_question=question,
        )
        return key

    def _prompt(
        self,
        question: str,
        resume_digest: str,
        job,
        page_context: str,
    ) -> str:
        prefs = self.profile.job_preferences
        visa = prefs.visa_requirements
        job_block = "The candidate has not told me which job this is."
        if job is not None:
            job_block = f"""{job.role} at {job.company}{f" ({job.location})" if job.location else ""}
Technologies named: {", ".join(job.technologies or []) or "none extracted"}
Match score: {job.match_score if job.match_score is not None else "not scored"}

{(job.description or "")[:2500]}"""

        return f"""THE FIELD THEY ARE STUCK ON
{question}

{f"SURROUNDING TEXT FROM THE FORM{chr(10)}{page_context[:1200]}{chr(10)}" if page_context else ""}
THE JOB
{job_block}

THE CANDIDATE
Name: {self.profile.identity.name}
Based in: {self.profile.identity.location}
Locations they will work in: {", ".join(prefs.locations) or "not stated"}
Remote: {prefs.remote} | Hybrid: {prefs.hybrid} | Onsite: {prefs.onsite} | Relocation: {prefs.relocation}
Salary: minimum {prefs.minimum_salary}, preferred {prefs.preferred_salary} ({"/".join(prefs.currencies)})
Work authorisation: EU={visa.authorized_eu} (needs sponsorship: {visa.requires_sponsorship_eu}), \
US={visa.authorized_us} (needs sponsorship: {visa.requires_sponsorship_us})

THEIR CV
{resume_digest or "(CV unavailable, answer only from the profile above and say so)"}
"""

    async def _resume_digest(self) -> str:
        client = self.rr_client
        if client is None:
            try:
                client = ReactiveResumeClient()
            except Exception:
                return ""
        resume_id = self.profile.reactive_resume.master_resume_id
        if not resume_id:
            return ""
        try:
            return build_resume_digest(await client.get_resume(resume_id), max_chars=9000)
        except Exception:
            return ""


def _clamp(value: Any, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _profile_corpus(profile: CandidateProfileModel) -> str:
    prefs = profile.job_preferences
    return " ".join(list(prefs.interests) + list(prefs.roles))


__all__ = ["ApplicationAssistant", "AssistantAnswer", "ChatTurn"]
