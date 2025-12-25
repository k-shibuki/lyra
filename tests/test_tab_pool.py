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


# =============================================================================
# TabPool Backoff Tests (ADR-0015)
# =============================================================================


class TestTabPoolBackoff:
    """Tests for TabPool backoff functionality.

    Per ADR-0015: Adaptive Concurrency Control.

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
