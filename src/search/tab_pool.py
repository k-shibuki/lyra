"""
Tab pool for browser-based SERP fetching.

Per ADR-0014: Browser SERP Resource Control.
Per ADR-0014: Adaptive Concurrency Control (auto-backoff on CAPTCHA/403).

Design:
- Manages a pool of browser tabs (Page objects) for parallel SERP fetching
- Prevents simultaneous operations on the same Page
- Supports configurable max_tabs for gradual parallelization
- Default max_tabs=1 ensures correctness (no Page contention)
- Auto-backoff: reduces effective_max_tabs on CAPTCHA/403 (no auto-increase per ADR-0014)
- Increase max_tabs for parallelization after stability validation
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.utils.logging import get_logger

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page

logger = get_logger(__name__)


@dataclass
class TabPoolBackoffState:
    """Tracks backoff state for TabPool (ADR-0014)."""

    effective_max_tabs: int = 1  # Current effective limit (may be < config max)
    config_max_tabs: int = 1  # Original config limit (upper bound)
    last_captcha_time: float = 0.0  # Timestamp of last CAPTCHA detection
    last_403_time: float = 0.0  # Timestamp of last 403 error
    backoff_active: bool = False  # Whether backoff is currently active
    captcha_count: int = 0  # Total CAPTCHA count since last reset
    error_403_count: int = 0  # Total 403 count since last reset


@dataclass
class HeldTab:
    """Tab held for CAPTCHA resolution (ADR-0007).

    When a CAPTCHA is detected during SERP search, the tab is held
    instead of being released to the pool. This allows:
    1. User to solve CAPTCHA in the browser
    2. Background check to detect resolution
    3. Auto-release on resolution/expiry
    """

    tab: Page
    queue_id: str  # InterventionQueue item ID
    engine: str  # Search engine name (for CircuitBreaker reset)
    task_id: str  # Task ID (for filtering on stop_task)
    held_at: float  # Timestamp when tab was held
    expires_at: float  # Timestamp when tab should be force-released


class TabPool:
    """Manages browser tabs for parallel SERP fetching.

    Prevents Page sharing between concurrent operations per ADR-0014.
    Each search operation borrows a tab, uses it exclusively, then returns it.
    Implements auto-backoff on CAPTCHA/403 (ADR-0014).

    Example:
        pool = TabPool(max_tabs=1)
        tab = await pool.acquire(context)
        try:
            await tab.goto(url)
            # ... search operations ...
        except CaptchaError:
            pool.report_captcha()  # Triggers backoff
            raise
        finally:
            pool.release(tab)

    Args:
        max_tabs: Maximum number of concurrent tabs. Start with 1 for safety.
        acquire_timeout: Timeout in seconds for acquiring a tab.
    """

    def __init__(self, max_tabs: int = 1, acquire_timeout: float = 60.0) -> None:
        """Initialize tab pool.

        Args:
            max_tabs: Maximum concurrent tabs. Start with 1 for correctness,
                     increase after stability validation.
            acquire_timeout: Timeout for tab acquisition in seconds.
        """
        if max_tabs < 1:
            raise ValueError("max_tabs must be at least 1")

        self._max_tabs = max_tabs
        self._acquire_timeout = acquire_timeout

        # Backoff state (ADR-0014)
        self._backoff_state = TabPoolBackoffState(
            effective_max_tabs=max_tabs,
            config_max_tabs=max_tabs,
        )

        # Semaphore controls how many tabs can be acquired simultaneously
        # Note: Uses config max_tabs; backoff is enforced via _active_count
        self._semaphore = asyncio.Semaphore(max_tabs)

        # Active count for backoff enforcement
        self._active_count = 0
        # Event to signal when a slot becomes available
        self._slot_available = asyncio.Event()
        self._slot_available.set()  # Initially available

        # Track created tabs for cleanup
        self._tabs: list[Page] = []
        self._available_tabs: asyncio.Queue[Page] = asyncio.Queue()

        # Lock for tab creation/cleanup
        self._lock = asyncio.Lock()

        # Track if pool is closed
        self._closed = False

        # Held tabs for CAPTCHA resolution (ADR-0007)
        self._held_tabs: dict[str, HeldTab] = {}  # queue_id -> HeldTab
        self._held_tabs_check_task: asyncio.Task[None] | None = None
        self._held_tabs_check_interval: float = 10.0  # Check every 10 seconds

        logger.debug("TabPool initialized", max_tabs=max_tabs)

    async def acquire(self, context: BrowserContext) -> Page:
        """Acquire a tab from the pool.

        Blocks until a tab is available or creates a new one if under effective_max_tabs.
        Respects backoff state (ADR-0014).

        Args:
            context: Browser context to create new tabs in.

        Returns:
            A Page object for exclusive use.

        Raises:
            RuntimeError: If pool is closed.
            TimeoutError: If acquire_timeout is exceeded.
        """
        if self._closed:
            raise RuntimeError("TabPool is closed")

        # Wait for backoff slot if necessary (ADR-0014)
        start_time = time.time()
        poll_interval = 0.1  # Check every 100ms

        while True:
            if self._active_count < self._backoff_state.effective_max_tabs:
                self._active_count += 1
                break

            # Check timeout
            elapsed = time.time() - start_time
            if elapsed >= self._acquire_timeout:
                raise TimeoutError(
                    f"Failed to acquire tab within {self._acquire_timeout}s "
                    f"(backoff: effective_max_tabs={self._backoff_state.effective_max_tabs})"
                )

            logger.debug(
                "Backoff limiting: waiting for tab slot",
                active=self._active_count,
                effective_max=self._backoff_state.effective_max_tabs,
            )

            # Wait for slot to become available or timeout
            self._slot_available.clear()
            try:
                await asyncio.wait_for(
                    self._slot_available.wait(),
                    timeout=min(poll_interval, self._acquire_timeout - elapsed),
                )
            except TimeoutError:
                # Continue polling
                pass

        # Try to get an existing available tab
        try:
            tab = self._available_tabs.get_nowait()
            logger.debug("Reusing existing tab", tabs_count=len(self._tabs))
            return tab
        except asyncio.QueueEmpty:
            pass

        # Create a new tab
        async with self._lock:
            if len(self._tabs) < self._backoff_state.effective_max_tabs:
                tab = await context.new_page()
                self._tabs.append(tab)
                logger.debug("Created new tab", tabs_count=len(self._tabs))
                return tab

        # Wait for an available tab from the queue
        try:
            remaining = self._acquire_timeout - (time.time() - start_time)
            tab = await asyncio.wait_for(
                self._available_tabs.get(),
                timeout=max(0.1, remaining),
            )
            return tab
        except TimeoutError as e:
            # Release the backoff slot
            self._active_count -= 1
            self._slot_available.set()
            raise TimeoutError("No tab available after waiting") from e

    def release(self, tab: Page) -> None:
        """Release a tab back to the pool.

        Must be called after acquire() completes, typically in a finally block.

        Args:
            tab: The Page to release.
        """
        if self._closed:
            # Pool is closed, don't return tab
            return

        # Return tab to available queue
        try:
            self._available_tabs.put_nowait(tab)
        except asyncio.QueueFull:
            # Should never happen, but log if it does
            logger.warning("Available tabs queue full, tab not returned")

        # Release backoff slot (ADR-0014)
        if self._active_count > 0:
            self._active_count -= 1
        self._slot_available.set()  # Signal that a slot is available

        logger.debug("Tab released", available=self._available_tabs.qsize())

    def hold_for_captcha(
        self,
        tab: Page,
        queue_id: str,
        engine: str,
        task_id: str,
        expires_at: float,
    ) -> None:
        """Hold a tab for CAPTCHA resolution (ADR-0007).

        Instead of releasing the tab to the pool, hold it so the user can
        solve the CAPTCHA in the browser. A background task will check
        periodically if the CAPTCHA has been resolved.

        Args:
            tab: The Page to hold.
            queue_id: InterventionQueue item ID.
            engine: Search engine name (for CircuitBreaker reset).
            task_id: Task ID (for filtering on stop_task).
            expires_at: Unix timestamp when to force-release.
        """
        if self._closed:
            return

        held = HeldTab(
            tab=tab,
            queue_id=queue_id,
            engine=engine,
            task_id=task_id,
            held_at=time.time(),
            expires_at=expires_at,
        )
        self._held_tabs[queue_id] = held

        # Release backoff slot but don't return tab to pool
        if self._active_count > 0:
            self._active_count -= 1
        self._slot_available.set()

        logger.info(
            "Tab held for CAPTCHA resolution",
            queue_id=queue_id,
            engine=engine,
            task_id=task_id,
            held_count=len(self._held_tabs),
        )

        # Start background check if not running
        if self._held_tabs_check_task is None or self._held_tabs_check_task.done():
            self._held_tabs_check_task = asyncio.create_task(
                self._check_held_tabs_loop(),
                name="tab_pool_held_tabs_check",
            )

    async def _check_held_tabs_loop(self) -> None:
        """Periodically check if held tabs' CAPTCHAs are resolved (ADR-0007)."""
        try:
            while self._held_tabs and not self._closed:
                await asyncio.sleep(self._held_tabs_check_interval)
                await self._check_all_held_tabs()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("Held tabs check loop error", error=str(e))

    async def _check_all_held_tabs(self) -> None:
        """Check all held tabs for CAPTCHA resolution or expiry."""
        from src.crawler.challenge_detector import _is_challenge_page

        to_release: list[tuple[str, str]] = []  # (queue_id, reason)

        for queue_id, held in list(self._held_tabs.items()):
            # Check timeout
            if time.time() > held.expires_at:
                to_release.append((queue_id, "expired"))
                continue

            # Check if CAPTCHA resolved
            try:
                if held.tab.is_closed():
                    to_release.append((queue_id, "tab_closed"))
                    continue

                content = await held.tab.content()
                if not _is_challenge_page(content, {}):
                    to_release.append((queue_id, "resolved"))
            except Exception as e:
                logger.debug(
                    "Held tab check failed",
                    queue_id=queue_id,
                    error=str(e),
                )
                to_release.append((queue_id, "error"))

        # Release resolved/expired tabs
        for queue_id, reason in to_release:
            await self._release_held_tab(queue_id, reason)

    async def _release_held_tab(self, queue_id: str, reason: str) -> None:
        """Release a held tab back to pool (ADR-0007).

        Args:
            queue_id: InterventionQueue item ID.
            reason: Why the tab is being released (resolved/expired/error/manual).
        """
        if queue_id not in self._held_tabs:
            return

        held = self._held_tabs.pop(queue_id)

        logger.info(
            "Releasing held tab",
            queue_id=queue_id,
            engine=held.engine,
            reason=reason,
            held_duration_s=round(time.time() - held.held_at, 1),
        )

        if reason == "resolved":
            # Capture session cookies before releasing (ADR-0007)
            session_data = None
            try:
                from src.mcp.tools.auth import capture_auth_session_cookies

                session_data = await capture_auth_session_cookies(held.engine)
                if session_data:
                    logger.info(
                        "Auto-captured session cookies on CAPTCHA resolution",
                        engine=held.engine,
                        cookie_count=len(session_data.get("cookies", [])),
                    )
            except Exception as e:
                logger.debug(
                    "Failed to capture session cookies (non-critical)",
                    engine=held.engine,
                    error=str(e),
                )

            # Reset circuit breaker for this engine
            try:
                from src.mcp.tools.auth import reset_circuit_breaker_for_engine

                await reset_circuit_breaker_for_engine(held.engine)
            except Exception as e:
                logger.warning(
                    "Failed to reset circuit breaker",
                    engine=held.engine,
                    error=str(e),
                )

            # Requeue awaiting_auth jobs (same as resolve_auth flow)
            try:
                from src.mcp.tools.auth import requeue_awaiting_auth_jobs

                requeued = await requeue_awaiting_auth_jobs(held.engine)
                if requeued > 0:
                    logger.info(
                        "Auto-requeued awaiting_auth jobs on CAPTCHA resolution",
                        engine=held.engine,
                        requeued_count=requeued,
                    )
            except Exception as e:
                logger.warning(
                    "Failed to requeue awaiting_auth jobs",
                    engine=held.engine,
                    error=str(e),
                )

            # Mark intervention queue item as completed with session data
            try:
                from src.utils.intervention_queue import get_intervention_queue

                queue = get_intervention_queue()
                await queue.complete(queue_id, success=True, session_data=session_data)
            except Exception as e:
                logger.warning(
                    "Failed to complete intervention queue item",
                    queue_id=queue_id,
                    error=str(e),
                )

        # Release tab to pool (if not closed)
        if not held.tab.is_closed():
            self.release(held.tab)

    async def release_captcha_tab(self, queue_id: str) -> bool:
        """Manually release a CAPTCHA tab (called from resolve_auth).

        Args:
            queue_id: InterventionQueue item ID.

        Returns:
            True if tab was found and released.
        """
        if queue_id in self._held_tabs:
            await self._release_held_tab(queue_id, "manual")
            return True
        return False

    async def release_held_tabs_for_task(self, task_id: str) -> int:
        """Release all held tabs for a specific task (called from stop_task).

        Args:
            task_id: Task ID to filter by.

        Returns:
            Number of tabs released.
        """
        to_release = [qid for qid, held in self._held_tabs.items() if held.task_id == task_id]

        for queue_id in to_release:
            await self._release_held_tab(queue_id, "task_stopped")

        return len(to_release)

    def report_captcha(self) -> None:
        """Report CAPTCHA detection.

        Triggers backoff: reduces effective_max_tabs (ADR-0014).
        Note: No auto-increase for browser SERP (manual only per ADR-0014).

        When already at floor (effective_max_tabs=1), logs warning to alert operator
        that CAPTCHAs are continuing despite minimum concurrency.
        """
        # Load backoff config
        from src.utils.config import get_settings

        settings = get_settings()
        decrease_step = settings.concurrency.backoff.browser_serp.decrease_step

        backoff = self._backoff_state
        now = time.time()

        # Reduce effective_max_tabs (floor at 1)
        new_max = max(1, backoff.effective_max_tabs - decrease_step)

        backoff.last_captcha_time = now
        backoff.captcha_count += 1

        if new_max < backoff.effective_max_tabs:
            # Actual reduction
            backoff.effective_max_tabs = new_max
            backoff.backoff_active = True

            logger.warning(
                "TabPool backoff triggered (CAPTCHA): reducing effective_max_tabs",
                new_effective_max=new_max,
                config_max=backoff.config_max_tabs,
                captcha_count=backoff.captcha_count,
            )
        else:
            # Already at floor (effective_max_tabs=1)
            # Still mark as backoff active and warn operator
            backoff.backoff_active = True

            logger.warning(
                "TabPool at floor (CAPTCHA): already at minimum concurrency",
                effective_max_tabs=backoff.effective_max_tabs,
                captcha_count=backoff.captcha_count,
                hint="Consider increasing cooldown or checking profile health",
            )

    def report_403(self) -> None:
        """Report 403 error.

        Triggers backoff: reduces effective_max_tabs (ADR-0014).
        Note: No auto-increase for browser SERP (manual only per ADR-0014).

        When already at floor (effective_max_tabs=1), logs warning to alert operator
        that 403 errors are continuing despite minimum concurrency.
        """
        # Load backoff config
        from src.utils.config import get_settings

        settings = get_settings()
        decrease_step = settings.concurrency.backoff.browser_serp.decrease_step

        backoff = self._backoff_state
        now = time.time()

        # Reduce effective_max_tabs (floor at 1)
        new_max = max(1, backoff.effective_max_tabs - decrease_step)

        backoff.last_403_time = now
        backoff.error_403_count += 1

        if new_max < backoff.effective_max_tabs:
            # Actual reduction
            backoff.effective_max_tabs = new_max
            backoff.backoff_active = True

            logger.warning(
                "TabPool backoff triggered (403): reducing effective_max_tabs",
                new_effective_max=new_max,
                config_max=backoff.config_max_tabs,
                error_403_count=backoff.error_403_count,
            )
        else:
            # Already at floor (effective_max_tabs=1)
            # Still mark as backoff active and warn operator
            backoff.backoff_active = True

            logger.warning(
                "TabPool at floor (403): already at minimum concurrency",
                effective_max_tabs=backoff.effective_max_tabs,
                error_403_count=backoff.error_403_count,
                hint="Consider increasing cooldown or checking profile health",
            )

    def reset_backoff(self) -> None:
        """Manually reset backoff state.

        Call this after manual config adjustment to restore effective_max_tabs
        to config value (ADR-0014: no auto-increase for browser SERP).
        """
        backoff = self._backoff_state
        backoff.effective_max_tabs = backoff.config_max_tabs
        backoff.backoff_active = False
        backoff.captcha_count = 0
        backoff.error_403_count = 0

        logger.info(
            "TabPool backoff reset",
            effective_max_tabs=backoff.effective_max_tabs,
        )

    async def clear(self) -> None:
        """Clear all tab references without closing the pool.

        Called when browser connection is stale and needs to be re-established.
        This clears all tab references so that new tabs will be created
        on the next acquire() call.

        BUG-001a: This is needed because when Chrome is closed by user,
        the TabPool holds stale tab references that cause errors.
        """
        # Cancel held tabs check task
        if self._held_tabs_check_task and not self._held_tabs_check_task.done():
            self._held_tabs_check_task.cancel()
            try:
                await self._held_tabs_check_task
            except asyncio.CancelledError:
                pass

        # Clear held tabs (don't try to close - browser is already gone)
        self._held_tabs.clear()

        async with self._lock:
            # Clear all tab references (don't try to close - browser is already gone)
            self._tabs.clear()

            # Clear available queue
            while not self._available_tabs.empty():
                try:
                    self._available_tabs.get_nowait()
                except asyncio.QueueEmpty:
                    break

            # Reset active count
            self._active_count = 0
            self._slot_available.set()

        logger.info(
            "TabPool cleared for browser reconnection",
            backoff_active=self._backoff_state.backoff_active,
        )

    async def close(self) -> None:
        """Close all tabs and cleanup resources.

        Should be called when the provider is being shut down.
        """
        self._closed = True

        # Cancel held tabs check task
        if self._held_tabs_check_task and not self._held_tabs_check_task.done():
            self._held_tabs_check_task.cancel()
            try:
                await self._held_tabs_check_task
            except asyncio.CancelledError:
                pass

        # Close held tabs
        for held in list(self._held_tabs.values()):
            try:
                if not held.tab.is_closed():
                    await held.tab.close()
            except Exception as e:
                logger.debug("Error closing held tab", error=str(e))
        self._held_tabs.clear()

        async with self._lock:
            for tab in self._tabs:
                try:
                    if not tab.is_closed():
                        await tab.close()
                except Exception as e:
                    logger.debug("Error closing tab", error=str(e))

            self._tabs.clear()

            # Clear available queue
            while not self._available_tabs.empty():
                try:
                    self._available_tabs.get_nowait()
                except asyncio.QueueEmpty:
                    break

        logger.debug("TabPool closed")

    @property
    def max_tabs(self) -> int:
        """Maximum number of concurrent tabs."""
        return self._max_tabs

    @property
    def active_count(self) -> int:
        """Number of currently active (borrowed) tabs."""
        return len(self._tabs) - self._available_tabs.qsize()

    @property
    def total_count(self) -> int:
        """Total number of tabs created."""
        return len(self._tabs)

    def get_stats(self) -> dict[str, Any]:
        """Get pool statistics.

        Returns:
            Dict with pool stats for monitoring, including backoff state (ADR-0014)
            and held tabs state (ADR-0007).
        """
        backoff = self._backoff_state
        return {
            "max_tabs": self._max_tabs,
            "total_tabs": len(self._tabs),
            "available_tabs": self._available_tabs.qsize(),
            "active_tabs": self._active_count,
            "closed": self._closed,
            # Backoff state (ADR-0014)
            "effective_max_tabs": backoff.effective_max_tabs,
            "backoff_active": backoff.backoff_active,
            "captcha_count": backoff.captcha_count,
            "error_403_count": backoff.error_403_count,
            "last_captcha_time": backoff.last_captcha_time,
            "last_403_time": backoff.last_403_time,
            # Held tabs state (ADR-0007)
            "held_tabs_count": len(self._held_tabs),
            "held_tabs": [
                {
                    "queue_id": h.queue_id,
                    "engine": h.engine,
                    "task_id": h.task_id,
                    "held_at": h.held_at,
                    "expires_at": h.expires_at,
                }
                for h in self._held_tabs.values()
            ],
        }


class EngineRateLimiter:
    """Per-engine rate limiter for SERP requests.

    Enforces min_interval between requests to the same engine.
    Used in conjunction with TabPool for fine-grained control.

    Example:
        limiter = EngineRateLimiter()
        await limiter.acquire("duckduckgo")
        try:
            # ... search operations ...
        finally:
            limiter.release("duckduckgo")
    """

    def __init__(self) -> None:
        """Initialize engine rate limiter."""
        self._locks: dict[str, asyncio.Lock] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._last_request: dict[str, float] = {}
        self._init_lock = asyncio.Lock()

    async def _ensure_initialized(self, engine: str) -> None:
        """Ensure locks are initialized for an engine."""
        if engine in self._locks:
            return

        async with self._init_lock:
            if engine in self._locks:
                return

            config = self._get_engine_config(engine)
            self._locks[engine] = asyncio.Lock()
            self._semaphores[engine] = asyncio.Semaphore(config["concurrency"])
            logger.debug(
                "Initialized rate limiter for engine",
                engine=engine,
                concurrency=config["concurrency"],
            )

    def _get_engine_config(self, engine: str) -> dict[str, Any]:
        """Get rate limit config for an engine from engines.yaml.

        Args:
            engine: Engine name.

        Returns:
            Dict with min_interval and concurrency.
        """
        try:
            from src.search.engine_config import get_engine_config_manager

            manager = get_engine_config_manager()
            config = manager.get_engine(engine)

            return {
                "min_interval": getattr(config, "min_interval", 2.0),
                "concurrency": getattr(config, "concurrency", 1),
            }
        except Exception as e:
            logger.debug("Failed to load engine config", engine=engine, error=str(e))
            return {"min_interval": 2.0, "concurrency": 1}

    async def acquire(self, engine: str) -> None:
        """Acquire rate limit slot for an engine.

        Args:
            engine: Engine name (e.g., "duckduckgo", "mojeek").
        """
        import time

        await self._ensure_initialized(engine)

        # 1. Acquire concurrency slot
        await self._semaphores[engine].acquire()

        # 2. Enforce min_interval
        config = self._get_engine_config(engine)
        async with self._locks[engine]:
            last = self._last_request.get(engine, 0)
            elapsed = time.time() - last
            wait_time = config["min_interval"] - elapsed

            if wait_time > 0:
                logger.debug(
                    "Engine rate limiting: waiting",
                    engine=engine,
                    wait_seconds=wait_time,
                )
                await asyncio.sleep(wait_time)

            self._last_request[engine] = time.time()

    def release(self, engine: str) -> None:
        """Release rate limit slot for an engine.

        Args:
            engine: Engine name.
        """
        if engine in self._semaphores:
            self._semaphores[engine].release()


# Global instances
# Worker ID -> TabPool mapping (ADR-0014 Phase 3: Worker Context Isolation)
_tab_pools: dict[int, TabPool] = {}
_tab_pools_lock = asyncio.Lock()
_engine_rate_limiter: EngineRateLimiter | None = None


def get_tab_pool(worker_id: int = 0, max_tabs: int | None = None) -> TabPool:
    """Get or create a tab pool for a specific worker.

    Per ADR-0014 Phase 3: Each worker gets its own TabPool to enable
    true parallelization and reduce blocking risk.

    Args:
        worker_id: Worker identifier (0 to num_workers-1).
                   Each worker gets its own isolated TabPool.
        max_tabs: Maximum concurrent tabs per worker (only used on first call).
                  If None, reads from config (ADR-0014).

    Returns:
        TabPool instance for the specified worker.
    """
    if worker_id not in _tab_pools:
        if max_tabs is None:
            # Read from config (ADR-0014)
            from src.utils.config import get_settings

            settings = get_settings()
            max_tabs = settings.concurrency.browser_serp.max_tabs
        _tab_pools[worker_id] = TabPool(max_tabs=max_tabs)
        logger.info(
            "Created TabPool for worker",
            worker_id=worker_id,
            max_tabs=max_tabs,
        )
    return _tab_pools[worker_id]


def get_engine_rate_limiter() -> EngineRateLimiter:
    """Get or create the global engine rate limiter.

    Returns:
        Global EngineRateLimiter instance.
    """
    global _engine_rate_limiter
    if _engine_rate_limiter is None:
        _engine_rate_limiter = EngineRateLimiter()
    return _engine_rate_limiter


async def reset_tab_pool(worker_id: int | None = None) -> None:
    """Reset tab pool(s) (for testing only).

    Args:
        worker_id: If specified, reset only the pool for that worker.
                   If None, reset all worker pools.
    """
    global _tab_pools
    if worker_id is not None:
        # Reset specific worker's pool
        if worker_id in _tab_pools:
            await _tab_pools[worker_id].close()
            del _tab_pools[worker_id]
            logger.debug("Reset TabPool for worker", worker_id=worker_id)
    else:
        # Reset all pools
        for _wid, pool in list(_tab_pools.items()):
            await pool.close()
        _tab_pools.clear()
        logger.debug("Reset all TabPools")


def reset_engine_rate_limiter() -> None:
    """Reset the global engine rate limiter (for testing only)."""
    global _engine_rate_limiter
    _engine_rate_limiter = None


def get_all_tab_pools() -> dict[int, TabPool]:
    """Get all active tab pools (for monitoring/testing).

    Returns:
        Dict mapping worker_id to TabPool.
    """
    return _tab_pools.copy()


def get_tab_pool_stats() -> dict[int, dict]:
    """Get stats for all active tab pools.

    Returns:
        Dict mapping worker_id to pool stats.
    """
    return {wid: pool.get_stats() for wid, pool in _tab_pools.items()}
