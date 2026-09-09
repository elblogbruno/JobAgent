import asyncio
from apps.worker.celery_app import celery_app
from packages.agents.pipeline_agent import JobAgentPipeline
from packages.persistence.database import AsyncSessionLocal


@celery_app.task(name="apps.worker.tasks.discovery.discover_and_evaluate_jobs")
def discover_and_evaluate_jobs(limit: int = 20):
    async def _run():
        async with AsyncSessionLocal() as session:
            pipeline = JobAgentPipeline(session=session)
            jobs = await pipeline.run_discovery_cycle(limit=limit)
            await session.commit()
            return len(jobs)

    loop = asyncio.get_event_loop()
    if loop.is_running():
        import nest_asyncio
        nest_asyncio.apply()
        return loop.run_until_complete(_run())
    else:
        return asyncio.run(_run())
