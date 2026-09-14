import json
from typing import List, Optional
from packages.domain.models import CandidateProfileModel, SearchPlan, SearchPlanEntry
from packages.llm.base import LLMMessage
from packages.llm.gateway import LLMGateway

SYSTEM_PROMPT = """You are a Job Search Strategist planning the queries an automated job agent will run
against public job boards (Greenhouse, Lever, Ashby and company career pages).

Your job is to translate a candidate profile into concrete, high-yield search queries.

CRITICAL RULES:
1. Every query must be a short keyword phrase a job board would match against a job title or description
   (2 to 4 words). Never write a sentence, a boolean expression or a location inside the query string.
2. Cover the candidate's distinct specialisations rather than repeating one theme with synonyms.
3. Prefer the vocabulary employers actually use in postings over the candidate's own job titles.
4. Use the feedback about previously ignored roles to steer away from mismatched queries, and the
   feedback about previously interesting roles to double down on what works.
5. Never invent skills or domains the candidate profile does not support.
6. Output MUST be valid JSON adhering exactly to the specified JSON schema.

JSON OUTPUT SCHEMA:
{
  "queries": [
    {
      "query": "<2-4 keyword phrase>",
      "locations": ["<location 1>", ...],
      "remote": <true|false>,
      "rationale": "<why this query fits the candidate>"
    }
  ],
  "notes": "<short summary of the strategy>"
}
"""


class SearchPlannerAgent:
    """Turns the candidate profile into the set of queries a discovery cycle should run."""

    def __init__(self, llm_gateway: Optional[LLMGateway] = None):
        self.gateway = llm_gateway or LLMGateway.get()

    async def plan(
        self,
        profile: CandidateProfileModel,
        ignored_titles: Optional[List[str]] = None,
        promising_titles: Optional[List[str]] = None,
    ) -> SearchPlan:
        max_queries = max(1, profile.discovery.max_queries_per_cycle)

        if not profile.discovery.use_llm_planner:
            return self.fallback_plan(profile)

        user_prompt = self._build_user_prompt(profile, ignored_titles, promising_titles, max_queries)
        messages = [
            LLMMessage(role="system", content=SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]

        try:
            response = await self.gateway.generate(messages, temperature=0.4, response_format="json")
            plan = self._parse_plan(response.content, profile, max_queries)
        except Exception:
            plan = None

        if plan is None or not plan.entries:
            return self.fallback_plan(profile)
        return plan

    def fallback_plan(self, profile: CandidateProfileModel) -> SearchPlan:
        """Deterministic plan used when no LLM is configured or its answer is unusable."""
        max_queries = max(1, profile.discovery.max_queries_per_cycle)
        prefs = profile.job_preferences

        terms: List[str] = []
        for term in list(profile.discovery.seed_queries) + list(prefs.roles) + list(prefs.interests):
            cleaned = term.strip()
            if cleaned and cleaned.lower() not in {t.lower() for t in terms}:
                terms.append(cleaned)

        entries = [
            SearchPlanEntry(
                query=term,
                locations=list(prefs.locations),
                remote=True if prefs.remote else None,
                rationale="Derived from the configured candidate profile.",
            )
            for term in terms[:max_queries]
        ]
        return SearchPlan(
            entries=entries,
            generated_by="fallback",
            notes="Seed queries, target roles and interests taken directly from the profile.",
        )

    def _build_user_prompt(
        self,
        profile: CandidateProfileModel,
        ignored_titles: Optional[List[str]],
        promising_titles: Optional[List[str]],
        max_queries: int,
    ) -> str:
        prefs = profile.job_preferences
        app_prefs = profile.application_preferences
        return f"""
Candidate Profile:
- Target Roles: {", ".join(prefs.roles) or "not specified"}
- Tech Interests: {", ".join(prefs.interests) or "not specified"}
- Locations: {", ".join(prefs.locations) or "not specified"}
- Remote: {prefs.remote} | Hybrid: {prefs.hybrid} | Onsite: {prefs.onsite}
- Relocation: {prefs.relocation}
- Minimum Salary: {prefs.minimum_salary} {"/".join(prefs.currencies)}
- Work Authorisation: EU={prefs.visa_requirements.authorized_eu}, US={prefs.visa_requirements.authorized_us}
- Excluded Roles: {", ".join(app_prefs.excluded_roles) or "none"}
- Excluded Companies: {", ".join(app_prefs.excluded_companies) or "none"}

Seed queries already configured by the candidate:
{", ".join(profile.discovery.seed_queries) or "none"}

Roles the agent recently discarded as a poor match:
{", ".join(ignored_titles or []) or "none recorded yet"}

Roles the agent recently rated as a good match:
{", ".join(promising_titles or []) or "none recorded yet"}

Produce at most {max_queries} queries, ordered from highest to lowest expected yield.
"""

    def _parse_plan(
        self,
        content: str,
        profile: CandidateProfileModel,
        max_queries: int,
    ) -> Optional[SearchPlan]:
        parsed = json.loads(content)
        raw_queries = parsed.get("queries")
        if not isinstance(raw_queries, list):
            return None

        default_locations = list(profile.job_preferences.locations)
        entries: List[SearchPlanEntry] = []
        seen: set[str] = set()

        for item in raw_queries:
            if not isinstance(item, dict):
                continue
            query = str(item.get("query", "")).strip()
            if not query or query.lower() in seen:
                continue
            seen.add(query.lower())

            locations = item.get("locations")
            if not isinstance(locations, list) or not locations:
                locations = default_locations

            remote = item.get("remote")
            entries.append(
                SearchPlanEntry(
                    query=query,
                    locations=[str(loc) for loc in locations],
                    remote=bool(remote) if isinstance(remote, bool) else None,
                    rationale=str(item.get("rationale", "")),
                )
            )
            if len(entries) >= max_queries:
                break

        if not entries:
            return None

        return SearchPlan(
            entries=entries,
            generated_by="llm",
            notes=str(parsed.get("notes", "")),
        )
