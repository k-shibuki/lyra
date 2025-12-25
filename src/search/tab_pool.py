"""
Tab pool for browser-based SERP fetching.

Per ADR-0014: Browser SERP Resource Control.

Design:
- Manages a pool of browser tabs (Page objects) for parallel SERP fetching
- Prevents simultaneous operations on the same Page
- Supports configurable max_tabs for gradual parallelization
- Default max_tabs=1 ensures correctness (no Page contention)
- Increase max_tabs for parallelization after stability validation
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from src.utils.logging import get_logger

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page

logger = get_logger(__name__)


class TabPool:
    """Manages browser tabs for parallel SERP fetching.

    Prevents Page sharing between concurrent operations per ADR-0014.
    Each search operation borrows a tab, uses it exclusively, then returns it.

    Example:
        pool = TabPool(max_tabs=1)
        tab = await pool.acquire(context)
        try:
            await tab.goto(url)
            # ... search operations ...
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

        # Semaphore controls how many tabs can be acquired simultaneously
        self._semaphore = asyncio.Semaphore(max_tabs)

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

        Blocks until a tab is available or creates a new one if under max_tabs.

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

        # Acquire semaphore slot (blocks if max_tabs reached)
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=self._acquire_timeout,
            )
        except TimeoutError as e:
            raise TimeoutError(
                f"Failed to acquire tab within {self._acquire_timeout}s (max_tabs={self._max_tabs})"
            ) from e

        # Try to get an existing available tab
        try:
            tab = self._available_tabs.get_nowait()
            logger.debug("Reusing existing tab", tabs_count=len(self._tabs))
            return tab
        except asyncio.QueueEmpty:
            pass

        # Create a new tab
        async with self._lock:
            if len(self._tabs) < self._max_tabs:
                tab = await context.new_page()
                self._tabs.append(tab)
                logger.debug("Created new tab", tabs_count=len(self._tabs))
                return tab

        # This shouldn't happen if semaphore is working correctly
        # But as a safety measure, wait for an available tab
        try:
            tab = await asyncio.wait_for(
                self._available_tabs.get(),
                timeout=self._acquire_timeout,
            )
            return tab
        except TimeoutError as e:
            self._semaphore.release()
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

        # Release semaphore slot
        self._semaphore.release()
        logger.debug("Tab released", available=self._available_tabs.qsize())

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
            Dict with pool stats for monitoring.
        """
        return {
            "max_tabs": self._max_tabs,
            "total_tabs": len(self._tabs),
            "available_tabs": self._available_tabs.qsize(),
            "active_tabs": self.active_count,
            "closed": self._closed,
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
_tab_pool: TabPool | None = None
_engine_rate_limiter: EngineRateLimiter | None = None


def get_tab_pool(max_tabs: int = 1) -> TabPool:
    """Get or create the global tab pool.

    Args:
        max_tabs: Maximum concurrent tabs (only used on first call).

    Returns:
        Global TabPool instance.
    """
    global _tab_pool
    if _tab_pool is None:
        _tab_pool = TabPool(max_tabs=max_tabs)
    return _tab_pool


def get_engine_rate_limiter() -> EngineRateLimiter:
    """Get or create the global engine rate limiter.

    Returns:
        Global EngineRateLimiter instance.
    """
    global _engine_rate_limiter
    if _engine_rate_limiter is None:
        _engine_rate_limiter = EngineRateLimiter()
    return _engine_rate_limiter


async def reset_tab_pool() -> None:
    """Reset the global tab pool (for testing only)."""
    global _tab_pool
    if _tab_pool is not None:
        await _tab_pool.close()
        _tab_pool = None


def reset_engine_rate_limiter() -> None:
    """Reset the global engine rate limiter (for testing only)."""
    global _engine_rate_limiter
    _engine_rate_limiter = None
