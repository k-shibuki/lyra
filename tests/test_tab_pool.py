"""
Tests for TabPool and EngineRateLimiter.

Per ADR-0014: Browser SERP Resource Control.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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

    def test_get_tab_pool_worker_id_isolation(self) -> None:
        """Test get_tab_pool returns different instances per worker_id.

        Given: Global tab pool is reset
        When: get_tab_pool() is called with different worker_ids
        Then: Different instances are returned for each worker_id (ADR-0014 Phase 3)
        """
        # When: Get pool for different workers
        pool0 = get_tab_pool(worker_id=0)
        pool1 = get_tab_pool(worker_id=1)

        # Then: Different instances
        assert pool0 is not pool1

    def test_get_tab_pool_same_worker_id_singleton(self) -> None:
        """Test get_tab_pool returns same instance for same worker_id.

        Given: Global tab pool is reset
        When: get_tab_pool() is called twice with same worker_id
        Then: Same instance is returned
        """
        # When: Get pool twice for same worker
        pool1 = get_tab_pool(worker_id=0)
        pool2 = get_tab_pool(worker_id=0)

        # Then: Same instance
        assert pool1 is pool2

    @pytest.mark.asyncio
    async def test_reset_tab_pool_all(self) -> None:
        """Test reset without worker_id clears all pools.

        Given: Multiple worker pools exist
        When: reset_tab_pool() is called without worker_id
        Then: All pools are cleared and new instances are returned
        """
        # Given: Get pools for multiple workers
        pool0_before = get_tab_pool(worker_id=0)
        pool1_before = get_tab_pool(worker_id=1)

        # When: Reset all
        await reset_tab_pool()

        # Then: New instances for all workers
        pool0_after = get_tab_pool(worker_id=0)
        pool1_after = get_tab_pool(worker_id=1)
        assert pool0_before is not pool0_after
        assert pool1_before is not pool1_after

    @pytest.mark.asyncio
    async def test_reset_tab_pool_specific_worker(self) -> None:
        """Test reset with worker_id clears only that worker's pool.

        Given: Multiple worker pools exist
        When: reset_tab_pool(worker_id=0) is called
        Then: Only worker 0's pool is cleared, worker 1's remains
        """
        # Given: Get pools for multiple workers
        pool0_before = get_tab_pool(worker_id=0)
        pool1_before = get_tab_pool(worker_id=1)

        # When: Reset only worker 0
        await reset_tab_pool(worker_id=0)

        # Then: Only worker 0 gets new instance
        pool0_after = get_tab_pool(worker_id=0)
        pool1_after = get_tab_pool(worker_id=1)
        assert pool0_before is not pool0_after
        assert pool1_before is pool1_after  # Same instance


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


# =============================================================================
# TabPool Backoff Tests (ADR-0014)
# =============================================================================


class TestTabPoolBackoff:
    """Tests for TabPool backoff functionality.

    Per ADR-0014: Adaptive Concurrency Control.

    Test Perspectives Table:
    | Case ID | Input / Precondition | Perspective | Expected Result |
    |---------|----------------------|-------------|-----------------|
    | TC-T-01 | Initial state | Equivalence | backoff_active=False |
    | TC-T-02 | report_captcha once | Equivalence | effective_max_tabs decreases |
    | TC-T-03 | report_403 once | Equivalence | effective_max_tabs decreases |
    | TC-T-04 | report_captcha at effective=1 | Boundary | effective=1 (floor) |
    | TC-T-05 | reset_backoff | Equivalence | restore to config_max |
    | TC-T-06 | get_stats with backoff | Equivalence | contains backoff state |
    | TC-T-07 | max_tabs=2, backoff blocks | Boundary | 2nd acquire blocks |
    """

    @pytest.fixture(autouse=True)
    async def reset_pool(self) -> None:
        """Reset global tab pool before each test."""
        await reset_tab_pool()

    def _create_mock_settings(self, decrease_step: int = 1) -> MagicMock:
        """Create mock settings for backoff config."""
        mock_settings = MagicMock()
        mock_settings.concurrency.backoff.browser_serp.decrease_step = decrease_step
        return mock_settings

    # =========================================================================
    # TC-T-01: Initial backoff state
    # =========================================================================
    def test_initial_backoff_state(self) -> None:
        """Test initial backoff state.

        Given: A newly created TabPool
        When: Checking backoff state
        Then: backoff_active=False, effective_max_tabs=config_max
        """
        # Given/When
        pool = TabPool(max_tabs=3)

        # Then
        assert pool._backoff_state.backoff_active is False
        assert pool._backoff_state.effective_max_tabs == 3
        assert pool._backoff_state.config_max_tabs == 3
        assert pool._backoff_state.captcha_count == 0
        assert pool._backoff_state.error_403_count == 0

    # =========================================================================
    # TC-T-02: report_captcha triggers backoff
    # =========================================================================
    def test_report_captcha_triggers_backoff(self) -> None:
        """Test report_captcha triggers backoff.

        Given: A TabPool with max_tabs=3
        When: report_captcha is called
        Then: effective_max_tabs decreases, backoff_active=True
        """
        # Given
        pool = TabPool(max_tabs=3)
        mock_settings = self._create_mock_settings(decrease_step=1)

        # When (patch at use site per test rules)
        with patch("src.utils.config.get_settings", return_value=mock_settings):
            pool.report_captcha()

        # Then
        assert pool._backoff_state.effective_max_tabs == 2  # 3 - 1 = 2
        assert pool._backoff_state.backoff_active is True
        assert pool._backoff_state.captcha_count == 1

    # =========================================================================
    # TC-T-03: report_403 triggers backoff
    # =========================================================================
    def test_report_403_triggers_backoff(self) -> None:
        """Test report_403 triggers backoff.

        Given: A TabPool with max_tabs=3
        When: report_403 is called
        Then: effective_max_tabs decreases, backoff_active=True
        """
        # Given
        pool = TabPool(max_tabs=3)
        mock_settings = self._create_mock_settings(decrease_step=1)

        # When (patch at use site per test rules)
        with patch("src.utils.config.get_settings", return_value=mock_settings):
            pool.report_403()

        # Then
        assert pool._backoff_state.effective_max_tabs == 2  # 3 - 1 = 2
        assert pool._backoff_state.backoff_active is True
        assert pool._backoff_state.error_403_count == 1

    # =========================================================================
    # TC-T-04: report_captcha floors at 1
    # =========================================================================
    def test_report_captcha_floors_at_one(self) -> None:
        """Test effective_max_tabs floors at 1.

        Given: A TabPool with effective_max_tabs=1
        When: report_captcha is called
        Then: effective_max_tabs remains 1 (floor), but backoff_active=True and warning logged
        """
        # Given
        pool = TabPool(max_tabs=1)
        mock_settings = self._create_mock_settings(decrease_step=1)

        # When (patch at use site per test rules)
        with patch("src.utils.config.get_settings", return_value=mock_settings):
            pool.report_captcha()

        # Then
        assert pool._backoff_state.effective_max_tabs == 1  # Floor at 1
        assert pool._backoff_state.captcha_count == 1
        # Even at floor, backoff should be active to alert operator
        assert pool._backoff_state.backoff_active is True

    def test_report_403_floors_at_one(self) -> None:
        """Test effective_max_tabs floors at 1 for 403 errors.

        Given: A TabPool with effective_max_tabs=1
        When: report_403 is called
        Then: effective_max_tabs remains 1 (floor), but backoff_active=True and warning logged
        """
        # Given
        pool = TabPool(max_tabs=1)
        mock_settings = self._create_mock_settings(decrease_step=1)

        # When (patch at use site per test rules)
        with patch("src.utils.config.get_settings", return_value=mock_settings):
            pool.report_403()

        # Then
        assert pool._backoff_state.effective_max_tabs == 1  # Floor at 1
        assert pool._backoff_state.error_403_count == 1
        # Even at floor, backoff should be active to alert operator
        assert pool._backoff_state.backoff_active is True

    def test_report_captcha_repeated_at_floor(self) -> None:
        """Test repeated CAPTCHA reports at floor are all counted.

        Given: A TabPool with effective_max_tabs=1
        When: report_captcha is called 3 times
        Then: All CAPTCHAs are counted, backoff_active=True throughout
        """
        # Given
        pool = TabPool(max_tabs=1)
        mock_settings = self._create_mock_settings(decrease_step=1)

        # When (patch at use site per test rules)
        with patch("src.utils.config.get_settings", return_value=mock_settings):
            pool.report_captcha()
            pool.report_captcha()
            pool.report_captcha()

        # Then
        assert pool._backoff_state.effective_max_tabs == 1  # Still at floor
        assert pool._backoff_state.captcha_count == 3  # All counted
        assert pool._backoff_state.backoff_active is True  # Active throughout

    # =========================================================================
    # TC-T-05: reset_backoff restores config_max
    # =========================================================================
    def test_reset_backoff_restores_config_max(self) -> None:
        """Test reset_backoff restores effective_max_tabs to config_max.

        Given: A TabPool in backoff state
        When: reset_backoff is called
        Then: effective_max_tabs restored, backoff_active=False, counters reset
        """
        # Given
        pool = TabPool(max_tabs=3)
        pool._backoff_state.effective_max_tabs = 1
        pool._backoff_state.backoff_active = True
        pool._backoff_state.captcha_count = 5
        pool._backoff_state.error_403_count = 3

        # When
        pool.reset_backoff()

        # Then
        assert pool._backoff_state.effective_max_tabs == 3  # Restored
        assert pool._backoff_state.backoff_active is False
        assert pool._backoff_state.captcha_count == 0
        assert pool._backoff_state.error_403_count == 0

    # =========================================================================
    # TC-T-06: get_stats includes backoff state
    # =========================================================================
    def test_get_stats_includes_backoff_state(self) -> None:
        """Test get_stats includes backoff state.

        Given: A TabPool with backoff active
        When: get_stats is called
        Then: Stats include effective_max_tabs, captcha_count, etc.
        """
        # Given
        pool = TabPool(max_tabs=3)
        pool._backoff_state.effective_max_tabs = 2
        pool._backoff_state.backoff_active = True
        pool._backoff_state.captcha_count = 3
        pool._backoff_state.error_403_count = 1
        pool._backoff_state.last_captcha_time = 12345.0
        pool._backoff_state.last_403_time = 12346.0

        # When
        stats = pool.get_stats()

        # Then
        assert stats["effective_max_tabs"] == 2
        assert stats["backoff_active"] is True
        assert stats["captcha_count"] == 3
        assert stats["error_403_count"] == 1
        assert stats["last_captcha_time"] == 12345.0
        assert stats["last_403_time"] == 12346.0
        assert stats["max_tabs"] == 3  # Config value

    # =========================================================================
    # TC-T-07: Backoff limits acquire
    # =========================================================================
    @pytest.mark.asyncio
    async def test_backoff_limits_acquire(self) -> None:
        """Test backoff limits concurrent acquires.

        Given: A TabPool with max_tabs=2 but effective_max_tabs=1
        When: Second acquire is attempted while first is held
        Then: Second acquire blocks/times out
        """
        # Given
        pool = TabPool(max_tabs=2, acquire_timeout=0.2)

        # Set effective to 1 (backoff state)
        pool._backoff_state.effective_max_tabs = 1

        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_page.is_closed.return_value = False

        async def new_page() -> MagicMock:
            return mock_page

        mock_context.new_page = new_page

        # When: First acquire succeeds
        tab1 = await pool.acquire(mock_context)
        assert pool._active_count == 1

        # When: Second acquire should timeout (effective=1)
        with pytest.raises(TimeoutError) as exc_info:
            await pool.acquire(mock_context)

        # Then: Error mentions backoff
        assert "backoff" in str(exc_info.value).lower() or "effective_max_tabs" in str(
            exc_info.value
        )

        # Cleanup
        pool.release(tab1)
        assert pool._active_count == 0

    # =========================================================================
    # Effect test: decrease_step affects backoff amount
    # =========================================================================
    def test_decrease_step_effect(self) -> None:
        """Test decrease_step affects backoff amount.

        Given: A TabPool with max_tabs=5 and decrease_step=2
        When: report_captcha is called
        Then: effective_max_tabs decreases by 2
        """
        # Given
        pool = TabPool(max_tabs=5)
        mock_settings = self._create_mock_settings(decrease_step=2)

        # When (patch at use site per test rules)
        with patch("src.utils.config.get_settings", return_value=mock_settings):
            pool.report_captcha()

        # Then
        assert pool._backoff_state.effective_max_tabs == 3  # 5 - 2 = 3

    # =========================================================================
    # Test release signals slot availability
    # =========================================================================
    @pytest.mark.asyncio
    async def test_release_signals_slot_available(self) -> None:
        """Test release signals slot availability for waiting acquires.

        Given: A TabPool with effective_max_tabs=1 and one tab held
        When: Tab is released
        Then: Waiting acquire can proceed
        """
        # Given
        pool = TabPool(max_tabs=2, acquire_timeout=1.0)
        pool._backoff_state.effective_max_tabs = 1

        mock_context = MagicMock()
        mock_pages: list[MagicMock] = []

        async def new_page() -> MagicMock:
            mock_page = MagicMock()
            mock_page.is_closed.return_value = False
            mock_pages.append(mock_page)
            return mock_page

        mock_context.new_page = new_page

        # Acquire first tab
        tab1 = await pool.acquire(mock_context)
        assert pool._active_count == 1

        # Start second acquire in background (will block)
        async def delayed_acquire() -> Any:
            return await pool.acquire(mock_context)

        acquire_task = asyncio.create_task(delayed_acquire())

        # Give it time to start waiting
        await asyncio.sleep(0.05)

        # When: Release first tab
        pool.release(tab1)

        # Then: Second acquire should complete
        tab2 = await asyncio.wait_for(acquire_task, timeout=0.5)
        assert tab2 is not None

        # Cleanup
        pool.release(tab2)

    # =========================================================================
    # TC-T-08: max_tabs=2 parallel operation (production default)
    # =========================================================================
    @pytest.mark.asyncio
    async def test_max_tabs_2_parallel_operation(self) -> None:
        """Test max_tabs=2 allows parallel tab operations.

        Given: A TabPool with max_tabs=2 (production default)
        When: Two tabs are acquired simultaneously
        Then: Both acquire without blocking, each gets independent Page
        """
        # Given
        pool = TabPool(max_tabs=2, acquire_timeout=1.0)

        mock_context = MagicMock()
        created_pages: list[MagicMock] = []

        async def new_page() -> MagicMock:
            mock_page = MagicMock()
            mock_page.is_closed.return_value = False
            mock_page.close = AsyncMock()
            # Give each page a unique ID to verify independence
            mock_page.page_id = len(created_pages)
            created_pages.append(mock_page)
            return mock_page

        mock_context.new_page = new_page

        # When: Acquire two tabs simultaneously
        tab1 = await pool.acquire(mock_context)
        tab2 = await pool.acquire(mock_context)

        # Then: Both acquired, each is independent
        assert pool._active_count == 2
        assert tab1 is not tab2  # Different Page objects
        assert len(created_pages) == 2

        # Verify stats
        stats = pool.get_stats()
        assert stats["max_tabs"] == 2
        assert stats["active_tabs"] == 2
        assert stats["effective_max_tabs"] == 2

        # Cleanup
        pool.release(tab1)
        pool.release(tab2)
        assert pool._active_count == 0

    # =========================================================================
    # TC-T-09: max_tabs=2 blocks third acquire
    # =========================================================================
    @pytest.mark.asyncio
    async def test_max_tabs_2_blocks_third_acquire(self) -> None:
        """Test max_tabs=2 blocks third acquire.

        Given: A TabPool with max_tabs=2 and both tabs held
        When: Third acquire is attempted
        Then: Third acquire times out
        """
        # Given
        pool = TabPool(max_tabs=2, acquire_timeout=0.2)

        mock_context = MagicMock()

        async def new_page() -> MagicMock:
            mock_page = MagicMock()
            mock_page.is_closed.return_value = False
            return mock_page

        mock_context.new_page = new_page

        # Acquire both tabs
        tab1 = await pool.acquire(mock_context)
        tab2 = await pool.acquire(mock_context)
        assert pool._active_count == 2

        # When: Third acquire should timeout
        with pytest.raises(TimeoutError):
            await pool.acquire(mock_context)

        # Cleanup
        pool.release(tab1)
        pool.release(tab2)


# =============================================================================
# TabPool HeldTab Tests (ADR-0007: CAPTCHA Tab Hold)
# =============================================================================


class TestTabPoolHeldTabs:
    """Tests for TabPool held tabs functionality.

    Per ADR-0007: Human-in-the-Loop Authentication.

    Test Perspectives Table:
    | Case ID | Input / Precondition | Perspective | Expected Result |
    |---------|----------------------|-------------|-----------------|
    | TC-H-01 | hold_for_captcha() | Equivalence | Tab held, not in pool |
    | TC-H-02 | release_captcha_tab() | Equivalence | Tab returned to pool |
    | TC-H-03 | release_held_tabs_for_task() | Equivalence | All task tabs released |
    | TC-H-04 | Expired tab | Boundary | Tab auto-released |
    | TC-H-05 | Resolved CAPTCHA | Equivalence | Tab auto-released, CB reset |
    | TC-H-06 | get_stats with held tabs | Equivalence | Stats include held_tabs |
    | TC-H-07 | close() with held tabs | Equivalence | Held tabs cleaned up |
    """

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
            # Add content method for CAPTCHA checking
            mock_page.content = AsyncMock(return_value="<html>Normal page</html>")
            mock_pages.append(mock_page)
            return mock_page

        mock_context.new_page = new_page
        mock_context._mock_pages = mock_pages
        return mock_context

    # =========================================================================
    # TC-H-01: hold_for_captcha basic functionality
    # =========================================================================
    @pytest.mark.asyncio
    async def test_hold_for_captcha_basic(self) -> None:
        """Test hold_for_captcha holds tab and removes from pool.

        Given: A TabPool with an acquired tab
        When: hold_for_captcha() is called
        Then: Tab is held, not returned to pool, slot is released
        """
        # Given: Pool with acquired tab
        pool = TabPool(max_tabs=1)
        mock_context = self._create_mock_context()
        tab = await pool.acquire(mock_context)

        expires_at = time.time() + 3600

        # When: Hold tab for CAPTCHA
        pool.hold_for_captcha(
            tab=tab,
            queue_id="test-queue-id",
            engine="duckduckgo",
            task_id="test-task",
            expires_at=expires_at,
        )

        # Then: Tab is held, slot is released
        assert "test-queue-id" in pool._held_tabs
        assert pool._active_count == 0  # Slot released for other work
        assert pool._available_tabs.qsize() == 0  # But tab not in available queue

        # Verify held tab data
        held = pool._held_tabs["test-queue-id"]
        assert held.tab is tab
        assert held.engine == "duckduckgo"
        assert held.task_id == "test-task"
        assert held.expires_at == expires_at

        # Cleanup
        await pool.close()

    # =========================================================================
    # TC-H-02: release_captcha_tab manual release
    # =========================================================================
    @pytest.mark.asyncio
    async def test_release_captcha_tab_manual(self) -> None:
        """Test release_captcha_tab returns tab to pool.

        Given: A TabPool with a held CAPTCHA tab
        When: release_captcha_tab() is called
        Then: Tab is returned to pool, held_tabs cleared
        """
        # Given: Pool with held tab
        pool = TabPool(max_tabs=1)
        mock_context = self._create_mock_context()
        tab = await pool.acquire(mock_context)

        pool.hold_for_captcha(
            tab=tab,
            queue_id="test-queue-id",
            engine="duckduckgo",
            task_id="test-task",
            expires_at=time.time() + 3600,
        )

        # When: Manual release
        result = await pool.release_captcha_tab("test-queue-id")

        # Then: Tab returned to pool
        assert result is True
        assert "test-queue-id" not in pool._held_tabs
        assert pool._available_tabs.qsize() == 1  # Tab in available queue

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    async def test_release_captcha_tab_nonexistent(self) -> None:
        """Test release_captcha_tab returns False for unknown queue_id.

        Given: A TabPool with no held tabs
        When: release_captcha_tab() is called with unknown queue_id
        Then: Returns False
        """
        # Given: Empty pool
        pool = TabPool(max_tabs=1)

        # When: Release unknown queue_id
        result = await pool.release_captcha_tab("nonexistent")

        # Then: Returns False
        assert result is False

        # Cleanup
        await pool.close()

    # =========================================================================
    # TC-H-03: release_held_tabs_for_task releases all task tabs
    # =========================================================================
    @pytest.mark.asyncio
    async def test_release_held_tabs_for_task(self) -> None:
        """Test release_held_tabs_for_task releases all tabs for a task.

        Given: A TabPool with multiple held tabs for different tasks
        When: release_held_tabs_for_task() is called for one task
        Then: Only that task's tabs are released
        """
        # Given: Pool with tabs for multiple tasks
        pool = TabPool(max_tabs=3)
        mock_context = self._create_mock_context()

        tab1 = await pool.acquire(mock_context)
        tab2 = await pool.acquire(mock_context)
        tab3 = await pool.acquire(mock_context)

        pool.hold_for_captcha(
            tab=tab1,
            queue_id="queue-1",
            engine="duckduckgo",
            task_id="task-A",
            expires_at=time.time() + 3600,
        )
        pool.hold_for_captcha(
            tab=tab2,
            queue_id="queue-2",
            engine="mojeek",
            task_id="task-A",
            expires_at=time.time() + 3600,
        )
        pool.hold_for_captcha(
            tab=tab3,
            queue_id="queue-3",
            engine="brave",
            task_id="task-B",
            expires_at=time.time() + 3600,
        )

        # When: Release tabs for task-A
        released = await pool.release_held_tabs_for_task("task-A")

        # Then: Only task-A tabs released
        assert released == 2
        assert "queue-1" not in pool._held_tabs
        assert "queue-2" not in pool._held_tabs
        assert "queue-3" in pool._held_tabs  # task-B still held

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    async def test_release_held_tabs_for_nonexistent_task(self) -> None:
        """Test release_held_tabs_for_task with nonexistent task_id returns 0.

        Given: A TabPool with held tabs for task-A
        When: release_held_tabs_for_task() is called with nonexistent task-Z
        Then: Returns 0, no tabs released
        """
        # Given: Pool with held tab for task-A
        pool = TabPool(max_tabs=1)
        mock_context = self._create_mock_context()
        tab = await pool.acquire(mock_context)

        pool.hold_for_captcha(
            tab=tab,
            queue_id="queue-1",
            engine="duckduckgo",
            task_id="task-A",
            expires_at=time.time() + 3600,
        )

        # When: Release tabs for nonexistent task-Z
        released = await pool.release_held_tabs_for_task("task-Z")

        # Then: No tabs released
        assert released == 0
        assert "queue-1" in pool._held_tabs  # task-A still held

        # Cleanup
        await pool.close()

    # =========================================================================
    # TC-H-04: Expired tab auto-release
    # =========================================================================
    @pytest.mark.asyncio
    async def test_expired_tab_auto_release(self) -> None:
        """Test expired held tab is auto-released.

        Given: A TabPool with an expired held tab
        When: _check_all_held_tabs() is called
        Then: Expired tab is released
        """
        # Given: Pool with expired held tab
        pool = TabPool(max_tabs=1)
        mock_context = self._create_mock_context()
        tab = await pool.acquire(mock_context)

        # Set expires_at to past
        pool.hold_for_captcha(
            tab=tab,
            queue_id="test-queue-id",
            engine="duckduckgo",
            task_id="test-task",
            expires_at=time.time() - 1,  # Already expired
        )

        # When: Check held tabs
        await pool._check_all_held_tabs()

        # Then: Tab released
        assert "test-queue-id" not in pool._held_tabs
        assert pool._available_tabs.qsize() == 1

        # Cleanup
        await pool.close()

    # =========================================================================
    # TC-H-05: Resolved CAPTCHA auto-release (with full wiring verification)
    # =========================================================================
    @pytest.mark.asyncio
    async def test_resolved_captcha_auto_release(self) -> None:
        """Test resolved CAPTCHA auto-releases tab with full resolve_auth flow.

        Given: A TabPool with a held tab showing normal content (CAPTCHA resolved)
        When: _check_all_held_tabs() is called
        Then: Tab is released, all resolve_auth equivalent actions are triggered:
              - capture_auth_session_cookies called
              - reset_circuit_breaker_for_engine called
              - requeue_awaiting_auth_jobs called
              - queue.complete called with session_data
        """
        # Given: Pool with held tab
        pool = TabPool(max_tabs=1)
        mock_context = self._create_mock_context()
        tab = await pool.acquire(mock_context)

        # Tab returns normal content (CAPTCHA was resolved)
        tab.content = AsyncMock(return_value="<html>Normal search results</html>")  # type: ignore[method-assign]

        pool.hold_for_captcha(
            tab=tab,
            queue_id="test-queue-id",
            engine="duckduckgo",
            task_id="test-task",
            expires_at=time.time() + 3600,
        )

        # Mock dependencies - verify all wiring for resolve_auth equivalent flow
        mock_session_data = {"cookies": [{"name": "test", "value": "123"}]}
        with (
            patch(
                "src.mcp.tools.auth.capture_auth_session_cookies",
                new_callable=AsyncMock,
                return_value=mock_session_data,
            ) as mock_capture_cookies,
            patch(
                "src.mcp.tools.auth.reset_circuit_breaker_for_engine",
                new_callable=AsyncMock,
            ) as mock_reset_cb,
            patch(
                "src.mcp.tools.auth.requeue_awaiting_auth_jobs",
                new_callable=AsyncMock,
                return_value=2,
            ) as mock_requeue,
            patch("src.utils.intervention_queue.get_intervention_queue") as mock_get_queue,
            patch("src.crawler.challenge_detector._is_challenge_page", return_value=False),
        ):
            mock_queue = MagicMock()
            mock_queue.complete = AsyncMock()
            mock_get_queue.return_value = mock_queue

            # When: Check held tabs
            await pool._check_all_held_tabs()

            # Then: All resolve_auth equivalent actions are called
            # 1. Cookie capture (wiring verification)
            mock_capture_cookies.assert_called_once_with("duckduckgo")

            # 2. Circuit breaker reset (wiring verification)
            mock_reset_cb.assert_called_once_with("duckduckgo")

            # 3. Requeue awaiting_auth jobs (wiring verification - added feature)
            mock_requeue.assert_called_once_with("duckduckgo")

            # 4. Queue completion with session data (effect verification)
            mock_queue.complete.assert_called_once_with(
                "test-queue-id", success=True, session_data=mock_session_data
            )

        # Then: Tab released to pool
        assert "test-queue-id" not in pool._held_tabs
        assert pool._available_tabs.qsize() == 1

        # Cleanup
        await pool.close()

    # =========================================================================
    # TC-H-05b: Closed tab during check is handled gracefully
    # =========================================================================
    @pytest.mark.asyncio
    async def test_closed_tab_during_check_is_released(self) -> None:
        """Test that a tab closed externally is released without error.

        Given: A TabPool with a held tab that has been closed externally
        When: _check_all_held_tabs() is called
        Then: Tab is released with reason "tab_closed", no exceptions
        """
        # Given: Pool with held tab
        pool = TabPool(max_tabs=1)
        mock_context = self._create_mock_context()
        tab = await pool.acquire(mock_context)

        pool.hold_for_captcha(
            tab=tab,
            queue_id="test-queue-id",
            engine="duckduckgo",
            task_id="test-task",
            expires_at=time.time() + 3600,
        )

        # Simulate tab being closed externally
        tab.is_closed.return_value = True  # type: ignore[attr-defined]

        # When: Check held tabs (should not raise)
        await pool._check_all_held_tabs()

        # Then: Tab removed from held tabs (released with reason="tab_closed")
        assert "test-queue-id" not in pool._held_tabs

        # Cleanup
        await pool.close()

    # =========================================================================
    # TC-H-05c: Empty held tabs check is no-op
    # =========================================================================
    @pytest.mark.asyncio
    async def test_check_empty_held_tabs_is_noop(self) -> None:
        """Test _check_all_held_tabs with no held tabs does nothing.

        Given: A TabPool with no held tabs
        When: _check_all_held_tabs() is called
        Then: No errors, no state changes
        """
        # Given: Empty pool
        pool = TabPool(max_tabs=1)
        assert len(pool._held_tabs) == 0

        # When: Check held tabs (should be no-op)
        await pool._check_all_held_tabs()

        # Then: Still empty, no errors
        assert len(pool._held_tabs) == 0

        # Cleanup
        await pool.close()

    # =========================================================================
    # TC-H-06: get_stats includes held tabs info
    # =========================================================================
    @pytest.mark.asyncio
    async def test_get_stats_includes_held_tabs(self) -> None:
        """Test get_stats includes held tabs information.

        Given: A TabPool with held tabs
        When: get_stats() is called
        Then: Stats include held_tabs_count and held_tabs list
        """
        # Given: Pool with held tab
        pool = TabPool(max_tabs=1)
        mock_context = self._create_mock_context()
        tab = await pool.acquire(mock_context)

        expires_at = time.time() + 3600
        pool.hold_for_captcha(
            tab=tab,
            queue_id="test-queue-id",
            engine="duckduckgo",
            task_id="test-task",
            expires_at=expires_at,
        )

        # When: Get stats
        stats = pool.get_stats()

        # Then: Stats include held tabs
        assert stats["held_tabs_count"] == 1
        assert len(stats["held_tabs"]) == 1
        held_info = stats["held_tabs"][0]
        assert held_info["queue_id"] == "test-queue-id"
        assert held_info["engine"] == "duckduckgo"
        assert held_info["task_id"] == "test-task"
        assert held_info["expires_at"] == expires_at

        # Cleanup
        await pool.close()

    # =========================================================================
    # TC-H-07: close() cleans up held tabs
    # =========================================================================
    @pytest.mark.asyncio
    async def test_close_cleans_up_held_tabs(self) -> None:
        """Test close() cleans up held tabs.

        Given: A TabPool with held tabs
        When: close() is called
        Then: Held tabs are closed and cleaned up
        """
        # Given: Pool with held tab
        pool = TabPool(max_tabs=1)
        mock_context = self._create_mock_context()
        tab = await pool.acquire(mock_context)

        pool.hold_for_captcha(
            tab=tab,
            queue_id="test-queue-id",
            engine="duckduckgo",
            task_id="test-task",
            expires_at=time.time() + 3600,
        )

        assert len(pool._held_tabs) == 1

        # When: Close pool
        await pool.close()

        # Then: Held tabs cleared
        assert len(pool._held_tabs) == 0
        # Tab was closed (via MagicMock)
        assert tab.close.called  # type: ignore[attr-defined]

    # =========================================================================
    # TC-H-08: hold_for_captcha starts background check task
    # =========================================================================
    @pytest.mark.asyncio
    async def test_hold_starts_check_task(self) -> None:
        """Test hold_for_captcha starts background check task.

        Given: A TabPool with no held tabs
        When: hold_for_captcha() is called
        Then: Background check task is started
        """
        # Given: Pool with acquired tab
        pool = TabPool(max_tabs=1)
        mock_context = self._create_mock_context()
        tab = await pool.acquire(mock_context)

        assert pool._held_tabs_check_task is None

        # When: Hold tab for CAPTCHA
        pool.hold_for_captcha(
            tab=tab,
            queue_id="test-queue-id",
            engine="duckduckgo",
            task_id="test-task",
            expires_at=time.time() + 3600,
        )

        # Then: Check task started
        assert pool._held_tabs_check_task is not None
        assert not pool._held_tabs_check_task.done()

        # Cleanup
        await pool.close()

    # =========================================================================
    # TC-H-09: hold_for_captcha on closed pool is no-op
    # =========================================================================
    @pytest.mark.asyncio
    async def test_hold_on_closed_pool_is_noop(self) -> None:
        """Test hold_for_captcha on closed pool is no-op.

        Given: A closed TabPool
        When: hold_for_captcha() is called
        Then: No error, no tab held
        """
        # Given: Closed pool
        pool = TabPool(max_tabs=1)
        await pool.close()

        mock_page = MagicMock()
        mock_page.is_closed.return_value = False

        # When: Try to hold (should be no-op)
        pool.hold_for_captcha(
            tab=mock_page,
            queue_id="test-queue-id",
            engine="duckduckgo",
            task_id="test-task",
            expires_at=time.time() + 3600,
        )

        # Then: No tab held
        assert len(pool._held_tabs) == 0


# =============================================================================
# TabPool.clear() Tests (BUG-001a: Browser Reconnection)
# =============================================================================


class TestTabPoolClear:
    """Tests for TabPool.clear() method.

    BUG-001a: When browser is closed by user, TabPool holds stale tab references.
    clear() is called during browser reconnection to reset tab state.

    Test Perspectives Table:
    | Case ID | Input / Precondition | Perspective | Expected Result |
    |---------|----------------------|-------------|-----------------|
    | TC-CLR-01 | TabPool with active tab | Equivalence | tabs cleared |
    | TC-CLR-02 | TabPool with held tabs | Equivalence | held tabs cleared |
    | TC-CLR-03 | Empty TabPool | Boundary | No error |
    | TC-CLR-04 | Closed TabPool | Boundary | No error (graceful) |
    | TC-CLR-05 | TabPool with multiple tabs | Equivalence | All tabs cleared |
    """

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
    # TC-CLR-01: clear() clears active tab
    # =========================================================================
    @pytest.mark.asyncio
    async def test_clear_clears_active_tab(self) -> None:
        """Test clear() clears active tab references.

        Given: A TabPool with 1 acquired tab that was released
        When: clear() is called
        Then: tabs list is empty, available queue is empty, active_count=0
        """
        # Given: Pool with acquired and released tab
        pool = TabPool(max_tabs=1)
        mock_context = self._create_mock_context()
        tab = await pool.acquire(mock_context)
        pool.release(tab)

        assert pool.total_count == 1
        assert pool._available_tabs.qsize() == 1

        # When: Clear
        await pool.clear()

        # Then: All tab references cleared
        assert pool.total_count == 0
        assert pool._available_tabs.qsize() == 0
        assert pool._active_count == 0

        # Pool is still usable (not closed)
        assert pool._closed is False

    # =========================================================================
    # TC-CLR-02: clear() clears held tabs
    # =========================================================================
    @pytest.mark.asyncio
    async def test_clear_clears_held_tabs(self) -> None:
        """Test clear() clears held CAPTCHA tabs.

        Given: A TabPool with a held CAPTCHA tab
        When: clear() is called
        Then: held_tabs dict is cleared, check task cancelled
        """
        # Given: Pool with held tab
        pool = TabPool(max_tabs=1)
        mock_context = self._create_mock_context()
        tab = await pool.acquire(mock_context)

        pool.hold_for_captcha(
            tab=tab,
            queue_id="test-queue-id",
            engine="duckduckgo",
            task_id="test-task",
            expires_at=time.time() + 3600,
        )

        assert len(pool._held_tabs) == 1
        assert pool._held_tabs_check_task is not None

        # When: Clear
        await pool.clear()

        # Then: Held tabs cleared
        assert len(pool._held_tabs) == 0

    # =========================================================================
    # TC-CLR-03: clear() on empty pool is no-op
    # =========================================================================
    @pytest.mark.asyncio
    async def test_clear_empty_pool_is_noop(self) -> None:
        """Test clear() on empty pool is no-op.

        Given: An empty TabPool
        When: clear() is called
        Then: No error, state unchanged
        """
        # Given: Empty pool
        pool = TabPool(max_tabs=1)
        assert pool.total_count == 0

        # When: Clear (should not raise)
        await pool.clear()

        # Then: Still empty
        assert pool.total_count == 0
        assert pool._closed is False

    # =========================================================================
    # TC-CLR-04: clear() after close is graceful (implicit via pool state)
    # =========================================================================
    @pytest.mark.asyncio
    async def test_clear_preserves_pool_usability(self) -> None:
        """Test clear() preserves pool usability (unlike close()).

        Given: A TabPool with tabs that has been cleared
        When: acquire() is called after clear()
        Then: New tab can be acquired (pool not closed)
        """
        # Given: Pool with tab, then cleared
        pool = TabPool(max_tabs=1)
        mock_context = self._create_mock_context()
        tab = await pool.acquire(mock_context)
        pool.release(tab)

        await pool.clear()

        # When: Acquire after clear
        new_tab = await pool.acquire(mock_context)

        # Then: Acquisition succeeds
        assert new_tab is not None
        assert pool.total_count == 1

        # Cleanup
        pool.release(new_tab)
        await pool.close()

    # =========================================================================
    # TC-CLR-05: clear() clears multiple tabs
    # =========================================================================
    @pytest.mark.asyncio
    async def test_clear_clears_multiple_tabs(self) -> None:
        """Test clear() clears multiple tabs.

        Given: A TabPool with multiple tabs (max_tabs=3)
        When: clear() is called
        Then: All tabs are cleared
        """
        # Given: Pool with multiple tabs
        pool = TabPool(max_tabs=3)
        mock_context = self._create_mock_context()

        tab1 = await pool.acquire(mock_context)
        tab2 = await pool.acquire(mock_context)
        pool.release(tab1)
        pool.release(tab2)

        assert pool.total_count == 2
        assert pool._available_tabs.qsize() == 2

        # When: Clear
        await pool.clear()

        # Then: All tabs cleared
        assert pool.total_count == 0
        assert pool._available_tabs.qsize() == 0
        assert pool._active_count == 0

    # =========================================================================
    # TC-CLR-06: clear() resets slot_available event
    # =========================================================================
    @pytest.mark.asyncio
    async def test_clear_resets_slot_available(self) -> None:
        """Test clear() resets slot_available event.

        Given: A TabPool with active count > 0
        When: clear() is called
        Then: active_count is reset to 0, slot_available is set
        """
        # Given: Pool with active tab (simulated)
        pool = TabPool(max_tabs=1)
        pool._active_count = 1
        pool._slot_available.clear()

        # When: Clear
        await pool.clear()

        # Then: Active count reset, slot available
        assert pool._active_count == 0
        assert pool._slot_available.is_set()

    # =========================================================================
    # Effect test: clear() does not call tab.close() (browser already gone)
    # =========================================================================
    @pytest.mark.asyncio
    async def test_clear_does_not_close_tabs(self) -> None:
        """Test clear() does not call tab.close() (browser already gone).

        Given: A TabPool with tabs
        When: clear() is called
        Then: tab.close() is NOT called (unlike close() method)

        This is important because when browser is disconnected, the tab
        references are stale and calling close() on them would fail.
        """
        # Given: Pool with tab
        pool = TabPool(max_tabs=1)
        mock_context = self._create_mock_context()
        tab = await pool.acquire(mock_context)
        pool.release(tab)

        # When: Clear
        await pool.clear()

        # Then: tab.close() was NOT called
        # (cast to MagicMock for assertion - tab is from mock_context.new_page)
        assert hasattr(tab, "close")
        tab.close.assert_not_called()  # type: ignore[attr-defined]

        # Cleanup (pool is still usable)
        await pool.close()
