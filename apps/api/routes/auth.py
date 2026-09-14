import secrets
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from apps.api.security import (
    SESSION_COOKIE_NAME,
    create_session_token,
    get_current_user_from_request,
)
from config.settings import settings

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(payload: LoginRequest, response: Response):
    """Authenticate user with username and password, setting an HTTP-only session cookie."""
    if not settings.is_auth_active:
        token = create_session_token(payload.username or "admin")
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            httponly=True,
            samesite="lax",
            max_age=86400 * settings.auth_session_expire_days,
            path="/",
        )
        return {
            "status": "success",
            "username": payload.username or "admin",
            "token": token,
            "message": "Auth is not enabled; session granted.",
        }

    valid_user = secrets.compare_digest(payload.username.strip(), settings.auth_username.strip())
    valid_pass = secrets.compare_digest(payload.password, settings.auth_password)

    if not (valid_user and valid_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos",
        )

    token = create_session_token(
        settings.auth_username, expire_days=settings.auth_session_expire_days
    )
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400 * settings.auth_session_expire_days,
        path="/",
    )
    return {
        "status": "success",
        "username": settings.auth_username,
        "token": token,
    }


@router.post("/logout")
async def logout(response: Response):
    """Clear session cookie to log out."""
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return {"status": "logged_out"}


@router.get("/me")
async def get_me(request: Request):
    """Check current authentication status and user information."""
    if not settings.is_auth_active:
        return {
            "authenticated": True,
            "auth_enabled": False,
            "username": settings.auth_username or "admin",
        }
    user = get_current_user_from_request(request)
    return {
        "authenticated": bool(user),
        "auth_enabled": True,
        "username": user if user else None,
    }
