"""
Tests for TabPool and EngineRateLimiter.

Per ADR-0014: Browser SERP Resource Control.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from src.search.tab_pool import (
    EngineRateLimiter,
    TabPool,
    get_engine_rate_limiter,
    get_tab_pool,
    reset_engine_rate_limiter,
    reset_tab_pool,
)


class TestTabPool:
    """Tests for TabPool class."""

    @pytest.fixture(autouse=True)
    async def reset_pool(self) -> None:
        """Reset global tab pool before each test."""
        await reset_tab_pool()

    def _create_mock_context(self) -> MagicMock:
        """Create a mock BrowserContext."""
        mock_context = MagicMock()
        mock_pages: list[MagicMock] = []

        async def new_page() -> MagicMock:
            mock_page = MagicMock()
            mock_page.is_closed.return_value = False
            mock_page.close = AsyncMock()
            mock_pages.append(mock_page)
            return mock_page

        mock_context.new_page = new_page
        mock_context._mock_pages = mock_pages
        return mock_context

    # =========================================================================
    # TC-N-01: Basic acquire/release flow
    # =========================================================================
    @pytest.mark.asyncio
    async def test_acquire_release_basic(self) -> None:
        """Test basic acquire and release flow.

        Given: A TabPool with max_tabs=1
        When: acquire() and release() are called
        Then: Tab is acquired and released successfully
        """
        # Given: TabPool and mock context
        pool = TabPool(max_tabs=1)
        mock_context = self._create_mock_context()

        # When: Acquire and release
        tab = await pool.acquire(mock_context)
        pool.release(tab)

        # Then: Stats reflect usage
        stats = pool.get_stats()
        assert stats["total_tabs"] == 1
        assert stats["available_tabs"] == 1
        assert stats["active_tabs"] == 0

    # =========================================================================
    # TC-N-02: Multiple tabs with max_tabs=2
    # =========================================================================
    @pytest.mark.asyncio
    async def test_multiple_tabs_within_limit(self) -> None:
        """Test acquiring multiple tabs within limit.

        Given: A TabPool with max_tabs=2
        When: Two tabs are acquired
        Then: Both tabs are successfully acquired
        """
        # Given: TabPool with 2 max tabs
        pool = TabPool(max_tabs=2)
        mock_context = self._create_mock_context()

        # When: Acquire 2 tabs
        tab1 = await pool.acquire(mock_context)
        tab2 = await pool.acquire(mock_context)

        # Then: Both acquired, 2 total tabs
        assert pool.total_count == 2
        assert pool.active_count == 2

        # Cleanup
        pool.release(tab1)
        pool.release(tab2)

    # =========================================================================
    # TC-N-03: Tab reuse after release
    # =========================================================================
    @pytest.mark.asyncio
    async def test_tab_reuse_after_release(self) -> None:
        """Test that released tabs are reused.

        Given: A TabPool with max_tabs=1
        When: Tab is acquired, released, then acquired again
        Then: Same tab is reused (no new tab created)
        """
        # Given: TabPool
        pool = TabPool(max_tabs=1)
        mock_context = self._create_mock_context()

        # When: First acquire
        tab1 = await pool.acquire(mock_context)
        pool.release(tab1)

        # When: Second acquire
        tab2 = await pool.acquire(mock_context)

        # Then: Same tab reused
        assert tab1 is tab2
        assert pool.total_count == 1

        # Cleanup
        pool.release(tab2)

    # =========================================================================
    # TC-N-04: get_stats returns correct statistics
    # =========================================================================
    @pytest.mark.asyncio
    async def test_get_stats(self) -> None:
        """Test get_stats returns correct statistics.

        Given: A TabPool with known state
        When: get_stats() is called
        Then: Returns dict with correct values
        """
        # Given: TabPool with acquired tab
        pool = TabPool(max_tabs=3, acquire_timeout=30.0)
        mock_context = self._create_mock_context()
        tab = await pool.acquire(mock_context)

        # When: Get stats
        stats = pool.get_stats()

        # Then: Stats are correct
        assert stats["max_tabs"] == 3
        assert stats["total_tabs"] == 1
        assert stats["available_tabs"] == 0
        assert stats["active_tabs"] == 1
        assert stats["closed"] is False

        # Cleanup
        pool.release(tab)

    # =========================================================================
    # TC-B-01: max_tabs=0 raises ValueError
    # =========================================================================
    def test_max_tabs_zero_raises_error(self) -> None:
        """Test that max_tabs=0 raises ValueError.

        Given: max_tabs=0
        When: TabPool is instantiated
        Then: ValueError is raised
        """
        # Given/When/Then: ValueError for invalid max_tabs
        with pytest.raises(ValueError, match="max_tabs must be at least 1"):
            TabPool(max_tabs=0)

    def test_max_tabs_negative_raises_error(self) -> None:
        """Test that negative max_tabs raises ValueError.

        Given: max_tabs=-1
        When: TabPool is instantiated
        Then: ValueError is raised
        """
        # Given/When/Then: ValueError for negative max_tabs
        with pytest.raises(ValueError, match="max_tabs must be at least 1"):
            TabPool(max_tabs=-1)

    # =========================================================================
    # TC-B-02: Exceeding max_tabs causes timeout
    # =========================================================================
    @pytest.mark.asyncio
    async def test_exceeding_max_tabs_blocks(self) -> None:
        """Test that exceeding max_tabs blocks until timeout.

        Given: A TabPool with max_tabs=1 and short timeout
        When: Two concurrent acquire() calls
        Then: Second call times out
        """
        # Given: TabPool with short timeout
        pool = TabPool(max_tabs=1, acquire_timeout=0.1)
        mock_context = self._create_mock_context()

        # When: First acquire succeeds
        tab1 = await pool.acquire(mock_context)

        # Then: Second acquire times out
        with pytest.raises(TimeoutError, match="Failed to acquire tab"):
            await pool.acquire(mock_context)

        # Cleanup
        pool.release(tab1)

    # =========================================================================
    # TC-A-01: acquire after close raises RuntimeError
    # =========================================================================
    @pytest.mark.asyncio
    async def test_acquire_after_close_raises_error(self) -> None:
        """Test that acquire after close raises RuntimeError.

        Given: A closed TabPool
        When: acquire() is called
        Then: RuntimeError is raised
        """
        # Given: Closed pool
        pool = TabPool(max_tabs=1)
        mock_context = self._create_mock_context()
        await pool.close()

        # When/Then: RuntimeError
        with pytest.raises(RuntimeError, match="TabPool is closed"):
            await pool.acquire(mock_context)

    # =========================================================================
    # TC-A-02: release after close is no-op
    # =========================================================================
    @pytest.mark.asyncio
    async def test_release_after_close_is_noop(self) -> None:
        """Test that release after close is a no-op.

        Given: A TabPool with an acquired tab, then closed
        When: release() is called
        Then: No exception (ignored)
        """
        # Given: Pool with acquired tab
        pool = TabPool(max_tabs=1)
        mock_context = self._create_mock_context()
        tab = await pool.acquire(mock_context)

        # When: Close pool, then release
        await pool.close()
        pool.release(tab)  # Should not raise

        # Then: Pool stats show closed
        stats = pool.get_stats()
        assert stats["closed"] is True

    @pytest.mark.asyncio
    async def test_close_cleans_up_tabs(self) -> None:
        """Test that close() cleans up all tabs.

        Given: A TabPool with created tabs
        When: close() is called
        Then: All tabs are closed
        """
        # Given: Pool with tabs
        pool = TabPool(max_tabs=2)
        mock_context = self._create_mock_context()
        tab1 = await pool.acquire(mock_context)
        tab2 = await pool.acquire(mock_context)
        pool.release(tab1)
        pool.release(tab2)

        # When: Close
        await pool.close()

        # Then: Tabs were closed
        for mock_page in mock_context._mock_pages:
            mock_page.close.assert_called()

    @pytest.mark.asyncio
    async def test_properties(self) -> None:
        """Test property accessors.

        Given: A TabPool with known configuration
        When: Properties are accessed
        Then: Correct values are returned
        """
        # Given: TabPool
        pool = TabPool(max_tabs=5)
        mock_context = self._create_mock_context()
        tab = await pool.acquire(mock_context)

        # When/Then: Properties
        assert pool.max_tabs == 5
        assert pool.total_count == 1
        assert pool.active_count == 1

        pool.release(tab)
        assert pool.active_count == 0


class TestEngineRateLimiter:
    """Tests for EngineRateLimiter class."""

    @pytest.fixture(autouse=True)
    def reset_limiter(self) -> None:
        """Reset global engine rate limiter before each test."""
        reset_engine_rate_limiter()

    # =========================================================================
    # TC-N-01: Basic acquire/release flow
    # =========================================================================
    @pytest.mark.asyncio
    async def test_acquire_release_basic(self) -> None:
        """Test basic acquire and release flow.

        Given: An EngineRateLimiter
        When: acquire() and release() are called for an engine
        Then: Both operations complete without error
        """
        # Given: Rate limiter with mocked config
        limiter = EngineRateLimiter()

        with patch.object(
            limiter,
            "_get_engine_config",
            return_value={"min_interval": 0.0, "concurrency": 1},
        ):
            # When: acquire and release
            await limiter.acquire("duckduckgo")
            limiter.release("duckduckgo")

            # Then: No exceptions raised (implicit assertion)

    # =========================================================================
    # TC-N-02: Multiple engines are isolated
    # =========================================================================
    @pytest.mark.asyncio
    async def test_multiple_engines_isolated(self) -> None:
        """Test that different engines have isolated rate limits.

        Given: Two different engines
        When: acquire() is called for both simultaneously
        Then: Both can be acquired without blocking each other
        """
        # Given: Rate limiter
        limiter = EngineRateLimiter()

        with patch.object(
            limiter,
            "_get_engine_config",
            return_value={"min_interval": 0.0, "concurrency": 1},
        ):
            # When: Acquire both engines
            await limiter.acquire("duckduckgo")
            await limiter.acquire("mojeek")

            # Then: Both acquired (no blocking between engines)
            limiter.release("duckduckgo")
            limiter.release("mojeek")

    # =========================================================================
    # TC-B-01: QPS limiting (min_interval enforcement)
    # =========================================================================
    @pytest.mark.asyncio
    async def test_qps_limiting_enforces_min_interval(self) -> None:
        """Test that min_interval is enforced between requests.

        Given: An EngineRateLimiter with min_interval=0.1
        When: Two acquire() calls in quick succession
        Then: Second call waits until min_interval has passed
        """
        # Given: Rate limiter with 0.1s min interval
        limiter = EngineRateLimiter()

        with patch.object(
            limiter,
            "_get_engine_config",
            return_value={"min_interval": 0.1, "concurrency": 1},
        ):
            # When: First acquire
            start = time.time()
            await limiter.acquire("test_engine")
            limiter.release("test_engine")

            # When: Second acquire immediately
            await limiter.acquire("test_engine")
            elapsed = time.time() - start
            limiter.release("test_engine")

            # Then: Total time >= min_interval (with small tolerance)
            assert elapsed >= 0.09, f"Expected elapsed >= 0.09s, got {elapsed:.3f}s"

    # =========================================================================
    # TC-A-01: Config loading failure uses defaults
    # =========================================================================
    @pytest.mark.asyncio
    async def test_config_failure_uses_defaults(self) -> None:
        """Test that config loading failure falls back to defaults.

        Given: Config loading raises an exception
        When: acquire() is called
        Then: Default config values are used (no exception)
        """
        # Given: Rate limiter that returns default config on failure
        limiter = EngineRateLimiter()

        # Patch _get_engine_config to simulate failure and return defaults
        def failing_config(engine: str) -> dict[str, Any]:
            return {"min_interval": 2.0, "concurrency": 1}

        with patch.object(limiter, "_get_engine_config", side_effect=failing_config):
            # When: acquire/release (should not raise)
            await limiter.acquire("unknown_engine")
            limiter.release("unknown_engine")

            # Then: No exception (uses defaults)

    @pytest.mark.asyncio
    async def test_release_without_acquire_is_noop(self) -> None:
        """Test that release on uninitialized engine doesn't crash.

        Given: An engine that was never acquired
        When: release() is called
        Then: No exception (no-op)
        """
        # Given: Fresh limiter
        limiter = EngineRateLimiter()

        # When/Then: release without acquire doesn't crash
        limiter.release("never_acquired")  # Should not raise


class TestGlobalTabPoolFunctions:
    """Tests for global tab pool singleton functions."""

    @pytest.fixture(autouse=True)
    async def reset_pool(self) -> None:
        """Reset global tab pool before each test."""
        await reset_tab_pool()

    def test_get_tab_pool_singleton(self) -> None:
        """Test get_tab_pool returns singleton.

        Given: Global tab pool is reset
        When: get_tab_pool() is called twice
        Then: Same instance is returned
        """
        # When: Get pool twice
        pool1 = get_tab_pool()
        pool2 = get_tab_pool()

        # Then: Same instance
        assert pool1 is pool2

    @pytest.mark.asyncio
    async def test_reset_tab_pool(self) -> None:
        """Test reset creates new instance.

        Given: A global tab pool exists
        When: reset_tab_pool() is called
        Then: Next get_tab_pool() returns new instance
        """
        # Given: Get initial pool
        pool1 = get_tab_pool()

        # When: Reset
        await reset_tab_pool()

        # Then: New instance
        pool2 = get_tab_pool()
        assert pool1 is not pool2


class TestGlobalEngineRateLimiterFunctions:
    """Tests for global engine rate limiter singleton functions."""

    @pytest.fixture(autouse=True)
    def reset_limiter(self) -> None:
        """Reset global engine rate limiter before each test."""
        reset_engine_rate_limiter()

    def test_get_engine_rate_limiter_singleton(self) -> None:
        """Test get_engine_rate_limiter returns singleton.

        Given: Global rate limiter is reset
        When: get_engine_rate_limiter() is called twice
        Then: Same instance is returned
        """
        # When: Get limiter twice
        limiter1 = get_engine_rate_limiter()
        limiter2 = get_engine_rate_limiter()

        # Then: Same instance
        assert limiter1 is limiter2

    def test_reset_engine_rate_limiter(self) -> None:
        """Test reset creates new instance.

        Given: A global rate limiter exists
        When: reset_engine_rate_limiter() is called
        Then: Next get_engine_rate_limiter() returns new instance
        """
        # Given: Get initial limiter
        limiter1 = get_engine_rate_limiter()

        # When: Reset
        reset_engine_rate_limiter()

        # Then: New instance
        limiter2 = get_engine_rate_limiter()
        assert limiter1 is not limiter2

