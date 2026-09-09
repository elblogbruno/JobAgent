from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from packages.domain.models import CanonicalJob
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
    }
