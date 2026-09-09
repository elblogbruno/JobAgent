import re
from typing import List, Optional
from playwright.async_api import Locator, Page
from packages.domain.enums import BlockedReason


class CaptchaBlockedException(Exception):
    def __init__(self, reason: BlockedReason = BlockedReason.CAPTCHA, details: str = ""):
        super().__init__(f"Application blocked by anti-bot verification: {reason.value} - {details}")
        self.reason = reason
        self.details = details


class SemanticLocators:
    @staticmethod
    async def check_for_anti_bot(page: Page) -> Optional[BlockedReason]:
        """
        Detects CAPTCHA, Cloudflare challenges, or 2FA prompts.
        """
        # Cloudflare Turnstile or Challenge
        cf_count = await page.locator("iframe[src*='challenges.cloudflare.com'], #challenge-running, .cf-turnstile").count()
        if cf_count > 0:
            return BlockedReason.CAPTCHA

        # Google reCAPTCHA
        recaptcha_count = await page.locator("iframe[src*='recaptcha'], .g-recaptcha").count()
        if recaptcha_count > 0:
            return BlockedReason.CAPTCHA

        # hCaptcha
        hcaptcha_count = await page.locator("iframe[src*='hcaptcha'], .h-captcha").count()
        if hcaptcha_count > 0:
            return BlockedReason.CAPTCHA

        # 2FA or Password Login Screen
        login_count = await page.locator("input[type='password'], input[name*='2fa'], input[name*='otp']").count()
        if login_count > 0:
            return BlockedReason.LOGIN_REQUIRED

        return None

    @staticmethod
    async def find_input_by_label_or_name(page: Page, keywords: List[str]) -> Optional[Locator]:
        for kw in keywords:
            # 1. By placeholder
            loc = page.get_by_placeholder(re.compile(rf"\b{re.escape(kw)}\b", re.I))
            if await loc.count() > 0:
                return loc.first

            # 2. By aria-label / label text
            loc = page.get_by_label(re.compile(rf"\b{re.escape(kw)}\b", re.I))
            if await loc.count() > 0:
                return loc.first

            # 3. By name or id attribute
            loc = page.locator(f"input[name*='{kw}' i], textarea[name*='{kw}' i], input[id*='{kw}' i]")
            if await loc.count() > 0:
                return loc.first

        return None

    @staticmethod
    async def find_file_input(page: Page, label_hint: str = "resume") -> Optional[Locator]:
        # 1. Any visible file input
        file_inputs = page.locator("input[type='file']")
        count = await file_inputs.count()
        if count == 1:
            return file_inputs.first
        elif count > 1:
            for i in range(count):
                inp = file_inputs.nth(i)
                inp_id = await inp.get_attribute("id") or ""
                inp_name = await inp.get_attribute("name") or ""
                if label_hint.lower() in inp_id.lower() or label_hint.lower() in inp_name.lower():
                    return inp
            return file_inputs.first
        return None

    @staticmethod
    async def find_submit_button(page: Page) -> Optional[Locator]:
        patterns = [
            r"submit\s+application",
            r"apply\s+now",
            r"submit",
            r"send\s+application",
            r"enviar\s+candidatura",
            r"postular",
        ]
        for pat in patterns:
            btn = page.get_by_role("button", name=re.compile(pat, re.I))
            if await btn.count() > 0:
                return btn.first

        # Fallback to standard input type=submit or button with type submit
        fallback = page.locator("input[type='submit'], button[type='submit']")
        if await fallback.count() > 0:
            return fallback.first

        return None
