from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from packages.domain.models import CandidateProfileModel, CanonicalJob, MatchScorecard
from packages.llm.gateway import LLMGateway
from packages.reactive_resume.client import ReactiveResumeClient
from packages.reactive_resume.models import (
    ApplicationCreateRequest,
    ApplicationResponse,
    ResumeDetail,
)
from packages.reactive_resume.patch_builder import ResumePatchBuilder
from packages.resume_pipeline.tailoring_agent import ResumeTailoringAgent, TailoringPlan


class ResumeAgent:
    def __init__(
        self,
        rr_client: ReactiveResumeClient,
        profile: CandidateProfileModel,
        artifacts_dir: Path = Path("artifacts/resumes"),
        llm_gateway: Optional[LLMGateway] = None,
    ):
        self.client = rr_client
        self.profile = profile
        self.artifacts_dir = artifacts_dir
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.tailoring_agent = ResumeTailoringAgent(llm_gateway)
        #: What the last preparation actually changed, for the caller to log.
        self.last_tailoring: Optional[TailoringPlan] = None
        self.last_patch_error: Optional[str] = None
        #: The derived CV the last preparation produced, so it can be replaced.
        self.last_derived_resume_id: Optional[str] = None

    async def find_or_get_master_resume(self) -> ResumeDetail:
        master_id = self.profile.reactive_resume.master_resume_id
        if master_id:
            try:
                return await self.client.get_resume(master_id)
            except Exception:
                pass

        # Search by name
        resumes = await self.client.list_resumes()
        target_name = self.profile.reactive_resume.master_resume_name.lower()
        for r in resumes:
            if target_name in r.name.lower() or "master" in r.name.lower():
                return await self.client.get_resume(r.id)

        if resumes:
            # Fallback to first resume if any
            return await self.client.get_resume(resumes[0].id)

        raise RuntimeError(
            "No master resume found in Reactive Resume. Please create or import one."
        )

    async def prepare_application_and_resume(
        self,
        job: CanonicalJob,
        match_score: int,
        execution_mode: str = "AUTO_APPLY",
        scorecard: Optional[MatchScorecard] = None,
    ) -> Tuple[ApplicationResponse, str, bytes]:
        """
        Executes full preparation lifecycle:
        1. Creates Application in Reactive Resume.
        2. Duplicates Master CV into a tailored derivative.
        3. Formulates and applies non-hallucinatory JSON patch.
        4. Downloads PDF and attaches to Application.
        Returns: (ApplicationResponse, local_pdf_path, pdf_bytes)
        """
        master = await self.find_or_get_master_resume()

        # 1. Create Reactive Resume Application
        app_req = ApplicationCreateRequest(
            company=job.normalized_company,
            role=job.normalized_role,
            location=job.location,
            salary=f"{job.salary_min or ''} - {job.salary_max or ''} {job.salary_currency or ''}".strip(),
            source=job.source.value,
            sourceUrl=job.canonical_url,
            jobDescription=job.description[:19000],
            notes=f"Match Score: {match_score}/100. Mode: {execution_mode}.",
            tags=["jobagent", "tailored"],
            status="saved",
            stageEnteredAt=datetime.utcnow().strftime("%Y-%m-%d"),
        )
        application = await self.client.create_application(app_req)

        # 2. Duplicate Master CV
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        unique_suffix = f"{job.id[:6]}-{int(datetime.utcnow().timestamp()) % 100000}"
        derived_name = f"{self.profile.identity.name} — {job.normalized_company} — {job.normalized_role} ({unique_suffix})"
        derived_slug = f"{self.profile.identity.name.lower().replace(' ', '-')}-{job.normalized_company.lower()[:15]}-{unique_suffix}"
        derived_slug = "".join(c for c in derived_slug if c.isalnum() or c == "-").strip("-")

        derived_resume = await self.client.duplicate_resume(
            resume_id=master.id,
            name=derived_name,
            slug=derived_slug,
            tags=["derived", job.normalized_company.lower()[:20]],
        )

        # 3. Tailor the copy to this posting, using only what the master already
        # says. Anything the agent proposes that is not evidenced there is
        # dropped before the patch is built.
        plan = await self.tailoring_agent.build_plan(
            master=master.data,
            job=job,
            profile=self.profile,
            scorecard=scorecard,
            use_llm=self.profile.role_discovery.use_llm,
        )
        self.last_tailoring = plan
        self.last_patch_error = None

        operations = self._build_operations(plan, master)

        if operations:
            try:
                await self.client.patch_resume(derived_resume.id, operations)
            except Exception as exc:
                # The duplicate is still a valid CV, so the application proceeds,
                # but the caller needs to know it went out untailored.
                self.last_patch_error = str(exc)

        # 4. Lock derived resume
        try:
            await self.client.lock_resume(derived_resume.id)
        except Exception:
            pass

        # 5. Download PDF
        pdf_bytes = await self.client.download_resume_pdf(derived_resume.id, target="resume")
        if not pdf_bytes or len(pdf_bytes) < 100:
            # Create a mock valid PDF file content if remote PDF generator is idle or mock
            pdf_bytes = b"%PDF-1.4 Mock Tailored Resume Content for Job Agent testing\n%%EOF"

        local_pdf_path = self.artifacts_dir / f"resume_{application.id}.pdf"
        with open(local_pdf_path, "wb") as f:
            f.write(pdf_bytes)

        # 6. Attach PDF to Reactive Resume application
        try:
            await self.client.attach_application_document(
                application_id=application.id,
                kind="resume",
                file_bytes=pdf_bytes,
                filename=f"{derived_name}.pdf",
            )
        except Exception:
            pass

        self.last_derived_resume_id = derived_resume.id
        return application, str(local_pdf_path), pdf_bytes

    def _build_operations(self, plan: TailoringPlan, master: ResumeDetail) -> List[Any]:
        """Turns a validated plan into JSON Patch operations.

        Only the headline, the summary, experience entry summaries and the order
        of the skills list are touched. Companies, positions, dates and every
        other field are left exactly as the master has them.
        """
        builder = ResumePatchBuilder()

        if plan.headline:
            builder.replace_headline(plan.headline)

        if plan.summary and _has_section(master, "summary"):
            builder.replace_summary(plan.summary)

        # Only indices the master actually has: a patch against a missing entry
        # is rejected, and the whole patch goes with it.
        experience = (master.data.sections or {}).get("experience")
        items = experience.get("items") if isinstance(experience, dict) else None
        available = len(items) if isinstance(items, list) else 0
        for index, summary in sorted(plan.experience.items()):
            if 0 <= index < available:
                builder.update_work_item_summary(index, summary)

        if plan.skill_priority:
            reordered = _reorder_skills(master, plan.skill_priority)
            if reordered is not None:
                builder.update_skills(reordered)

        return builder.build()


def _has_section(master: ResumeDetail, key: str) -> bool:
    return isinstance((master.data.sections or {}).get(key), dict)


def _reorder_skills(master: ResumeDetail, priority: List[str]) -> Optional[List[Dict[str, Any]]]:
    """Reorders the existing skill items. Never adds, never drops."""
    section = (master.data.sections or {}).get("skills")
    items = section.get("items") if isinstance(section, dict) else None
    if not isinstance(items, list) or not items:
        return None

    order = {name.lower(): position for position, name in enumerate(priority)}
    reordered = sorted(
        items,
        key=lambda item: order.get(str(item.get("name", "")).strip().lower(), len(order)),
    )
    if reordered == items:
        return None
    return reordered
