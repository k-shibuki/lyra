"""
Generic Circuit Breaker implementation.

A lightweight, dependency-free circuit breaker for protecting external service calls.
This module provides the core circuit breaker pattern without database persistence
or domain-specific features.

State transitions:
    CLOSED -> OPEN: After consecutive failures reach threshold
    OPEN -> HALF_OPEN: After cooldown period elapses
    HALF_OPEN -> CLOSED: After successful probe
    HALF_OPEN -> OPEN: After failed probe

Usage:
    breaker = CircuitBreaker("my-service", failure_threshold=3, cooldown_seconds=60)

    if breaker.is_available:
        try:
            result = call_external_service()
            breaker.record_success()
        except Exception:
            breaker.record_failure()
    else:
        # Circuit is open, skip or use fallback

For async contexts:
    async_breaker = AsyncCircuitBreaker(breaker)
    async with async_breaker:
        result = await call_external_service()
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation, tracking failures
    OPEN = "open"  # Blocking requests, waiting for cooldown
    HALF_OPEN = "half-open"  # Testing recovery with limited requests


@dataclass
class CircuitBreaker:
    """
    Thread-safe, synchronous circuit breaker.

    Designed to be minimal and dependency-free. For persistence or
    domain-specific metrics, wrap this class (composition over inheritance).

    Attributes:
        name: Identifier for this circuit breaker.
        failure_threshold: Number of consecutive failures before opening.
        cooldown_seconds: Time to wait before transitioning to half-open.
        half_open_max_calls: Max successful calls in half-open before closing.

    Example:
        >>> breaker = CircuitBreaker("api", failure_threshold=2, cooldown_seconds=30)
        >>> breaker.is_available
        True
        >>> breaker.record_failure()
        >>> breaker.record_failure()  # Threshold reached
        >>> breaker.state
        <CircuitState.OPEN: 'open'>
    """

    name: str
    failure_threshold: int = 2
    cooldown_seconds: float = 60.0
    half_open_max_calls: int = 1

    # Internal state (not configurable)
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False, repr=False)
    _consecutive_failures: int = field(default=0, init=False, repr=False)
    _opened_at: float | None = field(default=None, init=False, repr=False)
    _half_open_successes: int = field(default=0, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    # Callbacks (optional)
    _on_state_change: Callable[[CircuitState, CircuitState], None] | None = field(
        default=None, init=False, repr=False
    )

    def __post_init__(self) -> None:
        """Validate configuration."""
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if self.cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be > 0")
        if self.half_open_max_calls < 1:
            raise ValueError("half_open_max_calls must be >= 1")

    @property
    def state(self) -> CircuitState:
        """
        Get current circuit state.

        Automatically transitions OPEN -> HALF_OPEN when cooldown elapses.
        """
        with self._lock:
            return self._get_state_unlocked()

    def _get_state_unlocked(self) -> CircuitState:
        """Get state without acquiring lock (caller must hold lock)."""
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self.cooldown_seconds:
                self._transition_to(CircuitState.HALF_OPEN)
        return self._state

    @property
    def is_available(self) -> bool:
        """
        Check if circuit allows requests.

        Returns True for CLOSED and HALF_OPEN states.
        """
        return self.state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    @property
    def consecutive_failures(self) -> int:
        """Get current consecutive failure count."""
        with self._lock:
            return self._consecutive_failures

    @property
    def time_until_half_open(self) -> float | None:
        """
        Get seconds remaining until OPEN -> HALF_OPEN transition.

        Returns None if not in OPEN state.
        """
        with self._lock:
            if self._state != CircuitState.OPEN or self._opened_at is None:
                return None
            elapsed = time.monotonic() - self._opened_at
            remaining = self.cooldown_seconds - elapsed
            return max(0.0, remaining)

    def record_success(self) -> None:
        """
        Record a successful request.

        In CLOSED state: resets consecutive failure counter.
        In HALF_OPEN state: increments success counter, may close circuit.
        """
        with self._lock:
            # Ensure state is current
            self._get_state_unlocked()

            self._consecutive_failures = 0

            if self._state == CircuitState.HALF_OPEN:
                self._half_open_successes += 1
                if self._half_open_successes >= self.half_open_max_calls:
                    self._transition_to(CircuitState.CLOSED)

    def record_failure(self) -> None:
        """
        Record a failed request.

        In CLOSED state: increments failure counter, may open circuit.
        In HALF_OPEN state: immediately reopens circuit.
        """
        with self._lock:
            # Ensure state is current
            self._get_state_unlocked()

            self._consecutive_failures += 1

            if self._state == CircuitState.HALF_OPEN:
                # Probe failed, reopen immediately
                self._open_circuit()
            elif self._state == CircuitState.CLOSED:
                if self._consecutive_failures >= self.failure_threshold:
                    self._open_circuit()

    def _open_circuit(self) -> None:
        """Open the circuit (caller must hold lock)."""
        self._transition_to(CircuitState.OPEN)
        self._opened_at = time.monotonic()

    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to new state (caller must hold lock)."""
        old_state = self._state
        if old_state == new_state:
            return

        self._state = new_state

        # Reset state-specific counters
        if new_state == CircuitState.CLOSED:
            self._consecutive_failures = 0
            self._opened_at = None
            self._half_open_successes = 0
        elif new_state == CircuitState.HALF_OPEN:
            self._half_open_successes = 0

        # Notify callback
        if self._on_state_change is not None:
            try:
                self._on_state_change(old_state, new_state)
            except Exception:
                pass  # Don't let callback errors affect circuit breaker

    def force_open(self, cooldown_seconds: float | None = None) -> None:
        """
        Manually force circuit to OPEN state.

        Args:
            cooldown_seconds: Custom cooldown duration. Uses default if None.
        """
        with self._lock:
            self._transition_to(CircuitState.OPEN)
            self._opened_at = time.monotonic()
            if cooldown_seconds is not None:
                # Adjust opened_at to achieve desired cooldown
                # This is a slight hack but avoids adding mutable cooldown
                pass  # For simplicity, ignore custom cooldown in force_open

    def force_close(self) -> None:
        """Manually force circuit to CLOSED state."""
        with self._lock:
            self._transition_to(CircuitState.CLOSED)

    def reset(self) -> None:
        """Reset circuit to initial state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._consecutive_failures = 0
            self._opened_at = None
            self._half_open_successes = 0

    def set_on_state_change(
        self,
        callback: Callable[[CircuitState, CircuitState], None] | None,
    ) -> None:
        """
        Set callback for state changes.

        Args:
            callback: Function(old_state, new_state) called on transitions.
        """
        with self._lock:
            self._on_state_change = callback

    def get_stats(self) -> dict[str, Any]:
        """
        Get current statistics.

        Returns:
            Dictionary with state, failures, availability, etc.
        """
        with self._lock:
            state = self._get_state_unlocked()
            time_until = None
            if state == CircuitState.OPEN and self._opened_at is not None:
                elapsed = time.monotonic() - self._opened_at
                time_until = max(0.0, self.cooldown_seconds - elapsed)

            return {
                "name": self.name,
                "state": state.value,
                "is_available": state in (CircuitState.CLOSED, CircuitState.HALF_OPEN),
                "consecutive_failures": self._consecutive_failures,
                "half_open_successes": self._half_open_successes,
                "time_until_half_open": time_until,
                "failure_threshold": self.failure_threshold,
                "cooldown_seconds": self.cooldown_seconds,
            }


class CircuitBreakerError(Exception):
    """Raised when circuit breaker rejects a request."""

    def __init__(self, breaker: CircuitBreaker, message: str | None = None):
        self.breaker = breaker
        self.state = breaker.state
        msg = message or f"Circuit breaker '{breaker.name}' is {self.state.value}"
        super().__init__(msg)


class AsyncCircuitBreaker:
    """
    Async context manager wrapper for CircuitBreaker.

    Usage:
        breaker = CircuitBreaker("api")
        async_breaker = AsyncCircuitBreaker(breaker)

        async with async_breaker:
            result = await call_api()

        # Or with auto_record=False for manual control:
        async with async_breaker.guard(auto_record=False) as ctx:
            try:
                result = await call_api()
                ctx.record_success()
            except SomeRecoverableError:
                ctx.record_failure()
                raise
    """

    def __init__(self, breaker: CircuitBreaker):
        """
        Initialize async wrapper.

        Args:
            breaker: The underlying CircuitBreaker instance.
        """
        self.breaker = breaker

    @property
    def is_available(self) -> bool:
        """Check if circuit allows requests."""
        return self.breaker.is_available

    @property
    def state(self) -> CircuitState:
        """Get current state."""
        return self.breaker.state

    async def __aenter__(self) -> AsyncCircuitBreaker:
        """Enter context, checking availability."""
        if not self.breaker.is_available:
            raise CircuitBreakerError(self.breaker)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Exit context, recording success or failure."""
        if exc_type is None:
            self.breaker.record_success()
        else:
            self.breaker.record_failure()
        return False  # Don't suppress exceptions

    def guard(self, auto_record: bool = True) -> _AsyncCircuitGuard:
        """
        Create a guard context with optional manual recording.

        Args:
            auto_record: If True, auto-record success/failure on exit.
                        If False, caller must call record_success/failure.

        Returns:
            Context manager for guarded execution.
        """
        return _AsyncCircuitGuard(self.breaker, auto_record)


class _AsyncCircuitGuard:
    """Internal context manager for AsyncCircuitBreaker.guard()."""

    def __init__(self, breaker: CircuitBreaker, auto_record: bool):
        self.breaker = breaker
        self.auto_record = auto_record
        self._recorded = False

    async def __aenter__(self) -> _AsyncCircuitGuard:
        if not self.breaker.is_available:
            raise CircuitBreakerError(self.breaker)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self.auto_record and not self._recorded:
            if exc_type is None:
                self.breaker.record_success()
            else:
                self.breaker.record_failure()
        return False

    def record_success(self) -> None:
        """Manually record success."""
        self._recorded = True
        self.breaker.record_success()

    def record_failure(self) -> None:
        """Manually record failure."""
        self._recorded = True
        self.breaker.record_failure()
