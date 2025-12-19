"""
Policy auto-update engine for Lancet.
Implements closed-loop control as defined in requirements §4.6.

Controls:
- Engine weights and QPS limits
- Domain cooldown times
- Headful/Tor usage ratios
- Circuit breaker states

Safeguards:
- Upper/lower bounds on all parameters
- Hysteresis to prevent oscillation
- Minimum hold times for parameter changes
"""

import asyncio
from collections.abc import ItemsView, Iterator, KeysView, ValuesView
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.utils.config import get_settings
from src.utils.logging import get_logger
from src.utils.metrics import MetricsCollector, get_metrics_collector

logger = get_logger(__name__)


class PolicyParameter(str, Enum):
    """Parameters that can be auto-adjusted."""

    ENGINE_WEIGHT = "engine_weight"
    ENGINE_QPS = "engine_qps"
    DOMAIN_QPS = "domain_qps"
    DOMAIN_COOLDOWN = "domain_cooldown"
    HEADFUL_RATIO = "headful_ratio"
    TOR_USAGE_RATIO = "tor_usage_ratio"
    BROWSER_ROUTE_RATIO = "browser_route_ratio"


@dataclass
class ParameterBounds:
    """Bounds for a controllable parameter."""

    min_value: float
    max_value: float
    default_value: float
    step_up: float  # Amount to increase per adjustment
    step_down: float  # Amount to decrease per adjustment


def _get_default_bounds() -> dict["PolicyParameter", ParameterBounds]:
    """Get default parameter bounds from DomainPolicyManager.

    Loads bounds from config/domains.yaml via DomainPolicyManager.
    Falls back to hardcoded defaults if config not available.

    Returns:
        Dictionary mapping PolicyParameter to ParameterBounds.
    """
    try:
        from src.utils.domain_policy import get_domain_policy_manager

        policy_manager = get_domain_policy_manager()
        policy_bounds = policy_manager.get_policy_bounds()

        # Map config schema to ParameterBounds
        return {
            PolicyParameter.ENGINE_WEIGHT: ParameterBounds(
                min_value=policy_bounds.engine_weight.min,
                max_value=policy_bounds.engine_weight.max,
                default_value=policy_bounds.engine_weight.default,
                step_up=policy_bounds.engine_weight.step_up,
                step_down=policy_bounds.engine_weight.step_down,
            ),
            PolicyParameter.ENGINE_QPS: ParameterBounds(
                min_value=policy_bounds.engine_qps.min,
                max_value=policy_bounds.engine_qps.max,
                default_value=policy_bounds.engine_qps.default,
                step_up=policy_bounds.engine_qps.step_up,
                step_down=policy_bounds.engine_qps.step_down,
            ),
            PolicyParameter.DOMAIN_QPS: ParameterBounds(
                min_value=policy_bounds.domain_qps.min,
                max_value=policy_bounds.domain_qps.max,
                default_value=policy_bounds.domain_qps.default,
                step_up=policy_bounds.domain_qps.step_up,
                step_down=policy_bounds.domain_qps.step_down,
            ),
            PolicyParameter.DOMAIN_COOLDOWN: ParameterBounds(
                min_value=policy_bounds.domain_cooldown.min,
                max_value=policy_bounds.domain_cooldown.max,
                default_value=policy_bounds.domain_cooldown.default,
                step_up=policy_bounds.domain_cooldown.step_up,
                step_down=policy_bounds.domain_cooldown.step_down,
            ),
            PolicyParameter.HEADFUL_RATIO: ParameterBounds(
                min_value=policy_bounds.headful_ratio.min,
                max_value=policy_bounds.headful_ratio.max,
                default_value=policy_bounds.headful_ratio.default,
                step_up=policy_bounds.headful_ratio.step_up,
                step_down=policy_bounds.headful_ratio.step_down,
            ),
            PolicyParameter.TOR_USAGE_RATIO: ParameterBounds(
                min_value=policy_bounds.tor_usage_ratio.min,
                max_value=policy_bounds.tor_usage_ratio.max,
                default_value=policy_bounds.tor_usage_ratio.default,
                step_up=policy_bounds.tor_usage_ratio.step_up,
                step_down=policy_bounds.tor_usage_ratio.step_down,
            ),
            PolicyParameter.BROWSER_ROUTE_RATIO: ParameterBounds(
                min_value=policy_bounds.browser_route_ratio.min,
                max_value=policy_bounds.browser_route_ratio.max,
                default_value=policy_bounds.browser_route_ratio.default,
                step_up=policy_bounds.browser_route_ratio.step_up,
                step_down=policy_bounds.browser_route_ratio.step_down,
            ),
        }
    except Exception as e:
        logger.warning(f"Failed to load policy bounds from config: {e}, using hardcoded defaults")
        # Fallback to hardcoded defaults
        return {
            PolicyParameter.ENGINE_WEIGHT: ParameterBounds(
                min_value=0.1,
                max_value=2.0,
                default_value=1.0,
                step_up=0.1,
                step_down=0.2,
            ),
            PolicyParameter.ENGINE_QPS: ParameterBounds(
                min_value=0.1,
                max_value=0.5,
                default_value=0.25,
                step_up=0.05,
                step_down=0.1,
            ),
            PolicyParameter.DOMAIN_QPS: ParameterBounds(
                min_value=0.05,
                max_value=0.3,
                default_value=0.2,
                step_up=0.02,
                step_down=0.05,
            ),
            PolicyParameter.DOMAIN_COOLDOWN: ParameterBounds(
                min_value=30.0,
                max_value=240.0,
                default_value=60.0,
                step_up=30.0,
                step_down=15.0,
            ),
            PolicyParameter.HEADFUL_RATIO: ParameterBounds(
                min_value=0.0,
                max_value=0.5,
                default_value=0.1,
                step_up=0.05,
                step_down=0.05,
            ),
            PolicyParameter.TOR_USAGE_RATIO: ParameterBounds(
                min_value=0.0,
                max_value=0.2,
                default_value=0.0,
                step_up=0.02,
                step_down=0.05,
            ),
            PolicyParameter.BROWSER_ROUTE_RATIO: ParameterBounds(
                min_value=0.1,
                max_value=0.5,
                default_value=0.3,
                step_up=0.05,
                step_down=0.05,
            ),
        }


# Lazy-loaded default bounds (from config)
_default_bounds: dict[PolicyParameter, ParameterBounds] | None = None


def get_default_bounds() -> dict[PolicyParameter, ParameterBounds]:
    """Get default parameter bounds (lazy-loaded singleton).

    Returns:
        Dictionary mapping PolicyParameter to ParameterBounds.
    """
    global _default_bounds
    if _default_bounds is None:
        _default_bounds = _get_default_bounds()
    return _default_bounds


def reset_default_bounds() -> None:
    """Reset default bounds cache (for testing/reloading config)."""
    global _default_bounds
    _default_bounds = None


class _DefaultBoundsProxy:
    """Proxy class that mimics dict access but loads bounds lazily."""

    def __getitem__(self, key: PolicyParameter) -> ParameterBounds:
        return get_default_bounds()[key]

    def get(
        self, key: PolicyParameter, default: ParameterBounds | None = None
    ) -> ParameterBounds | None:
        return get_default_bounds().get(key, default)

    def keys(self) -> KeysView[PolicyParameter]:
        return get_default_bounds().keys()

    def values(self) -> ValuesView[ParameterBounds]:
        return get_default_bounds().values()

    def items(self) -> ItemsView[PolicyParameter, ParameterBounds]:
        return get_default_bounds().items()

    def __iter__(self) -> Iterator[PolicyParameter]:
        return iter(get_default_bounds())

    def __len__(self) -> int:
        return len(get_default_bounds())


# Backward compatibility: DEFAULT_BOUNDS acts like a dict but loads lazily
DEFAULT_BOUNDS = _DefaultBoundsProxy()


@dataclass
class ParameterState:
    """Current state of a parameter with change tracking."""

    current_value: float
    last_changed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_direction: str = "none"  # "up", "down", "none"
    change_count: int = 0

    def can_change(self, min_interval_seconds: int = 300) -> bool:
        """Check if enough time has passed since last change.

        Args:
            min_interval_seconds: Minimum seconds between changes.

        Returns:
            True if change is allowed.
        """
        elapsed = (datetime.now(UTC) - self.last_changed_at).total_seconds()
        return elapsed >= min_interval_seconds

    def apply_change(
        self,
        new_value: float,
        direction: str,
        bounds: ParameterBounds,
    ) -> float:
        """Apply a parameter change with bounds checking.

        Args:
            new_value: Proposed new value.
            direction: "up" or "down".
            bounds: Parameter bounds.

        Returns:
            Actual new value after bounds clamping.
        """
        # Clamp to bounds
        clamped = max(bounds.min_value, min(bounds.max_value, new_value))

        self.current_value = clamped
        self.last_changed_at = datetime.now(UTC)
        self.last_direction = direction
        self.change_count += 1

        return clamped


@dataclass
class PolicyUpdate:
    """Record of a policy update."""

    timestamp: datetime
    target_type: str  # "engine", "domain"
    target_id: str
    parameter: str
    old_value: float
    new_value: float
    reason: str
    metrics_snapshot: dict[str, Any]


class PolicyEngine:
    """Engine for automatic policy adjustments.

    Runs periodic updates based on collected metrics, adjusting
    system parameters to maintain optimal performance while
    avoiding blocks and errors.
    """

    def __init__(
        self,
        metrics_collector: MetricsCollector | None = None,
        update_interval: int | None = None,
        hysteresis_interval: int | None = None,
    ):
        """Initialize policy engine.

        Args:
            metrics_collector: Metrics collector to use.
            update_interval: Seconds between policy updates.
            hysteresis_interval: Minimum seconds between parameter changes.
        """
        self._settings = get_settings()
        self._collector = metrics_collector or get_metrics_collector()

        self._update_interval = (
            update_interval
            if update_interval is not None
            else self._settings.metrics.ema_update_interval
        )
        self._hysteresis_interval = (
            hysteresis_interval
            if hysteresis_interval is not None
            else self._settings.metrics.hysteresis_min_interval
        )

        # Parameter states: {target_type}:{target_id}:{param} -> ParameterState
        self._param_states: dict[str, ParameterState] = {}

        # Update history
        self._update_history: list[PolicyUpdate] = []
        self._max_history = 1000

        # Control loop
        self._running = False
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    def _get_param_key(
        self,
        target_type: str,
        target_id: str,
        param: PolicyParameter,
    ) -> str:
        """Generate key for parameter state lookup."""
        return f"{target_type}:{target_id}:{param.value}"

    def _get_or_create_state(
        self,
        target_type: str,
        target_id: str,
        param: PolicyParameter,
    ) -> ParameterState:
        """Get or create parameter state.

        Args:
            target_type: "engine" or "domain".
            target_id: Engine or domain name.
            param: Parameter type.

        Returns:
            ParameterState instance.
        """
        key = self._get_param_key(target_type, target_id, param)

        if key not in self._param_states:
            bounds = DEFAULT_BOUNDS[param]
            self._param_states[key] = ParameterState(
                current_value=bounds.default_value,
            )

        return self._param_states[key]

    # =========================================================
    # Policy adjustment logic
    # =========================================================

    async def _adjust_engine_policy(self, engine: str) -> list[PolicyUpdate]:
        """Adjust policy for a search engine based on metrics.

        Args:
            engine: Engine name.

        Returns:
            List of policy updates made.
        """
        updates: list[PolicyUpdate] = []
        engine_metrics = self._collector.get_engine_metrics(engine)

        if not engine_metrics:
            return updates

        # Get success rate EMA
        success_rate = engine_metrics.get("success_rate", {}).get("ema_short", 0.5)
        latency = engine_metrics.get("latency_ms", {}).get("ema_short", 1000)

        # Adjust engine weight based on success rate
        weight_state = self._get_or_create_state("engine", engine, PolicyParameter.ENGINE_WEIGHT)
        weight_bounds = DEFAULT_BOUNDS[PolicyParameter.ENGINE_WEIGHT]

        if weight_state.can_change(self._hysteresis_interval):
            if success_rate < 0.5:
                # Low success rate -> decrease weight
                new_weight = weight_state.current_value - weight_bounds.step_down
                if new_weight < weight_state.current_value:
                    old_value = weight_state.current_value
                    actual = weight_state.apply_change(new_weight, "down", weight_bounds)
                    updates.append(
                        PolicyUpdate(
                            timestamp=datetime.now(UTC),
                            target_type="engine",
                            target_id=engine,
                            parameter=PolicyParameter.ENGINE_WEIGHT.value,
                            old_value=old_value,
                            new_value=actual,
                            reason=f"Low success rate: {success_rate:.2f}",
                            metrics_snapshot={"success_rate": success_rate, "latency_ms": latency},
                        )
                    )
            elif success_rate > 0.9:
                # High success rate -> increase weight
                new_weight = weight_state.current_value + weight_bounds.step_up
                if new_weight > weight_state.current_value:
                    old_value = weight_state.current_value
                    actual = weight_state.apply_change(new_weight, "up", weight_bounds)
                    updates.append(
                        PolicyUpdate(
                            timestamp=datetime.now(UTC),
                            target_type="engine",
                            target_id=engine,
                            parameter=PolicyParameter.ENGINE_WEIGHT.value,
                            old_value=old_value,
                            new_value=actual,
                            reason=f"High success rate: {success_rate:.2f}",
                            metrics_snapshot={"success_rate": success_rate, "latency_ms": latency},
                        )
                    )

        # Adjust QPS based on error patterns
        qps_state = self._get_or_create_state("engine", engine, PolicyParameter.ENGINE_QPS)
        qps_bounds = DEFAULT_BOUNDS[PolicyParameter.ENGINE_QPS]

        if qps_state.can_change(self._hysteresis_interval):
            if success_rate < 0.7:
                # Reduce QPS on poor performance
                new_qps = qps_state.current_value - qps_bounds.step_down
                old_value = qps_state.current_value
                actual = qps_state.apply_change(new_qps, "down", qps_bounds)
                if actual != old_value:
                    updates.append(
                        PolicyUpdate(
                            timestamp=datetime.now(UTC),
                            target_type="engine",
                            target_id=engine,
                            parameter=PolicyParameter.ENGINE_QPS.value,
                            old_value=old_value,
                            new_value=actual,
                            reason=f"Reducing QPS due to low success rate: {success_rate:.2f}",
                            metrics_snapshot={"success_rate": success_rate},
                        )
                    )

        return updates

    async def _adjust_domain_policy(self, domain: str) -> list[PolicyUpdate]:
        """Adjust policy for a domain based on metrics.

        Args:
            domain: Domain name.

        Returns:
            List of policy updates made.
        """
        updates: list[PolicyUpdate] = []
        domain_metrics = self._collector.get_domain_metrics(domain)

        if not domain_metrics:
            return updates

        # Get error rates
        captcha_rate = domain_metrics.get("captcha_rate", {}).get("ema_short", 0.0)
        error_403_rate = domain_metrics.get("error_403_rate", {}).get("ema_short", 0.0)
        error_429_rate = domain_metrics.get("error_429_rate", {}).get("ema_short", 0.0)
        domain_metrics.get("tor_usage", {}).get("ema_short", 0.0)

        combined_error_rate = captcha_rate + error_403_rate + error_429_rate

        # Adjust headful ratio based on error rates
        headful_state = self._get_or_create_state("domain", domain, PolicyParameter.HEADFUL_RATIO)
        headful_bounds = DEFAULT_BOUNDS[PolicyParameter.HEADFUL_RATIO]

        if headful_state.can_change(self._hysteresis_interval):
            if combined_error_rate > 0.3:
                # High error rate -> increase headful usage
                new_ratio = headful_state.current_value + headful_bounds.step_up
                old_value = headful_state.current_value
                actual = headful_state.apply_change(new_ratio, "up", headful_bounds)
                if actual != old_value:
                    updates.append(
                        PolicyUpdate(
                            timestamp=datetime.now(UTC),
                            target_type="domain",
                            target_id=domain,
                            parameter=PolicyParameter.HEADFUL_RATIO.value,
                            old_value=old_value,
                            new_value=actual,
                            reason=f"High error rate: {combined_error_rate:.2f}",
                            metrics_snapshot={
                                "captcha_rate": captcha_rate,
                                "error_403_rate": error_403_rate,
                                "error_429_rate": error_429_rate,
                            },
                        )
                    )
            elif (
                combined_error_rate < 0.05
                and headful_state.current_value > headful_bounds.default_value
            ):
                # Low error rate -> can reduce headful usage
                new_ratio = headful_state.current_value - headful_bounds.step_down
                old_value = headful_state.current_value
                actual = headful_state.apply_change(new_ratio, "down", headful_bounds)
                if actual != old_value:
                    updates.append(
                        PolicyUpdate(
                            timestamp=datetime.now(UTC),
                            target_type="domain",
                            target_id=domain,
                            parameter=PolicyParameter.HEADFUL_RATIO.value,
                            old_value=old_value,
                            new_value=actual,
                            reason=f"Low error rate: {combined_error_rate:.2f}",
                            metrics_snapshot={"combined_error_rate": combined_error_rate},
                        )
                    )

        # Adjust Tor usage based on 403/429 rates
        tor_state = self._get_or_create_state("domain", domain, PolicyParameter.TOR_USAGE_RATIO)
        tor_bounds = DEFAULT_BOUNDS[PolicyParameter.TOR_USAGE_RATIO]

        if tor_state.can_change(self._hysteresis_interval):
            if error_403_rate > 0.2 or error_429_rate > 0.2:
                # High block rate -> consider Tor
                new_ratio = tor_state.current_value + tor_bounds.step_up
                old_value = tor_state.current_value
                actual = tor_state.apply_change(new_ratio, "up", tor_bounds)
                if actual != old_value:
                    updates.append(
                        PolicyUpdate(
                            timestamp=datetime.now(UTC),
                            target_type="domain",
                            target_id=domain,
                            parameter=PolicyParameter.TOR_USAGE_RATIO.value,
                            old_value=old_value,
                            new_value=actual,
                            reason=f"High block rate - considering Tor: 403={error_403_rate:.2f}, 429={error_429_rate:.2f}",
                            metrics_snapshot={
                                "error_403_rate": error_403_rate,
                                "error_429_rate": error_429_rate,
                            },
                        )
                    )

        # Adjust cooldown based on persistent errors
        cooldown_state = self._get_or_create_state(
            "domain", domain, PolicyParameter.DOMAIN_COOLDOWN
        )
        cooldown_bounds = DEFAULT_BOUNDS[PolicyParameter.DOMAIN_COOLDOWN]

        if cooldown_state.can_change(self._hysteresis_interval):
            if captcha_rate > 0.3:
                # High CAPTCHA rate -> increase cooldown
                new_cooldown = cooldown_state.current_value + cooldown_bounds.step_up
                old_value = cooldown_state.current_value
                actual = cooldown_state.apply_change(new_cooldown, "up", cooldown_bounds)
                if actual != old_value:
                    updates.append(
                        PolicyUpdate(
                            timestamp=datetime.now(UTC),
                            target_type="domain",
                            target_id=domain,
                            parameter=PolicyParameter.DOMAIN_COOLDOWN.value,
                            old_value=old_value,
                            new_value=actual,
                            reason=f"High CAPTCHA rate: {captcha_rate:.2f}",
                            metrics_snapshot={"captcha_rate": captcha_rate},
                        )
                    )

        return updates

    async def _apply_updates_to_db(self, updates: list[PolicyUpdate]) -> None:
        """Persist policy updates to database.

        Args:
            updates: List of policy updates to persist.
        """
        if not updates:
            return

        # Lazy import to avoid circular dependency
        from src.storage.database import get_database

        db = await get_database()

        for update in updates:
            if update.target_type == "engine":
                # Update engine_health table
                if update.parameter == PolicyParameter.ENGINE_WEIGHT.value:
                    await db.execute(
                        "UPDATE engine_health SET weight = ?, updated_at = ? WHERE engine = ?",
                        (update.new_value, datetime.now(UTC).isoformat(), update.target_id),
                    )
                elif update.parameter == PolicyParameter.ENGINE_QPS.value:
                    await db.execute(
                        "UPDATE engine_health SET qps_limit = ?, updated_at = ? WHERE engine = ?",
                        (update.new_value, datetime.now(UTC).isoformat(), update.target_id),
                    )
            elif update.target_type == "domain":
                # Update domains table
                if update.parameter == PolicyParameter.HEADFUL_RATIO.value:
                    await db.execute(
                        "UPDATE domains SET headful_ratio = ?, updated_at = ? WHERE domain = ?",
                        (update.new_value, datetime.now(UTC).isoformat(), update.target_id),
                    )
                elif update.parameter == PolicyParameter.DOMAIN_COOLDOWN.value:
                    await db.execute(
                        "UPDATE domains SET cooldown_minutes = ?, updated_at = ? WHERE domain = ?",
                        (int(update.new_value), datetime.now(UTC).isoformat(), update.target_id),
                    )

            # Log the update event
            await db.log_event(
                event_type="policy_update",
                message=f"Policy updated: {update.target_type}/{update.target_id}/{update.parameter}",
                component="policy_engine",
                details={
                    "target_type": update.target_type,
                    "target_id": update.target_id,
                    "parameter": update.parameter,
                    "old_value": update.old_value,
                    "new_value": update.new_value,
                    "reason": update.reason,
                    "metrics_snapshot": update.metrics_snapshot,
                },
            )

    # =========================================================
    # Control loop
    # =========================================================

    async def _run_update_cycle(self) -> None:
        """Run a single policy update cycle."""
        async with self._lock:
            all_updates = []

            # Process engine metrics
            engine_metrics = self._collector.get_all_engine_metrics()
            for engine in engine_metrics.keys():
                updates = await self._adjust_engine_policy(engine)
                all_updates.extend(updates)

            # Process domain metrics
            domain_metrics = self._collector.get_all_domain_metrics()
            for domain in domain_metrics.keys():
                updates = await self._adjust_domain_policy(domain)
                all_updates.extend(updates)

            # Apply updates to database
            if all_updates:
                await self._apply_updates_to_db(all_updates)

                # Store in history
                self._update_history.extend(all_updates)
                if len(self._update_history) > self._max_history:
                    self._update_history = self._update_history[-self._max_history :]

                logger.info(
                    "Policy updates applied",
                    update_count=len(all_updates),
                    engines_updated=len(
                        {u.target_id for u in all_updates if u.target_type == "engine"}
                    ),
                    domains_updated=len(
                        {u.target_id for u in all_updates if u.target_type == "domain"}
                    ),
                )

    async def _update_loop(self) -> None:
        """Background loop for periodic policy updates."""
        logger.info(
            "Policy engine started",
            update_interval=self._update_interval,
            hysteresis_interval=self._hysteresis_interval,
        )

        while self._running:
            try:
                await self._run_update_cycle()
            except Exception as e:
                logger.error("Policy update cycle failed", error=str(e))

            await asyncio.sleep(self._update_interval)

    async def start(self) -> None:
        """Start the policy engine background loop."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._update_loop())

    async def stop(self) -> None:
        """Stop the policy engine background loop."""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("Policy engine stopped")

    # =========================================================
    # Manual interventions
    # =========================================================

    async def force_update(self) -> list[PolicyUpdate]:
        """Force an immediate policy update cycle.

        Returns:
            List of updates made.
        """
        await self._run_update_cycle()
        return self._update_history[-50:]  # Return recent updates

    def get_parameter_value(
        self,
        target_type: str,
        target_id: str,
        param: PolicyParameter,
    ) -> float:
        """Get current value of a parameter.

        Args:
            target_type: "engine" or "domain".
            target_id: Engine or domain name.
            param: Parameter type.

        Returns:
            Current parameter value.
        """
        state = self._get_or_create_state(target_type, target_id, param)
        return state.current_value

    async def set_parameter_value(
        self,
        target_type: str,
        target_id: str,
        param: PolicyParameter,
        value: float,
        reason: str = "Manual override",
    ) -> PolicyUpdate:
        """Manually set a parameter value.

        Args:
            target_type: "engine" or "domain".
            target_id: Engine or domain name.
            param: Parameter type.
            value: New value.
            reason: Reason for change.

        Returns:
            PolicyUpdate record.
        """
        async with self._lock:
            state = self._get_or_create_state(target_type, target_id, param)
            bounds = DEFAULT_BOUNDS[param]

            old_value = state.current_value
            direction = "up" if value > old_value else "down"
            actual = state.apply_change(value, direction, bounds)

            update = PolicyUpdate(
                timestamp=datetime.now(UTC),
                target_type=target_type,
                target_id=target_id,
                parameter=param.value,
                old_value=old_value,
                new_value=actual,
                reason=reason,
                metrics_snapshot={},
            )

            await self._apply_updates_to_db([update])
            self._update_history.append(update)

            return update

    def get_update_history(
        self,
        limit: int = 100,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get policy update history.

        Args:
            limit: Maximum number of updates to return.
            target_type: Filter by target type.
            target_id: Filter by target ID.

        Returns:
            List of update records.
        """
        history = self._update_history.copy()

        if target_type:
            history = [u for u in history if u.target_type == target_type]
        if target_id:
            history = [u for u in history if u.target_id == target_id]

        return [
            {
                "timestamp": u.timestamp.isoformat(),
                "target_type": u.target_type,
                "target_id": u.target_id,
                "parameter": u.parameter,
                "old_value": u.old_value,
                "new_value": u.new_value,
                "reason": u.reason,
            }
            for u in history[-limit:]
        ]

    # =========================================================
    # Dynamic Weight Calculation
    # =========================================================

    def calculate_dynamic_weight(
        self,
        base_weight: float,
        success_rate_1h: float,
        success_rate_24h: float,
        captcha_rate: float,
        median_latency_ms: float,
        last_used_at: datetime | None,
    ) -> tuple[float, float]:
        """Calculate dynamic weight based on engine health metrics.

        Per §3.1.1, §3.1.4, §4.6: Calculates engine weight adjustment based on
        past accuracy, failure rate, and block rate. Uses time decay to
        handle stale metrics from infrequently used engines.

        Args:
            base_weight: Base weight from config/engines.yaml (0.0-2.0).
            success_rate_1h: 1-hour EMA success rate (0.0-1.0).
            success_rate_24h: 24-hour EMA success rate (0.0-1.0).
            captcha_rate: CAPTCHA encounter rate (0.0-1.0).
            median_latency_ms: Median latency in milliseconds.
            last_used_at: Last usage timestamp for time decay calculation.

        Returns:
            Tuple of (dynamic_weight, confidence):
            - dynamic_weight: Adjusted weight (0.1-1.0)
            - confidence: Metrics confidence based on time decay (0.1-1.0)
        """
        # 1. Calculate metrics confidence (time decay)
        # Per plan: 48 hours for 90% decay to default
        if last_used_at:
            hours_since_use = (datetime.now(UTC) - last_used_at).total_seconds() / 3600
            confidence = max(0.1, 1.0 - (hours_since_use / 48))
        else:
            confidence = 0.1  # Never used = almost default

        # 2. Calculate raw dynamic weight from metrics
        # Success factor: weighted average of short and long term
        success_factor = 0.6 * success_rate_1h + 0.4 * success_rate_24h

        # CAPTCHA penalty: high CAPTCHA rate reduces weight
        captcha_penalty = 1.0 - (captcha_rate * 0.5)

        # Latency factor: high latency reduces weight (1s baseline)
        latency_factor = 1.0 / (1.0 + median_latency_ms / 1000.0)

        # Raw weight from metrics
        raw_weight = base_weight * success_factor * captcha_penalty * latency_factor

        # 3. Apply time decay: blend raw weight with base weight
        # based on confidence
        final_weight = confidence * raw_weight + (1 - confidence) * base_weight

        # 4. Clamp to valid range
        final_weight = max(0.1, min(1.0, final_weight))

        return final_weight, confidence

    async def get_dynamic_engine_weight(
        self,
        engine: str,
        category: str | None = None,
    ) -> float:
        """Get dynamic weight for an engine.

        Per §3.1.1, §3.1.4: Retrieves engine health metrics from database
        and calculates dynamic weight with time decay.

        Args:
            engine: Engine name (case-insensitive).
            category: Optional query category for future category-specific
                     weight adjustments.

        Returns:
            Dynamic weight (0.1-1.0). Returns base weight from config
            if engine not found in database or on error.
        """
        # Get base weight from engine config
        try:
            from src.search.engine_config import get_engine_config_manager

            config_manager = get_engine_config_manager()
            engine_config = config_manager.get_engine(engine)

            if engine_config is None:
                logger.debug(
                    "Engine not found in config, using default weight",
                    engine=engine,
                )
                return 1.0

            base_weight = engine_config.weight
        except Exception as e:
            logger.warning(
                "Failed to get engine config, using default weight",
                engine=engine,
                error=str(e),
            )
            return 1.0

        # Get health metrics from database
        try:
            from src.storage.database import get_database

            db = await get_database()
            metrics = await db.get_engine_health_metrics(engine)

            if metrics is None:
                logger.debug(
                    "No health metrics for engine, using base weight",
                    engine=engine,
                    base_weight=base_weight,
                )
                return base_weight

            # Parse last_used_at from updated_at
            last_used_at = None
            if metrics.get("updated_at"):
                try:
                    updated_at_str = metrics["updated_at"]
                    last_used_at = datetime.fromisoformat(updated_at_str)
                    if last_used_at.tzinfo is None:
                        last_used_at = last_used_at.replace(tzinfo=UTC)
                except (ValueError, TypeError):
                    last_used_at = None

            # Calculate dynamic weight
            dynamic_weight, confidence = self.calculate_dynamic_weight(
                base_weight=base_weight,
                success_rate_1h=metrics.get("success_rate_1h", 1.0),
                success_rate_24h=metrics.get("success_rate_24h", 1.0),
                captcha_rate=metrics.get("captcha_rate", 0.0),
                median_latency_ms=metrics.get("median_latency_ms", 1000.0),
                last_used_at=last_used_at,
            )

            logger.debug(
                "Dynamic weight calculated",
                engine=engine,
                base_weight=base_weight,
                dynamic_weight=round(dynamic_weight, 3),
                confidence=round(confidence, 3),
                category=category,
            )

            return dynamic_weight

        except Exception as e:
            logger.warning(
                "Failed to calculate dynamic weight, using base weight",
                engine=engine,
                error=str(e),
            )
            return base_weight


# Global policy engine instance
_engine: PolicyEngine | None = None


async def get_policy_engine() -> PolicyEngine:
    """Get the global policy engine instance.

    Returns:
        PolicyEngine instance.
    """
    global _engine
    if _engine is None:
        _engine = PolicyEngine()
    return _engine


async def start_policy_engine() -> None:
    """Start the global policy engine."""
    engine = await get_policy_engine()
    await engine.start()


async def stop_policy_engine() -> None:
    """Stop the global policy engine."""
    global _engine
    if _engine:
        await _engine.stop()
        _engine = None
