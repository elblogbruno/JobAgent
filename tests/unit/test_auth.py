import pytest
from httpx import ASGITransport, AsyncClient
from apps.api.main import app
from apps.api.security import create_session_token, verify_session_token
from config.settings import settings


def test_session_token_creation_and_verification():
    token = create_session_token("testuser", expire_days=1)
    assert token is not None
    user = verify_session_token(token)
    assert user == "testuser"


def test_session_token_tampered_fails():
    token = create_session_token("testuser", expire_days=1)
    data, sig = token.rsplit(".", 1)
    # Alter signature
    bad_sig = "a" * len(sig)
    assert verify_session_token(f"{data}.{bad_sig}") is None


def test_session_token_expired_fails():
    # Negative expire days = expired
    token = create_session_token("testuser", expire_days=-1)
    assert verify_session_token(token) is None


@pytest.mark.asyncio
async def test_auth_api_flow():
    # Enable auth temporarily for test
    orig_enabled = settings.auth_enabled
    orig_user = settings.auth_username
    orig_pass = settings.auth_password
    try:
        settings.auth_enabled = True
        settings.auth_username = "admin"
        settings.auth_password = "supersecretpassword123"

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # 1. Initially unauthenticated
            me_res = await ac.get("/api/auth/me")
            assert me_res.status_code == 200
            assert me_res.json()["authenticated"] is False

            # 2. Accessing protected route returns 401
            prot_res = await ac.get("/api/jobs?limit=5")
            assert prot_res.status_code == 401

            # 3. Wrong password fails 401
            bad_login = await ac.post(
                "/api/auth/login",
                json={"username": "admin", "password": "wrongpassword"},
            )
            assert bad_login.status_code == 401

            # 4. Correct credentials succeed and return cookie
            good_login = await ac.post(
                "/api/auth/login",
                json={"username": "admin", "password": "supersecretpassword123"},
            )
            assert good_login.status_code == 200
            assert "jobagent_session" in good_login.cookies

            # 5. /api/auth/me is now authenticated
            ac.cookies = good_login.cookies
            me_after = await ac.get("/api/auth/me")
            assert me_after.status_code == 200
            assert me_after.json()["authenticated"] is True
            assert me_after.json()["username"] == "admin"

            # 6. Logout clears session
            logout_res = await ac.post("/api/auth/logout")
            assert logout_res.status_code == 200
    finally:
        settings.auth_enabled = orig_enabled
        settings.auth_username = orig_user
        settings.auth_password = orig_pass
