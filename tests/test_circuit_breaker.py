"""
Tests for src/search/circuit_breaker.py
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

import pytest

from src.search.circuit_breaker import (
    CircuitState,
    EngineCircuitBreaker,
    CircuitBreakerManager,
    check_engine_available,
    record_engine_result,
    get_available_engines,
)


class TestCircuitState:
    """Tests for CircuitState enum."""

    def test_states_exist(self):
        """Test all states are defined."""
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.HALF_OPEN.value == "half-open"
        assert CircuitState.OPEN.value == "open"


class TestEngineCircuitBreaker:
    """Tests for EngineCircuitBreaker class."""

    def test_init_defaults(self):
        """Test initialization with defaults."""
        breaker = EngineCircuitBreaker("test_engine")
        
        assert breaker.engine == "test_engine"
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_available is True
        assert breaker._consecutive_failures == 0

    def test_init_custom_thresholds(self):
        """Test initialization with custom thresholds."""
        breaker = EngineCircuitBreaker(
            "test_engine",
            failure_threshold=5,
            cooldown_min=60,
            cooldown_max=240,
        )
        
        assert breaker.failure_threshold == 5
        assert breaker.cooldown_min == 60
        assert breaker.cooldown_max == 240

    def test_record_success_updates_metrics(self):
        """Test recording success updates metrics."""
        breaker = EngineCircuitBreaker("test")
        breaker._success_rate_1h = 0.5
        
        breaker.record_success(latency_ms=100)
        
        # EMA should increase: 0.1 * 1.0 + 0.9 * 0.5 = 0.55
        assert breaker._success_rate_1h == pytest.approx(0.55, rel=0.01)
        assert breaker._consecutive_failures == 0

    def test_record_success_updates_latency(self):
        """Test recording success updates latency EMA."""
        breaker = EngineCircuitBreaker("test")
        breaker._latency_ema = 1000.0
        
        breaker.record_success(latency_ms=200)
        
        # EMA: 0.1 * 200 + 0.9 * 1000 = 920
        assert breaker._latency_ema == pytest.approx(920.0, rel=0.01)

    def test_record_failure_increments_count(self):
        """Test recording failure increments consecutive count."""
        breaker = EngineCircuitBreaker("test")
        
        breaker.record_failure()
        
        assert breaker._consecutive_failures == 1
        assert breaker.state == CircuitState.CLOSED

    def test_circuit_opens_after_threshold(self):
        """Test circuit opens after consecutive failures reach threshold."""
        breaker = EngineCircuitBreaker("test", failure_threshold=2)
        
        breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED
        
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN
        assert breaker.is_available is False

    def test_circuit_half_opens_after_cooldown(self):
        """Test circuit transitions to half-open after cooldown."""
        breaker = EngineCircuitBreaker("test", failure_threshold=2, cooldown_min=1)
        
        # Open the circuit
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN
        
        # Simulate cooldown elapsed
        breaker._cooldown_until = datetime.now(timezone.utc) - timedelta(minutes=1)
        
        # State check should trigger transition
        assert breaker.state == CircuitState.HALF_OPEN
        assert breaker.is_available is True

    def test_half_open_closes_on_success(self):
        """Test half-open circuit closes on successful probe."""
        breaker = EngineCircuitBreaker("test", failure_threshold=2)
        breaker._state = CircuitState.HALF_OPEN
        
        breaker.record_success()
        
        assert breaker.state == CircuitState.CLOSED

    def test_half_open_reopens_on_failure(self):
        """Test half-open circuit reopens on failed probe."""
        breaker = EngineCircuitBreaker("test", failure_threshold=2)
        breaker._state = CircuitState.HALF_OPEN
        
        breaker.record_failure()
        
        assert breaker.state == CircuitState.OPEN

    def test_captcha_updates_captcha_rate(self):
        """Test CAPTCHA failure updates captcha rate."""
        breaker = EngineCircuitBreaker("test")
        breaker._captcha_rate = 0.0
        
        breaker.record_failure(is_captcha=True)
        
        # EMA: 0.1 * 1.0 + 0.9 * 0.0 = 0.1
        assert breaker._captcha_rate == pytest.approx(0.1, rel=0.01)

    def test_force_open(self):
        """Test force opening circuit."""
        breaker = EngineCircuitBreaker("test")
        
        breaker.force_open(cooldown_minutes=60)
        
        assert breaker.state == CircuitState.OPEN
        # Cooldown should be set to a datetime in the future
        assert isinstance(breaker._cooldown_until, datetime), (
            f"Expected datetime for cooldown, got {type(breaker._cooldown_until)}"
        )

    def test_force_close(self):
        """Test force closing circuit."""
        breaker = EngineCircuitBreaker("test", failure_threshold=2)
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN
        
        breaker.force_close()
        
        assert breaker.state == CircuitState.CLOSED
        assert breaker._consecutive_failures == 0
        assert breaker._cooldown_until is None

    def test_get_metrics(self):
        """Test getting metrics."""
        breaker = EngineCircuitBreaker("test_engine")
        breaker.record_success(latency_ms=150)
        
        metrics = breaker.get_metrics()
        
        assert metrics["engine"] == "test_engine"
        assert metrics["state"] == "closed"
        assert "success_rate_1h" in metrics
        assert "latency_ema_ms" in metrics
        assert metrics["is_available"] is True

    def test_calculate_cooldown_exponential_backoff(self):
        """Test cooldown calculation with exponential backoff."""
        breaker = EngineCircuitBreaker("test", cooldown_min=30, cooldown_max=120)
        
        # Initial cooldown
        breaker._total_failures_in_window = 0
        cooldown1 = breaker._calculate_cooldown()
        
        # After more failures
        breaker._total_failures_in_window = 6
        cooldown2 = breaker._calculate_cooldown()
        
        # Should increase with failures
        assert cooldown2 > cooldown1
        # But not exceed max
        assert cooldown2.total_seconds() / 60 <= breaker.cooldown_max


class TestCircuitBreakerManager:
    """Tests for CircuitBreakerManager class."""

    @pytest.mark.asyncio
    async def test_get_breaker_creates_new(self):
        """Test get_breaker creates new breaker if not exists."""
        manager = CircuitBreakerManager()
        
        # Mock database to return no existing record
        with patch("src.search.circuit_breaker.get_database") as mock_db:
            mock_db.return_value.fetch_one = AsyncMock(return_value=None)
            
            breaker = await manager.get_breaker("new_engine")
        
        assert breaker.engine == "new_engine"
        assert "new_engine" in manager._breakers

    @pytest.mark.asyncio
    async def test_get_breaker_returns_cached(self):
        """Test get_breaker returns cached breaker."""
        manager = CircuitBreakerManager()
        
        with patch("src.search.circuit_breaker.get_database") as mock_db:
            mock_db.return_value.fetch_one = AsyncMock(return_value=None)
            
            breaker1 = await manager.get_breaker("engine1")
            breaker2 = await manager.get_breaker("engine1")
        
        assert breaker1 is breaker2

    @pytest.mark.asyncio
    async def test_record_success(self):
        """Test recording success through manager."""
        manager = CircuitBreakerManager()
        
        with patch("src.search.circuit_breaker.get_database") as mock_db:
            mock_db.return_value.fetch_one = AsyncMock(return_value=None)
            mock_db.return_value.execute = AsyncMock()
            
            await manager.record_success("engine1", latency_ms=100)
            
            breaker = manager._breakers["engine1"]
            assert breaker._consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_record_failure(self):
        """Test recording failure through manager."""
        manager = CircuitBreakerManager()
        
        with patch("src.search.circuit_breaker.get_database") as mock_db:
            mock_db.return_value.fetch_one = AsyncMock(return_value=None)
            mock_db.return_value.execute = AsyncMock()
            
            await manager.record_failure("engine1", is_captcha=True)
            
            breaker = manager._breakers["engine1"]
            assert breaker._consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_get_available_engines(self):
        """Test getting available engines."""
        manager = CircuitBreakerManager()
        
        with patch("src.search.circuit_breaker.get_database") as mock_db:
            mock_db.return_value.fetch_one = AsyncMock(return_value=None)
            
            # Create breakers with different states
            breaker1 = await manager.get_breaker("available1")
            breaker2 = await manager.get_breaker("available2")
            breaker3 = await manager.get_breaker("unavailable")
            breaker3._state = CircuitState.OPEN
            breaker3._cooldown_until = datetime.now(timezone.utc) + timedelta(hours=1)
            
            available = await manager.get_available_engines(
                ["available1", "available2", "unavailable"]
            )
        
        assert "available1" in available
        assert "available2" in available
        assert "unavailable" not in available


@pytest.mark.integration
class TestDatabasePersistence:
    """Tests for database persistence.
    
    Integration tests per §7.1.7 - uses temporary database.
    """

    @pytest.mark.asyncio
    async def test_save_to_db(self, test_database):
        """Test saving circuit state to database."""
        from src.search import circuit_breaker
        
        breaker = EngineCircuitBreaker("test_engine")
        breaker.record_failure()
        
        with patch.object(circuit_breaker, "get_database", return_value=test_database):
            await breaker.save_to_db()
        
        # Verify in database
        row = await test_database.fetch_one(
            "SELECT * FROM engine_health WHERE engine = ?",
            ("test_engine",),
        )
        
        assert row is not None
        assert row["engine"] == "test_engine"
        assert row["consecutive_failures"] == 1

    @pytest.mark.asyncio
    async def test_load_from_db(self, test_database):
        """Test loading circuit state from database."""
        from src.search import circuit_breaker
        
        # Insert test data
        await test_database.execute(
            """
            INSERT INTO engine_health (engine, status, success_rate_1h, consecutive_failures)
            VALUES (?, ?, ?, ?)
            """,
            ("existing_engine", "half-open", 0.7, 3),
        )
        
        breaker = EngineCircuitBreaker("existing_engine")
        
        with patch.object(circuit_breaker, "get_database", return_value=test_database):
            loaded = await breaker.load_from_db()
        
        assert loaded is True
        assert breaker._state == CircuitState.HALF_OPEN
        assert breaker._success_rate_1h == pytest.approx(0.7, rel=0.01)
        assert breaker._consecutive_failures == 3

    @pytest.mark.asyncio
    async def test_load_from_db_not_found(self, test_database):
        """Test loading returns False when engine not found."""
        from src.search import circuit_breaker
        
        breaker = EngineCircuitBreaker("nonexistent")
        
        with patch.object(circuit_breaker, "get_database", return_value=test_database):
            loaded = await breaker.load_from_db()
        
        assert loaded is False


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    @pytest.mark.asyncio
    async def test_check_engine_available(self):
        """Test check_engine_available function."""
        from src.search import circuit_breaker
        
        with patch.object(circuit_breaker, "get_circuit_breaker_manager") as mock_get_mgr:
            mock_manager = AsyncMock()
            mock_breaker = EngineCircuitBreaker("test")
            mock_manager.get_breaker.return_value = mock_breaker
            mock_get_mgr.return_value = mock_manager
            
            result = await check_engine_available("test")
        
        assert result is True

    @pytest.mark.asyncio
    async def test_record_engine_result_success(self):
        """Test record_engine_result for success."""
        from src.search import circuit_breaker
        
        with patch.object(circuit_breaker, "get_circuit_breaker_manager") as mock_get_mgr:
            mock_manager = AsyncMock()
            mock_get_mgr.return_value = mock_manager
            
            await record_engine_result("test", success=True, latency_ms=100)
            
            mock_manager.record_success.assert_called_once_with("test", 100)

    @pytest.mark.asyncio
    async def test_record_engine_result_failure(self):
        """Test record_engine_result for failure."""
        from src.search import circuit_breaker
        
        with patch.object(circuit_breaker, "get_circuit_breaker_manager") as mock_get_mgr:
            mock_manager = AsyncMock()
            mock_get_mgr.return_value = mock_manager
            
            await record_engine_result(
                "test",
                success=False,
                is_captcha=True,
                is_timeout=False,
            )
            
            mock_manager.record_failure.assert_called_once_with("test", True, False)


class TestStateTransitionScenarios:
    """Integration tests for state transition scenarios."""

    def test_full_cycle_closed_open_halfopen_closed(self):
        """Test full state transition cycle."""
        breaker = EngineCircuitBreaker("test", failure_threshold=2, cooldown_min=1)
        
        # Start closed
        assert breaker.state == CircuitState.CLOSED
        
        # Failures -> open
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN
        
        # Simulate cooldown elapsed -> half-open
        breaker._cooldown_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert breaker.state == CircuitState.HALF_OPEN
        
        # Success -> closed
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED

    def test_half_open_failure_returns_to_open(self):
        """Test half-open failure returns to open."""
        breaker = EngineCircuitBreaker("test", failure_threshold=2, cooldown_min=1)
        
        # Get to half-open
        breaker.record_failure()
        breaker.record_failure()
        breaker._cooldown_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert breaker.state == CircuitState.HALF_OPEN
        
        # Probe failure
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN
        
        # Should have new cooldown
        assert breaker._cooldown_until > datetime.now(timezone.utc)

    def test_success_resets_failure_count(self):
        """Test success resets consecutive failure count."""
        breaker = EngineCircuitBreaker("test", failure_threshold=3)
        
        breaker.record_failure()
        breaker.record_failure()
        assert breaker._consecutive_failures == 2
        
        breaker.record_success()
        assert breaker._consecutive_failures == 0
        
        # Should need 3 more failures to open
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED
        
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

