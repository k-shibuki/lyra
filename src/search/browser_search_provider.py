"""
Browser-based Search Provider for Lyra.

Implements direct browser-based search using Playwright
for improved resilience and session management.

Design Philosophy:
- Uses same browser profile as content fetching (consistent fingerprint)
- Supports CAPTCHA detection and InterventionManager integration
- Session cookies are preserved for subsequent searches
- Parsers are externalized for easy maintenance

References:
- ADR-0003 (Browser automation)
- ADR-0007 (Authentication queue)
- ADR-0006 (Stealth requirements)
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Playwright

from src.crawler.browser_fetcher import HumanBehavior
from src.search.circuit_breaker import check_engine_available, record_engine_result
from src.search.engine_config import get_engine_config_manager
from src.search.parsers import (
    get_available_parsers,
    get_parser,
)
from src.search.provider import (
    BaseSearchProvider,
    HealthState,
    HealthStatus,
    SearchProviderOptions,
    SearchResponse,
    SERPResult,
)
from src.search.search_api import transform_query_for_engine
from src.utils.config import get_settings
from src.utils.logging import get_logger
from src.utils.notification_provider import Platform, detect_platform
from src.utils.policy_engine import get_policy_engine
from src.utils.schemas import LastmileCheckResult

logger = get_logger(__name__)


# =============================================================================
# Exceptions
# =============================================================================


class CDPConnectionError(Exception):
    """
    Raised when CDP connection to Chrome fails.

    This indicates Chrome is not running with remote debugging enabled.
    Per spec (ADR-0006), headless fallback is not supported.
    """

    pass


# =============================================================================
# Chrome Auto-Start Lock (Race Condition Prevention)
# =============================================================================
# Prevents multiple workers from simultaneously calling chrome.sh start-worker,
# which could cause duplicate Chrome instances to be spawned.

_chrome_start_lock: asyncio.Lock | None = None


def _get_chrome_start_lock() -> asyncio.Lock:
    """Get or create the global Chrome start lock.

    Returns:
        asyncio.Lock instance for serializing Chrome auto-start calls.
    """
    global _chrome_start_lock
    if _chrome_start_lock is None:
        _chrome_start_lock = asyncio.Lock()
    return _chrome_start_lock


async def _check_cdp_available(host: str, port: int, timeout: float = 2.0) -> bool:
    """Check if Chrome CDP endpoint is available.

    Lightweight HTTP check without full Playwright initialization.

    Args:
        host: Chrome host (usually localhost).
        port: Chrome CDP port.
        timeout: Connection timeout in seconds.

    Returns:
        True if CDP is available, False otherwise.
    """
    import aiohttp

    cdp_url = f"http://{host}:{port}/json/version"
    try:
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.get(cdp_url) as response:
                return response.status == 200
    except Exception:
        return False


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class BrowserSearchSession:
    """Session data for browser-based search."""

    engine: str
    cookies: list[dict[str, Any]]
    last_used: float
    captcha_count: int = 0
    success_count: int = 0

    def is_fresh(self, max_age_seconds: float = 3600.0) -> bool:
        """Check if session is still fresh."""
        return (time.time() - self.last_used) < max_age_seconds

    def record_success(self) -> None:
        """Record successful search."""
        self.success_count += 1
        self.last_used = time.time()

    def record_captcha(self) -> None:
        """Record CAPTCHA encounter."""
        self.captcha_count += 1
        self.last_used = time.time()


# =============================================================================
# Browser Search Provider
# =============================================================================


class BrowserSearchProvider(BaseSearchProvider):
    """
    Browser-based search provider using Playwright.

    Executes searches directly in browser, maintaining consistent
    fingerprint and session across search and fetch stages.

    Features:
    - Direct browser search via Playwright
    - Cookie/fingerprint consistency
    - CAPTCHA detection and intervention queue integration
    - Session preservation across searches
    - Multiple search engine support (DuckDuckGo, Mojeek, etc.)

    Example:
        provider = BrowserSearchProvider()
        response = await provider.search("AI regulations", SearchProviderOptions(language="ja"))
        if response.ok:
            for result in response.results:
                print(result.title, result.url)
        await provider.close()
    """

    DEFAULT_ENGINE = "duckduckgo"
    DEFAULT_TIMEOUT = 30
    MIN_INTERVAL = 2.0  # Minimum seconds between searches

    def __init__(
        self,
        default_engine: str | None = None,
        timeout: int | None = None,
        min_interval: float | None = None,
        worker_id: int = 0,
    ):
        """
        Initialize browser search provider.

        Per ADR-0014 Phase 3: Each worker gets its own BrowserSearchProvider
        instance with isolated BrowserContext for true parallelization.

        Args:
            default_engine: Default search engine to use.
            timeout: Search timeout in seconds.
            min_interval: Minimum interval between searches.
            worker_id: Worker identifier (0 to num_workers-1).
                       Each worker gets its own isolated Context and TabPool.
        """
        super().__init__("browser_search")

        self._settings = get_settings()
        self._default_engine = default_engine or self.DEFAULT_ENGINE
        self._timeout = timeout or self.DEFAULT_TIMEOUT
        self._min_interval = min_interval or self.MIN_INTERVAL
        self._worker_id = worker_id

        # Browser state (lazy initialization)
        # Browser is shared across workers (single CDP connection)
        # Context is isolated per worker for cookie/state separation
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Any = None

        # Rate limiting (ADR-0014: Browser SERP Resource Control)
        # TabPool manages browser tabs; EngineRateLimiter enforces per-engine QPS
        from src.search.tab_pool import get_engine_rate_limiter, get_tab_pool

        # Each worker gets its own TabPool (ADR-0014 Phase 3)
        self._tab_pool = get_tab_pool(worker_id=worker_id)
        self._engine_rate_limiter = get_engine_rate_limiter()
        # Per-search serialization semaphore; ensures one search at a time within this provider
        self._rate_limiter = asyncio.Semaphore(1)
        self._last_search_times: dict[str, float] = {}  # Per-engine tracking

        # Session management
        self._sessions: dict[str, BrowserSearchSession] = {}

        # CDP connection state
        self._cdp_connected = False

        # Health metrics
        self._success_count = 0
        self._failure_count = 0
        self._captcha_count = 0
        self._total_latency = 0.0
        self._last_error: str | None = None

        # Human behavior simulation
        self._human_behavior = HumanBehavior()

        logger.debug(
            "BrowserSearchProvider initialized",
            worker_id=worker_id,
        )

    async def _ensure_browser(self) -> None:
        """
        Ensure browser is initialized via CDP connection.

        Per spec (ADR-0003, ADR-0006), CDP connection to real Chrome profile is required.
        Headless fallback is not supported as it violates the "real profile consistency" principle.

        Auto-starts Chrome via chrome.sh if not running (same behavior as BrowserFetcher).

        Raises:
            CDPConnectionError: If CDP connection fails after auto-start attempt.
        """
        # BUG-001a fix: Check if existing browser connection is stale
        if self._browser is not None:
            try:
                is_connected = self._browser.is_connected()
            except Exception:
                is_connected = False
            if not is_connected:
                logger.warning("Browser disconnected, cleaning up for reconnection...")
                await self._cleanup_stale_browser()

        if self._playwright is None:
            try:
                from playwright.async_api import async_playwright

                self._playwright = await async_playwright().start()
                assert self._playwright is not None  # Just initialized

                # CDP connection to Chrome (required, no fallback)
                # Dynamic Worker Pool: Each worker connects to its own Chrome instance
                from src.utils.config import get_chrome_port

                chrome_host = getattr(self._settings.browser, "chrome_host", "localhost")
                chrome_port = get_chrome_port(self._worker_id)
                cdp_url = f"http://{chrome_host}:{chrome_port}"

                cdp_connected = False
                cdp_error: Exception | None = None

                # First attempt to connect
                try:
                    # IMPORTANT: When CDP is down, Playwright's connect_over_cdp can hang.
                    # Pass timeout directly to connect_over_cdp (Playwright uses ms)
                    import asyncio

                    self._browser = await asyncio.wait_for(
                        self._playwright.chromium.connect_over_cdp(
                            cdp_url,
                            timeout=2000,  # 2 seconds in milliseconds
                        ),
                        timeout=3.0,  # Slightly longer asyncio timeout as safety net
                    )
                    cdp_connected = True
                    self._cdp_connected = True
                    logger.info("Connected to Chrome via CDP", url=cdp_url)
                except Exception as e:
                    logger.info("CDP connection failed, attempting auto-start", error=str(e))
                    cdp_error = e

                # Auto-start Chrome if CDP connection failed
                if not cdp_connected:
                    auto_start_success = await self._auto_start_chrome()

                    if auto_start_success:
                        # Wait for CDP connection with polling (max 15 seconds, 0.5s interval)
                        import asyncio
                        import time

                        start_time = time.monotonic()
                        timeout = 15.0
                        poll_interval = 0.5

                        while time.monotonic() - start_time < timeout:
                            try:
                                # Pass timeout directly to connect_over_cdp
                                self._browser = await asyncio.wait_for(
                                    self._playwright.chromium.connect_over_cdp(
                                        cdp_url,
                                        timeout=2000,  # 2 seconds in milliseconds
                                    ),
                                    timeout=3.0,  # Slightly longer asyncio timeout as safety net
                                )
                                cdp_connected = True
                                self._cdp_connected = True
                                logger.info(
                                    "Connected to Chrome via CDP after auto-start",
                                    url=cdp_url,
                                    elapsed=f"{time.monotonic() - start_time:.1f}s",
                                )
                                break
                            except Exception:
                                await asyncio.sleep(poll_interval)

                if not cdp_connected:
                    # CDP connection failed - do NOT fall back to headless
                    # Per spec: "real profile consistency" is required
                    self._cdp_connected = False
                    if self._playwright is not None:
                        await self._playwright.stop()
                        self._playwright = None

                    raise CDPConnectionError(
                        f"CDP connection failed: {cdp_error}. Start Chrome with: make chrome-start"
                    ) from cdp_error

                # Per ADR-0014 Phase 3: Each worker connects to its own Chrome instance (own CDP port).
                # Each Chrome instance is launched with a worker-specific --user-data-dir (see scripts/chrome.sh),
                # so the default context already provides worker-level cookie/session isolation.
                assert self._browser is not None  # Just connected
                existing_contexts = self._browser.contexts

                if existing_contexts:
                    # Reuse the Chrome profile's default context (preserves cookies).
                    # NOTE: Creating a new context under CDP creates an incognito-like context,
                    # which looks like "separate/secret" session to operators.
                    self._context = existing_contexts[0]
                    logger.info(
                        "Reusing existing browser context for cookie preservation",
                        worker_id=self._worker_id,
                        context_count=len(existing_contexts),
                    )
                else:
                    # Fallback: create new context if none exists (rare).
                    self._context = await self._browser.new_context(
                        viewport={"width": 1920, "height": 1080},
                        locale="ja-JP",
                        timezone_id="Asia/Tokyo",
                        user_agent=self._get_user_agent(),
                    )
                    logger.info(
                        "Created new browser context (no existing context found)",
                        worker_id=self._worker_id,
                        total_contexts=len(self._browser.contexts),
                    )

                # Block unnecessary resources
                assert self._context is not None  # Just created or reused
                await self._context.route(
                    "**/*.{png,jpg,jpeg,gif,svg,webp,mp4,webm,mp3,woff,woff2}",
                    lambda route: route.abort(),
                )

                # Perform profile health audit on browser session initialization
                # Only audit for worker 0 (avoids redundant audits)
                if self._worker_id == 0 and not existing_contexts:
                    await self._perform_health_audit()

            except CDPConnectionError:
                raise
            except Exception as e:
                logger.error("Failed to initialize browser", error=str(e))
                raise

    async def _cleanup_stale_browser(self) -> None:
        """Cleanup stale browser references for reconnection.

        Called when browser.is_connected() returns False, indicating
        that Chrome was closed by user or crashed.
        """
        # BUG-001a fix: Clear TabPool first (it holds stale tab references)
        try:
            await self._tab_pool.clear()
        except Exception as e:
            logger.debug("Failed to clear TabPool", error=str(e))

        try:
            if self._context:
                await self._context.close()
        except Exception:
            pass
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass

        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._cdp_connected = False

        logger.info("Stale browser cleaned up, ready for reconnection")

    def _get_user_agent(self) -> str:
        """Get user agent string matching the current platform's Chrome."""
        current_platform = detect_platform()
        if current_platform == Platform.LINUX:
            return (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        # WSL, Windows - use Windows user agent
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )

    async def _auto_start_chrome(self) -> bool:
        """Auto-start Chrome for this worker using chrome.sh script.

        When a CDP (Chrome DevTools Protocol) connection is not detected,
        Lyra automatically executes ./scripts/chrome.sh start-worker N to launch
        Chrome for the specific worker.

        Uses a global lock to prevent race conditions where multiple workers
        might simultaneously try to start Chrome instances.

        Returns:
            True if Chrome is ready (started or already running), False otherwise.
        """
        # #region agent log
        import json
        import time

        try:
            from pathlib import Path as _DbgPath

            from src.utils.config import get_chrome_port as _dbg_get_chrome_port

            _dbg_script_path = _DbgPath(__file__).parent.parent.parent / "scripts" / "chrome.sh"
            with open("/home/statuser/Projects/lyra/.cursor/debug.log", "a") as f:
                f.write(
                    json.dumps(
                        {
                            "sessionId": "debug-session",
                            "runId": "pre-fix",
                            "hypothesisId": "SERP-H1",
                            "location": "src/search/browser_search_provider.py:_auto_start_chrome:entry",
                            "message": "enter auto_start_chrome",
                            "data": {
                                "worker_id": self._worker_id,
                                "chrome_host": getattr(
                                    self._settings.browser, "chrome_host", "localhost"
                                ),
                                "chrome_port": _dbg_get_chrome_port(self._worker_id),
                                "script_exists": _dbg_script_path.exists(),
                            },
                            "timestamp": int(time.time() * 1000),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except Exception:
            pass
        # #endregion
        from pathlib import Path

        from src.utils.config import get_chrome_port

        # Find chrome.sh script relative to project root
        # src/search/browser_search_provider.py -> scripts/chrome.sh
        script_path = Path(__file__).parent.parent.parent / "scripts" / "chrome.sh"

        if not script_path.exists():
            logger.warning("chrome.sh not found", path=str(script_path))
            return False

        # Get Chrome connection info for this worker
        chrome_host = getattr(self._settings.browser, "chrome_host", "localhost")
        chrome_port = get_chrome_port(self._worker_id)

        # Acquire lock to prevent race conditions between workers
        lock = _get_chrome_start_lock()
        async with lock:
            # After acquiring lock, check if Chrome is already ready
            # (another worker may have started it while we were waiting)
            if await _check_cdp_available(chrome_host, chrome_port):
                # #region agent log
                import json
                import time

                try:
                    with open("/home/statuser/Projects/lyra/.cursor/debug.log", "a") as f:
                        f.write(
                            json.dumps(
                                {
                                    "sessionId": "debug-session",
                                    "runId": "pre-fix",
                                    "hypothesisId": "SERP-H1",
                                    "location": "src/search/browser_search_provider.py:_auto_start_chrome:already_available",
                                    "message": "cdp already available; skip auto-start",
                                    "data": {"worker_id": self._worker_id, "port": chrome_port},
                                    "timestamp": int(time.time() * 1000),
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                except Exception:
                    pass
                # #endregion
                logger.info(
                    "Chrome already available (started by another worker or mcp.sh)",
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

                # #region agent log
                import json
                import time

                try:
                    with open("/home/statuser/Projects/lyra/.cursor/debug.log", "a") as f:
                        f.write(
                            json.dumps(
                                {
                                    "sessionId": "debug-session",
                                    "runId": "pre-fix",
                                    "hypothesisId": "SERP-H1",
                                    "location": "src/search/browser_search_provider.py:_auto_start_chrome:subprocess_done",
                                    "message": "auto-start subprocess finished",
                                    "data": {
                                        "worker_id": self._worker_id,
                                        "returncode": process.returncode,
                                        "stdout_head": (stdout_text[:200] if stdout_text else ""),
                                        "stderr_head": (stderr_text[:200] if stderr_text else ""),
                                    },
                                    "timestamp": int(time.time() * 1000),
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                except Exception:
                    pass
                # #endregion

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

    async def _perform_health_audit(self) -> None:
        """Perform profile health audit on browser session initialization.

        Per high-frequency check requirement: Execute audit at browser session
        initialization to detect drift in UA, fonts, language, timezone, canvas, audio.
        """
        try:
            from src.crawler.profile_audit import AuditStatus, perform_health_check

            # Create temporary page for audit (minimal impact on performance)
            assert self._context is not None  # Guaranteed by caller
            page = await self._context.new_page()
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
                        drifts=[d.attribute for d in audit_result.drifts],
                        repair_status=audit_result.repair_status.value,
                    )
                elif audit_result.status == AuditStatus.FAIL:
                    logger.warning(
                        "Profile health audit failed",
                        error=audit_result.error,
                    )
                else:
                    logger.debug(
                        "Profile health check passed",
                        status=audit_result.status.value,
                    )
            finally:
                await page.close()
        except Exception as e:
            # Non-blocking: Log error but continue with normal flow
            logger.warning(
                "Profile health audit error (non-blocking)",
                error=str(e),
            )

    async def _get_page(self) -> Any:
        """Get or create a browser page."""
        await self._ensure_browser()
        assert self._context is not None  # Guaranteed by _ensure_browser

        if self._page is None or self._page.is_closed():
            self._page = await self._context.new_page()

        return self._page

    async def _rate_limit(self, engine: str | None = None) -> None:
        """Apply rate limiting between searches (per-engine QPS).

        Per spec ADR-0010: "Engine-specific rate control (concurrency=1, strict QPS)"
        Per spec ADR-0006: "Engine QPS≤0.25, concurrency=1"

        Args:
            engine: Engine name for per-engine rate limiting.
                   If None, uses default interval.
        """
        # Get engine-specific interval from config
        min_interval = self._min_interval  # Default fallback

        if engine:
            engine_config = get_engine_config_manager().get_engine(engine)
            if engine_config:
                min_interval = engine_config.min_interval

        async with self._rate_limiter:
            # Track per-engine last search time
            engine_key = engine or "default"
            last_time = self._last_search_times.get(engine_key, 0.0)

            elapsed = time.time() - last_time
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)

            self._last_search_times[engine_key] = time.time()

    def _detect_category(self, query: str) -> str:
        """Detect query category based on keywords.

        Simple keyword-based category detection. Categories:
        - academic: research papers, academic sources
        - news: current events, news articles
        - government: government sources, official documents
        - technical: technical documentation, code, APIs
        - general: default category

        Args:
            query: Search query text.

        Returns:
            Category name: "general", "academic", "news", "government", or "technical".
        """
        query_lower = query.lower()

        # Academic keywords
        academic_keywords = [
            "論文",
            "research",
            "study",
            "studies",
            "arxiv",
            "pubmed",
            "scholar",
            "academic",
            "journal",
            "publication",
            "paper",
            "dissertation",
            "thesis",
            "peer-reviewed",
            "peer reviewed",
        ]
        if any(keyword in query_lower for keyword in academic_keywords):
            return "academic"

        # News keywords
        news_keywords = [
            "ニュース",
            "news",
            "最新",
            "today",
            "recent",
            "breaking",
            "headline",
            "article",
            "report",
            "報道",
            "速報",
        ]
        if any(keyword in query_lower for keyword in news_keywords):
            return "news"

        # Government keywords
        government_keywords = [
            "政府",
            "government",
            "官公庁",
            ".gov",
            "official",
            "ministry",
            "department",
            "agency",
            "regulation",
            "law",
            "legal",
            "policy",
            "legislation",
            "法令",
            "条例",
        ]
        if any(keyword in query_lower for keyword in government_keywords):
            return "government"

        # Technical keywords
        technical_keywords = [
            "技術",
            "technical",
            "api",
            "code",
            "github",
            "documentation",
            "tutorial",
            "guide",
            "reference",
            "implementation",
            "algorithm",
            "programming",
            "software",
            "開発",
            "実装",
        ]
        if any(keyword in query_lower for keyword in technical_keywords):
            return "technical"

        # Default to general
        return "general"

    # =========================================================================
    # Lastmile Slot Selection (ADR-0010)
    # =========================================================================

    def _should_use_lastmile(
        self,
        harvest_rate: float,
        threshold: float = 0.9,
    ) -> LastmileCheckResult:
        """
        Check if lastmile engine should be used based on harvest rate.

        Per ADR-0010: "ラストマイル・スロット: 回収率の最後の10%を狙う限定枠として
        Google/Braveを最小限開放（厳格なQPS・回数・時間帯制御）"

        Args:
            harvest_rate: Current harvest rate (0.0-1.0).
            threshold: Threshold for lastmile activation (default 0.9).

        Returns:
            LastmileCheckResult with decision and reason.
        """
        if harvest_rate >= threshold:
            return LastmileCheckResult(
                should_use_lastmile=True,
                reason=f"Harvest rate {harvest_rate:.2f} >= threshold {threshold}",
                harvest_rate=harvest_rate,
                threshold=threshold,
            )
        return LastmileCheckResult(
            should_use_lastmile=False,
            reason=f"Harvest rate {harvest_rate:.2f} < threshold {threshold}",
            harvest_rate=harvest_rate,
            threshold=threshold,
        )

    async def _select_lastmile_engine(self) -> str | None:
        """
        Select a lastmile engine with strict QPS/daily limit checks.

        Per ADR-0010: Lastmile engines (Google/Brave/Bing) have strict limits:
        - Daily limits (google: 10, brave: 50, bing: 10)
        - Stricter QPS (google: 0.05, brave: 0.1, bing: 0.05)

        Returns:
            Engine name if available, None if all engines exhausted.
        """
        config_manager = get_engine_config_manager()
        lastmile_engines = config_manager.get_lastmile_engines()

        if not lastmile_engines:
            logger.debug("No lastmile engines configured")
            return None

        # Check each lastmile engine for availability
        for engine_name in lastmile_engines:
            try:
                # Check circuit breaker
                if not await check_engine_available(engine_name):
                    logger.debug(
                        "Lastmile engine unavailable (circuit breaker)",
                        engine=engine_name,
                    )
                    continue

                # Get engine config
                engine_config = config_manager.get_engine(engine_name)
                if not engine_config or not engine_config.is_available:
                    logger.debug(
                        "Lastmile engine not available",
                        engine=engine_name,
                    )
                    continue

                # Check daily limit
                if engine_config.daily_limit:
                    daily_usage = await self._get_daily_usage(engine_name)
                    if daily_usage >= engine_config.daily_limit:
                        logger.debug(
                            "Lastmile engine daily limit reached",
                            engine=engine_name,
                            daily_usage=daily_usage,
                            daily_limit=engine_config.daily_limit,
                        )
                        continue

                # Engine is available
                logger.info(
                    "Selected lastmile engine",
                    engine=engine_name,
                    daily_limit=engine_config.daily_limit,
                    qps=engine_config.qps,
                )
                return engine_name

            except Exception as e:
                logger.warning(
                    "Error checking lastmile engine",
                    engine=engine_name,
                    error=str(e),
                )
                continue

        logger.warning("No lastmile engines available")
        return None

    async def _get_daily_usage(self, engine: str) -> int:
        """
        Get today's usage count for an engine.

        Args:
            engine: Engine name.

        Returns:
            Number of searches today.
        """
        try:
            from datetime import date

            from src.storage.database import get_database

            db = await get_database()
            today = date.today().isoformat()

            result = await db.fetch_one(
                """
                SELECT usage_count FROM lastmile_usage
                WHERE engine = ? AND date = ?
                """,
                (engine, today),
            )

            return result["usage_count"] if result else 0
        except Exception as e:
            logger.debug(
                "Failed to get daily usage",
                engine=engine,
                error=str(e),
            )
            return 0

    async def _record_lastmile_usage(self, engine: str) -> None:
        """
        Record usage of a lastmile engine.

        Args:
            engine: Engine name.
        """
        try:
            from datetime import date

            from src.storage.database import get_database

            db = await get_database()
            today = date.today().isoformat()

            await db.execute(
                """
                INSERT INTO lastmile_usage (engine, date, usage_count)
                VALUES (?, ?, 1)
                ON CONFLICT(engine, date) DO UPDATE SET
                    usage_count = usage_count + 1
                """,
                (engine, today),
            )

            logger.debug(
                "Recorded lastmile usage",
                engine=engine,
                date=today,
            )
        except Exception as e:
            logger.warning(
                "Failed to record lastmile usage",
                engine=engine,
                error=str(e),
            )

    async def search(
        self,
        query: str,
        options: SearchProviderOptions | None = None,
        harvest_rate: float | None = None,
    ) -> SearchResponse:
        """
        Execute a search using browser.

        Args:
            query: Search query text.
            options: Search options.
            harvest_rate: Current harvest rate (0.0-1.0) for lastmile decision.
                         If provided and >= 0.9, lastmile engines may be used.

        Returns:
            SearchResponse with results or error.
        """
        self._check_closed()

        if options is None:
            options = SearchProviderOptions()

        start_time = time.time()

        # Category detection
        category = self._detect_category(query)

        # Check if lastmile engines should be used (ADR-0010)
        use_lastmile = False
        lastmile_engine: str | None = None

        if harvest_rate is not None:
            lastmile_check = self._should_use_lastmile(harvest_rate)
            if lastmile_check.should_use_lastmile:
                lastmile_engine = await self._select_lastmile_engine()
                if lastmile_engine:
                    use_lastmile = True
                    logger.info(
                        "Using lastmile engine",
                        engine=lastmile_engine,
                        harvest_rate=harvest_rate,
                        reason=lastmile_check.reason,
                    )

        # Engine selection with weighted selection and circuit breaker
        config_manager = get_engine_config_manager()

        # If lastmile engine selected, use it directly
        if use_lastmile and lastmile_engine:
            engine = lastmile_engine
            # Skip normal engine selection
        else:
            if options.engines:
                # Use specified engines
                candidate_engines = options.engines
            else:
                # Use default_engines from config as primary source
                # This ensures only engines with parsers are selected
                candidate_engines = config_manager.get_default_engines()
                if not candidate_engines:
                    # Fall back to category engines if no defaults configured
                    candidate_engines_configs = config_manager.get_engines_for_category(category)
                    if not candidate_engines_configs:
                        candidate_engines_configs = config_manager.get_available_engines()
                    candidate_engines = [cfg.name for cfg in candidate_engines_configs]

            # Filter to only engines with available parsers
            # This prevents selection of engines like arxiv, wikipedia, marginalia
            # that are defined in engines.yaml but don't have parsers implemented
            candidate_engines = config_manager.get_engines_with_parsers(candidate_engines)

            if not candidate_engines:
                logger.warning(
                    "No engines with parsers available",
                    category=category,
                    original_candidates=options.engines if options.engines else None,
                )
                return SearchResponse(
                    results=[],
                    query=query,
                    provider=self.name,
                    error="No engines with parsers available",
                    elapsed_ms=(time.time() - start_time) * 1000,
                    connection_mode="cdp" if self._cdp_connected else None,
                )

            # Filter by circuit breaker and availability
            # Use dynamic weights from PolicyEngine (per ADR-0010, ADR-0006)
            available_engines: list[tuple[str, float]] = []
            policy_engine = await get_policy_engine()

            for engine_name in candidate_engines:
                try:
                    _is_available = await check_engine_available(engine_name)
                    if _is_available:
                        engine_config = config_manager.get_engine(engine_name)
                        if engine_config and engine_config.is_available:
                            # Get dynamic weight with time decay
                            dynamic_weight = await policy_engine.get_dynamic_engine_weight(
                                engine_name, category
                            )
                            available_engines.append((engine_name, dynamic_weight))
                except Exception as e:
                    # Log error but continue with next engine
                    logger.warning(
                        "Failed to check engine availability",
                        engine=engine_name,
                        error=str(e),
                    )
                    continue

            # Check if any engines are available
            if not available_engines:
                logger.warning(
                    "No available engines",
                    category=category,
                    candidate_engines=candidate_engines,
                )
                return SearchResponse(
                    results=[],
                    query=query,
                    provider=self.name,
                    error="No available engines",
                    elapsed_ms=(time.time() - start_time) * 1000,
                    connection_mode="cdp" if self._cdp_connected else None,
                )

            # Weighted selection (sort by weight descending)
            available_engines.sort(key=lambda x: x[1], reverse=True)
            engine = available_engines[0][0]

            logger.debug(
                "Engine selected",
                engine=engine,
                category=category,
                weight=available_engines[0][1],
                available_count=len(available_engines),
            )

        try:
            await self._rate_limit(engine)

            # Get parser for engine
            parser = get_parser(engine)
            if parser is None:
                return SearchResponse(
                    results=[],
                    query=query,
                    provider=self.name,
                    error=f"No parser available for engine: {engine}",
                    elapsed_ms=(time.time() - start_time) * 1000,
                    connection_mode="cdp" if self._cdp_connected else None,
                )

            # Normalize query operators for the selected engine (ADR-0006)
            normalized_query = transform_query_for_engine(query, engine)

            # Log if query was transformed
            if normalized_query != query:
                logger.debug(
                    "Query operators normalized",
                    original=query[:50] if query else "",
                    normalized=normalized_query[:50] if normalized_query else "",
                    engine=engine,
                )

            # Initialize pagination for multi-page SERP results
            # See ADR-0010 and ADR-0014 for pagination strategy design
            from src.search.pagination_strategy import (
                PaginationConfig,
                PaginationContext,
                PaginationStrategy,
            )

            pagination_config = PaginationConfig(
                serp_max_pages=options.serp_max_pages,
                min_novelty_rate=0.1,
                min_harvest_rate=0.05,
                strategy="auto",
            )
            pagination_strategy = PaginationStrategy(pagination_config)

            # Pagination state
            all_results: list[SERPResult] = []
            seen_urls: set[str] = set()
            current_page = options.serp_page
            max_page = options.serp_page + options.serp_max_pages - 1

            # Execute search with TabPool (ADR-0014) and EngineRateLimiter
            await self._ensure_browser()
            assert self._context is not None  # Guaranteed by _ensure_browser

            # Acquire per-engine rate limit slot (held for entire pagination loop)
            await self._engine_rate_limiter.acquire(engine)
            try:
                # Pagination loop: fetch pages until max or stop condition
                while current_page <= max_page:
                    # Build search URL for current page
                    search_url = parser.build_search_url(
                        query=normalized_query,
                        time_range=options.time_range,
                        serp_page=current_page,
                    )

                    logger.debug(
                        "Browser search (pagination)",
                        engine=engine,
                        query=normalized_query[:50] if normalized_query else "",
                        serp_page=current_page,
                        url=search_url[:100],
                    )

                    # Acquire a tab from the pool (prevents Page sharing)
                    tab = await self._tab_pool.acquire(self._context)
                    tab_held = False  # Track if tab was held for CAPTCHA (ADR-0007)
                    try:
                        # Navigate to search page
                        await tab.goto(
                            search_url,
                            timeout=self._timeout * 1000,
                            wait_until="domcontentloaded",
                        )

                        # Wait for content to load (with fallback for JS-heavy sites)
                        try:
                            await tab.wait_for_load_state("networkidle", timeout=5000)
                        except Exception:
                            # Some engines (e.g., Brave) have constant JS activity
                            await asyncio.sleep(2)

                        # Get HTML content
                        html = await tab.content()

                        # Apply human-like behavior to search results page
                        try:
                            await self._human_behavior.simulate_reading(
                                tab, len(html.encode("utf-8"))
                            )
                            try:
                                result_links = await tab.query_selector_all(
                                    "a[href*='http'], a[href*='https']"
                                )
                                if result_links:
                                    target_link = random.choice(result_links[:5])
                                    link_selector = await target_link.evaluate(
                                        """
                                        (el) => {
                                            if (el.id) return `#${el.id}`;
                                            if (el.className) {
                                                const classes = el.className.split(' ').filter(c => c).join('.');
                                                if (classes) return `a.${classes}`;
                                            }
                                            return 'a';
                                        }
                                    """
                                    )
                                    if link_selector:
                                        await self._human_behavior.move_mouse_to_element(
                                            tab, link_selector
                                        )
                            except Exception as e:
                                logger.debug("Mouse movement skipped", error=str(e))
                        except Exception as e:
                            logger.debug("Human behavior skipped", error=str(e))

                        # Parse results
                        parse_result = parser.parse(html, query)

                        # Handle CAPTCHA on current page (ADR-0007)
                        queue_id = None
                        captcha_queued = False
                        if parse_result.is_captcha:
                            self._captcha_count += 1
                            self._record_session_captcha(engine)
                            self._tab_pool.report_captcha()

                            try:
                                await record_engine_result(
                                    engine=engine,
                                    success=False,
                                    latency_ms=(time.time() - start_time) * 1000,
                                    is_captcha=True,
                                )
                            except Exception as e:
                                logger.warning(
                                    "Failed to record engine result",
                                    engine=engine,
                                    error=str(e),
                                )

                            # Queue CAPTCHA for batch processing (ADR-0007)
                            if options.task_id:
                                try:
                                    from src.utils.intervention_queue import (
                                        get_intervention_queue,
                                    )

                                    queue = get_intervention_queue()
                                    queue_id = await queue.enqueue(
                                        task_id=options.task_id,
                                        url=search_url,
                                        domain=engine,
                                        auth_type=parse_result.captcha_type or "captcha",
                                        priority="medium",
                                        search_job_id=options.search_job_id,
                                    )
                                    captcha_queued = True
                                    logger.info(
                                        "CAPTCHA queued for intervention",
                                        queue_id=queue_id,
                                        engine=engine,
                                    )

                                    # Hold tab for CAPTCHA resolution (ADR-0007)
                                    # Tab will be auto-released when CAPTCHA is resolved
                                    # or expires (default: 3 hours)
                                    expires_at = time.time() + 3 * 3600
                                    self._tab_pool.hold_for_captcha(
                                        tab=tab,
                                        queue_id=queue_id,
                                        engine=engine,
                                        task_id=options.task_id,
                                        expires_at=expires_at,
                                    )
                                    tab_held = True
                                except Exception as e:
                                    logger.warning(
                                        "Failed to queue CAPTCHA",
                                        engine=engine,
                                        error=str(e),
                                    )
                    finally:
                        # Release tab back to pool unless held for CAPTCHA (ADR-0007)
                        if not tab_held:
                            self._tab_pool.release(tab)

                    # Return CAPTCHA response
                    if parse_result.is_captcha:
                        # Return partial results if we have any
                        if all_results:
                            logger.info(
                                "CAPTCHA during pagination, returning partial results",
                                engine=engine,
                                pages_fetched=current_page - options.serp_page,
                                result_count=len(all_results),
                            )
                            return SearchResponse(
                                results=all_results[: options.limit],
                                query=query,
                                provider=self.name,
                                total_count=len(all_results),
                                elapsed_ms=(time.time() - start_time) * 1000,
                                connection_mode="cdp",
                                captcha_queued=captcha_queued,
                                queue_id=queue_id,
                            )
                        # No results yet
                        return SearchResponse(
                            results=[],
                            query=query,
                            provider=self.name,
                            error=f"CAPTCHA detected: {parse_result.captcha_type}",
                            elapsed_ms=(time.time() - start_time) * 1000,
                            connection_mode="cdp",
                            captcha_queued=captcha_queued,
                            queue_id=queue_id,
                        )

                    # Handle parse failure on current page
                    if not parse_result.ok:
                        logger.warning(
                            "Parse failed on page",
                            engine=engine,
                            serp_page=current_page,
                            error=parse_result.error,
                        )
                        # If first page fails with no results, return error
                        if current_page == options.serp_page and not all_results:
                            self._failure_count += 1
                            self._last_error = parse_result.error

                            error_msg = parse_result.error or "Parse failed"
                            if parse_result.selector_errors:
                                error_msg += (
                                    f" ({len(parse_result.selector_errors)} selector errors)"
                                )
                            if parse_result.html_saved_path:
                                error_msg += f" [HTML saved: {parse_result.html_saved_path}]"

                            try:
                                await record_engine_result(
                                    engine=engine,
                                    success=False,
                                    latency_ms=(time.time() - start_time) * 1000,
                                    is_captcha=False,
                                )
                            except Exception as e:
                                logger.warning(
                                    "Failed to record engine result",
                                    engine=engine,
                                    error=str(e),
                                )

                            return SearchResponse(
                                results=[],
                                query=query,
                                provider=self.name,
                                error=error_msg,
                                elapsed_ms=(time.time() - start_time) * 1000,
                                connection_mode="cdp",
                            )
                        # Otherwise stop pagination, return partial results
                        break

                    # Merge results: deduplicate by URL.
                    # current_page is recorded into SERPResult.page_number (and persisted to DB) for audit/reproducibility.
                    page_results = [
                        r.to_search_result(engine, serp_page=current_page)
                        for r in parse_result.results
                    ]
                    new_urls = [r.url for r in page_results]

                    # Calculate novelty rate before merging
                    novelty_rate = pagination_strategy.calculate_novelty_rate(new_urls, seen_urls)

                    # Add only new (unseen) results
                    for result in page_results:
                        if result.url not in seen_urls:
                            seen_urls.add(result.url)
                            all_results.append(result)

                    logger.debug(
                        "Page results merged",
                        engine=engine,
                        serp_page=current_page,
                        page_results=len(page_results),
                        new_results=len([u for u in new_urls if u not in seen_urls]),
                        total_results=len(all_results),
                        novelty_rate=round(novelty_rate, 3),
                    )

                    # Check stop condition (auto strategy).
                    # harvest_rate is passed from the caller to influence pagination decision.
                    context = PaginationContext(
                        current_page=current_page,
                        novelty_rate=novelty_rate,
                        harvest_rate=harvest_rate,
                    )

                    if not pagination_strategy.should_fetch_next(context):
                        logger.info(
                            "Pagination stopped by strategy",
                            engine=engine,
                            serp_page=current_page,
                            novelty_rate=round(novelty_rate, 3),
                            total_results=len(all_results),
                        )
                        break

                    # Move to next page
                    current_page += 1

                    # Add delay between pages to avoid rate limiting
                    if current_page <= max_page:
                        await asyncio.sleep(1.0)

            finally:
                # Always release engine rate limit slot
                self._engine_rate_limiter.release(engine)

            elapsed_ms = (time.time() - start_time) * 1000

            # Limit results to requested limit
            results = all_results[: options.limit]

            # Save session cookies (uses context, not tab)
            await self._save_session(engine)

            self._success_count += 1
            self._total_latency += elapsed_ms

            logger.info(
                "Browser search completed",
                engine=engine,
                query=query[:50],
                result_count=len(results),
                pages_fetched=current_page - options.serp_page + 1,
                elapsed_ms=round(elapsed_ms, 1),
            )

            # Record engine health (success)
            try:
                await record_engine_result(
                    engine=engine,
                    success=True,
                    latency_ms=elapsed_ms,
                )
            except Exception as e:
                logger.warning(
                    "Failed to record engine result",
                    engine=engine,
                    error=str(e),
                )

            # Record lastmile usage if lastmile engine was used
            if use_lastmile and lastmile_engine:
                await self._record_lastmile_usage(lastmile_engine)

            return SearchResponse(
                results=results,
                query=query,
                provider=self.name,
                total_count=len(all_results),
                elapsed_ms=elapsed_ms,
                connection_mode="cdp",
            )

        except CDPConnectionError as e:
            # CDP connection failed - Chrome not running with remote debugging
            self._failure_count += 1
            self._last_error = str(e)
            elapsed_ms = (time.time() - start_time) * 1000

            logger.error(
                "CDP connection failed",
                error=str(e),
            )

            return SearchResponse(
                results=[],
                query=query,
                provider=self.name,
                error=str(e),
                elapsed_ms=elapsed_ms,
                connection_mode=None,
            )

        except TimeoutError:
            self._failure_count += 1
            self._last_error = "Timeout"
            elapsed_ms = (time.time() - start_time) * 1000

            logger.error("Browser search timeout", engine=engine, query=query[:50])

            return SearchResponse(
                results=[],
                query=query,
                provider=self.name,
                error="Timeout",
                elapsed_ms=elapsed_ms,
                connection_mode="cdp" if self._cdp_connected else None,
            )

        except Exception as e:
            self._failure_count += 1
            self._last_error = str(e)
            elapsed_ms = (time.time() - start_time) * 1000

            logger.error(
                "Browser search error",
                engine=engine,
                query=query[:50],
                error=str(e),
            )

            # BUG-001a fix: Detect browser disconnection errors and reset state
            error_str = str(e).lower()
            if (
                "browser has been closed" in error_str
                or "target closed" in error_str
                or "context or browser" in error_str
            ):
                logger.warning("Browser disconnect detected, will reconnect on next search")
                # Reset state so next _ensure_browser() will reconnect
                self._playwright = None
                self._browser = None
                self._context = None
                self._page = None
                self._cdp_connected = False

            return SearchResponse(
                results=[],
                query=query,
                provider=self.name,
                error=str(e),
                elapsed_ms=elapsed_ms,
                connection_mode="cdp" if self._cdp_connected else None,
            )

    async def _request_intervention(
        self,
        url: str,
        engine: str,
        captcha_type: str | None,
        page: Any,
    ) -> bool:
        """
        Request manual intervention for CAPTCHA.

        Returns True if intervention succeeded.
        """
        try:
            from src.utils.intervention_manager import get_intervention_manager
            from src.utils.intervention_types import InterventionStatus, InterventionType

            intervention_manager = get_intervention_manager()

            # Map captcha type to intervention type
            type_map = {
                "recaptcha": InterventionType.CAPTCHA,
                "turnstile": InterventionType.TURNSTILE,
                "ddg_challenge": InterventionType.JS_CHALLENGE,
                "verification": InterventionType.CAPTCHA,
                "rate_limit": InterventionType.CLOUDFLARE,
                "blocked": InterventionType.CLOUDFLARE,
            }

            intervention_type = type_map.get(
                captcha_type or "",
                InterventionType.CAPTCHA,
            )

            # Request intervention
            result = await intervention_manager.request_intervention(
                intervention_type=intervention_type,
                url=url,
                domain=engine,
                message=f"CAPTCHA detected on {engine} search",
                page=page,
            )

            # Check if resolved
            return result.status == InterventionStatus.SUCCESS

        except ImportError:
            logger.warning("InterventionManager not available")
            return False
        except Exception as e:
            logger.error("Intervention request failed", error=str(e))
            return False

    async def _save_session(self, engine: str) -> None:
        """Save session cookies for engine.

        Note: Uses self._context to get cookies. Tab is not needed because
        cookies are stored at the context level.
        """
        if self._context is None:
            return  # No context to save from
        try:
            cookies = await self._context.cookies()

            self._sessions[engine] = BrowserSearchSession(
                engine=engine,
                cookies=[dict(c) for c in cookies],
                last_used=time.time(),
            )
            self._sessions[engine].record_success()

        except Exception as e:
            logger.debug("Failed to save session", error=str(e))

    def _record_session_captcha(self, engine: str) -> None:
        """Record CAPTCHA for engine session."""
        if engine in self._sessions:
            self._sessions[engine].record_captcha()

    def get_session(self, engine: str) -> BrowserSearchSession | None:
        """Get session for engine."""
        session = self._sessions.get(engine)
        if session and session.is_fresh():
            return session
        return None

    async def get_health(self) -> HealthStatus:
        """
        Get current health status.

        Returns:
            HealthStatus based on recent metrics.
        """
        if self._is_closed:
            return HealthStatus.unhealthy("Provider closed")

        total = self._success_count + self._failure_count

        if total == 0:
            return HealthStatus(
                state=HealthState.UNKNOWN,
                message="No searches made yet",
            )

        success_rate = self._success_count / total
        avg_latency = self._total_latency / total if total > 0 else 0

        # Factor in CAPTCHA rate
        captcha_rate = self._captcha_count / total if total > 0 else 0

        if success_rate >= 0.9 and captcha_rate < 0.1:
            return HealthStatus.healthy(latency_ms=avg_latency)
        elif success_rate >= 0.5:
            message = self._last_error
            if captcha_rate >= 0.2:
                message = f"High CAPTCHA rate: {captcha_rate:.0%}"
            return HealthStatus.degraded(
                success_rate=success_rate,
                message=message,
            )
        else:
            return HealthStatus.unhealthy(message=self._last_error)

    async def close(self) -> None:
        """Close browser and cleanup."""
        try:
            if self._page and not self._page.is_closed():
                await self._page.close()

            if self._context:
                await self._context.close()

            if self._browser:
                await self._browser.close()

            if self._playwright:
                await self._playwright.stop()

        except Exception as e:
            logger.warning("Error during browser cleanup", error=str(e))
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None

        await super().close()

    def reset_metrics(self) -> None:
        """Reset health metrics. For testing purposes."""
        self._success_count = 0
        self._failure_count = 0
        self._captcha_count = 0
        self._total_latency = 0.0
        self._last_error = None

    def get_available_engines(self) -> list[str]:
        """Get list of available search engines."""
        return get_available_parsers()

    def get_stats(self) -> dict[str, Any]:
        """Get provider statistics."""
        total = self._success_count + self._failure_count
        return {
            "provider": self.name,
            "default_engine": self._default_engine,
            "available_engines": self.get_available_engines(),
            "success_count": self._success_count,
            "failure_count": self._failure_count,
            "captcha_count": self._captcha_count,
            "success_rate": self._success_count / total if total > 0 else 0,
            "captcha_rate": self._captcha_count / total if total > 0 else 0,
            "avg_latency_ms": self._total_latency / total if total > 0 else 0,
            "active_sessions": len(self._sessions),
            "last_error": self._last_error,
        }


# =============================================================================
# Factory Functions
# =============================================================================


# Worker ID -> BrowserSearchProvider mapping (ADR-0014 Phase 3)
_providers: dict[int, BrowserSearchProvider] = {}


def get_browser_search_provider(worker_id: int = 0) -> BrowserSearchProvider:
    """
    Get or create a BrowserSearchProvider instance for a specific worker.

    Per ADR-0014 Phase 3: Each worker gets its own isolated provider
    with separate BrowserContext for true parallelization.

    Args:
        worker_id: Worker identifier (0 to num_workers-1).
                   Each worker gets its own isolated provider.

    Returns:
        BrowserSearchProvider instance for the specified worker.
    """
    if worker_id not in _providers:
        _providers[worker_id] = BrowserSearchProvider(worker_id=worker_id)
        logger.info(
            "Created BrowserSearchProvider for worker",
            worker_id=worker_id,
            total_providers=len(_providers),
        )
    return _providers[worker_id]


async def cleanup_browser_search_provider(worker_id: int | None = None) -> None:
    """
    Close and cleanup BrowserSearchProvider(s).

    Args:
        worker_id: If specified, cleanup only that worker's provider.
                   If None, cleanup all providers.

    Used for testing cleanup and graceful shutdown.
    """
    global _providers
    if worker_id is not None:
        # Cleanup specific worker's provider
        if worker_id in _providers:
            await _providers[worker_id].close()
            del _providers[worker_id]
            logger.debug("Cleaned up BrowserSearchProvider", worker_id=worker_id)
    else:
        # Cleanup all providers
        for _wid, provider in list(_providers.items()):
            await provider.close()
        _providers.clear()
        logger.debug("Cleaned up all BrowserSearchProviders")


def reset_browser_search_provider(worker_id: int | None = None) -> None:
    """
    Reset provider(s). For testing purposes only.

    Args:
        worker_id: If specified, reset only that worker's provider.
                   If None, reset all providers.
    """
    global _providers
    if worker_id is not None:
        if worker_id in _providers:
            del _providers[worker_id]
    else:
        _providers.clear()
