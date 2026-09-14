"""
InfoJobs REST API integration.

Reference: https://developer.infojobs.net/documentation/operation-list/index.xhtml

Every call carries HTTP Basic credentials for the registered application. Operations
that touch candidate data (applications, CVs) additionally require a user access token
obtained through OAuth2, which the API expects appended to the same header:

    Authorization: Basic <base64(clientId:clientSecret)>,Bearer <accessToken>
"""

import asyncio
import base64
from datetime import datetime
from typing import Any, Dict, List, Optional
import httpx
from config.settings import settings
from packages.domain.enums import JobSourceType
from packages.domain.models import JobSearchQuery, RawJob
from packages.job_sources.base import JobSource


class InfoJobsAuthError(RuntimeError):
    """Raised when InfoJobs rejects the application or user credentials."""


class InfoJobsClient:
    BASE_URL = "https://api.infojobs.net/api"
    AUTHORIZE_URL = "https://www.infojobs.net/api/oauth/user-authorize/index.xhtml"
    TOKEN_URL = "https://www.infojobs.net/oauth/authorize"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        access_token: Optional[str] = None,
        timeout: float = 30.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.client_id = client_id if client_id is not None else settings.infojobs_client_id
        self.client_secret = (
            client_secret if client_secret is not None else settings.infojobs_client_secret
        )
        self.access_token = (
            access_token if access_token is not None else settings.infojobs_access_token
        )
        self.timeout = timeout
        self.transport = transport

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def has_user_token(self) -> bool:
        return bool(self.access_token)

    def authorization_url(self, scopes: List[str], redirect_uri: Optional[str] = None) -> str:
        """Builds the consent URL the candidate has to open once to authorise the app."""
        redirect = redirect_uri or settings.infojobs_redirect_uri
        params = httpx.QueryParams(
            {
                "scope": ",".join(scopes),
                "client_id": self.client_id,
                "redirect_uri": redirect,
                "response_type": "code",
            }
        )
        return f"{self.AUTHORIZE_URL}?{params}"

    async def exchange_code(self, code: str, redirect_uri: Optional[str] = None) -> Dict[str, Any]:
        """Trades the OAuth2 authorization code for an access and refresh token."""
        return await self._token_request(
            {
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "redirect_uri": redirect_uri or settings.infojobs_redirect_uri,
            }
        )

    async def refresh(self, refresh_token: Optional[str] = None) -> Dict[str, Any]:
        """Renews the user access token, which InfoJobs issues for about 12 hours."""
        payload = await self._token_request(
            {
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": refresh_token or settings.infojobs_refresh_token,
                "redirect_uri": settings.infojobs_redirect_uri,
            }
        )
        if payload.get("access_token"):
            self.access_token = payload["access_token"]
        return payload

    def auth_header(self, require_user_token: bool = False) -> str:
        if not self.is_configured:
            raise InfoJobsAuthError(
                "InfoJobs client credentials are missing. "
                "Set INFOJOBS_CLIENT_ID and INFOJOBS_CLIENT_SECRET."
            )
        raw = f"{self.client_id}:{self.client_secret}".encode("utf-8")
        header = f"Basic {base64.b64encode(raw).decode('ascii')}"
        if require_user_token and not self.access_token:
            raise InfoJobsAuthError(
                "This InfoJobs operation needs a candidate access token. "
                "Complete the OAuth2 consent flow and set INFOJOBS_ACCESS_TOKEN."
            )
        if self.access_token:
            header = f"{header},Bearer {self.access_token}"
        return header

    async def get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        require_user_token: bool = False,
    ) -> Any:
        return await self._request(
            "GET", path, params=params, require_user_token=require_user_token
        )

    async def post(
        self,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
        require_user_token: bool = True,
    ) -> Any:
        return await self._request(
            "POST", path, json_body=json_body, require_user_token=require_user_token
        )

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        require_user_token: bool = False,
    ) -> Any:
        headers = {
            "Authorization": self.auth_header(require_user_token=require_user_token),
            "Accept": "application/json",
        }
        url = f"{self.BASE_URL}/{path.lstrip('/')}"

        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await client.request(
                method, url, params=params, json=json_body, headers=headers
            )

        if response.status_code in (401, 403):
            raise InfoJobsAuthError(
                f"InfoJobs rejected the credentials for {method} {path}: {response.text[:200]}"
            )
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()

    async def _token_request(self, data: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await client.post(self.TOKEN_URL, data=data)
        response.raise_for_status()
        return response.json()


class InfoJobsSource(JobSource):
    """Discovers Spanish job postings through the InfoJobs offer API."""

    requires_query_parameter = True

    SEARCH_PATH = "9/offer"
    DETAIL_PATH = "7/offer"
    MAX_RESULTS_PER_PAGE = 50

    def __init__(
        self,
        client: Optional[InfoJobsClient] = None,
        provinces: Optional[List[str]] = None,
        detail_limit: int = 25,
        detail_concurrency: int = 5,
    ):
        self.client = client or InfoJobsClient()
        self.provinces = provinces or []
        self.detail_limit = detail_limit
        self.detail_concurrency = detail_concurrency

    async def search(self, query: JobSearchQuery) -> List[RawJob]:
        if not self.client.is_configured:
            return []

        max_results = min(query.limit, self.MAX_RESULTS_PER_PAGE)
        provinces: List[Optional[str]] = list(self.provinces) or [None]

        offers: List[Dict[str, Any]] = []
        for province in provinces:
            params: Dict[str, Any] = {"maxResults": max_results, "page": 1}
            if query.query:
                params["q"] = query.query
            if province:
                params["province"] = province
            try:
                payload = await self.client.get(self.SEARCH_PATH, params=params)
            except Exception:
                continue
            offers.extend(payload.get("offers", []) if isinstance(payload, dict) else [])
            if len(offers) >= query.limit:
                break

        jobs = [self._parse_offer(offer) for offer in offers[: query.limit]]
        return await self._enrich_with_details(jobs)

    async def get_job(self, source_job_id_or_url: str) -> Optional[RawJob]:
        offer_id = self._extract_offer_id(source_job_id_or_url)
        if not offer_id or not self.client.is_configured:
            return None
        try:
            detail = await self.client.get(f"{self.DETAIL_PATH}/{offer_id}")
        except Exception:
            return None
        if not isinstance(detail, dict):
            return None
        return self._apply_detail(self._parse_detail(detail), detail)

    async def _enrich_with_details(self, jobs: List[RawJob]) -> List[RawJob]:
        """Search results carry no description, so the detail endpoint fills it in."""
        semaphore = asyncio.Semaphore(self.detail_concurrency)

        async def enrich(job: RawJob) -> RawJob:
            async with semaphore:
                try:
                    detail = await self.client.get(f"{self.DETAIL_PATH}/{job.source_job_id}")
                except Exception:
                    return job
            if not isinstance(detail, dict):
                return job
            return self._apply_detail(job, detail)

        enriched = await asyncio.gather(*(enrich(job) for job in jobs[: self.detail_limit]))
        return list(enriched) + jobs[self.detail_limit :]

    def _parse_offer(self, offer: Dict[str, Any]) -> RawJob:
        offer_id = str(offer.get("id", ""))
        link = offer.get("link") or f"https://www.infojobs.net/offer/{offer_id}"
        author = offer.get("author") or {}

        return RawJob(
            source=JobSourceType.INFOJOBS,
            source_job_id=offer_id,
            canonical_url=link,
            apply_url=link,
            company=author.get("name") or "Empresa confidencial",
            role=offer.get("title", ""),
            location=self._format_location(offer.get("city"), self._value(offer.get("province"))),
            remote_policy=self._value(offer.get("teleworking")),
            salary=offer.get("salaryDescription"),
            currency="EUR",
            description=offer.get("requirementMin") or "",
            employment_type=self._value(offer.get("contractType")),
            published_at=self._parse_date(offer.get("updated") or offer.get("published")),
        )

    def _parse_detail(self, detail: Dict[str, Any]) -> RawJob:
        offer_id = str(detail.get("id", ""))
        link = detail.get("link") or f"https://www.infojobs.net/offer/{offer_id}"
        profile = detail.get("profile") or {}

        return RawJob(
            source=JobSourceType.INFOJOBS,
            source_job_id=offer_id,
            canonical_url=link,
            apply_url=detail.get("externalUrlForm") or link,
            company=profile.get("name") or "Empresa confidencial",
            role=detail.get("title", ""),
            location=self._format_location(detail.get("city"), self._value(detail.get("province"))),
            currency="EUR",
            description=detail.get("description") or "",
        )

    def _apply_detail(self, job: RawJob, detail: Dict[str, Any]) -> RawJob:
        """Merges the richer detail payload onto a job parsed from a search result."""
        updated = job.model_copy(deep=True)
        profile = detail.get("profile") or {}

        updated.description = detail.get("description") or updated.description
        updated.apply_url = detail.get("externalUrlForm") or updated.apply_url
        updated.company = profile.get("name") or updated.company
        updated.employment_type = self._value(detail.get("contractType")) or updated.employment_type
        updated.remote_policy = self._value(detail.get("residence")) or updated.remote_policy

        if detail.get("minRequirements"):
            updated.requirements = [detail["minRequirements"]]
        if detail.get("desiredRequirements"):
            updated.preferred_requirements = [detail["desiredRequirements"]]

        skills = detail.get("skillsList") or []
        parsed_skills = [s.get("skill") for s in skills if isinstance(s, dict) and s.get("skill")]
        if parsed_skills:
            updated.technologies = parsed_skills

        min_pay = (detail.get("minPay") or {}).get("amountValue")
        max_pay = (detail.get("maxPay") or {}).get("amountValue")
        if min_pay or max_pay:
            updated.salary = " - ".join(part for part in (min_pay, max_pay) if part)

        updated.published_at = self._parse_date(detail.get("updateDate")) or updated.published_at
        return updated

    @staticmethod
    def _value(item: Any) -> Optional[str]:
        if isinstance(item, dict):
            return item.get("value")
        if isinstance(item, str):
            return item
        return None

    @staticmethod
    def _format_location(city: Optional[str], province: Optional[str]) -> Optional[str]:
        parts = [part for part in (city, province) if part]
        return ", ".join(parts) if parts else None

    @staticmethod
    def _parse_date(value: Any) -> Optional[datetime]:
        """InfoJobs mixes ISO timestamps with human wording, so unparseable dates are dropped."""
        if not isinstance(value, str) or not value:
            return None
        candidate = value.replace("Z", "+00:00")
        for text in (candidate, candidate.replace("+0000", "+00:00")):
            try:
                return datetime.fromisoformat(text)
            except ValueError:
                continue
        return None

    @staticmethod
    def _extract_offer_id(source_job_id_or_url: str) -> Optional[str]:
        value = source_job_id_or_url.strip()
        if not value:
            return None
        if not value.startswith("http"):
            return value
        if "infojobs.net" not in value:
            return None
        tail = value.rstrip("/").split("/")[-1].split("?")[0]
        # Public offer URLs end in the offer id prefixed with "of-i".
        if tail.startswith("of-i"):
            tail = tail[4:]
        return tail or None
