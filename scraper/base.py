"""Base scraper using Playwright. All developer scrapers inherit from this."""
import asyncio
import json
import random
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Response
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log
import logging

from .models import DeveloperSnapshot

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1280, "height": 800},
    {"width": 1366, "height": 768},
]


class BaseScraper(ABC):
    name: str = ""
    url: str = ""

    def __init__(self, proxy_url: Optional[str] = None):
        self.proxy_url = proxy_url

    # ── Playwright context helpers ─────────────────────────────────────────

    async def _new_context(self, browser: Browser) -> BrowserContext:
        """Create a context with stealth settings."""
        ua = random.choice(USER_AGENTS)
        vp = random.choice(VIEWPORTS)
        proxy = {"server": self.proxy_url} if self.proxy_url else None
        ctx = await browser.new_context(
            user_agent=ua,
            viewport=vp,
            locale="sv-SE",
            timezone_id="Europe/Stockholm",
            proxy=proxy,
            extra_http_headers={
                "Accept-Language": "sv-SE,sv;q=0.9,en-GB;q=0.8,en;q=0.7",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "DNT": "1",
            },
        )
        # Basic stealth: override navigator.webdriver
        await ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
            window.chrome = { runtime: {} };
        """)
        return ctx

    async def _intercept_json(
        self,
        page: Page,
        trigger_url: str,
        url_pattern: str,
        timeout: int = 30000,
    ) -> Optional[dict | list]:
        """
        Navigate to trigger_url, capture the first XHR/fetch response whose URL
        matches url_pattern (regex), return parsed JSON.
        Returns None if nothing matched within timeout.
        """
        captured: list[dict | list] = []

        async def handle_response(response: Response):
            if captured:
                return
            if not re.search(url_pattern, response.url, re.IGNORECASE):
                return
            ct = response.headers.get("content-type", "")
            if "json" not in ct:
                return
            try:
                body = await response.json()
                captured.append(body)
            except Exception:
                pass

        page.on("response", handle_response)
        await page.goto(trigger_url, wait_until="domcontentloaded", timeout=60000)
        # Wait up to timeout for a matching response
        deadline = asyncio.get_event_loop().time() + timeout / 1000
        while not captured and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.2)

        page.remove_listener("response", handle_response)
        return captured[0] if captured else None

    async def _next_data(self, page: Page, url: str) -> Optional[dict]:
        """Extract Next.js __NEXT_DATA__ or Nuxt __NUXT_DATA__ embedded JSON."""
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        for selector in ["#__NEXT_DATA__", "#__NUXT_DATA__", "script[id='__NEXT_DATA__']"]:
            el = await page.query_selector(selector)
            if el:
                text = await el.inner_text()
                try:
                    return json.loads(text)
                except Exception:
                    pass
        return None

    async def _rendered_soup(self, page: Page, url: str) -> BeautifulSoup:
        """Navigate and return BeautifulSoup of fully-rendered page."""
        await page.goto(url, wait_until="networkidle", timeout=90000)
        await asyncio.sleep(random.uniform(1.0, 2.5))
        html = await page.content()
        return BeautifulSoup(html, "lxml")

    # ── Public interface ───────────────────────────────────────────────────

    @abstractmethod
    async def scrape(self, browser: Browser) -> list:
        """Return list of Project instances."""
        ...

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=30),
        reraise=True,
    )
    async def _run_with_retry(self, browser: Browser) -> list:
        return await self.scrape(browser)

    async def run(self) -> DeveloperSnapshot:
        now = datetime.now(timezone.utc).isoformat()
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                projects = await self._run_with_retry(browser)
                return DeveloperSnapshot(
                    developer=self.name,
                    developer_url=self.url,
                    scraped_at=now,
                    projects=[p.to_dict() if hasattr(p, "to_dict") else p for p in projects],
                )
            except Exception as exc:
                logger.error(f"[{self.name}] FAILED: {exc}")
                return DeveloperSnapshot(
                    developer=self.name,
                    developer_url=self.url,
                    scraped_at=now,
                    projects=[],
                    error=str(exc),
                )
            finally:
                await browser.close()
