"""The form assistant answers as the candidate, from the candidate's own material."""

import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from packages.assistant.application_assistant import ApplicationAssistant, ChatTurn
from packages.candidate_profile.profile import CandidateProfileLoader
from packages.domain.enums import JobSourceType
from packages.domain.models import CanonicalJob
from packages.llm.base import LLMProvider, LLMResponse
from packages.llm.gateway import LLMGateway
from packages.persistence.database import Base
from packages.persistence.repositories import CandidateAnswerRepository, JobRepository
from packages.persistence.schema_upgrade import apply_additive_migrations
from packages.reactive_resume.models import ResumeBasics, ResumeData, ResumeDetail


class StubLLMProvider(LLMProvider):
    def __init__(self, payload: str):
        self.payload = payload
        self.calls = 0

    async def generate(self, messages, temperature=0.2, max_tokens=4096, response_format=None):
        self.calls += 1
        self.last_prompt = "\n".join(message.content for message in messages)
        return LLMResponse(content=self.payload, model="stub-provider")


class FakeReactiveResume:
    async def get_resume(self, _resume_id: str) -> ResumeDetail:
        return ResumeDetail(
            id="master",
            name="Master",
            slug="master",
            data=ResumeData(
                basics=ResumeBasics(name="Bruno Moya", headline="XR Engineer"),
                sections={
                    "experience": {
                        "items": [
                            {
                                "company": "Glassear",
                                "position": "Founder",
                                "date": "2021",
                                "summary": "Built AR glasses with Unity and OpenCV.",
                            }
                        ]
                    },
                    "skills": {"items": [{"name": "Unity", "keywords": ["C#"]}]},
                },
            ),
        )


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await apply_additive_migrations(conn)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


def _assistant(session: AsyncSession, payload: str) -> tuple:
    provider = StubLLMProvider(payload)
    assistant = ApplicationAssistant(
        session,
        profile=CandidateProfileLoader.get(),
        rr_client=FakeReactiveResume(),
        llm_gateway=LLMGateway(provider=provider),
    )
    return assistant, provider


ANSWER = json.dumps(
    {
        "answer": "I have shipped AR products in Unity, including hand tracking with OpenCV.",
        "confidence": 0.8,
        "caveats": ["Mention the specific product if the form has room."],
        "missing": [],
    }
)


@pytest.mark.asyncio
async def test_a_known_question_is_answered_from_the_vault(session: AsyncSession):
    """Visa and salary questions have one right answer. No model call needed."""
    assistant, provider = _assistant(session, ANSWER)

    answer = await assistant.answer("Are you legally authorized to work in the European Union?")

    assert answer.source == "vault"
    assert answer.answer == "Yes"
    assert answer.canonical_key == "authorized_to_work_eu"
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_an_open_question_is_drafted_from_the_cv(session: AsyncSession):
    assistant, provider = _assistant(session, ANSWER)

    answer = await assistant.answer("Describe your experience with real-time graphics.")

    assert answer.source == "model"
    assert provider.calls == 1
    assert "Unity" in answer.answer
    assert answer.caveats
    assert "master CV" in answer.grounded_on


@pytest.mark.asyncio
async def test_the_job_on_screen_reaches_the_prompt(session: AsyncSession):
    job = CanonicalJob(
        dedup_hash="assistant-test",
        company="Studio Beta",
        normalized_company="Studio Beta",
        role="Mixed Reality Engineer",
        normalized_role="Mixed Reality Engineer",
        canonical_url="https://jobs.ashbyhq.com/studio-beta/1",
        apply_url="https://jobs.ashbyhq.com/studio-beta/1",
        source=JobSourceType.ASHBY,
        source_job_id="1",
        description="Mixed reality work in Unity.",
    )
    job_orm = await JobRepository(session).create_or_update(job)

    assistant, provider = _assistant(session, ANSWER)
    answer = await assistant.answer("Why do you want to work here?", job_id=job_orm.id)

    assert "Studio Beta" in provider.last_prompt
    assert "Mixed Reality Engineer" in provider.last_prompt
    assert any("Studio Beta" in source for source in answer.grounded_on)


@pytest.mark.asyncio
async def test_a_draft_claiming_absent_technology_is_flagged(session: AsyncSession):
    """The answer goes into a real application, so the same guard applies."""
    payload = json.dumps(
        {
            "answer": "I have deep experience with Kubernetes and PyTorch in production.",
            "confidence": 0.9,
            "caveats": [],
            "missing": [],
        }
    )
    assistant, _ = _assistant(session, payload)

    answer = await assistant.answer("Describe your infrastructure experience.")

    assert answer.warnings
    assert any(
        "Kubernetes" in warning or "Cloud Infrastructure" in warning for warning in answer.warnings
    )


@pytest.mark.asyncio
async def test_an_unusable_model_response_is_reported_not_faked(session: AsyncSession):
    assistant, _ = _assistant(session, "not json")
    answer = await assistant.answer("Describe your experience with Rust.")

    assert answer.source == "error"
    assert answer.confidence == 0.0


@pytest.mark.asyncio
async def test_an_empty_question_asks_for_one(session: AsyncSession):
    assistant, provider = _assistant(session, ANSWER)
    answer = await assistant.answer("   ")

    assert answer.source == "error"
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_history_is_passed_to_the_model(session: AsyncSession):
    assistant, provider = _assistant(session, ANSWER)
    await assistant.answer(
        "Make it shorter.",
        history=[
            ChatTurn(role="user", content="Why do you want to work here?"),
            ChatTurn(role="assistant", content="A long first draft."),
        ],
    )
    assert "A long first draft." in provider.last_prompt


@pytest.mark.asyncio
async def test_a_confirmed_answer_is_recalled_next_time(session: AsyncSession):
    assistant, provider = _assistant(session, ANSWER)
    question = "What is your expected salary?"

    key = await assistant.save_answer(question, "€45,000")
    assert key == "expected_salary"

    stored = await CandidateAnswerRepository(session).get_by_canonical("expected_salary")
    assert stored is not None
    assert stored.answer == "€45,000"

    answer = await assistant.answer(question)
    assert answer.source == "vault"
    assert answer.answer == "€45,000"
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_an_unrecognised_field_is_not_stored(session: AsyncSession):
    """An arbitrary form field has no stable identity to recall it by."""
    assistant, _ = _assistant(session, ANSWER)
    assert await assistant.save_answer("What is your favourite typeface?", "Inter") is None
