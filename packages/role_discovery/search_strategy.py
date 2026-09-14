"""Turns a RoleMap into concrete, clickable search queries.

Every query is a first-class entity: it belongs to a role, targets one provider,
carries a priority, and accumulates its own performance record. The exploration
budget guarantees that a share of the slate is always spent on roles the system
is not yet sure about.
"""

import json
from typing import List, Optional, Sequence

from packages.domain.enums import RoleCategory, SearchProviderId, SearchQueryStatus
from packages.domain.models import CandidateProfileModel
from packages.domain.role_discovery import (
    DiscoveredRole,
    ExplorationBudget,
    JobSearchQuerySpec,
    RoleMap,
    SearchStrategy,
)
from packages.llm.base import LLMMessage
from packages.llm.gateway import LLMGateway
from packages.role_discovery.agent import is_searchable_term
from packages.role_discovery.prompts import SEARCH_STRATEGY_SYSTEM_PROMPT
from packages.search_providers.registry import get_provider, resolve_search_url

# Providers that are worth a row for the highest-priority variant of a role.
_BROAD_PROVIDERS = (SearchProviderId.LINKEDIN, SearchProviderId.GOOGLE)

_SENIORITY_PREFIX = {
    "senior": "Senior",
    "staff": "Staff",
    "lead": "Lead",
    "principal": "Principal",
}


class SearchStrategyGenerator:
    """Expands roles into per-provider search queries under an exploration budget."""

    def __init__(self, llm_gateway: Optional[LLMGateway] = None):
        self.gateway = llm_gateway or LLMGateway.get()

    async def generate(
        self,
        profile: CandidateProfileModel,
        role_map: RoleMap,
        seniority_level: str = "mid",
        use_llm: bool = False,
    ) -> SearchStrategy:
        config = profile.role_discovery
        budget = ExplorationBudget(
            primary_share=config.primary_share,
            secondary_share=config.secondary_share,
            exploratory_share=config.exploratory_share,
            total_queries=config.total_active_queries,
        )
        slots = budget.slots()
        enabled = _enabled_providers(config.providers)

        queries: List[JobSearchQuerySpec] = []
        for category, slot_count in slots.items():
            roles = [role for role in role_map.in_category(category) if role in role_map.searchable]
            if not roles:
                continue
            for variant_index, role in _round_robin(roles, slot_count):
                variants = await self._variants_for_role(
                    role, profile, seniority_level, use_llm=use_llm
                )
                if variant_index >= len(variants):
                    continue
                label, query_text, priority = variants[variant_index]
                queries.extend(
                    self._materialise(
                        role=role,
                        profile=profile,
                        label=label,
                        query_text=query_text,
                        priority=priority,
                        variant_index=variant_index,
                        enabled_providers=enabled,
                        exploratory=(category == RoleCategory.STRETCH),
                    )
                )

        queries.sort(key=lambda q: q.priority, reverse=True)
        return SearchStrategy(
            queries=queries,
            notes=(
                f"{slots[RoleCategory.PRIMARY]} primary, {slots[RoleCategory.SECONDARY]} secondary "
                f"and {slots[RoleCategory.STRETCH]} exploratory searches across "
                f"{len(enabled)} providers."
            ),
        )

    # -- variants ----------------------------------------------------------

    async def _variants_for_role(
        self,
        role: DiscoveredRole,
        profile: CandidateProfileModel,
        seniority_level: str,
        use_llm: bool,
    ) -> List[tuple]:
        """Returns (label, query, priority) tuples, best first."""
        if use_llm and len(role.search_queries) < 2:
            llm_variants = await self._llm_variants(role, profile)
            if llm_variants:
                return llm_variants
        return self.deterministic_variants(role, profile, seniority_level)

    def deterministic_variants(
        self,
        role: DiscoveredRole,
        profile: CandidateProfileModel,
        seniority_level: str = "mid",
    ) -> List[tuple]:
        """Builds query variants without a model.

        The variants deliberately vary along different axes rather than being
        synonyms of each other: exact title, title plus a differentiating
        technology, alternative titles employers use, seniority wording, and an
        ATS-scoped web search.
        """
        variants: List[tuple] = []
        seen: set = set()

        def add(label: str, query: str, priority: int) -> None:
            key = query.strip().lower()
            if not key or key in seen:
                return
            seen.add(key)
            variants.append((label, query.strip(), max(1, min(99, priority))))

        base = max(role.fit_score, 40)
        technologies = [s for s in role.strengths if is_searchable_term(s)][:3]

        for index, seeded in enumerate(role.search_queries[:4]):
            add(_label_for(seeded, role.title), seeded, base - index)

        add(role.title, f'"{role.title}"', base)

        for index, tech in enumerate(technologies[:2]):
            add(f"{role.title} + {tech}", f'"{role.title}" {tech}', base - 2 - index)

        for index, alt in enumerate(role.equivalent_titles[:3]):
            add(alt, f'"{alt}"', base - 4 - index)

        prefix = _SENIORITY_PREFIX.get(seniority_level)
        if prefix:
            add(f"{prefix} {role.title}", f'"{prefix} {role.title}"', base - 6)

        for index, industry in enumerate(role.industries[:1]):
            add(f"{role.title} · {industry}", f'"{role.title}" {industry}', base - 8)

        # A site-scoped variant reaches company ATS pages that job boards miss.
        add(
            f"{role.title} on ATS sites",
            f'"{role.title}" (site:jobs.ashbyhq.com OR site:boards.greenhouse.io'
            " OR site:jobs.lever.co)",
            base - 10,
        )

        variants.sort(key=lambda item: item[2], reverse=True)
        return variants

    async def _llm_variants(
        self,
        role: DiscoveredRole,
        profile: CandidateProfileModel,
    ) -> List[tuple]:
        prefs = profile.job_preferences
        prompt = f"""ROLE
{role.title} (fit {role.fit_score}/100, family: {role.role_family or "unspecified"})
Reasoning: {role.reasoning_summary}
Equivalent titles employers use: {", ".join(role.equivalent_titles) or "unknown"}
Candidate strengths relevant to this role: {", ".join(role.strengths) or "unknown"}
Industries: {", ".join(role.industries) or "unknown"}
Company types: {", ".join(role.company_types) or "unknown"}

CANDIDATE CONSTRAINTS
Locations: {", ".join(prefs.locations) or "none"} | Remote: {prefs.remote}

Produce 5 to 7 query variants.
"""
        try:
            response = await self.gateway.generate(
                [
                    LLMMessage(role="system", content=SEARCH_STRATEGY_SYSTEM_PROMPT),
                    LLMMessage(role="user", content=prompt),
                ],
                temperature=0.4,
                response_format="json",
            )
            parsed = json.loads(response.content)
        except Exception:
            return []

        variants: List[tuple] = []
        for item in parsed.get("queries") or []:
            if not isinstance(item, dict):
                continue
            query = str(item.get("query", "")).strip()
            if not query:
                continue
            label = str(item.get("label", "")).strip() or _label_for(query, role.title)
            try:
                priority = max(1, min(99, int(round(float(item.get("priority", role.fit_score))))))
            except (TypeError, ValueError):
                priority = role.fit_score
            variants.append((label, query, priority))
        variants.sort(key=lambda item: item[2], reverse=True)
        return variants

    # -- materialisation ---------------------------------------------------

    def _materialise(
        self,
        role: DiscoveredRole,
        profile: CandidateProfileModel,
        label: str,
        query_text: str,
        priority: int,
        variant_index: int,
        enabled_providers: List[SearchProviderId],
        exploratory: bool,
    ) -> List[JobSearchQuerySpec]:
        prefs = profile.job_preferences
        location = prefs.locations[0] if prefs.locations else None
        remote = True if prefs.remote else None

        # The second variant of a role drops the location so remote-first postings,
        # which rarely name a city, are not filtered away.
        if variant_index == 1 and prefs.remote:
            location = None

        targets = self._targets(enabled_providers, location, variant_index, query_text)

        specs: List[JobSearchQuerySpec] = []
        for provider_id in targets:
            provider = get_provider(provider_id)
            effective_location = location if provider.supports_location(location) else None
            if provider_id == SearchProviderId.INFOJOBS and not _is_spain(prefs.locations):
                continue
            spec = JobSearchQuerySpec(
                role_id=role.id,
                role_title=role.title,
                group_label=role.role_family or role.title,
                label=label,
                query=query_text,
                provider=provider_id,
                location=effective_location,
                remote=remote,
                priority=priority,
                status=SearchQueryStatus.ACTIVE,
                is_exploratory=exploratory,
                created_by="role-discovery-agent",
            )
            spec.resolved_url = resolve_search_url(spec)
            specs.append(spec)
        return specs

    def _targets(
        self,
        enabled: List[SearchProviderId],
        location: Optional[str],
        variant_index: int,
        query_text: str,
    ) -> List[SearchProviderId]:
        # A site-scoped query only makes sense on a web search engine.
        if "site:" in query_text:
            return [
                p for p in enabled if p in (SearchProviderId.GENERIC_WEB, SearchProviderId.GOOGLE)
            ][:1] or [SearchProviderId.GENERIC_WEB]
        # The top variant of a role is worth spreading wide; later variants stay on
        # the two broad providers so the search list remains browsable.
        if variant_index == 0:
            return enabled[:3]
        return [p for p in enabled if p in _BROAD_PROVIDERS] or enabled[:1]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _enabled_providers(configured: Sequence[str]) -> List[SearchProviderId]:
    providers: List[SearchProviderId] = []
    for raw in configured:
        try:
            provider_id = SearchProviderId(str(raw).strip().lower())
        except ValueError:
            continue
        if provider_id not in providers:
            providers.append(provider_id)
    return providers or [SearchProviderId.LINKEDIN, SearchProviderId.GOOGLE]


def _round_robin(roles: List[DiscoveredRole], slots: int) -> List[tuple]:
    """Yields (variant_index, role) pairs, spreading slots evenly across roles."""
    assignments: List[tuple] = []
    if not roles or slots <= 0:
        return assignments
    variant_index = 0
    while len(assignments) < slots:
        for role in roles:
            if len(assignments) >= slots:
                break
            assignments.append((variant_index, role))
        variant_index += 1
        if variant_index > 8:
            break
    return assignments


def _label_for(query: str, fallback: str) -> str:
    cleaned = query.replace('"', "").strip()
    if "site:" in cleaned:
        return f"{fallback} on ATS sites"
    words = cleaned.split()
    return " ".join(words[:5]) if words else fallback


def _is_spain(locations: Sequence[str]) -> bool:
    hints = ("spain", "españa", "espana", "barcelona", "madrid", "valencia", "bilbao", "sevilla")
    return any(hint in " ".join(locations).lower() for hint in hints)


def apply_stat_adjusted_priority(spec: JobSearchQuerySpec) -> int:
    """Blends the agent's prior with observed performance.

    A query that produced high-match jobs climbs; one that produced volume without
    quality falls. Queries with no data keep the agent's original priority.
    """
    stats = spec.stats
    if stats.jobs_imported == 0:
        return spec.priority
    delta = 0
    if stats.average_match_score >= 80:
        delta += 8
    elif stats.average_match_score < 60:
        delta -= 12
    if stats.high_match_ratio >= 0.5:
        delta += 6
    if stats.interviews_produced:
        delta += 10
    return max(1, min(99, spec.priority + delta))
