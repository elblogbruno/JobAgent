from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from apps.api.routes import (
    answers,
    applications,
    assistant,
    auth,
    candidate,
    extension,
    infojobs,
    jobs,
    llm,
    resumes,
    roles,
    searches,
    system,
    webhooks,
)
from apps.api.security import get_current_user_from_request
from config.settings import settings
from packages.persistence.database import Base, async_engine
from packages.persistence import models  # noqa: F401
from packages.persistence.schema_upgrade import apply_additive_migrations


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables, then add columns create_all cannot add to
    # tables that already exist.
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await apply_additive_migrations(conn)
    yield
    # Teardown
    await async_engine.dispose()


app = FastAPI(
    title="Job Agent API",
    description="Autonomous Agent for Job Search, Reactive Resume Integration, and Browser Automation",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Enforces authentication on /api routes when AUTH_ENABLED and AUTH_PASSWORD are set."""
    path = request.url.path
    if settings.is_auth_active and path.startswith("/api/"):
        is_exempt = (
            path.startswith("/api/auth/")
            or path.startswith("/api/webhooks/")
            or path.startswith("/api/extension/")
            or path == "/api/infojobs/callback"
            or path == "/api/infojobs/authorize-url"
            or request.method == "OPTIONS"
        )
        if not is_exempt:
            user = get_current_user_from_request(request)
            if not user:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Authentication required", "authenticated": False},
                )
    return await call_next(request)


# Ensure artifact directories exist and mount static evidence/video routes
Path("artifacts/evidence").mkdir(parents=True, exist_ok=True)
Path("artifacts/videos").mkdir(parents=True, exist_ok=True)
app.mount("/evidence", StaticFiles(directory="artifacts/evidence"), name="evidence")
app.mount("/videos", StaticFiles(directory="artifacts/videos"), name="videos")

app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(applications.router)
app.include_router(assistant.router)
app.include_router(resumes.router)
app.include_router(roles.router)
app.include_router(searches.router)
app.include_router(extension.router)
app.include_router(candidate.router)
app.include_router(llm.router)
app.include_router(infojobs.router)
app.include_router(answers.router)
app.include_router(system.router)
app.include_router(webhooks.router)


@app.get("/")
async def root():
    return {
        "name": "Job Agent API",
        "version": "0.1.0",
        "status": "online",
        "docs": "/docs",
    }
