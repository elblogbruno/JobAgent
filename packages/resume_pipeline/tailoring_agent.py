"""Tailoring a CV to one job, without inventing anything.

The rule that shapes this module: a tailored CV may only re-emphasise what the
master CV already says. It may reorder, reword and foreground. It may not add a
technology, an employer, a date or a metric that is not already there. Everything
the model proposes is checked against the master before it is applied, field by
field, and anything that fails is dropped rather than the whole patch.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from packages.candidate_profile.guard import HallucinationGuard
from packages.domain.models import CandidateProfileModel, CanonicalJob, MatchScorecard
from packages.llm.base import LLMMessage
from packages.llm.gateway import LLMGateway
from packages.reactive_resume.models import ResumeData
from packages.role_discovery.lexicon import CAPABILITY_LEXICON

TAILORING_SYSTEM_PROMPT = """You rewrite a candidate's master CV so it speaks directly to one job
posting. You are editing an existing document, not writing a new one.

ABSOLUTE RULES:
1. Never add a technology, tool, employer, job title, qualification, date or metric that is not
   already in the master CV. If the job asks for something the candidate does not have, leave it
   out. A CV that quietly acquires the job's requirements is a lie and will be rejected.
2. Every number, percentage and duration in your output must already appear in the passage you are
   rewriting.
3. You may reorder, reword, shorten, and move the most relevant evidence to the front. That is the
   entire job.
4. Keep the candidate's voice. Do not add adjectives they did not earn. No "passionate", no
   "world-class", no filler.
5. The headline is at most 90 characters and names what the candidate is, framed for this role.
6. The summary is 2 to 4 sentences of plain text, leading with the evidence this posting cares
   about most.
7. For each experience entry you rewrite, keep the same facts and reorder the emphasis. Return the
   entry index exactly as given. Skip entries that need no change.

Output MUST be valid JSON matching the schema exactly, with no prose around it.

JSON OUTPUT SCHEMA:
{
  "headline": "<tailored headline>",
  "summary": "<tailored summary, plain text>",
  "experience": [
    {"index": <int>, "summary": "<rewritten entry, keeping every fact>"}
  ],
  "skill_priority": ["<skill name exactly as it appears in the master CV>", ...],
  "reasoning": "<one sentence on what you foregrounded and why>"
}
"""

# Technology names the guard knows how to spot in free text. Drawn from the same
# lexicon role discovery uses, so both halves of the system agree on vocabulary.
_TECH_TERMS: List[Tuple[str, Tuple[str, ...]]] = [
    (entry.label, entry.aliases)
    for entry in CAPABILITY_LEXICON
    if entry.kind.value in ("technology", "capability")
]


class TailoringPlan(BaseModel):
    """What will actually be applied to the duplicated CV."""

    headline: Optional[str] = None
    summary: Optional[str] = None
    experience: Dict[int, str] = Field(default_factory=dict)
    skill_priority: List[str] = Field(default_factory=list)
    reasoning: str = ""
    generated_by: str = "heuristic"  # llm | heuristic
    rejected: List[str] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.headline or self.summary or self.experience or self.skill_priority)


class ResumeTailoringAgent:
    """Produces a validated TailoringPlan for one job."""

    def __init__(self, llm_gateway: Optional[LLMGateway] = None):
        self.gateway = llm_gateway or LLMGateway.get()

    async def build_plan(
        self,
        master: ResumeData,
        job: CanonicalJob,
        profile: CandidateProfileModel,
        scorecard: Optional[MatchScorecard] = None,
        use_llm: bool = True,
    ) -> TailoringPlan:
        guard = HallucinationGuard(profile=profile, master_resume_data=master)
        entries = _experience_entries(master)

        if use_llm:
            try:
                response = await self.gateway.generate(
                    [
                        LLMMessage(role="system", content=TAILORING_SYSTEM_PROMPT),
                        LLMMessage(
                            role="user",
                            content=self._prompt(master, job, scorecard, entries),
                        ),
                    ],
                    temperature=0.3,
                    response_format="json",
                )
                plan = self._parse(response.content, master, guard, entries)
                if plan is not None and not plan.is_empty:
                    return plan
            except Exception:
                pass

        return self.heuristic_plan(master, job, scorecard)

    # -- prompt ------------------------------------------------------------

    def _prompt(
        self,
        master: ResumeData,
        job: CanonicalJob,
        scorecard: Optional[MatchScorecard],
        entries: List[Dict[str, Any]],
    ) -> str:
        experience = "\n".join(
            f"[{entry['index']}] {entry['position']} at {entry['company']} ({entry['date']})\n"
            f"    {entry['summary'][:700]}"
            for entry in entries
        )
        skills = ", ".join(_skill_names(master)) or "none listed"
        strengths = ", ".join(scorecard.strengths[:6]) if scorecard else ""
        gaps = ", ".join(scorecard.gaps[:4]) if scorecard else ""

        return f"""THE JOB
{job.role} at {job.company}{f" ({job.location})" if job.location else ""}
Technologies named in the posting: {", ".join(job.technologies) or "none extracted"}
Requirements: {"; ".join(job.requirements[:8]) or "not itemised"}

Description:
{job.description[:3500]}

WHY THIS CANDIDATE FITS, ACCORDING TO THE MATCH ANALYSIS
Strengths: {strengths or "not assessed"}
Gaps (do NOT paper over these): {gaps or "none recorded"}

THE MASTER CV YOU ARE EDITING
Current headline: {master.basics.headline or "none"}
Current summary: {_summary_text(master)[:800] or "none"}

Skills listed: {skills}

Experience entries:
{experience or "none"}
"""

    # -- parsing and validation -------------------------------------------

    def _parse(
        self,
        content: str,
        master: ResumeData,
        guard: HallucinationGuard,
        entries: List[Dict[str, Any]],
    ) -> Optional[TailoringPlan]:
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            return None

        plan = TailoringPlan(generated_by="llm", reasoning=str(parsed.get("reasoning", "")))
        by_index = {entry["index"]: entry for entry in entries}
        master_corpus = _master_corpus(master)

        headline = _clean(parsed.get("headline"))
        if headline:
            violations = guard.verify_no_invented_technologies(headline, master_corpus)
            if violations:
                plan.rejected.append("headline: " + "; ".join(violations))
            else:
                plan.headline = headline[:90]

        summary = _clean(parsed.get("summary"))
        if summary:
            violations = guard.verify_no_invented_technologies(summary, master_corpus)
            violations += guard.verify_tailored_bullets([summary], [_summary_text(master)])
            if violations:
                plan.rejected.append("summary: " + "; ".join(violations))
            else:
                plan.summary = summary

        for item in parsed.get("experience") or []:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index"))
            except (TypeError, ValueError):
                continue
            entry = by_index.get(index)
            rewritten = _clean(item.get("summary"))
            if entry is None or not rewritten:
                continue

            original = entry["summary"]
            violations = guard.verify_no_invented_technologies(rewritten, master_corpus)
            violations += guard.verify_tailored_bullets([rewritten], [original])
            if violations:
                plan.rejected.append(f"experience[{index}]: " + "; ".join(violations))
                continue
            plan.experience[index] = rewritten

        known_skills = {name.lower(): name for name in _skill_names(master)}
        for raw in parsed.get("skill_priority") or []:
            name = str(raw).strip()
            if name.lower() in known_skills and name not in plan.skill_priority:
                plan.skill_priority.append(known_skills[name.lower()])

        return plan

    # -- deterministic fallback -------------------------------------------

    def heuristic_plan(
        self,
        master: ResumeData,
        job: CanonicalJob,
        scorecard: Optional[MatchScorecard] = None,
    ) -> TailoringPlan:
        """Tailors without a model, using only the overlap that genuinely exists.

        The headline names the role and the technologies the candidate really has
        that this posting actually asks for. If there is no overlap, the headline
        is left alone: a headline claiming relevance that is not there is worse
        than the original.
        """
        overlap = _shared_technologies(master, job, scorecard)
        plan = TailoringPlan(generated_by="heuristic")

        if overlap:
            suffix = " · ".join(overlap[:3])
            headline = f"{job.normalized_role} · {suffix}"
            plan.headline = headline[:90]
            plan.reasoning = (
                "Headline points at the role and the overlapping technologies already "
                "evidenced in the master CV."
            )
        else:
            plan.reasoning = "No technology overlap found, so the master headline stands."

        plan.skill_priority = _prioritised_skills(master, job, scorecard)
        return plan


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _clean(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = re.sub(r"\s+", " ", value).strip()
    return "" if text.lower() in ("null", "none") else text


def _summary_text(master: ResumeData) -> str:
    section = (master.sections or {}).get("summary")
    if isinstance(section, dict):
        return re.sub(r"<[^>]+>", " ", str(section.get("content") or "")).strip()
    return ""


def _experience_entries(master: ResumeData) -> List[Dict[str, Any]]:
    section = (master.sections or {}).get("experience")
    items = section.get("items") if isinstance(section, dict) else None
    if not isinstance(items, list):
        return []

    entries: List[Dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        entries.append(
            {
                "index": index,
                "company": str(item.get("company", "")),
                "position": str(item.get("position", "")),
                "date": str(item.get("date", "")),
                "summary": re.sub(r"<[^>]+>", " ", str(item.get("summary") or "")).strip(),
            }
        )
    return entries


def _skill_names(master: ResumeData) -> List[str]:
    section = (master.sections or {}).get("skills")
    items = section.get("items") if isinstance(section, dict) else None
    if not isinstance(items, list):
        return []
    return [
        str(item.get("name", "")).strip()
        for item in items
        if isinstance(item, dict) and item.get("name")
    ]


def _master_corpus(master: ResumeData) -> str:
    """Everything the master CV says, lowercased, for containment checks."""
    parts = [
        master.basics.headline or "",
        master.basics.name or "",
        _summary_text(master),
    ]
    for entry in _experience_entries(master):
        parts.extend([entry["company"], entry["position"], entry["summary"]])
    parts.extend(_skill_names(master))

    section = (master.sections or {}).get("skills")
    if isinstance(section, dict):
        for item in section.get("items") or []:
            if isinstance(item, dict):
                parts.extend(str(kw) for kw in item.get("keywords") or [])

    for key in ("projects", "education", "certifications", "awards"):
        block = (master.sections or {}).get(key)
        if isinstance(block, dict):
            for item in block.get("items") or []:
                if isinstance(item, dict):
                    parts.extend(
                        str(item.get(field) or "")
                        for field in ("name", "description", "summary", "institution", "studyType")
                    )
                    parts.extend(str(kw) for kw in item.get("keywords") or [])

    return re.sub(r"<[^>]+>", " ", " ".join(parts)).lower()


def technologies_in(text: str) -> List[str]:
    """Technology and capability terms the lexicon can recognise in free text."""
    lowered = text.lower()
    found: List[str] = []
    for label, aliases in _TECH_TERMS:
        for alias in aliases:
            token = alias.strip()
            if not token:
                continue
            pattern = rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9+#])"
            if re.search(pattern, lowered):
                found.append(label)
                break
    return found


def _shared_technologies(
    master: ResumeData,
    job: CanonicalJob,
    scorecard: Optional[MatchScorecard],
) -> List[str]:
    """Technologies the posting wants that the master CV actually evidences."""
    corpus = _master_corpus(master)
    mine = set(technologies_in(corpus))
    mine.update(name for name in _skill_names(master))

    # Only what the POSTING asks for. The scorecard's matched skills qualify
    # because "matched" already means the job asked and the candidate has it;
    # its strengths do not, since they describe the candidate alone.
    wanted: List[str] = list(job.technologies)
    if scorecard:
        wanted.extend(scorecard.matched_skills)
    wanted.extend(technologies_in(f"{job.role} {job.description[:4000]}"))

    overlap: List[str] = []
    for term in wanted:
        cleaned = str(term).strip()
        if not cleaned or len(cleaned) > 24:
            continue
        match = next((own for own in mine if own.lower() == cleaned.lower()), None)
        if match is None and cleaned.lower() in corpus:
            match = cleaned
        if match and match not in overlap:
            overlap.append(match)
    return overlap


def _prioritised_skills(
    master: ResumeData,
    job: CanonicalJob,
    scorecard: Optional[MatchScorecard],
) -> List[str]:
    """Master skills ordered so the ones this posting asks about come first."""
    names = _skill_names(master)
    if not names:
        return []
    wanted = " ".join(
        list(job.technologies)
        + (scorecard.matched_skills if scorecard else [])
        + [job.role, job.description[:2000]]
    ).lower()

    relevant = [name for name in names if name.lower() in wanted]
    rest = [name for name in names if name not in relevant]
    return relevant + rest if relevant else []
