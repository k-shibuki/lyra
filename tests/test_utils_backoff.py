"""
Tests for exponential backoff calculation utilities.

Test coverage per §7.1 (Test Strategy):
- §4.3.5: Exponential backoff calculation
- §4.3: "クールダウン≥30分"
- §3.1.4: "TTL（30〜120分）"

Test Perspectives Table:
| Case ID | Input / Precondition | Perspective | Expected Result | Notes |
|---------|---------------------|-------------|-----------------|-------|
| TC-B-01 | attempt=0, default config | Normal | ~1.0s delay | First retry |
| TC-B-02 | attempt=1, default config | Normal | ~2.0s delay | Second retry |
| TC-B-03 | attempt=5, default config | Normal | ~32.0s delay | Fifth retry |
| TC-B-04 | attempt=10, default config | Boundary | 60.0s (capped) | Max delay |
| TC-B-05 | attempt=-1 | Boundary | ValueError | Negative attempt |
| TC-B-06 | base_delay=0 | Boundary | ValueError | Invalid config |
| TC-B-07 | add_jitter=False | Normal | Exact values | Deterministic |
| TC-B-08 | add_jitter=True | Normal | ±10% variation | Jitter applied |
| TC-C-01 | failure_count=0 | Normal | 30 min | Base cooldown |
| TC-C-02 | failure_count=3 | Normal | 60 min | Second tier |
| TC-C-03 | failure_count=6 | Normal | 120 min | Third tier |
| TC-C-04 | failure_count=100 | Boundary | 120 min (capped) | Max cooldown |
| TC-C-05 | failure_count=-1 | Boundary | ValueError | Negative count |
| TC-T-01 | max_retries=3 | Normal | 7.0s total | Sum of delays |
| TC-T-02 | max_retries=0 | Boundary | 0.0s total | No retries |
"""

import random

import pytest

from src.utils.backoff import (
    BackoffConfig,
    calculate_backoff,
    calculate_cooldown_minutes,
    calculate_total_delay,
)


class TestBackoffConfig:
    """Tests for BackoffConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values per §4.3.5."""
        # Given: No arguments
        # When: Creating default config
        config = BackoffConfig()

        # Then: Default values are set
        assert config.base_delay == 1.0
        assert config.max_delay == 60.0
        assert config.exponential_base == 2.0
        assert config.jitter_factor == 0.1

    def test_custom_values(self):
        """Test custom configuration values."""
        # Given: Custom values
        # When: Creating config with custom values
        config = BackoffConfig(
            base_delay=2.0,
            max_delay=120.0,
            exponential_base=3.0,
            jitter_factor=0.2,
        )

        # Then: Custom values are set
        assert config.base_delay == 2.0
        assert config.max_delay == 120.0
        assert config.exponential_base == 3.0
        assert config.jitter_factor == 0.2

    def test_invalid_base_delay_zero(self):
        """Test that base_delay=0 raises ValueError."""
        # Given: Invalid base_delay
        # When/Then: ValueError is raised
        with pytest.raises(ValueError, match="base_delay must be positive"):
            BackoffConfig(base_delay=0)

    def test_invalid_base_delay_negative(self):
        """Test that negative base_delay raises ValueError."""
        # Given: Negative base_delay
        # When/Then: ValueError is raised
        with pytest.raises(ValueError, match="base_delay must be positive"):
            BackoffConfig(base_delay=-1.0)

    def test_invalid_max_delay_zero(self):
        """Test that max_delay=0 raises ValueError."""
        # Given: Invalid max_delay
        # When/Then: ValueError is raised
        with pytest.raises(ValueError, match="max_delay must be positive"):
            BackoffConfig(max_delay=0)

    def test_invalid_max_delay_less_than_base(self):
        """Test that max_delay < base_delay raises ValueError."""
        # Given: max_delay less than base_delay
        # When/Then: ValueError is raised
        with pytest.raises(ValueError, match="max_delay must be >= base_delay"):
            BackoffConfig(base_delay=10.0, max_delay=5.0)

    def test_invalid_exponential_base(self):
        """Test that exponential_base <= 1 raises ValueError."""
        # Given: Invalid exponential_base
        # When/Then: ValueError is raised
        with pytest.raises(ValueError, match="exponential_base must be > 1"):
            BackoffConfig(exponential_base=1.0)

    def test_invalid_jitter_factor_negative(self):
        """Test that negative jitter_factor raises ValueError."""
        # Given: Negative jitter_factor
        # When/Then: ValueError is raised
        with pytest.raises(ValueError, match="jitter_factor must be between 0 and 1"):
            BackoffConfig(jitter_factor=-0.1)

    def test_invalid_jitter_factor_too_large(self):
        """Test that jitter_factor > 1 raises ValueError."""
        # Given: jitter_factor too large
        # When/Then: ValueError is raised
        with pytest.raises(ValueError, match="jitter_factor must be between 0 and 1"):
            BackoffConfig(jitter_factor=1.5)

    def test_config_is_frozen(self):
        """Test that BackoffConfig is immutable."""
        # Given: A config instance
        config = BackoffConfig()

        # When/Then: Attempting to modify raises FrozenInstanceError
        with pytest.raises(dataclasses.FrozenInstanceError):
            config.base_delay = 5.0


class TestCalculateBackoff:
    """Tests for calculate_backoff function."""

    def test_first_retry_default_config(self):
        """TC-B-01: First retry with default config returns ~1.0s."""
        # Given: attempt=0, default config, no jitter
        # When: Calculating backoff
        delay = calculate_backoff(0, add_jitter=False)

        # Then: Delay equals base_delay (1.0)
        assert delay == 1.0

    def test_second_retry_default_config(self):
        """TC-B-02: Second retry with default config returns ~2.0s."""
        # Given: attempt=1, default config, no jitter
        # When: Calculating backoff
        delay = calculate_backoff(1, add_jitter=False)

        # Then: Delay equals base_delay * 2^1 = 2.0
        assert delay == 2.0

    def test_fifth_retry_default_config(self):
        """TC-B-03: Fifth retry with default config returns ~32.0s."""
        # Given: attempt=5, default config, no jitter
        # When: Calculating backoff
        delay = calculate_backoff(5, add_jitter=False)

        # Then: Delay equals base_delay * 2^5 = 32.0
        assert delay == 32.0

    def test_max_delay_cap(self):
        """TC-B-04: Delay is capped at max_delay."""
        # Given: High attempt number, default config
        # When: Calculating backoff
        delay = calculate_backoff(10, add_jitter=False)

        # Then: Delay is capped at max_delay (60.0)
        assert delay == 60.0

    def test_negative_attempt_raises_error(self):
        """TC-B-05: Negative attempt raises ValueError."""
        # Given: Negative attempt
        # When/Then: ValueError is raised
        with pytest.raises(ValueError, match="attempt must be non-negative"):
            calculate_backoff(-1)

    def test_jitter_disabled(self):
        """TC-B-07: Jitter disabled returns exact values."""
        # Given: Multiple attempts with jitter disabled
        # When: Calculating backoffs
        delays = [calculate_backoff(i, add_jitter=False) for i in range(5)]

        # Then: Values are exact powers of 2
        assert delays == [1.0, 2.0, 4.0, 8.0, 16.0]

    def test_jitter_enabled(self):
        """TC-B-08: Jitter enabled adds ±10% variation."""
        # Given: Fixed random seed for reproducibility
        random.seed(42)
        config = BackoffConfig(jitter_factor=0.1)

        # When: Calculating backoff multiple times
        delays = [calculate_backoff(2, config, add_jitter=True) for _ in range(100)]

        # Then: All delays are within ±10% of base value (4.0)
        base_value = 4.0
        min_expected = base_value * 0.9
        max_expected = base_value * 1.1

        for delay in delays:
            assert min_expected <= delay <= max_expected, (
                f"Delay {delay} outside ±10% of {base_value}"
            )

    def test_custom_config(self):
        """Test backoff with custom configuration."""
        # Given: Custom config
        config = BackoffConfig(
            base_delay=2.0,
            max_delay=100.0,
            exponential_base=3.0,
        )

        # When: Calculating backoffs
        delays = [calculate_backoff(i, config, add_jitter=False) for i in range(4)]

        # Then: Values follow custom base (3^n)
        assert delays == [2.0, 6.0, 18.0, 54.0]

    def test_default_config_used_when_none(self):
        """Test that default config is used when config is None."""
        # Given: No config provided
        # When: Calculating backoff
        delay = calculate_backoff(0, None, add_jitter=False)

        # Then: Default base_delay is used
        assert delay == 1.0

    def test_delay_never_negative(self):
        """Test that delay is never negative even with large negative jitter."""
        # Given: Config with large jitter (edge case)
        config = BackoffConfig(jitter_factor=0.9)

        # When: Calculating many backoffs
        random.seed(42)
        delays = [calculate_backoff(0, config, add_jitter=True) for _ in range(1000)]

        # Then: No delay is negative
        assert all(d >= 0.0 for d in delays), "Delay should never be negative"


class TestCalculateCooldownMinutes:
    """Tests for calculate_cooldown_minutes function."""

    def test_zero_failures(self):
        """TC-C-01: Zero failures returns base cooldown per §4.3."""
        # Given: No failures
        # When: Calculating cooldown
        cooldown = calculate_cooldown_minutes(0)

        # Then: Base cooldown (30 min) is returned
        assert cooldown == 30

    def test_first_tier_failures(self):
        """Test failures 1-2 return base cooldown."""
        # Given: Failures in first tier (0-2)
        # When: Calculating cooldowns
        cooldowns = [calculate_cooldown_minutes(i) for i in range(3)]

        # Then: All return base cooldown
        assert all(c == 30 for c in cooldowns)

    def test_second_tier_failures(self):
        """TC-C-02: 3-5 failures return doubled cooldown."""
        # Given: Failures in second tier
        # When: Calculating cooldowns
        cooldowns = [calculate_cooldown_minutes(i) for i in range(3, 6)]

        # Then: Cooldown is 30 * 2 = 60
        assert all(c == 60 for c in cooldowns)

    def test_third_tier_failures(self):
        """TC-C-03: 6-8 failures return quadrupled cooldown (capped)."""
        # Given: Failures in third tier
        # When: Calculating cooldowns
        cooldowns = [calculate_cooldown_minutes(i) for i in range(6, 9)]

        # Then: Cooldown is min(30 * 4, 120) = 120
        assert all(c == 120 for c in cooldowns)

    def test_max_cooldown_cap(self):
        """TC-C-04: High failure count is capped at max."""
        # Given: Very high failure count
        # When: Calculating cooldown
        cooldown = calculate_cooldown_minutes(100)

        # Then: Capped at 120 minutes
        assert cooldown == 120

    def test_negative_failures_raises_error(self):
        """TC-C-05: Negative failure count raises ValueError."""
        # Given: Negative failure count
        # When/Then: ValueError is raised
        with pytest.raises(ValueError, match="failure_count must be non-negative"):
            calculate_cooldown_minutes(-1)

    def test_custom_base_and_max(self):
        """Test custom base and max cooldown values."""
        # Given: Custom values
        # When: Calculating cooldown
        cooldown = calculate_cooldown_minutes(6, base_minutes=60, max_minutes=300)

        # Then: 60 * 4 = 240 (within max)
        assert cooldown == 240

    def test_custom_max_caps_result(self):
        """Test that custom max_minutes caps the result."""
        # Given: Custom max that is lower than calculated
        # When: Calculating cooldown
        cooldown = calculate_cooldown_minutes(6, base_minutes=60, max_minutes=100)

        # Then: Capped at custom max
        assert cooldown == 100

    def test_invalid_base_minutes(self):
        """Test that invalid base_minutes raises ValueError."""
        # Given: Zero base_minutes
        # When/Then: ValueError is raised
        with pytest.raises(ValueError, match="base_minutes must be positive"):
            calculate_cooldown_minutes(0, base_minutes=0)

    def test_invalid_max_minutes(self):
        """Test that invalid max_minutes raises ValueError."""
        # Given: Zero max_minutes
        # When/Then: ValueError is raised
        with pytest.raises(ValueError, match="max_minutes must be positive"):
            calculate_cooldown_minutes(0, max_minutes=0)

    def test_max_less_than_base_raises_error(self):
        """Test that max_minutes < base_minutes raises ValueError."""
        # Given: max_minutes less than base_minutes
        # When/Then: ValueError is raised
        with pytest.raises(ValueError, match="max_minutes must be >= base_minutes"):
            calculate_cooldown_minutes(0, base_minutes=60, max_minutes=30)


class TestCalculateTotalDelay:
    """Tests for calculate_total_delay function."""

    def test_three_retries(self):
        """TC-T-01: Total delay for 3 retries is 7.0s."""
        # Given: 3 retries with default config
        # When: Calculating total delay
        total = calculate_total_delay(3)

        # Then: 1 + 2 + 4 = 7.0
        assert total == 7.0

    def test_zero_retries(self):
        """TC-T-02: Zero retries returns 0.0s."""
        # Given: No retries
        # When: Calculating total delay
        total = calculate_total_delay(0)

        # Then: Total is 0.0
        assert total == 0.0

    def test_five_retries(self):
        """Test total delay for 5 retries."""
        # Given: 5 retries with default config
        # When: Calculating total delay
        total = calculate_total_delay(5)

        # Then: 1 + 2 + 4 + 8 + 16 = 31.0
        assert total == 31.0

    def test_with_max_delay_cap(self):
        """Test total delay with values hitting max_delay cap."""
        # Given: Many retries, some will hit cap
        config = BackoffConfig(base_delay=1.0, max_delay=10.0)

        # When: Calculating total delay
        total = calculate_total_delay(6, config)

        # Then: 1 + 2 + 4 + 8 + 10 + 10 = 35.0 (last two capped)
        assert total == 35.0

    def test_custom_config(self):
        """Test total delay with custom configuration."""
        # Given: Custom config
        config = BackoffConfig(
            base_delay=2.0,
            max_delay=100.0,
            exponential_base=2.0,
        )

        # When: Calculating total delay
        total = calculate_total_delay(3, config)

        # Then: 2 + 4 + 8 = 14.0
        assert total == 14.0

    def test_negative_retries_raises_error(self):
        """Test that negative max_retries raises ValueError."""
        # Given: Negative max_retries
        # When/Then: ValueError is raised
        with pytest.raises(ValueError, match="max_retries must be non-negative"):
            calculate_total_delay(-1)


class TestSpecCompliance:
    """Tests for compliance with specification sections."""

    def test_spec_4_3_5_backoff_formula(self):
        """Test §4.3.5 formula: delay = min(base_delay * (2 ^ attempt), max_delay)."""
        # Given: Various attempts
        config = BackoffConfig(base_delay=1.0, max_delay=60.0, exponential_base=2.0)

        # When/Then: Formula is correctly applied
        assert calculate_backoff(0, config, add_jitter=False) == 1.0  # 1 * 2^0 = 1
        assert calculate_backoff(1, config, add_jitter=False) == 2.0  # 1 * 2^1 = 2
        assert calculate_backoff(2, config, add_jitter=False) == 4.0  # 1 * 2^2 = 4
        assert calculate_backoff(6, config, add_jitter=False) == 60.0  # capped

    def test_spec_4_3_5_cooldown_formula(self):
        """Test §4.3.5 formula: cooldown = min(base * (2 ^ (failures // 3)), max)."""
        # Given: Various failure counts
        # When/Then: Formula is correctly applied
        assert calculate_cooldown_minutes(0) == 30  # 30 * 2^0 = 30
        assert calculate_cooldown_minutes(3) == 60  # 30 * 2^1 = 60
        assert calculate_cooldown_minutes(6) == 120  # 30 * 2^2 = 120
        assert calculate_cooldown_minutes(9) == 120  # capped at 4x (factor limit)

    def test_spec_4_3_minimum_cooldown(self):
        """Test §4.3 requirement: クールダウン≥30分."""
        # Given: Any failure count
        # When: Calculating cooldown
        cooldown = calculate_cooldown_minutes(0)

        # Then: Cooldown is at least 30 minutes
        assert cooldown >= 30

    def test_spec_3_1_4_cooldown_range(self):
        """Test §3.1.4 requirement: TTL（30〜120分）."""
        # Given: Various failure counts
        # When: Calculating cooldowns
        cooldowns = [calculate_cooldown_minutes(i) for i in range(20)]

        # Then: All cooldowns are within 30-120 range
        assert all(30 <= c <= 120 for c in cooldowns)

    def test_spec_4_3_5_jitter_prevents_thundering_herd(self):
        """Test that jitter provides variation per §4.3.5."""
        # Given: Same attempt, multiple calculations
        random.seed(42)
        config = BackoffConfig(jitter_factor=0.1)

        # When: Calculating many backoffs
        delays = [calculate_backoff(3, config, add_jitter=True) for _ in range(50)]

        # Then: Delays vary (not all identical) - prevents thundering herd
        unique_delays = {round(d, 6) for d in delays}
        assert len(unique_delays) > 1, "Jitter should provide variation"
