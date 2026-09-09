from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from packages.application_adapters.ashby import AshbyAdapter
from packages.application_adapters.base import ApplicationAdapter
from packages.application_adapters.generic import GenericApplicationAdapter
from packages.application_adapters.greenhouse import GreenhouseAdapter
from packages.application_adapters.lever import LeverAdapter
from packages.browser.locators import BlockedReason, CaptchaBlockedException, SemanticLocators
from packages.browser.session import BrowserSessionManager
from packages.candidate_profile.answer_vault import CandidateAnswerVault
from packages.candidate_profile.profile import CandidateProfileLoader
from packages.domain.enums import ApplicationStatus, ExecutionMode, Recommendation
from packages.domain.models import (
    CandidateProfileModel,
    CanonicalJob,
    JobSearchQuery,
    MatchScorecard,
    RawJob,
)
from packages.job_sources.feeds import ConfiguredFeedsSource
from packages.match_engine.engine import MatchEngine
from packages.normalizer.deduplicator import JobDeduplicator
from packages.normalizer.normalizer import JobNormalizer
from packages.persistence.repositories import (
    AgentDecisionRepository,
    ApplicationRunRepository,
    CandidateAnswerRepository,
    EventRepository,
    JobRepository,
    ManualQuestionRepository,
)
from packages.preflight.checker import ApplicationPreflight
from packages.reactive_resume.client import ReactiveResumeClient
from packages.reactive_resume.models import ApplicationUpdateRequest
from packages.resume_pipeline.cover_letter import CoverLetterAgent
from packages.resume_pipeline.tailor import ResumeAgent
from packages.telegram.bot import TelegramNotifier
from packages.verification.verifier import SubmissionVerifier


class JobAgentPipeline:
    def __init__(
        self,
        session: AsyncSession,
        profile: Optional[CandidateProfileModel] = None,
        rr_client: Optional[ReactiveResumeClient] = None,
        telegram_notifier: Optional[TelegramNotifier] = None,
    ):
        self.session = session
        self.profile = profile or CandidateProfileLoader.get()
        self.rr_client = rr_client or ReactiveResumeClient()
        self.telegram = telegram_notifier or TelegramNotifier()

        # Repositories
        self.job_repo = JobRepository(session)
        self.run_repo = ApplicationRunRepository(session)
        self.event_repo = EventRepository(session)
        self.decision_repo = AgentDecisionRepository(session)
        self.manual_q_repo = ManualQuestionRepository(session)

        # Components
        self.answer_vault = CandidateAnswerVault(session)
        self.match_engine = MatchEngine()
        self.resume_agent = ResumeAgent(self.rr_client, self.profile)
        self.cover_letter_agent = CoverLetterAgent(self.profile, rr_client=self.rr_client)
        self.deduplicator = JobDeduplicator(session, self.rr_client)

        # Adapters
        self.adapters: List[ApplicationAdapter] = [
            GreenhouseAdapter(),
            LeverAdapter(),
            AshbyAdapter(),
            GenericApplicationAdapter(),
        ]

    async def run_discovery_cycle(self, limit: int = 20) -> List[CanonicalJob]:
        """Discovers jobs, normalizes, deduplicates, and evaluates them."""
        feeds = ConfiguredFeedsSource()
        query = JobSearchQuery(limit=limit, remote=self.profile.job_preferences.remote)
        raw_jobs = await feeds.search(query)

        processed_jobs: List[CanonicalJob] = []

        for raw in raw_jobs:
            canonical = JobNormalizer.normalize(raw)

            # Check duplication
            is_dup, reason = await self.deduplicator.is_duplicate(canonical)
            if is_dup:
                canonical.status = ApplicationStatus.DUPLICATE
                await self.job_repo.create_or_update(canonical)
                continue

            # Evaluate with Match Engine
            scorecard = await self.match_engine.evaluate(canonical, self.profile)

            # Save canonical job
            if scorecard.recommendation == Recommendation.IGNORE:
                canonical.status = ApplicationStatus.IGNORED
            else:
                canonical.status = ApplicationStatus.EVALUATED

            job_orm = await self.job_repo.create_or_update(canonical)
            canonical.id = job_orm.id

            # Record Agent Decision
            await self.decision_repo.record(
                run_id=job_orm.id,
                agent_name="JobAnalysisAgent",
                decision=scorecard.recommendation.value,
                confidence=scorecard.confidence,
                reason=f"Score: {scorecard.score}/100. Fit: {scorecard.seniority_fit}",
                input_summary={"company": canonical.company, "role": canonical.role},
                evidence=scorecard.strengths,
            )

            processed_jobs.append(canonical)

            # Process candidates eligible for preparation
            if scorecard.recommendation in (Recommendation.APPLY, Recommendation.PREPARE):
                await self.process_job_application(canonical, scorecard)

        return processed_jobs

    async def process_job_application(
        self,
        job: CanonicalJob,
        scorecard: MatchScorecard
    ) -> Optional[str]:
        """
        Executes end-to-end preparation, document generation, and browser application.
        """
        mode = self.profile.application_preferences.execution_mode.value

        # 1. Create DB ApplicationRun
        app_run = await self.run_repo.create(
            job_id=job.id,
            execution_mode=mode,
            match_score=scorecard.score,
            scorecard=scorecard.model_dump(),
        )

        await self.event_repo.log(
            event_type="APPLICATION_STARTED",
            message=f"Starting application pipeline for {job.company} — {job.role}",
            application_run_id=app_run.id,
            job_id=job.id,
        )

        # 2. Document preparation in Reactive Resume
        try:
            rr_app, pdf_path, pdf_bytes = await self.resume_agent.prepare_application_and_resume(
                job=job,
                match_score=scorecard.score,
                execution_mode=mode,
            )
            app_run.reactive_resume_application_id = rr_app.id
            app_run.tailored_resume_path = pdf_path
            app_run.status = ApplicationStatus.READY.value

            # Draft Cover Letter
            cl_text = await self.cover_letter_agent.generate(job, application_id=rr_app.id)
            app_run.cover_letter_text = cl_text

            await self.session.flush()

        except Exception as exc:
            await self.run_repo.update_status(
                app_run.id,
                status=ApplicationStatus.FAILED.value,
                error_message=f"Document generation failed: {exc}",
                error_category="DOCUMENT_ERROR",
            )
            return app_run.id

        # Check execution mode constraints
        if mode == ExecutionMode.DISCOVERY_ONLY.value:
            await self.run_repo.update_status(app_run.id, status=ApplicationStatus.EVALUATED.value)
            return app_run.id

        if mode == ExecutionMode.PREPARE.value:
            await self.run_repo.update_status(app_run.id, status=ApplicationStatus.READY.value)
            return app_run.id

        if mode == ExecutionMode.REVIEW_BEFORE_SUBMIT.value:
            await self.run_repo.update_status(app_run.id, status=ApplicationStatus.READY_FOR_REVIEW.value)
            await self.telegram.notify_review_prompt(job, scorecard, app_run.id)
            return app_run.id

        # 3. Mode is AUTO_APPLY -> Execute browser submission
        if mode == ExecutionMode.AUTO_APPLY.value:
            await self.execute_browser_submission(app_run.id, job, pdf_path, cl_text, scorecard)

        return app_run.id

    async def execute_browser_submission(
        self,
        run_id: str,
        job: CanonicalJob,
        pdf_path: str,
        cover_letter_text: str,
        scorecard: MatchScorecard,
    ) -> bool:
        """Launches Playwright and submits the job application form."""
        browser_mgr = BrowserSessionManager()
        try:
            page = await browser_mgr.new_page()
            await self.run_repo.update_status(run_id, status=ApplicationStatus.APPLYING.value)

            # Navigate to job application page
            await page.goto(job.apply_url, wait_until="domcontentloaded")

            # Check for CAPTCHA / anti-bot
            blocked_reason = await SemanticLocators.check_for_anti_bot(page)
            if blocked_reason:
                await self.run_repo.update_status(
                    run_id,
                    status=ApplicationStatus.BLOCKED.value,
                    error_message=f"Application blocked by {blocked_reason.value}",
                    error_category=blocked_reason.value,
                )
                await self.telegram.notify_blocked(job, blocked_reason.value)
                return False

            # Select suitable adapter
            selected_adapter = None
            for adapter in self.adapters:
                if await adapter.can_handle(job.apply_url, page):
                    selected_adapter = adapter
                    break

            if not selected_adapter:
                selected_adapter = GenericApplicationAdapter()

            # Fill the application form
            await selected_adapter.fill(
                page=page,
                profile=self.profile,
                resume_pdf_path=pdf_path,
                cover_letter_text=cover_letter_text,
                answer_vault=self.answer_vault,
            )

            # Preflight Check
            preflight = ApplicationPreflight(
                profile=self.profile,
                job=job,
                tailored_resume_path=pdf_path,
                match_score=scorecard.score,
            )
            preflight_report = await preflight.run_checks(page)
            if not preflight_report.passed:
                await self.run_repo.update_status(
                    run_id,
                    status=ApplicationStatus.FAILED.value,
                    error_message=f"Preflight failed: {'; '.join(preflight_report.failure_reasons)}",
                    error_category="PREFLIGHT_FAILED",
                )
                return False

            # Submit
            await self.run_repo.update_status(run_id, status=ApplicationStatus.SUBMITTED_UNVERIFIED.value)
            await selected_adapter.submit(page)

            # Wait and verify
            await page.wait_for_timeout(4000)
            evidence = await SubmissionVerifier.verify(page)

            if evidence.verified:
                await self.run_repo.update_status(run_id, status=ApplicationStatus.APPLIED.value)

                # Update Reactive Resume application status
                app_run = await self.run_repo.get_by_id(run_id)
                if app_run and app_run.reactive_resume_application_id:
                    try:
                        await self.rr_client.update_application(
                            app_run.reactive_resume_application_id,
                            ApplicationUpdateRequest(status="applied")
                        )
                        await self.rr_client.log_application_note(
                            app_run.reactive_resume_application_id,
                            f"Application submitted and verified via Job Agent. Evidence: {evidence.details}"
                        )
                    except Exception:
                        pass

                # Send Telegram notification card
                cv_name = Path(pdf_path).name.replace(".pdf", "")
                await self.telegram.notify_submission(job, scorecard, cv_name)
                return True
            else:
                await self.run_repo.update_status(
                    run_id,
                    status=ApplicationStatus.SUBMITTED_UNVERIFIED.value,
                    error_message="Submission clicked but verification evidence was unconfirmed.",
                    error_category="UNVERIFIED",
                )
                return False

        except CaptchaBlockedException as c_err:
            await self.run_repo.update_status(
                run_id,
                status=ApplicationStatus.BLOCKED.value,
                error_message=str(c_err),
                error_category=c_err.reason.value,
            )
            await self.telegram.notify_blocked(job, c_err.reason.value)
            return False

        except Exception as exc:
            await self.run_repo.update_status(
                run_id,
                status=ApplicationStatus.FAILED.value,
                error_message=f"Browser submission error: {exc}",
                error_category="BROWSER_ERROR",
            )
            return False

        finally:
            await browser_mgr.close()
