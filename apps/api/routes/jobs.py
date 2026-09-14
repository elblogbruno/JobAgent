from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.background import schedule_job_analysis
from apps.api.security import require_extension_token
from packages.domain.models import CanonicalJob
from packages.domain.role_discovery import BrowserJobCapture
from packages.job_import.service import BrowserImportService
from packages.persistence.database import get_db
from packages.persistence.models import JobORM
from packages.persistence.repositories import JobRepository

router = APIRouter(prefix="/api/jobs", tags=["Jobs"])


@router.get("", response_model=List[dict])
async def list_jobs(
    status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    repo = JobRepository(db)
    jobs = await repo.list_jobs(status=status, limit=limit, offset=offset)
    return [
        {
            "id": j.id,
            "company": j.company,
            "role": j.role,
            "location": j.location,
            "is_remote": j.is_remote,
            "source": j.source,
            "status": j.status,
            "apply_url": j.apply_url,
            "discovered_at": j.discovered_at.isoformat() if j.discovered_at else None,
            "technologies": j.technologies,
            "salary": f"{j.salary_min or ''} - {j.salary_max or ''} {j.salary_currency or ''}".strip(),
            "match_score": j.match_score,
            "discovered_by": j.discovered_by,
            "search_query_id": j.search_query_id,
            "search_provider": j.search_provider,
        }
        for j in jobs
    ]


@router.get("/{job_id}")
async def get_job_detail(job_id: str, db: AsyncSession = Depends(get_db)):
    repo = JobRepository(db)
    job = await repo.get_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "id": job.id,
        "company": job.company,
        "role": job.role,
        "location": job.location,
        "is_remote": job.is_remote,
        "is_hybrid": job.is_hybrid,
        "source": job.source,
        "status": job.status,
        "apply_url": job.apply_url,
        "canonical_url": job.canonical_url,
        "description": job.description,
        "requirements": job.requirements,
        "preferred_requirements": job.preferred_requirements,
        "technologies": job.technologies,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_currency": job.salary_currency,
        "discovered_at": job.discovered_at.isoformat() if job.discovered_at else None,
        "match_score": job.match_score,
        "scorecard": job.scorecard,
        "discovered_by": job.discovered_by,
        "search_query_id": job.search_query_id,
        "search_provider": job.search_provider,
        "source_url": job.source_url,
    }


@router.post("/discover")
async def trigger_discovery(limit: int = Query(default=5, ge=1, le=50)):
    try:
        from apps.worker.tasks.discovery import discover_and_evaluate_jobs
        task = discover_and_evaluate_jobs.delay(limit)
        return {"status": "success", "task_id": task.id, "message": f"Discovery cycle queued for {limit} jobs."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/import-browser")
async def import_job_from_browser(
    background_tasks: BackgroundTasks,
    capture: BrowserJobCapture = Body(...),
    token=Depends(require_extension_token),
    db: AsyncSession = Depends(get_db),
):
    """Imports the job page the user is looking at.

    Returns as soon as the job is parsed, deduplicated and stored. Scoring and any
    document preparation are queued, so the browser is never blocked. Importing a
    job never submits an application.
    """
    service = BrowserImportService(db)
    try:
        result = await service.import_job(capture)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse this page: {exc}")

    payload = result.to_api_dict()

    if result.status == "imported" and result.job_id and result.analysis_state == "pending":
        await db.commit()
        payload["analysisQueuedOn"] = schedule_job_analysis(
            result.job_id,
            prepare=capture.prepare_application,
            background_tasks=background_tasks,
        )

    return payload


@router.get("/{job_id}/import-status")
async def get_import_status(
    job_id: str,
    token=Depends(require_extension_token),
    db: AsyncSession = Depends(get_db),
):
    """Polled by the extension while the analysis runs."""
    result = await BrowserImportService(db).status_for(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return result.to_api_dict()


@router.post("/{job_id}/prepare")
async def prepare_application_for_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    token=Depends(require_extension_token),
    db: AsyncSession = Depends(get_db),
):
    """Prepares documents for an already-imported job. Never submits.

    A person pressing the button outranks the match threshold, so this prepares
    the CV even for a job the agent would have skipped.
    """
    repo = JobRepository(db)
    if await repo.get_by_id(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    queued_on = schedule_job_analysis(
        job_id, prepare=True, background_tasks=background_tasks, forced=True
    )
    return {"status": "queued", "jobId": job_id, "analysisQueuedOn": queued_on}
