"""
InfoJobs API application adapter.

Unlike the other adapters this one never touches a browser: InfoJobs exposes
POST /api/4/offer/{offerId}/application, so the whole submission is an HTTP call.
It needs a candidate access token with the my_applications scope, plus the cv scope
to look up which curriculum to attach.
"""

import json
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from config.settings import settings
from packages.domain.models import CandidateProfileModel, CanonicalJob
from packages.job_sources.infojobs import InfoJobsAuthError, InfoJobsClient
from packages.llm.base import LLMMessage
from packages.llm.gateway import LLMGateway

COVER_LETTER_NAME_LIMIT = 100
COVER_LETTER_TEXT_LIMIT = 4000

KILLER_QUESTION_PROMPT = """You are answering the screening questions of a Spanish job application
on behalf of a candidate. The questions are multiple choice and usually written in Spanish.

CRITICAL RULES:
1. Choose the answer that is truthful for the candidate profile provided. Never overstate experience.
2. If no option is truthful, or the profile does not contain the information, return null for that question.
3. Answer with the exact answer id given in the options, never with the answer text.
4. Output MUST be valid JSON adhering exactly to the specified JSON schema.

JSON OUTPUT SCHEMA:
{
  "answers": [
    {"id": <question id>, "answerId": <chosen answer id or null>, "confidence": <float 0.0-1.0>}
  ]
}
"""

OPEN_QUESTION_PROMPT = """You are answering the open questions of a Spanish job application on behalf
of a candidate. Answer in the language of the question, in at most three sentences per answer.

CRITICAL RULES:
1. Only state facts supported by the candidate profile. Never invent experience, studies or salary.
2. If the profile does not support an answer, return null for that question.
3. Output MUST be valid JSON adhering exactly to the specified JSON schema.

JSON OUTPUT SCHEMA:
{
  "answers": [
    {"id": <question id>, "answer": "<text or null>", "confidence": <float 0.0-1.0>}
  ]
}
"""


class InfoJobsApplicationResult(BaseModel):
    submitted: bool
    application_code: Optional[str] = None
    curriculum_name: Optional[str] = None
    has_cover_letter: bool = False
    applied_at: Optional[str] = None
    unanswered_questions: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class InfoJobsApiAdapter:
    CURRICULUM_PATH = "2/curriculum"
    KILLER_QUESTION_PATH = "1/offer/{offer_id}/killerquestion"
    OPEN_QUESTION_PATH = "1/offer/{offer_id}/openquestion"
    APPLICATION_PATH = "4/offer/{offer_id}/application"
    SCOPES = ["MY_APPLICATIONS", "CV"]
    ANSWER_CONFIDENCE_THRESHOLD = 0.7

    def __init__(
        self,
        client: Optional[InfoJobsClient] = None,
        llm_gateway: Optional[LLMGateway] = None,
    ):
        self.client = client or InfoJobsClient()
        self.gateway = llm_gateway or LLMGateway.get()

    def can_handle(self, job: CanonicalJob) -> bool:
        """InfoJobs offers that redirect to an external form still need the browser path."""
        if job.source.value != "infojobs":
            return False
        if not (self.client.is_configured and self.client.has_user_token):
            return False
        return "infojobs.net" in (job.apply_url or "")

    async def resolve_curriculum_code(self) -> Optional[str]:
        """Picks the CV to attach: the configured one, else the candidate's primary CV."""
        if settings.infojobs_curriculum_code:
            return settings.infojobs_curriculum_code

        payload = await self.client.get(self.CURRICULUM_PATH, require_user_token=True)
        if not isinstance(payload, list) or not payload:
            return None

        for cv in payload:
            if cv.get("principal") and cv.get("code"):
                return cv["code"]
        for cv in payload:
            if cv.get("completed") and cv.get("code"):
                return cv["code"]
        return payload[0].get("code")

    async def apply(
        self,
        job: CanonicalJob,
        profile: CandidateProfileModel,
        cover_letter_text: str = "",
        curriculum_code: Optional[str] = None,
    ) -> InfoJobsApplicationResult:
        offer_id = job.source_job_id
        try:
            code = curriculum_code or await self.resolve_curriculum_code()
        except InfoJobsAuthError as exc:
            return InfoJobsApplicationResult(submitted=False, error=str(exc))
        except Exception as exc:
            return InfoJobsApplicationResult(
                submitted=False, error=f"Could not resolve InfoJobs CV: {exc}"
            )

        body: Dict[str, Any] = {}
        if code:
            body["curriculumCode"] = code
        if cover_letter_text:
            body["coverLetter"] = self._build_cover_letter(job, cover_letter_text)

        try:
            killer, killer_pending = await self._resolve_killer_questions(offer_id, job, profile)
            open_answers, open_pending = await self._resolve_open_questions(offer_id, job, profile)
        except InfoJobsAuthError as exc:
            return InfoJobsApplicationResult(submitted=False, error=str(exc))

        pending = killer_pending + open_pending
        if pending:
            return InfoJobsApplicationResult(
                submitted=False,
                unanswered_questions=pending,
                error="Application needs answers the candidate profile does not cover.",
            )

        if killer:
            body["offerKillerQuestions"] = killer
        if open_answers:
            body["offerOpenQuestions"] = open_answers

        try:
            payload = await self.client.post(
                self.APPLICATION_PATH.format(offer_id=offer_id), json_body=body
            )
        except InfoJobsAuthError as exc:
            return InfoJobsApplicationResult(submitted=False, error=str(exc))
        except Exception as exc:
            return InfoJobsApplicationResult(submitted=False, error=f"InfoJobs rejected the application: {exc}")

        if not isinstance(payload, dict) or not payload.get("code"):
            return InfoJobsApplicationResult(
                submitted=False, error="InfoJobs returned no application code."
            )

        return InfoJobsApplicationResult(
            submitted=True,
            application_code=payload.get("code"),
            curriculum_name=payload.get("cv"),
            has_cover_letter=bool(payload.get("hasCoverLetter")),
            applied_at=payload.get("date"),
        )

    @staticmethod
    def _build_cover_letter(job: CanonicalJob, text: str) -> Dict[str, Any]:
        name = f"{job.role} - {job.company}"[:COVER_LETTER_NAME_LIMIT]
        return {
            "name": name,
            "text": text.replace("\r\n", "\n")[:COVER_LETTER_TEXT_LIMIT],
            "main": False,
            "doSave": False,
        }

    async def _resolve_killer_questions(
        self,
        offer_id: str,
        job: CanonicalJob,
        profile: CandidateProfileModel,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        questions = await self._fetch_questions(self.KILLER_QUESTION_PATH, offer_id)
        if not questions:
            return [], []

        rendered = [
            {
                "id": q.get("id"),
                "question": q.get("question", ""),
                "options": [
                    {"answerId": a.get("id"), "answer": a.get("answer", "")}
                    for a in (q.get("answers") or [])
                ],
            }
            for q in questions
            if q.get("id")
        ]
        parsed = await self._ask_llm(KILLER_QUESTION_PROMPT, rendered, job, profile)

        answers: List[Dict[str, Any]] = []
        pending: List[str] = []
        by_id = {item["id"]: item for item in rendered}

        for item in parsed:
            question = by_id.get(item.get("id"))
            if not question:
                continue
            answer_id = item.get("answerId")
            valid_ids = {option["answerId"] for option in question["options"]}
            confident = float(item.get("confidence") or 0.0) >= self.ANSWER_CONFIDENCE_THRESHOLD
            if answer_id in valid_ids and confident:
                answers.append({"id": question["id"], "answerId": answer_id})
            else:
                pending.append(question["question"])

        answered_ids = {answer["id"] for answer in answers}
        pending.extend(q["question"] for q in rendered if q["id"] not in answered_ids and q["question"] not in pending)
        return answers, pending

    async def _resolve_open_questions(
        self,
        offer_id: str,
        job: CanonicalJob,
        profile: CandidateProfileModel,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        questions = await self._fetch_questions(self.OPEN_QUESTION_PATH, offer_id)
        if not questions:
            return [], []

        rendered = [
            {"id": q.get("id"), "question": q.get("question", "")}
            for q in questions
            if q.get("id")
        ]
        parsed = await self._ask_llm(OPEN_QUESTION_PROMPT, rendered, job, profile)

        answers: List[Dict[str, Any]] = []
        pending: List[str] = []
        by_id = {item["id"]: item for item in rendered}

        for item in parsed:
            question = by_id.get(item.get("id"))
            if not question:
                continue
            text = item.get("answer")
            confident = float(item.get("confidence") or 0.0) >= self.ANSWER_CONFIDENCE_THRESHOLD
            if text and confident:
                answers.append({"id": question["id"], "answer": str(text).replace("\r\n", "\n")})
            else:
                pending.append(question["question"])

        answered_ids = {answer["id"] for answer in answers}
        pending.extend(q["question"] for q in rendered if q["id"] not in answered_ids and q["question"] not in pending)
        return answers, pending

    async def _fetch_questions(self, path_template: str, offer_id: str) -> List[Dict[str, Any]]:
        try:
            payload = await self.client.get(
                path_template.format(offer_id=offer_id), require_user_token=True
            )
        except InfoJobsAuthError:
            raise
        except Exception:
            return []
        return payload if isinstance(payload, list) else []

    async def _ask_llm(
        self,
        system_prompt: str,
        questions: List[Dict[str, Any]],
        job: CanonicalJob,
        profile: CandidateProfileModel,
    ) -> List[Dict[str, Any]]:
        prefs = profile.job_preferences
        user_prompt = f"""
Candidate Profile:
- Name: {profile.identity.name}
- Location: {profile.identity.location}
- Target Roles: {", ".join(prefs.roles)}
- Tech Interests: {", ".join(prefs.interests)}
- Minimum Salary: {prefs.minimum_salary} | Preferred: {prefs.preferred_salary}
- Willing to relocate: {prefs.relocation}
- Work Authorisation: EU={prefs.visa_requirements.authorized_eu}, US={prefs.visa_requirements.authorized_us}

Job: {job.role} at {job.company} ({job.location})

Questions:
{json.dumps(questions, ensure_ascii=False, indent=2)}
"""
        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt),
        ]

        try:
            response = await self.gateway.generate(messages, temperature=0.1, response_format="json")
            parsed = json.loads(response.content)
        except Exception:
            return []

        answers = parsed.get("answers")
        return [item for item in answers if isinstance(item, dict)] if isinstance(answers, list) else []
