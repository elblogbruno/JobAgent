from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apps.api.routes import answers, applications, jobs, system, webhooks
from config.settings import settings
from packages.persistence.database import Base, async_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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
    allow_origins=settings.cors_origins_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router)
app.include_router(applications.router)
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
