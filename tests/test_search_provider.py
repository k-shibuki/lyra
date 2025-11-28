"""
Unit tests for the search provider abstraction layer.

Tests for Phase 17.1.1: SearchProvider abstraction.
Validates:
- SearchProvider protocol and BaseSearchProvider
- SearchResult and SearchResponse data classes
- SearchProviderRegistry registration and fallback

Follows §7.1 test code quality standards:
- Specific assertions with concrete values
- No conditional assertions
- Proper mocking of external dependencies
- Boundary conditions coverage

BrowserSearchProvider tests are in test_browser_search_provider.py.
"""

import asyncio

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.search.provider import (
    BaseSearchProvider,
    HealthState,
    HealthStatus,
    SearchOptions,
    SearchProviderRegistry,
    SearchResponse,
    SearchResult,
    SourceTag,
    get_registry,
    reset_registry,
)


# ============================================================================
# Test Fixtures
# ============================================================================


class MockSearchProvider(BaseSearchProvider):
    """Mock provider for testing."""
    
    def __init__(
        self,
        name: str = "mock",
        results: list[SearchResult] | None = None,
        error: str | None = None,
        health: HealthStatus | None = None,
    ):
        super().__init__(name)
        self._results = results or []
        self._error = error
        self._health = health or HealthStatus.healthy()
        self.search_calls: list[tuple[str, SearchOptions | None]] = []
    
    async def search(
        self,
        query: str,
        options: SearchOptions | None = None,
    ) -> SearchResponse:
        self.search_calls.append((query, options))
        
        if self._error:
            return SearchResponse(
                results=[],
                query=query,
                provider=self.name,
                error=self._error,
            )
        
        return SearchResponse(
            results=self._results,
            query=query,
            provider=self.name,
            total_count=len(self._results),
        )
    
    async def get_health(self) -> HealthStatus:
        return self._health


@pytest.fixture
def sample_results() -> list[SearchResult]:
    """Create sample search results for testing."""
    return [
        SearchResult(
            title="Test Result 1",
            url="https://example.com/page1",
            snippet="This is a test snippet for the first result.",
            engine="google",
            rank=1,
            source_tag=SourceTag.UNKNOWN,
        ),
        SearchResult(
            title="Academic Paper on AI",
            url="https://arxiv.org/abs/1234.5678",
            snippet="Machine learning research paper.",
            engine="duckduckgo",
            rank=2,
            date="2024-01-15",
            source_tag=SourceTag.ACADEMIC,
        ),
        SearchResult(
            title="Government Report",
            url="https://www.go.jp/report/2024",
            snippet="Official government publication.",
            engine="qwant",
            rank=3,
            source_tag=SourceTag.GOVERNMENT,
        ),
    ]


@pytest.fixture
def mock_provider(sample_results) -> MockSearchProvider:
    """Create a mock provider with sample results."""
    return MockSearchProvider(results=sample_results)


@pytest.fixture(autouse=True)
def cleanup():
    """Reset global state before and after each test."""
    reset_registry()
    yield
    reset_registry()


# ============================================================================
# SearchResult Tests
# ============================================================================


class TestSearchResult:
    """Tests for SearchResult data class."""
    
    def test_create_minimal_result(self):
        """Test creating a result with required fields only."""
        result = SearchResult(
            title="Test",
            url="https://example.com",
            snippet="Snippet text",
            engine="test",
            rank=1,
        )
        
        assert result.title == "Test"
        assert result.url == "https://example.com"
        assert result.snippet == "Snippet text"
        assert result.engine == "test"
        assert result.rank == 1
        assert result.date is None
        assert result.source_tag == SourceTag.UNKNOWN
    
    def test_create_full_result(self):
        """Test creating a result with all fields."""
        result = SearchResult(
            title="Academic Paper",
            url="https://arxiv.org/abs/1234",
            snippet="Research findings",
            engine="google",
            rank=3,
            date="2024-01-15",
            source_tag=SourceTag.ACADEMIC,
            raw_data={"extra": "data"},
        )
        
        assert result.title == "Academic Paper"
        assert result.date == "2024-01-15"
        assert result.source_tag == SourceTag.ACADEMIC
        assert result.raw_data == {"extra": "data"}
    
    def test_to_dict_serialization(self):
        """Test serialization to dictionary."""
        result = SearchResult(
            title="Test",
            url="https://example.com",
            snippet="Snippet",
            engine="google",
            rank=1,
            date="2024-01-15",
            source_tag=SourceTag.NEWS,
        )
        
        d = result.to_dict()
        
        assert d["title"] == "Test"
        assert d["url"] == "https://example.com"
        assert d["snippet"] == "Snippet"
        assert d["engine"] == "google"
        assert d["rank"] == 1
        assert d["date"] == "2024-01-15"
        assert d["source_tag"] == "news"
    
    def test_from_dict_deserialization(self):
        """Test deserialization from dictionary."""
        data = {
            "title": "Test Title",
            "url": "https://test.com",
            "snippet": "Test snippet",
            "engine": "bing",
            "rank": 5,
            "date": "2024-02-20",
            "source_tag": "academic",
        }
        
        result = SearchResult.from_dict(data)
        
        assert result.title == "Test Title"
        assert result.url == "https://test.com"
        assert result.engine == "bing"
        assert result.rank == 5
        assert result.source_tag == SourceTag.ACADEMIC
    
    def test_from_dict_with_missing_fields(self):
        """Test deserialization handles missing optional fields."""
        data = {
            "title": "Minimal",
            "url": "https://minimal.com",
        }
        
        result = SearchResult.from_dict(data)
        
        assert result.title == "Minimal"
        assert result.url == "https://minimal.com"
        assert result.snippet == ""
        assert result.engine == "unknown"
        assert result.rank == 0
        assert result.source_tag == SourceTag.UNKNOWN


# ============================================================================
# SearchResponse Tests
# ============================================================================


class TestSearchResponse:
    """Tests for SearchResponse data class."""
    
    def test_successful_response(self, sample_results):
        """Test creating a successful response."""
        response = SearchResponse(
            results=sample_results,
            query="test query",
            provider="browser",
            total_count=3,
            elapsed_ms=150.5,
        )
        
        assert response.ok is True
        assert response.error is None
        assert len(response.results) == 3
        assert response.query == "test query"
        assert response.provider == "browser"
        assert response.total_count == 3
        assert response.elapsed_ms == 150.5
    
    def test_error_response(self):
        """Test creating an error response."""
        response = SearchResponse(
            results=[],
            query="failed query",
            provider="browser",
            error="Connection timeout",
        )
        
        assert response.ok is False
        assert response.error == "Connection timeout"
        assert len(response.results) == 0
    
    def test_to_dict_includes_ok(self, sample_results):
        """Test that to_dict includes the ok property."""
        response = SearchResponse(
            results=sample_results,
            query="test",
            provider="test",
        )
        
        d = response.to_dict()
        
        assert "ok" in d
        assert d["ok"] is True
        assert "results" in d
        assert len(d["results"]) == 3


# ============================================================================
# SearchOptions Tests
# ============================================================================


class TestSearchOptions:
    """Tests for SearchOptions data class."""
    
    def test_default_options(self):
        """Test default option values."""
        options = SearchOptions()
        
        assert options.engines is None
        assert options.categories is None
        assert options.language == "ja"
        assert options.time_range == "all"
        assert options.limit == 10
        assert options.page == 1
    
    def test_custom_options(self):
        """Test custom option values."""
        options = SearchOptions(
            engines=["google", "duckduckgo"],
            categories=["general", "news"],
            language="en",
            time_range="week",
            limit=20,
            page=2,
        )
        
        assert options.engines == ["google", "duckduckgo"]
        assert options.categories == ["general", "news"]
        assert options.language == "en"
        assert options.time_range == "week"
        assert options.limit == 20
        assert options.page == 2


# ============================================================================
# HealthStatus Tests
# ============================================================================


class TestHealthStatus:
    """Tests for HealthStatus data class."""
    
    def test_healthy_status(self):
        """Test creating healthy status."""
        status = HealthStatus.healthy(latency_ms=50.0)
        
        assert status.state == HealthState.HEALTHY
        assert status.success_rate == 1.0
        assert status.latency_ms == 50.0
        assert status.last_check is not None
    
    def test_degraded_status(self):
        """Test creating degraded status."""
        status = HealthStatus.degraded(
            success_rate=0.7,
            message="High error rate",
        )
        
        assert status.state == HealthState.DEGRADED
        assert status.success_rate == 0.7
        assert status.message == "High error rate"
    
    def test_unhealthy_status(self):
        """Test creating unhealthy status."""
        status = HealthStatus.unhealthy(message="Service unavailable")
        
        assert status.state == HealthState.UNHEALTHY
        assert status.success_rate == 0.0
        assert status.message == "Service unavailable"


# ============================================================================
# SearchProviderRegistry Tests
# ============================================================================


class TestSearchProviderRegistry:
    """Tests for SearchProviderRegistry."""
    
    def test_register_provider(self, mock_provider):
        """Test registering a provider."""
        registry = SearchProviderRegistry()
        registry.register(mock_provider)
        
        assert "mock" in registry.list_providers()
        assert registry.get("mock") is mock_provider
    
    def test_register_sets_default(self, mock_provider):
        """Test that first provider becomes default."""
        registry = SearchProviderRegistry()
        registry.register(mock_provider)
        
        assert registry.get_default() is mock_provider
    
    def test_register_duplicate_raises(self, mock_provider):
        """Test that duplicate registration raises error."""
        registry = SearchProviderRegistry()
        registry.register(mock_provider)
        
        with pytest.raises(ValueError, match="already registered"):
            registry.register(mock_provider)
    
    def test_unregister_provider(self, mock_provider):
        """Test unregistering a provider."""
        registry = SearchProviderRegistry()
        registry.register(mock_provider)
        
        removed = registry.unregister("mock")
        
        assert removed is mock_provider
        assert "mock" not in registry.list_providers()
    
    def test_unregister_nonexistent(self):
        """Test unregistering non-existent provider returns None."""
        registry = SearchProviderRegistry()
        
        removed = registry.unregister("nonexistent")
        
        assert removed is None
    
    def test_set_default(self):
        """Test changing default provider."""
        registry = SearchProviderRegistry()
        provider1 = MockSearchProvider("provider1")
        provider2 = MockSearchProvider("provider2")
        
        registry.register(provider1)
        registry.register(provider2)
        
        assert registry.get_default() is provider1
        
        registry.set_default("provider2")
        
        assert registry.get_default() is provider2
    
    def test_set_default_nonexistent_raises(self):
        """Test setting non-existent provider as default raises error."""
        registry = SearchProviderRegistry()
        
        with pytest.raises(ValueError, match="not registered"):
            registry.set_default("nonexistent")
    
    @pytest.mark.asyncio
    async def test_search_with_fallback_success(self, mock_provider):
        """Test successful search with fallback mechanism."""
        registry = SearchProviderRegistry()
        registry.register(mock_provider)
        
        response = await registry.search_with_fallback("test query")
        
        assert response.ok
        assert len(mock_provider.search_calls) == 1
        assert mock_provider.search_calls[0][0] == "test query"
    
    @pytest.mark.asyncio
    async def test_search_with_fallback_uses_fallback(self, sample_results):
        """Test that fallback is used when primary fails."""
        registry = SearchProviderRegistry()
        
        failing_provider = MockSearchProvider("failing", error="Service unavailable")
        working_provider = MockSearchProvider("working", results=sample_results)
        
        registry.register(failing_provider, set_default=True)
        registry.register(working_provider)
        
        response = await registry.search_with_fallback("test query")
        
        assert response.ok
        assert response.provider == "working"
        assert len(response.results) == 3
    
    @pytest.mark.asyncio
    async def test_search_with_fallback_skips_unhealthy(self, sample_results):
        """Test that unhealthy providers are skipped."""
        registry = SearchProviderRegistry()
        
        unhealthy_provider = MockSearchProvider(
            "unhealthy",
            results=sample_results,
            health=HealthStatus.unhealthy("Down"),
        )
        healthy_provider = MockSearchProvider("healthy", results=sample_results)
        
        registry.register(unhealthy_provider, set_default=True)
        registry.register(healthy_provider)
        
        response = await registry.search_with_fallback("test query")
        
        assert response.ok
        assert response.provider == "healthy"
        # Unhealthy provider should not have been called
        assert len(unhealthy_provider.search_calls) == 0
    
    @pytest.mark.asyncio
    async def test_search_with_fallback_all_fail(self):
        """Test error response when all providers fail."""
        registry = SearchProviderRegistry()
        
        registry.register(MockSearchProvider("p1", error="Error 1"))
        registry.register(MockSearchProvider("p2", error="Error 2"))
        
        response = await registry.search_with_fallback("test query")
        
        assert not response.ok
        assert "All providers failed" in response.error
    
    @pytest.mark.asyncio
    async def test_search_with_fallback_no_providers(self):
        """Test error when no providers registered."""
        registry = SearchProviderRegistry()
        
        with pytest.raises(RuntimeError, match="No search providers registered"):
            await registry.search_with_fallback("test query")
    
    @pytest.mark.asyncio
    async def test_get_all_health(self):
        """Test getting health from all providers."""
        registry = SearchProviderRegistry()
        
        registry.register(MockSearchProvider("p1", health=HealthStatus.healthy()))
        registry.register(MockSearchProvider(
            "p2", 
            health=HealthStatus.degraded(0.8),
        ))
        
        health = await registry.get_all_health()
        
        assert "p1" in health
        assert "p2" in health
        assert health["p1"].state == HealthState.HEALTHY
        assert health["p2"].state == HealthState.DEGRADED
    
    @pytest.mark.asyncio
    async def test_close_all(self, mock_provider):
        """Test closing all providers."""
        registry = SearchProviderRegistry()
        registry.register(mock_provider)
        
        await registry.close_all()
        
        assert len(registry.list_providers()) == 0
        assert mock_provider.is_closed


# Note: TestClassifySource moved to test_search.py
# See test_browser_search_provider.py for BrowserSearchProvider tests


# ============================================================================
# Global Registry Tests
# ============================================================================


class TestGlobalRegistry:
    """Tests for global registry functions."""
    
    def test_get_registry_singleton(self):
        """Test that get_registry returns singleton."""
        registry1 = get_registry()
        registry2 = get_registry()
        
        assert registry1 is registry2
    
    def test_reset_registry(self):
        """Test that reset creates new instance."""
        registry1 = get_registry()
        registry1.register(MockSearchProvider("test"))
        
        reset_registry()
        registry2 = get_registry()
        
        assert registry1 is not registry2
        assert len(registry2.list_providers()) == 0

