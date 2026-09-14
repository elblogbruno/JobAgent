from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from packages.agents.search_planner import SearchPlannerAgent
from packages.application_adapters.ashby import AshbyAdapter
from packages.application_adapters.base import ApplicationAdapter
from packages.application_adapters.generic import GenericApplicationAdapter
from packages.application_adapters.greenhouse import GreenhouseAdapter
from packages.application_adapters.infojobs_api import InfoJobsApiAdapter
from packages.application_adapters.lever import LeverAdapter
from packages.browser.locators import BlockedReason, CaptchaBlockedException, SemanticLocators
from packages.browser.session import BrowserSessionManager
from packages.candidate_profile.answer_vault import CandidateAnswerVault
from packages.candidate_profile.profile import (
    CandidateProfileLoader,
    is_company_allowed,
    is_role_allowed,
)
from packages.domain.enums import ApplicationStatus, ExecutionMode, Recommendation
from packages.domain.models import (
    CandidateProfileModel,
    CanonicalJob,
    MatchScorecard,
    RawJob,
    SearchPlan,
    SearchPlanEntry,
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
        self.search_planner = SearchPlannerAgent()
        self.infojobs_adapter = InfoJobsApiAdapter()
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
        """Plans the search, discovers jobs, normalizes, deduplicates, and evaluates them."""
        plan = await self.build_search_plan()

        feeds = ConfiguredFeedsSource(
            discovery=self.profile.discovery,
            allowed_sources=self.profile.application_preferences.allowed_sources,
        )
        raw_jobs = await feeds.search_plan(
            plan,
            limit=limit,
            per_query_limit=self.profile.discovery.results_per_query,
        )

        await self.event_repo.log(
            event_type="DISCOVERY_PLAN",
            message=(
                f"Planned {len(plan.entries)} queries ({plan.generated_by}), "
                f"discovered {len(raw_jobs)} postings"
            ),
            details={
                "generated_by": plan.generated_by,
                "notes": plan.notes,
                "queries": [entry.query for entry in plan.entries],
            },
        )

        processed_jobs: List[CanonicalJob] = []

        for raw in raw_jobs:
            canonical = JobNormalizer.normalize(raw)

            # Honour the exclusion lists before spending an evaluation call
            if not is_role_allowed(self.profile, canonical.role) or not is_company_allowed(
                self.profile, canonical.company
            ):
                canonical.status = ApplicationStatus.IGNORED
                await self.job_repo.create_or_update(canonical)
                continue

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

            # Cache the evaluation on the job so the RoleDiscoveryAgent can judge
            # search performance without walking application runs.
            job_orm.match_score = scorecard.score
            job_orm.scorecard = scorecard.model_dump(mode="json")
            await self.session.flush()

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

    async def build_search_plan(self) -> SearchPlan:
        """Builds the query plan for a discovery cycle.

        The role map is the better source when one exists: its titles were derived
        from the candidate's capabilities and are already ranked by fit. The
        SearchPlannerAgent remains the fallback for a system that has not run role
        discovery yet.
        """
        plan = await self.plan_from_role_map()
        if plan is not None:
            return plan

        try:
            ignored = await self.job_repo.list_jobs(status=ApplicationStatus.IGNORED.value, limit=15)
            promising = await self.job_repo.list_jobs(status=ApplicationStatus.EVALUATED.value, limit=15)
        except Exception:
            ignored, promising = [], []

        return await self.search_planner.plan(
            self.profile,
            ignored_titles=[job.role for job in ignored],
            promising_titles=[job.role for job in promising],
        )

    async def plan_from_role_map(self) -> Optional[SearchPlan]:
        """Turns the role map into board-friendly keyword queries.

        Board sources match plain keywords, so the stored provider queries (which
        carry quotes and site: operators for human browsing) are not reused here.
        The role titles and the alternative titles employers use are.
        """
        if not self.profile.role_discovery.enabled:
            return None
        try:
            from packages.role_discovery.service import RoleDiscoveryService

            role_map = await RoleDiscoveryService(
                self.session, profile=self.profile, rr_client=self.rr_client
            ).get_role_map()
        except Exception:
            return None
        if role_map is None or not role_map.searchable:
            return None

        max_queries = max(1, self.profile.discovery.max_queries_per_cycle)
        locations = list(self.profile.job_preferences.locations)
        remote = True if self.profile.job_preferences.remote else None

        entries: List[SearchPlanEntry] = []
        seen: set = set()
        ordered = role_map.primary + role_map.secondary + role_map.stretch

        for role in ordered:
            for title in [role.title] + role.equivalent_titles[:1]:
                key = title.strip().lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                entries.append(
                    SearchPlanEntry(
                        query=title.strip(),
                        locations=locations,
                        remote=remote,
                        rationale=(
                            f"{role.category.value.title()} role from the role map "
                            f"(fit {role.fit_score}/100)."
                        ),
                    )
                )
                if len(entries) >= max_queries:
                    break
            if len(entries) >= max_queries:
                break

        if not entries:
            return None
        return SearchPlan(
            entries=entries,
            generated_by="role-map",
            notes=f"Derived from role map v{role_map.version} ({role_map.generated_by}).",
        )

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
                scorecard=scorecard,
            )
            app_run.reactive_resume_application_id = rr_app.id
            app_run.reactive_resume_resume_id = self.resume_agent.last_derived_resume_id
            app_run.tailored_resume_path = pdf_path
            app_run.status = ApplicationStatus.READY.value

            # Draft Cover Letter
            cl_text = await self.cover_letter_agent.generate(job, application_id=rr_app.id)
            app_run.cover_letter_text = cl_text

            await self.session.flush()
            await self.log_tailoring(app_run.id, job.id)

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

        # 3. Mode is AUTO_APPLY -> Submit through the API when available, else the browser
        if mode == ExecutionMode.AUTO_APPLY.value:
            if self.infojobs_adapter.can_handle(job):
                await self.execute_infojobs_submission(app_run.id, job, cl_text, scorecard)
            else:
                await self.execute_browser_submission(app_run.id, job, pdf_path, cl_text, scorecard)

        return app_run.id

    async def log_tailoring(self, run_id: str, job_id: Optional[str]) -> None:
        """Records what the tailoring changed, and what it refused to claim."""
        plan = self.resume_agent.last_tailoring
        if plan is None:
            return

        changed = []
        if plan.headline:
            changed.append("headline")
        if plan.summary:
            changed.append("summary")
        if plan.experience:
            changed.append(f"{len(plan.experience)} experience entries")
        if plan.skill_priority:
            changed.append("skill order")

        message = (
            f"CV tailored ({plan.generated_by}): {', '.join(changed) or 'nothing changed'}"
        )
        if plan.rejected:
            message += f". Rejected {len(plan.rejected)} unsupported claim(s)"
        if self.resume_agent.last_patch_error:
            message += ". The patch failed, so the CV went out as a plain copy of the master"

        await self.event_repo.log(
            event_type="RESUME_TAILORED",
            message=message,
            application_run_id=run_id,
            job_id=job_id,
            severity="WARNING" if self.resume_agent.last_patch_error else "INFO",
            details={
                "generated_by": plan.generated_by,
                "headline": plan.headline,
                "reasoning": plan.reasoning,
                "rejected": plan.rejected,
                "patch_error": self.resume_agent.last_patch_error,
            },
        )

    async def execute_infojobs_submission(
        self,
        run_id: str,
        job: CanonicalJob,
        cover_letter_text: str,
        scorecard: MatchScorecard,
    ) -> bool:
        """Submits an InfoJobs application over their REST API, with no browser involved."""
        await self.run_repo.update_status(run_id, status=ApplicationStatus.APPLYING.value)

        result = await self.infojobs_adapter.apply(
            job=job,
            profile=self.profile,
            cover_letter_text=cover_letter_text,
        )

        if result.unanswered_questions:
            for question in result.unanswered_questions:
                await self.manual_q_repo.create(
                    question_text=question,
                    application_run_id=run_id,
                    context={"source": "infojobs", "offer_id": job.source_job_id},
                )
                await self.telegram.notify_manual_question(job, question, run_id)

            await self.run_repo.update_status(
                run_id,
                status=ApplicationStatus.NEEDS_USER_INPUT.value,
                error_message=result.error or "InfoJobs screening questions need a human answer.",
                error_category="NEEDS_ANSWERS",
            )
            return False

        if not result.submitted:
            await self.run_repo.update_status(
                run_id,
                status=ApplicationStatus.FAILED.value,
                error_message=result.error or "InfoJobs application failed.",
                error_category="INFOJOBS_ERROR",
            )
            return False

        await self.run_repo.update_status(run_id, status=ApplicationStatus.APPLIED.value)
        await self.event_repo.log(
            event_type="APPLICATION_SUBMITTED",
            message=f"InfoJobs application {result.application_code} sent for {job.company}",
            application_run_id=run_id,
            job_id=job.id,
            details={"curriculum": result.curriculum_name, "applied_at": result.applied_at},
        )

        app_run = await self.run_repo.get_by_id(run_id)
        if app_run and app_run.reactive_resume_application_id:
            try:
                await self.rr_client.update_application(
                    app_run.reactive_resume_application_id,
                    ApplicationUpdateRequest(status="applied"),
                )
                await self.rr_client.log_application_note(
                    app_run.reactive_resume_application_id,
                    f"Submitted through the InfoJobs API. Application code: {result.application_code}",
                )
            except Exception:
                pass

        await self.telegram.notify_submission(job, scorecard, result.curriculum_name or "InfoJobs CV")
        return True

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
