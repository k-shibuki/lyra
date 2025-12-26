"""
Playwright-based browser provider for Lyra.

Implements BrowserProvider protocol using Playwright for browser automation.
Supports both headless and headful modes with CDP connection to Windows Chrome.

Features:
- Automatic headless/headful mode switching
- CDP connection to Windows Chrome for fingerprint consistency
- Resource blocking (ads, trackers, large media)
- Human-like behavior simulation
- Lifecycle management for task-scoped cleanup
"""

import asyncio
import hashlib
import random
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright, Route
    from playwright.async_api._generated import SetCookieParam

from src.crawler.browser_provider import (
    BaseBrowserProvider,
    BrowserHealthStatus,
    BrowserMode,
    BrowserOptions,
    Cookie,
    PageResult,
)
from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class HumanBehaviorSimulator:
    """Simulates human-like browser interactions.

    Implements realistic delays, mouse movements, and scrolling patterns
    to reduce bot detection per ADR-0006 (stealth requirements).
    """

    @staticmethod
    def random_delay(min_seconds: float = 0.5, max_seconds: float = 2.0) -> float:
        """Generate a random delay following human-like distribution.

        Uses log-normal distribution to better simulate human reaction times.
        """
        mu = 0.0
        sigma = 0.5
        delay = random.lognormvariate(mu, sigma)
        return max(min_seconds, min(delay, max_seconds))

    @staticmethod
    def scroll_pattern(page_height: int, viewport_height: int) -> list[tuple[int, float]]:
        """Generate realistic scroll positions and delays."""
        positions = []
        current = 0
        max_scroll = max(0, page_height - viewport_height)

        while current < max_scroll:
            scroll_amount = int(viewport_height * random.uniform(0.5, 1.5))
            current = min(current + scroll_amount, max_scroll)
            delay = HumanBehaviorSimulator.random_delay(0.3, 1.5)
            positions.append((current, delay))

        return positions

    @staticmethod
    async def simulate_reading(page: "Page", content_length: int) -> None:
        """Simulate human reading behavior on page."""
        try:
            dimensions = await page.evaluate("""
                () => ({
                    height: document.body.scrollHeight,
                    viewportHeight: window.innerHeight
                })
            """)

            page_height = dimensions.get("height", 2000)
            viewport_height = dimensions.get("viewportHeight", 1080)

            scroll_positions = HumanBehaviorSimulator.scroll_pattern(page_height, viewport_height)

            for scroll_y, delay in scroll_positions[:5]:  # Limit scrolls
                await page.evaluate(f"window.scrollTo(0, {scroll_y})")
                await asyncio.sleep(delay)

        except Exception as e:
            logger.debug("Reading simulation error", error=str(e))


class PlaywrightProvider(BaseBrowserProvider):
    """
    Browser provider implementation using Playwright.

    Supports:
    - Headless and headful browser modes
    - CDP connection to Windows Chrome
    - Resource blocking for performance
    - Human-like behavior simulation
    - Screenshot and content capture
    """

    def __init__(self) -> None:
        """Initialize Playwright provider."""
        super().__init__("playwright")
        self._settings = get_settings()
        self._playwright: Playwright | None = None
        self._headless_browser: Browser | None = None
        self._headless_context: BrowserContext | None = None
        self._headful_browser: Browser | None = None
        self._headful_context: BrowserContext | None = None
        self._current_page: Page | None = None
        self._human_sim = HumanBehaviorSimulator()

    async def _ensure_playwright(self) -> None:
        """Ensure Playwright is initialized."""
        if self._playwright is None:
            try:
                from playwright.async_api import async_playwright

                self._playwright = await async_playwright().start()
                logger.info("Playwright initialized")
            except ImportError as e:
                raise RuntimeError("Playwright not installed") from e

    async def _get_browser_and_context(
        self,
        mode: BrowserMode,
    ) -> tuple[Any, Any]:
        """Get or create browser and context for the specified mode.

        Args:
            mode: Browser mode (headless/headful).

        Returns:
            Tuple of (browser, context).
        """
        await self._ensure_playwright()
        assert self._playwright is not None  # Guaranteed by _ensure_playwright

        browser_settings = self._settings.browser

        if mode == BrowserMode.HEADFUL:
            if self._headful_browser is None:
                try:
                    # Try CDP connection first (Windows Chrome)
                    # Use base port (worker 0) for default connection
                    cdp_url = (
                        f"http://{browser_settings.chrome_host}:{browser_settings.chrome_base_port}"
                    )
                    self._headful_browser = await self._playwright.chromium.connect_over_cdp(
                        cdp_url
                    )
                    logger.info("Connected to Chrome via CDP (headful)", url=cdp_url)
                except Exception as e:
                    # Per spec ADR-0006: CDP connection is required, no fallback
                    raise RuntimeError(
                        f"CDP connection failed: {e}. Start Chrome with: make chrome-start"
                    ) from e

                # Reuse existing context if available (preserves profile cookies per ADR-0007)
                # This only applies when connected via CDP to real Chrome
                existing_contexts = self._headful_browser.contexts
                if existing_contexts:
                    self._headful_context = existing_contexts[0]
                    logger.info(
                        "Reusing existing browser context for cookie preservation",
                        context_count=len(existing_contexts),
                    )
                else:
                    self._headful_context = await self._headful_browser.new_context(
                        viewport={
                            "width": browser_settings.viewport_width,
                            "height": browser_settings.viewport_height,
                        },
                        locale="ja-JP",
                        timezone_id="Asia/Tokyo",
                    )
                    logger.info("Created new browser context")

            return self._headful_browser, self._headful_context
        else:
            # Per spec ADR-0006: Headless mode is prohibited
            # Lyra uses "real profile consistency" design, not "headless disguised as human"
            raise RuntimeError(
                "Headless mode is prohibited per spec ADR-0006. "
                "Use headful mode with CDP connection to real Chrome profile."
            )

    async def _setup_blocking(self, context: "BrowserContext") -> None:
        """Setup resource blocking rules."""
        browser_settings = self._settings.browser

        block_patterns = []

        if browser_settings.block_ads:
            block_patterns.extend(
                [
                    "*googlesyndication.com*",
                    "*doubleclick.net*",
                    "*googleadservices.com*",
                    "*adnxs.com*",
                    "*criteo.com*",
                ]
            )

        if browser_settings.block_trackers:
            block_patterns.extend(
                [
                    "*google-analytics.com*",
                    "*googletagmanager.com*",
                    "*facebook.com/tr*",
                    "*hotjar.com*",
                    "*mixpanel.com*",
                ]
            )

        if browser_settings.block_large_media:
            block_patterns.extend(
                [
                    "*.mp4",
                    "*.webm",
                    "*.avi",
                    "*.mov",
                ]
            )

        async def block_route(route: "Route") -> None:
            await route.abort()

        for pattern in block_patterns:
            await context.route(pattern, block_route)

    def _is_challenge_page(self, content: str) -> tuple[bool, str | None]:
        """Check if page is a challenge/captcha page.

        Returns:
            Tuple of (is_challenge, challenge_type).
        """
        content_lower = content.lower()

        # Cloudflare indicators
        cloudflare_indicators = [
            "cf-browser-verification",
            "cloudflare ray id",
            "please wait while we verify",
            "checking your browser",
            "just a moment",
            "_cf_chl_opt",
        ]

        if any(ind in content_lower for ind in cloudflare_indicators):
            return True, "cloudflare"

        # Turnstile indicators
        if "cf-turnstile" in content_lower or "turnstile-widget" in content_lower:
            return True, "turnstile"

        # CAPTCHA indicators
        if "hcaptcha" in content_lower or "h-captcha" in content_lower:
            return True, "hcaptcha"

        if "recaptcha" in content_lower or "g-recaptcha" in content_lower:
            return True, "recaptcha"

        if "captcha" in content_lower:
            return True, "captcha"

        return False, None

    async def _save_content(self, url: str, content: bytes) -> Path | None:
        """Save fetched content to file."""
        cache_dir = Path(self._settings.storage.cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)

        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        filename = f"{timestamp}_{url_hash}_pw.html"
        filepath = cache_dir / filename

        filepath.write_bytes(content)
        return filepath

    async def _save_screenshot(self, page: "Page", url: str) -> Path | None:
        """Save page screenshot."""
        screenshots_dir = Path(self._settings.storage.screenshots_dir)
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        filename = f"{timestamp}_{url_hash}_pw.png"
        filepath = screenshots_dir / filename

        try:
            await page.screenshot(path=str(filepath), full_page=False)
            return filepath
        except Exception as e:
            logger.debug("Screenshot failed", error=str(e))
            return None

    async def navigate(
        self,
        url: str,
        options: BrowserOptions | None = None,
    ) -> PageResult:
        """Navigate to a URL and return the page content."""
        self._check_closed()

        options = options or BrowserOptions()
        start_time = time.time()

        try:
            browser, context = await self._get_browser_and_context(options.mode)

            # Setup blocking if needed
            if options.block_resources:
                await self._setup_blocking(context)

            page = await context.new_page()
            self._current_page = page

            # Set referer if provided
            if options.referer:
                await page.set_extra_http_headers({"Referer": options.referer})

            # Human-like pre-navigation delay
            if options.simulate_human:
                await asyncio.sleep(self._human_sim.random_delay(0.5, 1.5))

            # Navigate
            response = await page.goto(
                url,
                timeout=int(options.timeout * 1000),
                wait_until=options.wait_until,
            )

            if response is None:
                await page.close()
                return PageResult.failure(
                    url=url,
                    error="no_response",
                    provider=self.name,
                    mode=options.mode,
                )

            # Wait for dynamic content
            wait_time = self._human_sim.random_delay(1.0, 2.5) if options.simulate_human else 1.0
            await page.wait_for_timeout(int(wait_time * 1000))

            # Get content
            content = await page.content()
            content_bytes = content.encode("utf-8")
            content_hash = hashlib.sha256(content_bytes).hexdigest()

            # Check for challenge
            is_challenge, challenge_type = self._is_challenge_page(content)
            if is_challenge:
                logger.info(
                    "Challenge detected",
                    url=url[:80],
                    challenge_type=challenge_type,
                    mode=options.mode.value,
                )
                await page.close()
                return PageResult.failure(
                    url=url,
                    error=f"challenge_detected:{challenge_type}",
                    provider=self.name,
                    status=response.status,
                    mode=options.mode,
                    challenge_detected=True,
                    challenge_type=challenge_type,
                )

            # Simulate human reading behavior
            if options.simulate_human:
                await self._human_sim.simulate_reading(page, len(content_bytes))

            # Save content
            html_path = await self._save_content(url, content_bytes)

            # Take screenshot if requested
            screenshot_path = None
            if options.take_screenshot:
                screenshot_path = await self._save_screenshot(page, url)

            # Get cookies
            raw_cookies = await context.cookies()
            cookies = [Cookie.from_dict(c) for c in raw_cookies]

            elapsed_ms = (time.time() - start_time) * 1000

            await page.close()

            logger.info(
                "Playwright navigation success",
                url=url[:80],
                status=response.status,
                content_length=len(content_bytes),
                mode=options.mode.value,
            )

            return PageResult.success(
                url=url,
                content=content,
                provider=self.name,
                status=response.status,
                content_hash=content_hash,
                cookies=cookies,
                screenshot_path=str(screenshot_path) if screenshot_path else None,
                html_path=str(html_path) if html_path else None,
                mode=options.mode,
                elapsed_ms=elapsed_ms,
            )

        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            logger.error(
                "Playwright navigation error",
                url=url[:80],
                error=str(e),
                mode=options.mode.value,
            )
            return PageResult.failure(
                url=url,
                error=str(e),
                provider=self.name,
                mode=options.mode,
            )

    async def execute_script(
        self,
        script: str,
        *args: Any,
    ) -> Any:
        """Execute JavaScript on the current page."""
        self._check_closed()

        if self._current_page is None:
            raise RuntimeError("No page available for script execution")

        return await self._current_page.evaluate(script, *args)

    async def get_cookies(self, url: str | None = None) -> list[Cookie]:
        """Get cookies from the browser."""
        self._check_closed()

        cookies = []

        for context in [self._headless_context, self._headful_context]:
            if context is not None:
                try:
                    if url:
                        raw_cookies = await context.cookies([url])
                    else:
                        raw_cookies = await context.cookies()
                    cookies.extend([Cookie.from_dict(cast(dict[str, Any], c)) for c in raw_cookies])
                except Exception as e:
                    logger.debug("Failed to get cookies", error=str(e))

        return cookies

    async def set_cookies(self, cookies: list[Cookie]) -> None:
        """Set cookies in the browser."""
        self._check_closed()

        cookie_dicts = cast("list[SetCookieParam]", [c.to_dict() for c in cookies])

        for context in [self._headless_context, self._headful_context]:
            if context is not None:
                try:
                    await context.add_cookies(cookie_dicts)
                except Exception as e:
                    logger.debug("Failed to set cookies", error=str(e))

    async def take_screenshot(
        self,
        path: str | None = None,
        full_page: bool = False,
    ) -> str | None:
        """Take a screenshot of the current page."""
        self._check_closed()

        if self._current_page is None:
            return None

        if path is None:
            screenshots_dir = Path(self._settings.storage.screenshots_dir)
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = str(screenshots_dir / f"{timestamp}_manual_pw.png")

        try:
            await self._current_page.screenshot(path=path, full_page=full_page)
            return path
        except Exception as e:
            logger.error("Screenshot failed", error=str(e))
            return None

    async def get_health(self) -> BrowserHealthStatus:
        """Get current health status."""
        try:
            # Check if Playwright is available
            from playwright.async_api import async_playwright  # noqa: F401
        except ImportError:
            return BrowserHealthStatus.unavailable("Playwright not installed")

        if self._is_closed:
            return BrowserHealthStatus.unhealthy("Provider is closed")

        return BrowserHealthStatus.healthy()

    async def close(self) -> None:
        """Close and cleanup provider resources."""
        if self._headless_context:
            try:
                await self._headless_context.close()
            except Exception:
                pass
            self._headless_context = None

        if self._headless_browser:
            try:
                await self._headless_browser.close()
            except Exception:
                pass
            self._headless_browser = None

        if self._headful_context:
            try:
                await self._headful_context.close()
            except Exception:
                pass
            self._headful_context = None

        if self._headful_browser:
            try:
                await self._headful_browser.close()
            except Exception:
                pass
            self._headful_browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        self._current_page = None

        await super().close()
        logger.info("Playwright provider closed")


# ============================================================================
# Factory and Global Instance
# ============================================================================

_playwright_provider: PlaywrightProvider | None = None


def get_playwright_provider() -> PlaywrightProvider:
    """
    Get or create the global PlaywrightProvider instance.

    Returns:
        PlaywrightProvider instance.
    """
    global _playwright_provider

    if _playwright_provider is None:
        _playwright_provider = PlaywrightProvider()

    return _playwright_provider


async def close_playwright_provider() -> None:
    """Close the global PlaywrightProvider instance."""
    global _playwright_provider

    if _playwright_provider is not None:
        await _playwright_provider.close()
        _playwright_provider = None


def reset_playwright_provider() -> None:
    """Reset the global provider without closing. For testing only."""
    global _playwright_provider
    _playwright_provider = None
