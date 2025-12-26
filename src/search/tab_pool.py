"""
Tab pool for browser-based SERP fetching.

Per ADR-0014: Browser SERP Resource Control.
Per ADR-0015: Adaptive Concurrency Control (auto-backoff on CAPTCHA/403).

Design:
- Manages a pool of browser tabs (Page objects) for parallel SERP fetching
- Prevents simultaneous operations on the same Page
- Supports configurable max_tabs for gradual parallelization
- Default max_tabs=1 ensures correctness (no Page contention)
- Auto-backoff: reduces effective_max_tabs on CAPTCHA/403 (no auto-increase per ADR-0015)
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
    """Tracks backoff state for TabPool (ADR-0015)."""

    effective_max_tabs: int = 1  # Current effective limit (may be < config max)
    config_max_tabs: int = 1  # Original config limit (upper bound)
    last_captcha_time: float = 0.0  # Timestamp of last CAPTCHA detection
    last_403_time: float = 0.0  # Timestamp of last 403 error
    backoff_active: bool = False  # Whether backoff is currently active
    captcha_count: int = 0  # Total CAPTCHA count since last reset
    error_403_count: int = 0  # Total 403 count since last reset


class TabPool:
    """Manages browser tabs for parallel SERP fetching.

    Prevents Page sharing between concurrent operations per ADR-0014.
    Each search operation borrows a tab, uses it exclusively, then returns it.
    Implements auto-backoff on CAPTCHA/403 (ADR-0015).

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

        # Backoff state (ADR-0015)
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

        logger.debug("TabPool initialized", max_tabs=max_tabs)

    async def acquire(self, context: BrowserContext) -> Page:
        """Acquire a tab from the pool.

        Blocks until a tab is available or creates a new one if under effective_max_tabs.
        Respects backoff state (ADR-0015).

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

        # Wait for backoff slot if necessary (ADR-0015)
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

        # Release backoff slot (ADR-0015)
        if self._active_count > 0:
            self._active_count -= 1
        self._slot_available.set()  # Signal that a slot is available

        logger.debug("Tab released", available=self._available_tabs.qsize())

    def report_captcha(self) -> None:
        """Report CAPTCHA detection.

        Triggers backoff: reduces effective_max_tabs (ADR-0015).
        Note: No auto-increase for browser SERP (manual only per ADR-0015).

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

        Triggers backoff: reduces effective_max_tabs (ADR-0015).
        Note: No auto-increase for browser SERP (manual only per ADR-0015).

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
        to config value (ADR-0015: no auto-increase for browser SERP).
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

    async def close(self) -> None:
        """Close all tabs and cleanup resources.

        Should be called when the provider is being shut down.
        """
        self._closed = True

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
            Dict with pool stats for monitoring, including backoff state (ADR-0015).
        """
        backoff = self._backoff_state
        return {
            "max_tabs": self._max_tabs,
            "total_tabs": len(self._tabs),
            "available_tabs": self._available_tabs.qsize(),
            "active_tabs": self._active_count,
            "closed": self._closed,
            # Backoff state (ADR-0015)
            "effective_max_tabs": backoff.effective_max_tabs,
            "backoff_active": backoff.backoff_active,
            "captcha_count": backoff.captcha_count,
            "error_403_count": backoff.error_403_count,
            "last_captcha_time": backoff.last_captcha_time,
            "last_403_time": backoff.last_403_time,
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
                  If None, reads from config (ADR-0015).

    Returns:
        TabPool instance for the specified worker.
    """
    if worker_id not in _tab_pools:
        if max_tabs is None:
            # Read from config (ADR-0015)
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
        for wid, pool in list(_tab_pools.items()):
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
