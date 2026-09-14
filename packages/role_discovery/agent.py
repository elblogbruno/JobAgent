"""The RoleDiscoveryAgent.

Answers the question the candidate cannot answer for themselves: what should I be
searching for? It reasons over the CandidateCapabilityGraph rather than over
keywords, and keeps improving as the user imports real jobs from the market.
"""

import json
from typing import Dict, List, Optional, Sequence

from packages.domain.enums import RoleCategory, RoleProposalStatus
from packages.domain.models import CandidateProfileModel
from packages.domain.role_discovery import (
    CandidateCapabilityGraph,
    CapabilityGap,
    DiscoveredRole,
    RoleFamily,
    RoleMap,
    slugify,
)
from packages.llm.base import LLMMessage
from packages.llm.gateway import LLMGateway
from packages.role_discovery.lexicon import ROLE_SIGNATURES, RoleSignature
from packages.role_discovery.prompts import (
    ROLE_MAP_SYSTEM_PROMPT,
    ROLE_PROPOSAL_SYSTEM_PROMPT,
)

# Fit score bands used by the deterministic path and to sanity-check the LLM.
PRIMARY_THRESHOLD = 80
SECONDARY_THRESHOLD = 66
STRETCH_THRESHOLD = 52


class RoleDiscoveryAgent:
    """Turns a capability graph into a RoleMap, and keeps that map honest over time."""

    def __init__(self, llm_gateway: Optional[LLMGateway] = None):
        self.gateway = llm_gateway or LLMGateway.get()

    # -- role map ----------------------------------------------------------

    async def discover(
        self,
        profile: CandidateProfileModel,
        graph: CandidateCapabilityGraph,
        market_feedback: str = "",
        use_llm: bool = True,
        version: int = 1,
    ) -> RoleMap:
        if use_llm:
            try:
                response = await self.gateway.generate(
                    [
                        LLMMessage(role="system", content=ROLE_MAP_SYSTEM_PROMPT),
                        LLMMessage(
                            role="user",
                            content=self._discovery_prompt(profile, graph, market_feedback),
                        ),
                    ],
                    temperature=0.5,
                    response_format="json",
                )
                role_map = self._parse_role_map(response.content, profile, version)
                if role_map is not None and len(role_map.searchable) >= 3:
                    return role_map
            except Exception:
                pass

        return self.heuristic_role_map(profile, graph, version=version)

    def _discovery_prompt(
        self,
        profile: CandidateProfileModel,
        graph: CandidateCapabilityGraph,
        market_feedback: str,
    ) -> str:
        by_kind: Dict[str, List[str]] = {}
        for node in graph.nodes:
            entry = f"{node.label} (strength {node.strength:.2f})"
            by_kind.setdefault(node.kind.value, []).append(entry)

        facets = "\n".join(
            f"- {kind}: {', '.join(labels)}" for kind, labels in sorted(by_kind.items())
        )
        clusters = "\n".join(
            f"- {cluster.label} [{cluster.strength:.2f}]: "
            + ", ".join(
                node.label
                for node_id in cluster.node_ids
                if (node := graph.node(node_id)) is not None
            )
            + f" — {cluster.rationale}"
            for cluster in graph.clusters
        )
        prefs = profile.job_preferences
        config = profile.role_discovery

        return f"""CANDIDATE SUMMARY
{graph.summary or "(none)"}

SENIORITY
level={graph.seniority.level}, years={graph.seniority.years_experience}, \
leads_people={graph.seniority.leads_people}, owns_product={graph.seniority.owns_product}
{graph.seniority.rationale}

CAPABILITY GRAPH BY FACET
{facets or "(empty)"}

CAPABILITY COMBINATIONS (the important signal)
{clusters or "(none identified)"}

CONSTRAINTS
Locations: {", ".join(prefs.locations) or "none"}
Remote: {prefs.remote} | Hybrid: {prefs.hybrid} | Onsite: {prefs.onsite} | Relocation: {prefs.relocation}
Minimum salary: {prefs.minimum_salary} {"/".join(prefs.currencies)}
Work authorisation: EU={prefs.visa_requirements.authorized_eu}, US={prefs.visa_requirements.authorized_us}
Desired industries (candidate's own words): {", ".join(prefs.interests) or "not stated"}
Roles the candidate excluded outright: {", ".join(profile.application_preferences.excluded_roles) or "none"}

JOB TITLES THE CANDIDATE GUESSED (hints only, do not anchor on these)
{", ".join(prefs.roles) or "none"}

MARKET FEEDBACK FROM JOBS THE CANDIDATE ACTUALLY IMPORTED
{market_feedback or "No import history yet."}

Produce at most {config.max_roles} roles. Include at least three "primary", several "secondary",
at least two "stretch" that the candidate probably has not considered, and at least one "avoid".
"""

    def _parse_role_map(
        self,
        content: str,
        profile: CandidateProfileModel,
        version: int,
    ) -> Optional[RoleMap]:
        parsed = json.loads(content)
        raw_roles = parsed.get("roles")
        if not isinstance(raw_roles, list):
            return None

        roles: List[DiscoveredRole] = []
        seen_ids: set = set()
        for raw in raw_roles:
            role = _role_from_payload(raw)
            if role is None or role.id in seen_ids:
                continue
            seen_ids.add(role.id)
            roles.append(role)

        if not roles:
            return None

        _apply_exclusions(roles, profile)

        families: List[RoleFamily] = []
        title_to_id = {role.title.lower(): role.id for role in roles}
        for raw in parsed.get("roleFamilies") or []:
            if not isinstance(raw, dict):
                continue
            label = str(raw.get("label", "")).strip()
            if not label:
                continue
            member_ids = [
                title_to_id[str(t).strip().lower()]
                for t in (raw.get("roles") or [])
                if str(t).strip().lower() in title_to_id
            ]
            families.append(
                RoleFamily(
                    id=f"family_{slugify(label)}",
                    label=label,
                    description=str(raw.get("description", "")),
                    role_ids=member_ids,
                )
            )
        if not families:
            families = _families_from_roles(roles)

        gaps: List[CapabilityGap] = []
        for raw in parsed.get("capabilityGaps") or []:
            if not isinstance(raw, dict):
                continue
            capability = str(raw.get("capability", "")).strip()
            if not capability:
                continue
            gaps.append(
                CapabilityGap(
                    capability=capability,
                    severity=str(raw.get("severity", "medium")).strip().lower(),
                    why_it_matters=str(raw.get("whyItMatters", "")),
                    blocks_roles=[str(r) for r in (raw.get("blocksRoles") or [])],
                )
            )

        return RoleMap(
            version=version,
            generated_by="llm",
            roles=roles,
            role_families=families,
            industries=[str(i) for i in (parsed.get("industries") or [])],
            company_types=[str(c) for c in (parsed.get("companyTypes") or [])],
            capability_gaps=gaps,
            notes=str(parsed.get("notes", "")),
        )

    # -- deterministic fallback -------------------------------------------

    def heuristic_role_map(
        self,
        profile: CandidateProfileModel,
        graph: CandidateCapabilityGraph,
        version: int = 1,
    ) -> RoleMap:
        """Scores every known role signature against the capability graph.

        A signature only fires when several independent capabilities are present, so
        a single strong keyword can never on its own become a recommended role.
        """
        strengths_by_label = {node.label: node.strength for node in graph.nodes}
        cluster_labels = {node_id for cluster in graph.clusters for node_id in cluster.node_ids}
        node_ids_by_label = {node.label: node.id for node in graph.nodes}

        roles: List[DiscoveredRole] = []
        for signature in ROLE_SIGNATURES:
            scored = self._score_signature(
                signature, strengths_by_label, cluster_labels, node_ids_by_label
            )
            if scored is not None:
                roles.append(scored)

        roles.sort(key=lambda r: r.fit_score, reverse=True)

        # Guarantee a usable map even for a thin profile: the best two roles are
        # always primary, so the extension is never empty.
        for role in roles[:2]:
            if role.category == RoleCategory.SECONDARY:
                role.category = RoleCategory.PRIMARY

        _apply_exclusions(roles, profile)

        gaps = _gaps_from_roles(roles)
        industries = _unique([i for role in roles for i in role.industries])
        company_types = _unique([c for role in roles for c in role.company_types])

        return RoleMap(
            version=version,
            generated_by="heuristic",
            roles=roles[: profile.role_discovery.max_roles],
            role_families=_families_from_roles(roles),
            industries=industries[:12],
            company_types=company_types[:12],
            capability_gaps=gaps[:8],
            notes=(
                "Scored from capability combinations in the lexicon. Configure an LLM "
                "provider for a richer map that can name roles outside the lexicon."
            ),
        )

    def _score_signature(
        self,
        signature: RoleSignature,
        strengths: Dict[str, float],
        clustered_node_ids: set,
        node_ids_by_label: Dict[str, str],
    ) -> Optional[DiscoveredRole]:
        matched = {
            label: (weight, strengths[label])
            for label, weight in signature.signals.items()
            if label in strengths
        }
        if len(matched) < signature.min_signals:
            return None

        total_weight = sum(signature.signals.values())
        achieved = sum(weight * strength for weight, strength in matched.values())
        coverage = achieved / total_weight if total_weight else 0.0
        breadth = len(matched) / len(signature.signals)

        matched_node_ids = {node_ids_by_label[label] for label in matched}
        # Capabilities that were applied together in one real project count for more
        # than the same capabilities listed separately.
        combination_bonus = 0.06 if len(matched_node_ids & clustered_node_ids) >= 2 else 0.0

        # Capped below a perfect score: this is a lexicon match, not a judgement.
        fit = min(97, round(100 * min(1.0, 0.65 * coverage + 0.35 * breadth + combination_bonus)))
        if fit < STRETCH_THRESHOLD:
            return None

        if fit >= PRIMARY_THRESHOLD:
            category = RoleCategory.PRIMARY
        elif fit >= SECONDARY_THRESHOLD:
            category = RoleCategory.SECONDARY
        else:
            category = RoleCategory.STRETCH

        matched_labels = sorted(matched, key=lambda label: matched[label][1], reverse=True)
        missing_labels = [label for label in signature.signals if label not in matched]

        return DiscoveredRole(
            id=DiscoveredRole.make_id(signature.title),
            title=signature.title,
            fit_score=fit,
            confidence=round(min(0.95, 0.45 + 0.5 * breadth), 2),
            category=category,
            role_family=signature.family,
            reasoning_summary=(
                f"{signature.rationale} Matched {len(matched)} of "
                f"{len(signature.signals)} expected capability signals."
            ),
            strengths=matched_labels[:6],
            gaps=missing_labels[:4],
            equivalent_titles=list(signature.equivalent_titles),
            search_aliases=list(signature.aliases),
            search_queries=_seed_queries(signature, matched_labels),
            industries=list(signature.industries),
            company_types=list(signature.company_types),
            capability_ids=sorted(matched_node_ids),
        )

    # -- learning from imported jobs ---------------------------------------

    async def propose_roles_from_jobs(
        self,
        profile: CandidateProfileModel,
        graph: CandidateCapabilityGraph,
        role_map: RoleMap,
        job_signals: Sequence[Dict[str, object]],
        use_llm: bool = True,
    ) -> List[DiscoveredRole]:
        """Discovers job titles the map does not yet know, from what the user imported.

        ``job_signals`` entries carry: title, company, match_score, technologies,
        description_excerpt and job_id.
        """
        candidates = _unknown_title_candidates(role_map, job_signals, profile)
        if not candidates:
            return []

        if use_llm:
            try:
                response = await self.gateway.generate(
                    [
                        LLMMessage(role="system", content=ROLE_PROPOSAL_SYSTEM_PROMPT),
                        LLMMessage(
                            role="user",
                            content=self._proposal_prompt(graph, role_map, candidates),
                        ),
                    ],
                    temperature=0.4,
                    response_format="json",
                )
                proposed = self._parse_proposals(response.content, role_map)
                if proposed:
                    return proposed
            except Exception:
                pass

        return _heuristic_proposals(candidates, role_map)

    def _proposal_prompt(
        self,
        graph: CandidateCapabilityGraph,
        role_map: RoleMap,
        candidates: List[Dict[str, object]],
    ) -> str:
        known = ", ".join(
            [role.title for role in role_map.roles]
            + [alt for role in role_map.roles for alt in role.equivalent_titles]
        )
        lines = []
        for candidate in candidates:
            lines.append(
                f'- "{candidate["title"]}" seen {candidate["count"]}x, '
                f"average match {candidate['average_score']}, "
                f"technologies: {', '.join(candidate['technologies'][:8]) or 'n/a'}\n"
                f"  excerpt: {str(candidate['excerpt'])[:400]}"
            )
        return f"""CAPABILITY GRAPH
{graph.summary}
Facets: {", ".join(sorted({node.label for node in graph.nodes}))}

ROLES ALREADY IN THE MAP (do not re-propose these or their rewordings)
{known}

TITLES THE CANDIDATE IMPORTED THAT ARE NOT IN THE MAP
{chr(10).join(lines)}
"""

    def _parse_proposals(self, content: str, role_map: RoleMap) -> List[DiscoveredRole]:
        parsed = json.loads(content)
        raw = parsed.get("proposedRoles")
        if not isinstance(raw, list):
            return []

        known_ids = {role.id for role in role_map.roles}
        proposals: List[DiscoveredRole] = []
        for item in raw:
            role = _role_from_payload(item, default_category=RoleCategory.SECONDARY)
            if role is None or role.id in known_ids:
                continue
            if role.category not in (RoleCategory.SECONDARY, RoleCategory.STRETCH):
                role.category = RoleCategory.SECONDARY
            role.proposal_status = RoleProposalStatus.PROPOSED
            known_ids.add(role.id)
            proposals.append(role)
        return proposals


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _role_from_payload(
    raw: object,
    default_category: RoleCategory = RoleCategory.SECONDARY,
) -> Optional[DiscoveredRole]:
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title", "")).strip()
    if not title:
        return None

    try:
        category = RoleCategory(str(raw.get("category", default_category.value)).strip().lower())
    except ValueError:
        category = default_category

    fit = raw.get("fitScore", raw.get("fit_score", 0))
    try:
        fit_score = max(0, min(100, int(round(float(fit)))))
    except (TypeError, ValueError):
        fit_score = 0

    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.6))))
    except (TypeError, ValueError):
        confidence = 0.6

    def _strings(key: str, alt: str = "") -> List[str]:
        value = raw.get(key)
        if value is None and alt:
            value = raw.get(alt)
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    return DiscoveredRole(
        id=DiscoveredRole.make_id(title),
        title=title,
        fit_score=fit_score,
        confidence=round(confidence, 2),
        category=category,
        role_family=str(raw.get("roleFamily", raw.get("role_family", ""))).strip(),
        reasoning_summary=str(raw.get("reasoningSummary", raw.get("reasoning_summary", ""))),
        strengths=_strings("strengths"),
        gaps=_strings("gaps"),
        equivalent_titles=_strings("equivalentTitles", "equivalent_titles"),
        search_aliases=_strings("searchAliases", "search_aliases"),
        search_queries=_strings("searchQueries", "search_queries") or [f'"{title}"'],
        industries=_strings("industries"),
        company_types=_strings("companyTypes", "company_types"),
    )


def _apply_exclusions(roles: List[DiscoveredRole], profile: CandidateProfileModel) -> None:
    """Forces roles the candidate has excluded into the avoid category."""
    excluded = [term.lower() for term in profile.application_preferences.excluded_roles]
    if not excluded:
        return
    for role in roles:
        haystack = " ".join([role.title] + role.equivalent_titles).lower()
        if any(term in haystack for term in excluded):
            role.category = RoleCategory.AVOID
            if not role.reasoning_summary.endswith("(excluded by the candidate)"):
                role.reasoning_summary = (
                    f"{role.reasoning_summary} (excluded by the candidate)".strip()
                )


def _families_from_roles(roles: List[DiscoveredRole]) -> List[RoleFamily]:
    grouped: Dict[str, List[str]] = {}
    for role in roles:
        label = role.role_family or "Other"
        grouped.setdefault(label, []).append(role.id)
    return [
        RoleFamily(id=f"family_{slugify(label)}", label=label, role_ids=ids)
        for label, ids in grouped.items()
    ]


def _gaps_from_roles(roles: List[DiscoveredRole]) -> List[CapabilityGap]:
    counts: Dict[str, List[str]] = {}
    for role in roles:
        if role.category == RoleCategory.AVOID:
            continue
        for gap in role.gaps:
            counts.setdefault(gap, []).append(role.title)
    gaps = []
    for capability, blocked in sorted(counts.items(), key=lambda kv: len(kv[1]), reverse=True):
        severity = "high" if len(blocked) >= 4 else "medium" if len(blocked) >= 2 else "low"
        gaps.append(
            CapabilityGap(
                capability=capability,
                severity=severity,
                why_it_matters=f"Named as a requirement across {len(blocked)} recommended roles.",
                blocks_roles=blocked[:6],
            )
        )
    return gaps


def _seed_queries(signature: RoleSignature, matched_labels: List[str]) -> List[str]:
    queries = [f'"{signature.title}"']
    for title in signature.equivalent_titles[:2]:
        if title.lower() != signature.title.lower():
            queries.append(f'"{title}"')
    for label in matched_labels:
        if not is_searchable_term(label):
            continue
        queries.append(f'"{signature.title}" {label}')
        if len(queries) >= 5:
            break
    return _unique(queries)[:5]


def is_searchable_term(label: str) -> bool:
    """Whether a capability label works as a keyword next to a job title.

    Labels like "XR / AR / VR" or "Client & Stakeholder Management" read well in a
    capability graph but match nothing in a job board's keyword field.
    """
    cleaned = label.strip()
    if not cleaned or len(cleaned) > 22:
        return False
    return not any(ch in cleaned for ch in "/&(),")


def _unique(values: Sequence[str]) -> List[str]:
    seen: set = set()
    result: List[str] = []
    for value in values:
        key = value.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value.strip())
    return result


def _unknown_title_candidates(
    role_map: RoleMap,
    job_signals: Sequence[Dict[str, object]],
    profile: CandidateProfileModel,
) -> List[Dict[str, object]]:
    """Groups imported job titles that the role map has no vocabulary for."""
    known_terms = set()
    for role in role_map.roles:
        for term in [role.title] + role.equivalent_titles + role.search_aliases:
            known_terms.add(term.strip().lower())

    excluded = [term.lower() for term in profile.application_preferences.excluded_roles]

    grouped: Dict[str, Dict[str, object]] = {}
    for signal in job_signals:
        title = str(signal.get("title", "")).strip()
        if not title:
            continue
        lowered = title.lower()
        if any(term and term in lowered for term in known_terms):
            continue
        if any(term in lowered for term in excluded):
            continue

        entry = grouped.setdefault(
            lowered,
            {
                "title": title,
                "count": 0,
                "scores": [],
                "technologies": [],
                "excerpt": "",
                "job_ids": [],
            },
        )
        entry["count"] = int(entry["count"]) + 1
        score = signal.get("match_score")
        if isinstance(score, (int, float)):
            entry["scores"].append(int(score))  # type: ignore[union-attr]
        technologies = signal.get("technologies")
        if isinstance(technologies, list):
            for tech in technologies:
                if tech not in entry["technologies"]:  # type: ignore[operator]
                    entry["technologies"].append(str(tech))  # type: ignore[union-attr]
        if not entry["excerpt"]:
            entry["excerpt"] = str(signal.get("description_excerpt", ""))[:600]
        job_id = signal.get("job_id")
        if job_id:
            entry["job_ids"].append(str(job_id))  # type: ignore[union-attr]

    candidates = []
    for entry in grouped.values():
        scores: List[int] = entry["scores"]  # type: ignore[assignment]
        average = round(sum(scores) / len(scores)) if scores else 0
        # A repeated title, or a single posting that scored genuinely well.
        if int(entry["count"]) >= 2 or average >= 75:
            entry["average_score"] = average
            candidates.append(entry)

    candidates.sort(key=lambda item: (int(item["average_score"]), int(item["count"])), reverse=True)
    return candidates[:8]


def _heuristic_proposals(
    candidates: List[Dict[str, object]],
    role_map: RoleMap,
) -> List[DiscoveredRole]:
    known_ids = {role.id for role in role_map.roles}
    proposals: List[DiscoveredRole] = []
    for candidate in candidates:
        title = str(candidate["title"])
        role_id = DiscoveredRole.make_id(title)
        if role_id in known_ids:
            continue
        average = int(candidate.get("average_score", 0))
        if average < STRETCH_THRESHOLD:
            continue
        technologies = [str(t) for t in candidate.get("technologies", [])][:5]  # type: ignore[union-attr]
        job_ids = [str(j) for j in candidate.get("job_ids", [])]  # type: ignore[union-attr]
        proposals.append(
            DiscoveredRole(
                id=role_id,
                title=title,
                fit_score=average,
                confidence=round(min(0.85, 0.4 + 0.1 * int(candidate["count"])), 2),
                category=(
                    RoleCategory.SECONDARY
                    if average >= SECONDARY_THRESHOLD
                    else RoleCategory.STRETCH
                ),
                role_family="Discovered from market",
                reasoning_summary=(
                    f"Imported {candidate['count']} time(s) from real postings with an average "
                    f"match of {average}. The title is not yet in the role map."
                ),
                strengths=technologies,
                equivalent_titles=[],
                search_queries=_unique(
                    [f'"{title}"'] + [f'"{title}" {tech}' for tech in technologies[:2]]
                ),
                proposal_status=RoleProposalStatus.PROPOSED,
                discovered_from_job_id=job_ids[0] if job_ids else None,
            )
        )
        known_ids.add(role_id)
    return proposals
