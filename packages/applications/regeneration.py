"""Rebuilding the tailored CV for an application that already has one.

Preparing a job creates a derived CV in Reactive Resume. Rebuilding it must not
leave the old one behind, or a few weeks of applying fills the account with
near-duplicates nobody can tell apart.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from packages.candidate_profile.profile import CandidateProfileLoader
from packages.domain.enums import ApplicationStatus, ExecutionMode, Recommendation
from packages.domain.models import CandidateProfileModel, MatchScorecard
from packages.llm.gateway import LLMGateway
from packages.persistence.repositories import (
    ApplicationRunRepository,
    EventRepository,
    JobRepository,
)
from packages.reactive_resume.client import ReactiveResumeClient
from packages.resume_pipeline.tailor import ResumeAgent


class ResumeRegenerationService:
    def __init__(
        self,
        session: AsyncSession,
        profile: Optional[CandidateProfileModel] = None,
        rr_client: Optional[ReactiveResumeClient] = None,
        llm_gateway: Optional[LLMGateway] = None,
    ):
        self.session = session
        self.profile = profile or CandidateProfileLoader.get()
        self.rr_client = rr_client or ReactiveResumeClient()
        self.gateway = llm_gateway
        self.job_repo = JobRepository(session)
        self.run_repo = ApplicationRunRepository(session)
        self.event_repo = EventRepository(session)

    async def regenerate(self, run_id: str) -> Dict[str, Any]:
        """Rebuilds the tailored CV for one application, replacing the old one."""
        run = await self.run_repo.get_by_id(run_id)
        if run is None:
            raise LookupError("Application run not found")

        job_orm = await self.job_repo.get_by_id(run.job_id)
        if job_orm is None:
            raise LookupError("The job this application belongs to no longer exists")

        from packages.job_import.service import _canonical_from_orm

        job = _canonical_from_orm(job_orm)
        job.id = job_orm.id
        scorecard = _scorecard_from(job_orm)
        previous_resume_id = run.reactive_resume_resume_id

        agent = ResumeAgent(
            rr_client=self.rr_client, profile=self.profile, llm_gateway=self.gateway
        )
        rr_app, pdf_path, _ = await agent.prepare_application_and_resume(
            job=job,
            match_score=scorecard.score,
            execution_mode=ExecutionMode.PREPARE.value,
            scorecard=scorecard,
        )

        run.reactive_resume_application_id = rr_app.id
        run.reactive_resume_resume_id = agent.last_derived_resume_id
        run.tailored_resume_path = pdf_path
        # A successful rebuild means the documents exist, so a run still working
        # towards them is ready. States that came later, such as APPLIED or
        # INTERVIEW, describe the outside world and are left untouched.
        if run.status in (
            ApplicationStatus.EVALUATED.value,
            ApplicationStatus.PREPARING.value,
            ApplicationStatus.NEEDS_USER_INPUT.value,
            ApplicationStatus.FAILED.value,
        ):
            run.status = ApplicationStatus.READY.value
        run.updated_at = datetime.utcnow()
        await self.session.flush()

        removed = await self._remove_previous(previous_resume_id, agent.last_derived_resume_id)
        plan = agent.last_tailoring

        message = (
            f"Tailored CV rebuilt for {job_orm.company} — {job_orm.role}"
            f" ({plan.generated_by if plan else 'unknown'})"
        )
        if plan and plan.rejected:
            message += f", rejecting {len(plan.rejected)} unsupported claim(s)"
        if removed:
            message += ". The previous CV was deleted"

        await self.event_repo.log(
            event_type="RESUME_REGENERATED",
            message=message,
            application_run_id=run.id,
            job_id=run.job_id,
            severity="WARNING" if agent.last_patch_error else "INFO",
            details={
                "previous_resume_id": previous_resume_id,
                "resume_id": agent.last_derived_resume_id,
                "previous_deleted": removed,
                "headline": plan.headline if plan else None,
                "rejected": plan.rejected if plan else [],
                "patch_error": agent.last_patch_error,
            },
        )

        return {
            "runId": run.id,
            "jobId": run.job_id,
            "resumeId": agent.last_derived_resume_id,
            "previousResumeDeleted": removed,
            "headline": plan.headline if plan else None,
            "generatedBy": plan.generated_by if plan else None,
            "rejected": plan.rejected if plan else [],
            "patchError": agent.last_patch_error,
            "message": message,
        }

    async def _remove_previous(self, previous_id: Optional[str], new_id: Optional[str]) -> bool:
        """Deletes the superseded CV, unless it is the master or the new one."""
        if not previous_id or previous_id == new_id:
            return False
        if previous_id == self.profile.reactive_resume.master_resume_id:
            return False
        try:
            return await self.rr_client.delete_resume(previous_id)
        except Exception:
            # A leftover CV is untidy; failing the rebuild over it would be worse.
            return False


def _scorecard_from(job_orm) -> MatchScorecard:
    """Reuses the stored evaluation so rebuilding costs one model call, not two."""
    stored = job_orm.scorecard
    if isinstance(stored, dict) and stored:
        try:
            return MatchScorecard.model_validate(stored)
        except Exception:
            pass
    return MatchScorecard(
        score=job_orm.match_score or 0,
        recommendation=Recommendation.PREPARE,
        confidence=0.5,
    )
