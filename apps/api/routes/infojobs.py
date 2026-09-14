from fastapi import APIRouter, HTTPException
from config.settings import settings
from packages.application_adapters.infojobs_api import InfoJobsApiAdapter
from packages.job_sources.infojobs import InfoJobsAuthError, InfoJobsClient

router = APIRouter(prefix="/api/infojobs", tags=["InfoJobs"])


@router.get("/status")
async def infojobs_status():
    client = InfoJobsClient()
    return {
        "client_configured": client.is_configured,
        "user_token_present": client.has_user_token,
        "redirect_uri": settings.infojobs_redirect_uri,
        "curriculum_code": settings.infojobs_curriculum_code or None,
    }


@router.get("/authorize-url")
async def authorize_url():
    """Returns the consent URL the candidate opens once to authorise the application."""
    client = InfoJobsClient()
    if not client.is_configured:
        raise HTTPException(
            status_code=400,
            detail="Set INFOJOBS_CLIENT_ID and INFOJOBS_CLIENT_SECRET before starting the OAuth flow.",
        )
    if not settings.infojobs_redirect_uri:
        raise HTTPException(
            status_code=400,
            detail="Set INFOJOBS_REDIRECT_URI to the callback registered on the developer site.",
        )
    return {"url": client.authorization_url(scopes=InfoJobsApiAdapter.SCOPES)}


@router.get("/callback")
async def oauth_callback(code: str):
    """
    Exchanges the authorization code for tokens. The tokens are returned rather than
    persisted, so they can be copied into INFOJOBS_ACCESS_TOKEN and INFOJOBS_REFRESH_TOKEN.
    """
    client = InfoJobsClient()
    try:
        payload = await client.exchange_code(code)
    except InfoJobsAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {exc}")

    return {
        "status": "success",
        "message": "Copy these values into your .env file.",
        "INFOJOBS_ACCESS_TOKEN": payload.get("access_token"),
        "INFOJOBS_REFRESH_TOKEN": payload.get("refresh_token"),
        "expires_in": payload.get("expires_in"),
        "scope": payload.get("scope"),
    }


@router.get("/curriculum")
async def list_curriculum():
    """Lists the CVs on the InfoJobs account so one can be pinned as INFOJOBS_CURRICULUM_CODE."""
    client = InfoJobsClient()
    try:
        payload = await client.get(InfoJobsApiAdapter.CURRICULUM_PATH, require_user_token=True)
    except InfoJobsAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"InfoJobs request failed: {exc}")
    return payload or []
