"""
Tests for policy engine module.
Tests PolicyEngine, ParameterState, and auto-adjustment logic.

Related spec: §4.6 ポリシー自動更新（クローズドループ制御）
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
        for param in PolicyParameter:
            assert param in DEFAULT_BOUNDS, f"Missing bounds for {param}"
    
    def test_bounds_values_valid(self):
        """Test that bounds values are valid."""
        for param, bounds in DEFAULT_BOUNDS.items():
            assert bounds.min_value < bounds.max_value, f"Invalid bounds for {param}"
            assert bounds.min_value <= bounds.default_value <= bounds.max_value
            assert bounds.step_up > 0
            assert bounds.step_down > 0


class TestParameterState:
    """Tests for ParameterState."""
    
    def test_initial_state(self):
        """Test initial parameter state."""
        state = ParameterState(current_value=0.5)
        
        assert state.current_value == 0.5
        assert state.last_direction == "none"
        assert state.change_count == 0
    
    def test_can_change_immediately(self):
        """Test that new state can change immediately."""
        state = ParameterState(current_value=0.5)
        state.last_changed_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        
        assert state.can_change(min_interval_seconds=300)  # 5 minutes
    
    def test_cannot_change_too_soon(self):
        """Test that recent changes block further changes."""
        state = ParameterState(current_value=0.5)
        state.last_changed_at = datetime.now(timezone.utc) - timedelta(seconds=60)
        
        assert not state.can_change(min_interval_seconds=300)
    
    def test_apply_change_within_bounds(self):
        """Test applying a change within bounds."""
        state = ParameterState(current_value=0.5)
        bounds = ParameterBounds(
            min_value=0.0,
            max_value=1.0,
            default_value=0.5,
            step_up=0.1,
            step_down=0.1,
        )
        
        result = state.apply_change(0.7, "up", bounds)
        
        assert result == 0.7
        assert state.current_value == 0.7
        assert state.last_direction == "up"
        assert state.change_count == 1
    
    def test_apply_change_clamped_max(self):
        """Test that changes are clamped to max bound."""
        state = ParameterState(current_value=0.9)
        bounds = ParameterBounds(
            min_value=0.0,
            max_value=1.0,
            default_value=0.5,
            step_up=0.1,
            step_down=0.1,
        )
        
        result = state.apply_change(1.5, "up", bounds)
        
        assert result == 1.0
        assert state.current_value == 1.0
    
    def test_apply_change_clamped_min(self):
        """Test that changes are clamped to min bound."""
        state = ParameterState(current_value=0.1)
        bounds = ParameterBounds(
            min_value=0.0,
            max_value=1.0,
            default_value=0.5,
            step_up=0.1,
            step_down=0.1,
        )
        
        result = state.apply_change(-0.5, "down", bounds)
        
        assert result == 0.0
        assert state.current_value == 0.0


class TestPolicyUpdate:
    """Tests for PolicyUpdate dataclass."""
    
    def test_policy_update_creation(self):
        """Test creating a policy update record."""
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
        
        assert update.target_type == "engine"
        assert update.target_id == "google"
        assert update.old_value == 1.0
        assert update.new_value == 0.8


@pytest.mark.asyncio
class TestPolicyEngine:
    """Tests for PolicyEngine class."""
    
    async def test_engine_initialization(self):
        """Test policy engine initialization."""
        collector = MetricsCollector()
        engine = PolicyEngine(
            metrics_collector=collector,
            update_interval=60,
            hysteresis_interval=300,
        )
        
        assert engine._update_interval == 60
        assert engine._hysteresis_interval == 300
    
    async def test_get_parameter_value_default(self):
        """Test getting default parameter value."""
        collector = MetricsCollector()
        engine = PolicyEngine(metrics_collector=collector)
        
        value = engine.get_parameter_value(
            "engine", "test", PolicyParameter.ENGINE_WEIGHT
        )
        
        assert value == DEFAULT_BOUNDS[PolicyParameter.ENGINE_WEIGHT].default_value
    
    async def test_set_parameter_value(self):
        """Test manually setting parameter value."""
        collector = MetricsCollector()
        engine = PolicyEngine(metrics_collector=collector)
        
        # Mock database (patching at source since lazy import)
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
            
            assert update.new_value == 0.3
            assert update.reason == "Manual test"
    
    async def test_get_update_history(self):
        """Test getting update history returns empty list initially.
        
        Verifies that history is a list and is empty when no updates have occurred.
        """
        collector = MetricsCollector()
        engine = PolicyEngine(metrics_collector=collector)
        
        history = engine.get_update_history(limit=10)
        
        assert history == [], f"Expected empty list for new engine, got {history}"
    
    async def test_adjust_engine_policy_low_success(self):
        """Test engine policy adjustment on low success rate.
        
        When success_rate EMA is below 0.5, the engine weight should decrease.
        Hysteresis is disabled (interval=0) to test immediate adjustment logic
        without timing dependencies.
        
        Related spec: §4.6 ポリシー自動更新
        """
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
        
        updates = await engine._adjust_engine_policy("test_engine")
        
        # Should recommend weight decrease
        weight_updates = [u for u in updates if u.parameter == "engine_weight"]
        assert len(weight_updates) == 1, f"Expected 1 weight update, got {len(weight_updates)}"
        assert weight_updates[0].new_value < weight_updates[0].old_value, (
            f"Weight should decrease: {weight_updates[0].old_value} -> {weight_updates[0].new_value}"
        )
    
    async def test_adjust_domain_policy_high_error(self):
        """Test domain policy adjustment on high error rate.
        
        When combined error rate (captcha + 403 + 429) exceeds 0.3 threshold,
        headful_ratio should increase. Hysteresis is disabled (interval=0)
        to test immediate adjustment logic.
        
        Related spec: §4.6 ポリシー自動更新、§4.3 抗堪性とステルス性
        """
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
        
        updates = await engine._adjust_domain_policy("blocked.com")
        
        # Should recommend headful increase (at minimum)
        headful_updates = [u for u in updates if u.parameter == "headful_ratio"]
        assert len(headful_updates) >= 1, (
            f"Expected at least 1 headful_ratio update for high error domain, got {len(headful_updates)}"
        )
        # Verify headful ratio increased
        for update in headful_updates:
            assert update.new_value > update.old_value, (
                f"headful_ratio should increase: {update.old_value} -> {update.new_value}"
            )
    
    async def test_hysteresis_prevents_rapid_changes(self):
        """Test that hysteresis prevents rapid parameter changes."""
        collector = MetricsCollector()
        engine = PolicyEngine(
            metrics_collector=collector,
            hysteresis_interval=300,  # 5 minutes
        )
        
        # Get state and simulate recent change
        state = engine._get_or_create_state(
            "engine", "test", PolicyParameter.ENGINE_WEIGHT
        )
        state.last_changed_at = datetime.now(timezone.utc)
        
        # Should not allow change due to hysteresis
        assert not state.can_change(300)
    
    async def test_start_stop_engine(self):
        """Test starting and stopping the policy engine."""
        collector = MetricsCollector()
        engine = PolicyEngine(
            metrics_collector=collector,
            update_interval=1,  # Short for testing
        )
        
        await engine.start()
        assert engine._running is True
        
        await engine.stop()
        assert engine._running is False


@pytest.mark.asyncio
async def test_get_policy_engine_singleton():
    """Test that get_policy_engine returns singleton."""
    # Reset global state
    import src.utils.policy_engine as pe
    pe._engine = None
    
    engine1 = await get_policy_engine()
    engine2 = await get_policy_engine()
    
    assert engine1 is engine2
    
    # Cleanup
    pe._engine = None

