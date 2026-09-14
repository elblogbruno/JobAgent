import asyncio

from apps.worker.celery_app import celery_app
from packages.job_import.service import BrowserImportService
from packages.persistence.database import AsyncSessionLocal


@celery_app.task(name="apps.worker.tasks.imports.analyze_imported_job")
def analyze_imported_job(job_id: str, prepare: bool = False, forced: bool = False):
    """Scores a browser-imported job and optionally prepares its documents.

    Runs off the request path so the extension never waits on a model call.
    """

    async def _run():
        async with AsyncSessionLocal() as session:
            service = BrowserImportService(session)
            result = await service.analyze(job_id, prepare=prepare, forced=forced)
            await session.commit()
            return result.to_api_dict()

    return asyncio.run(_run())
