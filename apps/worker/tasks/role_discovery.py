import asyncio

from apps.worker.celery_app import celery_app
from packages.persistence.database import AsyncSessionLocal
from packages.role_discovery.service import RoleDiscoveryService


@celery_app.task(name="apps.worker.tasks.role_discovery.refresh_role_map")
def refresh_role_map(use_llm: bool = True):
    """Rebuilds the capability graph, role map and search slate."""

    async def _run():
        async with AsyncSessionLocal() as session:
            summary = await RoleDiscoveryService(session).refresh(use_llm=use_llm)
            await session.commit()
            return summary

    return asyncio.run(_run())


@celery_app.task(name="apps.worker.tasks.role_discovery.learn_from_market")
def learn_from_market(use_llm: bool = True):
    """Retunes search priorities and proposes roles from imported jobs."""

    async def _run():
        async with AsyncSessionLocal() as session:
            report = await RoleDiscoveryService(session).learn_from_market(use_llm=use_llm)
            await session.commit()
            return {
                "summary": report.summary,
                "adjustments": len(report.adjustments),
                "proposed_roles": [role.title for role in report.proposed_roles],
                "auto_accepted": report.auto_accepted_role_ids,
            }

    return asyncio.run(_run())
