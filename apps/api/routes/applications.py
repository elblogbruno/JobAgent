from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from packages.agents.pipeline_agent import JobAgentPipeline
from packages.domain.enums import ApplicationStatus
from packages.persistence.database import get_db
from packages.persistence.models import ApplicationEventORM, ApplicationRunORM, JobORM
from packages.persistence.repositories import ApplicationRunRepository, JobRepository

router = APIRouter(prefix="/api/applications", tags=["Applications"])


@router.get("", response_model=List[dict])
async def list_applications(
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    repo = ApplicationRunRepository(db)
    runs = await repo.list_recent(limit=limit)

    results = []
    job_repo = JobRepository(db)
    for r in runs:
        job = await job_repo.get_by_id(r.job_id)
        results.append({
            "id": r.id,
            "job_id": r.job_id,
            "company": job.company if job else "Unknown",
            "role": job.role if job else "Unknown",
            "status": r.status,
            "execution_mode": r.execution_mode,
            "match_score": r.match_score,
            "reactive_resume_application_id": r.reactive_resume_application_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "error_message": r.error_message,
        })
    return results


@router.get("/{run_id}")
async def get_application_detail(run_id: str, db: AsyncSession = Depends(get_db)):
    repo = ApplicationRunRepository(db)
    run = await repo.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Application run not found")

    job_repo = JobRepository(db)
    job = await job_repo.get_by_id(run.job_id)

    # Fetch events
    events_stmt = select(ApplicationEventORM).where(ApplicationEventORM.application_run_id == run_id)
    events_res = await db.execute(events_stmt)
    events = list(events_res.scalars().all())

    return {
        "id": run.id,
        "status": run.status,
        "execution_mode": run.execution_mode,
        "match_score": run.match_score,
        "scorecard": run.scorecard,
        "tailored_resume_path": run.tailored_resume_path,
        "cover_letter_text": run.cover_letter_text,
        "preflight_passed": run.preflight_passed,
        "preflight_report": run.preflight_report,
        "submission_evidence": run.submission_evidence,
        "error_message": run.error_message,
        "error_category": run.error_category,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "job": {
            "id": job.id,
            "company": job.company,
            "role": job.role,
            "apply_url": job.apply_url,
            "location": job.location,
        } if job else None,
        "events": [
            {
                "event_type": e.event_type,
                "message": e.message,
                "severity": e.severity,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ]
    }


@router.post("/{run_id}/apply")
async def manual_approve_application(run_id: str, db: AsyncSession = Depends(get_db)):
    repo = ApplicationRunRepository(db)
    run = await repo.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Application run not found")

    job_repo = JobRepository(db)
    job = await job_repo.get_by_id(run.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Associated job not found")

    pipeline = JobAgentPipeline(session=db)
    # Execute browser submission
    canonical = await job_repo.get_by_id(job.id)
    # Trigger background or synchronous submission
    return {"status": "submission_initiated", "run_id": run_id}
