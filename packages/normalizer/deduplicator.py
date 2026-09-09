from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from packages.domain.models import CanonicalJob
from packages.persistence.repositories import JobRepository
from packages.reactive_resume.client import ReactiveResumeClient


class JobDeduplicator:
    def __init__(
        self,
        session: AsyncSession,
        reactive_resume_client: Optional[ReactiveResumeClient] = None
    ):
        self.session = session
        self.repo = JobRepository(session)
        self.rr_client = reactive_resume_client

    async def is_duplicate(self, job: CanonicalJob) -> Tuple[bool, str]:
        """
        Returns (True, reason) if already applied or recorded; otherwise (False, "").
        """
        # 1. Local Database check by dedup_hash
        existing = await self.repo.get_by_hash(job.dedup_hash)
        if existing and existing.status in ("APPLIED", "READY", "PREPARING", "DUPLICATE"):
            return True, f"Already recorded locally with status {existing.status} (ID: {existing.id})"

        # 2. Reactive Resume Application tracker check
        if self.rr_client:
            try:
                applications = await self.rr_client.list_applications(include_archived=True)
                job_comp = job.normalized_company.lower()
                job_role = job.normalized_role.lower()

                for app in applications:
                    app_comp = app.company.strip().lower()
                    app_role = app.role.strip().lower()

                    # Exact company match and strong role substring match
                    if (app_comp == job_comp or app_comp in job_comp or job_comp in app_comp) and (
                        app_role in job_role or job_role in app_role
                    ):
                        return True, f"Found existing application in Reactive Resume: {app.company} — {app.role} (Status: {app.status})"
            except Exception:
                # If Reactive Resume is unreachable or mocked, fail open for discovery deduplication
                pass

        return False, ""
