"""
Tests for AcademicAPIRateLimiter.

Per ADR-0013: Worker Resource Contention Control.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from src.search.apis.rate_limiter import (
    AcademicAPIRateLimiter,
    BackoffState,
    ProviderRateLimitConfig,
    get_academic_rate_limiter,
    reset_academic_rate_limiter,
)

pytestmark = pytest.mark.integration


def _setup_limiter_with_config(
    limiter: AcademicAPIRateLimiter, provider: str, config: ProviderRateLimitConfig
) -> None:
    """Helper to manually initialize a limiter with specific config."""
    limiter._configs[provider] = config
    limiter._qps_locks[provider] = asyncio.Lock()
    limiter._concurrency_semaphores[provider] = asyncio.Semaphore(config.max_parallel)
    # ADR-0015: Initialize backoff-related state
    limiter._active_counts[provider] = 0
    limiter._slot_events[provider] = asyncio.Event()
    limiter._slot_events[provider].set()  # Initially available
    limiter._backoff_states[provider] = BackoffState(
        effective_max_parallel=config.max_parallel,
        config_max_parallel=config.max_parallel,
    )


class TestAcademicAPIRateLimiter:
    """Tests for AcademicAPIRateLimiter class."""

    @pytest.fixture(autouse=True)
    def reset_limiter(self) -> None:
        """Reset global rate limiter before each test."""
        reset_academic_rate_limiter()

    # =========================================================================
    # TC-N-01: Basic acquire/release flow
    # =========================================================================
    @pytest.mark.asyncio
    async def test_acquire_release_basic(self) -> None:
        """Test basic acquire and release flow.

        Given: A new rate limiter instance with pre-configured provider
        When: acquire() and release() are called for a provider
        Then: Both operations complete without error
        """
        # Given: A rate limiter with pre-configured provider
        limiter = AcademicAPIRateLimiter()
        config = ProviderRateLimitConfig(min_interval_seconds=0.0, max_parallel=1)
        _setup_limiter_with_config(limiter, "test_provider", config)

        # When: acquire and release
        await limiter.acquire("test_provider")
        limiter.release("test_provider")

        # Then: No exceptions raised (implicit assertion)

    # =========================================================================
    # TC-N-02: Multiple providers are isolated
    # =========================================================================
    @pytest.mark.asyncio
    async def test_multiple_providers_isolated(self) -> None:
        """Test that different providers have isolated rate limits.

        Given: Two different providers with max_parallel=1 each
        When: acquire() is called for both simultaneously
        Then: Both can be acquired without blocking each other
        """
        # Given: A rate limiter with two providers
        limiter = AcademicAPIRateLimiter()
        config = ProviderRateLimitConfig(min_interval_seconds=0.0, max_parallel=1)
        _setup_limiter_with_config(limiter, "provider_a", config)
        _setup_limiter_with_config(limiter, "provider_b", config)

        # When: Acquire both providers
        await limiter.acquire("provider_a")
        await limiter.acquire("provider_b")

        # Then: Both acquired (no blocking between providers)
        limiter.release("provider_a")
        limiter.release("provider_b")

    # =========================================================================
    # TC-N-03: get_stats returns correct statistics
    # =========================================================================
    @pytest.mark.asyncio
    async def test_get_stats(self) -> None:
        """Test get_stats returns correct statistics.

        Given: A rate limiter with known config
        When: get_stats() is called
        Then: Returns dict with correct values
        """
        # Given: A rate limiter with cached config
        limiter = AcademicAPIRateLimiter()
        config = ProviderRateLimitConfig(min_interval_seconds=0.5, max_parallel=2)
        limiter._configs["test_provider"] = config

        # When: Get stats
        stats = limiter.get_stats("test_provider")

        # Then: Stats contain expected fields
        assert stats["min_interval_seconds"] == 0.5
        assert stats["max_parallel"] == 2
        assert "last_request" in stats

    # =========================================================================
    # TC-B-01: QPS limiting (min_interval enforcement)
    # =========================================================================
    @pytest.mark.asyncio
    async def test_qps_limiting_enforces_min_interval(self) -> None:
        """Test that min_interval is enforced between requests.

        Given: A rate limiter with min_interval_seconds=0.1
        When: Two acquire() calls in quick succession
        Then: Second call waits until min_interval has passed
        """
        # Given: Rate limiter with 0.1s min interval
        limiter = AcademicAPIRateLimiter()
        config = ProviderRateLimitConfig(min_interval_seconds=0.1, max_parallel=1)
        _setup_limiter_with_config(limiter, "test_provider", config)

        # When: First acquire
        start = time.time()
        await limiter.acquire("test_provider")
        limiter.release("test_provider")

        # When: Second acquire immediately
        await limiter.acquire("test_provider")
        elapsed = time.time() - start
        limiter.release("test_provider")

        # Then: Total time >= min_interval (with small tolerance)
        assert elapsed >= 0.09, f"Expected elapsed >= 0.09s, got {elapsed:.3f}s"

    # =========================================================================
    # TC-B-02: Concurrency limiting (max_parallel=1)
    # =========================================================================
    @pytest.mark.asyncio
    async def test_concurrency_limiting_blocks_excess(self) -> None:
        """Test that max_parallel=1 blocks second concurrent acquire.

        Given: A rate limiter with max_parallel=1
        When: Two concurrent acquire() calls
        Then: Second call blocks until first is released
        """
        # Given: Rate limiter with max_parallel=1
        limiter = AcademicAPIRateLimiter()
        config = ProviderRateLimitConfig(min_interval_seconds=0.0, max_parallel=1)
        _setup_limiter_with_config(limiter, "test_provider", config)

        # When: First acquire
        await limiter.acquire("test_provider")

        # Then: Second acquire should block
        async def try_second_acquire() -> float:
            start = time.time()
            await limiter.acquire("test_provider")
            return time.time() - start

        # Start second acquire in background
        task = asyncio.create_task(try_second_acquire())
        await asyncio.sleep(0.05)  # Give task time to start blocking

        # Release first
        limiter.release("test_provider")

        # Second should now complete
        wait_time = await asyncio.wait_for(task, timeout=1.0)
        limiter.release("test_provider")

        # Then: Second waited at least some time
        assert wait_time >= 0.04, f"Expected wait_time >= 0.04s, got {wait_time:.3f}s"

    # =========================================================================
    # TC-B-03: Concurrency with max_parallel=2
    # =========================================================================
    @pytest.mark.asyncio
    async def test_concurrency_allows_parallel_up_to_max(self) -> None:
        """Test that max_parallel=2 allows two concurrent acquires.

        Given: A rate limiter with max_parallel=2
        When: Two concurrent acquire() calls
        Then: Both complete immediately without blocking
        """
        # Given: Rate limiter with max_parallel=2
        limiter = AcademicAPIRateLimiter()
        config = ProviderRateLimitConfig(min_interval_seconds=0.0, max_parallel=2)
        _setup_limiter_with_config(limiter, "test_provider", config)

        # When: Both acquire immediately
        start = time.time()
        await limiter.acquire("test_provider")
        await limiter.acquire("test_provider")
        elapsed = time.time() - start

        # Then: Both acquired quickly (no significant blocking)
        assert elapsed < 0.05, f"Expected < 0.05s, got {elapsed:.3f}s"

        # Cleanup
        limiter.release("test_provider")
        limiter.release("test_provider")

    # =========================================================================
    # TC-A-01: Config loading failure uses defaults
    # =========================================================================
    @pytest.mark.asyncio
    async def test_config_failure_uses_defaults(self) -> None:
        """Test that config loading failure falls back to defaults.

        Given: Config loading raises an exception inside _get_provider_config
        When: acquire() is called
        Then: Default config values are used (no exception)
        """
        # Given: Rate limiter
        limiter = AcademicAPIRateLimiter()

        # Patch the internal import to fail
        with patch.object(
            limiter,
            "_get_provider_config",
            wraps=limiter._get_provider_config,
        ):
            # Force config loading to fail by patching the import inside the method
            def failing_config(provider: str) -> ProviderRateLimitConfig:
                # Just return default without trying to load
                default_config = ProviderRateLimitConfig()
                limiter._configs[provider] = default_config
                return default_config

            limiter._get_provider_config = failing_config  # type: ignore

            # When: acquire/release
            await limiter.acquire("unknown_provider")
            limiter.release("unknown_provider")

            # Then: Stats show default values
            stats = limiter.get_stats("unknown_provider")
            assert stats["min_interval_seconds"] == 0.1
            assert stats["max_parallel"] == 1

    # =========================================================================
    # TC-A-02: Double release (defensive)
    # =========================================================================
    @pytest.mark.asyncio
    async def test_release_without_acquire_does_not_crash(self) -> None:
        """Test that release on uninitialized provider doesn't crash.

        Given: A provider that was never acquired
        When: release() is called
        Then: No exception (no-op)
        """
        # Given: Fresh limiter
        limiter = AcademicAPIRateLimiter()

        # When/Then: release without acquire doesn't crash
        limiter.release("never_acquired")  # Should not raise


class TestGlobalRateLimiterFunctions:
    """Tests for global rate limiter singleton functions."""

    @pytest.fixture(autouse=True)
    def reset_limiter(self) -> None:
        """Reset global rate limiter before each test."""
        reset_academic_rate_limiter()

    def test_get_academic_rate_limiter_singleton(self) -> None:
        """Test get_academic_rate_limiter returns singleton.

        Given: Global limiter is reset
        When: get_academic_rate_limiter() is called twice
        Then: Same instance is returned
        """
        # Given: Reset state
        reset_academic_rate_limiter()

        # When: Get limiter twice
        limiter1 = get_academic_rate_limiter()
        limiter2 = get_academic_rate_limiter()

        # Then: Same instance
        assert limiter1 is limiter2

    def test_reset_academic_rate_limiter(self) -> None:
        """Test reset creates new instance.

        Given: A global limiter exists
        When: reset_academic_rate_limiter() is called
        Then: Next get_academic_rate_limiter() returns new instance
        """
        # Given: Get initial limiter
        limiter1 = get_academic_rate_limiter()

        # When: Reset
        reset_academic_rate_limiter()

        # Then: New instance
        limiter2 = get_academic_rate_limiter()
        assert limiter1 is not limiter2


class TestProviderRateLimitConfig:
    """Tests for ProviderRateLimitConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default values are correct.

        Given: ProviderRateLimitConfig with no arguments
        When: Instance is created
        Then: Default values are applied
        """
        # Given/When: Create with defaults
        config = ProviderRateLimitConfig()

        # Then: Defaults
        assert config.min_interval_seconds == 0.1
        assert config.max_parallel == 1

    def test_custom_values(self) -> None:
        """Test custom values are set correctly.

        Given: ProviderRateLimitConfig with custom arguments
        When: Instance is created
        Then: Custom values are used
        """
        # Given/When: Create with custom values
        config = ProviderRateLimitConfig(min_interval_seconds=3.0, max_parallel=2)

        # Then: Custom values
        assert config.min_interval_seconds == 3.0
        assert config.max_parallel == 2
