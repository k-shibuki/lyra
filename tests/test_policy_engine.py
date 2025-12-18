"""
Tests for policy engine module.
Tests PolicyEngine, ParameterState, and auto-adjustment logic.

Related spec: §4.6 Policy Auto-update (Closed-loop Control)

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-PB-N-01 | All PolicyParameters | Equivalence – normal | All have DEFAULT_BOUNDS | - |
| TC-PB-N-02 | Each bound definition | Equivalence – normal | min < max, default in range, steps > 0 | - |
| TC-PS-N-01 | New ParameterState | Equivalence – normal | Initial values correct | - |
| TC-PS-N-02 | State with old change | Equivalence – normal | can_change returns True | - |
| TC-PS-B-01 | State with recent change | Boundary – time threshold | can_change returns False | - |
| TC-PS-N-03 | apply_change in bounds | Equivalence – normal | Value applied as-is | - |
| TC-PS-B-02 | apply_change exceeds max | Boundary – max value | Clamped to max | - |
| TC-PS-B-03 | apply_change below min | Boundary – min value | Clamped to min | - |
| TC-PU-N-01 | PolicyUpdate creation | Equivalence – normal | All fields set correctly | - |
| TC-PE-N-01 | PolicyEngine init | Equivalence – normal | Parameters stored | - |
| TC-PE-N-02 | Get unset parameter | Equivalence – normal | Returns default value | - |
| TC-PE-N-03 | Set parameter value | Equivalence – normal | Value updated, update returned | - |
| TC-PE-N-04 | Get history (empty) | Boundary – empty | Returns empty list | - |
| TC-PE-N-05 | Low success rate metric | Equivalence – normal | Weight decreased | - |
| TC-PE-N-06 | High error rate metric | Equivalence – normal | Headful ratio increased | - |
| TC-PE-B-04 | Change within hysteresis | Boundary – time interval | Change prevented | - |
| TC-PE-N-07 | Start/stop engine | Equivalence – normal | Running state toggled | - |
| TC-PE-N-08 | get_policy_engine() | Equivalence – normal | Returns singleton | - |
"""

import asyncio
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.utils.policy_engine import (
    PolicyEngine,
    PolicyParameter,
    ParameterBounds,
    ParameterState,
    PolicyUpdate,
    DEFAULT_BOUNDS,
    get_policy_engine,
)
from src.utils.metrics import MetricsCollector, MetricValue


pytestmark = pytest.mark.unit


class TestParameterBounds:
    """Tests for ParameterBounds."""

    def test_default_bounds_exist(self):
        """Test that default bounds are defined for all parameters."""
        # Given: All defined PolicyParameter enum values
        # When: Checking DEFAULT_BOUNDS dictionary
        # Then: Each parameter has corresponding bounds
        for param in PolicyParameter:
            assert param in DEFAULT_BOUNDS, f"Missing bounds for {param}"

    def test_bounds_values_valid(self):
        """Test that bounds values are valid."""
        # Given: All parameter bounds in DEFAULT_BOUNDS
        # When: Validating each bound's constraints
        # Then: min < max, default in range, steps positive
        for param, bounds in DEFAULT_BOUNDS.items():
            assert bounds.min_value < bounds.max_value, f"Invalid bounds for {param}"
            assert bounds.min_value <= bounds.default_value <= bounds.max_value
            assert bounds.step_up > 0
            assert bounds.step_down > 0


class TestParameterState:
    """Tests for ParameterState."""

    def test_initial_state(self):
        """Test initial parameter state."""
        # Given: A new ParameterState with value 0.5
        state = ParameterState(current_value=0.5)

        # When: Checking initial values
        # Then: Default values are set correctly
        assert state.current_value == 0.5
        assert state.last_direction == "none"
        assert state.change_count == 0

    def test_can_change_immediately(self):
        """Test that new state can change immediately."""
        # Given: A state with last change 10 minutes ago
        state = ParameterState(current_value=0.5)
        state.last_changed_at = datetime.now(timezone.utc) - timedelta(minutes=10)

        # When: Checking if change is allowed (5 min interval)
        # Then: Change is permitted
        assert state.can_change(min_interval_seconds=300)  # 5 minutes

    def test_cannot_change_too_soon(self):
        """Test that recent changes block further changes."""
        # Given: A state with last change 60 seconds ago
        state = ParameterState(current_value=0.5)
        state.last_changed_at = datetime.now(timezone.utc) - timedelta(seconds=60)

        # When: Checking if change is allowed (5 min interval)
        # Then: Change is blocked
        assert not state.can_change(min_interval_seconds=300)

    def test_apply_change_within_bounds(self):
        """Test applying a change within bounds."""
        # Given: A state at 0.5 with bounds [0.0, 1.0]
        state = ParameterState(current_value=0.5)
        bounds = ParameterBounds(
            min_value=0.0,
            max_value=1.0,
            default_value=0.5,
            step_up=0.1,
            step_down=0.1,
        )

        # When: Applying change to 0.7 (within bounds)
        result = state.apply_change(0.7, "up", bounds)

        # Then: Value is applied, state updated
        assert result == 0.7
        assert state.current_value == 0.7
        assert state.last_direction == "up"
        assert state.change_count == 1

    def test_apply_change_clamped_max(self):
        """Test that changes are clamped to max bound."""
        # Given: A state at 0.9 with max bound 1.0
        state = ParameterState(current_value=0.9)
        bounds = ParameterBounds(
            min_value=0.0,
            max_value=1.0,
            default_value=0.5,
            step_up=0.1,
            step_down=0.1,
        )

        # When: Applying change to 1.5 (exceeds max)
        result = state.apply_change(1.5, "up", bounds)

        # Then: Value is clamped to max (1.0)
        assert result == 1.0
        assert state.current_value == 1.0

    def test_apply_change_clamped_min(self):
        """Test that changes are clamped to min bound."""
        # Given: A state at 0.1 with min bound 0.0
        state = ParameterState(current_value=0.1)
        bounds = ParameterBounds(
            min_value=0.0,
            max_value=1.0,
            default_value=0.5,
            step_up=0.1,
            step_down=0.1,
        )

        # When: Applying change to -0.5 (below min)
        result = state.apply_change(-0.5, "down", bounds)

        # Then: Value is clamped to min (0.0)
        assert result == 0.0
        assert state.current_value == 0.0


class TestPolicyUpdate:
    """Tests for PolicyUpdate dataclass."""

    def test_policy_update_creation(self):
        """Test creating a policy update record."""
        # Given: Valid parameters for a policy update
        # When: Creating a PolicyUpdate instance
        update = PolicyUpdate(
            timestamp=datetime.now(timezone.utc),
            target_type="engine",
            target_id="google",
            parameter="engine_weight",
            old_value=1.0,
            new_value=0.8,
            reason="Low success rate",
            metrics_snapshot={"success_rate": 0.4},
        )

        # Then: All fields are set correctly
        assert update.target_type == "engine"
        assert update.target_id == "google"
        assert update.old_value == 1.0
        assert update.new_value == 0.8


@pytest.mark.asyncio
class TestPolicyEngine:
    """Tests for PolicyEngine class."""

    async def test_engine_initialization(self):
        """Test policy engine initialization."""
        # Given: A MetricsCollector and configuration values
        collector = MetricsCollector()

        # When: Creating a PolicyEngine with custom intervals
        engine = PolicyEngine(
            metrics_collector=collector,
            update_interval=60,
            hysteresis_interval=300,
        )

        # Then: Configuration is stored correctly
        assert engine._update_interval == 60
        assert engine._hysteresis_interval == 300

    async def test_get_parameter_value_default(self):
        """Test getting default parameter value."""
        # Given: A new PolicyEngine with no parameter overrides
        collector = MetricsCollector()
        engine = PolicyEngine(metrics_collector=collector)

        # When: Getting a parameter value that hasn't been set
        value = engine.get_parameter_value(
            "engine", "test", PolicyParameter.ENGINE_WEIGHT
        )

        # Then: Returns the default value from bounds
        assert value == DEFAULT_BOUNDS[PolicyParameter.ENGINE_WEIGHT].default_value

    async def test_set_parameter_value(self):
        """Test manually setting parameter value."""
        # Given: A PolicyEngine with mocked database
        collector = MetricsCollector()
        engine = PolicyEngine(metrics_collector=collector)

        # When: Setting a parameter value manually
        with patch("src.storage.database.get_database") as mock_db:
            mock_db.return_value = AsyncMock()
            mock_db.return_value.execute = AsyncMock()
            mock_db.return_value.log_event = AsyncMock()

            update = await engine.set_parameter_value(
                "domain",
                "example.com",
                PolicyParameter.HEADFUL_RATIO,
                0.3,
                reason="Manual test",
            )

            # Then: Update record reflects the change
            assert update.new_value == 0.3
            assert update.reason == "Manual test"

    async def test_get_update_history(self):
        """Test getting update history returns empty list initially."""
        # Given: A new PolicyEngine with no updates
        collector = MetricsCollector()
        engine = PolicyEngine(metrics_collector=collector)

        # When: Getting update history
        history = engine.get_update_history(limit=10)

        # Then: Returns empty list
        assert history == [], f"Expected empty list for new engine, got {history}"

    async def test_adjust_engine_policy_low_success(self):
        """Test engine policy adjustment on low success rate.

        Related spec: §4.6 Policy Auto-update
        """
        # Given: PolicyEngine with hysteresis disabled and low success metrics
        collector = MetricsCollector()
        engine = PolicyEngine(
            metrics_collector=collector,
            hysteresis_interval=0,  # Disabled to test adjustment logic without timing
        )

        # Simulate low success rate metrics (0.3 < 0.5 threshold)
        collector._engine_metrics["test_engine"] = {
            "success_rate": MetricValue(
                raw_value=0.3,
                ema_short=0.3,
                ema_long=0.4,
                sample_count=10,
            ),
            "latency_ms": MetricValue(
                raw_value=1500,
                ema_short=1500,
                ema_long=1200,
                sample_count=10,
            ),
        }

        # When: Adjusting engine policy
        updates = await engine._adjust_engine_policy("test_engine")

        # Then: Engine weight should decrease
        weight_updates = [u for u in updates if u.parameter == "engine_weight"]
        assert len(weight_updates) == 1, f"Expected 1 weight update, got {len(weight_updates)}"
        assert weight_updates[0].new_value < weight_updates[0].old_value, (
            f"Weight should decrease: {weight_updates[0].old_value} -> {weight_updates[0].new_value}"
        )

    async def test_adjust_domain_policy_high_error(self):
        """Test domain policy adjustment on high error rate.

        Related spec: §4.6 Policy Auto-update, §4.3 Resilience and Stealth
        """
        # Given: PolicyEngine with hysteresis disabled and high error metrics
        collector = MetricsCollector()
        engine = PolicyEngine(
            metrics_collector=collector,
            hysteresis_interval=0,  # Disabled to test adjustment logic without timing
        )

        # Simulate high error rates (combined = 0.4 + 0.2 + 0.1 = 0.7 > 0.3)
        collector._domain_metrics["blocked.com"] = {
            "captcha_rate": MetricValue(
                raw_value=0.4,
                ema_short=0.4,
                ema_long=0.3,
                sample_count=10,
            ),
            "error_403_rate": MetricValue(
                raw_value=0.2,
                ema_short=0.2,
                ema_long=0.15,
                sample_count=10,
            ),
            "error_429_rate": MetricValue(
                raw_value=0.1,
                ema_short=0.1,
                ema_long=0.05,
                sample_count=10,
            ),
        }

        # When: Adjusting domain policy
        updates = await engine._adjust_domain_policy("blocked.com")

        # Then: Headful ratio should increase
        headful_updates = [u for u in updates if u.parameter == "headful_ratio"]
        assert len(headful_updates) >= 1, (
            f"Expected at least 1 headful_ratio update for high error domain, got {len(headful_updates)}"
        )
        for update in headful_updates:
            assert update.new_value > update.old_value, (
                f"headful_ratio should increase: {update.old_value} -> {update.new_value}"
            )

    async def test_hysteresis_prevents_rapid_changes(self):
        """Test that hysteresis prevents rapid parameter changes."""
        # Given: A PolicyEngine with 5 minute hysteresis interval
        collector = MetricsCollector()
        engine = PolicyEngine(
            metrics_collector=collector,
            hysteresis_interval=300,  # 5 minutes
        )

        # And: A state that was just changed
        state = engine._get_or_create_state(
            "engine", "test", PolicyParameter.ENGINE_WEIGHT
        )
        state.last_changed_at = datetime.now(timezone.utc)

        # When: Checking if change is allowed
        # Then: Change is blocked due to hysteresis
        assert not state.can_change(300)

    async def test_start_stop_engine(self):
        """Test starting and stopping the policy engine."""
        # Given: A PolicyEngine with short update interval
        collector = MetricsCollector()
        engine = PolicyEngine(
            metrics_collector=collector,
            update_interval=1,  # Short for testing
        )

        # When: Starting the engine
        await engine.start()

        # Then: Engine is running
        assert engine._running is True

        # When: Stopping the engine
        await engine.stop()

        # Then: Engine is stopped
        assert engine._running is False


@pytest.mark.asyncio
async def test_get_policy_engine_singleton():
    """Test that get_policy_engine returns singleton."""
    # Given: Reset global engine state
    import src.utils.policy_engine as pe
    pe._engine = None

    # When: Getting policy engine twice
    engine1 = await get_policy_engine()
    engine2 = await get_policy_engine()

    # Then: Same instance is returned (singleton)
    assert engine1 is engine2

    # Cleanup
    pe._engine = None


# =============================================================================
# Dynamic Weight Calculation Tests
# =============================================================================


class TestDynamicWeightCalculation:
    """Tests for dynamic weight calculation.

    Per §3.1.1, §3.1.4, §4.6: Dynamic weight adjustment based on
    past accuracy/failure/block rates with time decay.

    ## Test Perspectives Table

    | Case ID | Input / Precondition | Perspective | Expected Result | Notes |
    |---------|---------------------|-------------|-----------------|-------|
    | TC-DW-N-01 | Ideal metrics, recent use | Equivalence - normal | weight ≈ base_weight | Ideal state |
    | TC-DW-N-02 | Degraded metrics, recent use | Equivalence - degraded | weight < base_weight | Degraded state |
    | TC-DW-B-01 | success_rate=0.0, recent use | Boundary - minimum | weight = 0.1 (min) | Min clamp |
    | TC-DW-B-02 | All optimal, recent use | Boundary - maximum | weight ≤ 1.0 (max) | Max clamp |
    | TC-DW-B-03 | captcha_rate=1.0, recent use | Boundary - high CAPTCHA | weight reduced | CAPTCHA penalty |
    | TC-DW-B-04 | median_latency=10000ms, recent | Boundary - high latency | weight reduced | Latency penalty |
    | TC-DW-B-05 | last_used=24h ago, bad metrics | Boundary - time decay | weight closer to base | 50% decay |
    | TC-DW-B-06 | last_used=48h ago, bad metrics | Boundary - full decay | weight ≈ base_weight | 90% decay |
    | TC-DW-B-07 | last_used=None (never used) | Boundary - never used | weight ≈ base_weight | Max decay |
    | TC-DW-A-01 | Engine not in DB | Abnormal - missing | returns base_weight | Fallback |
    """

    def test_ideal_metrics_recent_use(self):
        """TC-DW-N-01: Ideal metrics with recent use.

        Given: Ideal metrics (success=1.0, captcha=0, low latency) and recent use
        When: Calculating dynamic weight
        Then: Weight should be calculated correctly with high confidence

        Expected calculation:
        - success_factor = 0.6 * 1.0 + 0.4 * 1.0 = 1.0
        - captcha_penalty = 1.0 - 0.0 = 1.0
        - latency_factor = 1.0 / (1.0 + 500/1000) = 0.667
        - raw_weight = 0.7 * 1.0 * 1.0 * 0.667 ≈ 0.47
        - With high confidence (~0.98), final weight ≈ 0.47
        """
        engine = PolicyEngine()
        recent_time = datetime.now(timezone.utc) - timedelta(hours=1)

        weight, confidence = engine.calculate_dynamic_weight(
            base_weight=0.7,
            success_rate_1h=1.0,
            success_rate_24h=1.0,
            captcha_rate=0.0,
            median_latency_ms=500.0,
            last_used_at=recent_time,
        )

        # Weight should be in valid range and close to base
        assert 0.1 <= weight <= 1.0, f"Weight {weight} not in valid range"
        assert confidence > 0.9, f"Confidence {confidence} should be high for recent use"
        # With ideal metrics and latency factor, weight should be in reasonable range
        # (lower latency factor due to 500ms latency gives ~0.47)
        assert weight >= 0.4, f"Weight {weight} should be >= 0.4 with ideal metrics"

    def test_degraded_metrics_recent_use(self):
        """TC-DW-N-02: Degraded metrics with recent use.

        Given: Degraded metrics (low success, high captcha, high latency) and recent use
        When: Calculating dynamic weight
        Then: Weight should be reduced below base_weight
        """
        engine = PolicyEngine()
        recent_time = datetime.now(timezone.utc) - timedelta(hours=1)

        # First calculate with ideal metrics
        ideal_weight, _ = engine.calculate_dynamic_weight(
            base_weight=0.7,
            success_rate_1h=1.0,
            success_rate_24h=1.0,
            captcha_rate=0.0,
            median_latency_ms=500.0,
            last_used_at=recent_time,
        )

        # Then calculate with degraded metrics
        degraded_weight, confidence = engine.calculate_dynamic_weight(
            base_weight=0.7,
            success_rate_1h=0.5,
            success_rate_24h=0.6,
            captcha_rate=0.3,
            median_latency_ms=2000.0,
            last_used_at=recent_time,
        )

        assert degraded_weight < ideal_weight, \
            f"Degraded weight {degraded_weight} should be < ideal weight {ideal_weight}"
        assert 0.1 <= degraded_weight <= 1.0, \
            f"Degraded weight {degraded_weight} not in valid range"

    def test_minimum_weight_clamp(self):
        """TC-DW-B-01: Minimum weight clamping.

        Given: Worst possible metrics (success=0, high captcha, high latency)
        When: Calculating dynamic weight
        Then: Weight should be clamped to minimum (0.1)
        """
        engine = PolicyEngine()
        recent_time = datetime.now(timezone.utc) - timedelta(hours=1)

        weight, _ = engine.calculate_dynamic_weight(
            base_weight=0.7,
            success_rate_1h=0.0,
            success_rate_24h=0.0,
            captcha_rate=1.0,
            median_latency_ms=10000.0,
            last_used_at=recent_time,
        )

        assert weight >= 0.1, f"Weight {weight} should be >= 0.1 (minimum)"

    def test_maximum_weight_clamp(self):
        """TC-DW-B-02: Maximum weight clamping.

        Given: High base weight and optimal metrics
        When: Calculating dynamic weight
        Then: Weight should be clamped to maximum (1.0)
        """
        engine = PolicyEngine()
        recent_time = datetime.now(timezone.utc) - timedelta(hours=1)

        weight, _ = engine.calculate_dynamic_weight(
            base_weight=2.0,  # High base weight
            success_rate_1h=1.0,
            success_rate_24h=1.0,
            captcha_rate=0.0,
            median_latency_ms=100.0,
            last_used_at=recent_time,
        )

        assert weight <= 1.0, f"Weight {weight} should be <= 1.0 (maximum)"

    def test_high_captcha_rate_penalty(self):
        """TC-DW-B-03: High CAPTCHA rate penalty.

        Given: High CAPTCHA rate (1.0) with otherwise good metrics
        When: Calculating dynamic weight
        Then: Weight should be significantly reduced
        """
        engine = PolicyEngine()
        recent_time = datetime.now(timezone.utc) - timedelta(hours=1)

        # Calculate with no CAPTCHA
        no_captcha_weight, _ = engine.calculate_dynamic_weight(
            base_weight=0.7,
            success_rate_1h=1.0,
            success_rate_24h=1.0,
            captcha_rate=0.0,
            median_latency_ms=500.0,
            last_used_at=recent_time,
        )

        # Calculate with high CAPTCHA
        high_captcha_weight, _ = engine.calculate_dynamic_weight(
            base_weight=0.7,
            success_rate_1h=1.0,
            success_rate_24h=1.0,
            captcha_rate=1.0,
            median_latency_ms=500.0,
            last_used_at=recent_time,
        )

        assert high_captcha_weight < no_captcha_weight, \
            f"High CAPTCHA weight {high_captcha_weight} should be < no CAPTCHA weight {no_captcha_weight}"

    def test_high_latency_penalty(self):
        """TC-DW-B-04: High latency penalty.

        Given: High latency (10000ms) with otherwise good metrics
        When: Calculating dynamic weight
        Then: Weight should be reduced
        """
        engine = PolicyEngine()
        recent_time = datetime.now(timezone.utc) - timedelta(hours=1)

        # Calculate with low latency
        low_latency_weight, _ = engine.calculate_dynamic_weight(
            base_weight=0.7,
            success_rate_1h=1.0,
            success_rate_24h=1.0,
            captcha_rate=0.0,
            median_latency_ms=500.0,
            last_used_at=recent_time,
        )

        # Calculate with high latency
        high_latency_weight, _ = engine.calculate_dynamic_weight(
            base_weight=0.7,
            success_rate_1h=1.0,
            success_rate_24h=1.0,
            captcha_rate=0.0,
            median_latency_ms=10000.0,
            last_used_at=recent_time,
        )

        assert high_latency_weight < low_latency_weight, \
            f"High latency weight {high_latency_weight} should be < low latency weight {low_latency_weight}"

    def test_time_decay_24h(self):
        """TC-DW-B-05: Time decay at 24 hours.

        Given: Bad metrics and last used 24 hours ago
        When: Calculating dynamic weight
        Then: Weight should be closer to base_weight due to 50% decay
        """
        engine = PolicyEngine()

        bad_metrics = {
            "success_rate_1h": 0.3,
            "success_rate_24h": 0.4,
            "captcha_rate": 0.5,
            "median_latency_ms": 3000.0,
        }

        # Recent use (1h ago)
        recent_weight, recent_conf = engine.calculate_dynamic_weight(
            base_weight=0.7,
            last_used_at=datetime.now(timezone.utc) - timedelta(hours=1),
            **bad_metrics,
        )

        # 24h ago
        old_weight, old_conf = engine.calculate_dynamic_weight(
            base_weight=0.7,
            last_used_at=datetime.now(timezone.utc) - timedelta(hours=24),
            **bad_metrics,
        )

        # Old weight should be closer to base_weight (0.7)
        assert old_weight > recent_weight, \
            f"24h old weight {old_weight} should be > recent weight {recent_weight}"
        # Confidence should be around 0.5 for 24h
        assert 0.4 <= old_conf <= 0.6, \
            f"Confidence {old_conf} should be ~0.5 for 24h old metrics"

    def test_time_decay_48h(self):
        """TC-DW-B-06: Time decay at 48 hours.

        Given: Bad metrics and last used 48 hours ago
        When: Calculating dynamic weight
        Then: Weight should be approximately base_weight (90% decay)
        """
        engine = PolicyEngine()
        base_weight = 0.7

        bad_metrics = {
            "success_rate_1h": 0.3,
            "success_rate_24h": 0.4,
            "captcha_rate": 0.5,
            "median_latency_ms": 3000.0,
        }

        # 48h ago
        weight, confidence = engine.calculate_dynamic_weight(
            base_weight=base_weight,
            last_used_at=datetime.now(timezone.utc) - timedelta(hours=48),
            **bad_metrics,
        )

        # Confidence should be very low (0.1 minimum)
        assert confidence <= 0.15, \
            f"Confidence {confidence} should be <= 0.15 for 48h old metrics"
        # Weight should be close to base_weight
        assert abs(weight - base_weight) < 0.2, \
            f"Weight {weight} should be close to base_weight {base_weight}"

    def test_time_decay_never_used(self):
        """TC-DW-B-07: Never used engine.

        Given: Bad metrics but last_used_at is None (never used)
        When: Calculating dynamic weight
        Then: Weight should be approximately base_weight
        """
        engine = PolicyEngine()
        base_weight = 0.7

        weight, confidence = engine.calculate_dynamic_weight(
            base_weight=base_weight,
            success_rate_1h=0.3,
            success_rate_24h=0.4,
            captcha_rate=0.5,
            median_latency_ms=3000.0,
            last_used_at=None,
        )

        # Confidence should be at minimum (0.1)
        assert confidence == 0.1, \
            f"Confidence {confidence} should be 0.1 for never-used engine"
        # Weight should be close to base_weight
        assert abs(weight - base_weight) < 0.15, \
            f"Weight {weight} should be close to base_weight {base_weight}"

    @pytest.mark.asyncio
    async def test_get_dynamic_weight_fallback(self):
        """TC-DW-A-01: Fallback for non-existent engine.

        Given: Non-existent engine name
        When: Getting dynamic weight
        Then: Should return default weight (1.0)
        """
        engine = PolicyEngine()

        weight = await engine.get_dynamic_engine_weight(
            "nonexistent_engine_xyz",
            category="general",
        )

        # Should return default weight for unknown engine
        assert weight == 1.0, \
            f"Non-existent engine should return default weight 1.0, got {weight}"

    def test_confidence_calculation(self):
        """Test confidence calculation based on time since last use.

        Given: Various time intervals since last use
        When: Calculating confidence
        Then: Confidence should decay appropriately
        """
        engine = PolicyEngine()
        base_weight = 0.7
        good_metrics = {
            "success_rate_1h": 1.0,
            "success_rate_24h": 1.0,
            "captcha_rate": 0.0,
            "median_latency_ms": 500.0,
        }

        test_cases = [
            (timedelta(hours=0), 1.0),     # Just used
            (timedelta(hours=6), 0.875),   # 6h ago
            (timedelta(hours=12), 0.75),   # 12h ago
            (timedelta(hours=24), 0.5),    # 24h ago
            (timedelta(hours=48), 0.1),    # 48h ago (minimum)
            (timedelta(hours=72), 0.1),    # 72h ago (stays at minimum)
        ]

        for time_delta, expected_conf in test_cases:
            last_used = datetime.now(timezone.utc) - time_delta
            _, confidence = engine.calculate_dynamic_weight(
                base_weight=base_weight,
                last_used_at=last_used,
                **good_metrics,
            )

            # Allow some tolerance
            assert abs(confidence - expected_conf) < 0.05, \
                f"Confidence for {time_delta} should be ~{expected_conf}, got {confidence}"

