import re
from typing import List, Optional
from playwright.async_api import Locator, Page


class FormNavigator:
    @staticmethod
    async def is_multi_step(page: Page) -> bool:
        indicators = page.locator(".step, .wizard-step, [aria-label*='step' i], [aria-label*='progress' i]")
        return await indicators.count() > 1

    @staticmethod
    async def find_next_button(page: Page) -> Optional[Locator]:
        patterns = [r"^next$", r"^continue$", r"^siguiente$", r"^continuar$", r"^save\s+and\s+continue$"]
        for pat in patterns:
            btn = page.get_by_role("button", name=re.compile(pat, re.I))
            if await btn.count() > 0 and await btn.first.is_visible():
                return btn.first
        return None

    @staticmethod
    async def get_visible_validation_errors(page: Page) -> List[str]:
        error_locators = page.locator(".error, .invalid-feedback, [aria-invalid='true'], .alert-danger, [role='alert']")
        count = await error_locators.count()
        errors = []
        for i in range(count):
            loc = error_locators.nth(i)
            if await loc.is_visible():
                text = (await loc.text_content() or "").strip()
                if text and len(text) < 200:
                    errors.append(text)
        return list(set(errors))
