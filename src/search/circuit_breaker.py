"""
Circuit breaker implementation for search engines.

Manages engine health state transitions and failure recovery.
Uses the generic CircuitState from src.utils.circuit_breaker but implements
engine-specific features:
- Exponential backoff for cooldown (based on failure history, using shared backoff utilities)
- EMA metrics (success_rate, latency, captcha_rate)
- Database persistence with datetime-based cooldown

Per ADR-0006: Search engines use "エスカレーションパス" not simple retry.
The circuit breaker manages cooldown periods between escalation attempts.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from src.storage.database import get_database
from src.utils.backoff import calculate_cooldown_minutes
from src.utils.circuit_breaker import CircuitState  # Use shared enum
from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Re-export legacy symbols for convenience
__all__ = [
    "CircuitState",
    "EngineCircuitBreaker",
    "CircuitBreakerManager",
    "get_circuit_breaker_manager",
    "check_engine_available",
    "record_engine_result",
    "get_available_engines",
]


class EngineCircuitBreaker:
    """Circuit breaker for a single search engine.

    Extends the generic circuit breaker pattern with search-engine-specific
    features:
    - Exponential backoff for cooldown (based on total failures in window)
    - EMA metrics: success_rate_1h, latency_ema, captcha_rate
    - Database persistence with datetime-based cooldown
    - DomainPolicyManager integration for default configuration

    State transitions:
    - CLOSED: Normal operation. Failure count tracked.
    - OPEN: Engine disabled. Wait for cooldown before probing.
    - HALF_OPEN: Testing recovery. Single request allowed.

    Transitions:
    - CLOSED -> OPEN: consecutive_failures >= threshold
    - OPEN -> HALF_OPEN: cooldown period elapsed
    - HALF_OPEN -> CLOSED: probe success
    - HALF_OPEN -> OPEN: probe failure
    """

    def __init__(
        self,
        engine: str,
        failure_threshold: int | None = None,
        cooldown_min: int | None = None,
        cooldown_max: int | None = None,
    ):
        """Initialize circuit breaker.

        Uses DomainPolicyManager for default values if not specified.

        Args:
            engine: Engine name.
            failure_threshold: Failures before opening circuit. Default from config.
            cooldown_min: Minimum cooldown in minutes. Default from config.
            cooldown_max: Maximum cooldown in minutes. Default from config.
        """
        from src.utils.domain_policy import get_domain_policy_manager

        self.engine = engine

        # Get defaults from DomainPolicyManager if not provided
        policy_manager = get_domain_policy_manager()
        self.failure_threshold = (
            failure_threshold
            if failure_threshold is not None
            else policy_manager.get_circuit_breaker_failure_threshold()
        )
        self.cooldown_min = (
            cooldown_min
            if cooldown_min is not None
            else policy_manager.get_circuit_breaker_cooldown_min()
        )
        self.cooldown_max = (
            cooldown_max
            if cooldown_max is not None
            else policy_manager.get_circuit_breaker_cooldown_max()
        )

        # Core state (using shared CircuitState enum)
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._last_failure_at: datetime | None = None
        self._cooldown_until: datetime | None = None
        self._total_failures_in_window = 0
        self._probe_lock = asyncio.Lock()

        # Engine-specific EMA metrics
        self._success_rate_1h = 1.0
        self._latency_ema = 1000.0  # ms
        self._captcha_rate = 0.0
        self._alpha = 0.1  # EMA smoothing factor

    @property
    def state(self) -> CircuitState:
        """Get current circuit state, checking for auto-transition."""
        if self._state == CircuitState.OPEN:
            # Check if cooldown has elapsed
            if self._cooldown_until and datetime.now(UTC) >= self._cooldown_until:
                self._state = CircuitState.HALF_OPEN
                logger.info(
                    "Circuit half-opened for probing",
                    engine=self.engine,
                )
        return self._state

    @property
    def is_available(self) -> bool:
        """Check if engine is available for requests."""
        return self.state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def _calculate_cooldown(self) -> timedelta:
        """Calculate cooldown duration based on failure history.

        Uses shared exponential backoff calculation per ADR-0006.
        Cooldown is capped at cooldown_max.
        """
        # Use shared backoff utility per ADR-0006
        cooldown = calculate_cooldown_minutes(
            self._total_failures_in_window,
            base_minutes=self.cooldown_min,
            max_minutes=self.cooldown_max,
        )
        return timedelta(minutes=cooldown)

    def record_success(self, latency_ms: float | None = None) -> None:
        """Record successful request.

        Args:
            latency_ms: Request latency in milliseconds.
        """
        # Update EMA metrics
        self._success_rate_1h = self._alpha * 1.0 + (1 - self._alpha) * self._success_rate_1h

        if latency_ms is not None:
            self._latency_ema = self._alpha * latency_ms + (1 - self._alpha) * self._latency_ema

        # Reset failure count
        self._consecutive_failures = 0

        # Handle state transitions
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            self._cooldown_until = None
            self._total_failures_in_window = max(0, self._total_failures_in_window - 1)
            logger.info(
                "Circuit closed after successful probe",
                engine=self.engine,
                success_rate=round(self._success_rate_1h, 3),
            )

    def record_failure(
        self,
        is_captcha: bool = False,
        is_timeout: bool = False,
    ) -> None:
        """Record failed request.

        Args:
            is_captcha: Whether failure was due to CAPTCHA.
            is_timeout: Whether failure was due to timeout.
        """
        # Update EMA metrics
        self._success_rate_1h = self._alpha * 0.0 + (1 - self._alpha) * self._success_rate_1h

        if is_captcha:
            self._captcha_rate = self._alpha * 1.0 + (1 - self._alpha) * self._captcha_rate
        else:
            self._captcha_rate = self._alpha * 0.0 + (1 - self._alpha) * self._captcha_rate

        self._consecutive_failures += 1
        self._total_failures_in_window += 1
        self._last_failure_at = datetime.now(UTC)

        # Handle state transitions
        if self._state == CircuitState.HALF_OPEN:
            # Probe failed, reopen circuit
            self._open_circuit()
            logger.warning(
                "Circuit reopened after failed probe",
                engine=self.engine,
            )
        elif self._state == CircuitState.CLOSED:
            if self._consecutive_failures >= self.failure_threshold:
                self._open_circuit()
                logger.warning(
                    "Circuit opened due to consecutive failures",
                    engine=self.engine,
                    failures=self._consecutive_failures,
                )

    def _open_circuit(self) -> None:
        """Open the circuit and set cooldown."""
        self._state = CircuitState.OPEN
        cooldown = self._calculate_cooldown()
        self._cooldown_until = datetime.now(UTC) + cooldown

        logger.info(
            "Circuit opened",
            engine=self.engine,
            cooldown_minutes=cooldown.total_seconds() / 60,
            cooldown_until=self._cooldown_until.isoformat(),
        )

    def force_open(self, cooldown_minutes: int | None = None) -> None:
        """Force circuit open (manual intervention).

        Args:
            cooldown_minutes: Custom cooldown duration.
        """
        self._state = CircuitState.OPEN
        minutes = cooldown_minutes or self.cooldown_max
        self._cooldown_until = datetime.now(UTC) + timedelta(minutes=minutes)

        logger.info(
            "Circuit force-opened",
            engine=self.engine,
            cooldown_minutes=minutes,
        )

    def force_close(self) -> None:
        """Force circuit closed (manual intervention)."""
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._cooldown_until = None

        logger.info("Circuit force-closed", engine=self.engine)

    def get_metrics(self) -> dict[str, Any]:
        """Get current metrics.

        Returns:
            Metrics dictionary including engine-specific EMA metrics.
        """
        return {
            "engine": self.engine,
            "state": self.state.value,
            "success_rate_1h": round(self._success_rate_1h, 3),
            "latency_ema_ms": round(self._latency_ema, 1),
            "captcha_rate": round(self._captcha_rate, 3),
            "consecutive_failures": self._consecutive_failures,
            "total_failures_in_window": self._total_failures_in_window,
            "cooldown_until": self._cooldown_until.isoformat() if self._cooldown_until else None,
            "is_available": self.is_available,
        }

    async def save_to_db(self) -> None:
        """Persist circuit state to database."""
        db = await get_database()

        await db.execute(
            """
            INSERT INTO engine_health (engine, status, success_rate_1h, captcha_rate,
                                       median_latency_ms, consecutive_failures, cooldown_until)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(engine) DO UPDATE SET
                status = excluded.status,
                success_rate_1h = excluded.success_rate_1h,
                captcha_rate = excluded.captcha_rate,
                median_latency_ms = excluded.median_latency_ms,
                consecutive_failures = excluded.consecutive_failures,
                cooldown_until = excluded.cooldown_until,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                self.engine,
                self.state.value,
                self._success_rate_1h,
                self._captcha_rate,
                self._latency_ema,
                self._consecutive_failures,
                self._cooldown_until.isoformat() if self._cooldown_until else None,
            ),
        )

    async def load_from_db(self) -> bool:
        """Load circuit state from database.

        Returns:
            True if state was loaded, False if engine not found.
        """
        db = await get_database()

        row = await db.fetch_one(
            "SELECT * FROM engine_health WHERE engine = ?",
            (self.engine,),
        )

        if row is None:
            return False

        self._state = CircuitState(row["status"]) if row["status"] else CircuitState.CLOSED
        self._success_rate_1h = row.get("success_rate_1h", 1.0) or 1.0
        self._captcha_rate = row.get("captcha_rate", 0.0) or 0.0
        self._latency_ema = row.get("median_latency_ms", 1000.0) or 1000.0
        self._consecutive_failures = row.get("consecutive_failures", 0) or 0

        if row.get("cooldown_until"):
            self._cooldown_until = datetime.fromisoformat(row["cooldown_until"])
            if self._cooldown_until.tzinfo is None:
                self._cooldown_until = self._cooldown_until.replace(tzinfo=UTC)

        return True


class CircuitBreakerManager:
    """Manages circuit breakers for multiple search engines."""

    def __init__(self) -> None:
        """Initialize circuit breaker manager."""
        self._breakers: dict[str, EngineCircuitBreaker] = {}
        self._settings = get_settings()
        self._lock = asyncio.Lock()

    async def get_breaker(self, engine: str) -> EngineCircuitBreaker:
        """Get or create circuit breaker for an engine.

        Uses DomainPolicyManager for default settings via EngineCircuitBreaker.

        Args:
            engine: Engine name.

        Returns:
            Circuit breaker instance.
        """
        async with self._lock:
            if engine not in self._breakers:
                # EngineCircuitBreaker gets defaults from DomainPolicyManager
                breaker = EngineCircuitBreaker(engine=engine)
                # Try to load existing state
                await breaker.load_from_db()
                self._breakers[engine] = breaker

            return self._breakers[engine]

    async def get_available_engines(
        self,
        requested_engines: list[str] | None = None,
    ) -> list[str]:
        """Get list of available engines.

        Args:
            requested_engines: Engines to check. If None, returns all available.

        Returns:
            List of available engine names.
        """
        if requested_engines is None:
            # Return all non-open engines from database
            db = await get_database()
            rows = await db.fetch_all(
                """
                SELECT engine FROM engine_health
                WHERE status != 'open'
                  AND (cooldown_until IS NULL OR cooldown_until < ?)
                """,
                (datetime.now(UTC).isoformat(),),
            )
            return [row["engine"] for row in rows]

        available = []
        for engine in requested_engines:
            breaker = await self.get_breaker(engine)
            if breaker.is_available:
                available.append(engine)

        return available

    async def record_success(
        self,
        engine: str,
        latency_ms: float | None = None,
    ) -> None:
        """Record successful request for an engine.

        Args:
            engine: Engine name.
            latency_ms: Request latency.
        """
        breaker = await self.get_breaker(engine)
        breaker.record_success(latency_ms)
        await breaker.save_to_db()

    async def record_failure(
        self,
        engine: str,
        is_captcha: bool = False,
        is_timeout: bool = False,
    ) -> None:
        """Record failed request for an engine.

        Args:
            engine: Engine name.
            is_captcha: Whether failure was CAPTCHA.
            is_timeout: Whether failure was timeout.
        """
        breaker = await self.get_breaker(engine)
        breaker.record_failure(is_captcha=is_captcha, is_timeout=is_timeout)
        await breaker.save_to_db()

    async def get_all_metrics(self) -> list[dict[str, Any]]:
        """Get metrics for all tracked engines.

        Returns:
            List of metrics dicts.
        """
        # Load all engines from database
        db = await get_database()
        rows = await db.fetch_all("SELECT engine FROM engine_health")

        metrics = []
        for row in rows:
            breaker = await self.get_breaker(row["engine"])
            metrics.append(breaker.get_metrics())

        return metrics

    async def reset_all(self) -> None:
        """Reset all circuit breakers to closed state."""
        for breaker in self._breakers.values():
            breaker.force_close()
            await breaker.save_to_db()

        logger.info("All circuit breakers reset")


# Global manager instance
_manager: CircuitBreakerManager | None = None


async def get_circuit_breaker_manager() -> CircuitBreakerManager:
    """Get the global circuit breaker manager.

    Returns:
        CircuitBreakerManager instance.
    """
    global _manager
    if _manager is None:
        _manager = CircuitBreakerManager()
    return _manager


async def check_engine_available(engine: str) -> bool:
    """Check if an engine is available.

    Args:
        engine: Engine name.

    Returns:
        True if available.
    """
    manager = await get_circuit_breaker_manager()
    breaker = await manager.get_breaker(engine)
    return breaker.is_available


async def record_engine_result(
    engine: str,
    success: bool,
    latency_ms: float | None = None,
    is_captcha: bool = False,
    is_timeout: bool = False,
) -> None:
    """Record engine request result.

    Args:
        engine: Engine name.
        success: Whether request succeeded.
        latency_ms: Request latency.
        is_captcha: Whether failure was CAPTCHA.
        is_timeout: Whether failure was timeout.
    """
    manager = await get_circuit_breaker_manager()

    if success:
        await manager.record_success(engine, latency_ms)
    else:
        await manager.record_failure(engine, is_captcha, is_timeout)


async def get_available_engines(
    requested: list[str] | None = None,
) -> list[str]:
    """Get available engines.

    Args:
        requested: Engines to filter.

    Returns:
        List of available engines.
    """
    manager = await get_circuit_breaker_manager()
    return await manager.get_available_engines(requested)
