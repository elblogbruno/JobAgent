from celery import Celery
from config.settings import settings

celery_app = Celery(
    "jobagent_worker",
    broker=settings.rabbitmq_url,
    backend="rpc://",
    include=[
        "apps.worker.tasks.discovery",
        "apps.worker.tasks.submission",
        "apps.worker.tasks.monitoring",
        "apps.worker.tasks.imports",
        "apps.worker.tasks.role_discovery",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# Celery Beat Periodic Schedules
celery_app.conf.beat_schedule = {
    "run-job-discovery-every-2-hours": {
        "task": "apps.worker.tasks.discovery.discover_and_evaluate_jobs",
        "schedule": 7200.0, # every 2 hours
    },
    "monitor-applications-daily": {
        "task": "apps.worker.tasks.monitoring.run_application_monitor",
        "schedule": 14400.0, # every 4 hours
    },
    # Learn from what the user imported, then refresh the role map less often.
    "learn-from-imported-jobs-daily": {
        "task": "apps.worker.tasks.role_discovery.learn_from_market",
        "schedule": 86400.0, # every 24 hours
    },
    "refresh-role-map-weekly": {
        "task": "apps.worker.tasks.role_discovery.refresh_role_map",
        "schedule": 604800.0, # every 7 days
    },
}
