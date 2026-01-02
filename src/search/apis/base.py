"""
Base class for academic API clients.

Per ADR-0013: Worker Resource Contention Control, all academic API
clients use a global rate limiter to enforce per-provider QPS limits
across all worker instances.

Per E2E fix: Retry-aware slot release pattern - release slot before
backoff wait to allow other workers to proceed.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

import httpx

from src.utils.logging import get_logger
from src.utils.schemas import AcademicSearchResult, Paper

logger = get_logger(__name__)


class BaseAcademicClient(ABC):
    """Base class for academic API clients.

    All subclasses should use the rate-limited search method which
    automatically enforces global QPS and concurrency limits per ADR-0013.
    """

    def __init__(
        self,
        name: str,
        base_url: str | None = None,
        timeout: float | None = None,
        headers: dict[str, str] | None = None,
    ):
        """Initialize client.

        Args:
            name: Client name (used for rate limiting key)
            base_url: Base URL for API (if None, will try to load from config)
            timeout: Timeout in seconds (if None, will try to load from config)
            headers: HTTP headers (if None, will use default)
        """
        self.name = name
        self._session: httpx.AsyncClient | None = None

        # Load configuration if not provided
        if base_url is None or timeout is None:
            try:
                from src.utils.config import get_academic_apis_config

                config = get_academic_apis_config()
                api_config = config.get_api_config(name)

                if base_url is None:
                    base_url = api_config.base_url
                if timeout is None:
                    timeout = float(api_config.timeout_seconds)
                if headers is None and api_config.headers:
                    headers = api_config.headers.copy()
            except Exception as e:
                logger.debug("Failed to load config for academic API", api=name, error=str(e))
                if base_url is None:
                    base_url = None  # Will be set by subclass
                if timeout is None:
                    timeout = 30.0

        self.base_url = base_url
        self.timeout = timeout or 30.0

        # Default headers
        default_headers = {"User-Agent": "Lyra/1.0 (research tool; mailto:lyra@example.com)"}
        if headers:
            default_headers.update(headers)
        self.default_headers = default_headers

    async def _get_session(self) -> httpx.AsyncClient:
        """Get HTTP session (lazy initialization)."""
        if self._session is None:
            self._session = httpx.AsyncClient(timeout=self.timeout, headers=self.default_headers)
        return self._session

    async def search(self, query: str, limit: int = 10) -> AcademicSearchResult:
        """Search for papers with global rate limiting and retry-aware slot release.

        This method enforces per-provider QPS and concurrency limits
        per ADR-0013: Worker Resource Contention Control.

        Key improvement (E2E fix): Releases slot before backoff wait to allow
        other workers to proceed, preventing 60s timeout deadlocks when multiple
        workers compete for max_parallel=1 APIs like Semantic Scholar.

        Args:
            query: Search query
            limit: Maximum number of results

        Returns:
            AcademicSearchResult
        """
        from src.search.apis.rate_limiter import get_academic_rate_limiter
        from src.utils.api_retry import ACADEMIC_API_POLICY
        from src.utils.backoff import calculate_backoff

        limiter = get_academic_rate_limiter()
        max_retries = ACADEMIC_API_POLICY.max_retries
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            await limiter.acquire(self.name)
            retry_delay: float | None = None
            try:
                result = await self._search_impl(query, limit)
                limiter.report_success(self.name)
                return result
            except Exception as e:
                last_error = e

                # Check if retryable HTTP error
                status_code: int | None = None
                if isinstance(e, httpx.HTTPStatusError):
                    status_code = e.response.status_code
                elif hasattr(e, "response") and hasattr(e.response, "status_code"):
                    status_code = e.response.status_code

                # Report 429 to trigger adaptive backoff
                if status_code == 429:
                    await limiter.report_429(self.name)

                # Check if retryable (429 or 5xx)
                is_retryable = (
                    status_code in ACADEMIC_API_POLICY.retryable_status_codes
                    if status_code
                    else False
                )

                if not is_retryable or attempt >= max_retries:
                    # Not retryable or exhausted retries - re-raise
                    raise

                # Backoff wait (without holding slot - key improvement)
                retry_delay = calculate_backoff(attempt, ACADEMIC_API_POLICY.backoff)
                logger.info(
                    "Retrying search after releasing slot",
                    provider=self.name,
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    delay_seconds=round(retry_delay, 2),
                    status_code=status_code,
                )
            finally:
                # Always release slot (success or failure) to avoid deadlocks where
                # a provider's effective_max_parallel is exhausted permanently.
                limiter.release(self.name)

            # Backoff wait (outside the acquired slot)
            if retry_delay is not None:
                await asyncio.sleep(retry_delay)

        # Should not reach here, but handle edge case
        raise last_error or RuntimeError(f"Search failed after {max_retries + 1} attempts")

    @abstractmethod
    async def _search_impl(self, query: str, limit: int = 10) -> AcademicSearchResult:
        """Actual search implementation (subclass).

        Subclasses should implement this method instead of search().
        Rate limiting is handled by the base class search() method.

        Args:
            query: Search query
            limit: Maximum number of results

        Returns:
            AcademicSearchResult
        """
        pass

    @abstractmethod
    async def get_paper(self, paper_id: str) -> Paper | None:
        """Get paper metadata.

        Args:
            paper_id: Paper ID (API-specific format)

        Returns:
            Paper object or None
        """
        pass

    @abstractmethod
    async def get_references(self, paper_id: str) -> list[Paper]:
        """Get references (papers cited by this paper).

        Args:
            paper_id: Paper ID

        Returns:
            List of Paper objects
        """
        pass

    @abstractmethod
    async def get_citations(self, paper_id: str) -> list[Paper]:
        """Get citations (papers that cite this paper).

        Args:
            paper_id: Paper ID

        Returns:
            List of Paper objects
        """
        pass

    async def close(self) -> None:
        """Close the session."""
        if self._session:
            await self._session.aclose()
            self._session = None
            logger.debug("Academic API client closed", client=self.name)
