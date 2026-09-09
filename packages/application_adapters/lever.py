from pathlib import Path
from typing import List
from playwright.async_api import Page
from packages.application_adapters.base import ApplicationAdapter
from packages.browser.forms import FormNavigator
from packages.browser.locators import SemanticLocators
from packages.candidate_profile.answer_vault import CandidateAnswerVault
from packages.domain.models import CandidateProfileModel


class LeverAdapter(ApplicationAdapter):
    async def can_handle(self, url: str, page: Page) -> bool:
        if "lever.co" in url:
            return True
        return await page.locator(".lever-job-posting, #application-form, form[action*='lever']").count() > 0

    async def fill(
        self,
        page: Page,
        profile: CandidateProfileModel,
        resume_pdf_path: str,
        cover_letter_text: str,
        answer_vault: CandidateAnswerVault,
    ) -> None:
        ident = profile.identity

        # Full Name
        if await page.locator("input[name='name']").count() > 0:
            await page.fill("input[name='name']", ident.name)

        # Email & Phone
        if await page.locator("input[name='email']").count() > 0:
            await page.fill("input[name='email']", ident.email)
        if await page.locator("input[name='phone']").count() > 0:
            await page.fill("input[name='phone']", ident.phone)

        # Organization / Company
        if await page.locator("input[name='org']").count() > 0:
            await page.fill("input[name='org']", "Independent Consultant / Engineer")

        # URLs
        if await page.locator("input[name*='urls[LinkedIn]']").count() > 0 and ident.linkedin:
            await page.fill("input[name*='urls[LinkedIn]']", ident.linkedin)
        if await page.locator("input[name*='urls[GitHub]']").count() > 0 and ident.github:
            await page.fill("input[name*='urls[GitHub]']", ident.github)
        if await page.locator("input[name*='urls[Portfolio]']").count() > 0 and ident.website:
            await page.fill("input[name*='urls[Portfolio]']", ident.website)

        # File Upload
        file_input = page.locator("#resume-upload-input, input[type='file']")
        if await file_input.count() > 0 and Path(resume_pdf_path).exists():
            await file_input.first.set_input_files(resume_pdf_path)

        # Cover Letter / Comments
        comments = page.locator("textarea[name='comments']")
        if await comments.count() > 0 and cover_letter_text:
            await comments.fill(cover_letter_text)

        # Custom questions
        custom_cards = page.locator(".application-question")
        count = await custom_cards.count()
        for i in range(count):
            card = custom_cards.nth(i)
            text_el = card.locator(".text")
            if await text_el.count() == 0:
                continue
            question_text = (await text_el.text_content() or "").strip()
            answer_val, confidence, _ = await answer_vault.resolve(question_text, profile)
            if answer_val is not None and confidence >= 0.9:
                inp = card.locator("input[type='text'], textarea")
                if await inp.count() > 0 and await inp.input_value() == "":
                    await inp.fill(str(answer_val))

    async def validate(self, page: Page) -> List[str]:
        return await FormNavigator.get_visible_validation_errors(page)

    async def submit(self, page: Page) -> bool:
        btn = page.locator(".template-btn-submit, button[type='submit']")
        if await btn.count() > 0 and await btn.first.is_visible():
            await btn.first.click()
            return True

        btn_fallback = await SemanticLocators.find_submit_button(page)
        if btn_fallback and await btn_fallback.is_visible():
            await btn_fallback.click()
            return True

        return False
