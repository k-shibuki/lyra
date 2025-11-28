"""
Unit tests for BrowserSearchProvider.

Tests for Phase 16.9: Direct browser-based search.
Validates:
- BrowserSearchProvider initialization
- Search execution with mocked browser
- CAPTCHA detection and intervention handling
- Session management
- Health status reporting
- Error handling

Follows §7.1 test code quality standards:
- Specific assertions with concrete values
- No conditional assertions
- Proper mocking of external dependencies (Playwright)
- Boundary conditions coverage
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from src.search.browser_search_provider import (
    BrowserSearchProvider,
    BrowserSearchSession,
    get_browser_search_provider,
    reset_browser_search_provider,
)
from src.search.provider import (
    HealthState,
    HealthStatus,
    SearchOptions,
    SearchResponse,
    SearchResult,
    SourceTag,
)
from src.search.search_parsers import ParseResult, ParsedResult


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def sample_parsed_results() -> list[ParsedResult]:
    """Create sample parsed results for testing."""
    return [
        ParsedResult(
            title="Test Result 1",
            url="https://example.com/page1",
            snippet="This is a test snippet.",
            rank=1,
        ),
        ParsedResult(
            title="Test Result 2",
            url="https://arxiv.org/paper",
            snippet="Academic paper content.",
            rank=2,
        ),
    ]


@pytest.fixture
def mock_parse_result(sample_parsed_results) -> ParseResult:
    """Create mock parse result."""
    return ParseResult(ok=True, results=sample_parsed_results)


@pytest.fixture
def mock_page():
    """Create mock Playwright page."""
    page = AsyncMock()
    page.goto = AsyncMock(return_value=MagicMock(status=200))
    page.wait_for_load_state = AsyncMock()
    page.content = AsyncMock(return_value="<html><body>Test</body></html>")
    page.is_closed = MagicMock(return_value=False)
    return page


@pytest.fixture
def mock_context(mock_page):
    """Create mock Playwright context."""
    context = AsyncMock()
    context.new_page = AsyncMock(return_value=mock_page)
    context.cookies = AsyncMock(return_value=[])
    context.route = AsyncMock()
    context.close = AsyncMock()
    return context


@pytest.fixture
def mock_browser(mock_context):
    """Create mock Playwright browser."""
    browser = AsyncMock()
    browser.new_context = AsyncMock(return_value=mock_context)
    browser.close = AsyncMock()
    return browser


@pytest.fixture
def mock_playwright(mock_browser):
    """Create mock Playwright instance."""
    playwright = AsyncMock()
    playwright.chromium = MagicMock()
    playwright.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
    playwright.chromium.launch = AsyncMock(return_value=mock_browser)
    playwright.stop = AsyncMock()
    return playwright


@pytest.fixture(autouse=True)
def reset_provider():
    """Reset provider before each test."""
    reset_browser_search_provider()
    yield
    reset_browser_search_provider()


# ============================================================================
# BrowserSearchSession Tests
# ============================================================================


class TestBrowserSearchSession:
    """Tests for BrowserSearchSession."""
    
    def test_session_creation(self):
        """Test session creation with default values."""
        session = BrowserSearchSession(
            engine="duckduckgo",
            cookies=[{"name": "test", "value": "value"}],
            last_used=1000.0,
        )
        
        assert session.engine == "duckduckgo"
        assert len(session.cookies) == 1
        assert session.captcha_count == 0
        assert session.success_count == 0
    
    def test_session_freshness(self):
        """Test session freshness check."""
        import time
        
        # Fresh session
        session = BrowserSearchSession(
            engine="test",
            cookies=[],
            last_used=time.time(),
        )
        assert session.is_fresh(max_age_seconds=60.0) is True
        
        # Stale session
        session.last_used = time.time() - 7200  # 2 hours ago
        assert session.is_fresh(max_age_seconds=3600.0) is False
    
    def test_record_success(self):
        """Test recording successful search."""
        session = BrowserSearchSession(
            engine="test",
            cookies=[],
            last_used=0.0,
        )
        
        session.record_success()
        
        assert session.success_count == 1
        assert session.last_used > 0
    
    def test_record_captcha(self):
        """Test recording CAPTCHA encounter."""
        session = BrowserSearchSession(
            engine="test",
            cookies=[],
            last_used=0.0,
        )
        
        session.record_captcha()
        
        assert session.captcha_count == 1
        assert session.last_used > 0


# ============================================================================
# BrowserSearchProvider Tests
# ============================================================================


class TestBrowserSearchProvider:
    """Tests for BrowserSearchProvider."""
    
    def test_provider_initialization(self):
        """Test provider initializes correctly."""
        provider = BrowserSearchProvider()
        
        assert provider.name == "browser_search"
        assert provider._default_engine == "duckduckgo"
        assert provider._timeout == 30
        assert provider._is_closed is False
    
    def test_provider_custom_config(self):
        """Test provider with custom configuration."""
        provider = BrowserSearchProvider(
            default_engine="mojeek",
            timeout=60,
            min_interval=5.0,
        )
        
        assert provider._default_engine == "mojeek"
        assert provider._timeout == 60
        assert provider._min_interval == 5.0
    
    @pytest.mark.asyncio
    async def test_search_success(
        self,
        mock_playwright,
        mock_parse_result,
    ):
        """Test successful search execution."""
        provider = BrowserSearchProvider()
        
        with patch(
            "playwright.async_api.async_playwright"
        ) as mock_async_pw:
            mock_async_pw.return_value.start = AsyncMock(
                return_value=mock_playwright
            )
            
            with patch(
                "src.search.browser_search_provider.get_parser"
            ) as mock_get_parser:
                mock_parser = MagicMock()
                mock_parser.build_search_url = MagicMock(
                    return_value="https://duckduckgo.com/?q=test"
                )
                mock_parser.parse = MagicMock(return_value=mock_parse_result)
                mock_get_parser.return_value = mock_parser
                
                response = await provider.search("test query")
                
                assert response.ok is True
                assert len(response.results) == 2
                assert response.provider == "browser_search"
                assert response.error is None
        
        await provider.close()
    
    @pytest.mark.asyncio
    async def test_search_captcha_detection(self, mock_playwright):
        """Test CAPTCHA detection during search."""
        provider = BrowserSearchProvider()
        
        captcha_parse_result = ParseResult(
            ok=False,
            is_captcha=True,
            captcha_type="turnstile",
            error="CAPTCHA detected",
        )
        
        with patch(
            "playwright.async_api.async_playwright"
        ) as mock_async_pw:
            mock_async_pw.return_value.start = AsyncMock(
                return_value=mock_playwright
            )
            
            with patch(
                "src.search.browser_search_provider.get_parser"
            ) as mock_get_parser:
                mock_parser = MagicMock()
                mock_parser.build_search_url = MagicMock(
                    return_value="https://duckduckgo.com/?q=test"
                )
                mock_parser.parse = MagicMock(return_value=captcha_parse_result)
                mock_get_parser.return_value = mock_parser
                
                # Mock intervention to fail
                with patch.object(
                    provider,
                    "_request_intervention",
                    AsyncMock(return_value=False),
                ):
                    response = await provider.search("test query")
                    
                    assert response.ok is False
                    assert "CAPTCHA" in response.error
        
        await provider.close()
    
    @pytest.mark.asyncio
    async def test_search_no_parser(self):
        """Test search with unavailable parser."""
        provider = BrowserSearchProvider(default_engine="nonexistent")
        
        with patch(
            "src.search.browser_search_provider.get_parser",
            return_value=None,
        ):
            response = await provider.search("test query")
            
            assert response.ok is False
            assert "No parser available" in response.error
        
        await provider.close()
    
    @pytest.mark.asyncio
    async def test_search_timeout(self, mock_playwright, mock_context):
        """Test search timeout handling."""
        provider = BrowserSearchProvider(timeout=1)
        
        # Make page.goto timeout
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_page.is_closed = MagicMock(return_value=False)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        
        with patch(
            "playwright.async_api.async_playwright"
        ) as mock_async_pw:
            mock_async_pw.return_value.start = AsyncMock(
                return_value=mock_playwright
            )
            
            with patch(
                "src.search.browser_search_provider.get_parser"
            ) as mock_get_parser:
                mock_parser = MagicMock()
                mock_parser.build_search_url = MagicMock(
                    return_value="https://duckduckgo.com/?q=test"
                )
                mock_get_parser.return_value = mock_parser
                
                response = await provider.search("test query")
                
                assert response.ok is False
                assert response.error == "Timeout"
        
        await provider.close()
    
    @pytest.mark.asyncio
    async def test_health_status_unknown_initially(self):
        """Test health status is unknown before any searches."""
        provider = BrowserSearchProvider()
        
        health = await provider.get_health()
        
        assert health.state == HealthState.UNKNOWN
        assert "No searches" in health.message
    
    @pytest.mark.asyncio
    async def test_health_status_healthy(self):
        """Test health status after successful searches."""
        provider = BrowserSearchProvider()
        
        # Simulate successful searches
        provider._success_count = 10
        provider._failure_count = 0
        provider._captcha_count = 0
        provider._total_latency = 5000.0
        
        health = await provider.get_health()
        
        assert health.state == HealthState.HEALTHY
        assert health.latency_ms == 500.0  # 5000/10
    
    @pytest.mark.asyncio
    async def test_health_status_degraded(self):
        """Test health status when degraded."""
        provider = BrowserSearchProvider()
        
        # Simulate mixed results
        provider._success_count = 6
        provider._failure_count = 4
        provider._captcha_count = 3
        provider._total_latency = 10000.0
        
        health = await provider.get_health()
        
        assert health.state == HealthState.DEGRADED
    
    @pytest.mark.asyncio
    async def test_health_status_unhealthy(self):
        """Test health status when unhealthy."""
        provider = BrowserSearchProvider()
        
        # Simulate mostly failures
        provider._success_count = 2
        provider._failure_count = 8
        provider._last_error = "Connection failed"
        
        health = await provider.get_health()
        
        assert health.state == HealthState.UNHEALTHY
    
    @pytest.mark.asyncio
    async def test_close_provider(self, mock_playwright, mock_browser, mock_context):
        """Test provider cleanup."""
        provider = BrowserSearchProvider()
        
        # Manually set browser state
        provider._playwright = mock_playwright
        provider._browser = mock_browser
        provider._context = mock_context
        provider._page = AsyncMock()
        provider._page.is_closed = MagicMock(return_value=False)
        provider._page.close = AsyncMock()
        
        await provider.close()
        
        assert provider._is_closed is True
        mock_playwright.stop.assert_called_once()
    
    def test_get_available_engines(self):
        """Test getting available engines list."""
        provider = BrowserSearchProvider()
        
        engines = provider.get_available_engines()
        
        assert isinstance(engines, list)
        assert len(engines) > 0
    
    def test_get_stats(self):
        """Test getting provider statistics."""
        provider = BrowserSearchProvider()
        
        provider._success_count = 5
        provider._failure_count = 2
        provider._captcha_count = 1
        provider._total_latency = 3500.0
        
        stats = provider.get_stats()
        
        assert stats["provider"] == "browser_search"
        assert stats["success_count"] == 5
        assert stats["failure_count"] == 2
        assert stats["captcha_count"] == 1
        assert stats["success_rate"] == 5 / 7
        assert stats["avg_latency_ms"] == 500.0
    
    def test_reset_metrics(self):
        """Test resetting metrics."""
        provider = BrowserSearchProvider()
        
        provider._success_count = 10
        provider._failure_count = 5
        provider._captcha_count = 2
        provider._total_latency = 5000.0
        provider._last_error = "Some error"
        
        provider.reset_metrics()
        
        assert provider._success_count == 0
        assert provider._failure_count == 0
        assert provider._captcha_count == 0
        assert provider._total_latency == 0.0
        assert provider._last_error is None


# ============================================================================
# Factory Function Tests
# ============================================================================


class TestFactoryFunctions:
    """Tests for factory functions."""
    
    def test_get_browser_search_provider_singleton(self):
        """Test singleton pattern for provider."""
        provider1 = get_browser_search_provider()
        provider2 = get_browser_search_provider()
        
        assert provider1 is provider2
    
    def test_reset_browser_search_provider(self):
        """Test provider reset."""
        provider1 = get_browser_search_provider()
        reset_browser_search_provider()
        provider2 = get_browser_search_provider()
        
        assert provider1 is not provider2


# ============================================================================
# SearchOptions Integration Tests
# ============================================================================


class TestSearchOptionsIntegration:
    """Tests for SearchOptions integration with provider."""
    
    @pytest.mark.asyncio
    async def test_search_with_options(
        self,
        mock_playwright,
        mock_parse_result,
    ):
        """Test search with custom options."""
        provider = BrowserSearchProvider()
        
        with patch(
            "playwright.async_api.async_playwright"
        ) as mock_async_pw:
            mock_async_pw.return_value.start = AsyncMock(
                return_value=mock_playwright
            )
            
            with patch(
                "src.search.browser_search_provider.get_parser"
            ) as mock_get_parser:
                mock_parser = MagicMock()
                mock_parser.build_search_url = MagicMock(
                    return_value="https://duckduckgo.com/?q=test"
                )
                mock_parser.parse = MagicMock(return_value=mock_parse_result)
                mock_get_parser.return_value = mock_parser
                
                options = SearchOptions(
                    engines=["duckduckgo"],
                    time_range="week",
                    limit=5,
                )
                
                response = await provider.search("test query", options)
                
                assert response.ok is True
                # Verify parser was called with correct engine
                mock_get_parser.assert_called_with("duckduckgo")
        
        await provider.close()
    
    @pytest.mark.asyncio
    async def test_search_limit_applied(
        self,
        mock_playwright,
    ):
        """Test result limit is applied."""
        provider = BrowserSearchProvider()
        
        # Create 10 results
        many_results = [
            ParsedResult(
                title=f"Result {i}",
                url=f"https://example.com/page{i}",
                snippet=f"Snippet {i}",
                rank=i,
            )
            for i in range(10)
        ]
        parse_result = ParseResult(ok=True, results=many_results)
        
        with patch(
            "playwright.async_api.async_playwright"
        ) as mock_async_pw:
            mock_async_pw.return_value.start = AsyncMock(
                return_value=mock_playwright
            )
            
            with patch(
                "src.search.browser_search_provider.get_parser"
            ) as mock_get_parser:
                mock_parser = MagicMock()
                mock_parser.build_search_url = MagicMock(
                    return_value="https://duckduckgo.com/?q=test"
                )
                mock_parser.parse = MagicMock(return_value=parse_result)
                mock_get_parser.return_value = mock_parser
                
                options = SearchOptions(limit=3)
                response = await provider.search("test query", options)
                
                assert response.ok is True
                assert len(response.results) == 3
                assert response.total_count == 10
        
        await provider.close()

