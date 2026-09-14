"""Authentication for the browser extension.

The extension never ships a secret. The user creates a pairing token in the
dashboard, pastes it into the extension's options page once, and the extension
sends it as a bearer token from then on. Only the hash is stored server-side, and
any token can be revoked without touching the others.
"""

import base64
import hashlib
import hmac
import json
import time
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from packages.persistence.database import get_db
from packages.persistence.models import ExtensionTokenORM
from packages.persistence.role_repositories import ExtensionTokenRepository

SESSION_COOKIE_NAME = "jobagent_session"


def create_session_token(username: str, expire_days: int = 30) -> str:
    expires_at = int(time.time()) + (expire_days * 86400)
    payload = {"sub": username, "exp": expires_at}
    data = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
    sig = hmac.new(settings.secret_key.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{data}.{sig}"


def verify_session_token(token: str) -> Optional[str]:
    if not token or "." not in token:
        return None
    try:
        data, sig = token.rsplit(".", 1)
        expected_sig = hmac.new(
            settings.secret_key.encode("utf-8"), data.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        pad = len(data) % 4
        padded_data = data + ("=" * (4 - pad) if pad else "")
        payload = json.loads(base64.urlsafe_b64decode(padded_data.encode("utf-8")).decode("utf-8"))
        if payload.get("exp", 0) < time.time():
            return None
        return payload.get("sub")
    except Exception:
        return None


def get_current_user_from_request(request: Request) -> Optional[str]:
    if not settings.is_auth_active:
        return settings.auth_username or "admin"
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_token:
        user = verify_session_token(cookie_token)
        if user:
            return user
    auth_header = request.headers.get("Authorization")
    if auth_header:
        scheme, _, val = auth_header.partition(" ")
        if scheme.lower() == "bearer" and val.strip():
            user = verify_session_token(val.strip())
            if user:
                return user
    return None


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
