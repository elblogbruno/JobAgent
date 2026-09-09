from abc import ABC, abstractmethod
from typing import List
from playwright.async_api import Page
from packages.candidate_profile.answer_vault import CandidateAnswerVault
from packages.domain.models import CandidateProfileModel


class ApplicationAdapter(ABC):
    @abstractmethod
    async def can_handle(self, url: str, page: Page) -> bool:
        """Determines if this adapter is suitable for the current URL or page DOM."""
        pass

    @abstractmethod
    async def fill(
        self,
        page: Page,
        profile: CandidateProfileModel,
        resume_pdf_path: str,
        cover_letter_text: str,
        answer_vault: CandidateAnswerVault,
    ) -> None:
        """Fills all fields and uploads documents."""
        pass

    @abstractmethod
    async def validate(self, page: Page) -> List[str]:
        """Checks for any validation error messages on the page."""
        pass

    @abstractmethod
    async def submit(self, page: Page) -> bool:
        """Clicks the final submit button."""
        pass
