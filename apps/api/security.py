"""Authentication for the browser extension.

The extension never ships a secret. The user creates a pairing token in the
dashboard, pastes it into the extension's options page once, and the extension
sends it as a bearer token from then on. Only the hash is stored server-side, and
any token can be revoked without touching the others.
"""

from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from packages.persistence.database import get_db
from packages.persistence.models import ExtensionTokenORM
from packages.persistence.role_repositories import ExtensionTokenRepository

_PAIRING_HINT = (
    "Pair the extension first: open the Job Agent dashboard, go to Role Discovery, "
    "create an extension token, and paste it into the extension's options page."
)


def _extract_token(
    authorization: Optional[str],
    x_job_agent_token: Optional[str],
) -> Optional[str]:
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
    if x_job_agent_token and x_job_agent_token.strip():
        return x_job_agent_token.strip()
    return None


async def require_extension_token(
    authorization: Optional[str] = Header(default=None),
    x_job_agent_token: Optional[str] = Header(default=None, alias="X-Job-Agent-Token"),
    db: AsyncSession = Depends(get_db),
) -> Optional[ExtensionTokenORM]:
    """Rejects unpaired callers unless extension auth is explicitly disabled."""
    token = _extract_token(authorization, x_job_agent_token)

    if not settings.extension_auth_required:
        if not token:
            return None
        return await ExtensionTokenRepository(db).verify(token)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Missing extension token. {_PAIRING_HINT}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    record = await ExtensionTokenRepository(db).verify(token)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Extension token is not valid or has been revoked. {_PAIRING_HINT}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return record
