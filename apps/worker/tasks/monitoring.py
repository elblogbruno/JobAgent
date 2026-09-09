import asyncio
from apps.worker.celery_app import celery_app
from packages.monitoring.monitor import ApplicationMonitor
from packages.reactive_resume.client import ReactiveResumeClient


@celery_app.task(name="apps.worker.tasks.monitoring.run_application_monitor")
def run_application_monitor():
    async def _run():
        rr_client = ReactiveResumeClient()
        monitor = ApplicationMonitor(rr_client=rr_client)
        due = await monitor.check_follow_ups()
        return len(due)

    return asyncio.run(_run())
