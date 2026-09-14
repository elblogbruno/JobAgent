"""The tailored CV may re-emphasise the master. It may never add to it."""

import json

import pytest

from packages.candidate_profile.profile import CandidateProfileLoader
from packages.domain.enums import ApplicationStatus, JobSourceType, Recommendation
from packages.domain.models import CanonicalJob, MatchScorecard
from packages.llm.base import LLMProvider, LLMResponse
from packages.llm.gateway import LLMGateway
from packages.reactive_resume.models import ResumeBasics, ResumeData, ResumeDetail
from packages.resume_pipeline.tailor import ResumeAgent
from packages.resume_pipeline.tailoring_agent import ResumeTailoringAgent, technologies_in

MASTER = ResumeData(
    basics=ResumeBasics(name="Bruno Moya", headline="XR Engineer and Founder"),
    sections={
        "summary": {
            "content": "<p>Founder and engineer building AR products with Unity and OpenCV.</p>"
        },
        "experience": {
            "items": [
                {
                    "company": "Glassear",
                    "position": "Founder & CTO",
                    "date": "2021 - present",
                    "summary": (
                        "Led a team of four engineers building AR smart glasses. "
                        "Built hand tracking with OpenCV and shipped a Unity SDK."
                    ),
                },
                {
                    "company": "Studio X",
                    "position": "Interactive Installations Developer",
                    "date": "2019 - 2021",
                    "summary": "Real-time graphics installations in Unity with custom shaders.",
                },
            ]
        },
        "skills": {
            "items": [
                {"name": "Blender", "keywords": ["modelling"]},
                {"name": "Unity", "keywords": ["C#", "shaders"]},
                {"name": "OpenCV", "keywords": ["hand tracking"]},
            ]
        },
    },
)


def _job(**kwargs) -> CanonicalJob:
    defaults = dict(
        dedup_hash="tailor-test",
        company="Studio Beta",
        normalized_company="Studio Beta",
        role="Mixed Reality Engineer",
        normalized_role="Mixed Reality Engineer",
        canonical_url="https://jobs.ashbyhq.com/studio-beta/1",
        apply_url="https://jobs.ashbyhq.com/studio-beta/1",
        source=JobSourceType.ASHBY,
        source_job_id="1",
        description="We build mixed reality experiences with Unity and computer vision.",
        technologies=["Unity", "OpenCV"],
        status=ApplicationStatus.EVALUATED,
    )
    defaults.update(kwargs)
    return CanonicalJob(**defaults)


def _scorecard(**kwargs) -> MatchScorecard:
    defaults = dict(
        score=88,
        recommendation=Recommendation.APPLY,
        confidence=0.9,
        strengths=["Unity", "OpenCV"],
        gaps=["C++"],
        matched_skills=["Unity", "OpenCV"],
    )
    defaults.update(kwargs)
    return MatchScorecard(**defaults)


class StubLLMProvider(LLMProvider):
    def __init__(self, payload: str):
        self.payload = payload

    async def generate(self, messages, temperature=0.2, max_tokens=4096, response_format=None):
        return LLMResponse(content=self.payload, model="stub-provider")


@pytest.fixture
def profile():
    return CandidateProfileLoader.get()


# ---------------------------------------------------------------------------
# The deterministic path
# ---------------------------------------------------------------------------


def test_the_headline_names_the_role_and_real_overlap(profile):
    plan = ResumeTailoringAgent().heuristic_plan(MASTER, _job(), _scorecard())

    assert plan.headline is not None
    assert plan.headline.startswith("Mixed Reality Engineer")
    assert "Unity" in plan.headline
    # The old hardcoded suffix claimed spatial computing for every job.
    assert "Real-Time Graphics & Spatial Computing" not in plan.headline
    assert len(plan.headline) <= 90


def test_a_job_with_no_overlap_leaves_the_headline_alone(profile):
    """Better the master's honest headline than a claim of relevance that is not there."""
    unrelated = _job(
        role="Renewals Manager",
        normalized_role="Renewals Manager",
        description="Own renewals for enterprise accounts. Salesforce and forecasting.",
        technologies=[],
    )
    plan = ResumeTailoringAgent().heuristic_plan(MASTER, unrelated, _scorecard(matched_skills=[]))

    assert plan.headline is None
    assert "No technology overlap" in plan.reasoning


def test_skills_are_reordered_so_the_relevant_ones_lead(profile):
    plan = ResumeTailoringAgent().heuristic_plan(MASTER, _job(), _scorecard())

    assert plan.skill_priority[:2] == ["Unity", "OpenCV"]
    # Reordering never drops a skill.
    assert set(plan.skill_priority) == {"Unity", "OpenCV", "Blender"}


# ---------------------------------------------------------------------------
# The model path, and what it is not allowed to do
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_clean_plan_is_applied(profile):
    payload = json.dumps(
        {
            "headline": "Mixed Reality Engineer · Unity · OpenCV",
            "summary": "Founder and engineer who shipped AR products built on Unity and OpenCV.",
            "experience": [
                {
                    "index": 0,
                    "summary": (
                        "Built hand tracking with OpenCV and shipped a Unity SDK. "
                        "Led a team of four engineers building AR smart glasses."
                    ),
                }
            ],
            "skill_priority": ["OpenCV", "Unity", "Blender"],
            "reasoning": "Perception work first, since the posting leads with it.",
        }
    )
    plan = await ResumeTailoringAgent(LLMGateway(provider=StubLLMProvider(payload))).build_plan(
        MASTER, _job(), profile, _scorecard()
    )

    assert plan.generated_by == "llm"
    assert plan.headline == "Mixed Reality Engineer · Unity · OpenCV"
    assert plan.experience[0].startswith("Built hand tracking")
    assert plan.skill_priority == ["OpenCV", "Unity", "Blender"]
    assert plan.rejected == []


@pytest.mark.asyncio
async def test_a_technology_the_candidate_does_not_have_is_rejected(profile):
    """The posting mentions Kubernetes; the CV must not quietly acquire it."""
    payload = json.dumps(
        {
            "headline": "Mixed Reality Engineer · Unity · Kubernetes",
            "summary": "Engineer working across Unity, OpenCV and PyTorch.",
            "experience": [
                {"index": 0, "summary": "Led a team of four engineers, deploying with Kubernetes."}
            ],
            "skill_priority": ["Unity"],
        }
    )
    plan = await ResumeTailoringAgent(LLMGateway(provider=StubLLMProvider(payload))).build_plan(
        MASTER, _job(), profile, _scorecard()
    )

    assert plan.headline is None
    assert plan.summary is None
    assert plan.experience == {}
    assert len(plan.rejected) == 3
    assert any(
        "Kubernetes" in reason or "Cloud Infrastructure" in reason for reason in plan.rejected
    )
    # The safe part of the response still lands.
    assert plan.skill_priority == ["Unity"]


@pytest.mark.asyncio
async def test_an_invented_metric_is_rejected(profile):
    payload = json.dumps(
        {
            "headline": "Mixed Reality Engineer · Unity",
            "experience": [
                {"index": 0, "summary": "Led a team of four engineers and cut latency by 40%."}
            ],
        }
    )
    plan = await ResumeTailoringAgent(LLMGateway(provider=StubLLMProvider(payload))).build_plan(
        MASTER, _job(), profile, _scorecard()
    )

    assert plan.experience == {}
    assert any("40%" in reason for reason in plan.rejected)
    assert plan.headline == "Mixed Reality Engineer · Unity"


@pytest.mark.asyncio
async def test_skills_the_master_does_not_list_are_ignored(profile):
    payload = json.dumps(
        {"headline": "Mixed Reality Engineer · Unity", "skill_priority": ["Unity", "Rust", "Go"]}
    )
    plan = await ResumeTailoringAgent(LLMGateway(provider=StubLLMProvider(payload))).build_plan(
        MASTER, _job(), profile, _scorecard()
    )
    assert plan.skill_priority == ["Unity"]


@pytest.mark.asyncio
async def test_an_unknown_experience_index_is_ignored(profile):
    payload = json.dumps(
        {
            "headline": "Mixed Reality Engineer · Unity",
            "experience": [{"index": 99, "summary": "x"}],
        }
    )
    plan = await ResumeTailoringAgent(LLMGateway(provider=StubLLMProvider(payload))).build_plan(
        MASTER, _job(), profile, _scorecard()
    )
    assert plan.experience == {}


@pytest.mark.asyncio
async def test_an_unusable_response_falls_back(profile):
    plan = await ResumeTailoringAgent(LLMGateway(provider=StubLLMProvider("not json"))).build_plan(
        MASTER, _job(), profile, _scorecard()
    )
    assert plan.generated_by == "heuristic"
    assert plan.headline is not None


# ---------------------------------------------------------------------------
# What reaches Reactive Resume
# ---------------------------------------------------------------------------


def _agent(profile) -> ResumeAgent:
    return ResumeAgent(rr_client=None, profile=profile)  # type: ignore[arg-type]


def _master_detail() -> ResumeDetail:
    return ResumeDetail(id="m1", name="Master", slug="master", data=MASTER)


def test_the_patch_touches_only_the_safe_fields(profile):
    plan = ResumeTailoringAgent().heuristic_plan(MASTER, _job(), _scorecard())
    plan.summary = "A tailored summary."
    plan.experience = {0: "A rewritten entry."}

    operations = _agent(profile)._build_operations(plan, _master_detail())
    paths = [op.path for op in operations]

    assert "/basics/headline" in paths
    assert "/sections/summary/content" in paths
    assert "/sections/experience/items/0/summary" in paths
    assert "/sections/skills/items" in paths
    # Nothing may rewrite a company, a position or a date.
    assert not any("company" in path or "position" in path or "date" in path for path in paths)
    # "add" upserts in RFC 6902: replace fails outright when a CV has no summary
    # on an entry, which is common and used to void the whole patch.
    assert all(op.op == "add" for op in operations)


def test_reordering_skills_keeps_every_item(profile):
    plan = ResumeTailoringAgent().heuristic_plan(MASTER, _job(), _scorecard())
    operations = _agent(profile)._build_operations(plan, _master_detail())

    skills_op = next(op for op in operations if op.path == "/sections/skills/items")
    names = [item["name"] for item in skills_op.value]
    assert names == ["Unity", "OpenCV", "Blender"]
    assert len(skills_op.value) == 3


def test_an_unchanged_skill_order_produces_no_patch(profile):
    """Patching a list into the order it already has is noise, not tailoring."""
    from packages.resume_pipeline.tailoring_agent import TailoringPlan

    plan = TailoringPlan(skill_priority=["Blender", "Unity", "OpenCV"])
    assert _agent(profile)._build_operations(plan, _master_detail()) == []


def test_an_empty_plan_produces_no_patch(profile):
    from packages.resume_pipeline.tailoring_agent import TailoringPlan

    assert _agent(profile)._build_operations(TailoringPlan(), _master_detail()) == []


def test_technology_detection_does_not_fire_on_substrings():
    assert "Rust" not in technologies_in("robustness matters")
    assert "Rust" in technologies_in("written in Rust")
    assert "C#" in technologies_in("Unity and C# work")
