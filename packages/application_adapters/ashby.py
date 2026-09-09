from pathlib import Path
from typing import List
from playwright.async_api import Page
from packages.application_adapters.base import ApplicationAdapter
from packages.browser.forms import FormNavigator
from packages.browser.locators import SemanticLocators
from packages.candidate_profile.answer_vault import CandidateAnswerVault
from packages.domain.models import CandidateProfileModel


class AshbyAdapter(ApplicationAdapter):
    async def can_handle(self, url: str, page: Page) -> bool:
        if "ashbyhq.com" in url:
            return True
        return await page.locator("[data-ashby-job-posting-form], form[action*='ashby']").count() > 0

    async def fill(
        self,
        page: Page,
        profile: CandidateProfileModel,
        resume_pdf_path: str,
        cover_letter_text: str,
        answer_vault: CandidateAnswerVault,
    ) -> None:
        ident = profile.identity
        names = ident.name.split(" ", 1)
        first_name = names[0]
        last_name = names[1] if len(names) > 1 else ""

        # Name fields
        first_input = await SemanticLocators.find_input_by_label_or_name(page, ["first name"])
        if first_input:
            await first_input.fill(first_name)
        last_input = await SemanticLocators.find_input_by_label_or_name(page, ["last name"])
        if last_input:
            await last_input.fill(last_name)

        if not first_input and not last_input:
            name_input = await SemanticLocators.find_input_by_label_or_name(page, ["name", "full name"])
            if name_input:
                await name_input.fill(ident.name)

        # Email & Phone
        email_input = await SemanticLocators.find_input_by_label_or_name(page, ["email"])
        if email_input:
            await email_input.fill(ident.email)
        phone_input = await SemanticLocators.find_input_by_label_or_name(page, ["phone"])
        if phone_input:
            await phone_input.fill(ident.phone)

        # Resume file
        file_input = await SemanticLocators.find_file_input(page, "resume")
        if file_input and Path(resume_pdf_path).exists():
            await file_input.set_input_files(resume_pdf_path)

        # LinkedIn
        li_input = await SemanticLocators.find_input_by_label_or_name(page, ["linkedin"])
        if li_input and ident.linkedin:
            await li_input.fill(ident.linkedin)

        # Cover letter
        cl_input = await SemanticLocators.find_input_by_label_or_name(page, ["cover letter"])
        if cl_input and cover_letter_text:
            await cl_input.fill(cover_letter_text)

    async def validate(self, page: Page) -> List[str]:
        return await FormNavigator.get_visible_validation_errors(page)

    async def submit(self, page: Page) -> bool:
        btn = await SemanticLocators.find_submit_button(page)
        if btn and await btn.is_visible():
            await btn.click()
            return True
        return False
