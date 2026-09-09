from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from config.settings import settings
from packages.candidate_profile.profile import CandidateProfileLoader
from packages.persistence.database import get_db
from packages.persistence.models import ApplicationRunORM, JobORM, ManualQuestionORM
from packages.reactive_resume.client import ReactiveResumeClient

router = APIRouter(prefix="/api/system", tags=["System & Metrics"])


@router.get("/status")
async def get_system_status():
    profile = CandidateProfileLoader.get()
    return {
        "app_env": settings.app_env,
        "default_llm": settings.default_llm_provider,
        "execution_mode": profile.application_preferences.execution_mode.value,
        "auto_apply_threshold": profile.application_preferences.auto_apply_threshold,
        "prepare_threshold": profile.application_preferences.prepare_threshold,
        "candidate_name": profile.identity.name,
        "candidate_email": profile.identity.email,
        "playwright_headless": settings.playwright_headless,
        "status": "operational",
    }


@router.get("/metrics")
async def get_pipeline_metrics(db: AsyncSession = Depends(get_db)):
    # Aggregated counts
    total_jobs = await db.scalar(select(func.count(JobORM.id)))
    high_match_jobs = await db.scalar(
        select(func.count(JobORM.id)).where(JobORM.status.in_(["EVALUATED", "READY", "APPLIED"]))
    )
    total_applied = await db.scalar(
        select(func.count(ApplicationRunORM.id)).where(ApplicationRunORM.status == "APPLIED")
    )
    total_blocked = await db.scalar(
        select(func.count(ApplicationRunORM.id)).where(ApplicationRunORM.status == "BLOCKED")
    )
    pending_questions = await db.scalar(
        select(func.count(ManualQuestionORM.id)).where(ManualQuestionORM.status == "PENDING")
    )

    return {
        "total_jobs_discovered": total_jobs or 0,
        "high_match_jobs": high_match_jobs or 0,
        "total_applied": total_applied or 0,
        "total_blocked": total_blocked or 0,
        "pending_questions": pending_questions or 0,
    }
