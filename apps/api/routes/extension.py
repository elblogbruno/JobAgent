"""Endpoints the browser extension talks to, plus token pairing.

Everything under ``/api/extension`` except token management requires a bearer
token. Token management is dashboard-facing: the user creates a token there and
pastes it into the extension once.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.routes.searches import search_inbox
from apps.api.security import require_extension_token
from config.settings import settings
from packages.candidate_profile.profile import CandidateProfileLoader
from packages.job_import.service import BrowserImportService
from packages.persistence.database import get_db
from packages.persistence.role_repositories import ExtensionTokenRepository
from packages.role_discovery.service import RoleDiscoveryService

router = APIRouter(prefix="/api/extension", tags=["Browser Extension"])

# Hosts the extension knows how to extract from. The extension reads this so a
# new site can be supported by updating the backend alone.
SUPPORTED_HOSTS: List[Dict[str, str]] = [
    {"host": "www.linkedin.com", "extractor": "linkedin"},
    {"host": "www.infojobs.net", "extractor": "infojobs"},
    {"host": "indeed.com", "extractor": "indeed"},
    {"host": "boards.greenhouse.io", "extractor": "greenhouse"},
    {"host": "job-boards.greenhouse.io", "extractor": "greenhouse"},
    {"host": "jobs.lever.co", "extractor": "lever"},
    {"host": "jobs.ashbyhq.com", "extractor": "ashby"},
    {"host": "myworkdayjobs.com", "extractor": "workday"},
    {"host": "apply.workable.com", "extractor": "generic"},
    {"host": "jobs.smartrecruiters.com", "extractor": "generic"},
]


# ---------------------------------------------------------------------------
# Pairing (dashboard-facing)
# ---------------------------------------------------------------------------


@router.post("/tokens")
async def create_extension_token(
    payload: Optional[Dict[str, Any]] = Body(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Creates a pairing token. The plaintext value is returned exactly once."""
    name = str((payload or {}).get("name", "")).strip() or "Browser extension"
    token, orm = await ExtensionTokenRepository(db).create(name)
    return {
        "status": "success",
        "token": token,
        "id": orm.id,
        "name": orm.name,
        "message": ("Copy this token into the extension's options page. It is not shown again."),
    }


@router.get("/tokens")
async def list_extension_tokens(db: AsyncSession = Depends(get_db)):
    tokens = await ExtensionTokenRepository(db).list_tokens()
    return {
        "authRequired": settings.extension_auth_required,
        "tokens": [
            {
                "id": token.id,
                "name": token.name,
                "prefix": token.token_prefix,
                "revoked": token.revoked,
                "lastUsedAt": token.last_used_at.isoformat() if token.last_used_at else None,
                "createdAt": token.created_at.isoformat() if token.created_at else None,
            }
            for token in tokens
        ],
    }


@router.delete("/tokens/{token_id}")
async def revoke_extension_token(token_id: str, db: AsyncSession = Depends(get_db)):
    if not await ExtensionTokenRepository(db).revoke(token_id):
        raise HTTPException(status_code=404, detail="Token not found")
    return {"status": "success", "id": token_id}


# ---------------------------------------------------------------------------
# Extension-facing
# ---------------------------------------------------------------------------


@router.get("/session")
async def extension_session(
    token=Depends(require_extension_token),
    db: AsyncSession = Depends(get_db),
):
    """Validates the token and hands the extension its configuration."""
    profile = CandidateProfileLoader.get()
    role_map = await RoleDiscoveryService(db).get_role_map()
    return {
        "status": "paired",
        "tokenName": getattr(token, "name", None),
        "candidateName": profile.identity.name,
        "dashboardUrl": profile.extension.dashboard_url or settings.dashboard_url,
        "highMatchThreshold": profile.extension.high_match_threshold,
        "importPreparesApplication": profile.extension.import_prepares_application,
        "roleMapVersion": role_map.version if role_map else None,
        "primaryRole": role_map.primary[0].title if role_map and role_map.primary else None,
        "supportedHosts": SUPPORTED_HOSTS,
    }


@router.get("/settings")
async def get_extension_settings():
    profile = CandidateProfileLoader.get()
    return profile.extension.model_dump()


@router.put("/settings")
async def update_extension_settings(payload: Dict[str, Any] = Body(...)):
    """Changes how the extension behaves, without rewriting the whole profile."""
    profile = CandidateProfileLoader.get()
    data = profile.model_dump()

    for key in ("dashboard_url", "import_prepares_application", "high_match_threshold"):
        camel = key.split("_")[0] + "".join(part.title() for part in key.split("_")[1:])
        if key in payload:
            data["extension"][key] = payload[key]
        elif camel in payload:
            data["extension"][key] = payload[camel]

    try:
        updated = CandidateProfileLoader.save(data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid extension settings: {exc}")
    return {"status": "success", **updated.extension.model_dump()}


@router.get("/searches")
async def extension_searches(
    token=Depends(require_extension_token),
    db: AsyncSession = Depends(get_db),
):
    """The Search Inbox, same payload the dashboard uses."""
    return await search_inbox(db=db)


@router.post("/searches/{query_id}/opened")
async def extension_search_opened(
    query_id: str,
    token=Depends(require_extension_token),
    db: AsyncSession = Depends(get_db),
):
    if not await RoleDiscoveryService(db).record_search_opened(query_id):
        raise HTTPException(status_code=404, detail="Search query not found")
    return {"status": "success", "queryId": query_id}


@router.get("/jobs/lookup")
async def extension_job_lookup(
    url: str = Query(...),
    token=Depends(require_extension_token),
    db: AsyncSession = Depends(get_db),
):
    """Answers 'is this page already in Job Agent?' before the user clicks import."""
    result = await BrowserImportService(db).lookup(url)
    if result is None:
        return {"found": False}
    return {"found": True, **result.to_api_dict()}


@router.post("/jobs/{job_id}/outcome")
async def extension_job_outcome(
    job_id: str,
    payload: Dict[str, Any] = Body(...),
    token=Depends(require_extension_token),
    db: AsyncSession = Depends(get_db),
):
    """Reports an outcome from the browser, so the user never leaves the page.

    Recording is not submitting: this is the candidate saying what they already
    did on the company's own form.
    """
    from packages.applications.outcomes import ApplicationOutcomeService, UnknownOutcomeError
    from packages.domain.state_machine import InvalidStateTransitionError

    service = ApplicationOutcomeService(db)
    try:
        result = await service.record_for_job(
            job_id,
            str(payload.get("outcome", "applied")),
            note=str(payload.get("note", "")),
        )
    except UnknownOutcomeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"status": "success", **result}


@router.post("/jobs/{job_id}/outcome/undo")
async def extension_undo_outcome(
    job_id: str,
    token=Depends(require_extension_token),
    db: AsyncSession = Depends(get_db),
):
    """Reverts the last reported outcome, for a wrong automatic detection."""
    from packages.applications.outcomes import ApplicationOutcomeService
    from packages.persistence.repositories import ApplicationRunRepository

    run = await ApplicationRunRepository(db).get_by_job_id(job_id)
    if run is None:
        raise HTTPException(status_code=404, detail="This job has no application to undo")

    try:
        result = await ApplicationOutcomeService(db).undo_last(run.id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "success", **result}


@router.get("/jobs/{job_id}/status")
async def extension_job_status(
    job_id: str,
    token=Depends(require_extension_token),
    db: AsyncSession = Depends(get_db),
):
    result = await BrowserImportService(db).status_for(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return result.to_api_dict()
