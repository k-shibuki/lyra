"""
Undetected ChromeDriver browser provider for Lancet.

Implements BrowserProvider protocol using undetected-chromedriver for
Cloudflare/Turnstile bypass per §4.3.

This provider is intended as a fallback when Playwright fails due to
strong anti-bot protection.

Features:
- Automatic ChromeDriver patching to avoid detection
- Human-like behavior simulation
- Support for headless and headful modes
- Cloudflare challenge bypass waiting
"""

import asyncio
import hashlib
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any

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


class UndetectedChromeProvider(BaseBrowserProvider):
    """
    Browser provider implementation using undetected-chromedriver.

    This is a fallback provider for cases where Playwright fails due to
    strong anti-bot protection like Cloudflare or Turnstile (§4.3).

    Features:
    - Automatic ChromeDriver patching to avoid detection
    - Human-like behavior simulation
    - Support for headless and headful modes
    - Integration with existing cookie/session management

    Note: Uses Selenium under the hood (synchronous). Methods are wrapped
    for async compatibility.
    """

    def __init__(self) -> None:
        """Initialize UndetectedChrome provider."""
        super().__init__("undetected_chrome")
        self._settings = get_settings()
        self._driver = None
        self._available: bool | None = None

    def _check_available(self) -> bool:
        """Check if undetected-chromedriver is available."""
        if self._available is not None:
            return self._available

        try:
            import undetected_chromedriver as uc  # noqa: F401

            self._available = True
            logger.debug("undetected-chromedriver is available")
        except ImportError:
            self._available = False
            logger.warning(
                "undetected-chromedriver not available - "
                "install with: pip install undetected-chromedriver"
            )

        return self._available

    def _create_options(
        self,
        mode: BrowserMode,
        options: BrowserOptions,
    ) -> Any:
        """Create Chrome options for undetected-chromedriver."""
        import undetected_chromedriver as uc

        chrome_options = uc.ChromeOptions()

        # Set window size
        chrome_options.add_argument(
            f"--window-size={options.viewport_width},{options.viewport_height}"
        )

        # Language and locale settings
        chrome_options.add_argument("--lang=ja-JP")
        chrome_options.add_argument("--accept-lang=ja-JP,ja,en-US,en")

        # Disable notifications
        chrome_options.add_argument("--disable-notifications")

        # Disable extensions that might interfere
        chrome_options.add_argument("--disable-extensions")

        # Headless mode (if requested)
        if mode == BrowserMode.HEADLESS:
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--disable-gpu")

        # Additional stability options
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-setuid-sandbox")

        # Disable automation-related flags
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")

        return chrome_options

    def _init_driver(self, mode: BrowserMode, options: BrowserOptions) -> None:
        """Initialize the undetected-chromedriver instance."""
        if not self._check_available():
            raise RuntimeError("undetected-chromedriver is not available")

        import undetected_chromedriver as uc

        chrome_options = self._create_options(mode, options)

        # Create driver with version matching
        self._driver = uc.Chrome(
            options=chrome_options,
            use_subprocess=True,
            version_main=None,  # Auto-detect Chrome version
        )
        assert self._driver is not None  # Just initialized

        # Set page load timeout
        self._driver.set_page_load_timeout(int(options.timeout))

        # Set implicit wait
        self._driver.implicitly_wait(10)

        logger.info(
            "Initialized undetected-chromedriver",
            mode=mode.value,
        )

    def _simulate_human_delay(
        self,
        min_seconds: float = 0.5,
        max_seconds: float = 2.0,
    ) -> None:
        """Add human-like delay between actions."""
        delay = random.uniform(min_seconds, max_seconds)
        time.sleep(delay)

    def _simulate_scroll(self) -> None:
        """Simulate human-like scrolling behavior."""
        if not self._driver:
            return

        try:
            page_height = self._driver.execute_script("return document.body.scrollHeight")
            viewport_height = self._driver.execute_script("return window.innerHeight")

            current_position = 0
            max_scrolls = 3

            for _ in range(max_scrolls):
                if current_position >= page_height - viewport_height:
                    break

                scroll_amount = random.randint(
                    int(viewport_height * 0.5),
                    int(viewport_height * 1.2),
                )
                current_position = min(
                    current_position + scroll_amount,
                    page_height - viewport_height,
                )

                self._driver.execute_script(f"window.scrollTo(0, {current_position})")

                time.sleep(random.uniform(0.3, 1.0))

        except Exception as e:
            logger.debug("Scroll simulation failed", error=str(e))

    def _is_challenge_page(self, content: str) -> tuple[bool, str | None]:
        """Check if page is a challenge/captcha page."""
        content_lower = content.lower()

        # Cloudflare indicators
        cloudflare_indicators = [
            "cf-browser-verification",
            "checking your browser",
            "just a moment",
            "_cf_chl_opt",
        ]

        if any(ind in content_lower for ind in cloudflare_indicators):
            return True, "cloudflare"

        # Turnstile indicators
        if "cf-turnstile" in content_lower:
            return True, "turnstile"

        # CAPTCHA indicators
        if "hcaptcha" in content_lower or "h-captcha" in content_lower:
            return True, "hcaptcha"

        if "recaptcha" in content_lower or "g-recaptcha" in content_lower:
            return True, "recaptcha"

        return False, None

    def _wait_for_cloudflare(self, timeout: int = 30) -> bool:
        """Wait for Cloudflare challenge to complete.

        Returns:
            True if challenge was bypassed.
        """
        if not self._driver:
            return False

        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                page_source = self._driver.page_source.lower()

                cf_indicators = [
                    "cf-browser-verification",
                    "checking your browser",
                    "just a moment",
                    "_cf_chl_opt",
                    "cf-turnstile",
                ]

                if not any(ind in page_source for ind in cf_indicators):
                    logger.info(
                        "Cloudflare challenge bypassed",
                        elapsed=time.time() - start_time,
                    )
                    return True

                time.sleep(1.0)

            except Exception as e:
                logger.debug("Error checking Cloudflare status", error=str(e))
                time.sleep(0.5)

        logger.warning("Cloudflare challenge timeout", timeout=timeout)
        return False

    def _save_content(self, url: str, content: str) -> Path | None:
        """Save page content to file."""
        cache_dir = Path(self._settings.storage.cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)

        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        filename = f"{timestamp}_{url_hash}_uc.html"
        filepath = cache_dir / filename

        filepath.write_text(content, encoding="utf-8")
        return filepath

    def _save_screenshot(self, url: str) -> Path | None:
        """Save page screenshot."""
        if not self._driver:
            return None

        screenshots_dir = Path(self._settings.storage.screenshots_dir)
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        filename = f"{timestamp}_{url_hash}_uc.png"
        filepath = screenshots_dir / filename

        try:
            self._driver.save_screenshot(str(filepath))
            return filepath
        except Exception as e:
            logger.debug("Screenshot save failed", error=str(e))
            return None

    def _navigate_sync(
        self,
        url: str,
        options: BrowserOptions,
    ) -> PageResult:
        """Synchronously navigate to a URL.

        This is the core navigation method that runs in a synchronous context.
        """
        start_time = time.time()

        try:
            # Initialize driver if not already done
            if self._driver is None:
                self._init_driver(options.mode, options)
            assert self._driver is not None  # Guaranteed by _init_driver

            # Navigate to URL
            logger.info("Navigating with undetected-chromedriver", url=url[:80])
            self._driver.get(url)

            # Check for Cloudflare challenge
            page_source = self._driver.page_source
            is_challenge, challenge_type = self._is_challenge_page(page_source)

            if is_challenge:
                logger.info(
                    "Challenge detected, waiting for bypass",
                    url=url[:80],
                    challenge_type=challenge_type,
                )
                if not self._wait_for_cloudflare(30):
                    elapsed_ms = (time.time() - start_time) * 1000
                    return PageResult.failure(
                        url=url,
                        error="cloudflare_bypass_timeout",
                        provider=self.name,
                        mode=options.mode,
                        challenge_detected=True,
                        challenge_type=challenge_type,
                    )
                # Re-check content after bypass
                page_source = self._driver.page_source

            # Simulate human behavior
            if options.simulate_human:
                self._simulate_human_delay(1.0, 2.5)
                self._simulate_scroll()

            # Get content
            content = self._driver.page_source
            content_hash = hashlib.sha256(content.encode()).hexdigest()

            # Save content
            html_path = self._save_content(url, content)

            # Take screenshot if requested
            screenshot_path = None
            if options.take_screenshot:
                screenshot_path = self._save_screenshot(url)

            # Get cookies
            raw_cookies = self._driver.get_cookies()
            cookies = [Cookie.from_dict(c) for c in raw_cookies]

            elapsed_ms = (time.time() - start_time) * 1000

            logger.info(
                "Undetected-chromedriver navigation success",
                url=url[:80],
                content_length=len(content),
                mode=options.mode.value,
            )

            return PageResult.success(
                url=url,
                content=content,
                provider=self.name,
                status=200,  # Selenium doesn't provide HTTP status directly
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
                "Undetected-chromedriver navigation error",
                url=url[:80],
                error=str(e),
            )
            return PageResult.failure(
                url=url,
                error=str(e),
                provider=self.name,
                mode=options.mode,
            )

    async def navigate(
        self,
        url: str,
        options: BrowserOptions | None = None,
    ) -> PageResult:
        """Navigate to a URL and return the page content.

        Wraps the synchronous navigation method for async compatibility.
        """
        self._check_closed()

        if not self._check_available():
            return PageResult.failure(
                url=url,
                error="undetected-chromedriver not available",
                provider=self.name,
            )

        options = options or BrowserOptions(mode=BrowserMode.HEADFUL)

        # Run synchronous navigation in thread pool
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._navigate_sync(url, options),
        )

    async def execute_script(
        self,
        script: str,
        *args: Any,
    ) -> Any:
        """Execute JavaScript on the current page."""
        self._check_closed()

        if self._driver is None:
            raise RuntimeError("No browser instance available")

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._driver.execute_script(script, *args),
        )

    async def get_cookies(self, url: str | None = None) -> list[Cookie]:
        """Get cookies from the browser."""
        self._check_closed()

        if self._driver is None:
            return []

        try:
            loop = asyncio.get_running_loop()
            raw_cookies = await loop.run_in_executor(
                None,
                self._driver.get_cookies,
            )
            return [Cookie.from_dict(c) for c in raw_cookies]
        except Exception as e:
            logger.debug("Failed to get cookies", error=str(e))
            return []

    async def set_cookies(self, cookies: list[Cookie]) -> None:
        """Set cookies in the browser."""
        self._check_closed()

        if self._driver is None:
            return

        def _set_cookies_sync() -> None:
            for cookie in cookies:
                try:
                    self._driver.add_cookie(cookie.to_dict())
                except Exception as e:
                    logger.debug(
                        "Failed to add cookie",
                        cookie_name=cookie.name,
                        error=str(e),
                    )

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _set_cookies_sync)

    async def take_screenshot(
        self,
        path: str | None = None,
        full_page: bool = False,
    ) -> str | None:
        """Take a screenshot of the current page."""
        self._check_closed()

        if self._driver is None:
            return None

        if path is None:
            screenshots_dir = Path(self._settings.storage.screenshots_dir)
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = str(screenshots_dir / f"{timestamp}_manual_uc.png")

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: self._driver.save_screenshot(path),
            )
            return path
        except Exception as e:
            logger.error("Screenshot failed", error=str(e))
            return None

    async def get_health(self) -> BrowserHealthStatus:
        """Get current health status."""
        if not self._check_available():
            return BrowserHealthStatus.unavailable("undetected-chromedriver not installed")

        if self._is_closed:
            return BrowserHealthStatus.unhealthy("Provider is closed")

        return BrowserHealthStatus.healthy()

    def _close_sync(self) -> None:
        """Synchronously close the driver."""
        if self._driver:
            try:
                self._driver.quit()
                logger.info("Closed undetected-chromedriver")
            except Exception as e:
                logger.debug("Error closing driver", error=str(e))
            finally:
                self._driver = None

    async def close(self) -> None:
        """Close and cleanup provider resources."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._close_sync)
        await super().close()
        logger.info("UndetectedChrome provider closed")


# ============================================================================
# Factory and Global Instance
# ============================================================================

_undetected_provider: UndetectedChromeProvider | None = None


def get_undetected_provider() -> UndetectedChromeProvider:
    """
    Get or create the global UndetectedChromeProvider instance.

    Returns:
        UndetectedChromeProvider instance.
    """
    global _undetected_provider

    if _undetected_provider is None:
        _undetected_provider = UndetectedChromeProvider()

    return _undetected_provider


async def close_undetected_provider() -> None:
    """Close the global UndetectedChromeProvider instance."""
    global _undetected_provider

    if _undetected_provider is not None:
        await _undetected_provider.close()
        _undetected_provider = None


def reset_undetected_provider() -> None:
    """Reset the global provider without closing. For testing only."""
    global _undetected_provider
    _undetected_provider = None
