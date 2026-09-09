import json
from typing import Optional
from packages.domain.enums import Recommendation
from packages.domain.models import CandidateProfileModel, CanonicalJob, MatchScorecard
from packages.llm.base import LLMMessage
from packages.llm.gateway import LLMGateway

SYSTEM_PROMPT = """You are an expert AI Career Strategist and Technical Recruiter evaluating job postings for a senior technical professional.
You must compare the job requirements against the CandidateProfile accurately, objectively, and conservatively.

CRITICAL RULES:
1. NEVER hallucinate candidate qualifications. Only evaluate against what is explicitly stated in the profile.
2. Produce a fair, realistic match score from 0 to 100.
3. Classify recommendation as "APPLY", "PREPARE", or "IGNORE" based on the fit.
4. Output MUST be valid JSON adhering exactly to the specified JSON schema.

JSON OUTPUT SCHEMA:
{
  "score": <int 0-100>,
  "recommendation": "APPLY" | "PREPARE" | "IGNORE",
  "confidence": <float 0.0-1.0>,
  "strengths": ["<strength 1>", ...],
  "gaps": ["<gap 1>", ...],
  "hard_requirements": ["<hard requirement 1>", ...],
  "preferred_requirements": ["<preferred requirement 1>", ...],
  "matched_skills": ["<matched skill 1>", ...],
  "missing_skills": ["<missing skill 1>", ...],
  "seniority_fit": "<fit summary>",
  "location_fit": "<location summary>",
  "salary_fit": "<salary summary>",
  "domain_fit": "<domain summary>",
  "why_this_is_interesting": "<rationale>",
  "risks": ["<risk 1>", ...]
}
"""


class MatchEngine:
    def __init__(self, llm_gateway: Optional[LLMGateway] = None):
        self.gateway = llm_gateway or LLMGateway.get()

    async def evaluate(
        self,
        job: CanonicalJob,
        profile: CandidateProfileModel
    ) -> MatchScorecard:
        user_prompt = f"""
Candidate Profile:
- Name: {profile.identity.name}
- Target Roles: {", ".join(profile.job_preferences.roles)}
- Tech Interests: {", ".join(profile.job_preferences.interests)}
- Locations: {", ".join(profile.job_preferences.locations)}
- Remote Preferred: {profile.job_preferences.remote}
- Hybrid: {profile.job_preferences.hybrid}
- Min Salary: {profile.job_preferences.minimum_salary}
- Visa EU: {profile.job_preferences.visa_requirements.authorized_eu} (Requires sponsorship EU: {profile.job_preferences.visa_requirements.requires_sponsorship_eu})
- Visa US: {profile.job_preferences.visa_requirements.authorized_us} (Requires sponsorship US: {profile.job_preferences.visa_requirements.requires_sponsorship_us})

Job Details:
- Company: {job.company}
- Role: {job.role}
- Location: {job.location} (Remote: {job.is_remote})
- Salary: {job.salary_min} - {job.salary_max} {job.salary_currency}
- Technologies: {", ".join(job.technologies)}

Description:
{job.description[:4000]}
"""

        messages = [
            LLMMessage(role="system", content=SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]

        response = await self.gateway.generate(messages, temperature=0.1, response_format="json")

        try:
            parsed = json.loads(response.content)
            # Reconcile recommendation against candidate profile thresholds
            score = int(parsed.get("score", 0))
            if score >= profile.application_preferences.auto_apply_threshold:
                rec = Recommendation.APPLY
            elif score >= profile.application_preferences.prepare_threshold:
                rec = Recommendation.PREPARE
            else:
                rec = Recommendation.IGNORE

            return MatchScorecard(
                score=score,
                recommendation=rec,
                confidence=float(parsed.get("confidence", 0.9)),
                strengths=parsed.get("strengths", []),
                gaps=parsed.get("gaps", []),
                hard_requirements=parsed.get("hard_requirements", []),
                preferred_requirements=parsed.get("preferred_requirements", []),
                matched_skills=parsed.get("matched_skills", []),
                missing_skills=parsed.get("missing_skills", []),
                seniority_fit=parsed.get("seniority_fit", ""),
                location_fit=parsed.get("location_fit", ""),
                salary_fit=parsed.get("salary_fit", ""),
                domain_fit=parsed.get("domain_fit", ""),
                why_this_is_interesting=parsed.get("why_this_is_interesting", ""),
                risks=parsed.get("risks", []),
            )
        except Exception:
            # Safe fallback if parsing fails
            return MatchScorecard(
                score=50,
                recommendation=Recommendation.IGNORE,
                confidence=0.5,
                strengths=["Unable to parse complete LLM scorecard"],
                gaps=["Evaluation parsing error"],
                risks=["Malformed response from evaluator"],
            )
