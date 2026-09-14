"""The browser import pipeline: capture in, scored job out.

Importing is split in two on purpose. ``import_job`` parses, deduplicates and
stores, and returns immediately so the extension can show a result while the user
keeps browsing. ``analyze`` then scores the job and, when asked, prepares the
application documents.
"""

from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from packages.candidate_profile.profile import (
    CandidateProfileLoader,
    is_company_allowed,
    is_role_allowed,
)
from packages.domain.enums import (
    ApplicationStatus,
    DiscoveryChannel,
    ExecutionMode,
    Recommendation,
)
from packages.domain.models import CandidateProfileModel, CanonicalJob
from packages.domain.role_discovery import (
    BrowserJobCapture,
    JobImportResult,
    JobProvenance,
)
from packages.job_import.canonical import strip_tracking_params
from packages.job_import.extractor import BrowserJobExtractor
from packages.llm.gateway import LLMGateway
from packages.match_engine.engine import MatchEngine
from packages.normalizer.normalizer import JobNormalizer
from packages.persistence.models import JobORM
from packages.persistence.repositories import (
    ApplicationRunRepository,
    EventRepository,
    JobRepository,
)
from packages.reactive_resume.client import ReactiveResumeClient
from packages.role_discovery.service import RoleDiscoveryService


class BrowserImportService:
    def __init__(
        self,
        session: AsyncSession,
        profile: Optional[CandidateProfileModel] = None,
        rr_client: Optional[ReactiveResumeClient] = None,
        llm_gateway: Optional[LLMGateway] = None,
    ):
        self.session = session
        self.profile = profile or CandidateProfileLoader.get()
        self.rr_client = rr_client
        gateway = llm_gateway or LLMGateway.get()

        self.extractor = BrowserJobExtractor(gateway)
        self.match_engine = MatchEngine(gateway)
        self.job_repo = JobRepository(session)
        self.run_repo = ApplicationRunRepository(session)
        self.event_repo = EventRepository(session)
        self.role_service = RoleDiscoveryService(
            session, profile=self.profile, rr_client=rr_client, llm_gateway=gateway
        )
        #: Why the last preparation failed, so the caller can say so.
        self.last_prepare_error: str = ""

    # -- duplicate detection -----------------------------------------------

    async def find_existing(
        self,
        canonical_url: Optional[str] = None,
        page_url: Optional[str] = None,
        dedup_hash: Optional[str] = None,
        source: Optional[str] = None,
        source_job_id: Optional[str] = None,
        fingerprint: Optional[str] = None,
        normalized_company: Optional[str] = None,
        normalized_role: Optional[str] = None,
    ) -> Tuple[Optional[JobORM], str]:
        """Checks every signal in turn. Returns (job, which signal matched)."""
        if dedup_hash:
            existing = await self.job_repo.get_by_hash(dedup_hash)
            if existing:
                return existing, "dedup hash"

        # Both directions matter: the aggregator page the user is looking at and the
        # company ATS page it points to. Either one identifies the same job.
        for url in (canonical_url, page_url):
            if not url:
                continue
            cleaned = strip_tracking_params(url)
            existing = await self.job_repo.get_by_canonical_url(cleaned)
            if existing:
                return existing, "canonical URL"
            existing = await self.job_repo.get_by_source_url(cleaned)
            if existing:
                return existing, "source URL"

        if source and source_job_id:
            existing = await self.job_repo.get_by_source_job_id(source, source_job_id)
            if existing:
                return existing, "source job id"

        if fingerprint:
            existing = await self.job_repo.get_by_fingerprint(fingerprint)
            if existing:
                return existing, "description fingerprint"

        if normalized_company and normalized_role:
            existing = await self.job_repo.find_by_company_and_role(
                normalized_company, normalized_role
            )
            if existing:
                return existing, "company and title"

        return None, ""

    async def lookup(self, url: str) -> Optional[JobImportResult]:
        """Answers 'have I already imported this page?' before any parsing happens."""
        existing, matched_on = await self.find_existing(canonical_url=url, page_url=url)
        if existing is None:
            return None
        return await self._result_for_existing(existing, matched_on)

    # -- import ------------------------------------------------------------

    async def import_job(
        self,
        capture: BrowserJobCapture,
        allow_llm: bool = True,
    ) -> JobImportResult:
        raw = await self.extractor.extract(capture, allow_llm=allow_llm)
        canonical = JobNormalizer.normalize(raw)
        fingerprint = JobNormalizer.description_fingerprint(canonical.description)

        existing, matched_on = await self.find_existing(
            canonical_url=canonical.canonical_url,
            page_url=capture.url,
            dedup_hash=canonical.dedup_hash,
            source=canonical.source.value,
            source_job_id=canonical.source_job_id,
            fingerprint=fingerprint,
            normalized_company=canonical.normalized_company,
            normalized_role=canonical.normalized_role,
        )
        if existing is not None:
            return await self._result_for_existing(existing, matched_on)

        if not is_role_allowed(self.profile, canonical.role) or not is_company_allowed(
            self.profile, canonical.company
        ):
            canonical.status = ApplicationStatus.IGNORED
        else:
            canonical.status = ApplicationStatus.NORMALIZED

        provenance = JobProvenance(
            source=canonical.source.value,
            discovered_by=capture.discovered_by or DiscoveryChannel.BROWSER_EXTENSION,
            search_query_id=capture.search_query_id,
            search_provider=capture.search_provider,
            source_url=strip_tracking_params(capture.url),
            canonical_url=canonical.canonical_url,
        )
        job_orm = await self.job_repo.create_or_update(
            canonical, provenance=provenance, description_fingerprint=fingerprint
        )

        await self.role_service.record_job_imported(capture.search_query_id)
        await self.event_repo.log(
            event_type="JOB_IMPORTED_FROM_BROWSER",
            message=f"Imported {canonical.company} — {canonical.role} from {capture.hostname}",
            job_id=job_orm.id,
            details={
                "source_url": capture.url,
                "canonical_url": canonical.canonical_url,
                "search_query_id": capture.search_query_id,
                "search_provider": capture.search_provider,
                "extraction": raw.raw_payload.get("extraction_strategies", []),
            },
        )

        excluded = canonical.status == ApplicationStatus.IGNORED
        return JobImportResult(
            status="imported",
            job_id=job_orm.id,
            company=canonical.company,
            role=canonical.role,
            location=canonical.location,
            canonical_url=canonical.canonical_url,
            apply_url=canonical.apply_url,
            job_status=canonical.status.value,
            analysis_state="skipped" if excluded else "pending",
            prepare_requested=capture.prepare_application,
            message=(
                "Job saved but excluded by your profile filters."
                if excluded
                else "Job imported. Analysing the match now."
            ),
            dashboard_url=self._dashboard_url(job_orm.id),
        )

    # -- analysis ----------------------------------------------------------

    async def analyze(
        self,
        job_id: str,
        prepare: bool = False,
        forced: bool = False,
    ) -> JobImportResult:
        """Scores an imported job and optionally prepares its application.

        ``forced`` means a person pressed the button. That overrides the match
        threshold: the candidate can see the score and still want the CV, and
        silently refusing an explicit request is worse than preparing a CV for a
        job they will not send.
        """
        job_orm = await self.job_repo.get_by_id(job_id)
        if job_orm is None:
            return JobImportResult(
                status="rejected", analysis_state="failed", message="Job not found."
            )

        canonical = _canonical_from_orm(job_orm)
        scorecard = await self.match_engine.evaluate(canonical, self.profile)

        job_orm.match_score = scorecard.score
        job_orm.scorecard = scorecard.model_dump(mode="json")
        job_orm.status = (
            ApplicationStatus.IGNORED.value
            if scorecard.recommendation == Recommendation.IGNORE
            else ApplicationStatus.EVALUATED.value
        )
        job_orm.updated_at = datetime.utcnow()
        await self.session.flush()

        await self.role_service.record_match_score(job_orm.search_query_id, scorecard.score)

        primary_role = await self._primary_role_title()
        result = JobImportResult(
            status="imported",
            job_id=job_orm.id,
            company=job_orm.company,
            role=job_orm.role,
            location=job_orm.location,
            canonical_url=job_orm.canonical_url,
            apply_url=job_orm.apply_url,
            match_score=scorecard.score,
            recommendation=scorecard.recommendation.value,
            primary_role=primary_role,
            strengths=scorecard.strengths[:5],
            gaps=scorecard.gaps[:5],
            job_status=job_orm.status,
            analysis_state="complete",
            prepare_requested=prepare,
            message=f"Match {scorecard.score}/100 — {scorecard.recommendation.value}.",
            dashboard_url=self._dashboard_url(job_orm.id),
        )

        if prepare:
            if scorecard.recommendation == Recommendation.IGNORE and not forced:
                result.preparation_state = "skipped"
                result.preparation_error = (
                    f"El match es {scorecard.score}/100, por debajo de tu umbral de "
                    f"{self.profile.application_preferences.prepare_threshold}. "
                    "Pulsa Preparar CV si quieres el CV igualmente."
                )
                result.message += " CV no preparado."
            else:
                run_id = await self._prepare_application(canonical, scorecard, job_orm.id)
                if run_id:
                    result.application_run_id = run_id
                    await self.role_service.record_application_created(job_orm.search_query_id)
                    run = await self.run_repo.get_by_id(run_id)
                    if run is not None:
                        result.job_status = run.status
                        if run.tailored_resume_path:
                            result.preparation_state = "ready"
                            result.message += " CV adaptado listo."
                        else:
                            result.preparation_state = "failed"
                            result.preparation_error = (
                                run.error_message or "La preparación no produjo ningún CV."
                            )
                else:
                    result.preparation_state = "failed"
                    result.preparation_error = self.last_prepare_error or (
                        "No se pudo preparar el CV. Revisa el registro de eventos."
                    )

        await self.event_repo.log(
            event_type="IMPORTED_JOB_ANALYSED",
            message=(
                f"{job_orm.company} — {job_orm.role}: match {scorecard.score}/100 "
                f"({scorecard.recommendation.value})"
            ),
            job_id=job_orm.id,
            details={"prepare_requested": prepare, "search_query_id": job_orm.search_query_id},
        )
        return result

    async def _prepare_application(
        self,
        job: CanonicalJob,
        scorecard,
        job_id: str,
    ) -> Optional[str]:
        """Prepares documents only.

        Importing a job never submits an application. Submission stays with the
        pipeline's configured execution mode, so the profile is copied here with
        PREPARE forced on.
        """
        from packages.agents.pipeline_agent import JobAgentPipeline

        prepare_profile = self.profile.model_copy(deep=True)
        prepare_profile.application_preferences.execution_mode = ExecutionMode.PREPARE

        pipeline = JobAgentPipeline(self.session, profile=prepare_profile, rr_client=self.rr_client)
        job.id = job_id
        try:
            return await pipeline.process_job_application(job, scorecard)
        except Exception as exc:
            self.last_prepare_error = str(exc)
            await self.event_repo.log(
                event_type="IMPORT_PREPARE_FAILED",
                message=f"Could not prepare the application: {exc}",
                job_id=job_id,
                severity="ERROR",
            )
            return None

    # -- status ------------------------------------------------------------

    async def status_for(self, job_id: str) -> Optional[JobImportResult]:
        job_orm = await self.job_repo.get_by_id(job_id)
        if job_orm is None:
            return None
        return await self._result_for_existing(job_orm, "")

    async def _result_for_existing(
        self,
        job_orm: JobORM,
        matched_on: str,
    ) -> JobImportResult:
        run = await self.run_repo.get_by_job_id(job_orm.id)
        scorecard = job_orm.scorecard or {}
        analysed = job_orm.match_score is not None

        preparation_state = "none"
        preparation_error = ""
        if run is not None:
            if run.tailored_resume_path:
                preparation_state = "ready"
            elif run.status == ApplicationStatus.FAILED.value:
                preparation_state = "failed"
                preparation_error = run.error_message or "La preparación falló."

        return JobImportResult(
            status="duplicate" if matched_on else "imported",
            job_id=job_orm.id,
            company=job_orm.company,
            role=job_orm.role,
            location=job_orm.location,
            canonical_url=job_orm.canonical_url,
            apply_url=job_orm.apply_url,
            match_score=job_orm.match_score,
            recommendation=scorecard.get("recommendation"),
            primary_role=await self._primary_role_title(),
            strengths=list(scorecard.get("strengths") or [])[:5],
            gaps=list(scorecard.get("gaps") or [])[:5],
            application_run_id=run.id if run else None,
            job_status=run.status if run else job_orm.status,
            analysis_state="complete" if analysed else "pending",
            preparation_state=preparation_state,
            preparation_error=preparation_error,
            message=(f"Already imported (matched on {matched_on})." if matched_on else "Imported."),
            dashboard_url=self._dashboard_url(job_orm.id),
        )

    async def _primary_role_title(self) -> Optional[str]:
        try:
            role_map = await self.role_service.get_role_map()
        except Exception:
            return None
        if role_map is None:
            return None
        primary = role_map.primary
        return primary[0].title if primary else None

    def _dashboard_url(self, job_id: str) -> str:
        base = (self.profile.extension.dashboard_url or "").rstrip("/")
        return f"{base}/?job={job_id}" if base else f"/?job={job_id}"


def _canonical_from_orm(job: JobORM) -> CanonicalJob:
    from packages.domain.enums import JobSourceType

    try:
        source = JobSourceType(job.source)
    except ValueError:
        source = JobSourceType.GENERIC_WEB

    return CanonicalJob(
        id=job.id,
        dedup_hash=job.dedup_hash,
        company=job.company,
        normalized_company=job.normalized_company,
        role=job.role,
        normalized_role=job.normalized_role,
        canonical_url=job.canonical_url,
        apply_url=job.apply_url,
        source=source,
        source_job_id=job.source_job_id,
        location=job.location,
        is_remote=bool(job.is_remote),
        is_hybrid=bool(job.is_hybrid),
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        salary_currency=job.salary_currency,
        description=job.description or "",
        requirements=job.requirements or [],
        preferred_requirements=job.preferred_requirements or [],
        technologies=job.technologies or [],
        status=ApplicationStatus(job.status) if job.status else ApplicationStatus.NORMALIZED,
        published_at=job.published_at,
        discovered_at=job.discovered_at or datetime.utcnow(),
    )
