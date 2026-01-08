"""Browser fetcher for URL fetcher."""

import asyncio
import hashlib
import random
import time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from src.crawler.challenge_detector import (
    _detect_challenge_type,
    _estimate_auth_effort,
    _is_challenge_page,
)
from src.crawler.fetch_result import FetchResult
from src.crawler.http3_policy import (
    HTTP3RequestResult,
    ProtocolVersion,
    detect_protocol_from_playwright_response,
    get_http3_policy_manager,
)
from src.crawler.http_fetcher import RateLimiter
from src.crawler.human_behavior import get_human_behavior_simulator
from src.utils.config import get_settings
from src.utils.lifecycle import ResourceType, get_lifecycle_manager
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright, Route

logger = get_logger(__name__)


# Import utility functions from fetcher module
# These are imported at runtime to avoid circular dependency
# (fetcher.py imports BrowserFetcher, so we import utilities inside functions)


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
        # Return format: (position, delay_seconds)
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
        # Return format: (x, y) tuples
        return [(int(x), int(y)) for x, y, _ in path]

    async def simulate_reading(self, page: Page, content_length: int) -> None:
        """Simulate human reading behavior on page.

        Args:
            page: Playwright page object.
            content_length: Approximate content length.
        """
        try:
            await self._simulator.read_page(page, max_scrolls=5)
        except Exception as e:
            logger.debug("Reading simulation error", error=str(e))

    async def move_mouse_to_element(self, page: Page, selector: str) -> None:
        """Move mouse to element with human-like motion.

        Args:
            page: Playwright page object.
            selector: CSS selector for target element.
        """
        try:
            await self._simulator.move_to_element(page, selector)
        except Exception as e:
            logger.debug("Mouse movement error", error=str(e))


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

    async def _cleanup_stale_browser(self) -> None:
        """Cleanup stale browser references for reconnection.

        Called when browser.is_connected() returns False, indicating
        that Chrome was closed by user or crashed.
        """
        logger.info("Cleaning up stale browser for reconnection", worker_id=self._worker_id)

        try:
            if self._headful_context:
                await self._headful_context.close()
        except Exception:
            pass
        try:
            if self._headful_browser:
                await self._headful_browser.close()
        except Exception:
            pass
        try:
            if self._headless_context:
                await self._headless_context.close()
        except Exception:
            pass
        try:
            if self._headless_browser:
                await self._headless_browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass

        self._playwright = None
        self._headful_browser = None
        self._headful_context = None
        self._headless_browser = None
        self._headless_context = None

        logger.info("Stale browser cleaned up, ready for reconnection", worker_id=self._worker_id)

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

        # Check if existing browser connection is stale (user closed Chrome)
        if self._headful_browser is not None:
            try:
                is_connected = self._headful_browser.is_connected()
            except Exception:
                is_connected = False
            if not is_connected:
                logger.warning(
                    "Browser disconnected, cleaning up for reconnection",
                    worker_id=self._worker_id,
                )
                await self._cleanup_stale_browser()

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
                    # Pass timeout directly to connect_over_cdp
                    # asyncio.wait_for alone doesn't work for Playwright's internal blocking
                    self._headful_browser = await asyncio.wait_for(
                        self._playwright.chromium.connect_over_cdp(
                            cdp_url,
                            timeout=5000,  # 5 seconds in milliseconds (Playwright uses ms)
                        ),
                        timeout=6.0,  # Slightly longer asyncio timeout as safety net
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
                                # Pass timeout directly to connect_over_cdp
                                self._headful_browser = await asyncio.wait_for(
                                    self._playwright.chromium.connect_over_cdp(
                                        cdp_url,
                                        timeout=2000,  # 2 seconds in milliseconds
                                    ),
                                    timeout=3.0,  # Slightly longer asyncio timeout as safety net
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

                # Per ADR-0014 Phase 3: Each worker connects to its own Chrome instance
                # Each Chrome instance has its own profile, so reuse existing context
                # This preserves cookies and avoids creating incognito-like contexts
                if self._headful_browser is not None:
                    existing_contexts = self._headful_browser.contexts
                    if existing_contexts:
                        # Reuse the Chrome profile's default context (preserves cookies)
                        self._headful_context = existing_contexts[0]
                        logger.info(
                            "Reusing existing browser context for cookie preservation",
                            worker_id=self._worker_id,
                            context_count=len(existing_contexts),
                        )
                    else:
                        # Fallback: create new context if none exists
                        self._headful_context = await self._headful_browser.new_context(
                            viewport={
                                "width": browser_settings.viewport_width,
                                "height": browser_settings.viewport_height,
                            },
                            locale="ja-JP",
                            timezone_id="Asia/Tokyo",
                        )
                        logger.info(
                            "Created new browser context (no existing context found)",
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
        context: BrowserContext,
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

    async def _setup_blocking(self, context: BrowserContext) -> None:
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

        async def block_route(route: Route) -> None:
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
        from src.utils.intervention_queue import get_intervention_queue

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
                        from src.utils.intervention_queue import get_intervention_queue

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

            # Save content - import from fetcher to avoid circular dependency
            from src.crawler.fetcher import _save_content, _save_screenshot, _save_warc

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
