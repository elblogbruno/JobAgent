import asyncio
from apps.worker.celery_app import celery_app
from packages.agents.pipeline_agent import JobAgentPipeline
from packages.persistence.database import AsyncSessionLocal
from packages.persistence.repositories import ApplicationRunRepository, JobRepository


@celery_app.task(name="apps.worker.tasks.submission.submit_application_task")
def submit_application_task(run_id: str):
    async def _run():
        async with AsyncSessionLocal() as session:
            pipeline = JobAgentPipeline(session=session)
            run_repo = ApplicationRunRepository(session)
            job_repo = JobRepository(session)

            run = await run_repo.get_by_id(run_id)
            if not run or not run.tailored_resume_path:
                return False

            job_orm = await job_repo.get_by_id(run.job_id)
            if not job_orm:
                return False

            # Convert ORM to CanonicalJob
            canonical = await job_repo.get_by_id(job_orm.id)
            # Run browser submission
            result = await pipeline.execute_browser_submission(
                run_id=run.id,
                job=canonical,
                pdf_path=run.tailored_resume_path,
                cover_letter_text=run.cover_letter_text or "",
                scorecard=run.scorecard,
            )
            await session.commit()
            return result

    return asyncio.run(_run())
