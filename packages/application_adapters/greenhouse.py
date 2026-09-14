from pathlib import Path
from typing import List
from playwright.async_api import Page
from packages.application_adapters.base import ApplicationAdapter
from packages.browser.forms import FormNavigator
from packages.browser.locators import SemanticLocators
from packages.candidate_profile.answer_vault import CandidateAnswerVault
from packages.domain.models import CandidateProfileModel


class GreenhouseAdapter(ApplicationAdapter):
    async def can_handle(self, url: str, page: Page) -> bool:
        if "greenhouse.io" in url or "gh_src" in url:
            return True
        # Check DOM element indicator
        return await page.locator("#application_form, #submit_app, form[action*='greenhouse']").count() > 0

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

        # First & Last Name
        if await page.locator("#first_name").count() > 0:
            await page.fill("#first_name", first_name)
        if await page.locator("#last_name").count() > 0:
            await page.fill("#last_name", last_name)

        # Full Name fallback
        if await page.locator("input[name*='name' i]").count() > 0 and await page.locator("#first_name").count() == 0:
            await page.fill("input[name*='name' i]", ident.name)

        # Email & Phone
        if await page.locator("#email").count() > 0:
            await page.fill("#email", ident.email)
        if await page.locator("#phone").count() > 0:
            await page.fill("#phone", ident.phone)

        # Resume File Upload
        file_input = await SemanticLocators.find_file_input(page, "resume")
        if file_input and Path(resume_pdf_path).exists():
            await file_input.set_input_files(resume_pdf_path)

        # LinkedIn Profile
        li_input = await SemanticLocators.find_input_by_label_or_name(page, ["linkedin"])
        if li_input and ident.linkedin:
            await li_input.fill(ident.linkedin)

        # Website / Portfolio
        web_input = await SemanticLocators.find_input_by_label_or_name(page, ["website", "portfolio", "github"])
        if web_input and (ident.website or ident.github):
            await web_input.fill(ident.website or ident.github or "")

        # Cover letter field if available
        cl_input = await SemanticLocators.find_input_by_label_or_name(page, ["cover letter"])
        if cl_input and cover_letter_text:
            try:
                tag = await cl_input.evaluate("el => el.tagName ? el.tagName.toLowerCase() : ''")
                if tag in ("input", "textarea") or await cl_input.is_editable():
                    await cl_input.fill(cover_letter_text)
            except Exception:
                pass

        # Iterate custom question fields
        custom_fields = page.locator(".field:has(label)")
        field_count = await custom_fields.count()
        for i in range(field_count):
            field_el = custom_fields.nth(i)
            label_el = field_el.locator("label")
            if await label_el.count() == 0:
                continue
            question_text = (await label_el.text_content() or "").strip()
            answer_val, confidence, _ = await answer_vault.resolve(question_text, profile)

            if answer_val is not None and confidence >= 0.9:
                # Text input or textarea
                input_child = field_el.locator("input[type='text'], textarea")
                if await input_child.count() > 0 and await input_child.input_value() == "":
                    await input_child.fill(str(answer_val))

                # Dropdown / Select
                select_child = field_el.locator("select")
                if await select_child.count() > 0:
                    if isinstance(answer_val, bool):
                        opt_label = "Yes" if answer_val else "No"
                        try:
                            await select_child.select_option(label=opt_label)
                        except Exception:
                            pass

    async def validate(self, page: Page) -> List[str]:
        return await FormNavigator.get_visible_validation_errors(page)

    async def submit(self, page: Page) -> bool:
        btn = page.locator("#submit_app")
        if await btn.count() > 0 and await btn.is_visible():
            await btn.click()
            return True

        btn_fallback = await SemanticLocators.find_submit_button(page)
        if btn_fallback and await btn_fallback.is_visible():
            await btn_fallback.click()
            return True

        return False
