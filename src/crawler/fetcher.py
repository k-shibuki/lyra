"""
URL fetcher for Lyra.
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
import hashlib
import io
import json
import random
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

from warcio.statusandheaders import StatusAndHeaders

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright, Route

    from src.storage.database import Database
from warcio.warcwriter import WARCWriter

from src.crawler.browser_provider import (
    BrowserMode,
    BrowserOptions,
    get_browser_registry,
)
from src.crawler.dns_policy import (
    get_dns_policy_manager,
)
from src.crawler.http3_policy import (
    HTTP3RequestResult,
    ProtocolVersion,
    detect_protocol_from_playwright_response,
    get_http3_policy_manager,
)
from src.crawler.ipv6_manager import (
    AddressFamily,
    IPv6ConnectionResult,
    get_ipv6_manager,
)
from src.crawler.sec_fetch import (
    NavigationContext,
    SecFetchDest,
    generate_sec_fetch_headers,
)
from src.crawler.undetected import (
    get_undetected_fetcher,
)
from src.crawler.wayback import (
    get_wayback_fallback,
)
from src.storage.database import get_database
from src.utils.config import get_settings
from src.utils.lifecycle import (
    ResourceType,
    get_lifecycle_manager,
)
from src.utils.logging import CausalTrace, get_logger
from src.utils.notification import (
    InterventionStatus,
    InterventionType,
    get_intervention_manager,
)

logger = get_logger(__name__)


# =============================================================================
# Human-like Behavior Simulation (delegated to human_behavior module)
# =============================================================================

# E402: Intentionally import after other imports to avoid circular dependencies
# (human_behavior imports from fetcher, so we import it here after all other imports)
from src.crawler.human_behavior import (
    get_human_behavior_simulator,
)


class HumanBehavior:
    """Wrapper for human-like browser interactions.

    Delegates to the new HumanBehaviorSimulator for enhanced functionality.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._simulator = get_human_behavior_simulator()

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
        simulator = get_human_behavior_simulator()
        return simulator.random_delay(min_seconds, max_seconds)

    @staticmethod
    def scroll_pattern(page_height: int, viewport_height: int) -> list[tuple[int, float]]:
        """Generate realistic scroll positions and delays.

        Args:
            page_height: Total page height in pixels.
            viewport_height: Viewport height in pixels.

        Returns:
            List of (scroll_position, delay) tuples.
        """
        simulator = get_human_behavior_simulator()
        steps = simulator._scroll.generate_scroll_sequence(
            current_position=0,
            page_height=page_height,
            viewport_height=viewport_height,
        )
        # Convert to legacy format: (position, delay_seconds)
        return [(step.position, step.delay_ms / 1000) for step in steps]

    @staticmethod
    def mouse_path(
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
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
        simulator = get_human_behavior_simulator()
        path = simulator._mouse.generate_path(
            start=(float(start_x), float(start_y)),
            end=(float(end_x), float(end_y)),
        )
        # Convert to legacy format: (x, y) only (no delays)
        return [(int(x), int(y)) for x, y, _ in path]

    async def simulate_reading(self, page: "Page", content_length: int) -> None:
        """Simulate human reading behavior on page.

        Args:
            page: Playwright page object.
            content_length: Approximate content length.
        """
        try:
            await self._simulator.read_page(page, max_scrolls=5)
        except Exception as e:
            logger.debug("Reading simulation error", error=str(e))

    async def move_mouse_to_element(self, page: "Page", selector: str) -> None:
        """Move mouse to element with human-like motion.

        Args:
            page: Playwright page object.
            selector: CSS selector for target element.
        """
        try:
            await self._simulator.move_to_element(page, selector)
        except Exception as e:
            logger.debug("Mouse movement error", error=str(e))


# =============================================================================
# Tor Circuit Controller
# =============================================================================


class TorController:
    """Controls Tor circuits via Stem library.

    Provides circuit renewal and exit node management.
    """

    def __init__(self) -> None:
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
            if self._controller is not None:
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
                if self._controller is not None:
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

        Uses socks5h:// to ensure DNS is resolved through Tor.

        Returns:
            Exit IP address or None.
        """
        try:
            from curl_cffi import requests as curl_requests

            # Use DNS policy manager to get proxy with socks5h:// for DNS leak prevention
            dns_manager = get_dns_policy_manager()
            proxies = dns_manager.get_proxy_dict(use_tor=True)

            response = curl_requests.get(
                "https://check.torproject.org/api/ip",
                proxies=cast(Any, proxies),
                timeout=10,
            )

            data = response.json()
            return cast(str | None, data.get("IP"))

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


async def _can_use_tor(domain: str | None = None) -> bool:
    """Check if Tor can be used based on daily limits.

    Per ADR-0006 and : Check both global daily limit (20%) and domain-specific limit.

    Args:
        domain: Optional domain for domain-specific check.

    Returns:
        True if Tor can be used, False if limit reached.
    """
    try:
        from src.utils.config import get_settings
        from src.utils.metrics import get_metrics_collector

        settings = get_settings()
        max_ratio = settings.tor.max_usage_ratio  # 0.20

        collector = get_metrics_collector()
        metrics = collector.get_today_tor_metrics()

        # Check global daily limit
        if metrics.usage_ratio >= max_ratio:
            logger.debug(
                "Tor daily limit reached",
                current_ratio=metrics.usage_ratio,
                max_ratio=max_ratio,
                total_requests=metrics.total_requests,
                tor_requests=metrics.tor_requests,
            )
            return False

        # Check domain-specific Tor policy
        if domain:
            from src.utils.domain_policy import get_domain_policy

            domain_policy = get_domain_policy(domain)  # Sync function

            # Check if Tor is blocked for this domain
            if not domain_policy.tor_allowed or domain_policy.tor_blocked:
                logger.debug(
                    "Tor blocked for domain",
                    domain=domain,
                    tor_allowed=domain_policy.tor_allowed,
                    tor_blocked=domain_policy.tor_blocked,
                )
                return False

            # Check domain-specific usage ratio (use global max as fallback)
            domain_metrics = collector.get_domain_tor_metrics(domain)
            # Use the global max_ratio as domain limit
            if domain_metrics.usage_ratio >= max_ratio:
                logger.debug(
                    "Tor domain usage limit reached",
                    domain=domain,
                    current_ratio=domain_metrics.usage_ratio,
                    max_ratio=max_ratio,
                )
                return False

        return True

    except Exception as e:
        # Fail-open: if we can't check limits, allow Tor usage
        logger.warning(
            "Failed to check Tor limits, allowing usage",
            error=str(e),
        )
        return True


class FetchResult:
    """Result of a fetch operation.

    Includes detailed authentication information, IPv6 connection information,
    and archive/Wayback fallback information.
    """

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
        content_hash: str | None = None,
        reason: str | None = None,
        method: str = "http_client",
        from_cache: bool = False,
        etag: str | None = None,
        last_modified: str | None = None,
        # Authentication queue (semi-automatic operation)
        auth_queued: bool = False,
        queue_id: str | None = None,
        # Detailed authentication information
        auth_type: str | None = None,  # cloudflare/captcha/turnstile/hcaptcha/login
        estimated_effort: str | None = None,  # low/medium/high
        # IPv6 connection information
        ip_family: str | None = None,  # ipv4/ipv6/unknown
        ip_switched: bool = False,  # True if we switched from primary family
        # Wayback/archive fallback information
        is_archived: bool = False,  # True if content came from Wayback
        archive_date: datetime | None = None,  # Date of the archive snapshot
        archive_url: str | None = None,  # Original Wayback Machine URL
        freshness_penalty: float = 0.0,  # Penalty for stale content (0.0-1.0)
        # Redirect tracking
        final_url: str | None = None,  # URL after following redirects
    ):
        self.ok = ok
        self.url = url
        self.final_url = final_url or url  # Default to original URL if not provided
        self.status = status
        self.headers = headers or {}
        self.html_path = html_path
        self.pdf_path = pdf_path
        self.warc_path = warc_path
        self.screenshot_path = screenshot_path
        self.content_hash = content_hash
        self.reason = reason
        self.method = method
        self.from_cache = from_cache
        self.etag = etag
        self.last_modified = last_modified
        self.auth_queued = auth_queued
        self.queue_id = queue_id
        self.auth_type = auth_type
        self.estimated_effort = estimated_effort
        self.ip_family = ip_family
        self.ip_switched = ip_switched
        # Archive fields
        self.is_archived = is_archived
        self.archive_date = archive_date
        self.archive_url = archive_url
        self.freshness_penalty = freshness_penalty
        # Page ID for database reference (set after page record created)
        self.page_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "ok": self.ok,
            "url": self.url,
            "final_url": self.final_url,
            "status": self.status,
            "headers": self.headers,
            "html_path": self.html_path,
            "pdf_path": self.pdf_path,
            "warc_path": self.warc_path,
            "screenshot_path": self.screenshot_path,
            "content_hash": self.content_hash,
            "reason": self.reason,
            "method": self.method,
            "from_cache": self.from_cache,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "auth_queued": self.auth_queued,
            "queue_id": self.queue_id,
            "page_id": self.page_id,
        }
        # Include auth details only when relevant
        if self.auth_type:
            result["auth_type"] = self.auth_type
        if self.estimated_effort:
            result["estimated_effort"] = self.estimated_effort
        # Include IPv6 details
        if self.ip_family:
            result["ip_family"] = self.ip_family
        if self.ip_switched:
            result["ip_switched"] = self.ip_switched
        # Include archive details when content is from archive
        if self.is_archived:
            result["is_archived"] = self.is_archived
            result["archive_date"] = self.archive_date.isoformat() if self.archive_date else None
            result["archive_url"] = self.archive_url
            result["freshness_penalty"] = self.freshness_penalty
        return result


class RateLimiter:
    """Per-domain rate limiter.

    Uses DomainPolicyManager for per-domain QPS configuration.
    """

    def __init__(self) -> None:
        self._domain_locks: dict[str, asyncio.Lock] = {}
        self._domain_last_request: dict[str, float] = {}
        self._settings = get_settings()

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc.lower()

    async def acquire(self, url: str) -> None:
        """Acquire rate limit slot for a domain.

        Uses DomainPolicyManager to get per-domain QPS limits.

        Args:
            url: URL to fetch.
        """
        from src.utils.domain_policy import get_domain_policy_manager

        domain = self._get_domain(url)

        if domain not in self._domain_locks:
            self._domain_locks[domain] = asyncio.Lock()

        async with self._domain_locks[domain]:
            last_request = self._domain_last_request.get(domain, 0)

            # Get domain-specific QPS from DomainPolicyManager
            policy_manager = get_domain_policy_manager()
            domain_policy = policy_manager.get_policy(domain)
            min_interval = domain_policy.min_request_interval

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
    """HTTP client fetcher using curl_cffi.

    Features:
    - Chrome impersonation for fingerprint consistency
    - IPv6-first with automatic IPv4 fallback (Happy Eyeballs-style)
    - Per-domain IPv6 success rate learning
    - Conditional requests (ETag/If-Modified-Since) for 304 cache
    """

    def __init__(self) -> None:
        self._rate_limiter = RateLimiter()
        self._settings = get_settings()
        self._ipv6_manager = get_ipv6_manager()

    async def fetch(
        self,
        url: str,
        *,
        referer: str | None = None,
        headers: dict[str, str] | None = None,
        use_tor: bool = False,
        cached_etag: str | None = None,
        cached_last_modified: str | None = None,
    ) -> FetchResult:
        """Fetch URL using HTTP client with conditional request support.

        Implements sec-fetch-* header requirements:
        - Sec-Fetch-Site: Relationship between initiator and target
        - Sec-Fetch-Mode: Request mode (navigate for document fetch)
        - Sec-Fetch-Dest: Request destination (document for pages)
        - Sec-Fetch-User: ?1 for user-initiated navigation

        Args:
            url: URL to fetch.
            referer: Referer header.
            headers: Additional headers.
            use_tor: Whether to use Tor.
            cached_etag: ETag from cache for conditional request.
            cached_last_modified: Last-Modified from cache for conditional request.

        Returns:
            FetchResult instance.
        """
        await self._rate_limiter.acquire(url)

        try:
            from curl_cffi import requests as curl_requests

            # Prepare base headers
            req_headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
            }

            # Generate Sec-Fetch-* headers
            nav_context = NavigationContext(
                target_url=url,
                referer_url=referer,
                is_user_initiated=True,
                destination=SecFetchDest.DOCUMENT,
            )
            sec_fetch_headers = generate_sec_fetch_headers(nav_context)
            req_headers.update(sec_fetch_headers.to_dict())

            if referer:
                req_headers["Referer"] = referer

            # Add conditional request headers for 304 support
            # URL-specific cached values take precedence over session-level values
            # to ensure correct ETag/Last-Modified for each URL
            if cached_etag:
                req_headers["If-None-Match"] = cached_etag
            if cached_last_modified:
                req_headers["If-Modified-Since"] = cached_last_modified

            # Apply session transfer headers
            # Exclude conditional headers if URL-specific values are already set
            # to prevent session-level ETag/Last-Modified from overwriting URL-specific values
            try:
                from src.crawler.session_transfer import get_transfer_headers

                include_conditional = not (cached_etag or cached_last_modified)
                transfer_result = get_transfer_headers(url, include_conditional=include_conditional)

                if transfer_result.ok and transfer_result.headers:
                    req_headers.update(transfer_result.headers)
                    logger.debug(
                        "Applied session transfer headers",
                        url=url[:80],
                        session_id=transfer_result.session_id,
                        header_count=len(transfer_result.headers),
                    )
            except Exception as e:
                logger.debug(
                    "Session transfer header application failed (non-critical)",
                    url=url[:80],
                    error=str(e),
                )

            if headers:
                req_headers.update(headers)

            # Configure proxy if using Tor
            # Use DNS policy manager to ensure DNS is resolved through Tor (socks5h://)
            # when using Tor route, preventing DNS leaks
            dns_manager = get_dns_policy_manager()
            proxies = dns_manager.get_proxy_dict(use_tor)

            # Execute request with Chrome impersonation
            response = curl_requests.get(
                url,
                headers=req_headers,
                proxies=cast(Any, proxies),
                impersonate="chrome",
                timeout=self._settings.crawler.request_timeout,
                allow_redirects=True,
            )

            # Extract response headers
            resp_headers = dict(response.headers)

            # Extract ETag and Last-Modified from response
            resp_etag = resp_headers.get("etag") or resp_headers.get("ETag")
            resp_last_modified = resp_headers.get("last-modified") or resp_headers.get(
                "Last-Modified"
            )

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

            # Record HTTP client request for HTTP/3 policy tracking
            # HTTP client uses HTTP/2 by default, not HTTP/3
            domain = urlparse(url).netloc.lower()
            http3_manager = get_http3_policy_manager()
            await http3_manager.record_request(
                HTTP3RequestResult(
                    domain=domain,
                    url=url,
                    route="http_client",
                    success=True,
                    protocol=ProtocolVersion.HTTP_2,  # curl_cffi uses HTTP/2
                    status_code=response.status_code,
                )
            )

            logger.info(
                "HTTP fetch success",
                url=url[:80],
                status=response.status_code,
                content_length=len(response.content),
                has_etag=bool(resp_etag),
                has_last_modified=bool(resp_last_modified),
            )

            return FetchResult(
                ok=True,
                url=url,
                final_url=str(response.url),  # Track final URL after redirects
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

            # Record failed HTTP client request for HTTP/3 policy tracking
            domain = urlparse(url).netloc.lower()
            http3_manager = get_http3_policy_manager()
            await http3_manager.record_request(
                HTTP3RequestResult(
                    domain=domain,
                    url=url,
                    route="http_client",
                    success=False,
                    protocol=ProtocolVersion.UNKNOWN,
                    error=str(e),
                )
            )

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
    - Lifecycle management for task-scoped cleanup
    - Worker-isolated BrowserContext for true parallelization (ADR-0014 Phase 3)
    """

    def __init__(self, worker_id: int = 0) -> None:
        """Initialize browser fetcher.

        Args:
            worker_id: Worker identifier (0 to num_workers-1).
                       Each worker gets its own isolated BrowserContext.
        """
        self._worker_id = worker_id
        self._rate_limiter = RateLimiter()
        self._settings = get_settings()
        self._headless_browser: Browser | None = None
        self._headless_context: BrowserContext | None = None
        self._headful_browser: Browser | None = None
        self._headful_context: BrowserContext | None = None
        self._playwright: Playwright | None = None
        self._human_behavior = HumanBehavior()
        self._current_task_id: str | None = None
        self._lifecycle_manager = get_lifecycle_manager()

        logger.debug("BrowserFetcher initialized", worker_id=worker_id)

    async def _ensure_browser(
        self,
        headful: bool = False,
        task_id: str | None = None,
    ) -> tuple:
        """Ensure browser connection is established.

        Browser instances are tracked for lifecycle management
        and can be cleaned up after task completion.

        Args:
            headful: Whether to ensure headful browser.
            task_id: Associated task ID for lifecycle tracking.

        Returns:
            Tuple of (browser, context).
        """
        from playwright.async_api import async_playwright

        if self._playwright is None:
            self._playwright = await async_playwright().start()

            # Register playwright for lifecycle management
            if task_id:
                await self._lifecycle_manager.register_resource(
                    f"playwright_{id(self._playwright)}",
                    ResourceType.PLAYWRIGHT,
                    self._playwright,
                    task_id,
                )

        # Type guard: _playwright is guaranteed to be initialized at this point
        assert self._playwright is not None

        # Update current task ID
        if task_id:
            self._current_task_id = task_id

        browser_settings = self._settings.browser

        if headful:
            # Headful mode - for challenge bypass
            if self._headful_browser is None:
                # Try CDP connection first (Windows Chrome)
                # Dynamic Worker Pool: Each worker connects to its own Chrome instance
                from src.utils.config import get_chrome_port

                chrome_port = get_chrome_port(self._worker_id)
                cdp_url = f"http://{browser_settings.chrome_host}:{chrome_port}"
                cdp_connected = False

                logger.debug("Attempting CDP connection", url=cdp_url)
                try:
                    # Add timeout to prevent hanging
                    self._headful_browser = await asyncio.wait_for(
                        self._playwright.chromium.connect_over_cdp(cdp_url),
                        timeout=5.0,  # 5 second timeout for CDP connection
                    )
                    logger.info("Connected to Chrome via CDP (headful)", url=cdp_url)
                    cdp_connected = True
                except TimeoutError:
                    logger.info("CDP connection timed out, attempting auto-start", url=cdp_url)
                    cdp_error: Exception = Exception("CDP connection timeout")
                    # Fall through to auto-start logic
                except Exception as exc:
                    logger.info("CDP connection failed, attempting auto-start", error=str(exc))
                    cdp_error = exc

                # Auto-start Chrome if CDP connection failed
                if not cdp_connected:
                    logger.debug("Calling _auto_start_chrome()")
                    auto_start_success = await self._auto_start_chrome()
                    logger.debug("_auto_start_chrome() returned", success=auto_start_success)

                    if auto_start_success:
                        # Wait for CDP connection with polling (max 15 seconds, 0.5s interval)
                        start_time = time.monotonic()
                        timeout = 15.0
                        poll_interval = 0.5

                        logger.debug(
                            "Waiting for CDP connection after auto-start",
                            timeout=timeout,
                            poll_interval=poll_interval,
                        )
                        while time.monotonic() - start_time < timeout:
                            try:
                                self._headful_browser = await asyncio.wait_for(
                                    self._playwright.chromium.connect_over_cdp(cdp_url),
                                    timeout=2.0,  # 2 second timeout per attempt
                                )
                                elapsed = time.monotonic() - start_time
                                logger.info(
                                    "Connected to Chrome via CDP after auto-start",
                                    url=cdp_url,
                                    elapsed_seconds=round(elapsed, 1),
                                )
                                cdp_connected = True
                                break
                            except Exception as poll_error:
                                elapsed = time.monotonic() - start_time
                                logger.debug(
                                    "CDP connection attempt failed, retrying",
                                    elapsed=round(elapsed, 1),
                                    error=str(poll_error),
                                )
                                await asyncio.sleep(poll_interval)

                    if not cdp_connected:
                        # Per spec ADR-0006: CDP connection is required, no fallback
                        # BrowserFetcher requires real Chrome profile for fingerprint consistency
                        raise RuntimeError(
                            f"CDP connection failed: {cdp_error}. "
                            "Start Chrome with: make chrome-start"
                        )

                # Register browser for lifecycle management
                if task_id:
                    await self._lifecycle_manager.register_resource(
                        f"browser_headful_{id(self._headful_browser)}",
                        ResourceType.BROWSER,
                        self._headful_browser,
                        task_id,
                    )

                # Per ADR-0014 Phase 3: Each worker gets its own isolated BrowserContext
                # Worker 0 can reuse Chrome's default context for cookie preservation
                # Other workers always create new isolated contexts
                if self._headful_browser is not None:
                    existing_contexts = self._headful_browser.contexts
                    if self._worker_id == 0 and existing_contexts:
                        self._headful_context = existing_contexts[0]
                        logger.info(
                            "Worker 0 reusing existing browser context for cookie preservation",
                            worker_id=self._worker_id,
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
                        logger.info(
                            "Created new isolated browser context for worker",
                            worker_id=self._worker_id,
                            total_contexts=len(self._headful_browser.contexts),
                        )
                if self._headful_context is not None:
                    await self._setup_blocking(self._headful_context)

                # Register context for lifecycle management
                if task_id:
                    await self._lifecycle_manager.register_resource(
                        f"context_headful_{id(self._headful_context)}",
                        ResourceType.BROWSER_CONTEXT,
                        self._headful_context,
                        task_id,
                    )

                # Perform profile health audit on browser session initialization
                if self._headful_context is not None:
                    await self._perform_health_audit(self._headful_context, task_id)

            return self._headful_browser, self._headful_context
        else:
            # Per spec ADR-0006: Headless mode is prohibited
            # Lyra uses "real profile consistency" design, not "headless disguised as human"
            raise RuntimeError(
                "Headless mode is prohibited per spec ADR-0006. "
                "Use headful=True with CDP connection to real Chrome profile."
            )

    async def _perform_health_audit(
        self,
        context: "BrowserContext",
        task_id: str | None = None,
    ) -> None:
        """Perform profile health audit on browser session initialization.

        Per high-frequency check requirement: Execute audit at browser session
        initialization to detect drift in UA, fonts, language, timezone, canvas, audio.

        Args:
            context: Browser context to audit.
            task_id: Associated task ID for logging.
        """
        try:
            from src.crawler.profile_audit import AuditStatus, perform_health_check

            # Create temporary page for audit (minimal impact on performance)
            page = await context.new_page()
            try:
                await page.goto("about:blank", wait_until="domcontentloaded", timeout=5000)

                # Perform health check with auto-repair enabled
                audit_result = await perform_health_check(
                    page,
                    force=False,
                    auto_repair=True,
                )

                if audit_result.status == AuditStatus.DRIFT:
                    logger.warning(
                        "Profile drift detected and repaired",
                        task_id=task_id,
                        drifts=[d.attribute for d in audit_result.drifts],
                        repair_status=audit_result.repair_status.value,
                    )
                elif audit_result.status == AuditStatus.FAIL:
                    logger.warning(
                        "Profile health audit failed",
                        task_id=task_id,
                        error=audit_result.error,
                    )
                else:
                    logger.debug(
                        "Profile health check passed",
                        task_id=task_id,
                        status=audit_result.status.value,
                    )
            finally:
                await page.close()
        except Exception as e:
            # Non-blocking: Log error but continue with normal flow
            logger.warning(
                "Profile health audit error (non-blocking)",
                task_id=task_id,
                error=str(e),
            )

    async def _auto_start_chrome(self) -> bool:
        """Auto-start Chrome for this worker using chrome.sh script.

        When a CDP (Chrome DevTools Protocol) connection is not detected,
        Lyra automatically executes ./scripts/chrome.sh start-worker N to launch
        Chrome for the specific worker.

        Uses a global lock (shared with BrowserSearchProvider) to prevent race
        conditions where multiple components might simultaneously try to start
        Chrome instances.

        Returns:
            True if Chrome is ready (started or already running), False otherwise.
        """
        import asyncio
        from pathlib import Path

        from src.search.browser_search_provider import (
            _check_cdp_available,
            _get_chrome_start_lock,
        )
        from src.utils.config import get_chrome_port

        # Find chrome.sh script relative to project root
        # src/crawler/fetcher.py -> scripts/chrome.sh
        script_path = Path(__file__).parent.parent.parent / "scripts" / "chrome.sh"

        if not script_path.exists():
            logger.warning("chrome.sh not found", path=str(script_path))
            return False

        # Get Chrome connection info for this worker
        chrome_host = self._settings.browser.chrome_host
        chrome_port = get_chrome_port(self._worker_id)

        # Acquire lock to prevent race conditions between workers/components
        lock = _get_chrome_start_lock()
        async with lock:
            # After acquiring lock, check if Chrome is already ready
            # (another component may have started it while we were waiting)
            if await _check_cdp_available(chrome_host, chrome_port):
                logger.info(
                    "Chrome already available (started by another component or mcp.sh)",
                    worker_id=self._worker_id,
                    port=chrome_port,
                )
                return True

            # Start Chrome for this specific worker
            try:
                logger.info(
                    "Auto-starting Chrome for worker",
                    worker_id=self._worker_id,
                    port=chrome_port,
                    script=str(script_path),
                )
                process = await asyncio.create_subprocess_exec(
                    str(script_path),
                    "start-worker",
                    str(self._worker_id),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                # Wait for process completion with timeout
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=30.0,  # 30 second timeout for script execution
                    )
                except TimeoutError:
                    logger.error(
                        "Chrome auto-start timed out",
                        worker_id=self._worker_id,
                    )
                    process.kill()
                    await process.wait()
                    return False

                stdout_text = stdout.decode() if stdout else ""
                stderr_text = stderr.decode() if stderr else ""

                if process.returncode == 0:
                    logger.info(
                        "Chrome auto-start script completed",
                        worker_id=self._worker_id,
                        stdout=stdout_text[:200] if stdout_text else "",
                    )
                    return True
                else:
                    logger.warning(
                        "Chrome auto-start script failed",
                        worker_id=self._worker_id,
                        returncode=process.returncode,
                        stderr=stderr_text[:200] if stderr_text else "",
                    )
                    return False
            except Exception as e:
                logger.error(
                    "Chrome auto-start error",
                    worker_id=self._worker_id,
                    error=str(e),
                )
                return False

    async def _setup_blocking(self, context: "BrowserContext") -> None:
        """Setup resource blocking rules.

        Args:
            context: Playwright browser context.
        """
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

    async def _should_use_headful(self, domain: str) -> bool:
        """Determine if headful mode should be used for domain.

        Per ADR-0006: Headless mode is prohibited. Lyra uses "real profile
        consistency" design, requiring CDP connection to real Chrome profile.
        This method always returns True to enforce headful mode.

        Args:
            domain: Domain name (unused, kept for API compatibility).

        Returns:
            Always True (headful mode required per ADR-0006).
        """
        # ADR-0006: Headless mode is prohibited
        # Always use headful mode with CDP connection to real Chrome profile
        return True

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
        queue_auth: bool = True,
        auth_priority: str = "medium",
    ) -> FetchResult:
        """Fetch URL using browser with automatic mode selection.

        Args:
            url: URL to fetch.
            referer: Referer header.
            queue_auth: If True, queue authentication instead of blocking (semi-auto mode).
            auth_priority: Priority for queued auth (high, medium, low).
            headful: Force headful mode (None for auto-detect).
            take_screenshot: Whether to capture screenshot.
            simulate_human: Whether to simulate human behavior.
            task_id: Associated task ID for intervention tracking.
            allow_intervention: Whether to allow manual intervention on challenge.

        Returns:
            FetchResult instance.
        """
        await self._rate_limiter.acquire(url)

        domain = urlparse(url).netloc.lower()

        # Check for existing authenticated session for reuse
        # Domain-based authentication: one authentication applies to multiple tasks/URLs for the same domain
        existing_session = None
        from src.utils.notification import get_intervention_queue

        queue = get_intervention_queue()
        # task_id is optional (domain-based lookup)
        existing_session = await queue.get_session_for_domain(domain, task_id=task_id)

        # Determine headful mode
        if headful is None:
            headful = await self._should_use_headful(domain)

        browser, context = await self._ensure_browser(headful=headful, task_id=task_id)

        # Apply stored authentication cookies if available
        if existing_session and existing_session.get("cookies"):
            cookies = existing_session["cookies"]
            try:
                # Convert to Playwright cookie format
                playwright_cookies = []
                for c in cookies:
                    cookie_dict = {
                        "name": c.get("name", ""),
                        "value": c.get("value", ""),
                        "domain": c.get("domain", domain),
                        "path": c.get("path", "/"),
                        "httpOnly": c.get("httpOnly", False),
                        "secure": c.get("secure", True),
                        "sameSite": c.get("sameSite", "Lax"),
                    }
                    # Add expires if present
                    expires = c.get("expires")
                    if expires:
                        cookie_dict["expires"] = expires

                    playwright_cookies.append(cookie_dict)

                if playwright_cookies:
                    await context.add_cookies(playwright_cookies)
                    logger.info(
                        "Applied stored authentication cookies",
                        domain=domain,
                        cookie_count=len(playwright_cookies),
                        task_id=task_id,
                    )
            except Exception as e:
                logger.warning(
                    "Failed to apply stored cookies",
                    domain=domain,
                    error=str(e),
                    task_id=task_id,
                )

        page = None
        keep_page_open = False  # ADR-0007: Keep page open for CAPTCHA resolution
        try:
            page = await context.new_page()

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
                    # Detect challenge type for detailed response
                    challenge_type = _detect_challenge_type(content)
                    return FetchResult(
                        ok=False,
                        url=url,
                        status=response.status,
                        reason="challenge_detected_escalate_headful",
                        method="browser_headless",
                        auth_type=challenge_type,
                        estimated_effort=_estimate_auth_effort(challenge_type),
                    )
                else:
                    # Headful mode - handle authentication challenge
                    challenge_type = _detect_challenge_type(content)
                    estimated_effort = _estimate_auth_effort(challenge_type)

                    if allow_intervention and queue_auth and task_id:
                        # Queue authentication for batch processing (semi-auto mode)
                        from src.utils.notification import get_intervention_queue

                        queue = get_intervention_queue()
                        queue_id = await queue.enqueue(
                            task_id=task_id,
                            url=url,
                            domain=domain,
                            auth_type=challenge_type,
                            priority=auth_priority,
                        )

                        logger.info(
                            "Authentication queued - keeping page open for user resolution",
                            url=url[:80],
                            queue_id=queue_id,
                            auth_type=challenge_type,
                            estimated_effort=estimated_effort,
                        )

                        # ADR-0007: Keep page open for user to resolve CAPTCHA
                        keep_page_open = True

                        return FetchResult(
                            ok=False,
                            url=url,
                            status=response.status,
                            reason="auth_required",
                            method="browser_headful",
                            auth_queued=True,
                            queue_id=queue_id,
                            auth_type=challenge_type,
                            estimated_effort=estimated_effort,
                        )
                    elif allow_intervention:
                        # Immediate intervention (legacy mode)
                        intervention_result = await self._request_manual_intervention(
                            url=url,
                            domain=domain,
                            page=page,
                            task_id=task_id,
                            challenge_type=challenge_type,
                        )

                        if (
                            intervention_result
                            and intervention_result.status == InterventionStatus.SUCCESS
                        ):
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
                                    auth_type=challenge_type,
                                    estimated_effort=estimated_effort,
                                )
                        elif intervention_result:
                            # Intervention failed/timed out/skipped
                            return FetchResult(
                                ok=False,
                                url=url,
                                status=response.status,
                                reason=f"intervention_{intervention_result.status.value}",
                                method="browser_headful",
                                auth_type=challenge_type,
                                estimated_effort=estimated_effort,
                            )
                    else:
                        # Intervention not allowed - return challenge error
                        return FetchResult(
                            ok=False,
                            url=url,
                            status=response.status,
                            reason="challenge_detected",
                            method="browser_headful",
                            auth_type=challenge_type,
                            estimated_effort=estimated_effort,
                        )

                    # Re-get content after successful intervention
                    content = await page.content()
                    content_bytes = content.encode("utf-8")
                    content_hash = hashlib.sha256(content_bytes).hexdigest()

            # Simulate human reading behavior with full human-like interactions
            if simulate_human:
                # Apply inertial scrolling (reading simulation)
                await self._human_behavior.simulate_reading(page, len(content_bytes))

                # Apply mouse trajectory to page elements
                try:
                    # Find interactive elements (links, buttons, inputs)
                    elements = await page.query_selector_all(
                        "a, button, input[type='text'], input[type='search']"
                    )
                    if elements:
                        # Select random element from first 5 elements
                        target_element = random.choice(elements[:5])
                        # Get element selector
                        element_selector = await target_element.evaluate(
                            """
                            (el) => {
                                if (el.id) return `#${el.id}`;
                                if (el.className) {
                                    const classes = el.className.split(' ').filter(c => c).join('.');
                                    if (classes) return `${el.tagName.toLowerCase()}.${classes}`;
                                }
                                return el.tagName.toLowerCase();
                            }
                        """
                        )
                        if element_selector:
                            await self._human_behavior.move_mouse_to_element(page, element_selector)
                except Exception as e:
                    logger.debug("Mouse movement skipped", error=str(e))

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

            # Extract ETag and Last-Modified from response headers
            resp_etag = resp_headers.get("etag") or resp_headers.get("ETag")
            resp_last_modified = resp_headers.get("last-modified") or resp_headers.get(
                "Last-Modified"
            )

            # Detect HTTP/3 protocol usage
            protocol = await detect_protocol_from_playwright_response(response)

            # Record HTTP/3 usage for policy tracking
            http3_manager = get_http3_policy_manager()
            await http3_manager.record_request(
                HTTP3RequestResult(
                    domain=domain,
                    url=url,
                    route="browser",
                    success=True,
                    protocol=protocol,
                    status_code=response.status,
                )
            )

            logger.info(
                "Browser fetch success",
                url=url[:80],
                status=response.status,
                content_length=len(content_bytes),
                headful=headful,
                has_etag=bool(resp_etag),
                has_last_modified=bool(resp_last_modified),
                protocol=protocol.value,
            )

            # Capture browser session for transfer to HTTP client
            try:
                from src.crawler.session_transfer import capture_browser_session

                session_id = await capture_browser_session(
                    context,
                    url,
                    resp_headers,
                )
                if session_id:
                    logger.debug(
                        "Captured browser session",
                        url=url[:80],
                        session_id=session_id,
                    )
            except Exception as e:
                logger.debug(
                    "Session capture failed (non-critical)",
                    url=url[:80],
                    error=str(e),
                )

            return FetchResult(
                ok=True,
                url=url,
                final_url=page.url,  # Track final URL after redirects
                status=response.status,
                headers=resp_headers,
                html_path=str(html_path) if html_path else None,
                warc_path=str(warc_path) if warc_path else None,
                screenshot_path=str(screenshot_path) if screenshot_path else None,
                content_hash=content_hash,
                method="browser_headful" if headful else "browser_headless",
                from_cache=False,
                etag=resp_etag,
                last_modified=resp_last_modified,
            )

        except Exception as e:
            logger.error("Browser fetch error", url=url, headful=headful, error=str(e))

            # Record failed request for HTTP/3 policy tracking
            http3_manager = get_http3_policy_manager()
            await http3_manager.record_request(
                HTTP3RequestResult(
                    domain=domain,
                    url=url,
                    route="browser",
                    success=False,
                    protocol=ProtocolVersion.UNKNOWN,
                    error=str(e),
                )
            )

            return FetchResult(
                ok=False,
                url=url,
                reason=str(e),
                method="browser_headful" if headful else "browser_headless",
            )
        finally:
            # ADR-0007: Keep page open for CAPTCHA resolution if auth was queued
            if page and not keep_page_open:
                await page.close()
            elif keep_page_open:
                logger.debug(
                    "Page kept open for CAPTCHA resolution",
                    url=url[:80],
                )

    async def _request_manual_intervention(
        self,
        url: str,
        domain: str,
        page: "Page",
        task_id: str | None,
        challenge_type: str,
    ) -> Any:
        """Request manual intervention for challenge bypass.

        Safe Operation Policy:
        - Sends toast notification
        - Brings window to front via OS API
        - Returns PENDING status immediately
        - User finds and resolves challenge themselves
        - NO DOM operations (scroll, highlight, focus)

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

            # Request intervention per safe operation policy
            # No element_selector or on_success_callback (DOM operations forbidden)
            result = await intervention_manager.request_intervention(
                intervention_type=intervention_type,
                url=url,
                domain=domain,
                task_id=task_id,
                page=page,
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

    This function uses specific patterns to avoid false positives from:
    - Cookie consent banners that reference CAPTCHA services
    - Article content mentioning CAPTCHA/security topics
    - Third-party scripts with CAPTCHA-related URLs

    Args:
        content: Page content.
        headers: Response headers.

    Returns:
        True if challenge detected.
    """
    content_lower = content.lower()

    # Cloudflare challenge page indicators (highly specific)
    # These patterns indicate an ACTIVE challenge, not just a reference
    cloudflare_challenge_indicators = [
        "cf-browser-verification",  # Cloudflare verification element
        "_cf_chl_opt",  # Cloudflare challenge options
        "checking your browser before accessing",  # Challenge text
        "please wait while we verify your browser",  # Challenge text
        "ray id:</strong>",  # Challenge page format (not just "cloudflare ray id")
    ]

    if any(ind in content_lower for ind in cloudflare_challenge_indicators):
        return True

    # Check for "Just a moment" + Cloudflare combination (challenge page title)
    if "just a moment" in content_lower and (
        "cloudflare" in content_lower or "_cf_" in content_lower
    ):
        return True

    # CAPTCHA widget indicators (must be active widgets, not references)
    # Look for iframe sources or specific widget containers
    active_captcha_indicators = [
        'src="https://hcaptcha.com',  # hCaptcha iframe
        'src="https://www.hcaptcha.com',
        "data-sitekey=",  # CAPTCHA widget with sitekey
        'class="h-captcha"',  # hCaptcha container element
        'class="g-recaptcha"',  # reCAPTCHA container element
        'id="captcha-container"',  # Explicit captcha container
        "grecaptcha.execute",  # reCAPTCHA v3 execution
        "hcaptcha.execute",  # hCaptcha execution
    ]

    if any(ind in content_lower for ind in active_captcha_indicators):
        return True

    # Turnstile indicators (Cloudflare's CAPTCHA alternative)
    turnstile_indicators = [
        'class="cf-turnstile"',  # Turnstile widget container
        "challenges.cloudflare.com/turnstile",  # Turnstile script URL
    ]

    if any(ind in content_lower for ind in turnstile_indicators):
        return True

    # Server header check - only for small pages (challenge pages are typically tiny)
    server = headers.get("server", "").lower()
    if "cloudflare" in server:
        cf_ray = headers.get("cf-ray")
        # Challenge pages are very small (< 5KB) and have cf-ray header
        if cf_ray and len(content) < 5000:
            # Additional check: challenge pages have minimal HTML structure
            if "<body" in content_lower and content_lower.count("<div") < 10:
                return True

    return False


def _detect_challenge_type(content: str) -> str:
    """Detect the specific type of challenge from page content.

    This function is called AFTER _is_challenge_page() returns True,
    so we know the page is a challenge page. This determines the type.

    Args:
        content: Page HTML content.

    Returns:
        Challenge type string.
    """
    content_lower = content.lower()

    # Check for specific challenge types in order of specificity
    # Use same specific patterns as _is_challenge_page for consistency
    if (
        'class="cf-turnstile"' in content_lower
        or "challenges.cloudflare.com/turnstile" in content_lower
    ):
        return "turnstile"

    if 'src="https://hcaptcha.com' in content_lower or 'class="h-captcha"' in content_lower:
        return "hcaptcha"

    if 'class="g-recaptcha"' in content_lower or "grecaptcha.execute" in content_lower:
        return "recaptcha"

    if "data-sitekey=" in content_lower:
        # Generic CAPTCHA with sitekey - check for type indicators
        if "hcaptcha" in content_lower:
            return "hcaptcha"
        if "recaptcha" in content_lower:
            return "recaptcha"
        return "captcha"

    # Cloudflare challenge indicators
    cloudflare_indicators = [
        "cf-browser-verification",
        "_cf_chl_opt",
        "checking your browser before accessing",
    ]
    if any(ind in content_lower for ind in cloudflare_indicators):
        return "cloudflare"

    # Generic JS challenge (Cloudflare "Just a moment" page)
    if "just a moment" in content_lower and "cloudflare" in content_lower:
        return "js_challenge"

    return "cloudflare"  # Default for unidentified challenges


# NOTE: _get_challenge_element_selector has been removed per safe operation policy
# (Safe Operation Policy - no DOM operations during authentication sessions)


def _estimate_auth_effort(challenge_type: str) -> str:
    """Estimate the effort required to complete authentication.

    Provides estimated_effort for auth challenges.

    Args:
        challenge_type: Type of challenge detected.

    Returns:
        Effort level: "low", "medium", or "high".
    """
    # Effort mapping based on typical time/complexity
    effort_map = {
        # Low: Usually auto-resolves or simple click
        "js_challenge": "low",
        "cloudflare": "low",  # Basic Cloudflare often auto-resolves
        # Medium: Requires simple user interaction
        "turnstile": "medium",  # Usually just a click/checkbox
        # High: Requires significant user effort
        "captcha": "high",
        "recaptcha": "high",
        "hcaptcha": "high",
        "login": "high",
    }

    return effort_map.get(challenge_type, "medium")


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
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{url_hash}.warc.gz"
    filepath = warc_dir / filename

    try:
        with open(filepath, "wb") as output:
            writer = WARCWriter(output, gzip=True)

            # Create WARC-Date in ISO format
            warc_date = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

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


async def _save_screenshot(page: "Page", url: str) -> Path | None:
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
# Worker ID -> BrowserFetcher mapping (ADR-0014 Phase 3: Worker Context Isolation)
_browser_fetchers: dict[int, BrowserFetcher] = {}


async def fetch_url(
    url: str,
    context: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    task_id: str | None = None,
    worker_id: int = 0,
) -> dict[str, Any]:
    """Fetch URL with automatic method selection, escalation, and cache support.

    Implements multi-stage fetch strategy:
    1. HTTP client (fastest, with 304 cache support)
    2. Browser headless (for JS-rendered pages)
    3. Browser headful (for challenge bypass)
    4. Tor circuit renewal on 403/429
    5. Wayback fallback (for persistent blocks)

    Supports conditional requests (If-None-Match/If-Modified-Since) for
    efficient re-validation and 304 Not Modified responses.

    Cumulative timeout (max_fetch_time) ensures the entire fetch operation
    completes within a reasonable time, preventing exploration stalls.

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
            - use_provider: Use BrowserProviderRegistry for browser fetching (default: False).
            - provider_name: Specific provider to use (e.g., "playwright", "undetected_chrome").
            - max_fetch_time: Override cumulative timeout (default: from config).
        task_id: Associated task ID.
        worker_id: Worker ID for isolated browser context (ADR-0014 Phase 3).

    Returns:
        Fetch result dictionary with additional 'from_cache' field.
    """
    context = context or {}
    policy = policy or {}
    settings = get_settings()

    # Get cumulative timeout from policy or config
    max_fetch_time = policy.get("max_fetch_time", settings.crawler.max_fetch_time)

    try:
        # Wrap entire fetch operation with cumulative timeout
        return await asyncio.wait_for(
            _fetch_url_impl(url, context, policy, task_id, worker_id),
            timeout=float(max_fetch_time),
        )
    except TimeoutError:
        logger.warning(
            "Fetch cumulative timeout exceeded",
            url=url[:80],
            max_fetch_time=max_fetch_time,
        )
        # Return timeout result
        return FetchResult(
            ok=False,
            url=url,
            reason="cumulative_timeout",
            method="timeout",
        ).to_dict()


async def _fetch_url_impl(
    url: str,
    context: dict[str, Any],
    policy: dict[str, Any],
    task_id: str | None,
    worker_id: int = 0,
) -> dict[str, Any]:
    """Internal implementation of fetch_url with multi-stage escalation.

    This function contains the actual fetch logic. It is wrapped by fetch_url
    with a cumulative timeout to prevent indefinite blocking.

    Args:
        url: URL to fetch.
        context: Context information.
        policy: Fetch policy override.
        task_id: Associated task ID.
        worker_id: Worker ID for isolated browser context (ADR-0014 Phase 3).
    """
    global _http_fetcher, _browser_fetchers

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

        # Check domain daily budget (ADR-0006 - IP block prevention)
        from src.scheduler.domain_budget import get_domain_budget_manager

        budget_manager = get_domain_budget_manager()
        budget_check = budget_manager.can_request_to_domain(domain)

        if not budget_check.allowed:
            logger.warning(
                "Domain daily budget exceeded",
                domain=domain,
                reason=budget_check.reason,
                url=url[:80],
            )
            return FetchResult(
                ok=False,
                url=url,
                reason="domain_budget_exceeded",
            ).to_dict()

        # Record request for Tor daily limit tracking (Tor daily usage limit)
        # Must be after cooldown check to only count actual fetches
        from src.utils.metrics import get_metrics_collector

        collector = get_metrics_collector()
        collector.record_request(domain)

        # Determine fetch method
        force_browser = policy.get("force_browser", False)
        force_headful = policy.get("force_headful", False)
        use_tor = policy.get("use_tor", False)
        skip_cache = policy.get("skip_cache", False)
        policy.get("max_retries", settings.crawler.max_retries)
        use_provider = policy.get("use_provider", False)
        provider_name = policy.get("provider_name", None)

        # Initialize fetchers
        if _http_fetcher is None:
            _http_fetcher = HTTPFetcher()
        # Get worker-specific browser fetcher (ADR-0014 Phase 3)
        if worker_id not in _browser_fetchers:
            _browser_fetchers[worker_id] = BrowserFetcher(worker_id=worker_id)
            logger.info("Created BrowserFetcher for worker", worker_id=worker_id)
        _browser_fetcher = _browser_fetchers[worker_id]

        # Check cache for conditional request data
        cached_etag = None
        cached_last_modified = None
        cached_content_path = None
        cached_content_hash = None
        has_previous_browser_fetch = False

        if not skip_cache and not force_browser:
            cache_entry = await db.get_fetch_cache(url)
            if cache_entry:
                cached_etag = cache_entry.get("etag")
                cached_last_modified = cache_entry.get("last_modified")
                cached_content_path = cache_entry.get("content_path")
                cached_content_hash = cache_entry.get("content_hash")
                # Subsequent visits use HTTP client with 304 cache
                # If cache entry exists with ETag/Last-Modified, use HTTP client
                has_previous_browser_fetch = bool(cached_etag or cached_last_modified)

                logger.debug(
                    "Found cache entry for conditional request",
                    url=url[:80],
                    has_etag=bool(cached_etag),
                    has_last_modified=bool(cached_last_modified),
                    has_previous_browser_fetch=has_previous_browser_fetch,
                )

        result = None
        retry_count = 0
        escalation_path = []  # Track escalation for logging

        # =====================================================================
        # First visit uses browser, subsequent visits use HTTP client with 304 cache
        # =====================================================================
        # Stage 1: HTTP Client (with optional Tor) - only for subsequent visits
        # =====================================================================
        if not force_browser and has_previous_browser_fetch:
            result = await _http_fetcher.fetch(
                url,
                referer=context.get("referer"),
                use_tor=use_tor,
                cached_etag=cached_etag,
                cached_last_modified=cached_last_modified,
            )
            escalation_path.append(f"http_client(tor={use_tor})")

            # Record Tor usage when explicitly requested (Tor daily usage limit)
            if use_tor:
                from src.utils.metrics import get_metrics_collector

                collector = get_metrics_collector()
                collector.record_tor_usage(domain)

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

            # Handle 403/429 - try Tor circuit renewal (with daily limit check)
            if not result.ok and result.status in (403, 429) and not use_tor:
                # Check Tor daily limit before escalating (Tor daily usage limit)
                if await _can_use_tor(domain):
                    logger.info("HTTP error, trying with Tor", url=url[:80], status=result.status)

                    tor_controller = await get_tor_controller()
                    if await tor_controller.renew_circuit(domain):
                        result = await _http_fetcher.fetch(
                            url,
                            referer=context.get("referer"),
                            use_tor=True,
                            cached_etag=cached_etag,
                            cached_last_modified=cached_last_modified,
                        )
                        escalation_path.append("http_client(tor=True)")
                        retry_count += 1

                        # Record Tor usage for daily limit tracking
                        from src.utils.metrics import get_metrics_collector

                        collector = get_metrics_collector()
                        collector.record_tor_usage(domain)
                else:
                    logger.info(
                        "Tor daily limit reached, skipping Tor escalation",
                        url=url[:80],
                        status=result.status,
                    )

            # If challenge detected or still failing, escalate to browser
            if not result.ok and result.reason == "challenge_detected":
                logger.info("Challenge detected, escalating to browser", url=url[:80])
                force_browser = True

        # =====================================================================
        # First visit uses browser route (when cache is not available)
        # =====================================================================
        # Stage 1b: Browser (first visit) - first access uses browser by default
        # =====================================================================
        if not force_browser and not has_previous_browser_fetch and (not result or not result.ok):
            # First access uses browser route (headless) even for static pages
            logger.debug(
                "First visit detected, using browser route",
                url=url[:80],
            )
            force_browser = True

        # =====================================================================
        # Stage 2: Browser via Provider (if use_provider=True)
        # =====================================================================
        if force_browser and use_provider:
            registry = get_browser_registry()

            browser_options = BrowserOptions(
                mode=BrowserMode.HEADFUL if force_headful else BrowserMode.HEADLESS,
                referer=context.get("referer"),
                simulate_human=True,
                take_screenshot=True,
            )

            if provider_name:
                # Use specific provider
                provider = registry.get(provider_name)
                if provider:
                    provider_result = await provider.navigate(url, browser_options)
                else:
                    logger.warning(f"Provider {provider_name} not found, using fallback")
                    provider_result = await registry.navigate_with_fallback(url, browser_options)
            else:
                # Use fallback strategy
                provider_result = await registry.navigate_with_fallback(url, browser_options)

            escalation_path.append(f"provider({provider_result.provider})")

            if provider_result.ok:
                # Convert ProviderPageResult to FetchResult
                result = FetchResult(
                    ok=True,
                    url=url,
                    status=provider_result.status,
                    html_path=provider_result.html_path,
                    screenshot_path=provider_result.screenshot_path,
                    content_hash=provider_result.content_hash,
                    method=f"provider_{provider_result.provider}",
                    from_cache=False,
                )
            else:
                result = FetchResult(
                    ok=False,
                    url=url,
                    status=provider_result.status,
                    reason=provider_result.error,
                    method=f"provider_{provider_result.provider}",
                    auth_type=provider_result.challenge_type,
                )

                if provider_result.challenge_detected:
                    # Update domain policy for future
                    await _update_domain_headful_ratio(db, domain, increase=True)

        # =====================================================================
        # Stage 2b: Browser Headless (legacy path, auto mode selection)
        # =====================================================================
        elif force_browser and not force_headful:
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
        # Stage 4: Undetected ChromeDriver (for Cloudflare advanced/Turnstile)
        # =====================================================================
        use_undetected = policy.get("use_undetected", False)

        # Auto-escalate to undetected-chromedriver if:
        # 1. Explicitly requested, OR
        # 2. Headful browser failed with persistent challenge
        if not use_undetected and result and not result.ok:
            if result.reason in (
                "challenge_detected",
                "challenge_detected_after_intervention",
                "intervention_timeout",
                "intervention_failed",
            ):
                # Check if domain has high persistent challenge rate
                domain_info = await db.fetch_one(
                    "SELECT captcha_rate, block_score FROM domains WHERE domain = ?",
                    (domain,),
                )
                if domain_info:
                    captcha_rate = domain_info.get("captcha_rate", 0.0)
                    block_score = domain_info.get("block_score", 0)
                    # Auto-escalate for domains with persistent issues
                    if captcha_rate > 0.5 or block_score > 5:
                        use_undetected = True
                        logger.info(
                            "Auto-escalating to undetected-chromedriver",
                            url=url[:80],
                            captcha_rate=captcha_rate,
                            block_score=block_score,
                        )

        if use_undetected and (not result or not result.ok):
            try:
                undetected_fetcher = get_undetected_fetcher()

                if undetected_fetcher.is_available():
                    uc_result = await undetected_fetcher.fetch(
                        url,
                        headless=False,  # Headful is more effective for bypass
                        wait_for_cloudflare=True,
                        cloudflare_timeout=45,  # Allow more time for challenge
                        take_screenshot=True,
                        simulate_human=True,
                    )
                    escalation_path.append("undetected_chromedriver")
                    retry_count += 1

                    if uc_result.ok:
                        # Convert UndetectedFetchResult to FetchResult
                        result = FetchResult(
                            ok=True,
                            url=url,
                            status=uc_result.status,
                            html_path=uc_result.html_path,
                            screenshot_path=uc_result.screenshot_path,
                            content_hash=uc_result.content_hash,
                            method="undetected_chromedriver",
                            from_cache=False,
                        )
                        logger.info(
                            "Undetected-chromedriver bypass success",
                            url=url[:80],
                        )
                    else:
                        logger.warning(
                            "Undetected-chromedriver bypass failed",
                            url=url[:80],
                            reason=uc_result.reason,
                        )
                else:
                    logger.debug(
                        "Undetected-chromedriver not available, skipping",
                        url=url[:80],
                    )
            except Exception as e:
                logger.error(
                    "Undetected-chromedriver error",
                    url=url[:80],
                    error=str(e),
                )

        # =====================================================================
        # Stage 5: Wayback Fallback (for persistent 403/CAPTCHA)
        # =====================================================================
        use_wayback_fallback = policy.get("use_wayback_fallback", True)

        # Auto-fallback to Wayback if:
        # 1. Fallback is enabled, AND
        # 2. All previous stages failed with 403/CAPTCHA/blocking
        if use_wayback_fallback and result and not result.ok:
            should_try_wayback = result.status in (403, 429, 451, 503) or result.reason in (
                "challenge_detected",
                "challenge_detected_after_intervention",
                "challenge_detected_escalate_headful",
                "intervention_timeout",
                "intervention_failed",
                "auth_required",
            )

            if should_try_wayback:
                logger.info(
                    "Attempting Wayback fallback",
                    url=url[:80],
                    reason=result.reason,
                    status=result.status,
                )

                try:
                    wayback_fallback = get_wayback_fallback()
                    fallback_result = await wayback_fallback.get_fallback_content(url)

                    if fallback_result.ok and fallback_result.html:
                        # Save archived content
                        archived_content = fallback_result.html.encode("utf-8")
                        content_hash = hashlib.sha256(archived_content).hexdigest()
                        html_path = await _save_content(url, archived_content, {})

                        # Create successful result from archive
                        result = FetchResult(
                            ok=True,
                            url=url,
                            status=200,  # Treat as successful
                            html_path=str(html_path) if html_path else None,
                            content_hash=content_hash,
                            method="wayback_fallback",
                            from_cache=False,
                            # Archive-specific fields
                            is_archived=True,
                            archive_date=(
                                fallback_result.snapshot.timestamp
                                if fallback_result.snapshot
                                else None
                            ),
                            archive_url=(
                                fallback_result.snapshot.wayback_url
                                if fallback_result.snapshot
                                else None
                            ),
                            freshness_penalty=fallback_result.freshness_penalty,
                        )
                        escalation_path.append("wayback_fallback")

                        logger.info(
                            "Wayback fallback successful",
                            url=url[:80],
                            archive_date=(
                                result.archive_date.isoformat() if result.archive_date else None
                            ),
                            freshness_penalty=result.freshness_penalty,
                        )

                        # Update domain's wayback success rate for future reference
                        await _update_domain_wayback_success(db, domain, success=True)
                    else:
                        logger.warning(
                            "Wayback fallback failed",
                            url=url[:80],
                            error=fallback_result.error,
                        )
                        await _update_domain_wayback_success(db, domain, success=False)

                except Exception as e:
                    logger.error(
                        "Wayback fallback error",
                        url=url[:80],
                        error=str(e),
                    )

        # =====================================================================
        # Update Metrics and Store Results
        # =====================================================================

        # Update domain metrics
        if result is not None:
            await db.update_domain_metrics(
                domain,
                success=result.ok,
                is_captcha=bool(result.reason and "challenge" in result.reason),
                is_http_error=bool(result.status and result.status >= 400),
            )

        # Update IPv6 metrics
        # Track connection result for IPv6 learning
        ipv6_manager = get_ipv6_manager()
        ip_family_used = AddressFamily.IPV4  # Default assumption

        # Determine IP family from result or connection info
        # Note: curl_cffi doesn't expose the actual IP family used,
        # so we track based on success/failure patterns for learning
        if result is not None:
            if result.ok:
                # Record as success for learning
                ipv6_result = IPv6ConnectionResult(
                    hostname=urlparse(url).hostname or domain,
                    success=True,
                    family_used=ip_family_used,
                    family_attempted=ip_family_used,
                    switched=False,
                    switch_success=False,
                    latency_ms=0,  # Not tracked at this level
                )
                await ipv6_manager.record_connection_result(domain, ipv6_result)
            elif result.reason and "timeout" in result.reason.lower():
                # Timeout might indicate IPv6 connectivity issue
                ipv6_result = IPv6ConnectionResult(
                    hostname=urlparse(url).hostname or domain,
                    success=False,
                    family_used=ip_family_used,
                    family_attempted=ip_family_used,
                    switched=False,
                    switch_success=False,
                    latency_ms=0,
                    error=result.reason,
                )
                await ipv6_manager.record_connection_result(domain, ipv6_result)

        # Store page record and update cache if successful
        if result is not None and result.ok:
            # Update pages table and capture page_id for fragment linking
            page_id = await db.insert(
                "pages",
                {
                    "url": url,
                    "final_url": result.final_url,
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
                },
                or_replace=True,
            )
            if result is not None:
                result.page_id = page_id

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
        if result is not None:
            event_details = {
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
                "ip_family": result.ip_family,
                "ip_switched": result.ip_switched,
            }

            # Add archive details if content is from Wayback
            if result.is_archived:
                event_details["is_archived"] = True
                event_details["archive_date"] = (
                    result.archive_date.isoformat() if result.archive_date else None
                )
                event_details["freshness_penalty"] = result.freshness_penalty

            await db.log_event(
                event_type="fetch",
                message=f"Fetched {url[:60]}",
                task_id=task_id,
                cause_id=trace.id,
                component="crawler",
                details=event_details,
            )

            # Record domain request for daily budget tracking (ADR-0006 - Domain daily budget)
            # Only record successful fetches with actual content (not 304)
            if result.ok and result.status != 304:
                budget_manager.record_domain_request(domain, is_page=True)

            return result.to_dict()

        # If result is None, return empty dict
        return {}


async def _update_domain_headful_ratio(db: "Database", domain: str, increase: bool = True) -> None:
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
        await db.insert(
            "domains",
            {
                "domain": domain,
                "headful_ratio": 0.3 if increase else 0.1,
            },
            auto_id=False,
        )
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


async def _update_domain_wayback_success(db: "Database", domain: str, success: bool) -> None:
    """Update domain's Wayback fallback success rate.

    Track Wayback fallback success to inform future fallback decisions.

    Args:
        db: Database instance.
        domain: Domain name.
        success: Whether the Wayback fallback was successful.
    """
    current = await db.fetch_one(
        "SELECT wayback_success_count, wayback_failure_count FROM domains WHERE domain = ?",
        (domain,),
    )

    if current is None:
        # Create domain record with initial Wayback stats
        await db.insert(
            "domains",
            {
                "domain": domain,
                "wayback_success_count": 1 if success else 0,
                "wayback_failure_count": 0 if success else 1,
            },
            auto_id=False,
        )
    else:
        success_count = current.get("wayback_success_count", 0) or 0
        failure_count = current.get("wayback_failure_count", 0) or 0

        if success:
            success_count += 1
        else:
            failure_count += 1

        await db.update(
            "domains",
            {
                "wayback_success_count": success_count,
                "wayback_failure_count": failure_count,
            },
            "domain = ?",
            (domain,),
        )

        # Calculate success rate for logging
        total = success_count + failure_count
        success_rate = success_count / total if total > 0 else 0.0

        logger.debug(
            "Updated domain Wayback success rate",
            domain=domain,
            success_rate=success_rate,
            success_count=success_count,
            failure_count=failure_count,
        )
