"""Scheduling the expensive half of an import.

The extension must never wait for a model call. Import returns as soon as the job
is stored, and scoring plus document preparation happen afterwards: on the Celery
worker when a broker is reachable, otherwise in a FastAPI background task.
"""

import logging
from typing import Optional

from fastapi import BackgroundTasks

logger = logging.getLogger(__name__)


async def _analyze_in_process(job_id: str, prepare: bool, forced: bool = False) -> None:
    from packages.job_import.service import BrowserImportService
    from packages.persistence.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        try:
            service = BrowserImportService(session)
            await service.analyze(job_id, prepare=prepare, forced=forced)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("In-process analysis failed for job %s", job_id)


def schedule_job_analysis(
    job_id: str,
    prepare: bool,
    background_tasks: Optional[BackgroundTasks] = None,
    forced: bool = False,
) -> str:
    """Queues analysis and returns where it was queued: 'celery' or 'background'."""
    try:
        from apps.worker.tasks.imports import analyze_imported_job

        analyze_imported_job.apply_async(args=[job_id, prepare, forced], retry=False)
        return "celery"
    except Exception as exc:
        logger.info("Falling back to in-process analysis for job %s: %s", job_id, exc)

    if background_tasks is not None:
        background_tasks.add_task(_analyze_in_process, job_id, prepare, forced)
        return "background"
    return "none"
