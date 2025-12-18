"""
Unit tests for the search provider abstraction layer.

Tests for SearchProvider abstraction.
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

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-SR-N-01 | Valid SearchResult with required fields | Equivalence – normal | Result created successfully | - |
| TC-SR-N-02 | SearchResult with all fields | Equivalence – normal | All fields stored correctly | - |
| TC-SR-N-03 | SearchResult.to_dict() | Equivalence – normal | Dictionary with all fields | - |
| TC-SR-N-04 | SearchResult.from_dict() with complete data | Equivalence – normal | SearchResult object created | - |
| TC-SR-B-01 | Empty title string | Boundary – empty | Validation error or empty string | - |
| TC-SR-B-02 | Empty URL string | Boundary – empty | Validation error or empty string | - |
| TC-SR-B-03 | rank = 0 | Boundary – zero | Valid (minimum rank) | - |
| TC-SR-B-04 | rank = -1 | Boundary – negative | Validation error | - |
| TC-SR-A-01 | Missing required field in from_dict() | Abnormal – missing field | Default values used | - |
| TC-SR-A-02 | Invalid source_tag value | Abnormal – invalid enum | Validation error | - |
| TC-SP-N-01 | Successful SearchResponse | Equivalence – normal | ok=True, error=None | - |
| TC-SP-A-01 | SearchResponse with error | Abnormal – error | ok=False, error set | - |
| TC-SP-B-01 | Empty results list | Boundary – empty | Valid response | - |
| TC-SP-B-02 | total_count = 0 | Boundary – zero | Valid | - |
| TC-SO-N-01 | Default SearchOptions | Equivalence – normal | Default values set | - |
| TC-SO-N-02 | Custom SearchOptions | Equivalence – normal | Custom values stored | - |
| TC-SO-B-01 | limit = 0 | Boundary – zero | Validation error | - |
| TC-SO-B-02 | limit = -1 | Boundary – negative | Validation error | - |
| TC-SO-B-03 | page = 0 | Boundary – zero | Validation error | - |
| TC-HS-N-01 | Healthy status | Equivalence – normal | HEALTHY state | - |
| TC-HS-N-02 | Degraded status | Equivalence – normal | DEGRADED state | - |
| TC-HS-N-03 | Unhealthy status | Equivalence – normal | UNHEALTHY state | - |
| TC-HS-B-01 | success_rate = 0.0 | Boundary – zero | Valid | - |
| TC-HS-B-02 | success_rate = 1.0 | Boundary – max | Valid | - |
| TC-HS-B-03 | success_rate = -0.1 | Boundary – negative | Validation error | - |
| TC-HS-B-04 | success_rate = 1.1 | Boundary – above max | Validation error | - |
| TC-RG-N-01 | Register provider | Equivalence – normal | Provider registered | - |
| TC-RG-N-02 | Register sets default | Equivalence – normal | First provider is default | - |
| TC-RG-A-01 | Register duplicate provider | Abnormal – duplicate | ValueError raised | - |
| TC-RG-A-02 | Unregister nonexistent | Abnormal – not found | Returns None | - |
| TC-RG-A-03 | Set default nonexistent | Abnormal – not found | ValueError raised | - |
| TC-RG-A-04 | Search with no providers | Abnormal – empty | RuntimeError raised | - |
| TC-RG-N-03 | Search with fallback success | Equivalence – normal | Uses primary provider | - |
| TC-RG-N-04 | Search with fallback uses backup | Equivalence – normal | Falls back to backup | - |
| TC-RG-N-05 | Search skips unhealthy | Equivalence – normal | Skips unhealthy providers | - |
| TC-RG-A-05 | All providers fail | Abnormal – all fail | Error response | - |
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
        """TC-SR-N-01: Test creating a result with required fields only.
        
        // Given: Required fields only (title, url, snippet, engine, rank)
        // When: Creating SearchResult
        // Then: Result created with defaults for optional fields
        """
        # Given: Required fields only
        # When: Creating SearchResult
        result = SearchResult(
            title="Test",
            url="https://example.com",
            snippet="Snippet text",
            engine="test",
            rank=1,
        )
        
        # Then: Result created with defaults
        assert result.title == "Test"
        assert result.url == "https://example.com"
        assert result.snippet == "Snippet text"
        assert result.engine == "test"
        assert result.rank == 1
        assert result.date is None
        assert result.source_tag == SourceTag.UNKNOWN
    
    def test_create_full_result(self):
        """TC-SR-N-02: Test creating a result with all fields.
        
        // Given: All fields provided
        // When: Creating SearchResult
        // Then: All fields stored correctly
        """
        # Given: All fields provided
        # When: Creating SearchResult
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
        
        # Then: All fields stored correctly
        assert result.title == "Academic Paper"
        assert result.date == "2024-01-15"
        assert result.source_tag == SourceTag.ACADEMIC
        assert result.raw_data == {"extra": "data"}
    
    def test_to_dict_serialization(self):
        """TC-SR-N-03: Test serialization to dictionary.
        
        // Given: SearchResult with all fields
        // When: Calling to_dict()
        // Then: Dictionary with all fields returned
        """
        # Given: SearchResult with all fields
        result = SearchResult(
            title="Test",
            url="https://example.com",
            snippet="Snippet",
            engine="google",
            rank=1,
            date="2024-01-15",
            source_tag=SourceTag.NEWS,
        )
        
        # When: Calling to_dict()
        d = result.to_dict()
        
        # Then: Dictionary with all fields
        assert d["title"] == "Test"
        assert d["url"] == "https://example.com"
        assert d["snippet"] == "Snippet"
        assert d["engine"] == "google"
        assert d["rank"] == 1
        assert d["date"] == "2024-01-15"
        assert d["source_tag"] == "news"
    
    def test_from_dict_deserialization(self):
        """TC-SR-N-04: Test deserialization from dictionary.
        
        // Given: Complete dictionary data
        // When: Calling from_dict()
        // Then: SearchResult object created
        """
        # Given: Complete dictionary data
        data = {
            "title": "Test Title",
            "url": "https://test.com",
            "snippet": "Test snippet",
            "engine": "bing",
            "rank": 5,
            "date": "2024-02-20",
            "source_tag": "academic",
        }
        
        # When: Calling from_dict()
        result = SearchResult.from_dict(data)
        
        # Then: SearchResult object created
        assert result.title == "Test Title"
        assert result.url == "https://test.com"
        assert result.engine == "bing"
        assert result.rank == 5
        assert result.source_tag == SourceTag.ACADEMIC
    
    def test_from_dict_with_missing_fields(self):
        """TC-SR-A-01: Test deserialization handles missing optional fields.
        
        // Given: Dictionary with only required fields
        // When: Calling from_dict()
        // Then: Default values used for missing fields
        """
        # Given: Dictionary with only required fields
        data = {
            "title": "Minimal",
            "url": "https://minimal.com",
        }
        
        # When: Calling from_dict()
        result = SearchResult.from_dict(data)
        
        # Then: Default values used
        assert result.title == "Minimal"
        assert result.url == "https://minimal.com"
        assert result.snippet == ""
        assert result.engine == "unknown"
        assert result.rank == 0
        assert result.source_tag == SourceTag.UNKNOWN
    
    def test_empty_title(self):
        """TC-SR-B-01: Test empty title string.
        
        // Given: Empty title string
        // When: Creating SearchResult
        // Then: Empty string accepted (or validation error)
        """
        # Given: Empty title string
        # When: Creating SearchResult
        result = SearchResult(
            title="",
            url="https://example.com",
            snippet="Snippet",
            engine="test",
            rank=1,
        )
        
        # Then: Empty string accepted
        assert result.title == ""
    
    def test_empty_url(self):
        """TC-SR-B-02: Test empty URL string.
        
        // Given: Empty URL string
        // When: Creating SearchResult
        // Then: Empty string accepted (or validation error)
        """
        # Given: Empty URL string
        # When: Creating SearchResult
        result = SearchResult(
            title="Test",
            url="",
            snippet="Snippet",
            engine="test",
            rank=1,
        )
        
        # Then: Empty string accepted
        assert result.url == ""
    
    def test_rank_zero(self):
        """TC-SR-B-03: Test rank = 0 (minimum valid value).
        
        // Given: rank = 0
        // When: Creating SearchResult
        // Then: Valid result created
        """
        # Given: rank = 0
        # When: Creating SearchResult
        result = SearchResult(
            title="Test",
            url="https://example.com",
            snippet="Snippet",
            engine="test",
            rank=0,
        )
        
        # Then: Valid result
        assert result.rank == 0
    
    def test_rank_negative_raises_error(self):
        """TC-SR-B-04: Test rank = -1 raises validation error.
        
        // Given: rank = -1 (negative)
        // When: Creating SearchResult
        // Then: ValidationError raised
        """
        from pydantic import ValidationError
        
        # Given: rank = -1
        # When/Then: ValidationError raised
        with pytest.raises(ValidationError) as exc_info:
            SearchResult(
                title="Test",
                url="https://example.com",
                snippet="Snippet",
                engine="test",
                rank=-1,
            )
        
        # Then: Error mentions rank constraint
        error_str = str(exc_info.value)
        assert "rank" in error_str.lower() or "greater than" in error_str.lower()
    
    def test_invalid_source_tag_raises_error(self):
        """TC-SR-A-02: Test invalid source_tag value raises error.
        
        // Given: Invalid source_tag value
        // When: Creating SearchResult
        // Then: ValidationError raised
        """
        from pydantic import ValidationError
        
        # Given: Invalid source_tag
        # When/Then: ValidationError raised
        with pytest.raises(ValidationError):
            SearchResult(
                title="Test",
                url="https://example.com",
                snippet="Snippet",
                engine="test",
                rank=1,
                source_tag="invalid_tag",  # type: ignore
            )


# ============================================================================
# SearchResponse Tests
# ============================================================================


class TestSearchResponse:
    """Tests for SearchResponse data class."""
    
    def test_successful_response(self, sample_results):
        """TC-SP-N-01: Test creating a successful response.
        
        // Given: Valid results and query
        // When: Creating SearchResponse
        // Then: ok=True, error=None
        """
        # Given: Valid results and query
        # When: Creating SearchResponse
        response = SearchResponse(
            results=sample_results,
            query="test query",
            provider="browser",
            total_count=3,
            elapsed_ms=150.5,
        )
        
        # Then: ok=True, error=None
        assert response.ok is True
        assert response.error is None
        assert len(response.results) == 3
        assert response.query == "test query"
        assert response.provider == "browser"
        assert response.total_count == 3
        assert response.elapsed_ms == 150.5
    
    def test_error_response(self):
        """TC-SP-A-01: Test creating an error response.
        
        // Given: Error message provided
        // When: Creating SearchResponse with error
        // Then: ok=False, error set
        """
        # Given: Error message provided
        # When: Creating SearchResponse with error
        response = SearchResponse(
            results=[],
            query="failed query",
            provider="browser",
            error="Connection timeout",
        )
        
        # Then: ok=False, error set
        assert response.ok is False
        assert response.error == "Connection timeout"
        assert len(response.results) == 0
    
    def test_empty_results_list(self):
        """TC-SP-B-01: Test empty results list.
        
        // Given: Empty results list
        // When: Creating SearchResponse
        // Then: Valid response with empty results
        """
        # Given: Empty results list
        # When: Creating SearchResponse
        response = SearchResponse(
            results=[],
            query="test query",
            provider="browser",
            total_count=0,
        )
        
        # Then: Valid response with empty results
        assert response.ok is True
        assert len(response.results) == 0
        assert response.total_count == 0
    
    def test_total_count_zero(self):
        """TC-SP-B-02: Test total_count = 0.
        
        // Given: total_count = 0
        // When: Creating SearchResponse
        // Then: Valid response
        """
        # Given: total_count = 0
        # When: Creating SearchResponse
        response = SearchResponse(
            results=[],
            query="test",
            provider="test",
            total_count=0,
        )
        
        # Then: Valid response
        assert response.total_count == 0
    
    def test_to_dict_includes_ok(self, sample_results):
        """TC-SP-N-02: Test that to_dict includes the ok property.
        
        // Given: SearchResponse with results
        // When: Calling to_dict()
        // Then: Dictionary includes ok property
        """
        # Given: SearchResponse with results
        response = SearchResponse(
            results=sample_results,
            query="test",
            provider="test",
        )
        
        # When: Calling to_dict()
        d = response.to_dict()
        
        # Then: Dictionary includes ok property
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
        """TC-SO-N-01: Test default option values.
        
        // Given: No parameters provided
        // When: Creating SearchOptions
        // Then: Default values set
        """
        # Given: No parameters provided
        # When: Creating SearchOptions
        options = SearchOptions()
        
        # Then: Default values set
        assert options.engines is None
        assert options.categories is None
        assert options.language == "ja"
        assert options.time_range == "all"
        assert options.limit == 10
        assert options.page == 1
    
    def test_custom_options(self):
        """TC-SO-N-02: Test custom option values.
        
        // Given: Custom values provided
        // When: Creating SearchOptions
        // Then: Custom values stored
        """
        # Given: Custom values provided
        # When: Creating SearchOptions
        options = SearchOptions(
            engines=["google", "duckduckgo"],
            categories=["general", "news"],
            language="en",
            time_range="week",
            limit=20,
            page=2,
        )
        
        # Then: Custom values stored
        assert options.engines == ["google", "duckduckgo"]
        assert options.categories == ["general", "news"]
        assert options.language == "en"
        assert options.time_range == "week"
        assert options.limit == 20
        assert options.page == 2
    
    def test_limit_zero_raises_error(self):
        """TC-SO-B-01: Test limit = 0 raises validation error.
        
        // Given: limit = 0
        // When: Creating SearchOptions
        // Then: ValidationError raised
        """
        from pydantic import ValidationError
        
        # Given: limit = 0
        # When/Then: ValidationError raised
        with pytest.raises(ValidationError) as exc_info:
            SearchOptions(limit=0)
        
        # Then: Error mentions limit constraint
        error_str = str(exc_info.value)
        assert "limit" in error_str.lower() or "greater than" in error_str.lower()
    
    def test_limit_negative_raises_error(self):
        """TC-SO-B-02: Test limit = -1 raises validation error.
        
        // Given: limit = -1
        // When: Creating SearchOptions
        // Then: ValidationError raised
        """
        from pydantic import ValidationError
        
        # Given: limit = -1
        # When/Then: ValidationError raised
        with pytest.raises(ValidationError):
            SearchOptions(limit=-1)
    
    def test_page_zero_raises_error(self):
        """TC-SO-B-03: Test page = 0 raises validation error.
        
        // Given: page = 0
        // When: Creating SearchOptions
        // Then: ValidationError raised
        """
        from pydantic import ValidationError
        
        # Given: page = 0
        # When/Then: ValidationError raised
        with pytest.raises(ValidationError):
            SearchOptions(page=0)


# ============================================================================
# HealthStatus Tests
# ============================================================================


class TestHealthStatus:
    """Tests for HealthStatus data class."""
    
    def test_healthy_status(self):
        """TC-HS-N-01: Test creating healthy status.
        
        // Given: Healthy provider
        // When: Creating HealthStatus.healthy()
        // Then: HEALTHY state with success_rate=1.0
        """
        # Given: Healthy provider
        # When: Creating HealthStatus.healthy()
        status = HealthStatus.healthy(latency_ms=50.0)
        
        # Then: HEALTHY state with success_rate=1.0
        assert status.state == HealthState.HEALTHY
        assert status.success_rate == 1.0
        assert status.latency_ms == 50.0
        assert status.last_check is not None
    
    def test_degraded_status(self):
        """TC-HS-N-02: Test creating degraded status.
        
        // Given: Degraded provider (success_rate < 1.0)
        // When: Creating HealthStatus.degraded()
        // Then: DEGRADED state with success_rate set
        """
        # Given: Degraded provider
        # When: Creating HealthStatus.degraded()
        status = HealthStatus.degraded(
            success_rate=0.7,
            message="High error rate",
        )
        
        # Then: DEGRADED state with success_rate set
        assert status.state == HealthState.DEGRADED
        assert status.success_rate == 0.7
        assert status.message == "High error rate"
    
    def test_unhealthy_status(self):
        """TC-HS-N-03: Test creating unhealthy status.
        
        // Given: Unhealthy provider
        // When: Creating HealthStatus.unhealthy()
        // Then: UNHEALTHY state with success_rate=0.0
        """
        # Given: Unhealthy provider
        # When: Creating HealthStatus.unhealthy()
        status = HealthStatus.unhealthy(message="Service unavailable")
        
        # Then: UNHEALTHY state with success_rate=0.0
        assert status.state == HealthState.UNHEALTHY
        assert status.success_rate == 0.0
        assert status.message == "Service unavailable"
    
    def test_success_rate_zero(self):
        """TC-HS-B-01: Test success_rate = 0.0 is valid.
        
        // Given: success_rate = 0.0
        // When: Creating degraded status
        // Then: Valid status created
        """
        # Given: success_rate = 0.0
        # When: Creating degraded status
        status = HealthStatus.degraded(success_rate=0.0, message="Down")
        
        # Then: Valid status
        assert status.success_rate == 0.0
    
    def test_success_rate_max(self):
        """TC-HS-B-02: Test success_rate = 1.0 is valid.
        
        // Given: success_rate = 1.0
        // When: Creating healthy status
        // Then: Valid status created
        """
        # Given: success_rate = 1.0
        # When: Creating healthy status (healthy() always has success_rate=1.0)
        status = HealthStatus.healthy()
        
        # Then: Valid status
        assert status.success_rate == 1.0
    
    def test_success_rate_negative_raises_error(self):
        """TC-HS-B-03: Test success_rate = -0.1 raises validation error.
        
        // Given: success_rate = -0.1 (negative)
        // When: Creating degraded status
        // Then: ValidationError raised
        """
        from pydantic import ValidationError
        
        # Given: success_rate = -0.1
        # When/Then: ValidationError raised
        with pytest.raises(ValidationError) as exc_info:
            HealthStatus.degraded(success_rate=-0.1, message="Invalid")
        
        # Then: Error mentions success_rate constraint
        error_str = str(exc_info.value)
        assert "success_rate" in error_str.lower() or "greater than" in error_str.lower()
    
    def test_success_rate_above_max_raises_error(self):
        """TC-HS-B-04: Test success_rate = 1.1 raises validation error.
        
        // Given: success_rate = 1.1 (above max)
        // When: Creating degraded status
        // Then: ValidationError raised
        """
        from pydantic import ValidationError
        
        # Given: success_rate = 1.1
        # When/Then: ValidationError raised
        with pytest.raises(ValidationError) as exc_info:
            HealthStatus.degraded(success_rate=1.1, message="Invalid")
        
        # Then: Error mentions success_rate constraint
        error_str = str(exc_info.value)
        assert "success_rate" in error_str.lower() or "less than" in error_str.lower()


# ============================================================================
# SearchProviderRegistry Tests
# ============================================================================


class TestSearchProviderRegistry:
    """Tests for SearchProviderRegistry."""
    
    def test_register_provider(self, mock_provider):
        """TC-RG-N-01: Test registering a provider.
        
        // Given: A provider instance
        // When: Registering provider
        // Then: Provider registered and accessible
        """
        # Given: A provider instance
        registry = SearchProviderRegistry()
        
        # When: Registering provider
        registry.register(mock_provider)
        
        # Then: Provider registered and accessible
        assert "mock" in registry.list_providers()
        assert registry.get("mock") is mock_provider
    
    def test_register_sets_default(self, mock_provider):
        """TC-RG-N-02: Test that first provider becomes default.
        
        // Given: Empty registry
        // When: Registering first provider
        // Then: First provider becomes default
        """
        # Given: Empty registry
        registry = SearchProviderRegistry()
        
        # When: Registering first provider
        registry.register(mock_provider)
        
        # Then: First provider becomes default
        assert registry.get_default() is mock_provider
    
    def test_register_duplicate_raises(self, mock_provider):
        """TC-RG-A-01: Test that duplicate registration raises error.
        
        // Given: Provider already registered
        // When: Registering same provider again
        // Then: ValueError raised with message
        """
        # Given: Provider already registered
        registry = SearchProviderRegistry()
        registry.register(mock_provider)
        
        # When/Then: ValueError raised
        with pytest.raises(ValueError, match="already registered") as exc_info:
            registry.register(mock_provider)
        
        # Then: Error message mentions duplicate
        assert "already registered" in str(exc_info.value).lower()
    
    def test_unregister_provider(self, mock_provider):
        """TC-RG-N-03: Test unregistering a provider.
        
        // Given: Registered provider
        // When: Unregistering provider
        // Then: Provider removed from registry
        """
        # Given: Registered provider
        registry = SearchProviderRegistry()
        registry.register(mock_provider)
        
        # When: Unregistering provider
        removed = registry.unregister("mock")
        
        # Then: Provider removed
        assert removed is mock_provider
        assert "mock" not in registry.list_providers()
    
    def test_unregister_nonexistent(self):
        """TC-RG-A-02: Test unregistering non-existent provider returns None.
        
        // Given: Provider not registered
        // When: Unregistering nonexistent provider
        // Then: Returns None
        """
        # Given: Provider not registered
        registry = SearchProviderRegistry()
        
        # When: Unregistering nonexistent provider
        removed = registry.unregister("nonexistent")
        
        # Then: Returns None
        assert removed is None
    
    def test_set_default(self):
        """TC-RG-N-04: Test changing default provider.
        
        // Given: Multiple providers registered
        // When: Setting different default
        // Then: Default changed
        """
        # Given: Multiple providers registered
        registry = SearchProviderRegistry()
        provider1 = MockSearchProvider("provider1")
        provider2 = MockSearchProvider("provider2")
        
        registry.register(provider1)
        registry.register(provider2)
        
        assert registry.get_default() is provider1
        
        # When: Setting different default
        registry.set_default("provider2")
        
        # Then: Default changed
        assert registry.get_default() is provider2
    
    def test_set_default_nonexistent_raises(self):
        """TC-RG-A-03: Test setting non-existent provider as default raises error.
        
        // Given: Provider not registered
        // When: Setting as default
        // Then: ValueError raised with message
        """
        # Given: Provider not registered
        registry = SearchProviderRegistry()
        
        # When/Then: ValueError raised
        with pytest.raises(ValueError, match="not registered") as exc_info:
            registry.set_default("nonexistent")
        
        # Then: Error message mentions not registered
        assert "not registered" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_search_with_fallback_success(self, mock_provider):
        """TC-RG-N-05: Test successful search with fallback mechanism.
        
        // Given: Registered provider
        // When: Searching with fallback
        // Then: Uses primary provider successfully
        """
        # Given: Registered provider
        registry = SearchProviderRegistry()
        registry.register(mock_provider)
        
        # When: Searching with fallback
        response = await registry.search_with_fallback("test query")
        
        # Then: Uses primary provider successfully
        assert response.ok
        assert len(mock_provider.search_calls) == 1
        assert mock_provider.search_calls[0][0] == "test query"
    
    @pytest.mark.asyncio
    async def test_search_with_fallback_uses_fallback(self, sample_results):
        """TC-RG-N-06: Test that fallback is used when primary fails.
        
        // Given: Primary provider fails, backup provider available
        // When: Searching with fallback
        // Then: Falls back to backup provider
        """
        # Given: Primary provider fails, backup available
        registry = SearchProviderRegistry()
        
        failing_provider = MockSearchProvider("failing", error="Service unavailable")
        working_provider = MockSearchProvider("working", results=sample_results)
        
        registry.register(failing_provider, set_default=True)
        registry.register(working_provider)
        
        # When: Searching with fallback
        response = await registry.search_with_fallback("test query")
        
        # Then: Falls back to backup provider
        assert response.ok
        assert response.provider == "working"
        assert len(response.results) == 3
    
    @pytest.mark.asyncio
    async def test_search_with_fallback_skips_unhealthy(self, sample_results):
        """TC-RG-N-07: Test that unhealthy providers are skipped.
        
        // Given: Unhealthy primary provider, healthy backup
        // When: Searching with fallback
        // Then: Skips unhealthy, uses healthy provider
        """
        # Given: Unhealthy primary, healthy backup
        registry = SearchProviderRegistry()
        
        unhealthy_provider = MockSearchProvider(
            "unhealthy",
            results=sample_results,
            health=HealthStatus.unhealthy("Down"),
        )
        healthy_provider = MockSearchProvider("healthy", results=sample_results)
        
        registry.register(unhealthy_provider, set_default=True)
        registry.register(healthy_provider)
        
        # When: Searching with fallback
        response = await registry.search_with_fallback("test query")
        
        # Then: Skips unhealthy, uses healthy
        assert response.ok
        assert response.provider == "healthy"
        # Unhealthy provider should not have been called
        assert len(unhealthy_provider.search_calls) == 0
    
    @pytest.mark.asyncio
    async def test_search_with_fallback_all_fail(self):
        """TC-RG-A-05: Test error response when all providers fail.
        
        // Given: All providers fail
        // When: Searching with fallback
        // Then: Error response with message
        """
        # Given: All providers fail
        registry = SearchProviderRegistry()
        
        registry.register(MockSearchProvider("p1", error="Error 1"))
        registry.register(MockSearchProvider("p2", error="Error 2"))
        
        # When: Searching with fallback
        response = await registry.search_with_fallback("test query")
        
        # Then: Error response
        assert not response.ok
        assert "All providers failed" in response.error
    
    @pytest.mark.asyncio
    async def test_search_with_fallback_no_providers(self):
        """TC-RG-A-04: Test error when no providers registered.
        
        // Given: Empty registry
        // When: Searching with fallback
        // Then: RuntimeError raised with message
        """
        # Given: Empty registry
        registry = SearchProviderRegistry()
        
        # When/Then: RuntimeError raised
        with pytest.raises(RuntimeError, match="No search providers registered") as exc_info:
            await registry.search_with_fallback("test query")
        
        # Then: Error message mentions no providers
        assert "no search providers" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_get_all_health(self):
        """TC-RG-N-08: Test getting health from all providers.
        
        // Given: Multiple providers with different health states
        // When: Getting all health
        // Then: Health status for all providers returned
        """
        # Given: Multiple providers with different health states
        registry = SearchProviderRegistry()
        
        registry.register(MockSearchProvider("p1", health=HealthStatus.healthy()))
        registry.register(MockSearchProvider(
            "p2", 
            health=HealthStatus.degraded(0.8),
        ))
        
        # When: Getting all health
        health = await registry.get_all_health()
        
        # Then: Health status for all providers returned
        assert "p1" in health
        assert "p2" in health
        assert health["p1"].state == HealthState.HEALTHY
        assert health["p2"].state == HealthState.DEGRADED
    
    @pytest.mark.asyncio
    async def test_close_all(self, mock_provider):
        """TC-RG-N-09: Test closing all providers.
        
        // Given: Registered providers
        // When: Closing all providers
        // Then: All providers closed and removed
        """
        # Given: Registered providers
        registry = SearchProviderRegistry()
        registry.register(mock_provider)
        
        # When: Closing all providers
        await registry.close_all()
        
        # Then: All providers closed and removed
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
        """TC-RG-N-10: Test that get_registry returns singleton.
        
        // Given: Global registry
        // When: Calling get_registry() multiple times
        // Then: Same instance returned
        """
        # Given: Global registry
        # When: Calling get_registry() multiple times
        registry1 = get_registry()
        registry2 = get_registry()
        
        # Then: Same instance returned
        assert registry1 is registry2
    
    def test_reset_registry(self):
        """TC-RG-N-11: Test that reset creates new instance.
        
        // Given: Registry with registered provider
        // When: Resetting registry
        // Then: New instance created, providers cleared
        """
        # Given: Registry with registered provider
        registry1 = get_registry()
        registry1.register(MockSearchProvider("test"))
        
        # When: Resetting registry
        reset_registry()
        registry2 = get_registry()
        
        # Then: New instance created, providers cleared
        assert registry1 is not registry2
        assert len(registry2.list_providers()) == 0

