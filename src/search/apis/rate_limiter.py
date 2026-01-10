"""
Global rate limiter for academic APIs.

Enforces per-provider QPS limits across all worker instances.
Per ADR-0013: Worker Resource Contention Control.
Per ADR-0013: Adaptive Concurrency Control (auto-backoff on 429).

Design:
- Each provider (semantic_scholar, openalex) has its own rate limit settings
- Limits are loaded from config/academic_apis.yaml with profile-based selection
- Profiles: anonymous (no credentials), authenticated (S2 with API key), identified (OA with email)
- Both QPS (min_interval) and concurrency (max_parallel) are enforced
- Thread-safe for asyncio concurrent access
- Auto-backoff: reduces effective_max_parallel on 429, recovers after stable period
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.config import AcademicAPIConfig, AcademicAPIsConfig

logger = get_logger(__name__)

# Default timeout for acquiring rate limit slots (seconds).
# Designed for thoroughness over speed: Academic APIs are the primary source
# for structured, high-quality references. We wait longer to ensure comprehensive
# coverage rather than fail fast.
#
# Previous value (30s) caused many API calls to timeout and lose results.
# New value (300s) aligns with pipeline timeout, ensuring we collect as many
# academic references as possible within the overall time budget.
DEFAULT_SLOT_ACQUIRE_TIMEOUT_SECONDS = 300.0


class RateLimitProfile(str, Enum):
    """Rate limit profile for academic APIs."""

    ANONYMOUS = "anonymous"  # No credentials (default, most conservative)
    AUTHENTICATED = "authenticated"  # S2 with valid API key
    IDENTIFIED = "identified"  # OpenAlex with email (polite pool)


@dataclass
class ProviderRateLimitConfig:
    """Rate limit configuration for a single provider."""

    min_interval_seconds: float = 0.1  # Minimum time between requests
    max_parallel: int = 1  # Maximum concurrent requests
    profile: RateLimitProfile = RateLimitProfile.ANONYMOUS  # Currently active profile


@dataclass
class BackoffState:
    """Tracks backoff state for a provider (ADR-0013)."""

    effective_max_parallel: int = 1  # Current effective limit (may be < config max)
    config_max_parallel: int = 1  # Original config limit (upper bound)
    last_429_time: float = 0.0  # Timestamp of last 429 error
    last_recovery_attempt: float = 0.0  # Timestamp of last recovery attempt
    backoff_active: bool = False  # Whether backoff is currently active
    consecutive_429_count: int = 0  # Count of consecutive 429 errors


@dataclass
class ProviderState:
    """Complete state for a provider including profile and backoff."""

    profile: RateLimitProfile = RateLimitProfile.ANONYMOUS
    profile_downgraded: bool = False  # True if downgraded from authenticated/identified
    downgrade_logged: bool = False  # To ensure WARNING is logged only once
    startup_warning_logged: bool = False  # For initial missing-credentials warning


class AcademicAPIRateLimiter:
    """Global rate limiter for academic APIs with profile-based rate limits.

    Enforces per-provider QPS limits across all worker instances.
    Uses asyncio.Lock for QPS enforcement and asyncio.Semaphore for concurrency.
    Implements auto-backoff on 429 errors (ADR-0013).

    Profile Selection:
    - Semantic Scholar: authenticated (API key) or anonymous
    - OpenAlex: identified (email for polite pool) or anonymous

    Example:
        limiter = get_academic_rate_limiter()
        await limiter.acquire("semantic_scholar")
        try:
            result = await api_call()
            limiter.report_success("semantic_scholar")  # Optional: helps recovery
        except RateLimitError:
            limiter.report_429("semantic_scholar")  # Triggers backoff
            raise
        finally:
            limiter.release("semantic_scholar")
    """

    def __init__(self) -> None:
        """Initialize rate limiter with empty provider tracking."""
        # Per-provider locks for QPS enforcement
        self._qps_locks: dict[str, asyncio.Lock] = {}
        # Per-provider semaphores for concurrency enforcement
        # Note: Semaphore is created with config max_parallel; backoff uses additional tracking
        self._concurrency_semaphores: dict[str, asyncio.Semaphore] = {}
        # Last request timestamp per provider
        self._last_request: dict[str, float] = {}
        # Cached config per provider
        self._configs: dict[str, ProviderRateLimitConfig] = {}
        # Initialization lock
        self._init_lock = asyncio.Lock()
        # Backoff state per provider (ADR-0013)
        self._backoff_states: dict[str, BackoffState] = {}
        # Active request count per provider (for backoff enforcement)
        self._active_counts: dict[str, int] = {}
        # Event to signal when a slot becomes available per provider
        self._slot_events: dict[str, asyncio.Event] = {}
        # Provider state (profile, downgrade status)
        self._provider_states: dict[str, ProviderState] = {}

    def _select_profile(self, provider: str, api_config: AcademicAPIConfig) -> RateLimitProfile:
        """Select the appropriate rate limit profile based on credentials.

        Args:
            provider: API provider name.
            api_config: API configuration from academic_apis.yaml.

        Returns:
            Selected RateLimitProfile.
        """
        # Check if already downgraded (stick with anonymous)
        state = self._provider_states.get(provider)
        if state and state.profile_downgraded:
            return RateLimitProfile.ANONYMOUS

        # Semantic Scholar: authenticated if API key is set
        if provider == "semantic_scholar":
            if api_config.api_key:
                return RateLimitProfile.AUTHENTICATED
            return RateLimitProfile.ANONYMOUS

        # OpenAlex: identified if email is set
        if provider == "openalex":
            if api_config.email:
                return RateLimitProfile.IDENTIFIED
            return RateLimitProfile.ANONYMOUS

        # NCBI: authenticated if API key is set
        if provider == "ncbi":
            if api_config.api_key:
                return RateLimitProfile.AUTHENTICATED
            return RateLimitProfile.ANONYMOUS

        # Unknown providers default to anonymous
        return RateLimitProfile.ANONYMOUS

    def _get_provider_config(self, provider: str) -> ProviderRateLimitConfig:
        """Get rate limit configuration for a provider.

        Loads from config/academic_apis.yaml if not cached.
        Selects the appropriate profile based on credentials.

        Args:
            provider: API provider name (e.g., "semantic_scholar", "openalex")

        Returns:
            ProviderRateLimitConfig with rate limit settings.
        """
        if provider in self._configs:
            return self._configs[provider]

        # Load from config
        try:
            from src.utils.config import get_academic_apis_config

            config: AcademicAPIsConfig = get_academic_apis_config()
            api_config: AcademicAPIConfig = config.get_api_config(provider)

            # Initialize provider state
            if provider not in self._provider_states:
                self._provider_states[provider] = ProviderState()

            # Select profile based on credentials
            profile = self._select_profile(provider, api_config)
            self._provider_states[provider].profile = profile

            # Get rate limit from selected profile
            profiles = api_config.rate_limit_profiles
            if profiles:
                if profile == RateLimitProfile.AUTHENTICATED and profiles.authenticated:
                    rate_limit = profiles.authenticated
                elif profile == RateLimitProfile.IDENTIFIED and profiles.identified:
                    rate_limit = profiles.identified
                else:
                    rate_limit = profiles.anonymous

                provider_config = ProviderRateLimitConfig(
                    min_interval_seconds=rate_limit.min_interval_seconds,
                    max_parallel=rate_limit.max_parallel,
                    profile=profile,
                )
            else:
                # No profiles configured, use defaults
                provider_config = ProviderRateLimitConfig(profile=profile)

            self._configs[provider] = provider_config

            # Log profile selection
            logger.info(
                "Rate limiter profile selected",
                provider=provider,
                profile=profile.value,
                min_interval=provider_config.min_interval_seconds,
                max_parallel=provider_config.max_parallel,
            )

            # Log warning if using anonymous profile due to missing credentials
            self._log_missing_credentials_warning(provider, api_config, profile)

            return provider_config

        except Exception as e:
            logger.warning(
                "Failed to load rate limit config, using defaults",
                provider=provider,
                error=str(e),
            )
            default_config = ProviderRateLimitConfig()
            self._configs[provider] = default_config
            return default_config

    def _log_missing_credentials_warning(
        self, provider: str, api_config: AcademicAPIConfig, profile: RateLimitProfile
    ) -> None:
        """Log WARNING if credentials are missing (once per provider).

        Args:
            provider: API provider name.
            api_config: API configuration.
            profile: Selected profile.
        """
        state = self._provider_states.get(provider)
        if not state or state.startup_warning_logged:
            return

        if provider == "semantic_scholar" and profile == RateLimitProfile.ANONYMOUS:
            if not api_config.api_key:
                logger.warning(
                    "Semantic Scholar API key not configured - using conservative anonymous rate limits. "
                    "Set LYRA_ACADEMIC_APIS__APIS__SEMANTIC_SCHOLAR__API_KEY in .env for better performance. "
                    "Get free API key at: https://www.semanticscholar.org/product/api"
                )
            state.startup_warning_logged = True

        elif provider == "openalex" and profile == RateLimitProfile.ANONYMOUS:
            if not api_config.email:
                logger.warning(
                    "OpenAlex email not configured - using conservative anonymous rate limits. "
                    "Set LYRA_ACADEMIC_APIS__APIS__OPENALEX__EMAIL in .env for polite pool access."
                )
            state.startup_warning_logged = True

    async def _ensure_provider_initialized(self, provider: str) -> None:
        """Ensure locks and semaphores are initialized for a provider.

        Args:
            provider: API provider name.
        """
        if provider in self._qps_locks:
            return

        async with self._init_lock:
            # Double-check after acquiring lock
            if provider in self._qps_locks:
                return

            config = self._get_provider_config(provider)
            self._qps_locks[provider] = asyncio.Lock()
            self._concurrency_semaphores[provider] = asyncio.Semaphore(config.max_parallel)
            self._active_counts[provider] = 0
            # Event to signal slot availability
            self._slot_events[provider] = asyncio.Event()
            self._slot_events[provider].set()  # Initially available
            # Initialize backoff state (ADR-0013)
            self._backoff_states[provider] = BackoffState(
                effective_max_parallel=config.max_parallel,
                config_max_parallel=config.max_parallel,
            )
            logger.debug(
                "Initialized rate limiter for provider",
                provider=provider,
                profile=config.profile.value,
                max_parallel=config.max_parallel,
            )

    async def acquire(self, provider: str, timeout: float | None = None) -> None:
        """Acquire rate limit slot for a provider.

        Blocks until:
        1. A concurrency slot is available (respects effective_max_parallel with backoff)
        2. Minimum interval since last request has passed (QPS)

        Args:
            provider: API provider name (e.g., "semantic_scholar", "openalex")
            timeout: Maximum time to wait for a slot (seconds).
                If None, uses DEFAULT_SLOT_ACQUIRE_TIMEOUT_SECONDS (30s).
                This is intentionally shorter than pipeline timeout to allow
                fallback to other sources when an API is rate-limited.
        """
        await self._ensure_provider_initialized(provider)

        # Use short default timeout to avoid blocking pipeline (P0 fix)
        # Previous behavior used search_timeout_seconds (300s), which caused
        # SERP results to never be fetched when Academic API was rate-limited.
        if timeout is None:
            timeout = DEFAULT_SLOT_ACQUIRE_TIMEOUT_SECONDS

        # Check for recovery before acquiring (ADR-0013)
        await self._maybe_recover(provider)

        # 1. Acquire concurrency slot (may block if effective_max_parallel reached)
        start_time = time.time()
        poll_interval = 0.1  # Check every 100ms

        while True:
            backoff = self._backoff_states[provider]
            if self._active_counts[provider] < backoff.effective_max_parallel:
                self._active_counts[provider] += 1
                break

            # Check timeout
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                raise TimeoutError(
                    f"Failed to acquire rate limit slot within {timeout}s "
                    f"(provider={provider}, backoff: effective_max_parallel={backoff.effective_max_parallel})"
                )

            logger.debug(
                "Backoff limiting: waiting for slot",
                provider=provider,
                active=self._active_counts[provider],
                effective_max=backoff.effective_max_parallel,
            )

            # Wait for slot to become available or timeout
            event = self._slot_events[provider]
            event.clear()
            try:
                await asyncio.wait_for(
                    event.wait(),
                    timeout=min(poll_interval, timeout - elapsed),
                )
            except TimeoutError:
                # Continue polling
                pass

        # 2. Enforce QPS limit
        config = self._configs[provider]
        async with self._qps_locks[provider]:
            last = self._last_request.get(provider, 0)
            elapsed = time.time() - last
            wait_time = config.min_interval_seconds - elapsed

            if wait_time > 0:
                logger.debug(
                    "Rate limiting: waiting",
                    provider=provider,
                    wait_seconds=wait_time,
                )
                await asyncio.sleep(wait_time)

            self._last_request[provider] = time.time()

    def release(self, provider: str) -> None:
        """Release rate limit slot for a provider.

        Must be called after acquire() completes, typically in a finally block.

        Args:
            provider: API provider name.
        """
        if provider not in self._slot_events:
            return

        if self._active_counts.get(provider, 0) > 0:
            self._active_counts[provider] -= 1

        # Signal that a slot is available
        self._slot_events[provider].set()

    async def __aenter__(self) -> AcademicAPIRateLimiter:
        """Context manager entry (no-op, use acquire/release directly)."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Context manager exit (no-op)."""
        pass

    async def report_429(self, provider: str) -> None:
        """Report a 429 rate limit error for a provider.

        Triggers backoff: reduces effective_max_parallel (ADR-0013).

        Args:
            provider: API provider name.
        """
        if provider not in self._backoff_states:
            return

        # Load backoff config from academic_apis.yaml (centralized)
        from src.utils.config import get_academic_apis_config

        config = get_academic_apis_config()
        decrease_step = config.retry_policy.auto_backoff.decrease_step

        backoff = self._backoff_states[provider]
        now = time.time()

        # Reduce effective_max_parallel (floor at 1)
        new_max = max(1, backoff.effective_max_parallel - decrease_step)

        if new_max < backoff.effective_max_parallel:
            backoff.effective_max_parallel = new_max
            backoff.last_429_time = now
            backoff.backoff_active = True
            backoff.consecutive_429_count += 1

            logger.warning(
                "Backoff triggered: reducing effective_max_parallel",
                provider=provider,
                new_effective_max=new_max,
                config_max=backoff.config_max_parallel,
                consecutive_429_count=backoff.consecutive_429_count,
            )

    def report_success(self, provider: str) -> None:
        """Report a successful request for a provider.

        Resets consecutive 429 count (helps with recovery logic).

        Args:
            provider: API provider name.
        """
        if provider not in self._backoff_states:
            return

        backoff = self._backoff_states[provider]
        backoff.consecutive_429_count = 0

    def downgrade_profile(self, provider: str) -> None:
        """Downgrade provider to anonymous profile after 401/403 error.

        Called by API clients when credentials are invalidated.
        This affects the rate limit for the remainder of the process lifetime.

        Args:
            provider: API provider name.
        """
        if provider not in self._provider_states:
            self._provider_states[provider] = ProviderState()

        state = self._provider_states[provider]
        if state.profile_downgraded:
            return  # Already downgraded

        old_profile = state.profile
        state.profile = RateLimitProfile.ANONYMOUS
        state.profile_downgraded = True

        # Clear cached config to force reload with anonymous profile
        if provider in self._configs:
            del self._configs[provider]

        # Log warning (once)
        if not state.downgrade_logged:
            logger.warning(
                "API credentials invalidated - downgrading to anonymous rate limits",
                provider=provider,
                old_profile=old_profile.value,
                new_profile=RateLimitProfile.ANONYMOUS.value,
            )
            state.downgrade_logged = True

        # Re-initialize with new config if already initialized
        if provider in self._qps_locks:
            new_config = self._get_provider_config(provider)
            # Update backoff state with new config max
            if provider in self._backoff_states:
                backoff = self._backoff_states[provider]
                backoff.config_max_parallel = new_config.max_parallel
                # Also reduce effective if it exceeds new max
                if backoff.effective_max_parallel > new_config.max_parallel:
                    backoff.effective_max_parallel = new_config.max_parallel

    async def _maybe_recover(self, provider: str) -> None:
        """Attempt to recover from backoff if stable period has passed.

        Called before each acquire to check if we can increase effective_max_parallel.

        Args:
            provider: API provider name.
        """
        if provider not in self._backoff_states:
            return

        backoff = self._backoff_states[provider]
        if not backoff.backoff_active:
            return

        # Load recovery config from academic_apis.yaml (centralized)
        from src.utils.config import get_academic_apis_config

        config = get_academic_apis_config()
        recovery_stable_seconds = config.retry_policy.auto_backoff.recovery_stable_seconds

        now = time.time()
        time_since_last_429 = now - backoff.last_429_time
        time_since_last_recovery = now - backoff.last_recovery_attempt

        # Only attempt recovery if:
        # 1. Enough time has passed since last 429
        # 2. Enough time has passed since last recovery attempt
        if (
            time_since_last_429 >= recovery_stable_seconds
            and time_since_last_recovery >= recovery_stable_seconds
        ):
            backoff.last_recovery_attempt = now

            # Increase effective_max_parallel by 1 (up to config max)
            if backoff.effective_max_parallel < backoff.config_max_parallel:
                backoff.effective_max_parallel += 1

                logger.info(
                    "Backoff recovery: increasing effective_max_parallel",
                    provider=provider,
                    new_effective_max=backoff.effective_max_parallel,
                    config_max=backoff.config_max_parallel,
                )

                # Signal that a slot may be available
                event = self._slot_events.get(provider)
                if event:
                    event.set()

            # If we've recovered to config max, disable backoff
            if backoff.effective_max_parallel >= backoff.config_max_parallel:
                backoff.backoff_active = False
                logger.info(
                    "Backoff fully recovered",
                    provider=provider,
                    effective_max=backoff.effective_max_parallel,
                )

    def get_stats(self, provider: str) -> dict[str, float | int | bool | str]:
        """Get rate limiter statistics for a provider.

        Args:
            provider: API provider name.

        Returns:
            Dict with last_request timestamp, config values, profile, and backoff state.
        """
        config = self._get_provider_config(provider)
        backoff = self._backoff_states.get(provider)
        state = self._provider_states.get(provider)

        stats: dict[str, float | int | bool | str] = {
            "last_request": self._last_request.get(provider, 0),
            "min_interval_seconds": config.min_interval_seconds,
            "max_parallel": config.max_parallel,
            "active_count": self._active_counts.get(provider, 0),
            "profile": config.profile.value,
        }

        # Add provider state
        if state:
            stats["profile_downgraded"] = state.profile_downgraded

        # Add backoff state (ADR-0013)
        if backoff:
            stats["effective_max_parallel"] = backoff.effective_max_parallel
            stats["backoff_active"] = backoff.backoff_active
            stats["consecutive_429_count"] = backoff.consecutive_429_count
            stats["last_429_time"] = backoff.last_429_time
        else:
            stats["effective_max_parallel"] = config.max_parallel
            stats["backoff_active"] = False
            stats["consecutive_429_count"] = 0
            stats["last_429_time"] = 0.0

        return stats

    def get_current_profile(self, provider: str) -> RateLimitProfile:
        """Get the current rate limit profile for a provider.

        Args:
            provider: API provider name.

        Returns:
            Current RateLimitProfile.
        """
        state = self._provider_states.get(provider)
        if state:
            return state.profile
        return RateLimitProfile.ANONYMOUS


# Global instance
_rate_limiter: AcademicAPIRateLimiter | None = None


def get_academic_rate_limiter() -> AcademicAPIRateLimiter:
    """Get or create the global academic API rate limiter.

    Returns:
        Global AcademicAPIRateLimiter instance.
    """
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = AcademicAPIRateLimiter()
    return _rate_limiter


def reset_academic_rate_limiter() -> None:
    """Reset the global rate limiter (for testing only)."""
    global _rate_limiter
    _rate_limiter = None
