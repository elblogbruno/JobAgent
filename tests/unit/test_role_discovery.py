import json

import pytest

from packages.candidate_profile.profile import CandidateProfileLoader
from packages.domain.enums import (
    CapabilityKind,
    RoleCategory,
    RoleProposalStatus,
    SearchProviderId,
    SearchQueryStatus,
)
from packages.domain.role_discovery import (
    ExplorationBudget,
    JobSearchQuerySpec,
    RoleMap,
    SearchQueryStats,
)
from packages.llm.base import LLMProvider, LLMResponse
from packages.llm.gateway import LLMGateway
from packages.role_discovery import (
    CapabilityGraphBuilder,
    RoleDiscoveryAgent,
    SearchStrategyGenerator,
    build_job_signal,
    evaluate_query_performance,
    select_auto_accepted,
    summarise_market_feedback,
)
from packages.role_discovery.capability_graph import ASPIRATION_STRENGTH, INTEREST_STRENGTH
from packages.role_discovery.resume_digest import build_resume_digest
from packages.reactive_resume.models import ResumeBasics, ResumeData, ResumeDetail

RESUME_DIGEST = """## BASICS
Name: Test Candidate
Headline: XR Engineer and Founder

## EXPERIENCE
- Founder & CTO at Glassear - 2021 to present
  Founded the company and led a team of four engineers building AR smart glasses.
  Owned the product definition end-to-end, from hardware prototypes to a Unity SDK.
  Built computer vision hand tracking with OpenCV, plus depth camera calibration.
  Keywords: Unity, C#, OpenXR, computer vision, hardware integration, prototyping
- Interactive Installations Developer at Studio X - 2019 to 2021
  Real-time graphics installations for museums and live events, built in Unity with shaders.
  Rapid prototyping of interactive exhibits driven by sensors and projection mapping.
  Keywords: Unity, HLSL, sensor, exhibition, prototype

## PROJECTS
- Spatial UI toolkit
  Open source spatial interaction toolkit for immersive UX on visionOS.
  Keywords: visionOS, spatial computing
"""


class StubLLMProvider(LLMProvider):
    def __init__(self, payload: str):
        self.payload = payload
        self.calls = 0

    async def generate(self, messages, temperature=0.2, max_tokens=4096, response_format=None):
        self.calls += 1
        return LLMResponse(content=self.payload, model="stub-provider")


@pytest.fixture
def profile():
    return CandidateProfileLoader.get()


# ---------------------------------------------------------------------------
# Capability graph
# ---------------------------------------------------------------------------


def test_heuristic_graph_separates_the_capability_facets(profile):
    graph = CapabilityGraphBuilder().heuristic_graph(profile, resume_digest=RESUME_DIGEST)

    kinds = {node.kind for node in graph.nodes}
    assert CapabilityKind.TECHNOLOGY in kinds
    assert CapabilityKind.CAPABILITY in kinds
    assert CapabilityKind.DOMAIN in kinds
    assert CapabilityKind.LEADERSHIP in kinds
    assert CapabilityKind.PRODUCT_OWNERSHIP in kinds

    labels = graph.labels()
    assert "Unity" in labels
    assert "Computer Vision" in labels
    assert "Hardware Integration" in labels


def test_heuristic_graph_clusters_capabilities_that_appear_in_the_same_cv_entry(profile):
    graph = CapabilityGraphBuilder().heuristic_graph(profile, resume_digest=RESUME_DIGEST)

    assert graph.clusters, "co-occurring capabilities should produce clusters"
    biggest = max(graph.clusters, key=lambda cluster: len(cluster.node_ids))
    assert len(biggest.node_ids) >= 3
    # A cluster must span more than one facet, otherwise it is just a keyword list.
    kinds = {graph.node(node_id).kind for node_id in biggest.node_ids}
    assert len(kinds) >= 2


def test_desired_job_titles_are_not_treated_as_evidence(profile):
    """A wished-for title of CTO must not become proof of leadership experience."""
    graph = CapabilityGraphBuilder().heuristic_graph(profile, resume_digest="")

    assert graph.seniority.leads_people is False
    assert graph.seniority.level != "executive"

    # Capabilities named only in the wish list still appear, but weighted down and
    # labelled so nothing downstream mistakes them for experience.
    aspirational = [node for node in graph.nodes if node.strength <= ASPIRATION_STRENGTH]
    assert aspirational
    assert all("target titles" in " ".join(node.evidence) for node in aspirational)

    interests = [node for node in graph.nodes if node.strength == INTEREST_STRENGTH]
    assert all("not evidenced" in " ".join(node.evidence) for node in interests)
    assert all(node.strength <= INTEREST_STRENGTH for node in graph.nodes)


def test_evidenced_leadership_is_recognised(profile):
    graph = CapabilityGraphBuilder().heuristic_graph(profile, resume_digest=RESUME_DIGEST)
    assert graph.seniority.leads_people is True
    assert graph.seniority.owns_product is True


@pytest.mark.asyncio
async def test_capability_graph_parses_the_model_response(profile):
    payload = json.dumps(
        {
            "summary": "Immersive engineer with product ownership.",
            "seniority": {
                "level": "lead",
                "years_experience": 6,
                "leads_people": True,
                "owns_product": True,
                "rationale": "Led a team of four.",
            },
            "nodes": [
                {
                    "label": "Unity",
                    "kind": "technology",
                    "strength": 0.9,
                    "evidence": ["Unity SDK"],
                },
                {
                    "label": "Computer Vision",
                    "kind": "capability",
                    "strength": 0.8,
                    "evidence": ["hand tracking"],
                },
                {"label": "XR", "kind": "domain", "strength": 0.95, "evidence": ["AR glasses"]},
                {
                    "label": "Team Leadership",
                    "kind": "leadership",
                    "strength": 0.7,
                    "evidence": ["led a team"],
                },
                {
                    "label": "Product Definition",
                    "kind": "product-ownership",
                    "strength": 0.7,
                    "evidence": ["owned"],
                },
                {"label": "Nonsense", "kind": "not-a-kind", "strength": 3.0, "evidence": "bad"},
            ],
            "clusters": [
                {
                    "label": "Immersive product engineering",
                    "nodes": ["Unity", "Computer Vision", "XR"],
                    "strength": 0.9,
                    "rationale": "Ships immersive products end to end.",
                },
                {"label": "Too small", "nodes": ["Unity"], "strength": 0.5, "rationale": ""},
            ],
            "notes": "Founder experience is easy to miss.",
        }
    )
    graph = await CapabilityGraphBuilder(LLMGateway(provider=StubLLMProvider(payload))).build(
        profile, resume_digest=RESUME_DIGEST
    )

    assert graph.generated_by == "llm"
    assert graph.seniority.level == "lead"
    assert len(graph.nodes) == 6
    # An unknown kind degrades to a capability and an out-of-range strength is clamped.
    nonsense = next(node for node in graph.nodes if node.label == "Nonsense")
    assert nonsense.kind == CapabilityKind.CAPABILITY
    assert nonsense.strength == 1.0
    # Clusters need at least two known members.
    assert [cluster.label for cluster in graph.clusters] == ["Immersive product engineering"]


@pytest.mark.asyncio
async def test_capability_graph_falls_back_when_the_model_output_is_unusable(profile):
    gateway = LLMGateway(provider=StubLLMProvider("not json at all"))
    graph = await CapabilityGraphBuilder(gateway).build(profile, resume_digest=RESUME_DIGEST)
    assert graph.generated_by == "heuristic"
    assert graph.nodes


def test_resume_digest_renders_sections_and_strips_markup():
    resume = ResumeDetail(
        id="r1",
        name="Master CV",
        slug="master-cv",
        data=ResumeData(
            basics=ResumeBasics(name="Test Candidate", headline="XR Engineer"),
            sections={
                "experience": {
                    "name": "Experience",
                    "items": [
                        {
                            "company": "Glassear",
                            "position": "Founder & CTO",
                            "date": "2021 - present",
                            "summary": "<p>Led a team of <b>four</b> engineers.</p>",
                            "visible": True,
                        },
                        {"company": "Hidden Co", "position": "Nope", "visible": False},
                    ],
                },
                "skills": {"items": [{"name": "Unity", "keywords": ["C#", "shaders"]}]},
            },
        ),
    )
    digest = build_resume_digest(resume)

    assert "## EXPERIENCE" in digest
    assert "Founder & CTO at Glassear" in digest
    assert "Led a team of four engineers." in digest
    assert "<p>" not in digest
    assert "Hidden Co" not in digest
    assert "Keywords: C#, shaders" in digest


def test_resume_digest_handles_a_missing_resume():
    assert build_resume_digest(None) == ""


# ---------------------------------------------------------------------------
# Role map
# ---------------------------------------------------------------------------


def test_heuristic_role_map_infers_roles_from_capability_combinations(profile):
    graph = CapabilityGraphBuilder().heuristic_graph(profile, resume_digest=RESUME_DIGEST)
    role_map = RoleDiscoveryAgent().heuristic_role_map(profile, graph)

    titles = [role.title for role in role_map.roles]
    # Unity plus XR plus vision plus hardware means spatial computing work, not
    # "Unity Developer": the combination is what is being scored.
    assert "Spatial Computing Engineer" in titles
    assert "Unity Developer" not in titles
    # Roles the candidate would not have thought to search for.
    assert any(
        title in titles for title in ("Creative Technologist", "Immersive Technology Engineer")
    )
    assert role_map.primary, "a usable map always offers primary roles"
    assert all(0 <= role.fit_score <= 97 for role in role_map.roles)


def test_a_single_capability_never_produces_a_role(profile):
    """One strong keyword is not a role recommendation."""
    graph = CapabilityGraphBuilder().heuristic_graph(profile, resume_digest="Unity Unity Unity")
    role_map = RoleDiscoveryAgent().heuristic_role_map(profile, graph)

    unity_only = [
        role
        for role in role_map.roles
        if role.strengths == ["Unity"] and role.category != RoleCategory.AVOID
    ]
    assert unity_only == []


def test_excluded_roles_are_forced_into_the_avoid_category(profile):
    graph = CapabilityGraphBuilder().heuristic_graph(profile, resume_digest=RESUME_DIGEST)
    tweaked = profile.model_copy(deep=True)
    tweaked.application_preferences.excluded_roles = ["Creative Technologist"]

    role_map = RoleDiscoveryAgent().heuristic_role_map(tweaked, graph)
    creative = next(role for role in role_map.roles if role.title == "Creative Technologist")

    assert creative.category == RoleCategory.AVOID
    assert creative not in role_map.searchable


@pytest.mark.asyncio
async def test_role_map_parses_the_model_response(profile):
    graph = CapabilityGraphBuilder().heuristic_graph(profile, resume_digest=RESUME_DIGEST)
    payload = json.dumps(
        {
            "roles": [
                {
                    "title": "Spatial Computing Engineer",
                    "fitScore": 94,
                    "confidence": 0.9,
                    "category": "primary",
                    "roleFamily": "XR & Spatial Computing",
                    "reasoningSummary": "Combination of engine, perception and hardware work.",
                    "strengths": ["Unity", "Computer Vision"],
                    "gaps": ["C++"],
                    "equivalentTitles": ["Spatial Software Engineer"],
                    "searchQueries": ['"Spatial Computing Engineer"', '"XR Engineer" Unity'],
                    "industries": ["XR hardware"],
                    "companyTypes": ["Deep-tech startups"],
                },
                {
                    "title": "Creative Technologist",
                    "fitScore": 86,
                    "confidence": 0.8,
                    "category": "secondary",
                    "searchQueries": ['"Creative Technologist"'],
                },
                {
                    "title": "Emerging Technology Engineer",
                    "fitScore": 74,
                    "confidence": 0.6,
                    "category": "stretch",
                    "searchQueries": ['"Emerging Technology Engineer"'],
                },
                {
                    "title": "Junior Unity Developer",
                    "fitScore": 40,
                    "confidence": 0.7,
                    "category": "avoid",
                    "reasoningSummary": "A step backwards.",
                },
                {"title": "", "fitScore": 10},
                "not a dict",
            ],
            "roleFamilies": [
                {
                    "label": "XR & Spatial Computing",
                    "description": "Immersive engineering",
                    "roles": ["Spatial Computing Engineer"],
                }
            ],
            "industries": ["XR hardware"],
            "companyTypes": ["Startups"],
            "capabilityGaps": [
                {
                    "capability": "C++",
                    "severity": "medium",
                    "whyItMatters": "Engine-level roles ask for it.",
                    "blocksRoles": ["Graphics Engineer"],
                }
            ],
            "notes": "Trajectory points at spatial computing.",
        }
    )
    role_map = await RoleDiscoveryAgent(LLMGateway(provider=StubLLMProvider(payload))).discover(
        profile, graph
    )

    assert role_map.generated_by == "llm"
    assert [role.title for role in role_map.roles] == [
        "Spatial Computing Engineer",
        "Creative Technologist",
        "Emerging Technology Engineer",
        "Junior Unity Developer",
    ]
    assert role_map.primary[0].title == "Spatial Computing Engineer"
    assert role_map.avoid[0].title == "Junior Unity Developer"
    assert role_map.capability_gaps[0].capability == "C++"
    assert role_map.role_families[0].role_ids == ["role_spatial_computing_engineer"]


@pytest.mark.asyncio
async def test_role_map_falls_back_when_the_model_returns_too_few_roles(profile):
    graph = CapabilityGraphBuilder().heuristic_graph(profile, resume_digest=RESUME_DIGEST)
    payload = json.dumps({"roles": [{"title": "Only One", "fitScore": 80, "category": "primary"}]})
    role_map = await RoleDiscoveryAgent(LLMGateway(provider=StubLLMProvider(payload))).discover(
        profile, graph
    )
    assert role_map.generated_by == "heuristic"


# ---------------------------------------------------------------------------
# Search strategy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_strategy_produces_varied_provider_targeted_queries(profile):
    graph = CapabilityGraphBuilder().heuristic_graph(profile, resume_digest=RESUME_DIGEST)
    role_map = RoleDiscoveryAgent().heuristic_role_map(profile, graph)
    strategy = await SearchStrategyGenerator().generate(profile, role_map, use_llm=False)

    assert strategy.queries
    assert len({spec.query for spec in strategy.queries}) > 3, "variants must differ"
    assert len({spec.provider for spec in strategy.queries}) > 1, "several providers"
    assert all(spec.resolved_url for spec in strategy.queries), "every query resolves to a URL"
    assert all(spec.status == SearchQueryStatus.ACTIVE for spec in strategy.queries)
    assert any(spec.is_exploratory for spec in strategy.queries), "exploration budget is spent"
    # No query is a bare unquoted title, which would match far too broadly.
    assert all(spec.query.strip() for spec in strategy.queries)


@pytest.mark.asyncio
async def test_infojobs_is_skipped_when_the_candidate_is_not_in_spain(profile):
    graph = CapabilityGraphBuilder().heuristic_graph(profile, resume_digest=RESUME_DIGEST)
    role_map = RoleDiscoveryAgent().heuristic_role_map(profile, graph)

    abroad = profile.model_copy(deep=True)
    abroad.job_preferences.locations = ["Berlin", "Germany"]
    strategy = await SearchStrategyGenerator().generate(abroad, role_map, use_llm=False)

    assert all(spec.provider != SearchProviderId.INFOJOBS for spec in strategy.queries)


def test_exploration_budget_reserves_slots_for_unproven_roles():
    slots = ExplorationBudget(total_queries=20).slots()
    assert slots[RoleCategory.PRIMARY] == 14
    assert slots[RoleCategory.SECONDARY] == 4
    assert slots[RoleCategory.STRETCH] == 2
    assert sum(slots.values()) == 20


def test_exploration_budget_never_starves_a_category():
    slots = ExplorationBudget(total_queries=3).slots()
    assert all(count >= 1 for count in slots.values())


# ---------------------------------------------------------------------------
# Market feedback
# ---------------------------------------------------------------------------


def _query(query_id: str, label: str, **stats) -> JobSearchQuerySpec:
    return JobSearchQuerySpec(
        id=query_id,
        role_id="role_test",
        label=label,
        query=label,
        provider=SearchProviderId.LINKEDIN,
        priority=90,
        stats=SearchQueryStats(**stats),
    )


def test_a_query_producing_mediocre_jobs_is_demoted(profile):
    # 20 imports averaging 58: the "Unity Developer" case from the spec.
    spec = _query(
        "q1", "Unity Developer", jobs_imported=20, scored_imports=20, total_match_score=1160
    )
    adjustments = evaluate_query_performance([spec], profile.role_discovery)

    assert len(adjustments) == 1
    assert adjustments[0].new_priority < spec.priority
    assert "volume without quality" in adjustments[0].reason


def test_a_query_producing_poor_jobs_is_disabled(profile):
    spec = _query("q2", "Game Developer", jobs_imported=8, scored_imports=8, total_match_score=320)
    adjustments = evaluate_query_performance([spec], profile.role_discovery)

    assert adjustments[0].new_status == SearchQueryStatus.DISABLED


def test_a_query_producing_strong_jobs_is_promoted(profile):
    # 8 imports, 6 above the high-match threshold: worth more, not fewer, results.
    spec = _query(
        "q3",
        "Spatial Computing Engineer",
        jobs_imported=8,
        scored_imports=8,
        high_match_jobs_imported=6,
        total_match_score=700,
        interviews_produced=1,
    )
    spec.priority = 80
    adjustments = evaluate_query_performance([spec], profile.role_discovery)

    assert adjustments[0].new_priority > 80
    assert adjustments[0].new_status == SearchQueryStatus.ACTIVE
    assert "interview" in adjustments[0].reason


def test_a_query_nobody_imports_from_loses_priority(profile):
    spec = _query("q4", "Broad Query", searches_opened=6)
    adjustments = evaluate_query_performance([spec], profile.role_discovery)
    assert adjustments[0].new_priority == 80


def test_a_query_without_a_sample_is_left_alone(profile):
    spec = _query("q5", "New Query", jobs_imported=2, scored_imports=2, total_match_score=100)
    assert evaluate_query_performance([spec], profile.role_discovery) == []


def test_market_feedback_summary_names_the_good_and_the_bad(profile):
    specs = [
        _query(
            "q1",
            "Spatial Computing",
            jobs_imported=8,
            scored_imports=8,
            high_match_jobs_imported=6,
            total_match_score=700,
        ),
        _query(
            "q2", "Unity Developer", jobs_imported=20, scored_imports=20, total_match_score=1160
        ),
    ]
    signals = [
        build_job_signal("XR Engineer", "Company X", 92, ["Unity"], "great fit", "job1"),
        build_job_signal("Unity Gameplay Programmer", "Studio Y", 52, ["Unity"], "gaming", "job2"),
    ]
    summary = summarise_market_feedback(specs, signals, high_match_threshold=80)

    assert "SEARCH QUERY PERFORMANCE" in summary
    assert "XR Engineer at Company X" in summary
    assert "Unity Gameplay Programmer at Studio Y" in summary


# ---------------------------------------------------------------------------
# Learning new roles from imported jobs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeated_unknown_titles_become_proposed_roles(profile):
    graph = CapabilityGraphBuilder().heuristic_graph(profile, resume_digest=RESUME_DIGEST)
    role_map = RoleMap(roles=[])
    signals = [
        build_job_signal(
            "Experience Engineer",
            "Studio A",
            88,
            ["Unity", "AR"],
            "interactive installations",
            "job1",
        ),
        build_job_signal(
            "Experience Engineer", "Studio B", 84, ["Unity"], "real-time graphics", "job2"
        ),
        build_job_signal("Data Entry Clerk", "Corp", 21, [], "typing", "job3"),
    ]
    proposals = await RoleDiscoveryAgent().propose_roles_from_jobs(
        profile, graph, role_map, signals, use_llm=False
    )

    titles = [role.title for role in proposals]
    assert "Experience Engineer" in titles
    assert "Data Entry Clerk" not in titles

    proposed = next(role for role in proposals if role.title == "Experience Engineer")
    assert proposed.proposal_status == RoleProposalStatus.PROPOSED
    assert proposed.discovered_from_job_id == "job1"
    assert proposed.search_queries


@pytest.mark.asyncio
async def test_titles_already_in_the_map_are_not_reproposed(profile):
    graph = CapabilityGraphBuilder().heuristic_graph(profile, resume_digest=RESUME_DIGEST)
    role_map = RoleDiscoveryAgent().heuristic_role_map(profile, graph)
    known = role_map.roles[0].title

    signals = [
        build_job_signal(known, f"Company {i}", 90, ["Unity"], "same role", f"job{i}")
        for i in range(3)
    ]
    proposals = await RoleDiscoveryAgent().propose_roles_from_jobs(
        profile, graph, role_map, signals, use_llm=False
    )
    assert [role.title for role in proposals] == []


def test_auto_accept_policy_is_off_by_default(profile):
    graph = CapabilityGraphBuilder().heuristic_graph(profile, resume_digest=RESUME_DIGEST)
    role_map = RoleDiscoveryAgent().heuristic_role_map(profile, graph)
    strong = role_map.roles[0].model_copy(update={"fit_score": 95})

    assert select_auto_accepted([strong], profile.role_discovery) == []

    permissive = profile.model_copy(deep=True)
    permissive.role_discovery.auto_accept_proposed_roles = True
    permissive.role_discovery.auto_accept_fit_threshold = 85
    assert select_auto_accepted([strong], permissive.role_discovery) == [strong.id]
