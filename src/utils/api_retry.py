"""
Retry utilities for official public APIs (§3.1.3, §4.3.5).

IMPORTANT: This module is ONLY for APIs listed in §3.1.3/§5.1.1:
- e-Stat API, 法令API（e-Gov）, 国会会議録API, gBizINFO API, EDINET API
- OpenAlex API, Semantic Scholar API, Crossref API, Unpaywall API
- Wikidata API, DBpedia SPARQL

Per §3.1.3: "これらは公式APIであり、検索エンジンのようなbot検知問題はない"
Per §4.3.5: "ネットワーク/APIリトライ（トランジェントエラー向け）"

DO NOT use for:
- Search engines (use escalation path in fetcher.py per §4.3.5)
- Browser fetching (use InterventionQueue for CAPTCHA per §3.6.1)
- General web scraping
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from src.utils.backoff import BackoffConfig, calculate_backoff
from src.utils.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class APIRetryError(Exception):
    """Raised when all retry attempts are exhausted.

    Attributes:
        message: Error description
        attempts: Number of attempts made
        last_error: The last exception that caused failure
        last_status: The last HTTP status code (if applicable)
    """

    def __init__(
        self,
        message: str,
        attempts: int,
        last_error: Exception | None = None,
        last_status: int | None = None,
    ):
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error
        self.last_status = last_status


class HTTPStatusError(Exception):
    """Raised when HTTP response has an error status code.

    Attributes:
        status: HTTP status code
        message: Error description
    """

    def __init__(self, status: int, message: str = ""):
        super().__init__(message or f"HTTP {status}")
        self.status = status


@dataclass
class APIRetryPolicy:
    """Retry policy for official public APIs per §3.1.3 and §4.3.5.

    Safe to use because target APIs:
    - Are official government/academic APIs (§3.1.3)
    - Have no bot detection mechanisms
    - Use explicit rate limiting (429) handled with backoff

    Per §4.3.5: "検索エンジン/ブラウザ取得では使用禁止"

    Attributes:
        max_retries: Maximum retry attempts (default: 3 per §7)
        backoff: Backoff configuration for delay calculation
        retryable_exceptions: Exception types that are safe to retry
        retryable_status_codes: HTTP status codes that are safe to retry
        non_retryable_status_codes: HTTP status codes that should never be retried

    Example:
        >>> policy = APIRetryPolicy(max_retries=5)
        >>> policy.should_retry_exception(ConnectionError())
        True
        >>> policy.should_retry_status(429)
        True
        >>> policy.should_retry_status(404)
        False
    """

    max_retries: int = 3
    backoff: BackoffConfig = field(default_factory=BackoffConfig)

    # Network errors - always safe to retry
    # These are transient and not related to bot detection
    retryable_exceptions: tuple[type[Exception], ...] = (
        ConnectionError,
        TimeoutError,
        OSError,
    )

    # API rate limiting / transient server errors
    # 429: Rate limited (safe for official APIs)
    # 500: Internal server error (transient)
    # 502: Bad gateway (transient)
    # 503: Service unavailable (transient)
    # 504: Gateway timeout (transient)
    retryable_status_codes: frozenset[int] = field(
        default_factory=lambda: frozenset({429, 500, 502, 503, 504})
    )

    # Never retry these (client errors, not transient)
    # 400: Bad request (client error)
    # 401: Unauthorized (need auth)
    # 403: Forbidden (for APIs, usually auth issue, not bot detection)
    # 404: Not found (resource doesn't exist)
    # 410: Gone (resource permanently removed)
    non_retryable_status_codes: frozenset[int] = field(
        default_factory=lambda: frozenset({400, 401, 403, 404, 410})
    )

    def __post_init__(self) -> None:
        """Validate policy configuration."""
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")

        # Ensure no overlap between retryable and non-retryable
        overlap = self.retryable_status_codes & self.non_retryable_status_codes
        if overlap:
            raise ValueError(
                f"Status codes cannot be both retryable and non-retryable: {overlap}"
            )

    def should_retry_exception(self, exc: Exception) -> bool:
        """Check if exception is retryable.

        Args:
            exc: The exception to check

        Returns:
            True if the exception type is in retryable_exceptions
        """
        return isinstance(exc, self.retryable_exceptions)

    def should_retry_status(self, status: int) -> bool:
        """Check if HTTP status code is retryable.

        Args:
            status: HTTP status code

        Returns:
            True if status is retryable, False if non-retryable or unknown
        """
        if status in self.non_retryable_status_codes:
            return False
        return status in self.retryable_status_codes


async def retry_api_call[T](
    func: Callable[..., Awaitable[T]],
    *args: Any,
    policy: APIRetryPolicy | None = None,
    operation_name: str | None = None,
    **kwargs: Any,
) -> T:
    """Execute async function with retry logic for public APIs.

    Per §4.3.5: This function implements "ネットワーク/APIリトライ"
    for official public APIs listed in §3.1.3.

    The function will retry on:
    - Network errors (ConnectionError, TimeoutError, OSError)
    - HTTP status codes in policy.retryable_status_codes (429, 5xx)

    The function will NOT retry on:
    - HTTP status codes in policy.non_retryable_status_codes (400, 401, 403, 404, 410)
    - Other exceptions not in policy.retryable_exceptions

    Args:
        func: Async function to call
        *args: Positional arguments for func
        policy: Retry policy (default: APIRetryPolicy())
        operation_name: Name for logging (default: func.__name__)
        **kwargs: Keyword arguments for func

    Returns:
        Result from func

    Raises:
        APIRetryError: When all retries exhausted
        Exception: When a non-retryable error occurs

    Example:
        >>> async def fetch_estat(endpoint: str) -> dict:
        ...     response = await client.get(endpoint)
        ...     if response.status >= 400:
        ...         raise HTTPStatusError(response.status)
        ...     return response.json()
        >>>
        >>> result = await retry_api_call(
        ...     fetch_estat,
        ...     "/api/v1/stats",
        ...     policy=APIRetryPolicy(max_retries=5),
        ... )
    """
    if policy is None:
        policy = APIRetryPolicy()

    op_name = operation_name or getattr(func, "__name__", "api_call")
    last_error: Exception | None = None
    last_status: int | None = None

    for attempt in range(policy.max_retries + 1):
        try:
            return await func(*args, **kwargs)

        except HTTPStatusError as e:
            last_error = e
            last_status = e.status

            # Check if status is retryable
            if not policy.should_retry_status(e.status):
                logger.warning(
                    "Non-retryable HTTP status",
                    operation=op_name,
                    status=e.status,
                    attempt=attempt + 1,
                )
                raise

            # Check if more retries available
            if attempt >= policy.max_retries:
                break

            # Calculate delay and wait
            delay = calculate_backoff(attempt, policy.backoff)
            logger.info(
                "Retrying after HTTP error",
                operation=op_name,
                status=e.status,
                attempt=attempt + 1,
                max_retries=policy.max_retries,
                delay_seconds=round(delay, 2),
            )
            await asyncio.sleep(delay)

        except Exception as e:
            last_error = e

            # Check if exception is retryable
            if not policy.should_retry_exception(e):
                logger.warning(
                    "Non-retryable exception",
                    operation=op_name,
                    error_type=type(e).__name__,
                    error=str(e),
                    attempt=attempt + 1,
                )
                raise

            # Check if more retries available
            if attempt >= policy.max_retries:
                break

            # Calculate delay and wait
            delay = calculate_backoff(attempt, policy.backoff)
            logger.info(
                "Retrying after exception",
                operation=op_name,
                error_type=type(e).__name__,
                attempt=attempt + 1,
                max_retries=policy.max_retries,
                delay_seconds=round(delay, 2),
            )
            await asyncio.sleep(delay)

    # All retries exhausted
    raise APIRetryError(
        f"{op_name} failed after {policy.max_retries + 1} attempts",
        attempts=policy.max_retries + 1,
        last_error=last_error,
        last_status=last_status,
    )


def with_api_retry(
    policy: APIRetryPolicy | None = None,
    operation_name: str | None = None,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator for adding retry logic to async API functions.

    Per §4.3.5: Use only for official public APIs (§3.1.3).

    Args:
        policy: Retry policy (default: APIRetryPolicy())
        operation_name: Name for logging (default: function name)

    Returns:
        Decorator function

    Example:
        >>> @with_api_retry(APIRetryPolicy(max_retries=5))
        ... async def fetch_openalex_paper(doi: str) -> dict:
        ...     response = await client.get(f"/works/{doi}")
        ...     if response.status >= 400:
        ...         raise HTTPStatusError(response.status)
        ...     return response.json()
    """
    def decorator(
        func: Callable[..., Awaitable[T]],
    ) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await retry_api_call(
                func,
                *args,
                policy=policy,
                operation_name=operation_name or func.__name__,
                **kwargs,
            )
        return wrapper
    return decorator


# Pre-configured policies for common API types

#: Policy for Japanese government APIs (e-Stat, 法令API, etc.)
#: These tend to have stricter rate limits
JAPAN_GOV_API_POLICY = APIRetryPolicy(
    max_retries=3,
    backoff=BackoffConfig(base_delay=2.0, max_delay=60.0),
)

#: Policy for academic APIs (OpenAlex, Semantic Scholar, etc.)
#: Generally more lenient with rate limits
ACADEMIC_API_POLICY = APIRetryPolicy(
    max_retries=5,
    backoff=BackoffConfig(base_delay=1.0, max_delay=120.0),
)

#: Policy for entity APIs (Wikidata, DBpedia)
#: Can handle more aggressive retry
ENTITY_API_POLICY = APIRetryPolicy(
    max_retries=3,
    backoff=BackoffConfig(base_delay=0.5, max_delay=30.0),
)

