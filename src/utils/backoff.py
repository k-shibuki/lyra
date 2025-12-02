"""
Exponential backoff calculation utilities.

Shared by:
- SearchEngineCircuitBreaker (src/search/circuit_breaker.py)
- APIRetryPolicy (src/utils/api_retry.py)
- DomainPolicy cooldown calculation (src/utils/domain_policy.py)

Per §4.3.5: Exponential backoff calculation for retry strategies.
Per §4.3: "429/403検出時は指数バックオフ...を適用"
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class BackoffConfig:
    """Configuration for exponential backoff calculation.
    
    Per §4.3.5:
    - base_delay: Starting delay in seconds (default: 1.0)
    - max_delay: Maximum delay cap in seconds (default: 60.0)
    - exponential_base: Base for exponential calculation (default: 2.0)
    - jitter_factor: Random variation factor ±10% (default: 0.1)
    
    Example:
        >>> config = BackoffConfig(base_delay=2.0, max_delay=120.0)
    """
    
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter_factor: float = 0.1  # ±10%
    
    def __post_init__(self) -> None:
        """Validate configuration."""
        if self.base_delay <= 0:
            raise ValueError("base_delay must be positive")
        if self.max_delay <= 0:
            raise ValueError("max_delay must be positive")
        if self.max_delay < self.base_delay:
            raise ValueError("max_delay must be >= base_delay")
        if self.exponential_base <= 1:
            raise ValueError("exponential_base must be > 1")
        if self.jitter_factor < 0 or self.jitter_factor > 1:
            raise ValueError("jitter_factor must be between 0 and 1")


def calculate_backoff(
    attempt: int,
    config: BackoffConfig | None = None,
    *,
    add_jitter: bool = True,
) -> float:
    """Calculate delay with exponential backoff and optional jitter.
    
    Per §4.3.5: delay = min(base_delay * (2 ^ attempt), max_delay)
    With jitter: ±jitter_factor random variation
    
    Args:
        attempt: Attempt number (0-indexed, 0 = first retry)
        config: Backoff configuration (default: BackoffConfig())
        add_jitter: Whether to add random jitter (default: True)
    
    Returns:
        Delay in seconds
    
    Example:
        >>> calculate_backoff(0)  # First retry: ~1s (base)
        1.05  # with jitter
        >>> calculate_backoff(1)  # Second retry: ~2s
        2.1   # with jitter
        >>> calculate_backoff(2)  # Third retry: ~4s
        3.9   # with jitter
        >>> calculate_backoff(10)  # Capped at max_delay
        58.5  # ~60s with jitter
    
    Note:
        The jitter helps prevent "thundering herd" problems where
        many clients retry simultaneously after a shared failure.
    """
    if attempt < 0:
        raise ValueError("attempt must be non-negative")
    
    if config is None:
        config = BackoffConfig()
    
    # Calculate exponential delay with cap
    # Per §4.3.5: delay = min(base_delay * (2 ^ attempt), max_delay)
    delay = min(
        config.base_delay * (config.exponential_base ** attempt),
        config.max_delay,
    )
    
    # Add jitter to prevent thundering herd
    # Per §4.3.5: ±10% random variation
    if add_jitter and config.jitter_factor > 0:
        jitter_range = delay * config.jitter_factor
        delay += random.uniform(-jitter_range, jitter_range)
    
    return max(0.0, delay)


def calculate_cooldown_minutes(
    failure_count: int,
    base_minutes: int = 30,
    max_minutes: int = 120,
) -> int:
    """Calculate cooldown duration for circuit breaker / domain policy.
    
    Per §4.3.5: cooldown = min(base_minutes * (2 ^ (failures // 3)), max_minutes)
    Per §4.3: "クールダウン≥30分"
    Per §3.1.4: "自動無効化: TTL（30〜120分）"
    
    The formula groups failures into tiers of 3, doubling cooldown each tier:
    - 0-2 failures: base_minutes (30 min default)
    - 3-5 failures: base_minutes * 2 (60 min)
    - 6-8 failures: base_minutes * 4 (120 min, capped)
    - 9+ failures: max_minutes (120 min)
    
    Args:
        failure_count: Number of failures (can be consecutive or total in window)
        base_minutes: Minimum cooldown (default: 30 per §4.3)
        max_minutes: Maximum cooldown (default: 120 per §3.1.4)
    
    Returns:
        Cooldown duration in minutes
    
    Example:
        >>> calculate_cooldown_minutes(0)  # No failures yet
        30
        >>> calculate_cooldown_minutes(2)  # Still in first tier
        30
        >>> calculate_cooldown_minutes(3)  # Second tier
        60
        >>> calculate_cooldown_minutes(6)  # Third tier
        120
        >>> calculate_cooldown_minutes(100)  # Capped
        120
    """
    if failure_count < 0:
        raise ValueError("failure_count must be non-negative")
    if base_minutes <= 0:
        raise ValueError("base_minutes must be positive")
    if max_minutes <= 0:
        raise ValueError("max_minutes must be positive")
    if max_minutes < base_minutes:
        raise ValueError("max_minutes must be >= base_minutes")
    
    # Calculate exponential factor based on failure tiers
    # Each 3 failures doubles the cooldown, capped at 4x
    factor = min(2 ** (failure_count // 3), 4)
    
    # Apply factor and cap at max
    return min(base_minutes * factor, max_minutes)


def calculate_total_delay(
    max_retries: int,
    config: BackoffConfig | None = None,
) -> float:
    """Calculate total delay for all retry attempts (worst case).
    
    Useful for estimating timeout budgets.
    
    Args:
        max_retries: Maximum number of retry attempts
        config: Backoff configuration
    
    Returns:
        Total delay in seconds (without jitter)
    
    Example:
        >>> calculate_total_delay(3)  # 1 + 2 + 4 = 7 seconds
        7.0
        >>> calculate_total_delay(5)  # 1 + 2 + 4 + 8 + 16 = 31 seconds
        31.0
    """
    if max_retries < 0:
        raise ValueError("max_retries must be non-negative")
    
    if config is None:
        config = BackoffConfig()
    
    total = 0.0
    for attempt in range(max_retries):
        total += calculate_backoff(attempt, config, add_jitter=False)
    
    return total

