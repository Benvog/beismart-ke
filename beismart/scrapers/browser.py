"""One shared headless browser for stores that need JavaScript or pass a bot check.

Real Google Chrome is preferred (it gets past checks that bundled Chromium does not);
bundled Chromium is the fallback. The browser starts on first use and is reused."""

import asyncio
import time

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeout

from ..models import StoreStatus
from .http import USER_AGENT, FetchProblem, Page

_lock = asyncio.Lock()
MAX_PAGES_AT_ONCE = 3                      # heavy pages loading together starve each other and time out
_page_slots = asyncio.Semaphore(MAX_PAGES_AT_ONCE)
_playwright: Playwright | None = None
_browser: Browser | None = None
_context: BrowserContext | None = None  # one profile for all requests, so a bot-check pass (cookie) is remembered

_CHALLENGE_TITLES = ("just a moment", "attention required", "access denied", "verify you are human")


async def _get_browser() -> Browser:
    global _playwright, _browser
    async with _lock:
        if _browser and _browser.is_connected():
            return _browser
        if _playwright is None:
            _playwright = await async_playwright().start()
        try:
            _browser = await _playwright.chromium.launch(channel="chrome", headless=True)
        except Exception:
            _browser = await _playwright.chromium.launch(headless=True)
        return _browser


async def _get_context() -> BrowserContext:
    global _context
    browser = await _get_browser()
    async with _lock:
        # A new browser (after a crash) needs a new profile: the old one belongs to the dead browser.
        if _context is None or _context.browser is not browser:
            _context = await browser.new_context(user_agent=USER_AGENT, locale="en-KE", viewport={"width": 1280, "height": 800})
        return _context


async def close_browser() -> None:
    """Call once when the app shuts down."""
    global _playwright, _browser, _context
    _context = None
    if _browser:
        await _browser.close()
    if _playwright:
        await _playwright.stop()
    _browser = _playwright = None


async def get_rendered_page(url: str, wait_for: str, timeout: float = 30.0, retries: int = 1) -> Page:
    """Like _load_page, but a bot check, a timeout or a dropped connection is retried once. The browser profile keeps the
    pass it earns, and a cold browser is slow on its first page, so the second attempt usually works."""
    for attempt in range(retries + 1):
        try:
            async with _page_slots:            # waiting in line does not count against the page's time limit
                return await _load_page(url, wait_for, timeout)
        except FetchProblem as problem:
            if attempt == retries or problem.status not in (StoreStatus.BLOCKED, StoreStatus.TIMEOUT, StoreStatus.ERROR):
                raise
            await asyncio.sleep(3)


async def _load_page(url: str, wait_for: str, timeout: float) -> Page:
    """Open a page, wait until `wait_for` (a CSS selector) appears, and return its HTML.
    `timeout` is the total budget for loading the page and waiting for the selector together.

    Raises FetchProblem: BLOCKED for a bot-check page, TIMEOUT when nothing shows up in time."""
    context = await _get_context()
    page = await context.new_page()
    deadline = time.monotonic() + timeout
    try:
        response = None
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            await page.wait_for_selector(wait_for, timeout=max(1.0, deadline - time.monotonic()) * 1000)
        except PlaywrightTimeout:
            title = (await page.title()).lower()
            if any(t in title for t in _CHALLENGE_TITLES):
                raise FetchProblem(StoreStatus.BLOCKED, "The store showed a bot check instead of products")
            if response is not None and response.status in (403, 429):
                raise FetchProblem(StoreStatus.BLOCKED, f"HTTP {response.status}: the store refused the request")
            if response is None:
                raise FetchProblem(StoreStatus.TIMEOUT, f"No answer from {url} within {timeout:.0f}s")
            # Loaded, but the product selector never appeared: the scraper decides from the HTML
            # whether that means 'no results' or 'layout changed'.
            return Page(url=url, html=await page.content())
        except Exception as exc:
            reason = str(exc).strip().splitlines()[0][:120] if str(exc).strip() else exc.__class__.__name__
            raise FetchProblem(StoreStatus.ERROR, f"Browser could not load {url}: {reason}")
        return Page(url=url, html=await page.content())
    finally:
        await page.close()
