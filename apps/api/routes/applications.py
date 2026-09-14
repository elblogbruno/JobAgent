from pathlib import Path
from typing import Any, Dict, List
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from packages.applications.outcomes import (
    OUTCOMES,
    ApplicationOutcomeService,
    UnknownOutcomeError,
)
from packages.applications.regeneration import ResumeRegenerationService
from packages.domain.state_machine import InvalidStateTransitionError
from packages.persistence.database import get_db
from packages.persistence.models import ApplicationEventORM
from packages.persistence.repositories import ApplicationRunRepository, JobRepository

router = APIRouter(prefix="/api/applications", tags=["Applications"])

#: Tailored CVs are written here by the resume pipeline. Downloads are confined to
#: this directory: the stored path is data, and data is never trusted with the
#: filesystem.
ARTIFACTS_ROOT = Path("artifacts").resolve()


@router.get("", response_model=List[dict])
async def list_applications(limit: int = 50, db: AsyncSession = Depends(get_db)):
    repo = ApplicationRunRepository(db)
    runs = await repo.list_recent(limit=limit)

    results = []
    job_repo = JobRepository(db)
    for r in runs:
        job = await job_repo.get_by_id(r.job_id)
        results.append(
            {
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
                "applied_at": r.applied_at.isoformat() if r.applied_at else None,
                "submitted_manually": bool(r.submitted_manually),
                "outcome_history": r.outcome_history or [],
                "has_tailored_resume": bool(r.tailored_resume_path),
            }
        )
    return results


@router.get("/outcomes")
async def list_outcomes():
    """The outcomes a person can report, for the dashboard to render."""
    return {"outcomes": sorted(OUTCOMES), "statuses": {k: v.value for k, v in OUTCOMES.items()}}


@router.get("/{run_id}")
async def get_application_detail(run_id: str, db: AsyncSession = Depends(get_db)):
    repo = ApplicationRunRepository(db)
    run = await repo.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Application run not found")

    job_repo = JobRepository(db)
    job = await job_repo.get_by_id(run.job_id)

    # Fetch events
    events_stmt = select(ApplicationEventORM).where(
        ApplicationEventORM.application_run_id == run_id
    )
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
        "applied_at": run.applied_at.isoformat() if run.applied_at else None,
        "submitted_manually": bool(run.submitted_manually),
        "outcome_history": run.outcome_history or [],
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "job": {
            "id": job.id,
            "company": job.company,
            "role": job.role,
            "apply_url": job.apply_url,
            "location": job.location,
        }
        if job
        else None,
        "events": [
            {
                "event_type": e.event_type,
                "message": e.message,
                "severity": e.severity,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
    }


async def _record(service: ApplicationOutcomeService, coroutine):
    try:
        return await coroutine
    except UnknownOutcomeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{run_id}/outcome")
async def record_application_outcome(
    run_id: str,
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Records what happened: applied by hand, interview, offer, rejected, withdrawn.

    This never submits anything. It is the candidate telling the system what they
    already did, and it is what feeds interview outcomes back into role discovery.
    """
    service = ApplicationOutcomeService(db)
    result = await _record(
        service,
        service.record(
            run_id,
            str(payload.get("outcome", "")),
            note=str(payload.get("note", "")),
        ),
    )
    return {"status": "success", **result}


@router.post("/by-job/{job_id}/outcome")
async def record_job_outcome(
    job_id: str,
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Same, addressed by job.

    A job imported from the browser has no application run until documents are
    prepared, so this creates one rather than refusing the report.
    """
    service = ApplicationOutcomeService(db)
    result = await _record(
        service,
        service.record_for_job(
            job_id,
            str(payload.get("outcome", "")),
            note=str(payload.get("note", "")),
        ),
    )
    return {"status": "success", **result}


@router.get("/{run_id}/resume")
async def download_tailored_resume(run_id: str, db: AsyncSession = Depends(get_db)):
    """Serves the tailored CV this application prepared.

    This is the PDF to attach when applying by hand: it is the same file the
    browser automation would have uploaded.
    """
    run = await ApplicationRunRepository(db).get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Application run not found")
    if not run.tailored_resume_path:
        raise HTTPException(
            status_code=404,
            detail="This application has no tailored CV yet. Prepare it first.",
        )

    path = Path(run.tailored_resume_path).resolve()
    if ARTIFACTS_ROOT not in path.parents:
        raise HTTPException(
            status_code=400, detail="Resume path is outside the artifacts directory"
        )
    if not path.is_file():
        raise HTTPException(
            status_code=410,
            detail="The tailored CV file is gone from disk. Prepare the application again.",
        )

    job = await JobRepository(db).get_by_id(run.job_id)
    stem = "cv"
    if job is not None:
        stem = f"{job.company}-{job.role}".replace(" ", "-")
        stem = "".join(char for char in stem if char.isalnum() or char in "-_")[:80] or "cv"

    return FileResponse(path, media_type="application/pdf", filename=f"{stem}.pdf")


@router.post("/{run_id}/resume/regenerate")
async def regenerate_tailored_resume(run_id: str, db: AsyncSession = Depends(get_db)):
    """Rebuilds the tailored CV with the current tailoring, replacing the old one.

    Use it after changing the master CV, or on applications prepared before the
    tailoring understood the job. The superseded CV is deleted from Reactive
    Resume so the account does not fill with near-duplicates.
    """
    service = ResumeRegenerationService(db)
    try:
        result = await service.regenerate(run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not rebuild the CV: {exc}")
    return {"status": "success", **result}
