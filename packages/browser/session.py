from pathlib import Path
from typing import Optional
from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from config.settings import settings


class BrowserSessionManager:
    def __init__(
        self,
        user_data_dir: Optional[str] = None,
        headless: Optional[bool] = None,
        timeout_ms: Optional[int] = None,
    ):
        self.user_data_dir = user_data_dir or settings.browser_user_data_dir
        self.headless = headless if headless is not None else settings.playwright_headless
        self.timeout_ms = timeout_ms or settings.playwright_timeout_ms
        self._playwright = None
        self._context: Optional[BrowserContext] = None

    async def start(self) -> BrowserContext:
        Path(self.user_data_dir).mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()

        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            headless=self.headless,
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            accept_downloads=True,
        )
        self._context.set_default_timeout(self.timeout_ms)
        return self._context

    async def new_page(self) -> Page:
        if not self._context:
            await self.start()
        assert self._context is not None
        return await self._context.new_page()

    async def close(self):
        if self._context:
            await self._context.close()
            self._context = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
