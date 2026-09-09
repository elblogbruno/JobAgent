from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union
import httpx
from packages.reactive_resume.models import (
    ApplicationAutofillResponse,
    ApplicationCreateRequest,
    ApplicationDraftMessageResponse,
    ApplicationMatchScoreResponse,
    ApplicationResponse,
    ApplicationTailorResponse,
    ApplicationUpdateRequest,
    CoverLetterCreateRequest,
    CoverLetterResponse,
    JsonPatchOperation,
    ResumeDetail,
    ResumeListItem,
)


class ReactiveResumeError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class ReactiveResumeAuthError(ReactiveResumeError):
    pass


class ReactiveResumeNotFoundError(ReactiveResumeError):
    pass


class ReactiveResumeClient:
    def __init__(
        self,
        base_url: str = "https://rxresu.me/api/openapi",
        api_key: str = "",
        timeout: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = {
            "x-api-key": api_key,
            "Accept": "application/json",
        }
        self.timeout = timeout

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Any] = None,
        files: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> httpx.Response:
        url = f"{self.base_url}{path}"
        req_headers = dict(self.headers)
        if headers:
            req_headers.update(headers)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_data,
                    files=files,
                    headers=req_headers,
                )
            except httpx.RequestError as exc:
                raise ReactiveResumeError(f"HTTP request failed: {exc}") from exc

            if response.status_code in (401, 403):
                raise ReactiveResumeAuthError(
                    f"Authentication failed ({response.status_code}): {response.text}",
                    status_code=response.status_code,
                    response_body=response.text,
                )
            elif response.status_code == 404:
                raise ReactiveResumeNotFoundError(
                    f"Resource not found ({response.status_code}): {response.text}",
                    status_code=response.status_code,
                    response_body=response.text,
                )
            elif not response.is_success:
                raise ReactiveResumeError(
                    f"Reactive Resume API error ({response.status_code}): {response.text}",
                    status_code=response.status_code,
                    response_body=response.text,
                )

            return response

    # ================= RESUMES =================

    async def list_resumes(
        self,
        tags: Optional[List[str]] = None,
        sort: Optional[str] = None
    ) -> List[ResumeListItem]:
        params = {}
        if tags:
            params["tags"] = tags
        if sort:
            params["sort"] = sort
        resp = await self._request("GET", "/resumes", params=params)
        data = resp.json()
        items = data if isinstance(data, list) else data.get("resumes", [])
        return [ResumeListItem.model_validate(item) for item in items]

    async def get_resume(self, resume_id: str) -> ResumeDetail:
        resp = await self._request("GET", f"/resumes/{resume_id}")
        return ResumeDetail.model_validate(resp.json())

    async def create_resume(
        self,
        name: str,
        slug: str,
        tags: Optional[List[str]] = None,
        with_sample_data: bool = False
    ) -> str:
        body = {
            "name": name,
            "slug": slug,
            "tags": tags or [],
            "withSampleData": with_sample_data,
        }
        resp = await self._request("POST", "/resumes", json_data=body)
        data = resp.json()
        return data.get("id") if isinstance(data, dict) else str(data)

    async def duplicate_resume(
        self,
        resume_id: str,
        name: str,
        slug: str,
        tags: Optional[List[str]] = None
    ) -> ResumeDetail:
        body = {
            "name": name,
            "slug": slug,
            "tags": tags or [],
        }
        resp = await self._request("POST", f"/resumes/{resume_id}/duplicate", json_data=body)
        return ResumeDetail.model_validate(resp.json())

    async def patch_resume(
        self,
        resume_id: str,
        operations: List[JsonPatchOperation],
        expected_updated_at: Optional[datetime] = None
    ) -> ResumeDetail:
        body: Dict[str, Any] = {
            "operations": [op.model_dump(by_alias=True, exclude_none=True) for op in operations]
        }
        if expected_updated_at:
            body["expectedUpdatedAt"] = expected_updated_at.isoformat()

        resp = await self._request("PATCH", f"/resumes/{resume_id}", json_data=body)
        return ResumeDetail.model_validate(resp.json())

    async def lock_resume(self, resume_id: str) -> bool:
        resp = await self._request("POST", f"/resumes/{resume_id}/lock")
        return resp.is_success

    async def download_resume_pdf(
        self,
        resume_id: str,
        target: Literal["resume", "cover-letter"] = "resume"
    ) -> bytes:
        resp = await self._request(
            "GET",
            f"/resumes/{resume_id}/pdf",
            params={"target": target},
            headers={"Accept": "application/pdf"}
        )
        return resp.content

    async def list_resume_tags(self) -> List[str]:
        resp = await self._request("GET", "/resumes/tags")
        data = resp.json()
        return data if isinstance(data, list) else data.get("tags", [])

    async def list_resume_versions(self, resume_id: str) -> List[Dict[str, Any]]:
        resp = await self._request("GET", f"/resumes/{resume_id}/versions")
        return resp.json()

    async def restore_resume_version(self, resume_id: str, version_id: str) -> ResumeDetail:
        resp = await self._request("POST", f"/resumes/{resume_id}/versions/{version_id}/restore")
        return ResumeDetail.model_validate(resp.json())

    # ================= APPLICATIONS =================

    async def list_applications(
        self,
        stage: Optional[str] = None,
        tag: Optional[str] = None,
        include_archived: bool = False
    ) -> List[ApplicationResponse]:
        params = {}
        if stage:
            params["stage"] = stage
        if tag:
            params["tag"] = tag
        if include_archived:
            params["includeArchived"] = "true"

        resp = await self._request("GET", "/applications", params=params)
        data = resp.json()
        items = data if isinstance(data, list) else data.get("applications", [])
        return [ApplicationResponse.model_validate(item) for item in items]

    async def create_application(self, data: ApplicationCreateRequest) -> ApplicationResponse:
        body = data.model_dump(exclude_none=True)
        if data.followUpAt:
            body["followUpAt"] = data.followUpAt.isoformat()
        resp = await self._request("POST", "/applications", json_data=body)
        return ApplicationResponse.model_validate(resp.json())

    async def get_application(self, application_id: str) -> ApplicationResponse:
        resp = await self._request("GET", f"/applications/{application_id}")
        return ApplicationResponse.model_validate(resp.json())

    async def update_application(
        self,
        application_id: str,
        data: ApplicationUpdateRequest
    ) -> ApplicationResponse:
        body = data.model_dump(exclude_none=True)
        if data.followUpAt:
            body["followUpAt"] = data.followUpAt.isoformat()
        resp = await self._request("PUT", f"/applications/{application_id}", json_data=body)
        return ApplicationResponse.model_validate(resp.json())

    async def delete_application(self, application_id: str) -> bool:
        resp = await self._request("DELETE", f"/applications/{application_id}")
        return resp.is_success

    async def attach_application_document(
        self,
        application_id: str,
        kind: Literal["resume", "cover-letter"],
        file_bytes: bytes,
        filename: str = "document.pdf"
    ) -> Dict[str, Any]:
        files = {
            "file": (filename, file_bytes, "application/pdf")
        }
        resp = await self._request(
            "POST",
            f"/applications/{application_id}/documents/{kind}",
            files=files
        )
        return resp.json()

    async def remove_application_document(
        self,
        application_id: str,
        kind: Literal["resume", "cover-letter"]
    ) -> bool:
        resp = await self._request("DELETE", f"/applications/{application_id}/documents/{kind}")
        return resp.is_success

    async def log_application_note(self, application_id: str, note: str) -> Dict[str, Any]:
        resp = await self._request(
            "POST",
            f"/applications/{application_id}/notes",
            json_data={"note": note}
        )
        return resp.json()

    async def get_application_stats(self) -> Dict[str, Any]:
        resp = await self._request("GET", "/applications/stats")
        return resp.json()

    async def list_application_tags(self) -> List[str]:
        resp = await self._request("GET", "/applications/tags")
        data = resp.json()
        return data if isinstance(data, list) else data.get("tags", [])

    # ================= APPLICATION AI =================

    async def autofill_from_job(self, job_description: str) -> ApplicationAutofillResponse:
        resp = await self._request(
            "POST",
            "/applications/ai/autofill",
            json_data={"jobDescription": job_description}
        )
        return ApplicationAutofillResponse.model_validate(resp.json())

    async def get_ai_match_score(self, application_id: str) -> ApplicationMatchScoreResponse:
        resp = await self._request("POST", f"/applications/{application_id}/ai/match-score")
        return ApplicationMatchScoreResponse.model_validate(resp.json())

    async def tailor_resume_ai(self, application_id: str) -> ApplicationTailorResponse:
        resp = await self._request("POST", f"/applications/{application_id}/ai/tailor-resume")
        return ApplicationTailorResponse.model_validate(resp.json())

    async def draft_message_ai(
        self,
        application_id: str,
        kind: Literal["cover-letter", "follow-up"] = "cover-letter"
    ) -> ApplicationDraftMessageResponse:
        resp = await self._request(
            "POST",
            f"/applications/{application_id}/ai/draft-message",
            json_data={"kind": kind}
        )
        return ApplicationDraftMessageResponse.model_validate(resp.json())

    # ================= COVER LETTERS =================

    async def create_cover_letter(self, data: CoverLetterCreateRequest) -> CoverLetterResponse:
        resp = await self._request(
            "POST",
            "/coverLetters/create",
            json_data=data.model_dump(exclude_none=True)
        )
        return CoverLetterResponse.model_validate(resp.json())
