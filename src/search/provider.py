"""
Search provider abstraction layer for Lyra.

Provides a unified interface for search providers, enabling easy switching
between different search backends (BrowserSearchProvider is the default).
"""

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from src.utils.logging import get_logger

logger = get_logger(__name__)


# ============================================================================
# Pydantic Models for Search Results
# ============================================================================


class SourceTag(str, Enum):
    """Classification of source type."""

    ACADEMIC = "academic"
    GOVERNMENT = "government"
    STANDARDS = "standards"
    KNOWLEDGE = "knowledge"
    NEWS = "news"
    TECHNICAL = "technical"
    BLOG = "blog"
    UNKNOWN = "unknown"


class SearchResult(BaseModel):
    """
    Normalized search result from any provider.

    Standard SERP (Search Engine Results Page) schema with fields:
    - title: Result title
    - url: Result URL
    - snippet: Text preview
    - date: Publication/crawl date
    - engine: Search engine name
    - rank: Position in results
    - source_tag: Source classification (primary/secondary/tertiary)
    """

    model_config = ConfigDict(frozen=False, extra="forbid")

    title: str = Field(..., description="Result title")
    url: str = Field(..., description="Result URL")
    snippet: str = Field(..., description="Text snippet/content preview")
    engine: str = Field(..., description="Search engine that returned this result")
    rank: int = Field(..., ge=0, description="Rank position in search results")
    date: str | None = Field(default=None, description="Publication date if available")
    source_tag: SourceTag = Field(
        default=SourceTag.UNKNOWN, description="Classification of source type"
    )
    raw_data: dict[str, Any] | None = Field(
        default=None, description="Optional raw data from provider"
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "date": self.date,
            "engine": self.engine,
            "rank": self.rank,
            "source_tag": self.source_tag.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SearchResult":
        """Create from dictionary."""
        return cls(
            title=data.get("title", ""),
            url=data.get("url", ""),
            snippet=data.get("snippet", ""),
            date=data.get("date"),
            engine=data.get("engine", "unknown"),
            rank=data.get("rank", 0),
            source_tag=SourceTag(data.get("source_tag", "unknown")),
        )


class SearchResponse(BaseModel):
    """
    Response from a search provider.
    """

    model_config = ConfigDict(frozen=False)

    results: list[SearchResult] = Field(..., description="List of search results")
    query: str = Field(..., description="Original query")
    provider: str = Field(..., description="Provider name that returned this response")
    total_count: int = Field(default=0, ge=0, description="Total number of results")
    error: str | None = Field(default=None, description="Error message if search failed")
    elapsed_ms: float = Field(
        default=0.0, ge=0.0, description="Time taken for search in milliseconds"
    )
    connection_mode: str | None = Field(default=None, description="Browser connection mode used")
    # ADR-0007: CAPTCHA queue integration
    captcha_queued: bool = Field(
        default=False, description="True if CAPTCHA was queued for intervention"
    )
    queue_id: str | None = Field(
        default=None, description="Intervention queue ID if CAPTCHA was queued"
    )

    @property
    def ok(self) -> bool:
        """Check if search was successful."""
        return self.error is None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "results": [r.to_dict() for r in self.results],
            "query": self.query,
            "provider": self.provider,
            "total_count": self.total_count,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
            "ok": self.ok,
            "connection_mode": self.connection_mode,
        }
        # Only include CAPTCHA fields if relevant
        if self.captcha_queued:
            result["captcha_queued"] = self.captcha_queued
            result["queue_id"] = self.queue_id
        return result


class SearchOptions(BaseModel):
    """
    Options for search requests.

    Pagination fields:
    - serp_page: Current SERP page number (1-indexed)
    - serp_max_pages: Maximum SERP pages to fetch (pagination limit)

    ADR-0007 fields:
    - task_id: For CAPTCHA queue association
    - search_job_id: For auto-requeue on resolve_auth
    """

    model_config = ConfigDict(frozen=False, extra="forbid")

    engines: list[str] | None = Field(default=None, description="List of search engines to use")
    categories: list[str] | None = Field(default=None, description="Search categories")
    language: str = Field(default="ja", description="Search language code")
    time_range: str = Field(default="all", description="Time filter (all, day, week, month, year)")
    limit: int = Field(default=10, ge=1, le=100, description="Maximum number of results per page")
    serp_page: int = Field(default=1, ge=1, description="SERP page number (pagination)")
    serp_max_pages: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Maximum SERP pages to fetch for pagination",
    )
    # ADR-0007: CAPTCHA queue integration
    task_id: str | None = Field(default=None, description="Task ID for CAPTCHA queue association")
    search_job_id: str | None = Field(default=None, description="Search job ID for auto-requeue")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "engines": self.engines,
            "categories": self.categories,
            "language": self.language,
            "time_range": self.time_range,
            "limit": self.limit,
            "serp_page": self.serp_page,
            "serp_max_pages": self.serp_max_pages,
        }


# ============================================================================
# Health Status
# ============================================================================


class HealthState(str, Enum):
    """Provider health states."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class HealthStatus(BaseModel):
    """
    Health status of a search provider.
    """

    model_config = ConfigDict(frozen=False)

    state: HealthState = Field(..., description="Current health state")
    success_rate: float = Field(default=1.0, ge=0.0, le=1.0, description="Recent success rate")
    latency_ms: float = Field(default=0.0, ge=0.0, description="Average latency in milliseconds")
    last_check: datetime | None = Field(default=None, description="Last health check time")
    message: str | None = Field(default=None, description="Optional status message")
    details: dict[str, Any] = Field(default_factory=dict, description="Additional health details")

    @classmethod
    def healthy(cls, latency_ms: float = 0.0) -> "HealthStatus":
        """Create a healthy status."""
        return cls(
            state=HealthState.HEALTHY,
            success_rate=1.0,
            latency_ms=latency_ms,
            last_check=datetime.now(UTC),
        )

    @classmethod
    def degraded(cls, success_rate: float, message: str | None = None) -> "HealthStatus":
        """Create a degraded status."""
        return cls(
            state=HealthState.DEGRADED,
            success_rate=success_rate,
            message=message,
            last_check=datetime.now(UTC),
        )

    @classmethod
    def unhealthy(cls, message: str | None = None) -> "HealthStatus":
        """Create an unhealthy status."""
        return cls(
            state=HealthState.UNHEALTHY,
            success_rate=0.0,
            message=message,
            last_check=datetime.now(UTC),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "state": self.state.value,
            "success_rate": self.success_rate,
            "latency_ms": self.latency_ms,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "message": self.message,
            "details": self.details,
        }


# ============================================================================
# Search Provider Protocol
# ============================================================================


@runtime_checkable
class SearchProvider(Protocol):
    """
    Protocol for search providers.

    Defines the interface that all search providers must implement.
    Uses Python's Protocol for structural subtyping, allowing duck typing
    while maintaining type safety.

    Example implementation:
        class MyProvider:
            @property
            def name(self) -> str:
                return "my_provider"

            async def search(self, query: str, options: SearchOptions | None = None) -> SearchResponse:
                # Implementation
                ...

            async def get_health(self) -> HealthStatus:
                return HealthStatus.healthy()

            async def close(self) -> None:
                # Cleanup
                ...
    """

    @property
    def name(self) -> str:
        """Unique name of the provider."""
        ...

    async def search(
        self,
        query: str,
        options: SearchOptions | None = None,
    ) -> SearchResponse:
        """
        Execute a search query.

        Args:
            query: Search query text.
            options: Search options (engines, language, etc.).

        Returns:
            SearchResponse with results or error.
        """
        ...

    async def get_health(self) -> HealthStatus:
        """
        Get current health status.

        Returns:
            HealthStatus indicating provider health.
        """
        ...

    async def close(self) -> None:
        """
        Close and cleanup provider resources.

        Should be called when the provider is no longer needed.
        """
        ...


class BaseSearchProvider(ABC):
    """
    Abstract base class for search providers.

    Provides common functionality and enforces the interface contract.
    Subclasses should implement the abstract methods.
    """

    def __init__(self, provider_name: str):
        """
        Initialize base provider.

        Args:
            provider_name: Unique name for this provider.
        """
        self._name = provider_name
        self._is_closed = False

    @property
    def name(self) -> str:
        """Unique name of the provider."""
        return self._name

    @property
    def is_closed(self) -> bool:
        """Check if provider is closed."""
        return self._is_closed

    @abstractmethod
    async def search(
        self,
        query: str,
        options: SearchOptions | None = None,
    ) -> SearchResponse:
        """Execute a search query."""
        pass

    @abstractmethod
    async def get_health(self) -> HealthStatus:
        """Get current health status."""
        pass

    async def close(self) -> None:
        """Close and cleanup provider resources."""
        self._is_closed = True
        logger.debug("Search provider closed", provider=self._name)

    def _check_closed(self) -> None:
        """Raise error if provider is closed."""
        if self._is_closed:
            raise RuntimeError(f"Provider '{self._name}' is closed")


# ============================================================================
# Provider Registry
# ============================================================================


class SearchProviderRegistry:
    """
    Registry for search providers.

    Manages registration, retrieval, and lifecycle of search providers.
    Supports multiple providers with fallback selection.

    Example usage:
        registry = SearchProviderRegistry()
        registry.register(BrowserSearchProvider())

        # Get specific provider
        provider = registry.get("browser_search")

        # Get default provider
        provider = registry.get_default()

        # Search with fallback
        response = await registry.search_with_fallback(query)
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._providers: dict[str, SearchProvider] = {}
        self._default_name: str | None = None

    def register(
        self,
        provider: SearchProvider,
        set_default: bool = False,
    ) -> None:
        """
        Register a search provider.

        Args:
            provider: Provider instance to register.
            set_default: Whether to set as default provider.

        Raises:
            ValueError: If provider with same name already registered.
        """
        name = provider.name

        if name in self._providers:
            raise ValueError(f"Provider '{name}' already registered")

        self._providers[name] = provider

        if set_default or self._default_name is None:
            self._default_name = name

        logger.info(
            "Search provider registered",
            provider=name,
            is_default=set_default or self._default_name == name,
        )

    def unregister(self, name: str) -> SearchProvider | None:
        """
        Unregister a provider by name.

        Args:
            name: Provider name to unregister.

        Returns:
            The unregistered provider, or None if not found.
        """
        provider = self._providers.pop(name, None)

        if provider is not None:
            logger.info("Search provider unregistered", provider=name)

            # Update default if needed
            if self._default_name == name:
                self._default_name = next(iter(self._providers), None)

        return provider

    def get(self, name: str) -> SearchProvider | None:
        """
        Get a provider by name.

        Args:
            name: Provider name.

        Returns:
            Provider instance or None if not found.
        """
        return self._providers.get(name)

    def get_default(self) -> SearchProvider | None:
        """
        Get the default provider.

        Returns:
            Default provider or None if no providers registered.
        """
        if self._default_name is None:
            return None
        return self._providers.get(self._default_name)

    def set_default(self, name: str) -> None:
        """
        Set the default provider.

        Args:
            name: Provider name to set as default.

        Raises:
            ValueError: If provider not found.
        """
        if name not in self._providers:
            raise ValueError(f"Provider '{name}' not registered")

        self._default_name = name
        logger.info("Default search provider changed", provider=name)

    def list_providers(self) -> list[str]:
        """
        List all registered provider names.

        Returns:
            List of provider names.
        """
        return list(self._providers.keys())

    async def get_all_health(self) -> dict[str, HealthStatus]:
        """
        Get health status for all providers.

        Returns:
            Dict mapping provider names to health status.
        """
        health = {}
        for name, provider in self._providers.items():
            try:
                health[name] = await provider.get_health()
            except Exception as e:
                logger.error("Failed to get health", provider=name, error=str(e))
                health[name] = HealthStatus.unhealthy(str(e))
        return health

    async def search_with_fallback(
        self,
        query: str,
        options: SearchOptions | None = None,
        provider_order: list[str] | None = None,
    ) -> SearchResponse:
        """
        Search with automatic fallback to other providers on failure.

        Args:
            query: Search query.
            options: Search options.
            provider_order: Order of providers to try (default: default first, then others).

        Returns:
            SearchResponse from first successful provider.

        Raises:
            RuntimeError: If no providers available or all fail.
        """
        if not self._providers:
            raise RuntimeError("No search providers registered")

        # Determine provider order
        if provider_order is None:
            provider_order = []
            if self._default_name:
                provider_order.append(self._default_name)
            provider_order.extend(n for n in self._providers if n not in provider_order)

        errors = []

        for name in provider_order:
            provider = self._providers.get(name)
            if provider is None:
                continue

            try:
                # Check health first
                health = await provider.get_health()
                if health.state == HealthState.UNHEALTHY:
                    logger.debug(
                        "Skipping unhealthy provider",
                        provider=name,
                        message=health.message,
                    )
                    continue

                # Execute search
                response = await provider.search(query, options)

                if response.ok:
                    return response

                # Search returned error
                errors.append(f"{name}: {response.error}")
                logger.warning(
                    "Search provider returned error",
                    provider=name,
                    error=response.error,
                )

            except Exception as e:
                errors.append(f"{name}: {str(e)}")
                logger.error("Search provider failed", provider=name, error=str(e))

        # All providers failed
        error_msg = "; ".join(errors) if errors else "No providers available"
        return SearchResponse(
            results=[],
            query=query,
            provider="none",
            error=f"All providers failed: {error_msg}",
        )

    async def close_all(self) -> None:
        """Close all registered providers."""
        for name, provider in self._providers.items():
            try:
                await provider.close()
            except Exception as e:
                logger.error("Failed to close provider", provider=name, error=str(e))

        self._providers.clear()
        self._default_name = None
        logger.info("All search providers closed")


# ============================================================================
# Global Registry
# ============================================================================

_registry: SearchProviderRegistry | None = None


def get_registry() -> SearchProviderRegistry:
    """
    Get the global search provider registry.

    Returns:
        The global SearchProviderRegistry instance.
    """
    global _registry
    if _registry is None:
        _registry = SearchProviderRegistry()
    return _registry


async def cleanup_registry() -> None:
    """
    Cleanup the global registry.

    Closes all providers and resets the registry.
    """
    global _registry
    if _registry is not None:
        await _registry.close_all()
        _registry = None


def reset_registry() -> None:
    """
    Reset the global registry without closing providers.

    For testing purposes only.
    """
    global _registry
    _registry = None
