"""Market feedback: judging search queries by the jobs they actually produced.

Volume is not the objective. A query that surfaces three excellent postings is
worth more than one that surfaces eighty mediocre ones, and these rules are
written to say so.
"""

from typing import Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from packages.domain.enums import SearchQueryStatus
from packages.domain.models import RoleDiscoveryConfig
from packages.domain.role_discovery import DiscoveredRole, JobSearchQuerySpec


class QueryAdjustment(BaseModel):
    query_id: str
    label: str
    previous_priority: int
    new_priority: int
    previous_status: SearchQueryStatus
    new_status: SearchQueryStatus
    reason: str


class MarketFeedbackReport(BaseModel):
    adjustments: List[QueryAdjustment] = Field(default_factory=list)
    proposed_roles: List[DiscoveredRole] = Field(default_factory=list)
    auto_accepted_role_ids: List[str] = Field(default_factory=list)
    summary: str = ""


def evaluate_query_performance(
    specs: Sequence[JobSearchQuerySpec],
    config: RoleDiscoveryConfig,
) -> List[QueryAdjustment]:
    """Re-prioritises and retires queries based on the jobs they produced."""
    adjustments: List[QueryAdjustment] = []

    for spec in specs:
        if spec.id is None or spec.status == SearchQueryStatus.ARCHIVED:
            continue

        stats = spec.stats
        priority = spec.priority
        status = spec.status
        reasons: List[str] = []

        has_sample = stats.scored_imports >= config.min_samples_before_demoting

        if has_sample and stats.average_match_score < config.disable_below_average_score:
            priority = max(1, priority - 40)
            status = SearchQueryStatus.DISABLED
            reasons.append(
                f"{stats.scored_imports} imports averaging {stats.average_match_score} — "
                "the query is pointed at the wrong market"
            )
        elif has_sample and stats.average_match_score < config.demote_below_average_score:
            priority = max(1, priority - 25)
            reasons.append(
                f"{stats.scored_imports} imports averaging {stats.average_match_score} — "
                "volume without quality"
            )

        if stats.scored_imports >= 3 and stats.high_match_ratio >= 0.6:
            priority = min(99, priority + 8)
            reasons.append(
                f"{stats.high_match_jobs_imported} of {stats.scored_imports} imports "
                "scored above the high-match threshold"
            )

        if stats.interviews_produced:
            priority = min(99, priority + 10)
            reasons.append(f"produced {stats.interviews_produced} interview(s)")

        if stats.searches_opened >= 5 and stats.jobs_imported == 0:
            priority = max(1, priority - 10)
            reasons.append(f"opened {stats.searches_opened} times with nothing worth importing")

        if priority == spec.priority and status == spec.status:
            continue

        adjustments.append(
            QueryAdjustment(
                query_id=spec.id,
                label=spec.label,
                previous_priority=spec.priority,
                new_priority=priority,
                previous_status=spec.status,
                new_status=status,
                reason="; ".join(reasons) or "priority recalculated",
            )
        )

    return adjustments


def summarise_market_feedback(
    specs: Sequence[JobSearchQuerySpec],
    job_signals: Sequence[Dict[str, object]],
    high_match_threshold: int,
    max_lines: int = 12,
) -> str:
    """Renders performance history as prose for the role discovery prompt."""
    lines: List[str] = []

    performing = [spec for spec in specs if spec.stats.jobs_imported > 0]
    performing.sort(key=lambda s: s.stats.average_match_score, reverse=True)

    if performing:
        lines.append("SEARCH QUERY PERFORMANCE")
        for spec in performing[:max_lines]:
            stats = spec.stats
            lines.append(
                f'- "{spec.query}" ({spec.provider.value}) → {stats.jobs_imported} imported, '
                f"{stats.high_match_jobs_imported} above {high_match_threshold}, "
                f"average match {stats.average_match_score}, "
                f"{stats.applications_generated} applications, "
                f"{stats.interviews_produced} interviews"
            )

    unused = [
        spec for spec in specs if spec.stats.searches_opened >= 3 and not spec.stats.jobs_imported
    ]
    if unused:
        lines.append("")
        lines.append("QUERIES THE USER OPENED BUT IMPORTED NOTHING FROM")
        lines.extend(f'- "{spec.query}" ({spec.provider.value})' for spec in unused[:6])

    strong = [
        signal
        for signal in job_signals
        if isinstance(signal.get("match_score"), (int, float))
        and int(signal["match_score"]) >= high_match_threshold  # type: ignore[arg-type]
    ]
    if strong:
        lines.append("")
        lines.append("JOBS THE USER IMPORTED THAT SCORED WELL")
        for signal in strong[:max_lines]:
            lines.append(
                f"- {signal.get('title')} at {signal.get('company')} "
                f"(match {signal.get('match_score')})"
            )

    weak = [
        signal
        for signal in job_signals
        if isinstance(signal.get("match_score"), (int, float)) and int(signal["match_score"]) < 60  # type: ignore[arg-type]
    ]
    if weak:
        lines.append("")
        lines.append("JOBS THE USER IMPORTED THAT SCORED POORLY")
        for signal in weak[:6]:
            lines.append(
                f"- {signal.get('title')} at {signal.get('company')} "
                f"(match {signal.get('match_score')})"
            )

    return "\n".join(lines)


def select_auto_accepted(
    proposals: Sequence[DiscoveredRole],
    config: RoleDiscoveryConfig,
) -> List[str]:
    """Applies the configured policy for adopting a proposed role without asking."""
    if not config.auto_accept_proposed_roles:
        return []
    return [role.id for role in proposals if role.fit_score >= config.auto_accept_fit_threshold]


def build_job_signal(
    title: str,
    company: str,
    match_score: Optional[int],
    technologies: Sequence[str],
    description: str,
    job_id: Optional[str] = None,
    search_query_id: Optional[str] = None,
) -> Dict[str, object]:
    return {
        "title": title,
        "company": company,
        "match_score": match_score,
        "technologies": list(technologies),
        "description_excerpt": description[:600],
        "job_id": job_id,
        "search_query_id": search_query_id,
    }
