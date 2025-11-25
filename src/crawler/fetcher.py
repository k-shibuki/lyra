"""
URL fetcher for Lancet.
Handles fetching URLs via HTTP client or browser with appropriate strategies.

Features:
- HTTP client with Chrome impersonation (curl_cffi)
- Browser automation with Playwright (CDP connection)
- Headless/headful automatic switching based on domain policy
- Human-like behavior simulation (mouse movement, scrolling, delays)
- Tor integration with Stem for circuit control
- ETag/If-Modified-Since conditional requests (304 cache)
"""

import asyncio
import gzip
import hashlib
import io
import math
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from warcio.warcwriter import WARCWriter
from warcio.statusandheaders import StatusAndHeaders

from src.utils.config import get_settings
from src.utils.logging import get_logger, CausalTrace
from src.storage.database import get_database
from src.utils.notification import (
    get_intervention_manager,
    InterventionType,
    InterventionStatus,
)
from src.crawler.sec_fetch import (
    NavigationContext,
    SecFetchDest,
    generate_sec_fetch_headers,
    generate_sec_ch_ua_headers,
)
from src.crawler.stealth import (
    apply_stealth_to_context,
    get_stealth_args,
    get_viewport_jitter,
    ViewportJitterConfig,
)
from src.crawler.profile_audit import (
    get_profile_auditor,
    perform_health_check,
    AuditStatus,
    RepairAction,
)
from src.crawler.browser_archive import (
    get_browser_archiver,
    NetworkEventCollector,
)
from src.crawler.session_transfer import (
    get_session_transfer_manager,
    get_transfer_headers,
    update_session,
    SessionTransferManager,
)

logger = get_logger(__name__)


# =============================================================================
# Human-like Behavior Simulation
# =============================================================================

class HumanBehavior:
    """Simulates human-like browser interactions.
    
    Implements realistic delays, mouse movements, and scrolling patterns
    to reduce bot detection per §4.3 (stealth requirements).
    """
    
    def __init__(self):
        self._settings = get_settings()
    
    @staticmethod
    def random_delay(min_seconds: float = 0.5, max_seconds: float = 2.0) -> float:
        """Generate a random delay following human-like distribution.
        
        Uses log-normal distribution to better simulate human reaction times.
        
        Args:
            min_seconds: Minimum delay.
            max_seconds: Maximum delay.
            
        Returns:
            Delay in seconds.
        """
        # Log-normal distribution parameters (median ~= 1.0s)
        mu = 0.0
        sigma = 0.5
        
        delay = random.lognormvariate(mu, sigma)
        return max(min_seconds, min(delay, max_seconds))
    
    @staticmethod
    def scroll_pattern(page_height: int, viewport_height: int) -> list[tuple[int, float]]:
        """Generate realistic scroll positions and delays.
        
        Args:
            page_height: Total page height in pixels.
            viewport_height: Viewport height in pixels.
            
        Returns:
            List of (scroll_position, delay) tuples.
        """
        positions = []
        current = 0
        max_scroll = max(0, page_height - viewport_height)
        
        while current < max_scroll:
            # Variable scroll amount (50-150% of viewport)
            scroll_amount = int(viewport_height * random.uniform(0.5, 1.5))
            current = min(current + scroll_amount, max_scroll)
            
            # Human-like pause after scrolling
            delay = HumanBehavior.random_delay(0.3, 1.5)
            positions.append((current, delay))
        
        return positions
    
    @staticmethod
    def mouse_path(
        start_x: int, start_y: int,
        end_x: int, end_y: int,
        steps: int = 10,
    ) -> list[tuple[int, int]]:
        """Generate a human-like mouse movement path.
        
        Uses bezier curve interpolation with slight randomness.
        
        Args:
            start_x: Starting X coordinate.
            start_y: Starting Y coordinate.
            end_x: Ending X coordinate.
            end_y: Ending Y coordinate.
            steps: Number of points in the path.
            
        Returns:
            List of (x, y) coordinates.
        """
        path = []
        
        # Add random control point for bezier curve
        ctrl_x = (start_x + end_x) / 2 + random.uniform(-50, 50)
        ctrl_y = (start_y + end_y) / 2 + random.uniform(-50, 50)
        
        for i in range(steps + 1):
            t = i / steps
            
            # Quadratic bezier interpolation
            x = (1 - t) ** 2 * start_x + 2 * (1 - t) * t * ctrl_x + t ** 2 * end_x
            y = (1 - t) ** 2 * start_y + 2 * (1 - t) * t * ctrl_y + t ** 2 * end_y
            
            # Add small jitter
            x += random.uniform(-2, 2)
            y += random.uniform(-2, 2)
            
            path.append((int(x), int(y)))
        
        return path
    
    async def simulate_reading(self, page, content_length: int) -> None:
        """Simulate human reading behavior on page.
        
        Args:
            page: Playwright page object.
            content_length: Approximate content length.
        """
        try:
            # Get page dimensions
            dimensions = await page.evaluate("""
                () => ({
                    height: document.body.scrollHeight,
                    viewportHeight: window.innerHeight
                })
            """)
            
            page_height = dimensions.get("height", 2000)
            viewport_height = dimensions.get("viewportHeight", 1080)
            
            # Scroll through page
            scroll_positions = self.scroll_pattern(page_height, viewport_height)
            
            for scroll_y, delay in scroll_positions[:5]:  # Limit scrolls
                await page.evaluate(f"window.scrollTo(0, {scroll_y})")
                await asyncio.sleep(delay)
                
        except Exception as e:
            logger.debug("Reading simulation error", error=str(e))
    
    async def move_mouse_to_element(self, page, selector: str) -> None:
        """Move mouse to element with human-like motion.
        
        Args:
            page: Playwright page object.
            selector: CSS selector for target element.
        """
        try:
            element = await page.query_selector(selector)
            if not element:
                return
            
            box = await element.bounding_box()
            if not box:
                return
            
            # Current mouse position (assume center)
            viewport = page.viewport_size or {"width": 1920, "height": 1080}
            start_x = viewport["width"] // 2
            start_y = viewport["height"] // 2
            
            # Target position (center of element with jitter)
            end_x = int(box["x"] + box["width"] / 2 + random.uniform(-5, 5))
            end_y = int(box["y"] + box["height"] / 2 + random.uniform(-5, 5))
            
            # Generate path and move
            path = self.mouse_path(start_x, start_y, end_x, end_y)
            
            for x, y in path:
                await page.mouse.move(x, y)
                await asyncio.sleep(random.uniform(0.01, 0.03))
                
        except Exception as e:
            logger.debug("Mouse movement error", error=str(e))


# =============================================================================
# Tor Circuit Controller
# =============================================================================

class TorController:
    """Controls Tor circuits via Stem library.
    
    Provides circuit renewal and exit node management per §4.3.
    """
    
    def __init__(self):
        self._settings = get_settings()
        self._controller = None
        self._last_renewal: dict[str, float] = {}  # domain -> timestamp
        self._lock = asyncio.Lock()
    
    async def connect(self) -> bool:
        """Connect to Tor control port.
        
        Returns:
            True if connected successfully.
        """
        if not self._settings.tor.enabled:
            return False
        
        try:
            from stem.control import Controller
            
            self._controller = Controller.from_port(
                address=self._settings.tor.socks_host,
                port=self._settings.tor.control_port,
            )
            
            # Try to authenticate (no password by default)
            self._controller.authenticate()
            
            logger.info(
                "Connected to Tor control port",
                port=self._settings.tor.control_port,
            )
            return True
            
        except Exception as e:
            logger.warning("Tor control connection failed", error=str(e))
            self._controller = None
            return False
    
    async def renew_circuit(self, domain: str | None = None) -> bool:
        """Request a new Tor circuit.
        
        Args:
            domain: Optional domain for sticky circuit tracking.
            
        Returns:
            True if circuit renewed successfully.
        """
        async with self._lock:
            if self._controller is None:
                if not await self.connect():
                    return False
            
            try:
                # Check sticky period for domain
                if domain:
                    sticky_minutes = self._settings.tor.circuit_sticky_minutes
                    last = self._last_renewal.get(domain, 0)
                    
                    if time.time() - last < sticky_minutes * 60:
                        logger.debug(
                            "Skipping circuit renewal (sticky period)",
                            domain=domain,
                        )
                        return True
                
                # Request new circuit
                self._controller.signal("NEWNYM")
                
                # Wait for circuit to establish
                await asyncio.sleep(2.0)
                
                if domain:
                    self._last_renewal[domain] = time.time()
                
                logger.info("Tor circuit renewed", domain=domain)
                return True
                
            except Exception as e:
                logger.error("Tor circuit renewal failed", error=str(e))
                return False
    
    async def get_exit_ip(self) -> str | None:
        """Get current Tor exit node IP.
        
        Returns:
            Exit IP address or None.
        """
        try:
            from curl_cffi import requests as curl_requests
            
            tor_settings = self._settings.tor
            proxy_url = f"socks5://{tor_settings.socks_host}:{tor_settings.socks_port}"
            
            response = curl_requests.get(
                "https://check.torproject.org/api/ip",
                proxies={"http": proxy_url, "https": proxy_url},
                timeout=10,
            )
            
            data = response.json()
            return data.get("IP")
            
        except Exception as e:
            logger.debug("Failed to get Tor exit IP", error=str(e))
            return None
    
    def close(self) -> None:
        """Close Tor controller connection."""
        if self._controller:
            try:
                self._controller.close()
            except Exception:
                pass
            self._controller = None


# Global Tor controller
_tor_controller: TorController | None = None


async def get_tor_controller() -> TorController:
    """Get or create Tor controller instance.
    
    Returns:
        TorController instance.
    """
    global _tor_controller
    if _tor_controller is None:
        _tor_controller = TorController()
    return _tor_controller


class FetchResult:
    """Result of a fetch operation."""
    
    def __init__(
        self,
        ok: bool,
        url: str,
        *,
        status: int | None = None,
        headers: dict[str, str] | None = None,
        html_path: str | None = None,
        pdf_path: str | None = None,
        warc_path: str | None = None,
        screenshot_path: str | None = None,
        cdxj_path: str | None = None,
        har_path: str | None = None,
        content_hash: str | None = None,
        reason: str | None = None,
        method: str = "http_client",
        from_cache: bool = False,
        etag: str | None = None,
        last_modified: str | None = None,
    ):
        self.ok = ok
        self.url = url
        self.status = status
        self.headers = headers or {}
        self.html_path = html_path
        self.pdf_path = pdf_path
        self.warc_path = warc_path
        self.screenshot_path = screenshot_path
        self.cdxj_path = cdxj_path
        self.har_path = har_path
        self.content_hash = content_hash
        self.reason = reason
        self.method = method
        self.from_cache = from_cache
        self.etag = etag
        self.last_modified = last_modified
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "ok": self.ok,
            "url": self.url,
            "status": self.status,
            "headers": self.headers,
            "html_path": self.html_path,
            "pdf_path": self.pdf_path,
            "warc_path": self.warc_path,
            "screenshot_path": self.screenshot_path,
            "cdxj_path": self.cdxj_path,
            "har_path": self.har_path,
            "content_hash": self.content_hash,
            "reason": self.reason,
            "method": self.method,
            "from_cache": self.from_cache,
            "etag": self.etag,
            "last_modified": self.last_modified,
        }


class RateLimiter:
    """Per-domain rate limiter."""
    
    def __init__(self):
        self._domain_locks: dict[str, asyncio.Lock] = {}
        self._domain_last_request: dict[str, float] = {}
        self._settings = get_settings()
    
    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc.lower()
    
    async def acquire(self, url: str) -> None:
        """Acquire rate limit slot for a domain.
        
        Args:
            url: URL to fetch.
        """
        domain = self._get_domain(url)
        
        if domain not in self._domain_locks:
            self._domain_locks[domain] = asyncio.Lock()
        
        async with self._domain_locks[domain]:
            last_request = self._domain_last_request.get(domain, 0)
            min_interval = 1.0 / self._settings.crawler.domain_qps
            
            # Add jitter
            delay_min = self._settings.crawler.delay_min
            delay_max = self._settings.crawler.delay_max
            jitter = random.uniform(delay_min, delay_max)
            
            elapsed = time.time() - last_request
            wait_time = max(0, min_interval + jitter - elapsed)
            
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            
            self._domain_last_request[domain] = time.time()


class HTTPFetcher:
    """HTTP client fetcher using curl_cffi."""
    
    def __init__(self):
        self._rate_limiter = RateLimiter()
        self._settings = get_settings()
    
    async def fetch(
        self,
        url: str,
        *,
        referer: str | None = None,
        headers: dict[str, str] | None = None,
        use_tor: bool = False,
        cached_etag: str | None = None,
        cached_last_modified: str | None = None,
        session_id: str | None = None,
    ) -> FetchResult:
        """Fetch URL using HTTP client with conditional request support.
        
        Implements §4.3 sec-fetch-* header requirements:
        - Sec-Fetch-Site: Relationship between initiator and target
        - Sec-Fetch-Mode: Request mode (navigate for document fetch)
        - Sec-Fetch-Dest: Request destination (document for pages)
        - Sec-Fetch-User: ?1 for user-initiated navigation
        
        Session Transfer (§3.1.2):
        When session_id is provided, uses transferred session data from prior
        browser fetch including cookies, ETag, and proper header context.
        
        Args:
            url: URL to fetch.
            referer: Referer header.
            headers: Additional headers.
            use_tor: Whether to use Tor.
            cached_etag: ETag from cache for conditional request.
            cached_last_modified: Last-Modified from cache for conditional request.
            session_id: Session ID from browser fetch for session transfer (§3.1.2).
            
        Returns:
            FetchResult instance.
        """
        await self._rate_limiter.acquire(url)
        
        # Track if we're using session transfer
        using_session = False
        
        try:
            from curl_cffi import requests as curl_requests
            
            # Prepare base headers
            req_headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
            }
            
            # Try to use session transfer if session_id provided (§3.1.2)
            if session_id:
                transfer_result = get_transfer_headers(
                    url,
                    session_id=session_id,
                    include_conditional=True,
                )
                if transfer_result.ok:
                    # Use session headers (includes cookies, sec-fetch-*, etc.)
                    req_headers.update(transfer_result.headers)
                    using_session = True
                    logger.debug(
                        "Using transferred session headers",
                        session_id=session_id,
                        url=url[:80],
                    )
                else:
                    logger.debug(
                        "Session transfer failed, using default headers",
                        session_id=session_id,
                        reason=transfer_result.reason,
                    )
            
            # If not using session, generate standard headers
            if not using_session:
                # Generate Sec-Fetch-* headers per §4.3
                nav_context = NavigationContext(
                    target_url=url,
                    referer_url=referer,
                    is_user_initiated=True,
                    destination=SecFetchDest.DOCUMENT,
                )
                sec_fetch_headers = generate_sec_fetch_headers(nav_context)
                req_headers.update(sec_fetch_headers.to_dict())
                
                # Generate Sec-CH-UA-* (Client Hints) headers per §4.3
                # These headers provide browser brand information to match Chrome impersonation
                sec_ch_ua_headers = generate_sec_ch_ua_headers()
                req_headers.update(sec_ch_ua_headers.to_dict())
                
                if referer:
                    req_headers["Referer"] = referer
                
                # Add conditional request headers for 304 support
                if cached_etag:
                    req_headers["If-None-Match"] = cached_etag
                if cached_last_modified:
                    req_headers["If-Modified-Since"] = cached_last_modified
            
            if headers:
                req_headers.update(headers)
            
            # Configure proxy if using Tor
            proxies = None
            if use_tor:
                tor_settings = self._settings.tor
                proxy_url = f"socks5://{tor_settings.socks_host}:{tor_settings.socks_port}"
                proxies = {"http": proxy_url, "https": proxy_url}
            
            # Execute request with Chrome impersonation
            response = curl_requests.get(
                url,
                headers=req_headers,
                proxies=proxies,
                impersonate="chrome",
                timeout=self._settings.crawler.request_timeout,
                allow_redirects=True,
            )
            
            # Extract response headers
            resp_headers = dict(response.headers)
            
            # Extract ETag and Last-Modified from response
            resp_etag = resp_headers.get("etag") or resp_headers.get("ETag")
            resp_last_modified = resp_headers.get("last-modified") or resp_headers.get("Last-Modified")
            
            # Handle 304 Not Modified response
            if response.status_code == 304:
                logger.info(
                    "HTTP 304 Not Modified - using cached content",
                    url=url[:80],
                )
                return FetchResult(
                    ok=True,
                    url=url,
                    status=304,
                    headers=resp_headers,
                    method="http_client",
                    from_cache=True,
                    etag=resp_etag or cached_etag,
                    last_modified=resp_last_modified or cached_last_modified,
                )
            
            # Check for Cloudflare/JS challenge
            if _is_challenge_page(response.text, response.headers):
                logger.info("Challenge detected", url=url)
                return FetchResult(
                    ok=False,
                    url=url,
                    status=response.status_code,
                    reason="challenge_detected",
                    method="http_client",
                )
            
            # Save content
            content_hash = hashlib.sha256(response.content).hexdigest()
            html_path = await _save_content(url, response.content, response.headers)
            
            # Save WARC archive
            warc_path = await _save_warc(
                url,
                response.content,
                response.status_code,
                resp_headers,
                request_headers=req_headers,
            )
            
            logger.info(
                "HTTP fetch success",
                url=url[:80],
                status=response.status_code,
                content_length=len(response.content),
                has_etag=bool(resp_etag),
                has_last_modified=bool(resp_last_modified),
                using_session=using_session,
            )
            
            # Update session with response data if using session transfer (§3.1.2)
            if using_session and session_id:
                try:
                    update_session(session_id, url, resp_headers)
                except Exception as session_err:
                    logger.debug(
                        "Session update failed (non-fatal)",
                        session_id=session_id,
                        error=str(session_err),
                    )
            
            return FetchResult(
                ok=True,
                url=url,
                status=response.status_code,
                headers=resp_headers,
                html_path=str(html_path) if html_path else None,
                warc_path=str(warc_path) if warc_path else None,
                content_hash=content_hash,
                method="http_client",
                from_cache=False,
                etag=resp_etag,
                last_modified=resp_last_modified,
            )
            
        except Exception as e:
            logger.error("HTTP fetch error", url=url, error=str(e))
            return FetchResult(
                ok=False,
                url=url,
                reason=str(e),
                method="http_client",
            )


class BrowserFetcher:
    """Browser-based fetcher using Playwright with headless/headful auto-switching.
    
    Features:
    - Automatic headless/headful mode switching based on domain policy
    - Human-like behavior simulation (scrolling, mouse movement)
    - CDP connection to Windows Chrome for fingerprint consistency
    - Resource blocking (ads, trackers, large media)
    - Stealth measures (navigator.webdriver override, viewport jitter) per §4.3
    - Browser archive (CDXJ, HAR) generation per §4.3.2
    """
    
    def __init__(self):
        self._rate_limiter = RateLimiter()
        self._settings = get_settings()
        self._headless_browser = None
        self._headless_context = None
        self._headful_browser = None
        self._headful_context = None
        self._playwright = None
        self._human_behavior = HumanBehavior()
        
        # Initialize viewport jitter with settings from config
        browser_settings = self._settings.browser
        self._viewport_jitter = get_viewport_jitter(ViewportJitterConfig(
            base_width=browser_settings.viewport_width,
            base_height=browser_settings.viewport_height,
            max_width_jitter=20,  # Narrow jitter per §4.3
            max_height_jitter=15,
            hysteresis_seconds=300.0,  # 5 min minimum between changes
            enabled=True,
        ))
        
        # Track CDP connection status for stealth adjustments
        self._headful_is_cdp = False
        
        # Browser archiver for CDXJ/HAR generation (§4.3.2)
        self._archiver = get_browser_archiver()
        
        # Profile health audit (§4.3.1)
        self._profile_auditor = get_profile_auditor()
        self._restart_requested = False
        self._health_check_performed = False
    
    async def _ensure_browser(self, headful: bool = False) -> tuple:
        """Ensure browser connection is established.
        
        Applies stealth measures per §4.3:
        - navigator.webdriver override via init script
        - Viewport jitter with hysteresis
        - Stealth launch arguments
        
        Args:
            headful: Whether to ensure headful browser.
            
        Returns:
            Tuple of (browser, context).
        """
        from playwright.async_api import async_playwright
        
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        
        browser_settings = self._settings.browser
        
        # Get viewport with jitter applied per §4.3
        viewport = self._viewport_jitter.get_viewport()
        
        if headful:
            # Headful mode - for challenge bypass
            if self._headful_browser is None:
                try:
                    # Try CDP connection first (Windows Chrome)
                    cdp_url = f"http://{browser_settings.chrome_host}:{browser_settings.chrome_port}"
                    self._headful_browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
                    self._headful_is_cdp = True
                    logger.info("Connected to Chrome via CDP (headful)", url=cdp_url)
                except Exception as e:
                    logger.warning("CDP connection failed, launching local headful browser", error=str(e))
                    # Use stealth args for local launch
                    self._headful_browser = await self._playwright.chromium.launch(
                        headless=False,
                        args=get_stealth_args(),
                    )
                    self._headful_is_cdp = False
                
                self._headful_context = await self._headful_browser.new_context(
                    viewport=viewport,
                    locale="ja-JP",
                    timezone_id="Asia/Tokyo",
                )
                
                # Apply stealth scripts to context (all new pages get them)
                await apply_stealth_to_context(
                    self._headful_context,
                    is_cdp=self._headful_is_cdp,
                )
                
                await self._setup_blocking(self._headful_context)
                
                logger.info(
                    "Headful context initialized with stealth",
                    viewport=viewport,
                    is_cdp=self._headful_is_cdp,
                )
                
                # Perform profile health check on new context (§4.3.1)
                await self._perform_health_check(self._headful_context)
            
            return self._headful_browser, self._headful_context
        else:
            # Headless mode - default
            if self._headless_browser is None:
                # Use stealth args for launch
                self._headless_browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=get_stealth_args(),
                )
                logger.info("Launched headless browser with stealth args")
                
                self._headless_context = await self._headless_browser.new_context(
                    viewport=viewport,
                    locale="ja-JP",
                    timezone_id="Asia/Tokyo",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                )
                
                # Apply stealth scripts to context
                await apply_stealth_to_context(
                    self._headless_context,
                    is_cdp=False,
                )
                
                await self._setup_blocking(self._headless_context)
                
                logger.info(
                    "Headless context initialized with stealth",
                    viewport=viewport,
                )
                
                # Perform profile health check on new context (§4.3.1)
                await self._perform_health_check(self._headless_context)
            
            return self._headless_browser, self._headless_context
    
    async def _perform_health_check(self, context) -> None:
        """Perform profile health check on browser context (§4.3.1).
        
        Checks fingerprint consistency against baseline and triggers
        repair actions if drift is detected.
        
        Args:
            context: Playwright browser context.
        """
        if self._health_check_performed:
            # Only perform once per session to avoid overhead
            return
        
        try:
            # Create a temporary page for health check
            page = await context.new_page()
            
            try:
                # Navigate to about:blank to establish fingerprint
                await page.goto("about:blank", wait_until="domcontentloaded")
                
                # Perform health check
                audit_result = await perform_health_check(
                    page=page,
                    force=True,  # Force check on initialization
                    auto_repair=True,
                    browser_manager=self,
                )
                
                self._health_check_performed = True
                
                if audit_result.status == AuditStatus.PASS:
                    logger.info("Profile health check passed")
                elif audit_result.status == AuditStatus.DRIFT:
                    logger.warning(
                        "Profile drift detected during health check",
                        drifts=[d.attribute for d in audit_result.drifts],
                        repair_status=audit_result.repair_status.value,
                    )
                    
                    # If repair recommended browser restart, flag it
                    if RepairAction.RESTART_BROWSER in audit_result.repair_actions:
                        self._restart_requested = True
                        
            finally:
                await page.close()
                
        except Exception as e:
            logger.warning(
                "Profile health check failed (non-fatal)",
                error=str(e),
            )
            # Don't block browser initialization on health check failure
            self._health_check_performed = True
    
    async def request_restart(self) -> None:
        """Request browser restart due to profile drift.
        
        Called by ProfileAuditor when repair requires browser restart.
        """
        self._restart_requested = True
        logger.info("Browser restart requested due to profile drift")
    
    def is_restart_requested(self) -> bool:
        """Check if browser restart has been requested.
        
        Returns:
            True if restart is needed.
        """
        return self._restart_requested
    
    def clear_restart_request(self) -> None:
        """Clear the restart request flag after handling."""
        self._restart_requested = False
        self._health_check_performed = False

    async def _setup_blocking(self, context) -> None:
        """Setup resource blocking rules.
        
        Args:
            context: Playwright browser context.
        """
        browser_settings = self._settings.browser
        
        block_patterns = []
        
        if browser_settings.block_ads:
            block_patterns.extend([
                "*googlesyndication.com*",
                "*doubleclick.net*",
                "*googleadservices.com*",
                "*adnxs.com*",
                "*criteo.com*",
            ])
        
        if browser_settings.block_trackers:
            block_patterns.extend([
                "*google-analytics.com*",
                "*googletagmanager.com*",
                "*facebook.com/tr*",
                "*hotjar.com*",
                "*mixpanel.com*",
            ])
        
        if browser_settings.block_large_media:
            block_patterns.extend([
                "*.mp4",
                "*.webm",
                "*.avi",
                "*.mov",
            ])
        
        async def block_route(route):
            await route.abort()
        
        for pattern in block_patterns:
            await context.route(pattern, block_route)
    
    async def _should_use_headful(self, domain: str) -> bool:
        """Determine if headful mode should be used for domain.
        
        Based on domain policy's headful_ratio and past failure history.
        
        Args:
            domain: Domain name.
            
        Returns:
            True if headful mode should be used.
        """
        db = await get_database()
        
        # Check domain policy
        domain_info = await db.fetch_one(
            "SELECT headful_ratio, captcha_rate, block_score FROM domains WHERE domain = ?",
            (domain,),
        )
        
        if domain_info is None:
            # Default to settings-based ratio
            return random.random() < self._settings.browser.headful_ratio_initial
        
        headful_ratio = domain_info.get("headful_ratio", 0.1)
        captcha_rate = domain_info.get("captcha_rate", 0.0)
        
        # Increase headful probability if domain has high captcha rate
        if captcha_rate > 0.3:
            headful_ratio = min(1.0, headful_ratio * 2)
        
        return random.random() < headful_ratio
    
    async def fetch(
        self,
        url: str,
        *,
        referer: str | None = None,
        headful: bool | None = None,
        take_screenshot: bool = True,
        simulate_human: bool = True,
        task_id: str | None = None,
        allow_intervention: bool = True,
        save_archive: bool = True,
    ) -> FetchResult:
        """Fetch URL using browser with automatic mode selection.
        
        Args:
            url: URL to fetch.
            referer: Referer header.
            headful: Force headful mode (None for auto-detect).
            take_screenshot: Whether to capture screenshot.
            simulate_human: Whether to simulate human behavior.
            task_id: Associated task ID for intervention tracking.
            allow_intervention: Whether to allow manual intervention on challenge.
            save_archive: Whether to save browser archive (CDXJ/HAR) per §4.3.2.
            
        Returns:
            FetchResult instance.
        """
        await self._rate_limiter.acquire(url)
        
        domain = urlparse(url).netloc.lower()
        
        # Determine headful mode
        if headful is None:
            headful = await self._should_use_headful(domain)
        
        browser, context = await self._ensure_browser(headful=headful)
        
        page = None
        network_collector: NetworkEventCollector | None = None
        try:
            page = await context.new_page()
            
            # Attach network event collector for archive generation (§4.3.2)
            if save_archive:
                network_collector = await self._archiver.attach_to_page(page, url)
            
            # Set referer if provided
            if referer:
                await page.set_extra_http_headers({"Referer": referer})
            
            # Human-like pre-navigation delay
            if simulate_human:
                await asyncio.sleep(HumanBehavior.random_delay(0.5, 1.5))
            
            # Navigate
            response = await page.goto(
                url,
                timeout=self._settings.crawler.page_load_timeout * 1000,
                wait_until="domcontentloaded",
            )
            
            if response is None:
                return FetchResult(
                    ok=False,
                    url=url,
                    reason="no_response",
                    method="browser_headful" if headful else "browser_headless",
                )
            
            # Wait for dynamic content with human-like variation
            wait_time = HumanBehavior.random_delay(1.0, 2.5) if simulate_human else 1.0
            await page.wait_for_timeout(int(wait_time * 1000))
            
            # Get content
            content = await page.content()
            content_bytes = content.encode("utf-8")
            content_hash = hashlib.sha256(content_bytes).hexdigest()
            
            # Check for challenge
            if _is_challenge_page(content, {}):
                logger.info(
                    "Browser challenge detected",
                    url=url,
                    headful=headful,
                )
                
                # If in headless mode, suggest headful escalation
                if not headful:
                    return FetchResult(
                        ok=False,
                        url=url,
                        status=response.status,
                        reason="challenge_detected_escalate_headful",
                        method="browser_headless",
                    )
                else:
                    # Headful mode - try manual intervention if allowed
                    if allow_intervention:
                        intervention_result = await self._request_manual_intervention(
                            url=url,
                            domain=domain,
                            page=page,
                            task_id=task_id,
                            challenge_type=_detect_challenge_type(content),
                        )
                        
                        if intervention_result and intervention_result.status == InterventionStatus.SUCCESS:
                            # Re-check page content after intervention
                            content = await page.content()
                            if not _is_challenge_page(content, {}):
                                # Intervention succeeded - continue with normal flow
                                logger.info(
                                    "Challenge bypassed via manual intervention",
                                    url=url[:80],
                                )
                                # Fall through to save content below
                            else:
                                # Still challenged - return failure
                                return FetchResult(
                                    ok=False,
                                    url=url,
                                    status=response.status,
                                    reason="challenge_detected_after_intervention",
                                    method="browser_headful",
                                )
                        elif intervention_result:
                            # Intervention failed/timed out/skipped
                            return FetchResult(
                                ok=False,
                                url=url,
                                status=response.status,
                                reason=f"intervention_{intervention_result.status.value}",
                                method="browser_headful",
                            )
                    else:
                        # Intervention not allowed - return challenge error
                        return FetchResult(
                            ok=False,
                            url=url,
                            status=response.status,
                            reason="challenge_detected",
                            method="browser_headful",
                        )
                    
                    # Re-get content after successful intervention
                    content = await page.content()
                    content_bytes = content.encode("utf-8")
                    content_hash = hashlib.sha256(content_bytes).hexdigest()
            
            # Simulate human reading behavior
            if simulate_human:
                await self._human_behavior.simulate_reading(page, len(content_bytes))
            
            # Save content
            html_path = await _save_content(url, content_bytes, {})
            
            # Save WARC archive
            resp_headers = dict(response.headers)
            warc_path = await _save_warc(
                url,
                content_bytes,
                response.status,
                resp_headers,
            )
            
            # Take screenshot
            screenshot_path = None
            if take_screenshot:
                screenshot_path = await _save_screenshot(page, url)
            
            # Save browser archive (CDXJ/HAR) per §4.3.2
            cdxj_path = None
            har_path = None
            if save_archive:
                try:
                    # Get page title for HAR
                    page_title = ""
                    try:
                        page_title = await page.title()
                    except Exception:
                        pass
                    
                    archive_result = await self._archiver.save_archive(
                        url=url,
                        content=content_bytes,
                        title=page_title,
                        collector=network_collector,
                        warc_path=str(warc_path) if warc_path else None,
                    )
                    cdxj_path = archive_result.get("cdxj_path")
                    har_path = archive_result.get("har_path")
                    
                    if archive_result.get("status") == "success":
                        logger.debug(
                            "Browser archive saved",
                            url=url[:80],
                            cdxj_path=cdxj_path,
                            har_path=har_path,
                        )
                except Exception as archive_err:
                    logger.warning(
                        "Browser archive save failed (non-fatal)",
                        url=url[:80],
                        error=str(archive_err),
                    )
            
            # Extract ETag and Last-Modified from response headers
            resp_etag = resp_headers.get("etag") or resp_headers.get("ETag")
            resp_last_modified = resp_headers.get("last-modified") or resp_headers.get("Last-Modified")
            
            logger.info(
                "Browser fetch success",
                url=url[:80],
                status=response.status,
                content_length=len(content_bytes),
                headful=headful,
                has_etag=bool(resp_etag),
                has_last_modified=bool(resp_last_modified),
                has_archive=bool(cdxj_path or har_path),
            )
            
            # Capture session for future HTTP client transfers (§3.1.2)
            session_id = None
            try:
                session_manager = get_session_transfer_manager()
                session_id = await session_manager.capture_from_browser(
                    context,
                    url,
                    resp_headers,
                )
                if session_id:
                    logger.debug(
                        "Session captured for HTTP client transfer",
                        session_id=session_id,
                        url=url[:80],
                    )
            except Exception as session_err:
                logger.debug(
                    "Session capture failed (non-fatal)",
                    error=str(session_err),
                )
            
            return FetchResult(
                ok=True,
                url=url,
                status=response.status,
                headers=resp_headers,
                html_path=str(html_path) if html_path else None,
                warc_path=str(warc_path) if warc_path else None,
                screenshot_path=str(screenshot_path) if screenshot_path else None,
                cdxj_path=cdxj_path,
                har_path=har_path,
                content_hash=content_hash,
                method="browser_headful" if headful else "browser_headless",
                from_cache=False,
                etag=resp_etag,
                last_modified=resp_last_modified,
            )
            
        except Exception as e:
            logger.error("Browser fetch error", url=url, headful=headful, error=str(e))
            return FetchResult(
                ok=False,
                url=url,
                reason=str(e),
                method="browser_headful" if headful else "browser_headless",
            )
        finally:
            if page:
                await page.close()
    
    async def _request_manual_intervention(
        self,
        url: str,
        domain: str,
        page,
        task_id: str | None,
        challenge_type: str,
    ):
        """Request manual intervention for challenge bypass.
        
        Args:
            url: Target URL.
            domain: Domain name.
            page: Playwright page object.
            task_id: Associated task ID.
            challenge_type: Type of challenge detected.
            
        Returns:
            InterventionResult or None.
        """
        try:
            intervention_manager = get_intervention_manager()
            
            # Map challenge type to InterventionType
            intervention_type_map = {
                "cloudflare": InterventionType.CLOUDFLARE,
                "captcha": InterventionType.CAPTCHA,
                "recaptcha": InterventionType.CAPTCHA,
                "hcaptcha": InterventionType.CAPTCHA,
                "turnstile": InterventionType.TURNSTILE,
                "js_challenge": InterventionType.JS_CHALLENGE,
            }
            intervention_type = intervention_type_map.get(
                challenge_type,
                InterventionType.CLOUDFLARE,
            )
            
            # Determine element selector for highlighting
            element_selector = _get_challenge_element_selector(challenge_type)
            
            # Define success callback to check if challenge is bypassed
            async def check_challenge_bypassed() -> bool:
                try:
                    content = await page.content()
                    return not _is_challenge_page(content, {})
                except Exception:
                    return False
            
            # Request intervention
            result = await intervention_manager.request_intervention(
                intervention_type=intervention_type,
                url=url,
                domain=domain,
                task_id=task_id,
                page=page,
                element_selector=element_selector,
                on_success_callback=check_challenge_bypassed,
            )
            
            return result
            
        except Exception as e:
            logger.error(
                "Manual intervention request failed",
                url=url,
                error=str(e),
            )
            return None
    
    async def close(self) -> None:
        """Close all browser connections."""
        if self._headless_context:
            await self._headless_context.close()
        if self._headless_browser:
            await self._headless_browser.close()
        if self._headful_context:
            await self._headful_context.close()
        if self._headful_browser:
            await self._headful_browser.close()
        if self._playwright:
            await self._playwright.stop()


def _is_challenge_page(content: str, headers: dict) -> bool:
    """Check if page is a challenge/captcha page.
    
    Args:
        content: Page content.
        headers: Response headers.
        
    Returns:
        True if challenge detected.
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
        return True
    
    # CAPTCHA indicators
    captcha_indicators = [
        "recaptcha",
        "hcaptcha",
        "captcha-container",
        "g-recaptcha",
        "h-captcha",
    ]
    
    if any(ind in content_lower for ind in captcha_indicators):
        return True
    
    # Turnstile indicators
    turnstile_indicators = [
        "cf-turnstile",
        "turnstile-widget",
        "challenges.cloudflare.com/turnstile",
    ]
    
    if any(ind in content_lower for ind in turnstile_indicators):
        return True
    
    # Server header check
    server = headers.get("server", "").lower()
    if "cloudflare" in server:
        # Check for challenge response
        cf_ray = headers.get("cf-ray")
        if cf_ray and len(content) < 10000:  # Challenge pages are usually small
            return True
    
    return False


def _detect_challenge_type(content: str) -> str:
    """Detect the specific type of challenge from page content.
    
    Args:
        content: Page HTML content.
        
    Returns:
        Challenge type string.
    """
    content_lower = content.lower()
    
    # Check for specific challenge types in order of specificity
    if "turnstile" in content_lower or "cf-turnstile" in content_lower:
        return "turnstile"
    
    if "hcaptcha" in content_lower or "h-captcha" in content_lower:
        return "hcaptcha"
    
    if "recaptcha" in content_lower or "g-recaptcha" in content_lower:
        return "recaptcha"
    
    if "captcha" in content_lower:
        return "captcha"
    
    # Cloudflare indicators
    cloudflare_indicators = [
        "cf-browser-verification",
        "cloudflare ray id",
        "checking your browser",
        "_cf_chl_opt",
    ]
    if any(ind in content_lower for ind in cloudflare_indicators):
        return "cloudflare"
    
    # Generic JS challenge
    if "please wait" in content_lower or "just a moment" in content_lower:
        return "js_challenge"
    
    return "cloudflare"  # Default


def _get_challenge_element_selector(challenge_type: str) -> str | None:
    """Get CSS selector for challenge element to highlight.
    
    Args:
        challenge_type: Type of challenge.
        
    Returns:
        CSS selector or None.
    """
    selectors = {
        "turnstile": "[data-turnstile-container], .cf-turnstile, iframe[src*='turnstile']",
        "hcaptcha": ".h-captcha, [data-hcaptcha-widget-id], iframe[src*='hcaptcha']",
        "recaptcha": ".g-recaptcha, [data-sitekey], iframe[src*='recaptcha']",
        "captcha": "[class*='captcha'], [id*='captcha'], iframe[src*='captcha']",
        "cloudflare": "#cf-wrapper, .cf-browser-verification, #challenge-running",
        "js_challenge": "#challenge-body-text, #challenge-running, .main-wrapper",
    }
    
    return selectors.get(challenge_type)


async def _save_content(url: str, content: bytes, headers: dict) -> Path | None:
    """Save fetched content to file.
    
    Args:
        url: Source URL.
        content: Content bytes.
        headers: Response headers.
        
    Returns:
        Path to saved file.
    """
    settings = get_settings()
    cache_dir = Path(settings.storage.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate filename from URL hash
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Determine extension
    content_type = headers.get("content-type", "").lower()
    if "pdf" in content_type:
        ext = ".pdf"
    else:
        ext = ".html"
    
    filename = f"{timestamp}_{url_hash}{ext}"
    filepath = cache_dir / filename
    
    filepath.write_bytes(content)
    
    return filepath


async def _save_warc(
    url: str,
    content: bytes,
    status_code: int,
    response_headers: dict[str, str],
    *,
    request_headers: dict[str, str] | None = None,
    method: str = "GET",
) -> Path | None:
    """Save HTTP response as WARC file.
    
    Creates a WARC file containing the request and response records.
    
    Args:
        url: Request URL.
        content: Response body bytes.
        status_code: HTTP status code.
        response_headers: Response headers.
        request_headers: Request headers (optional).
        method: HTTP method (default: GET).
        
    Returns:
        Path to saved WARC file.
    """
    settings = get_settings()
    warc_dir = Path(settings.storage.warc_dir)
    warc_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate filename from URL hash and timestamp
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{url_hash}.warc.gz"
    filepath = warc_dir / filename
    
    try:
        with open(filepath, "wb") as output:
            writer = WARCWriter(output, gzip=True)
            
            # Create WARC-Date in ISO format
            warc_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            
            # Write request record (if headers provided)
            if request_headers:
                req_headers_list = list(request_headers.items())
                req_http_headers = StatusAndHeaders(
                    f"{method} {urlparse(url).path or '/'} HTTP/1.1",
                    req_headers_list,
                    is_http_request=True,
                )
                request_record = writer.create_warc_record(
                    url,
                    "request",
                    http_headers=req_http_headers,
                    warc_headers_dict={"WARC-Date": warc_date},
                )
                writer.write_record(request_record)
            
            # Build response status line
            status_text = _get_http_status_text(status_code)
            status_line = f"HTTP/1.1 {status_code} {status_text}"
            
            # Build response headers list
            resp_headers_list = list(response_headers.items())
            resp_http_headers = StatusAndHeaders(status_line, resp_headers_list)
            
            # Write response record
            response_record = writer.create_warc_record(
                url,
                "response",
                payload=io.BytesIO(content),
                http_headers=resp_http_headers,
                warc_headers_dict={"WARC-Date": warc_date},
            )
            writer.write_record(response_record)
        
        logger.debug("WARC saved", url=url[:60], path=str(filepath))
        return filepath
        
    except Exception as e:
        logger.error("WARC save failed", url=url[:60], error=str(e))
        return None


def _get_http_status_text(status_code: int) -> str:
    """Get HTTP status text for status code.
    
    Args:
        status_code: HTTP status code.
        
    Returns:
        Status text (e.g., "OK", "Not Found").
    """
    status_texts = {
        200: "OK",
        201: "Created",
        204: "No Content",
        301: "Moved Permanently",
        302: "Found",
        303: "See Other",
        304: "Not Modified",
        307: "Temporary Redirect",
        308: "Permanent Redirect",
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        408: "Request Timeout",
        429: "Too Many Requests",
        500: "Internal Server Error",
        502: "Bad Gateway",
        503: "Service Unavailable",
        504: "Gateway Timeout",
    }
    return status_texts.get(status_code, "Unknown")


async def _save_screenshot(page, url: str) -> Path | None:
    """Save page screenshot.
    
    Args:
        page: Playwright page.
        url: Source URL.
        
    Returns:
        Path to screenshot file.
    """
    settings = get_settings()
    screenshots_dir = Path(settings.storage.screenshots_dir)
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    filename = f"{timestamp}_{url_hash}.png"
    filepath = screenshots_dir / filename
    
    await page.screenshot(path=str(filepath), full_page=False)
    
    return filepath


# Global fetcher instances
_http_fetcher: HTTPFetcher | None = None
_browser_fetcher: BrowserFetcher | None = None


async def fetch_url(
    url: str,
    context: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Fetch URL with automatic method selection, escalation, and cache support.
    
    Implements multi-stage fetch strategy:
    1. HTTP client (fastest, with 304 cache support)
    2. Browser headless (for JS-rendered pages)
    3. Browser headful (for challenge bypass)
    4. Tor circuit renewal on 403/429
    
    Supports conditional requests (If-None-Match/If-Modified-Since) for
    efficient re-validation and 304 Not Modified responses.
    
    Args:
        url: URL to fetch.
        context: Context information (referer, etc.).
        policy: Fetch policy override. Supported keys:
            - force_browser: Force browser fetching.
            - force_headful: Force headful mode.
            - use_tor: Use Tor proxy.
            - skip_cache: Skip cache lookup and conditional requests.
            - max_retries: Override max retries (default: 3).
            - allow_intervention: Allow manual intervention on challenge (default: True).
            - session_id: Session ID for session transfer from prior browser fetch (§3.1.2).
        task_id: Associated task ID.
        
    Returns:
        Fetch result dictionary with additional 'from_cache' field.
    """
    global _http_fetcher, _browser_fetcher
    
    context = context or {}
    policy = policy or {}
    
    db = await get_database()
    settings = get_settings()
    
    with CausalTrace() as trace:
        # Check domain cooldown
        domain = urlparse(url).netloc.lower()
        if await db.is_domain_cooled_down(domain):
            logger.info("Domain in cooldown", domain=domain, url=url[:80])
            return FetchResult(
                ok=False,
                url=url,
                reason="domain_cooldown",
            ).to_dict()
        
        # Determine fetch method
        force_browser = policy.get("force_browser", False)
        force_headful = policy.get("force_headful", False)
        use_tor = policy.get("use_tor", False)
        skip_cache = policy.get("skip_cache", False)
        max_retries = policy.get("max_retries", settings.crawler.max_retries)
        session_id = policy.get("session_id")  # Session transfer (§3.1.2)
        
        # Initialize fetchers
        if _http_fetcher is None:
            _http_fetcher = HTTPFetcher()
        if _browser_fetcher is None:
            _browser_fetcher = BrowserFetcher()
        
        # Check cache for conditional request data
        cached_etag = None
        cached_last_modified = None
        cached_content_path = None
        cached_content_hash = None
        
        if not skip_cache and not force_browser:
            cache_entry = await db.get_fetch_cache(url)
            if cache_entry:
                cached_etag = cache_entry.get("etag")
                cached_last_modified = cache_entry.get("last_modified")
                cached_content_path = cache_entry.get("content_path")
                cached_content_hash = cache_entry.get("content_hash")
                
                logger.debug(
                    "Found cache entry for conditional request",
                    url=url[:80],
                    has_etag=bool(cached_etag),
                    has_last_modified=bool(cached_last_modified),
                )
        
        result = None
        retry_count = 0
        escalation_path = []  # Track escalation for logging
        
        # =====================================================================
        # Stage 1: HTTP Client (with optional Tor)
        # =====================================================================
        if not force_browser:
            result = await _http_fetcher.fetch(
                url,
                referer=context.get("referer"),
                use_tor=use_tor,
                cached_etag=cached_etag,
                cached_last_modified=cached_last_modified,
                session_id=session_id,  # Session transfer (§3.1.2)
            )
            escalation_path.append(f"http_client(tor={use_tor}, session={bool(session_id)})")
            
            # Handle 304 Not Modified - use cached content
            if result.ok and result.status == 304 and cached_content_path:
                logger.info(
                    "Using cached content (304 Not Modified)",
                    url=url[:80],
                    cached_path=cached_content_path,
                )
                result.html_path = cached_content_path
                result.content_hash = cached_content_hash
                
                # Update cache validation time
                await db.update_fetch_cache_validation(
                    url,
                    etag=result.etag,
                    last_modified=result.last_modified,
                )
            
            # Handle 403/429 - try Tor circuit renewal
            if not result.ok and result.status in (403, 429) and not use_tor:
                logger.info("HTTP error, trying with Tor", url=url[:80], status=result.status)
                
                tor_controller = await get_tor_controller()
                if await tor_controller.renew_circuit(domain):
                    result = await _http_fetcher.fetch(
                        url,
                        referer=context.get("referer"),
                        use_tor=True,
                        cached_etag=cached_etag,
                        cached_last_modified=cached_last_modified,
                        session_id=session_id,  # Session transfer (§3.1.2)
                    )
                    escalation_path.append("http_client(tor=True)")
                    retry_count += 1
            
            # If challenge detected or still failing, escalate to browser
            if not result.ok and result.reason == "challenge_detected":
                logger.info("Challenge detected, escalating to browser", url=url[:80])
                force_browser = True
        
        # =====================================================================
        # Stage 2: Browser Headless (auto mode selection)
        # =====================================================================
        if force_browser and not force_headful:
            allow_intervention = policy.get("allow_intervention", True)
            result = await _browser_fetcher.fetch(
                url,
                referer=context.get("referer"),
                headful=None,  # Auto-detect based on domain policy
                task_id=task_id,
                allow_intervention=allow_intervention,
            )
            escalation_path.append(f"browser({result.method})")
            retry_count += 1
            
            # If headless failed with escalation hint, try headful
            if not result.ok and result.reason == "challenge_detected_escalate_headful":
                logger.info("Headless challenge, escalating to headful", url=url[:80])
                force_headful = True
        
        # =====================================================================
        # Stage 3: Browser Headful (for persistent challenges)
        # =====================================================================
        if force_headful and (not result or not result.ok):
            allow_intervention = policy.get("allow_intervention", True)
            result = await _browser_fetcher.fetch(
                url,
                referer=context.get("referer"),
                headful=True,
                task_id=task_id,
                allow_intervention=allow_intervention,
            )
            escalation_path.append("browser_headful")
            retry_count += 1
            
            # If headful still fails, update domain policy for future
            if not result.ok and "challenge" in (result.reason or ""):
                await _update_domain_headful_ratio(db, domain, increase=True)
        
        # =====================================================================
        # Update Metrics and Store Results
        # =====================================================================
        
        # Update domain metrics
        await db.update_domain_metrics(
            domain,
            success=result.ok,
            is_captcha=result.reason and "challenge" in result.reason,
            is_http_error=result.status and result.status >= 400,
        )
        
        # Store page record and update cache if successful
        if result.ok:
            # Update pages table
            await db.insert("pages", {
                "url": url,
                "final_url": url,  # TODO: Track redirects
                "domain": domain,
                "fetch_method": result.method,
                "http_status": result.status,
                "content_hash": result.content_hash,
                "html_path": result.html_path,
                "warc_path": result.warc_path,
                "screenshot_path": result.screenshot_path,
                "etag": result.etag,
                "last_modified": result.last_modified,
                "headers_json": json.dumps(result.headers) if result.headers else None,
                "cause_id": trace.id,
            }, or_replace=True)
            
            # Update fetch cache for future conditional requests
            # Only cache if we have ETag or Last-Modified
            if (result.etag or result.last_modified) and not result.from_cache:
                await db.set_fetch_cache(
                    url,
                    etag=result.etag,
                    last_modified=result.last_modified,
                    content_hash=result.content_hash,
                    content_path=result.html_path,
                )
                logger.debug(
                    "Updated fetch cache",
                    url=url[:80],
                    etag=result.etag[:20] if result.etag else None,
                    last_modified=result.last_modified,
                )
        
        # Log event
        await db.log_event(
            event_type="fetch",
            message=f"Fetched {url[:60]}",
            task_id=task_id,
            cause_id=trace.id,
            component="crawler",
            details={
                "url": url,
                "ok": result.ok,
                "method": result.method,
                "status": result.status,
                "reason": result.reason,
                "from_cache": result.from_cache,
                "has_etag": bool(result.etag),
                "has_last_modified": bool(result.last_modified),
                "escalation_path": " -> ".join(escalation_path),
                "retry_count": retry_count,
            },
        )
        
        return result.to_dict()


async def _update_domain_headful_ratio(db, domain: str, increase: bool = True) -> None:
    """Update domain's headful ratio based on fetch outcomes.
    
    Args:
        db: Database instance.
        domain: Domain name.
        increase: Whether to increase (True) or decrease (False) the ratio.
    """
    current = await db.fetch_one(
        "SELECT headful_ratio FROM domains WHERE domain = ?",
        (domain,),
    )
    
    if current is None:
        # Create domain record with elevated headful ratio
        await db.insert("domains", {
            "domain": domain,
            "headful_ratio": 0.3 if increase else 0.1,
        }, auto_id=False)
    else:
        ratio = current.get("headful_ratio", 0.1)
        if increase:
            new_ratio = min(1.0, ratio * 1.5 + 0.1)  # Increase by 50% + 0.1
        else:
            new_ratio = max(0.05, ratio * 0.8)  # Decrease by 20%
        
        await db.update(
            "domains",
            {"headful_ratio": new_ratio},
            "domain = ?",
            (domain,),
        )
        
        logger.debug(
            "Updated domain headful ratio",
            domain=domain,
            old_ratio=ratio,
            new_ratio=new_ratio,
        )


# Need to import json for the db.insert call
import json

