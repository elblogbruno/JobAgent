import base64
import json
import httpx
import pytest
from packages.application_adapters.infojobs_api import InfoJobsApiAdapter
from packages.candidate_profile.profile import CandidateProfileLoader
from packages.domain.enums import ApplicationStatus, JobSourceType
from packages.domain.models import CanonicalJob, DiscoveryConfig, JobSearchQuery
from packages.job_sources.feeds import ConfiguredFeedsSource
from packages.job_sources.infojobs import InfoJobsAuthError, InfoJobsClient, InfoJobsSource
from packages.llm.base import LLMProvider, LLMResponse
from packages.llm.gateway import LLMGateway

SEARCH_PAYLOAD = {
    "currentPage": 1,
    "totalResults": 1,
    "offers": [
        {
            "id": "abc123",
            "title": "Desarrollador Unity XR",
            "province": {"id": 8, "value": "Barcelona"},
            "city": "Barcelona",
            "link": "https://www.infojobs.net/barcelona/desarrollador-unity/of-iabc123",
            "contractType": {"id": 1, "value": "Indefinido"},
            "salaryDescription": "30.000€ - 40.000€ Bruto/año",
            "teleworking": {"id": 3, "value": "Híbrido"},
            "requirementMin": "Experiencia con Unity",
            "author": {"id": "e1", "name": "Estudio XR"},
            "updated": "2026-09-01T08:39:22.000+0000",
        }
    ],
}

DETAIL_PAYLOAD = {
    "id": "abc123",
    "title": "Desarrollador Unity XR",
    "link": "https://www.infojobs.net/barcelona/desarrollador-unity/of-iabc123",
    "city": "Barcelona",
    "province": {"id": 8, "value": "Barcelona"},
    "description": "Buscamos un desarrollador de realidad aumentada con Unity y C#.",
    "profile": {"id": "e1", "name": "Estudio XR S.L."},
    "minRequirements": "3 años de experiencia con Unity",
    "desiredRequirements": "Conocimientos de OpenXR",
    "skillsList": [{"skill": "Unity"}, {"skill": "C#"}],
    "minPay": {"amountValue": "30.000€"},
    "maxPay": {"amountValue": "40.000€"},
    "contractType": {"id": 1, "value": "Indefinido"},
    "updateDate": "2026-09-01T08:39:22.000+0000",
}


class StubLLMProvider(LLMProvider):
    def __init__(self, payload: str):
        self.payload = payload

    async def generate(self, messages, temperature=0.2, max_tokens=4096, response_format=None):
        return LLMResponse(content=self.payload, model="stub-provider")


def _client(handler, **kwargs) -> InfoJobsClient:
    return InfoJobsClient(
        client_id="id",
        client_secret="secret",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def _infojobs_job() -> CanonicalJob:
    return CanonicalJob(
        dedup_hash="infojobs-abc123",
        company="Estudio XR",
        normalized_company="Estudio Xr",
        role="Desarrollador Unity XR",
        normalized_role="Desarrollador Unity Xr",
        canonical_url="https://www.infojobs.net/of-iabc123",
        apply_url="https://www.infojobs.net/of-iabc123",
        source=JobSourceType.INFOJOBS,
        source_job_id="abc123",
        description="Realidad aumentada con Unity",
        status=ApplicationStatus.EVALUATED,
    )


def test_auth_header_carries_basic_and_bearer():
    client = InfoJobsClient(client_id="id", client_secret="secret", access_token="tok")
    expected = base64.b64encode(b"id:secret").decode("ascii")

    assert client.auth_header() == f"Basic {expected},Bearer tok"


def test_auth_header_requires_credentials_and_user_token():
    with pytest.raises(InfoJobsAuthError):
        InfoJobsClient(client_id="", client_secret="").auth_header()

    with pytest.raises(InfoJobsAuthError):
        InfoJobsClient(client_id="id", client_secret="secret", access_token="").auth_header(
            require_user_token=True
        )


@pytest.mark.asyncio
async def test_search_parses_offers_and_merges_detail():
    seen_params = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/9/offer":
            seen_params.update(dict(request.url.params))
            return httpx.Response(200, json=SEARCH_PAYLOAD)
        if request.url.path == "/api/7/offer/abc123":
            return httpx.Response(200, json=DETAIL_PAYLOAD)
        return httpx.Response(404)

    source = InfoJobsSource(client=_client(handler), provinces=["barcelona"])
    jobs = await source.search(JobSearchQuery(query="Unity", limit=10))

    assert len(jobs) == 1
    job = jobs[0]
    assert seen_params["q"] == "Unity"
    assert seen_params["province"] == "barcelona"
    assert job.source == JobSourceType.INFOJOBS
    assert job.company == "Estudio XR S.L."
    assert job.description.startswith("Buscamos un desarrollador")
    assert job.requirements == ["3 años de experiencia con Unity"]
    assert job.preferred_requirements == ["Conocimientos de OpenXR"]
    assert job.technologies == ["Unity", "C#"]
    assert job.salary == "30.000€ - 40.000€"
    assert job.published_at is not None


@pytest.mark.asyncio
async def test_search_returns_nothing_without_credentials():
    source = InfoJobsSource(client=InfoJobsClient(client_id="", client_secret=""))
    assert await source.search(JobSearchQuery(query="Unity", limit=5)) == []


@pytest.mark.asyncio
async def test_get_job_accepts_offer_url():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/7/offer/abc123"
        return httpx.Response(200, json=DETAIL_PAYLOAD)

    source = InfoJobsSource(client=_client(handler))
    job = await source.get_job("https://www.infojobs.net/barcelona/desarrollador-unity/of-iabc123")

    assert job is not None
    assert job.source_job_id == "abc123"


@pytest.mark.asyncio
async def test_apply_builds_expected_payload():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/2/curriculum":
            return httpx.Response(200, json=[
                {"code": "CV-SECONDARY", "name": "Antiguo", "principal": False, "completed": True},
                {"code": "CV-MAIN", "name": "Principal", "principal": True, "completed": True},
            ])
        if path.endswith("/killerquestion"):
            return httpx.Response(200, json=[
                {
                    "id": 11,
                    "question": "¿Cuántos años de experiencia tienes con Unity?",
                    "answers": [
                        {"id": 21, "answer": "Más de 5 años"},
                        {"id": 22, "answer": "Menos de 1 año"},
                    ],
                }
            ])
        if path.endswith("/openquestion"):
            return httpx.Response(200, json=[])
        if path == "/api/4/offer/abc123/application":
            captured["body"] = json.loads(request.content)
            captured["auth"] = request.headers["Authorization"]
            return httpx.Response(200, json={
                "code": "e58f7150",
                "cv": "Principal",
                "hasCoverLetter": True,
                "coverLetterSavedKO": False,
                "date": "2026-09-01T08:39:22.000+0000",
            })
        return httpx.Response(404)

    llm = LLMGateway(provider=StubLLMProvider(json.dumps({
        "answers": [{"id": 11, "answerId": 21, "confidence": 0.95}]
    })))
    adapter = InfoJobsApiAdapter(client=_client(handler, access_token="tok"), llm_gateway=llm)

    result = await adapter.apply(
        job=_infojobs_job(),
        profile=CandidateProfileLoader.get(),
        cover_letter_text="Hola" * 2000,
    )

    assert result.submitted is True
    assert result.application_code == "e58f7150"
    body = captured["body"]
    assert body["curriculumCode"] == "CV-MAIN"
    assert body["offerKillerQuestions"] == [{"id": 11, "answerId": 21}]
    assert len(body["coverLetter"]["text"]) == 4000
    assert len(body["coverLetter"]["name"]) <= 100
    assert captured["auth"].startswith("Basic ") and ",Bearer tok" in captured["auth"]


@pytest.mark.asyncio
async def test_apply_escalates_unanswerable_questions():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/2/curriculum":
            return httpx.Response(200, json=[{"code": "CV-MAIN", "principal": True, "completed": True}])
        if path.endswith("/killerquestion"):
            return httpx.Response(200, json=[
                {
                    "id": 11,
                    "question": "¿Tienes carnet de camión?",
                    "answers": [{"id": 21, "answer": "Sí"}, {"id": 22, "answer": "No"}],
                }
            ])
        if path.endswith("/openquestion"):
            return httpx.Response(200, json=[])
        raise AssertionError(f"application should not be submitted, got {path}")

    llm = LLMGateway(provider=StubLLMProvider(json.dumps({
        "answers": [{"id": 11, "answerId": None, "confidence": 0.0}]
    })))
    adapter = InfoJobsApiAdapter(client=_client(handler, access_token="tok"), llm_gateway=llm)

    result = await adapter.apply(job=_infojobs_job(), profile=CandidateProfileLoader.get())

    assert result.submitted is False
    assert result.unanswered_questions == ["¿Tienes carnet de camión?"]


def test_adapter_skips_offers_without_user_token():
    adapter = InfoJobsApiAdapter(client=InfoJobsClient(client_id="id", client_secret="s", access_token=""))
    assert adapter.can_handle(_infojobs_job()) is False


def test_adapter_skips_offers_with_external_form():
    job = _infojobs_job()
    job.apply_url = "https://empresa.example.com/apply"
    adapter = InfoJobsApiAdapter(
        client=InfoJobsClient(client_id="id", client_secret="s", access_token="tok")
    )
    assert adapter.can_handle(job) is False


def test_feeds_include_infojobs_only_when_configured():
    without = ConfiguredFeedsSource(
        allowed_sources=["greenhouse", "infojobs"],
        infojobs_client=InfoJobsClient(client_id="", client_secret=""),
    )
    assert "infojobs" not in without.sources_by_name

    with_creds = ConfiguredFeedsSource(
        discovery=DiscoveryConfig(infojobs_provinces=["barcelona"]),
        allowed_sources=["greenhouse", "infojobs"],
        infojobs_client=InfoJobsClient(client_id="id", client_secret="secret"),
    )
    assert "infojobs" in with_creds.sources_by_name
    assert with_creds.sources_by_name["infojobs"].requires_query_parameter is True
