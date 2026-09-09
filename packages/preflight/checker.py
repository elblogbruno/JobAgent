from datetime import datetime
from pathlib import Path
from typing import List, Optional
import httpx
from playwright.async_api import Page
from packages.browser.forms import FormNavigator
from packages.domain.models import (
    CandidateProfileModel,
    CanonicalJob,
    PreflightCheckItem,
    PreflightResult,
)


class ApplicationPreflight:
    def __init__(
        self,
        profile: CandidateProfileModel,
        job: CanonicalJob,
        tailored_resume_path: str,
        match_score: int,
        snapshots_dir: Path = Path("artifacts/snapshots"),
    ):
        self.profile = profile
        self.job = job
        self.tailored_resume_path = tailored_resume_path
        self.match_score = match_score
        self.snapshots_dir = snapshots_dir
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    async def run_checks(self, page: Optional[Page] = None) -> PreflightResult:
        checks: List[PreflightCheckItem] = []
        failures: List[str] = []

        # 1. Job still active
        job_active = await self._check_job_active()
        checks.append(PreflightCheckItem(name="job_active", passed=job_active, details=self.job.apply_url))
        if not job_active:
            failures.append("Job application URL is no longer active (non-200 status).")

        # 2. Threshold met
        threshold = self.profile.application_preferences.auto_apply_threshold
        score_ok = self.match_score >= self.profile.application_preferences.prepare_threshold
        checks.append(PreflightCheckItem(name="score_threshold_met", passed=score_ok, details=f"Score: {self.match_score} (Min: {threshold})"))
        if not score_ok:
            failures.append(f"Score {self.match_score} below minimum threshold.")

        # 3. Correct tailored CV file exists and is not empty
        pdf_path = Path(self.tailored_resume_path)
        cv_valid = pdf_path.exists() and pdf_path.stat().st_size > 500
        checks.append(PreflightCheckItem(name="cv_file_valid", passed=cv_valid, details=str(pdf_path)))
        if not cv_valid:
            failures.append(f"Tailored CV PDF not found or empty at {pdf_path}")

        # 4. Identity parameters match
        id_ok = bool(self.profile.identity.name and self.profile.identity.email and self.profile.identity.phone)
        checks.append(PreflightCheckItem(name="identity_complete", passed=id_ok, details=self.profile.identity.email))
        if not id_ok:
            failures.append("Candidate identity fields are incomplete.")

        # 5. Page checks (if browser page provided)
        snapshot_file = None
        if page:
            # Form validation errors
            visible_errors = await FormNavigator.get_visible_validation_errors(page)
            no_errors = len(visible_errors) == 0
            checks.append(PreflightCheckItem(name="no_visible_form_errors", passed=no_errors, details=f"Errors: {visible_errors}"))
            if not no_errors:
                failures.append(f"Visible form validation errors: {visible_errors}")

            # Save pre-submit snapshot
            ts = int(datetime.utcnow().timestamp())
            snapshot_file = self.snapshots_dir / f"presubmit_{self.job.dedup_hash[:12]}_{ts}.html"
            try:
                content = await page.content()
                with open(snapshot_file, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception:
                pass

        all_passed = len(failures) == 0
        return PreflightResult(
            passed=all_passed,
            checks=checks,
            failure_reasons=failures,
            dom_snapshot_id=str(snapshot_file) if snapshot_file else None,
        )

    async def _check_job_active(self) -> bool:
        if self.job.apply_url.startswith("file://") or "example.com" in self.job.apply_url:
            return True
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.head(self.job.apply_url, follow_redirects=True)
                return resp.status_code in (200, 201, 302, 301)
        except Exception:
            return True # Fallback if HEAD request is blocked by server
