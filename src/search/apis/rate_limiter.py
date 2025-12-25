"""
Global rate limiter for academic APIs.

Enforces per-provider QPS limits across all worker instances.
Per ADR-0013: Worker Resource Contention Control.

Design:
- Each provider (semantic_scholar, openalex) has its own rate limit settings
- Limits are loaded from config/academic_apis.yaml
- Both QPS (min_interval) and concurrency (max_parallel) are enforced
- Thread-safe for asyncio concurrent access
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.config import AcademicAPIConfig

logger = get_logger(__name__)


@dataclass
class ProviderRateLimitConfig:
    """Rate limit configuration for a single provider."""

    min_interval_seconds: float = 0.1  # Minimum time between requests
    max_parallel: int = 1  # Maximum concurrent requests


class AcademicAPIRateLimiter:
    """Global rate limiter for academic APIs.

    Enforces per-provider QPS limits across all worker instances.
    Uses asyncio.Lock for QPS enforcement and asyncio.Semaphore for concurrency.

    Example:
        limiter = get_academic_rate_limiter()
        await limiter.acquire("semantic_scholar")
        try:
            result = await api_call()
        finally:
            limiter.release("semantic_scholar")
    """

    def __init__(self) -> None:
        """Initialize rate limiter with empty provider tracking."""
        # Per-provider locks for QPS enforcement
        self._qps_locks: dict[str, asyncio.Lock] = {}
        # Per-provider semaphores for concurrency enforcement
        self._concurrency_semaphores: dict[str, asyncio.Semaphore] = {}
        # Last request timestamp per provider
        self._last_request: dict[str, float] = {}
        # Cached config per provider
        self._configs: dict[str, ProviderRateLimitConfig] = {}
        # Initialization lock
        self._init_lock = asyncio.Lock()

    def _get_provider_config(self, provider: str) -> ProviderRateLimitConfig:
        """Get rate limit configuration for a provider.

        Loads from config/academic_apis.yaml if not cached.

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

            config = get_academic_apis_config()
            api_config: AcademicAPIConfig = config.get_api_config(provider)

            # Extract rate limit settings
            rate_limit = api_config.rate_limit
            if rate_limit:
                min_interval = getattr(rate_limit, "min_interval_seconds", None)
                max_parallel = getattr(rate_limit, "max_parallel", None)

                # If min_interval not explicitly set, derive from requests/interval
                if min_interval is None:
                    requests_per_interval = getattr(rate_limit, "requests_per_interval", None)
                    interval_seconds = getattr(rate_limit, "interval_seconds", None)
                    if requests_per_interval and interval_seconds:
                        min_interval = interval_seconds / requests_per_interval
                    else:
                        min_interval = 0.1  # Default: 10 req/s

                provider_config = ProviderRateLimitConfig(
                    min_interval_seconds=min_interval or 0.1,
                    max_parallel=max_parallel or 1,
                )
            else:
                provider_config = ProviderRateLimitConfig()

            self._configs[provider] = provider_config
            logger.debug(
                "Loaded rate limit config",
                provider=provider,
                min_interval=provider_config.min_interval_seconds,
                max_parallel=provider_config.max_parallel,
            )
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
            logger.debug(
                "Initialized rate limiter for provider",
                provider=provider,
                max_parallel=config.max_parallel,
            )

    async def acquire(self, provider: str) -> None:
        """Acquire rate limit slot for a provider.

        Blocks until:
        1. A concurrency slot is available (max_parallel)
        2. Minimum interval since last request has passed (QPS)

        Args:
            provider: API provider name (e.g., "semantic_scholar", "openalex")
        """
        await self._ensure_provider_initialized(provider)

        # 1. Acquire concurrency slot (may block if max_parallel reached)
        semaphore = self._concurrency_semaphores[provider]
        await semaphore.acquire()

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
        if provider in self._concurrency_semaphores:
            self._concurrency_semaphores[provider].release()

    async def __aenter__(self) -> AcademicAPIRateLimiter:
        """Context manager entry (no-op, use acquire/release directly)."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Context manager exit (no-op)."""
        pass

    def get_stats(self, provider: str) -> dict[str, float | int]:
        """Get rate limiter statistics for a provider.

        Args:
            provider: API provider name.

        Returns:
            Dict with last_request timestamp and config values.
        """
        config = self._get_provider_config(provider)
        return {
            "last_request": self._last_request.get(provider, 0),
            "min_interval_seconds": config.min_interval_seconds,
            "max_parallel": config.max_parallel,
        }


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
