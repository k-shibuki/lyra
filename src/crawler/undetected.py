"""
Undetected ChromeDriver integration for Lancet.

Provides fallback browser automation for Cloudflare/Turnstile bypass per §4.3:
- Cloudflare advanced challenge bypass
- Turnstile CAPTCHA bypass
- Other sophisticated anti-bot protection bypass

This module wraps undetected-chromedriver as a fallback when Playwright fails.
"""

import asyncio
import hashlib
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from undetected_chromedriver import ChromeOptions

from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class UndetectedFetchResult:
    """Result of an undetected-chromedriver fetch operation."""

    ok: bool
    url: str
    status: int | None = None
    content: str | None = None
    content_hash: str | None = None
    html_path: str | None = None
    screenshot_path: str | None = None
    reason: str | None = None
    method: str = "undetected_chromedriver"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "ok": self.ok,
            "url": self.url,
            "status": self.status,
            "content": self.content,
            "content_hash": self.content_hash,
            "html_path": self.html_path,
            "screenshot_path": self.screenshot_path,
            "reason": self.reason,
            "method": self.method,
        }


class UndetectedChromeFetcher:
    """Browser-based fetcher using undetected-chromedriver.

    This is a fallback for cases where Playwright fails due to strong
    anti-bot protection like Cloudflare or Turnstile (§4.3).

    Features:
    - Automatic ChromeDriver patching to avoid detection
    - Human-like behavior simulation
    - Support for headless and headful modes
    - Integration with existing cookie/session management

    Note: This uses Selenium under the hood, which is synchronous.
    Methods are wrapped to work with async code.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._driver = None
        self._available: bool | None = None

    def is_available(self) -> bool:
        """Check if undetected-chromedriver is available.

        Returns:
            True if the library is installed and importable.
        """
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
        headless: bool = False,
        user_data_dir: str | None = None,
    ) -> "ChromeOptions":
        """Create Chrome options for undetected-chromedriver.

        Args:
            headless: Whether to run in headless mode.
            user_data_dir: Path to user data directory for profile persistence.

        Returns:
            Chrome options object.
        """
        import undetected_chromedriver as uc

        options = uc.ChromeOptions()

        browser_settings = self._settings.browser

        # Set window size
        options.add_argument(
            f"--window-size={browser_settings.viewport_width},{browser_settings.viewport_height}"
        )

        # Language and locale settings
        options.add_argument("--lang=ja-JP")
        options.add_argument("--accept-lang=ja-JP,ja,en-US,en")

        # Disable notifications
        options.add_argument("--disable-notifications")

        # Disable extensions that might interfere
        options.add_argument("--disable-extensions")

        # Disable GPU for headless (more stable)
        if headless:
            options.add_argument("--headless=new")  # Use new headless mode
            options.add_argument("--disable-gpu")

        # User data directory for session persistence
        if user_data_dir:
            options.add_argument(f"--user-data-dir={user_data_dir}")

        # Additional stability options
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-setuid-sandbox")

        # Disable automation-related flags
        options.add_argument("--disable-blink-features=AutomationControlled")

        return options

    def _init_driver(
        self,
        headless: bool = False,
        user_data_dir: str | None = None,
    ) -> None:
        """Initialize the undetected-chromedriver instance.

        Args:
            headless: Whether to run in headless mode.
            user_data_dir: Path to user data directory.
        """
        if not self.is_available():
            raise RuntimeError("undetected-chromedriver is not available")

        import undetected_chromedriver as uc

        options = self._create_options(
            headless=headless,
            user_data_dir=user_data_dir,
        )

        # Create driver with version matching
        # use_subprocess=True helps avoid detection in some cases
        self._driver = uc.Chrome(
            options=options,
            use_subprocess=True,
            version_main=None,  # Auto-detect Chrome version
        )
        assert self._driver is not None  # Just initialized

        # Set page load timeout
        self._driver.set_page_load_timeout(self._settings.crawler.page_load_timeout)

        # Set implicit wait
        self._driver.implicitly_wait(10)

        logger.info(
            "Initialized undetected-chromedriver",
            headless=headless,
            user_data_dir=user_data_dir,
        )

    def _simulate_human_delay(
        self, min_seconds: float = 0.5, max_seconds: float = 2.0
    ) -> None:
        """Add human-like delay between actions.

        Args:
            min_seconds: Minimum delay.
            max_seconds: Maximum delay.
        """
        import random

        delay = random.uniform(min_seconds, max_seconds)
        time.sleep(delay)

    def _simulate_scroll(self) -> None:
        """Simulate human-like scrolling behavior."""
        if not self._driver:
            return

        import random

        try:
            # Get page height
            page_height = self._driver.execute_script("return document.body.scrollHeight")
            viewport_height = self._driver.execute_script("return window.innerHeight")

            # Scroll down in chunks
            current_position = 0
            max_scrolls = 3  # Limit scrolls

            for _ in range(max_scrolls):
                if current_position >= page_height - viewport_height:
                    break

                # Random scroll amount
                scroll_amount = random.randint(
                    int(viewport_height * 0.5),
                    int(viewport_height * 1.2),
                )
                current_position = min(
                    current_position + scroll_amount,
                    page_height - viewport_height,
                )

                self._driver.execute_script(f"window.scrollTo(0, {current_position})")

                # Random delay
                time.sleep(random.uniform(0.3, 1.0))

        except Exception as e:
            logger.debug("Scroll simulation failed", error=str(e))

    def _wait_for_cloudflare(self, timeout: int = 30) -> bool:
        """Wait for Cloudflare challenge to complete.

        Args:
            timeout: Maximum seconds to wait.

        Returns:
            True if challenge was bypassed.
        """
        if not self._driver:
            return False

        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                # Check if Cloudflare challenge is still present
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

                # Wait a bit before checking again
                time.sleep(1.0)

            except Exception as e:
                logger.debug("Error checking Cloudflare status", error=str(e))
                time.sleep(0.5)

        logger.warning("Cloudflare challenge timeout", timeout=timeout)
        return False

    def _save_content(self, url: str, content: str) -> Path | None:
        """Save page content to file.

        Args:
            url: Source URL.
            content: HTML content.

        Returns:
            Path to saved file.
        """
        settings = get_settings()
        cache_dir = Path(settings.storage.cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)

        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        filename = f"{timestamp}_{url_hash}_uc.html"
        filepath = cache_dir / filename

        filepath.write_text(content, encoding="utf-8")

        return filepath

    def _save_screenshot(self, url: str) -> Path | None:
        """Save page screenshot.

        Args:
            url: Source URL.

        Returns:
            Path to screenshot file.
        """
        if not self._driver:
            return None

        settings = get_settings()
        screenshots_dir = Path(settings.storage.screenshots_dir)
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

    def fetch_sync(
        self,
        url: str,
        *,
        headless: bool = False,
        wait_for_cloudflare: bool = True,
        cloudflare_timeout: int = 30,
        take_screenshot: bool = True,
        simulate_human: bool = True,
    ) -> UndetectedFetchResult:
        """Synchronously fetch a URL using undetected-chromedriver.

        This is the core fetch method that runs in a synchronous context.

        Args:
            url: URL to fetch.
            headless: Whether to run in headless mode (less effective for bypass).
            wait_for_cloudflare: Whether to wait for Cloudflare challenge.
            cloudflare_timeout: Timeout for Cloudflare bypass.
            take_screenshot: Whether to capture screenshot.
            simulate_human: Whether to simulate human behavior.

        Returns:
            UndetectedFetchResult instance.
        """
        if not self.is_available():
            return UndetectedFetchResult(
                ok=False,
                url=url,
                reason="undetected_chromedriver_not_available",
            )

        try:
            # Initialize driver if not already done
            if self._driver is None:
                self._init_driver(headless=headless)
            assert self._driver is not None  # Guaranteed by _init_driver

            # Navigate to URL
            logger.info("Navigating with undetected-chromedriver", url=url[:80])
            self._driver.get(url)

            # Wait for Cloudflare if needed
            if wait_for_cloudflare:
                page_source = self._driver.page_source.lower()
                cf_detected = any(
                    ind in page_source
                    for ind in ["cf-browser-verification", "checking your browser", "cf-turnstile"]
                )

                if cf_detected:
                    logger.info("Cloudflare detected, waiting for bypass", url=url[:80])
                    if not self._wait_for_cloudflare(cloudflare_timeout):
                        return UndetectedFetchResult(
                            ok=False,
                            url=url,
                            reason="cloudflare_bypass_timeout",
                        )

            # Simulate human behavior
            if simulate_human:
                self._simulate_human_delay(1.0, 2.5)
                self._simulate_scroll()

            # Get page content
            content = self._driver.page_source
            content_hash = hashlib.sha256(content.encode()).hexdigest()

            # Save content
            html_path = self._save_content(url, content)

            # Take screenshot
            screenshot_path = None
            if take_screenshot:
                screenshot_path = self._save_screenshot(url)

            logger.info(
                "Undetected-chromedriver fetch success",
                url=url[:80],
                content_length=len(content),
            )

            return UndetectedFetchResult(
                ok=True,
                url=url,
                status=200,  # Selenium doesn't provide HTTP status directly
                content=content,
                content_hash=content_hash,
                html_path=str(html_path) if html_path else None,
                screenshot_path=str(screenshot_path) if screenshot_path else None,
            )

        except Exception as e:
            logger.error(
                "Undetected-chromedriver fetch error",
                url=url[:80],
                error=str(e),
            )
            return UndetectedFetchResult(
                ok=False,
                url=url,
                reason=str(e),
            )

    async def fetch(
        self,
        url: str,
        *,
        headless: bool = False,
        wait_for_cloudflare: bool = True,
        cloudflare_timeout: int = 30,
        take_screenshot: bool = True,
        simulate_human: bool = True,
    ) -> UndetectedFetchResult:
        """Asynchronously fetch a URL using undetected-chromedriver.

        Wraps the synchronous fetch method to work with async code.

        Args:
            url: URL to fetch.
            headless: Whether to run in headless mode.
            wait_for_cloudflare: Whether to wait for Cloudflare challenge.
            cloudflare_timeout: Timeout for Cloudflare bypass.
            take_screenshot: Whether to capture screenshot.
            simulate_human: Whether to simulate human behavior.

        Returns:
            UndetectedFetchResult instance.
        """
        loop = asyncio.get_running_loop()

        # Run synchronous fetch in thread pool
        result = await loop.run_in_executor(
            None,
            lambda: self.fetch_sync(
                url,
                headless=headless,
                wait_for_cloudflare=wait_for_cloudflare,
                cloudflare_timeout=cloudflare_timeout,
                take_screenshot=take_screenshot,
                simulate_human=simulate_human,
            ),
        )

        return result

    def get_cookies(self) -> list[dict[str, Any]]:
        """Get all cookies from the current session.

        Returns:
            List of cookie dictionaries.
        """
        if not self._driver:
            return []

        try:
            return self._driver.get_cookies()
        except Exception as e:
            logger.debug("Failed to get cookies", error=str(e))
            return []

    def add_cookies(self, cookies: list[dict[str, Any]]) -> None:
        """Add cookies to the current session.

        Args:
            cookies: List of cookie dictionaries.
        """
        if not self._driver:
            return

        for cookie in cookies:
            try:
                self._driver.add_cookie(cookie)
            except Exception as e:
                logger.debug(
                    "Failed to add cookie",
                    cookie_name=cookie.get("name"),
                    error=str(e),
                )

    def close(self) -> None:
        """Close the browser and cleanup."""
        if self._driver:
            try:
                self._driver.quit()
                logger.info("Closed undetected-chromedriver")
            except Exception as e:
                logger.debug("Error closing driver", error=str(e))
            finally:
                self._driver = None

    async def close_async(self) -> None:
        """Asynchronously close the browser."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.close)

    def __enter__(self) -> "UndetectedChromeFetcher":
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> Literal[False]:
        """Context manager exit - cleanup driver."""
        self.close()
        return False


# Global instance
_undetected_fetcher: UndetectedChromeFetcher | None = None


def get_undetected_fetcher() -> UndetectedChromeFetcher:
    """Get or create the global UndetectedChromeFetcher instance.

    Returns:
        UndetectedChromeFetcher instance.
    """
    global _undetected_fetcher

    if _undetected_fetcher is None:
        _undetected_fetcher = UndetectedChromeFetcher()

    return _undetected_fetcher


async def close_undetected_fetcher() -> None:
    """Close the global UndetectedChromeFetcher instance."""
    global _undetected_fetcher

    if _undetected_fetcher is not None:
        await _undetected_fetcher.close_async()
        _undetected_fetcher = None
