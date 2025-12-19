"""
Tests for the generic CircuitBreaker in src/utils/circuit_breaker.py.

Test Perspectives Table:
| Case ID   | Input / Precondition                      | Perspective                    | Expected Result                              | Notes |
|-----------|-------------------------------------------|--------------------------------|----------------------------------------------|-------|
| TC-N-01   | New breaker, record success               | Equivalence - normal           | State stays CLOSED, failures reset           | -     |
| TC-N-02   | CLOSED, failures < threshold              | Equivalence - normal           | State stays CLOSED                           | -     |
| TC-N-03   | CLOSED, failures = threshold              | Boundary - threshold           | State transitions to OPEN                    | -     |
| TC-N-04   | OPEN, cooldown elapsed                    | Equivalence - normal           | State transitions to HALF_OPEN               | -     |
| TC-N-05   | HALF_OPEN, record success                 | Equivalence - normal           | State transitions to CLOSED                  | -     |
| TC-N-06   | HALF_OPEN, record failure                 | Equivalence - normal           | State transitions to OPEN                    | -     |
| TC-A-01   | failure_threshold = 0                     | Boundary - invalid             | ValueError raised                            | -     |
| TC-A-02   | cooldown_seconds = 0                      | Boundary - invalid             | ValueError raised                            | -     |
| TC-A-03   | half_open_max_calls = 0                   | Boundary - invalid             | ValueError raised                            | -     |
| TC-B-01   | failure_threshold = 1                     | Boundary - min valid           | Single failure opens circuit                 | -     |
| TC-B-02   | cooldown_seconds = 0.001                  | Boundary - min valid           | Immediate transition to HALF_OPEN            | -     |
| TC-B-03   | half_open_max_calls = 2                   | Boundary - multiple            | Needs 2 successes to close                   | -     |
| TC-F-01   | force_open()                              | Equivalence - manual           | State forced to OPEN                         | -     |
| TC-F-02   | force_close()                             | Equivalence - manual           | State forced to CLOSED, counters reset       | -     |
| TC-F-03   | reset()                                   | Equivalence - manual           | All state reset to initial                   | -     |
| TC-C-01   | State change callback                     | Equivalence - callback         | Callback invoked with old/new state          | -     |
| TC-C-02   | Callback raises exception                 | Boundary - exception           | Circuit breaker continues, no crash          | -     |
| TC-S-01   | get_stats() in CLOSED                     | Equivalence - stats            | Returns correct stats dict                   | -     |
| TC-S-02   | get_stats() in OPEN                       | Equivalence - stats            | Returns stats with time_until_half_open      | -     |
| TC-T-01   | Thread safety - concurrent access         | Equivalence - thread           | No race conditions                           | -     |
| TC-AS-01  | AsyncCircuitBreaker context success       | Equivalence - async            | Success recorded, no exception               | -     |
| TC-AS-02  | AsyncCircuitBreaker context failure       | Equivalence - async            | Failure recorded, exception re-raised        | -     |
| TC-AS-03  | AsyncCircuitBreaker when OPEN             | Equivalence - async            | CircuitBreakerError raised                   | -     |
| TC-AS-04  | AsyncCircuitBreaker.guard() manual record | Equivalence - async            | Manual recording works                       | -     |
"""

import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.utils.circuit_breaker import (
    AsyncCircuitBreaker,
    CircuitBreaker,
    CircuitBreakerError,
    CircuitState,
)

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def breaker() -> CircuitBreaker:
    """Create a standard circuit breaker for testing."""
    return CircuitBreaker(
        name="test-service",
        failure_threshold=2,
        cooldown_seconds=1.0,
        half_open_max_calls=1,
    )


@pytest.fixture
def fast_breaker() -> CircuitBreaker:
    """Create a circuit breaker with very short cooldown for testing."""
    return CircuitBreaker(
        name="fast-test",
        failure_threshold=1,
        cooldown_seconds=0.01,
        half_open_max_calls=1,
    )


# =============================================================================
# Normal Cases
# =============================================================================


class TestCircuitBreakerNormalCases:
    """Tests for normal circuit breaker operation."""

    def test_initial_state_is_closed(self, breaker: CircuitBreaker) -> None:
        """
        TC-N-01: Verify initial state is CLOSED.

        Given: A newly created circuit breaker
        When: Checking state
        Then: State should be CLOSED and available
        """
        # Given: breaker created in fixture

        # When/Then
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_available is True
        assert breaker.consecutive_failures == 0

    def test_record_success_resets_failures(self, breaker: CircuitBreaker) -> None:
        """
        TC-N-01: Success resets consecutive failure count.

        Given: A circuit breaker with some failures
        When: Recording a success
        Then: Failure count should reset to 0
        """
        # Given
        breaker.record_failure()
        assert breaker.consecutive_failures == 1

        # When
        breaker.record_success()

        # Then
        assert breaker.consecutive_failures == 0
        assert breaker.state == CircuitState.CLOSED

    def test_failures_below_threshold_stay_closed(
        self, breaker: CircuitBreaker
    ) -> None:
        """
        TC-N-02: Failures below threshold keep circuit CLOSED.

        Given: A circuit breaker with threshold=2
        When: Recording 1 failure
        Then: Circuit stays CLOSED
        """
        # Given: breaker with threshold=2

        # When
        breaker.record_failure()

        # Then
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_available is True
        assert breaker.consecutive_failures == 1

    def test_failures_at_threshold_opens_circuit(
        self, breaker: CircuitBreaker
    ) -> None:
        """
        TC-N-03: Failures reaching threshold opens circuit.

        Given: A circuit breaker with threshold=2
        When: Recording 2 consecutive failures
        Then: Circuit transitions to OPEN
        """
        # Given: breaker with threshold=2

        # When
        breaker.record_failure()
        breaker.record_failure()

        # Then
        assert breaker.state == CircuitState.OPEN
        assert breaker.is_available is False
        assert breaker.consecutive_failures == 2

    def test_cooldown_elapsed_transitions_to_half_open(
        self, fast_breaker: CircuitBreaker
    ) -> None:
        """
        TC-N-04: After cooldown, OPEN transitions to HALF_OPEN.

        Given: A circuit breaker in OPEN state
        When: Cooldown period elapses
        Then: State transitions to HALF_OPEN on next check
        """
        # Given
        fast_breaker.record_failure()  # Opens with threshold=1
        assert fast_breaker.state == CircuitState.OPEN

        # When: Wait for cooldown (0.01s)
        time.sleep(0.02)

        # Then: State should transition on property access
        assert fast_breaker.state == CircuitState.HALF_OPEN
        assert fast_breaker.is_available is True

    def test_half_open_success_closes_circuit(
        self, fast_breaker: CircuitBreaker
    ) -> None:
        """
        TC-N-05: Success in HALF_OPEN state closes circuit.

        Given: A circuit breaker in HALF_OPEN state
        When: Recording a success
        Then: Circuit transitions to CLOSED
        """
        # Given
        fast_breaker.record_failure()
        time.sleep(0.02)
        assert fast_breaker.state == CircuitState.HALF_OPEN

        # When
        fast_breaker.record_success()

        # Then
        assert fast_breaker.state == CircuitState.CLOSED
        assert fast_breaker.is_available is True

    def test_half_open_failure_reopens_circuit(
        self, fast_breaker: CircuitBreaker
    ) -> None:
        """
        TC-N-06: Failure in HALF_OPEN state reopens circuit.

        Given: A circuit breaker in HALF_OPEN state
        When: Recording a failure
        Then: Circuit transitions back to OPEN
        """
        # Given
        fast_breaker.record_failure()
        time.sleep(0.02)
        assert fast_breaker.state == CircuitState.HALF_OPEN

        # When
        fast_breaker.record_failure()

        # Then
        assert fast_breaker.state == CircuitState.OPEN
        assert fast_breaker.is_available is False


# =============================================================================
# Boundary Cases - Invalid Configuration
# =============================================================================


class TestCircuitBreakerInvalidConfig:
    """Tests for invalid configuration values."""

    def test_failure_threshold_zero_raises(self) -> None:
        """
        TC-A-01: failure_threshold=0 should raise ValueError.

        Given: Creating a circuit breaker with failure_threshold=0
        When: Initialization
        Then: ValueError is raised
        """
        # Given/When/Then
        with pytest.raises(ValueError, match="failure_threshold must be >= 1"):
            CircuitBreaker(name="test", failure_threshold=0)

    def test_cooldown_zero_raises(self) -> None:
        """
        TC-A-02: cooldown_seconds=0 should raise ValueError.

        Given: Creating a circuit breaker with cooldown_seconds=0
        When: Initialization
        Then: ValueError is raised
        """
        # Given/When/Then
        with pytest.raises(ValueError, match="cooldown_seconds must be > 0"):
            CircuitBreaker(name="test", cooldown_seconds=0)

    def test_cooldown_negative_raises(self) -> None:
        """
        TC-A-02: Negative cooldown should raise ValueError.

        Given: Creating a circuit breaker with negative cooldown
        When: Initialization
        Then: ValueError is raised
        """
        # Given/When/Then
        with pytest.raises(ValueError, match="cooldown_seconds must be > 0"):
            CircuitBreaker(name="test", cooldown_seconds=-1)

    def test_half_open_max_calls_zero_raises(self) -> None:
        """
        TC-A-03: half_open_max_calls=0 should raise ValueError.

        Given: Creating a circuit breaker with half_open_max_calls=0
        When: Initialization
        Then: ValueError is raised
        """
        # Given/When/Then
        with pytest.raises(ValueError, match="half_open_max_calls must be >= 1"):
            CircuitBreaker(name="test", half_open_max_calls=0)


# =============================================================================
# Boundary Cases - Minimum Valid Values
# =============================================================================


class TestCircuitBreakerBoundaryValues:
    """Tests for boundary value cases."""

    def test_failure_threshold_one(self) -> None:
        """
        TC-B-01: Single failure opens circuit with threshold=1.

        Given: A circuit breaker with failure_threshold=1
        When: Recording one failure
        Then: Circuit immediately opens
        """
        # Given
        breaker = CircuitBreaker(name="test", failure_threshold=1)

        # When
        breaker.record_failure()

        # Then
        assert breaker.state == CircuitState.OPEN

    def test_minimal_cooldown(self) -> None:
        """
        TC-B-02: Very short cooldown works correctly.

        Given: A circuit breaker with cooldown_seconds=0.001
        When: Opening and waiting
        Then: Transitions to HALF_OPEN almost immediately
        """
        # Given
        breaker = CircuitBreaker(
            name="test",
            failure_threshold=1,
            cooldown_seconds=0.001,
        )
        breaker.record_failure()

        # When
        time.sleep(0.005)

        # Then
        assert breaker.state == CircuitState.HALF_OPEN

    def test_half_open_requires_multiple_successes(self) -> None:
        """
        TC-B-03: half_open_max_calls=2 requires 2 successes.

        Given: A circuit breaker with half_open_max_calls=2
        When: In HALF_OPEN state
        Then: Needs 2 successes to close
        """
        # Given
        breaker = CircuitBreaker(
            name="test",
            failure_threshold=1,
            cooldown_seconds=0.001,
            half_open_max_calls=2,
        )
        breaker.record_failure()
        time.sleep(0.005)
        assert breaker.state == CircuitState.HALF_OPEN

        # When: First success
        breaker.record_success()

        # Then: Still HALF_OPEN
        assert breaker.state == CircuitState.HALF_OPEN

        # When: Second success
        breaker.record_success()

        # Then: Now CLOSED
        assert breaker.state == CircuitState.CLOSED


# =============================================================================
# Force Operations
# =============================================================================


class TestCircuitBreakerForceOperations:
    """Tests for manual force operations."""

    def test_force_open(self, breaker: CircuitBreaker) -> None:
        """
        TC-F-01: force_open() sets state to OPEN.

        Given: A circuit breaker in CLOSED state
        When: Calling force_open()
        Then: State becomes OPEN
        """
        # Given
        assert breaker.state == CircuitState.CLOSED

        # When
        breaker.force_open()

        # Then
        assert breaker.state == CircuitState.OPEN
        assert breaker.is_available is False

    def test_force_close(self, breaker: CircuitBreaker) -> None:
        """
        TC-F-02: force_close() resets to CLOSED state.

        Given: A circuit breaker in OPEN state with failures
        When: Calling force_close()
        Then: State becomes CLOSED, counters reset
        """
        # Given
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # When
        breaker.force_close()

        # Then
        assert breaker.state == CircuitState.CLOSED
        assert breaker.consecutive_failures == 0
        assert breaker.is_available is True

    def test_reset(self, breaker: CircuitBreaker) -> None:
        """
        TC-F-03: reset() returns to initial state.

        Given: A circuit breaker with modified state
        When: Calling reset()
        Then: All state returns to initial values
        """
        # Given
        breaker.record_failure()
        breaker.record_failure()

        # When
        breaker.reset()

        # Then
        assert breaker.state == CircuitState.CLOSED
        assert breaker.consecutive_failures == 0
        assert breaker.time_until_half_open is None


# =============================================================================
# Callback Tests
# =============================================================================


class TestCircuitBreakerCallbacks:
    """Tests for state change callbacks."""

    def test_callback_invoked_on_state_change(
        self, breaker: CircuitBreaker
    ) -> None:
        """
        TC-C-01: Callback is invoked when state changes.

        Given: A circuit breaker with callback registered
        When: State transitions
        Then: Callback receives old and new state
        """
        # Given
        transitions: list[tuple[CircuitState, CircuitState]] = []

        def on_change(old: CircuitState, new: CircuitState) -> None:
            transitions.append((old, new))

        breaker.set_on_state_change(on_change)

        # When: Trigger CLOSED -> OPEN
        breaker.record_failure()
        breaker.record_failure()

        # Then
        assert len(transitions) == 1
        assert transitions[0] == (CircuitState.CLOSED, CircuitState.OPEN)

    def test_callback_exception_does_not_crash(
        self, fast_breaker: CircuitBreaker
    ) -> None:
        """
        TC-C-02: Exception in callback doesn't crash circuit breaker.

        Given: A circuit breaker with callback that raises
        When: State transitions
        Then: Circuit breaker continues to function
        """

        # Given
        def bad_callback(old: CircuitState, new: CircuitState) -> None:
            raise RuntimeError("Callback error!")

        fast_breaker.set_on_state_change(bad_callback)

        # When: Trigger state change (should not raise)
        fast_breaker.record_failure()

        # Then: Circuit breaker still works
        assert fast_breaker.state == CircuitState.OPEN


# =============================================================================
# Statistics Tests
# =============================================================================


class TestCircuitBreakerStats:
    """Tests for get_stats() method."""

    def test_stats_closed_state(self, breaker: CircuitBreaker) -> None:
        """
        TC-S-01: get_stats() in CLOSED state returns correct data.

        Given: A circuit breaker in CLOSED state
        When: Calling get_stats()
        Then: Returns dict with correct values
        """
        # Given
        breaker.record_failure()

        # When
        stats = breaker.get_stats()

        # Then
        assert stats["name"] == "test-service"
        assert stats["state"] == "closed"
        assert stats["is_available"] is True
        assert stats["consecutive_failures"] == 1
        assert stats["time_until_half_open"] is None
        assert stats["failure_threshold"] == 2
        assert stats["cooldown_seconds"] == 1.0

    def test_stats_open_state(self, breaker: CircuitBreaker) -> None:
        """
        TC-S-02: get_stats() in OPEN state includes time_until_half_open.

        Given: A circuit breaker in OPEN state
        When: Calling get_stats()
        Then: Returns stats with time_until_half_open > 0
        """
        # Given
        breaker.record_failure()
        breaker.record_failure()

        # When
        stats = breaker.get_stats()

        # Then
        assert stats["state"] == "open"
        assert stats["is_available"] is False
        assert stats["time_until_half_open"] is not None
        assert stats["time_until_half_open"] > 0
        assert stats["time_until_half_open"] <= 1.0


# =============================================================================
# Thread Safety Tests
# =============================================================================


class TestCircuitBreakerThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_access(self, breaker: CircuitBreaker) -> None:
        """
        TC-T-01: Concurrent access doesn't cause race conditions.

        Given: A circuit breaker
        When: Multiple threads access simultaneously
        Then: No race conditions or crashes
        """
        # Given
        errors: list[Exception] = []

        def worker(thread_id: int) -> None:
            try:
                for _ in range(100):
                    if thread_id % 2 == 0:
                        breaker.record_success()
                    else:
                        breaker.record_failure()
                    _ = breaker.state
                    _ = breaker.is_available
                    _ = breaker.get_stats()
            except Exception as e:
                errors.append(e)

        # When
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(worker, i) for i in range(4)]
            for f in futures:
                f.result()

        # Then
        assert errors == [], f"Thread errors: {errors}"


# =============================================================================
# Async Circuit Breaker Tests
# =============================================================================


class TestAsyncCircuitBreaker:
    """Tests for AsyncCircuitBreaker wrapper."""

    @pytest.mark.asyncio
    async def test_context_manager_success(self, breaker: CircuitBreaker) -> None:
        """
        TC-AS-01: Successful operation records success.

        Given: An async circuit breaker
        When: Using context manager without exception
        Then: Success is recorded
        """
        # Given
        async_breaker = AsyncCircuitBreaker(breaker)
        breaker.record_failure()  # Start with 1 failure

        # When
        async with async_breaker:
            pass  # Simulating successful operation

        # Then
        assert breaker.consecutive_failures == 0  # Reset by success

    @pytest.mark.asyncio
    async def test_context_manager_failure(self, breaker: CircuitBreaker) -> None:
        """
        TC-AS-02: Exception records failure and re-raises.

        Given: An async circuit breaker
        When: Using context manager with exception
        Then: Failure is recorded and exception is re-raised
        """
        # Given
        async_breaker = AsyncCircuitBreaker(breaker)

        # When/Then
        with pytest.raises(ValueError, match="test error"):
            async with async_breaker:
                raise ValueError("test error")

        assert breaker.consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_context_manager_when_open(self, breaker: CircuitBreaker) -> None:
        """
        TC-AS-03: CircuitBreakerError raised when OPEN.

        Given: An async circuit breaker in OPEN state
        When: Entering context manager
        Then: CircuitBreakerError is raised
        """
        # Given
        breaker.record_failure()
        breaker.record_failure()
        async_breaker = AsyncCircuitBreaker(breaker)

        # When/Then
        with pytest.raises(CircuitBreakerError) as exc_info:
            async with async_breaker:
                pass

        assert exc_info.value.breaker is breaker
        assert exc_info.value.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_guard_manual_record(self, breaker: CircuitBreaker) -> None:
        """
        TC-AS-04: guard() with manual recording works.

        Given: An async circuit breaker with guard()
        When: Manually recording success
        Then: Success is recorded, no auto-record on exit
        """
        # Given
        async_breaker = AsyncCircuitBreaker(breaker)
        breaker.record_failure()  # Start with failure

        # When
        async with async_breaker.guard(auto_record=False) as ctx:
            # Do some work...
            ctx.record_success()  # Manual success

        # Then: Success was recorded
        assert breaker.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_guard_auto_record_false_exception(self, breaker: CircuitBreaker) -> None:
        """
        TC-AS-04: guard(auto_record=False) doesn't auto-record on exception.

        Given: An async circuit breaker with guard(auto_record=False)
        When: Exception raised without manual record
        Then: No failure recorded (auto_record=False)
        """
        # Given
        async_breaker = AsyncCircuitBreaker(breaker)

        # When
        with pytest.raises(ValueError):
            async with async_breaker.guard(auto_record=False):
                raise ValueError("error")

        # Then: No failure recorded (auto_record was False)
        assert breaker.consecutive_failures == 0


# =============================================================================
# CircuitBreakerError Tests
# =============================================================================


class TestCircuitBreakerError:
    """Tests for CircuitBreakerError exception."""

    def test_error_contains_breaker_info(
        self, breaker: CircuitBreaker
    ) -> None:
        """
        Verify error contains breaker and state info.

        Given: A circuit breaker in OPEN state
        When: Creating CircuitBreakerError
        Then: Error contains breaker reference and state
        """
        # Given
        breaker.force_open()

        # When
        error = CircuitBreakerError(breaker)

        # Then
        assert error.breaker is breaker
        assert error.state == CircuitState.OPEN
        assert "test-service" in str(error)
        assert "open" in str(error)

    def test_error_custom_message(self, breaker: CircuitBreaker) -> None:
        """
        Verify custom message is used.

        Given: A circuit breaker
        When: Creating error with custom message
        Then: Custom message is used
        """
        # Given/When
        error = CircuitBreakerError(breaker, "Custom error message")

        # Then
        assert str(error) == "Custom error message"


# =============================================================================
# Time Until Half Open Tests
# =============================================================================


class TestTimeUntilHalfOpen:
    """Tests for time_until_half_open property."""

    def test_none_when_closed(self, breaker: CircuitBreaker) -> None:
        """
        time_until_half_open is None when CLOSED.

        Given: A circuit breaker in CLOSED state
        When: Accessing time_until_half_open
        Then: Returns None
        """
        # Given/When/Then
        assert breaker.time_until_half_open is None

    def test_positive_when_open(self, breaker: CircuitBreaker) -> None:
        """
        time_until_half_open is positive when OPEN.

        Given: A circuit breaker in OPEN state
        When: Accessing time_until_half_open
        Then: Returns positive value
        """
        # Given
        breaker.record_failure()
        breaker.record_failure()

        # When
        remaining = breaker.time_until_half_open

        # Then
        assert remaining is not None
        assert remaining > 0
        assert remaining <= breaker.cooldown_seconds

    def test_decreases_over_time(self, breaker: CircuitBreaker) -> None:
        """
        time_until_half_open decreases as time passes.

        Given: A circuit breaker in OPEN state
        When: Time passes
        Then: Remaining time decreases
        """
        # Given
        breaker.record_failure()
        breaker.record_failure()
        first = breaker.time_until_half_open

        # When
        time.sleep(0.1)
        second = breaker.time_until_half_open

        # Then
        assert first is not None
        assert second is not None
        assert second < first
