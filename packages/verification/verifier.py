import re
from typing import Optional
from playwright.async_api import Page
from packages.domain.models import SubmissionEvidence

CONFIRMATION_PATTERNS = [
    r"thank\s+you\s+for\s+applying",
    r"application\s+received",
    r"we('ve|\s+have)\s+received\s+your\s+application",
    r"submission\s+successful",
    r"your\s+application\s+has\s+been\s+submitted",
    r"gracias\s+por\s+postular",
    r"candidatura\s+recibida",
    r"solicitud\s+enviada",
]


class SubmissionVerifier:
    @staticmethod
    async def verify(page: Page, timeout_seconds: int = 15) -> SubmissionEvidence:
        """
        Polls DOM and URL transitions to verify legitimate submission confirmation.
        """
        # 1. URL Check
        current_url = page.url.lower()
        if any(keyword in current_url for keyword in ["thank", "confirm", "success", "submitted", "received"]):
            return SubmissionEvidence(
                verified=True,
                evidence_type="URL_REDIRECT",
                details=f"Navigated to confirmation URL: {page.url}",
                redirect_url=page.url,
            )

        # 2. Text evidence check
        page_text = (await page.content()).lower()
        for pattern in CONFIRMATION_PATTERNS:
            match = re.search(pattern, page_text)
            if match:
                # Extract confirmation ID if present
                ref_match = re.search(r"\b(confirmation|reference|app)\s*#?:?\s*([A-Z0-9\-]{5,20})\b", page_text, re.I)
                conf_id = ref_match.group(2) if ref_match else None

                return SubmissionEvidence(
                    verified=True,
                    evidence_type="DOM_TEXT",
                    details=f"Matched confirmation text phrase: '{match.group(0)}'",
                    confirmation_id=conf_id,
                    redirect_url=page.url,
                )

        return SubmissionEvidence(
            verified=False,
            evidence_type="NONE",
            details="No confirmation message or success redirect detected after submit.",
        )
