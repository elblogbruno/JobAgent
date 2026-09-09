import pytest
import respx
import httpx
from packages.reactive_resume.client import ReactiveResumeClient
from packages.reactive_resume.models import (
    ApplicationCreateRequest,
    ApplicationUpdateRequest,
    JsonPatchOperation,
)


@pytest.mark.asyncio
@respx.mock
async def test_list_resumes_mock():
    respx.get("https://rxresu.me/api/openapi/resumes").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "resume-123",
                    "name": "Bruno Moya — Master CV",
                    "slug": "bruno-moya-master-cv",
                    "tags": ["master"],
                    "locked": False,
                }
            ],
        )
    )

    client = ReactiveResumeClient(api_key="test-key")
    resumes = await client.list_resumes()
    assert len(resumes) == 1
    assert resumes[0].id == "resume-123"
    assert resumes[0].name == "Bruno Moya — Master CV"


@pytest.mark.asyncio
@respx.mock
async def test_create_application_mock():
    respx.post("https://rxresu.me/api/openapi/applications").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": "app-456",
                "company": "Apple",
                "role": "XR Engineer",
                "status": "saved",
                "tags": ["xr"],
                "contacts": [],
                "timeline": [],
            },
        )
    )

    client = ReactiveResumeClient(api_key="test-key")
    req = ApplicationCreateRequest(
        company="Apple",
        role="XR Engineer",
        status="saved",
    )
    app = await client.create_application(req)
    assert app.id == "app-456"
    assert app.company == "Apple"
    assert app.status == "saved"
