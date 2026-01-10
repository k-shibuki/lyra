"""
Tests for AcademicAPIRateLimiter backoff functionality.

Per ADR-0013: Adaptive Concurrency Control.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|--------------------------------------|-----------------|-------|
| TC-R-01 | Initial state | Equivalence – normal | backoff_active=False, effective=config_max | - |
| TC-R-02 | report_429 once | Equivalence – trigger backoff | effective_max_parallel decreases | - |
| TC-R-03 | report_429 when effective=1 | Boundary – floor at 1 | effective=1 remains (floor) | - |
| TC-R-04 | Recovery after stable period | Equivalence – recovery | effective +1, up to config_max | - |
| TC-R-05 | Recovery before stable period | Boundary – too early | No recovery | - |
| TC-R-06 | report_success | Equivalence – reset counter | consecutive_429_count=0 | - |
| TC-R-07 | get_stats with backoff | Equivalence – stats | Contains backoff state | - |
| TC-W-03 | decrease_step=2 | Effect – backoff step | effective decreases by 2 | - |
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from src.search.apis.rate_limiter import (
    AcademicAPIRateLimiter,
    ProviderRateLimitConfig,
    RateLimitProfile,
    reset_academic_rate_limiter,
)


class TestAcademicAPIRateLimiterBackoff:
    """Tests for AcademicAPIRateLimiter backoff functionality."""

    @pytest.fixture(autouse=True)
    def reset_limiter(self) -> None:
        """Reset global rate limiter before each test."""
        reset_academic_rate_limiter()

    def _create_mock_academic_apis_config(
        self,
        recovery_stable_seconds: int = 60,
        decrease_step: int = 1,
    ) -> MagicMock:
        """Create mock academic APIs config for backoff settings."""
        mock_config = MagicMock()
        mock_config.retry_policy.auto_backoff.recovery_stable_seconds = recovery_stable_seconds
        mock_config.retry_policy.auto_backoff.decrease_step = decrease_step
        return mock_config

    # =========================================================================
    # TC-R-01: Initial state
    # =========================================================================
    @pytest.mark.asyncio
    async def test_initial_state(self) -> None:
        """Test initial backoff state.

        Given: A newly created AcademicAPIRateLimiter
        When: Provider is initialized
        Then: backoff_active=False, effective_max_parallel=config_max
        """
        # Given
        limiter = AcademicAPIRateLimiter()

        # Mock config to return max_parallel=3
        mock_config = ProviderRateLimitConfig(
            min_interval_seconds=0.1, max_parallel=3, profile=RateLimitProfile.ANONYMOUS
        )
        limiter._configs["test_provider"] = mock_config

        # When: Initialize provider
        await limiter._ensure_provider_initialized("test_provider")

        # Then
        backoff = limiter._backoff_states["test_provider"]
        assert backoff.backoff_active is False
        assert backoff.effective_max_parallel == 3
        assert backoff.config_max_parallel == 3
        assert backoff.consecutive_429_count == 0

    # =========================================================================
    # TC-R-02: report_429 triggers backoff
    # =========================================================================
    @pytest.mark.asyncio
    async def test_report_429_triggers_backoff(self) -> None:
        """Test that report_429 triggers backoff.

        Given: A limiter with max_parallel=3
        When: report_429 is called
        Then: effective_max_parallel decreases, backoff_active=True
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = ProviderRateLimitConfig(
            min_interval_seconds=0.1, max_parallel=3, profile=RateLimitProfile.ANONYMOUS
        )
        limiter._configs["test_provider"] = mock_config
        await limiter._ensure_provider_initialized("test_provider")

        mock_apis_config = self._create_mock_academic_apis_config(decrease_step=1)

        # When (patch at use site per test rules)
        with patch(
            "src.utils.config.get_academic_apis_config",
            return_value=mock_apis_config,
        ):
            await limiter.report_429("test_provider")

        # Then
        backoff = limiter._backoff_states["test_provider"]
        assert backoff.effective_max_parallel == 2  # 3 - 1 = 2
        assert backoff.backoff_active is True
        assert backoff.consecutive_429_count == 1

    # =========================================================================
    # TC-R-03: report_429 when effective=1 (floor)
    # =========================================================================
    @pytest.mark.asyncio
    async def test_report_429_floor_at_one(self) -> None:
        """Test that effective_max_parallel floors at 1.

        Given: A limiter with effective_max_parallel=1
        When: report_429 is called
        Then: effective_max_parallel remains 1 (floor)
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = ProviderRateLimitConfig(
            min_interval_seconds=0.1, max_parallel=1, profile=RateLimitProfile.ANONYMOUS
        )
        limiter._configs["test_provider"] = mock_config
        await limiter._ensure_provider_initialized("test_provider")

        mock_apis_config = self._create_mock_academic_apis_config(decrease_step=1)

        # When (patch at use site per test rules)
        with patch(
            "src.utils.config.get_academic_apis_config",
            return_value=mock_apis_config,
        ):
            await limiter.report_429("test_provider")

        # Then
        backoff = limiter._backoff_states["test_provider"]
        assert backoff.effective_max_parallel == 1  # Floor at 1
        # Note: backoff_active may or may not be True since no change occurred

    # =========================================================================
    # TC-R-04: Recovery after stable period
    # =========================================================================
    @pytest.mark.asyncio
    async def test_recovery_after_stable_period(self) -> None:
        """Test recovery after stable period.

        Given: A limiter in backoff state
        When: Stable period has passed and _maybe_recover is called
        Then: effective_max_parallel increases by 1
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = ProviderRateLimitConfig(
            min_interval_seconds=0.1, max_parallel=3, profile=RateLimitProfile.ANONYMOUS
        )
        limiter._configs["test_provider"] = mock_config
        await limiter._ensure_provider_initialized("test_provider")

        # Set backoff state manually
        backoff = limiter._backoff_states["test_provider"]
        backoff.effective_max_parallel = 1
        backoff.config_max_parallel = 3
        backoff.backoff_active = True
        backoff.last_429_time = time.time() - 120  # 2 minutes ago
        backoff.last_recovery_attempt = time.time() - 120

        mock_apis_config = self._create_mock_academic_apis_config(recovery_stable_seconds=60)

        # When (patch at use site per test rules)
        with patch(
            "src.utils.config.get_academic_apis_config",
            return_value=mock_apis_config,
        ):
            await limiter._maybe_recover("test_provider")

        # Then
        assert backoff.effective_max_parallel == 2  # 1 + 1 = 2 (not yet at config_max)
        assert backoff.backoff_active is True  # Still in backoff (not at max)

    # =========================================================================
    # TC-R-05: No recovery before stable period
    # =========================================================================
    @pytest.mark.asyncio
    async def test_no_recovery_before_stable_period(self) -> None:
        """Test no recovery if stable period has not passed.

        Given: A limiter in backoff state
        When: Stable period has NOT passed and _maybe_recover is called
        Then: effective_max_parallel remains unchanged
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = ProviderRateLimitConfig(
            min_interval_seconds=0.1, max_parallel=3, profile=RateLimitProfile.ANONYMOUS
        )
        limiter._configs["test_provider"] = mock_config
        await limiter._ensure_provider_initialized("test_provider")

        # Set backoff state - 429 just happened
        backoff = limiter._backoff_states["test_provider"]
        backoff.effective_max_parallel = 1
        backoff.config_max_parallel = 3
        backoff.backoff_active = True
        backoff.last_429_time = time.time() - 10  # Only 10 seconds ago
        backoff.last_recovery_attempt = time.time() - 10

        mock_apis_config = self._create_mock_academic_apis_config(recovery_stable_seconds=60)

        # When (patch at use site per test rules)
        with patch(
            "src.utils.config.get_academic_apis_config",
            return_value=mock_apis_config,
        ):
            await limiter._maybe_recover("test_provider")

        # Then
        assert backoff.effective_max_parallel == 1  # No change
        assert backoff.backoff_active is True

    # =========================================================================
    # TC-R-06: report_success resets consecutive count
    # =========================================================================
    @pytest.mark.asyncio
    async def test_report_success_resets_consecutive_count(self) -> None:
        """Test report_success resets consecutive_429_count.

        Given: A limiter with consecutive_429_count > 0
        When: report_success is called
        Then: consecutive_429_count is reset to 0
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = ProviderRateLimitConfig(
            min_interval_seconds=0.1, max_parallel=3, profile=RateLimitProfile.ANONYMOUS
        )
        limiter._configs["test_provider"] = mock_config
        await limiter._ensure_provider_initialized("test_provider")

        # Set some 429 count
        backoff = limiter._backoff_states["test_provider"]
        backoff.consecutive_429_count = 5

        # When
        limiter.report_success("test_provider")

        # Then
        assert backoff.consecutive_429_count == 0

    # =========================================================================
    # TC-R-07: get_stats includes backoff state
    # =========================================================================
    @pytest.mark.asyncio
    async def test_get_stats_includes_backoff_state(self) -> None:
        """Test get_stats includes backoff state.

        Given: A limiter with backoff active
        When: get_stats is called
        Then: Stats include effective_max_parallel, backoff_active, etc.
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = ProviderRateLimitConfig(
            min_interval_seconds=0.1, max_parallel=3, profile=RateLimitProfile.ANONYMOUS
        )
        limiter._configs["test_provider"] = mock_config
        await limiter._ensure_provider_initialized("test_provider")

        # Set backoff state
        backoff = limiter._backoff_states["test_provider"]
        backoff.effective_max_parallel = 2
        backoff.backoff_active = True
        backoff.consecutive_429_count = 3
        backoff.last_429_time = 12345.0

        # When
        stats = limiter.get_stats("test_provider")

        # Then
        assert stats["effective_max_parallel"] == 2
        assert stats["backoff_active"] is True
        assert stats["consecutive_429_count"] == 3
        assert stats["last_429_time"] == 12345.0
        assert stats["max_parallel"] == 3  # Config value

    # =========================================================================
    # TC-W-03: decrease_step=2 effect
    # =========================================================================
    @pytest.mark.asyncio
    async def test_decrease_step_effect(self) -> None:
        """Test decrease_step affects backoff amount.

        Given: A limiter with max_parallel=5 and decrease_step=2
        When: report_429 is called
        Then: effective_max_parallel decreases by 2
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = ProviderRateLimitConfig(
            min_interval_seconds=0.1, max_parallel=5, profile=RateLimitProfile.ANONYMOUS
        )
        limiter._configs["test_provider"] = mock_config
        await limiter._ensure_provider_initialized("test_provider")

        mock_apis_config = self._create_mock_academic_apis_config(decrease_step=2)

        # When (patch at use site per test rules)
        with patch(
            "src.utils.config.get_academic_apis_config",
            return_value=mock_apis_config,
        ):
            await limiter.report_429("test_provider")

        # Then
        backoff = limiter._backoff_states["test_provider"]
        assert backoff.effective_max_parallel == 3  # 5 - 2 = 3

    # =========================================================================
    # Additional: Full recovery to config_max
    # =========================================================================
    @pytest.mark.asyncio
    async def test_full_recovery_disables_backoff(self) -> None:
        """Test full recovery disables backoff_active.

        Given: A limiter at effective=2, config_max=3
        When: Recovery increases effective to config_max
        Then: backoff_active becomes False
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = ProviderRateLimitConfig(
            min_interval_seconds=0.1, max_parallel=3, profile=RateLimitProfile.ANONYMOUS
        )
        limiter._configs["test_provider"] = mock_config
        await limiter._ensure_provider_initialized("test_provider")

        # Set backoff state close to recovery
        backoff = limiter._backoff_states["test_provider"]
        backoff.effective_max_parallel = 2  # One below config_max
        backoff.config_max_parallel = 3
        backoff.backoff_active = True
        backoff.last_429_time = time.time() - 120
        backoff.last_recovery_attempt = time.time() - 120

        mock_apis_config = self._create_mock_academic_apis_config(recovery_stable_seconds=60)

        # When (patch at use site per test rules)
        with patch(
            "src.utils.config.get_academic_apis_config",
            return_value=mock_apis_config,
        ):
            await limiter._maybe_recover("test_provider")

        # Then
        assert backoff.effective_max_parallel == 3  # Recovered to config_max
        assert backoff.backoff_active is False  # Backoff disabled

    # =========================================================================
    # Test acquire respects effective_max_parallel
    # =========================================================================
    @pytest.mark.asyncio
    async def test_acquire_respects_effective_max_parallel(self) -> None:
        """Test acquire blocks when effective_max_parallel reached.

        Given: A limiter with effective_max_parallel=1
        When: Second acquire is attempted
        Then: Second acquire blocks (tested with timeout)
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = ProviderRateLimitConfig(
            min_interval_seconds=0.01, max_parallel=3, profile=RateLimitProfile.ANONYMOUS
        )
        limiter._configs["test_provider"] = mock_config
        await limiter._ensure_provider_initialized("test_provider")

        # Set effective to 1
        backoff = limiter._backoff_states["test_provider"]
        backoff.effective_max_parallel = 1

        # Mock config loading to avoid real config access (patch at use site)
        with patch(
            "src.utils.config.get_academic_apis_config",
            return_value=self._create_mock_academic_apis_config(),
        ):
            # When: First acquire succeeds
            await limiter.acquire("test_provider", timeout=1.0)
            assert limiter._active_counts["test_provider"] == 1

            # When: Second acquire should timeout (effective=1)
            with pytest.raises(TimeoutError):
                await limiter.acquire("test_provider", timeout=0.1)

            # Cleanup
            limiter.release("test_provider")
