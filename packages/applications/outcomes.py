"""Recording what actually happened to an application.

Most applications in this system are prepared or submitted by the agent, but the
candidate also applies by hand, gets interviews and gets rejected. Those outcomes
are the only ground truth the RoleDiscoveryAgent has about whether a search was
worth running, so there has to be one way to report them.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from packages.candidate_profile.profile import CandidateProfileLoader
from packages.domain.enums import ApplicationStatus, ExecutionMode
from packages.domain.models import CandidateProfileModel
from packages.domain.state_machine import InvalidStateTransitionError, validate_outcome
from packages.persistence.models import ApplicationRunORM, JobORM
from packages.persistence.repositories import (
    ApplicationRunRepository,
    EventRepository,
    JobRepository,
)
from packages.reactive_resume.client import ReactiveResumeClient
from packages.reactive_resume.models import ApplicationUpdateRequest
from packages.role_discovery.service import RoleDiscoveryService

#: The outcomes a person can report, and the status each one sets.
OUTCOMES: Dict[str, ApplicationStatus] = {
    "applied": ApplicationStatus.APPLIED,
    "interview": ApplicationStatus.INTERVIEW,
    "offer": ApplicationStatus.OFFER,
    "rejected": ApplicationStatus.REJECTED,
    "withdrawn": ApplicationStatus.WITHDRAWN,
}

#: Reactive Resume's own vocabulary. It has no equivalent for withdrawn.
_REACTIVE_RESUME_STATUS: Dict[str, Optional[str]] = {
    "applied": "applied",
    "interview": "interview",
    "offer": "offer",
    "rejected": "rejected",
    "withdrawn": None,
}


class UnknownOutcomeError(ValueError):
    pass


class ApplicationOutcomeService:
    def __init__(
        self,
        session: AsyncSession,
        profile: Optional[CandidateProfileModel] = None,
        rr_client: Optional[ReactiveResumeClient] = None,
    ):
        self.session = session
        self.profile = profile or CandidateProfileLoader.get()
        self.rr_client = rr_client
        self.job_repo = JobRepository(session)
        self.run_repo = ApplicationRunRepository(session)
        self.event_repo = EventRepository(session)

    async def record_for_job(
        self,
        job_id: str,
        outcome: str,
        note: str = "",
        occurred_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Records an outcome against a job, creating its run if there is none.

        A job imported from the browser has no application run until documents are
        prepared, and the candidate may well have applied to it by hand first.
        """
        job = await self.job_repo.get_by_id(job_id)
        if job is None:
            raise LookupError("Job not found")

        run = await self.run_repo.get_by_job_id(job_id)
        if run is None:
            run = await self.run_repo.create(
                job_id=job_id,
                execution_mode=ExecutionMode.PREPARE.value,
                match_score=job.match_score,
                scorecard=job.scorecard,
            )
            run.status = ApplicationStatus.EVALUATED.value
            await self.session.flush()

        return await self.record(run.id, outcome, note=note, occurred_at=occurred_at, job=job)

    async def record(
        self,
        run_id: str,
        outcome: str,
        note: str = "",
        occurred_at: Optional[datetime] = None,
        job: Optional[JobORM] = None,
    ) -> Dict[str, Any]:
        key = (outcome or "").strip().lower()
        if key not in OUTCOMES:
            raise UnknownOutcomeError(f"outcome must be one of {sorted(OUTCOMES)}, got {outcome!r}")

        run = await self.run_repo.get_by_id(run_id)
        if run is None:
            raise LookupError("Application run not found")

        target = OUTCOMES[key]
        current = _status_of(run)
        # Raises InvalidStateTransitionError, which the route turns into a 409.
        validate_outcome(current, target, context=f"manual outcome '{key}'")

        job = job or await self.job_repo.get_by_id(run.job_id)
        history: List[Dict[str, Any]] = list(run.outcome_history or [])
        already_reported = {entry.get("outcome") for entry in history}
        timestamp = occurred_at or datetime.utcnow()

        history.append(
            {
                "outcome": key,
                "status": target.value,
                "previous_status": current.value,
                "at": timestamp.isoformat(),
                "note": note,
                "source": "manual",
            }
        )
        run.outcome_history = history
        run.status = target.value
        run.updated_at = datetime.utcnow()

        if target == ApplicationStatus.APPLIED:
            run.applied_at = timestamp
            # Only a submission the agent did not perform is a manual one.
            if current not in (
                ApplicationStatus.APPLYING,
                ApplicationStatus.SUBMITTED_UNVERIFIED,
            ):
                run.submitted_manually = True
                run.submission_evidence = {
                    "verified": True,
                    "evidence_type": "MANUAL_CONFIRMATION",
                    "details": note or "The candidate reported sending this application by hand.",
                    "timestamp": timestamp.isoformat(),
                }

        if job is not None:
            job.status = target.value
            job.updated_at = datetime.utcnow()

        await self.session.flush()

        await self._record_search_performance(job, key, already_reported)
        await self._sync_reactive_resume(run, key, note)

        await self.event_repo.log(
            event_type=f"OUTCOME_{target.value}",
            message=(
                f"{job.company if job else 'Application'} — "
                f"{job.role if job else run.job_id}: reported as {key}"
                + (f" ({note})" if note else "")
            ),
            application_run_id=run.id,
            job_id=run.job_id,
            details={"outcome": key, "previous_status": current.value, "source": "manual"},
        )

        return {
            "runId": run.id,
            "jobId": run.job_id,
            "outcome": key,
            "status": run.status,
            "previousStatus": current.value,
            "appliedAt": run.applied_at.isoformat() if run.applied_at else None,
            "submittedManually": bool(run.submitted_manually),
            "history": history,
        }

    async def undo_last(self, run_id: str) -> Dict[str, Any]:
        """Reverts the most recent reported outcome.

        Automatic detection can be wrong, and a mis-click on "La envié yo" should
        not be permanent. The entry is dropped from the history and the status
        goes back to what it was, so an application never sits in a state the
        candidate did not put it in.
        """
        run = await self.run_repo.get_by_id(run_id)
        if run is None:
            raise LookupError("Application run not found")

        history: List[Dict[str, Any]] = list(run.outcome_history or [])
        if not history:
            raise LookupError("This application has no reported outcome to undo")

        removed = history.pop()
        previous = str(removed.get("previous_status") or ApplicationStatus.EVALUATED.value)

        run.outcome_history = history
        run.status = previous
        if removed.get("outcome") == "applied":
            run.applied_at = None
            run.submitted_manually = False
            run.submission_evidence = None
        run.updated_at = datetime.utcnow()

        job = await self.job_repo.get_by_id(run.job_id)
        if job is not None:
            job.status = previous
            job.updated_at = datetime.utcnow()
        await self.session.flush()

        await self.event_repo.log(
            event_type="OUTCOME_UNDONE",
            message=(
                f"Undid '{removed.get('outcome')}' on "
                f"{job.company if job else run.job_id}, back to {previous}"
            ),
            application_run_id=run.id,
            job_id=run.job_id,
            severity="WARNING",
            details={"undone": removed},
        )

        return {
            "runId": run.id,
            "jobId": run.job_id,
            "status": run.status,
            "undone": removed.get("outcome"),
            "history": history,
        }

    async def _record_search_performance(
        self,
        job: Optional[JobORM],
        outcome: str,
        already_reported: set,
    ) -> None:
        """Feeds the outcome back to the search query that produced the job.

        Counted once per run, so re-reporting the same outcome does not inflate the
        numbers the RoleDiscoveryAgent uses to retune queries.
        """
        if job is None or not job.search_query_id or outcome in already_reported:
            return
        service = RoleDiscoveryService(self.session, profile=self.profile, rr_client=self.rr_client)
        if outcome == "applied":
            await service.record_application_created(job.search_query_id)
        elif outcome == "interview":
            await service.record_interview(job.search_query_id)

    async def _sync_reactive_resume(
        self,
        run: ApplicationRunORM,
        outcome: str,
        note: str,
    ) -> None:
        """Mirrors the outcome into Reactive Resume's application tracker."""
        if not run.reactive_resume_application_id:
            return
        status = _REACTIVE_RESUME_STATUS.get(outcome)
        client = self.rr_client or ReactiveResumeClient()
        try:
            if status:
                await client.update_application(
                    run.reactive_resume_application_id,
                    ApplicationUpdateRequest(status=status),
                )
            await client.log_application_note(
                run.reactive_resume_application_id,
                f"Reported as {outcome} from the Job Agent dashboard."
                + (f" {note}" if note else ""),
            )
        except Exception:
            # Reactive Resume being unreachable must not lose the local record.
            pass


def _status_of(run: ApplicationRunORM) -> ApplicationStatus:
    try:
        return ApplicationStatus(run.status)
    except ValueError:
        return ApplicationStatus.EVALUATED


__all__ = [
    "ApplicationOutcomeService",
    "InvalidStateTransitionError",
    "OUTCOMES",
    "UnknownOutcomeError",
]
