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

