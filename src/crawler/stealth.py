"""
Browser stealth utilities for Lyra.

Implements minimal anti-bot detection measures per §4.3:
- navigator.webdriver property override
- Viewport jitter with hysteresis
- Other minimal stealth properties

Note: Excessive fingerprint manipulation is avoided to maintain consistency.
"""

import random
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.utils.logging import get_logger

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page

logger = get_logger(__name__)


# =============================================================================
# Stealth JavaScript Injections
# =============================================================================

# Minimal stealth.js equivalent - overrides navigator.webdriver and related properties
# per §4.3 (Browser/JS Layer)
STEALTH_JS = """
(() => {
    // Override navigator.webdriver
    // This property is set to true when browser is controlled via automation
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
        configurable: true
    });

    // Remove automation-related properties from navigator
    const automationProps = [
        'webdriver',
        '__webdriver_script_fn',
        '__driver_evaluate',
        '__webdriver_evaluate',
        '__selenium_evaluate',
        '__fxdriver_evaluate',
        '__driver_unwrapped',
        '__webdriver_unwrapped',
        '__selenium_unwrapped',
        '__fxdriver_unwrapped'
    ];

    for (const prop of automationProps) {
        try {
            delete navigator[prop];
        } catch (e) {}

        try {
            Object.defineProperty(navigator, prop, {
                get: () => undefined,
                configurable: true
            });
        } catch (e) {}
    }

    // Override navigator.permissions.query to hide automation
    const originalQuery = navigator.permissions?.query?.bind(navigator.permissions);
    if (originalQuery) {
        navigator.permissions.query = (parameters) => {
            if (parameters.name === 'notifications') {
                return Promise.resolve({ state: Notification.permission });
            }
            return originalQuery(parameters);
        };
    }

    // Override chrome.runtime to appear as normal browser
    if (!window.chrome) {
        window.chrome = {};
    }
    if (!window.chrome.runtime) {
        window.chrome.runtime = {};
    }

    // Override plugins array to have realistic length
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const plugins = [
                { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                { name: 'Native Client', filename: 'internal-nacl-plugin' }
            ];
            plugins.item = (i) => plugins[i];
            plugins.namedItem = (name) => plugins.find(p => p.name === name);
            plugins.refresh = () => {};
            return plugins;
        },
        configurable: true
    });

    // Override languages to be realistic
    Object.defineProperty(navigator, 'languages', {
        get: () => ['ja-JP', 'ja', 'en-US', 'en'],
        configurable: true
    });

    // Ensure hardwareConcurrency returns realistic value
    Object.defineProperty(navigator, 'hardwareConcurrency', {
        get: () => 8,
        configurable: true
    });

    // Ensure deviceMemory returns realistic value
    Object.defineProperty(navigator, 'deviceMemory', {
        get: () => 8,
        configurable: true
    });

    // Remove Playwright/Puppeteer detection
    delete window.__playwright;
    delete window.__puppeteer;
    delete window.callPhantom;
    delete window._phantom;

    // Override toString to hide modifications
    const originalToString = Function.prototype.toString;
    Function.prototype.toString = function() {
        if (this === navigator.permissions.query) {
            return 'function query() { [native code] }';
        }
        return originalToString.call(this);
    };
})();
"""

# Additional injection for CDP-connected browsers (Windows Chrome)
CDP_STEALTH_JS = """
(() => {
    // For CDP-connected browsers, ensure webdriver is still overridden
    // even if it was set before connection
    try {
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
            configurable: true
        });
    } catch (e) {}

    // Remove CDP-specific detection markers
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
})();
"""


# =============================================================================
# Viewport Jitter with Hysteresis
# =============================================================================


@dataclass
class ViewportJitterConfig:
    """Configuration for viewport jitter.

    Attributes:
        base_width: Base viewport width.
        base_height: Base viewport height.
        max_width_jitter: Maximum width jitter in pixels.
        max_height_jitter: Maximum height jitter in pixels.
        hysteresis_seconds: Minimum time between jitter changes (per §4.3).
        enabled: Whether jitter is enabled.
    """

    base_width: int = 1920
    base_height: int = 1080
    max_width_jitter: int = 20  # Narrow jitter per §4.3
    max_height_jitter: int = 15
    hysteresis_seconds: float = 300.0  # 5 minutes minimum between changes
    enabled: bool = True


@dataclass
class ViewportState:
    """Tracks viewport state for hysteresis.

    Attributes:
        current_width: Current viewport width.
        current_height: Current viewport height.
        last_change_time: Timestamp of last jitter change.
    """

    current_width: int = 1920
    current_height: int = 1080
    last_change_time: float = 0.0


class ViewportJitter:
    """Applies viewport jitter with hysteresis to reduce fingerprinting.

    Per §4.3, viewport jitter is applied with narrow limits and hysteresis
    to prevent oscillation while still providing some randomization.
    """

    def __init__(self, config: ViewportJitterConfig | None = None):
        """Initialize viewport jitter.

        Args:
            config: Jitter configuration. Uses defaults if not provided.
        """
        self._config = config or ViewportJitterConfig()
        self._state = ViewportState(
            current_width=self._config.base_width,
            current_height=self._config.base_height,
        )

    def get_viewport(self, force_update: bool = False) -> dict[str, int]:
        """Get viewport dimensions with jitter applied.

        Respects hysteresis - won't change dimensions if too recent.

        Args:
            force_update: Force jitter update regardless of hysteresis.

        Returns:
            Dict with 'width' and 'height' keys.
        """
        if not self._config.enabled:
            return {
                "width": self._config.base_width,
                "height": self._config.base_height,
            }

        current_time = time.time()
        time_since_last = current_time - self._state.last_change_time

        # Check hysteresis
        if not force_update and time_since_last < self._config.hysteresis_seconds:
            logger.debug(
                "Viewport jitter skipped (hysteresis)",
                time_since_last=time_since_last,
                hysteresis=self._config.hysteresis_seconds,
            )
            return {
                "width": self._state.current_width,
                "height": self._state.current_height,
            }

        # Apply narrow jitter
        width_jitter = random.randint(
            -self._config.max_width_jitter,
            self._config.max_width_jitter,
        )
        height_jitter = random.randint(
            -self._config.max_height_jitter,
            self._config.max_height_jitter,
        )

        new_width = self._config.base_width + width_jitter
        new_height = self._config.base_height + height_jitter

        # Update state
        self._state.current_width = new_width
        self._state.current_height = new_height
        self._state.last_change_time = current_time

        logger.debug(
            "Viewport jitter applied",
            width=new_width,
            height=new_height,
            width_jitter=width_jitter,
            height_jitter=height_jitter,
        )

        return {
            "width": new_width,
            "height": new_height,
        }

    def reset(self) -> None:
        """Reset viewport state to base dimensions."""
        self._state = ViewportState(
            current_width=self._config.base_width,
            current_height=self._config.base_height,
        )


# =============================================================================
# Stealth Application
# =============================================================================


async def apply_stealth_to_page(page: "Page", is_cdp: bool = False) -> None:
    """Apply stealth measures to a Playwright page.

    Injects JavaScript to override navigator.webdriver and related
    properties per §4.3 requirements.

    Args:
        page: Playwright page object.
        is_cdp: Whether the browser is connected via CDP.
    """
    try:
        # Inject main stealth script
        await page.add_init_script(STEALTH_JS)

        # For CDP connections, add additional overrides
        if is_cdp:
            await page.add_init_script(CDP_STEALTH_JS)

        logger.debug("Stealth scripts applied to page", is_cdp=is_cdp)

    except Exception as e:
        logger.warning("Failed to apply stealth scripts", error=str(e))


async def apply_stealth_to_context(context: "BrowserContext", is_cdp: bool = False) -> None:
    """Apply stealth measures to a Playwright browser context.

    Ensures all new pages in the context have stealth measures applied.

    Args:
        context: Playwright browser context.
        is_cdp: Whether the browser is connected via CDP.
    """
    try:
        # Add init script to context so all new pages get it
        await context.add_init_script(STEALTH_JS)

        if is_cdp:
            await context.add_init_script(CDP_STEALTH_JS)

        logger.info("Stealth scripts applied to context", is_cdp=is_cdp)

    except Exception as e:
        logger.warning("Failed to apply stealth to context", error=str(e))


def get_stealth_args() -> list[str]:
    """Get Chrome/Chromium launch arguments for stealth.

    Returns minimal set of arguments to reduce automation detection.

    Returns:
        List of command-line arguments.
    """
    return [
        # Disable automation-controlled flag
        "--disable-blink-features=AutomationControlled",
        # Disable infobars (e.g., "Chrome is being controlled by automated software")
        "--disable-infobars",
        # Use /dev/shm for faster operation
        "--disable-dev-shm-usage",
        # Disable extensions that might be detected
        "--disable-extensions",
        # Disable background networking
        "--disable-background-networking",
        # Disable sync
        "--disable-sync",
        # Disable translate
        "--disable-translate",
        # Disable various Chrome features that can be fingerprinted
        "--disable-features=IsolateOrigins,site-per-process",
        # Set window size explicitly (can be overridden by viewport)
        "--window-size=1920,1080",
    ]


def verify_stealth(page_content: str) -> dict[str, bool]:
    """Verify stealth measures are working by checking page content.

    This is useful for debugging and testing.

    Args:
        page_content: HTML content of the page.

    Returns:
        Dict with verification results.
    """
    content_lower = page_content.lower()

    results = {
        # Check for automation detection markers
        "no_webdriver_detected": "webdriver" not in content_lower
        or "bot detected" not in content_lower,
        "no_automation_detected": "automation" not in content_lower or "bot" not in content_lower,
        "no_headless_detected": "headless" not in content_lower,
    }

    return results


# Global viewport jitter instance
_viewport_jitter: ViewportJitter | None = None


def get_viewport_jitter(config: ViewportJitterConfig | None = None) -> ViewportJitter:
    """Get or create viewport jitter instance.

    Args:
        config: Optional configuration override.

    Returns:
        ViewportJitter instance.
    """
    global _viewport_jitter

    if _viewport_jitter is None or config is not None:
        _viewport_jitter = ViewportJitter(config)

    return _viewport_jitter
