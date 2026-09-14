from pathlib import Path
from typing import List
from playwright.async_api import Page
from packages.application_adapters.base import ApplicationAdapter
from packages.browser.forms import FormNavigator
from packages.browser.locators import SemanticLocators
from packages.candidate_profile.answer_vault import CandidateAnswerVault
from packages.domain.models import CandidateProfileModel


class GenericApplicationAdapter(ApplicationAdapter):
    """
    Universal fallback adapter for unknown career portals.
    Uses semantic heuristics, accessible roles, labels, and the Answer Vault.
    """

    async def can_handle(self, url: str, page: Page) -> bool:
        # Fallback adapter handles any form
        return True

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

        # 1. Names
        first_el = await SemanticLocators.find_input_by_label_or_name(page, ["first name", "nombre", "given name"])
        if first_el:
            await first_el.fill(first_name)

        last_el = await SemanticLocators.find_input_by_label_or_name(page, ["last name", "apellidos", "family name"])
        if last_el:
            await last_el.fill(last_name)

        if not first_el and not last_el:
            full_name_el = await SemanticLocators.find_input_by_label_or_name(page, ["name", "full name", "nombre completo"])
            if full_name_el:
                await full_name_el.fill(ident.name)

        # 2. Email
        email_el = await SemanticLocators.find_input_by_label_or_name(page, ["email", "correo", "e-mail"])
        if email_el:
            await email_el.fill(ident.email)

        # 3. Phone
        phone_el = await SemanticLocators.find_input_by_label_or_name(page, ["phone", "teléfono", "mobile", "celular"])
        if phone_el:
            await phone_el.fill(ident.phone)

        # 4. Location / City
        loc_el = await SemanticLocators.find_input_by_label_or_name(page, ["city", "location", "ciudad", "ubicación"])
        if loc_el:
            await loc_el.fill(ident.location)

        # 5. LinkedIn / URLs
        li_el = await SemanticLocators.find_input_by_label_or_name(page, ["linkedin"])
        if li_el and ident.linkedin:
            await li_el.fill(ident.linkedin)

        web_el = await SemanticLocators.find_input_by_label_or_name(page, ["website", "portfolio", "github"])
        if web_el and (ident.website or ident.github):
            await web_el.fill(ident.website or ident.github or "")

        # 6. Resume Upload
        file_input = await SemanticLocators.find_file_input(page, "resume")
        if file_input and Path(resume_pdf_path).exists():
            await file_input.set_input_files(resume_pdf_path)

        # 7. Cover Letter
        cl_el = await SemanticLocators.find_input_by_label_or_name(page, ["cover letter", "carta", "motivation", "summary"])
        if cl_el and cover_letter_text:
            try:
                tag = await cl_el.evaluate("el => el.tagName ? el.tagName.toLowerCase() : ''")
                if tag in ("input", "textarea") or await cl_el.is_editable():
                    await cl_el.fill(cover_letter_text)
            except Exception:
                pass

        # 8. Unanswered inputs through Answer Vault
        all_text_inputs = page.locator("input[type='text'], textarea")
        count = await all_text_inputs.count()
        for i in range(count):
            inp = all_text_inputs.nth(i)
            if not await inp.is_visible() or await inp.input_value() != "":
                continue

            # Check accessible label
            label = await inp.get_attribute("aria-label") or await inp.get_attribute("placeholder") or await inp.get_attribute("name") or ""
            if label:
                val, conf, _ = await answer_vault.resolve(label, profile)
                if val is not None and conf >= 0.9:
                    await inp.fill(str(val))

    async def validate(self, page: Page) -> List[str]:
        return await FormNavigator.get_visible_validation_errors(page)

    async def submit(self, page: Page) -> bool:
        btn = await SemanticLocators.find_submit_button(page)
        if btn and await btn.is_visible():
            await btn.click()
            return True
        return False
