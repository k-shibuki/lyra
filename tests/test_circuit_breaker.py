"""
Tests for src/search/circuit_breaker.py

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-CS-N-01 | CircuitState enum | Equivalence – normal | All states defined | - |
| TC-CB-N-01 | Default init | Equivalence – normal | Default values set | - |
| TC-CB-N-02 | Custom thresholds | Equivalence – normal | Custom values used | - |
| TC-CB-N-03 | Record success | Equivalence – normal | Metrics updated | - |
| TC-CB-N-04 | Record success latency | Equivalence – normal | Latency EMA updated | - |
| TC-CB-N-05 | Record failure | Equivalence – normal | Failure count +1 | - |
| TC-CB-B-01 | Failures reach threshold | Boundary – threshold | Circuit opens | - |
| TC-CB-N-06 | Half-open after cooldown | Equivalence – normal | State transitions | - |
| TC-CB-N-07 | Half-open success | Equivalence – normal | Circuit closes | - |
| TC-CB-N-08 | Half-open failure | Equivalence – normal | Circuit reopens | - |
| TC-CB-N-09 | CAPTCHA rate tracking | Equivalence – normal | Rate updated | - |
| TC-CB-N-10 | Force open | Equivalence – normal | State forced open | - |
| TC-CB-N-11 | Force close | Equivalence – normal | State forced closed | - |
| TC-CB-N-12 | Get metrics | Equivalence – normal | All fields present | - |
| TC-CB-N-13 | Exponential backoff | Equivalence – normal | Cooldown increases | - |
| TC-MGR-N-01 | Get breaker creates new | Equivalence – normal | New breaker created | - |
| TC-MGR-N-02 | Get breaker cached | Equivalence – normal | Same instance | - |
| TC-MGR-N-03 | Record success via mgr | Equivalence – normal | Breaker updated | - |
| TC-MGR-N-04 | Record failure via mgr | Equivalence – normal | Breaker updated | - |
| TC-MGR-N-05 | Get available engines | Equivalence – normal | Filters unavailable | - |
| TC-DB-N-01 | Save to DB | Equivalence – normal | Row inserted | - |
| TC-DB-N-02 | Load from DB | Equivalence – normal | State restored | - |
| TC-DB-A-01 | Load nonexistent | Equivalence – abnormal | Returns False | - |
| TC-FN-N-01 | check_engine_available | Equivalence – normal | Returns bool | - |
| TC-FN-N-02 | record_result success | Equivalence – normal | record_success called | - |
| TC-FN-N-03 | record_result failure | Equivalence – normal | record_failure called | - |
| TC-ST-N-01 | Full state cycle | Equivalence – normal | All transitions work | - |
| TC-ST-N-02 | Half-open failure cycle | Equivalence – normal | Returns to open | - |
| TC-ST-N-03 | Success resets count | Equivalence – normal | Counter reset | - |
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

import pytest

# All tests in this module are unit tests (except TestDatabasePersistence)
pytestmark = pytest.mark.unit

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
        # Given: CircuitState enum
        # When: Accessing state values
        # Then: All states have correct values
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.HALF_OPEN.value == "half-open"
        assert CircuitState.OPEN.value == "open"


class TestEngineCircuitBreaker:
    """Tests for EngineCircuitBreaker class."""

    def test_init_defaults(self):
        """Test initialization with defaults."""
        # Given: Engine name only
        # When: Creating breaker with defaults
        breaker = EngineCircuitBreaker("test_engine")

        # Then: Default values are set
        assert breaker.engine == "test_engine"
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_available is True
        assert breaker._consecutive_failures == 0

    def test_init_custom_thresholds(self):
        """Test initialization with custom thresholds."""
        # Given: Custom threshold values
        # When: Creating breaker with custom config
        breaker = EngineCircuitBreaker(
            "test_engine",
            failure_threshold=5,
            cooldown_min=60,
            cooldown_max=240,
        )

        # Then: Custom values are used
        assert breaker.failure_threshold == 5
        assert breaker.cooldown_min == 60
        assert breaker.cooldown_max == 240

    def test_record_success_updates_metrics(self):
        """Test recording success updates metrics."""
        # Given: Breaker with 0.5 success rate
        breaker = EngineCircuitBreaker("test")
        breaker._success_rate_1h = 0.5

        # When: Recording success
        breaker.record_success(latency_ms=100)

        # Then: EMA increases (0.1 * 1.0 + 0.9 * 0.5 = 0.55)
        assert breaker._success_rate_1h == pytest.approx(0.55, rel=0.01)
        assert breaker._consecutive_failures == 0

    def test_record_success_updates_latency(self):
        """Test recording success updates latency EMA."""
        # Given: Breaker with 1000ms latency EMA
        breaker = EngineCircuitBreaker("test")
        breaker._latency_ema = 1000.0

        # When: Recording success with 200ms latency
        breaker.record_success(latency_ms=200)

        # Then: EMA updated (0.1 * 200 + 0.9 * 1000 = 920)
        assert breaker._latency_ema == pytest.approx(920.0, rel=0.01)

    def test_record_failure_increments_count(self):
        """Test recording failure increments consecutive count."""
        # Given: Fresh breaker
        breaker = EngineCircuitBreaker("test")

        # When: Recording failure
        breaker.record_failure()

        # Then: Failure count incremented, state unchanged
        assert breaker._consecutive_failures == 1
        assert breaker.state == CircuitState.CLOSED

    def test_circuit_opens_after_threshold(self):
        """Test circuit opens after consecutive failures reach threshold."""
        # Given: Breaker with threshold=2
        breaker = EngineCircuitBreaker("test", failure_threshold=2)

        # When: Recording failures up to threshold
        breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED

        breaker.record_failure()

        # Then: Circuit opens
        assert breaker.state == CircuitState.OPEN
        assert breaker.is_available is False

    def test_circuit_half_opens_after_cooldown(self):
        """Test circuit transitions to half-open after cooldown."""
        # Given: Open circuit with expired cooldown
        breaker = EngineCircuitBreaker("test", failure_threshold=2, cooldown_min=1)
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # When: Cooldown expires
        breaker._cooldown_until = datetime.now(timezone.utc) - timedelta(minutes=1)

        # Then: State transitions to half-open
        assert breaker.state == CircuitState.HALF_OPEN
        assert breaker.is_available is True

    def test_half_open_closes_on_success(self):
        """Test half-open circuit closes on successful probe."""
        # Given: Half-open circuit
        breaker = EngineCircuitBreaker("test", failure_threshold=2)
        breaker._state = CircuitState.HALF_OPEN

        # When: Recording success
        breaker.record_success()

        # Then: Circuit closes
        assert breaker.state == CircuitState.CLOSED

    def test_half_open_reopens_on_failure(self):
        """Test half-open circuit reopens on failed probe."""
        # Given: Half-open circuit
        breaker = EngineCircuitBreaker("test", failure_threshold=2)
        breaker._state = CircuitState.HALF_OPEN

        # When: Recording failure
        breaker.record_failure()

        # Then: Circuit reopens
        assert breaker.state == CircuitState.OPEN

    def test_captcha_updates_captcha_rate(self):
        """Test CAPTCHA failure updates captcha rate."""
        # Given: Breaker with 0% captcha rate
        breaker = EngineCircuitBreaker("test")
        breaker._captcha_rate = 0.0

        # When: Recording captcha failure
        breaker.record_failure(is_captcha=True)

        # Then: Captcha rate EMA updated (0.1 * 1.0 + 0.9 * 0.0 = 0.1)
        assert breaker._captcha_rate == pytest.approx(0.1, rel=0.01)

    def test_force_open(self):
        """Test force opening circuit."""
        # Given: Fresh breaker
        breaker = EngineCircuitBreaker("test")

        # When: Force opening with 60 min cooldown
        breaker.force_open(cooldown_minutes=60)

        # Then: State is open with future cooldown
        assert breaker.state == CircuitState.OPEN
        assert isinstance(breaker._cooldown_until, datetime), (
            f"Expected datetime for cooldown, got {type(breaker._cooldown_until)}"
        )

    def test_force_close(self):
        """Test force closing circuit."""
        # Given: Open circuit
        breaker = EngineCircuitBreaker("test", failure_threshold=2)
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # When: Force closing
        breaker.force_close()

        # Then: State is closed, counters reset
        assert breaker.state == CircuitState.CLOSED
        assert breaker._consecutive_failures == 0
        assert breaker._cooldown_until is None

    def test_get_metrics(self):
        """Test getting metrics."""
        # Given: Breaker with some activity
        breaker = EngineCircuitBreaker("test_engine")
        breaker.record_success(latency_ms=150)

        # When: Getting metrics
        metrics = breaker.get_metrics()

        # Then: All fields present
        assert metrics["engine"] == "test_engine"
        assert metrics["state"] == "closed"
        assert "success_rate_1h" in metrics
        assert "latency_ema_ms" in metrics
        assert metrics["is_available"] is True

    def test_calculate_cooldown_exponential_backoff(self):
        """Test cooldown calculation with exponential backoff."""
        # Given: Breaker with cooldown range [30, 120]
        breaker = EngineCircuitBreaker("test", cooldown_min=30, cooldown_max=120)

        # When: Calculating cooldown with 0 failures
        breaker._total_failures_in_window = 0
        cooldown1 = breaker._calculate_cooldown()

        # And: Calculating with 6 failures
        breaker._total_failures_in_window = 6
        cooldown2 = breaker._calculate_cooldown()

        # Then: Cooldown increases but doesn't exceed max
        assert cooldown2 > cooldown1
        assert cooldown2.total_seconds() / 60 <= breaker.cooldown_max


class TestCircuitBreakerManager:
    """Tests for CircuitBreakerManager class."""

    @pytest.mark.asyncio
    async def test_get_breaker_creates_new(self):
        """Test get_breaker creates new breaker if not exists."""
        # Given: Fresh manager with mocked database
        manager = CircuitBreakerManager()

        with patch("src.search.circuit_breaker.get_database") as mock_db:
            mock_db.return_value.fetch_one = AsyncMock(return_value=None)

            # When: Getting a new breaker
            breaker = await manager.get_breaker("new_engine")

        # Then: New breaker is created and cached
        assert breaker.engine == "new_engine"
        assert "new_engine" in manager._breakers

    @pytest.mark.asyncio
    async def test_get_breaker_returns_cached(self):
        """Test get_breaker returns cached breaker."""
        # Given: Manager with one cached breaker
        manager = CircuitBreakerManager()

        with patch("src.search.circuit_breaker.get_database") as mock_db:
            mock_db.return_value.fetch_one = AsyncMock(return_value=None)

            # When: Getting same breaker twice
            breaker1 = await manager.get_breaker("engine1")
            breaker2 = await manager.get_breaker("engine1")

        # Then: Same instance is returned
        assert breaker1 is breaker2

    @pytest.mark.asyncio
    async def test_record_success(self):
        """Test recording success through manager."""
        # Given: Fresh manager
        manager = CircuitBreakerManager()

        with patch("src.search.circuit_breaker.get_database") as mock_db:
            mock_db.return_value.fetch_one = AsyncMock(return_value=None)
            mock_db.return_value.execute = AsyncMock()

            # When: Recording success
            await manager.record_success("engine1", latency_ms=100)

            # Then: Breaker is updated
            breaker = manager._breakers["engine1"]
            assert breaker._consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_record_failure(self):
        """Test recording failure through manager."""
        # Given: Fresh manager
        manager = CircuitBreakerManager()

        with patch("src.search.circuit_breaker.get_database") as mock_db:
            mock_db.return_value.fetch_one = AsyncMock(return_value=None)
            mock_db.return_value.execute = AsyncMock()

            # When: Recording failure
            await manager.record_failure("engine1", is_captcha=True)

            # Then: Breaker failure count incremented
            breaker = manager._breakers["engine1"]
            assert breaker._consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_get_available_engines(self):
        """Test getting available engines."""
        # Given: Manager with breakers in different states
        manager = CircuitBreakerManager()

        with patch("src.search.circuit_breaker.get_database") as mock_db:
            mock_db.return_value.fetch_one = AsyncMock(return_value=None)

            breaker1 = await manager.get_breaker("available1")
            breaker2 = await manager.get_breaker("available2")
            breaker3 = await manager.get_breaker("unavailable")
            breaker3._state = CircuitState.OPEN
            breaker3._cooldown_until = datetime.now(timezone.utc) + timedelta(hours=1)

            # When: Getting available engines
            available = await manager.get_available_engines(
                ["available1", "available2", "unavailable"]
            )

        # Then: Only available engines returned
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
        # Given: Breaker with one failure
        from src.search import circuit_breaker

        breaker = EngineCircuitBreaker("test_engine")
        breaker.record_failure()

        # When: Saving to database
        with patch.object(circuit_breaker, "get_database", return_value=test_database):
            await breaker.save_to_db()

        # Then: Row is inserted with correct values
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
        # Given: Existing database record
        from src.search import circuit_breaker

        await test_database.execute(
            """
            INSERT INTO engine_health (engine, status, success_rate_1h, consecutive_failures)
            VALUES (?, ?, ?, ?)
            """,
            ("existing_engine", "half-open", 0.7, 3),
        )

        breaker = EngineCircuitBreaker("existing_engine")

        # When: Loading from database
        with patch.object(circuit_breaker, "get_database", return_value=test_database):
            loaded = await breaker.load_from_db()

        # Then: State is restored
        assert loaded is True
        assert breaker._state == CircuitState.HALF_OPEN
        assert breaker._success_rate_1h == pytest.approx(0.7, rel=0.01)
        assert breaker._consecutive_failures == 3

    @pytest.mark.asyncio
    async def test_load_from_db_not_found(self, test_database):
        """Test loading returns False when engine not found."""
        # Given: Empty database
        from src.search import circuit_breaker

        breaker = EngineCircuitBreaker("nonexistent")

        # When: Trying to load
        with patch.object(circuit_breaker, "get_database", return_value=test_database):
            loaded = await breaker.load_from_db()

        # Then: Returns False
        assert loaded is False


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    @pytest.mark.asyncio
    async def test_check_engine_available(self):
        """Test check_engine_available function."""
        # Given: Mocked manager returning available breaker
        from src.search import circuit_breaker

        with patch.object(circuit_breaker, "get_circuit_breaker_manager") as mock_get_mgr:
            mock_manager = AsyncMock()
            mock_breaker = EngineCircuitBreaker("test")
            mock_manager.get_breaker.return_value = mock_breaker
            mock_get_mgr.return_value = mock_manager

            # When: Checking availability
            result = await check_engine_available("test")

        # Then: Returns True for available engine
        assert result is True

    @pytest.mark.asyncio
    async def test_record_engine_result_success(self):
        """Test record_engine_result for success."""
        # Given: Mocked manager
        from src.search import circuit_breaker

        with patch.object(circuit_breaker, "get_circuit_breaker_manager") as mock_get_mgr:
            mock_manager = AsyncMock()
            mock_get_mgr.return_value = mock_manager

            # When: Recording success
            await record_engine_result("test", success=True, latency_ms=100)

            # Then: record_success is called
            mock_manager.record_success.assert_called_once_with("test", 100)

    @pytest.mark.asyncio
    async def test_record_engine_result_failure(self):
        """Test record_engine_result for failure."""
        # Given: Mocked manager
        from src.search import circuit_breaker

        with patch.object(circuit_breaker, "get_circuit_breaker_manager") as mock_get_mgr:
            mock_manager = AsyncMock()
            mock_get_mgr.return_value = mock_manager

            # When: Recording failure with captcha
            await record_engine_result(
                "test",
                success=False,
                is_captcha=True,
                is_timeout=False,
            )

            # Then: record_failure is called
            mock_manager.record_failure.assert_called_once_with("test", True, False)


class TestStateTransitionScenarios:
    """Integration tests for state transition scenarios."""

    def test_full_cycle_closed_open_halfopen_closed(self):
        """Test full state transition cycle."""
        # Given: Fresh breaker with low threshold
        breaker = EngineCircuitBreaker("test", failure_threshold=2, cooldown_min=1)

        # Then: Starts closed
        assert breaker.state == CircuitState.CLOSED

        # When: Recording failures to threshold
        breaker.record_failure()
        breaker.record_failure()

        # Then: Opens
        assert breaker.state == CircuitState.OPEN

        # When: Cooldown expires
        breaker._cooldown_until = datetime.now(timezone.utc) - timedelta(seconds=1)

        # Then: Transitions to half-open
        assert breaker.state == CircuitState.HALF_OPEN

        # When: Success in half-open
        breaker.record_success()

        # Then: Closes
        assert breaker.state == CircuitState.CLOSED

    def test_half_open_failure_returns_to_open(self):
        """Test half-open failure returns to open."""
        # Given: Breaker in half-open state
        breaker = EngineCircuitBreaker("test", failure_threshold=2, cooldown_min=1)
        breaker.record_failure()
        breaker.record_failure()
        breaker._cooldown_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert breaker.state == CircuitState.HALF_OPEN

        # When: Probe failure
        breaker.record_failure()

        # Then: Returns to open with new cooldown
        assert breaker.state == CircuitState.OPEN
        assert breaker._cooldown_until > datetime.now(timezone.utc)

    def test_success_resets_failure_count(self):
        """Test success resets consecutive failure count."""
        # Given: Breaker with 2 failures (below threshold of 3)
        breaker = EngineCircuitBreaker("test", failure_threshold=3)
        breaker.record_failure()
        breaker.record_failure()
        assert breaker._consecutive_failures == 2

        # When: Recording success
        breaker.record_success()

        # Then: Counter is reset
        assert breaker._consecutive_failures == 0

        # And: Needs 3 new failures to open
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED

        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

