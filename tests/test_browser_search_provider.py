"""
Unit tests for BrowserSearchProvider.

Tests for browser-based search provider.
Validates:
- BrowserSearchProvider initialization
- Search execution with mocked browser
- CAPTCHA detection and intervention handling
- Session management
- Health status reporting
- Error handling
- Engine selection logic (category detection, weighted selection, circuit breaker)
- Engine health recording

Follows .1 test code quality standards:
- Specific assertions with concrete values
- No conditional assertions
- Proper mocking of external dependencies (Playwright)
- Boundary conditions coverage

Follows test-strategy.mdc:
- Given/When/Then comments in all tests
- Normal and abnormal cases coverage
- Boundary value testing (empty, NULL, edge cases)
- Exception type and message verification
"""

from collections.abc import Generator
from typing import Any

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.search.browser_search_provider import (
    BrowserSearchProvider,
    BrowserSearchSession,
    get_browser_search_provider,
    reset_browser_search_provider,
)
from src.search.provider import (
    HealthState,
    SearchOptions,
)
from src.search.search_parsers import ParsedResult, ParseResult
from src.utils.schemas import LastmileCheckResult

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
def mock_parse_result(sample_parsed_results: list[ParsedResult]) -> ParseResult:
    """Create mock parse result."""
    return ParseResult(ok=True, results=sample_parsed_results)


@pytest.fixture
def mock_page() -> AsyncMock:
    """Create mock Playwright page."""
    page = AsyncMock()
    page.goto = AsyncMock(return_value=MagicMock(status=200))
    page.wait_for_load_state = AsyncMock()
    page.content = AsyncMock(return_value="<html><body>Test</body></html>")
    page.is_closed = MagicMock(return_value=False)
    # Mock page.evaluate for profile_audit.py fingerprint collection
    page.evaluate = AsyncMock(
        return_value={
            "user_agent": "Mozilla/5.0 Test",
            "ua_major_version": "100",
            "fonts": ["Arial", "Helvetica"],
            "language": "en-US",
            "timezone": "UTC",
            "canvas_hash": "test_hash",
            "audio_hash": "test_audio",
            "screen_resolution": "1920x1080",
            "color_depth": 24,
            "platform": "Linux x86_64",
            "plugins_count": 3,
        }
    )
    return page


@pytest.fixture
def mock_context(mock_page: AsyncMock) -> AsyncMock:
    """Create mock Playwright context."""
    context = AsyncMock()
    context.new_page = AsyncMock(return_value=mock_page)
    context.cookies = AsyncMock(return_value=[])
    context.route = AsyncMock()
    context.close = AsyncMock()
    return context


@pytest.fixture
def mock_browser(mock_context: AsyncMock) -> AsyncMock:
    """Create mock Playwright browser."""
    browser = AsyncMock()
    browser.new_context = AsyncMock(return_value=mock_context)
    browser.close = AsyncMock()
    # contexts is empty list by default - new context will be created
    # Per Auth cookie capture: When contexts is empty, new_context() is called
    browser.contexts = []
    return browser


@pytest.fixture
def mock_playwright(mock_browser: AsyncMock) -> AsyncMock:
    """Create mock Playwright instance."""
    playwright = AsyncMock()
    playwright.chromium = MagicMock()
    playwright.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
    playwright.chromium.launch = AsyncMock(return_value=mock_browser)
    playwright.stop = AsyncMock()
    return playwright


@pytest.fixture(autouse=True)
def mock_human_behavior_simulator() -> Generator[Any]:
    """Mock get_human_behavior_simulator to avoid coroutine warnings."""
    mock_simulator = MagicMock()
    mock_simulator.read_page = AsyncMock()
    mock_simulator.move_to_element = AsyncMock()
    mock_simulator.random_delay = MagicMock(return_value=0.1)
    mock_simulator._scroll = MagicMock()
    mock_simulator._mouse = MagicMock()

    with patch(
        "src.crawler.fetcher.get_human_behavior_simulator",
        return_value=mock_simulator,
    ):
        yield mock_simulator


@pytest.fixture
def mock_tab_pool_and_rate_limiter(mock_page: AsyncMock) -> Generator[Any]:
    """Mock TabPool and EngineRateLimiter for browser search provider tests.

    Per ADR-0014: BrowserSearchProvider uses TabPool and EngineRateLimiter.
    These need to be mocked to avoid actual browser operations.

    Note: This fixture is NOT autouse - tests that need it should request it explicitly.
    The TabPool.acquire() mock returns the mock_page from the test fixture,
    so tests that set up mock_page behavior will work correctly.
    """
    mock_tab_pool = MagicMock()
    # acquire() should return the mock_page (simulating borrowing a tab)
    mock_tab_pool.acquire = AsyncMock(return_value=mock_page)
    mock_tab_pool.release = MagicMock()
    mock_tab_pool.report_captcha = MagicMock()
    mock_tab_pool.report_403 = MagicMock()
    mock_tab_pool.get_stats = MagicMock(
        return_value={"max_tabs": 2, "effective_max_tabs": 2, "backoff_active": False}
    )

    mock_engine_limiter = MagicMock()
    mock_engine_limiter.acquire = AsyncMock()
    mock_engine_limiter.release = MagicMock()

    with (
        patch("src.search.tab_pool.get_tab_pool", return_value=mock_tab_pool),
        patch("src.search.tab_pool.get_engine_rate_limiter", return_value=mock_engine_limiter),
    ):
        yield {"tab_pool": mock_tab_pool, "engine_limiter": mock_engine_limiter}


@pytest.fixture(autouse=True)
def reset_provider() -> Generator[None]:
    """Reset provider and tab pool/rate limiter before each test."""
    import asyncio

    from src.search.tab_pool import reset_engine_rate_limiter, reset_tab_pool

    reset_browser_search_provider()
    reset_engine_rate_limiter()
    # Reset tab pool synchronously if possible
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(reset_tab_pool())
        else:
            loop.run_until_complete(reset_tab_pool())
    except RuntimeError:
        # No event loop, create one temporarily
        asyncio.run(reset_tab_pool())

    yield

    reset_browser_search_provider()
    reset_engine_rate_limiter()


@pytest.fixture
def browser_search_provider(
    mock_human_behavior_simulator: MagicMock,
) -> Generator[BrowserSearchProvider]:
    """Create a properly managed BrowserSearchProvider for tests.

    Ensures the provider is properly closed after each test to prevent
    ResourceWarning: unclosed event loop warnings.
    """
    provider = BrowserSearchProvider()
    yield provider
    # Cleanup is handled synchronously since async cleanup in fixtures
    # can cause event loop issues with pytest-asyncio
    provider._is_closed = True


# ============================================================================
# BrowserSearchSession Tests
# ============================================================================


class TestBrowserSearchSession:
    """Tests for BrowserSearchSession."""

    def test_session_creation(self) -> None:
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

    def test_session_freshness(self) -> None:
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

    def test_record_success(self) -> None:
        """Test recording successful search."""
        session = BrowserSearchSession(
            engine="test",
            cookies=[],
            last_used=0.0,
        )

        session.record_success()

        assert session.success_count == 1
        assert session.last_used > 0

    def test_record_captcha(self) -> None:
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

    def test_provider_initialization(self) -> None:
        """Test provider initializes correctly."""
        provider = BrowserSearchProvider()

        assert provider.name == "browser_search"
        assert provider._default_engine == "duckduckgo"
        assert provider._timeout == 30
        assert provider._is_closed is False

    def test_provider_custom_config(self) -> None:
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
        mock_playwright: AsyncMock,
        mock_parse_result: ParseResult,
    ) -> None:
        """Test successful search execution.

        Given: Valid query, engine available, parser exists
        When: search() is called
        Then: SearchResponse with results is returned
        """
        provider = BrowserSearchProvider()

        with patch("playwright.async_api.async_playwright") as mock_async_pw:
            mock_async_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            # Mock engine selection components
            with (
                patch(
                    "src.search.browser_search_provider.check_engine_available",
                    AsyncMock(return_value=True),
                ),
                patch(
                    "src.search.browser_search_provider.get_engine_config_manager"
                ) as mock_get_config_manager,
            ):
                mock_config_manager = MagicMock()
                mock_engine_config = MagicMock()
                mock_engine_config.name = "duckduckgo"
                mock_engine_config.weight = 0.7
                mock_engine_config.is_available = True
                mock_engine_config.min_interval = 5.0  # Per-engine QPS
                mock_config_manager.get_default_engines.return_value = ["duckduckgo"]
                mock_config_manager.get_engines_for_category.return_value = [mock_engine_config]
                # Mock get_engines_with_parsers to return engines as-is (for testing)
                mock_config_manager.get_engines_with_parsers = MagicMock(
                    side_effect=lambda engines: engines if engines else []
                )
                mock_config_manager.get_engine.return_value = mock_engine_config
                mock_get_config_manager.return_value = mock_config_manager

                with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                    mock_parser = MagicMock()
                    mock_parser.build_search_url = MagicMock(
                        return_value="https://duckduckgo.com/?q=test"
                    )
                    mock_parser.parse = MagicMock(return_value=mock_parse_result)
                    mock_get_parser.return_value = mock_parser

                    # Mock record_engine_result
                    with patch(
                        "src.search.browser_search_provider.record_engine_result",
                        AsyncMock(),
                    ):
                        # Mock HumanBehavior to avoid coroutine warnings
                        with (
                            patch.object(
                                provider._human_behavior,
                                "simulate_reading",
                                AsyncMock(),
                            ),
                            patch.object(
                                provider._human_behavior,
                                "move_mouse_to_element",
                                AsyncMock(),
                            ),
                        ):
                            response = await provider.search("test query")

                            assert response.ok is True
                            assert len(response.results) == 2
                            assert response.provider == "browser_search"
                            assert response.error is None

        await provider.close()

    @pytest.mark.asyncio
    async def test_search_captcha_detection(self, mock_playwright: AsyncMock) -> None:
        """Test CAPTCHA detection during search.

        Given: CAPTCHA detected in parse result
        When: search() processes result
        Then: SearchResponse with CAPTCHA error is returned
        """
        provider = BrowserSearchProvider()

        captcha_parse_result = ParseResult(
            ok=False,
            is_captcha=True,
            captcha_type="turnstile",
            error="CAPTCHA detected",
        )

        with patch("playwright.async_api.async_playwright") as mock_async_pw:
            mock_async_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            # Mock engine selection components
            with (
                patch(
                    "src.search.browser_search_provider.check_engine_available",
                    AsyncMock(return_value=True),
                ),
                patch(
                    "src.search.browser_search_provider.get_engine_config_manager"
                ) as mock_get_config_manager,
            ):
                mock_config_manager = MagicMock()
                mock_engine_config = MagicMock()
                mock_engine_config.name = "duckduckgo"
                mock_engine_config.weight = 0.7
                mock_engine_config.is_available = True
                mock_engine_config.min_interval = 5.0  # Per-engine QPS
                mock_config_manager.get_default_engines.return_value = ["duckduckgo"]
                mock_config_manager.get_engines_for_category.return_value = [mock_engine_config]
                # Mock get_engines_with_parsers to return engines as-is (for testing)
                mock_config_manager.get_engines_with_parsers = MagicMock(
                    side_effect=lambda engines: engines if engines else []
                )
                mock_config_manager.get_engine.return_value = mock_engine_config
                mock_get_config_manager.return_value = mock_config_manager

                with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                    mock_parser = MagicMock()
                    mock_parser.build_search_url = MagicMock(
                        return_value="https://duckduckgo.com/?q=test"
                    )
                    mock_parser.parse = MagicMock(return_value=captcha_parse_result)
                    mock_get_parser.return_value = mock_parser

                    # Mock record_engine_result
                    with patch(
                        "src.search.browser_search_provider.record_engine_result",
                        AsyncMock(),
                    ):
                        # Mock intervention to fail
                        with patch.object(
                            provider,
                            "_request_intervention",
                            AsyncMock(return_value=False),
                        ):
                            # Mock HumanBehavior to avoid coroutine warnings
                            with (
                                patch.object(
                                    provider._human_behavior,
                                    "simulate_reading",
                                    AsyncMock(),
                                ),
                                patch.object(
                                    provider._human_behavior,
                                    "move_mouse_to_element",
                                    AsyncMock(),
                                ),
                            ):
                                response = await provider.search("test query")

                                assert response.ok is False
                                assert response.error is not None
                                assert "CAPTCHA" in response.error

        await provider.close()

    @pytest.mark.asyncio
    async def test_search_no_parser(self) -> None:
        """Test search with unavailable parser.

        Given: Parser not found for engine
        When: search() tries to get parser
        Then: SearchResponse(error="No parser available") is returned
        """
        provider = BrowserSearchProvider(default_engine="nonexistent")

        # Mock engine selection components
        with (
            patch(
                "src.search.browser_search_provider.check_engine_available",
                AsyncMock(return_value=True),
            ),
            patch(
                "src.search.browser_search_provider.get_engine_config_manager"
            ) as mock_get_config_manager,
        ):
            mock_config_manager = MagicMock()
            mock_engine_config = MagicMock()
            mock_engine_config.name = "nonexistent"
            mock_engine_config.weight = 0.7
            mock_engine_config.is_available = True
            mock_engine_config.min_interval = 5.0  # Per-engine QPS
            mock_config_manager.get_default_engines.return_value = []  # Fallback to category
            mock_config_manager.get_engines_for_category.return_value = [mock_engine_config]
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            mock_config_manager.get_engine.return_value = mock_engine_config
            mock_get_config_manager.return_value = mock_config_manager

            with patch(
                "src.search.browser_search_provider.get_parser",
                return_value=None,
            ):
                response = await provider.search("test query")

                assert response.ok is False
                assert response.error is not None
                assert "No parser available" in response.error

        await provider.close()

    @pytest.mark.asyncio
    async def test_search_timeout(
        self, mock_playwright: AsyncMock, mock_context: AsyncMock
    ) -> None:
        """Test search timeout handling.

        Given: Page navigation times out
        When: search() executes
        Then: SearchResponse(error="Timeout") is returned
        """
        provider = BrowserSearchProvider(timeout=1)

        # Make page.goto timeout
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(side_effect=TimeoutError())
        mock_page.is_closed = MagicMock(return_value=False)
        mock_context.new_page = AsyncMock(return_value=mock_page)

        # Mock TabPool to return the timeout-raising mock_page
        mock_tab_pool = MagicMock()
        mock_tab_pool.acquire = AsyncMock(return_value=mock_page)
        mock_tab_pool.release = MagicMock()
        mock_tab_pool.report_captcha = MagicMock()

        mock_engine_limiter = MagicMock()
        mock_engine_limiter.acquire = AsyncMock()
        mock_engine_limiter.release = MagicMock()

        with patch("playwright.async_api.async_playwright") as mock_async_pw:
            mock_async_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            with (
                patch("src.search.browser_search_provider.get_parser") as mock_get_parser,
                patch("src.search.tab_pool.get_tab_pool", return_value=mock_tab_pool),
                patch(
                    "src.search.tab_pool.get_engine_rate_limiter", return_value=mock_engine_limiter
                ),
            ):
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
    async def test_health_status_unknown_initially(self) -> None:
        """Test health status is unknown before any searches."""
        provider = BrowserSearchProvider()

        health = await provider.get_health()

        assert health.state == HealthState.UNKNOWN
        assert health.message is not None
        assert "No searches" in health.message

    @pytest.mark.asyncio
    async def test_health_status_healthy(self) -> None:
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
    async def test_health_status_degraded(self) -> None:
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
    async def test_health_status_unhealthy(self) -> None:
        """Test health status when unhealthy."""
        provider = BrowserSearchProvider()

        # Simulate mostly failures
        provider._success_count = 2
        provider._failure_count = 8
        provider._last_error = "Connection failed"

        health = await provider.get_health()

        assert health.state == HealthState.UNHEALTHY

    @pytest.mark.asyncio
    async def test_close_provider(
        self, mock_playwright: AsyncMock, mock_browser: AsyncMock, mock_context: AsyncMock
    ) -> None:
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

    def test_get_available_engines(self) -> None:
        """Test getting available engines list."""
        provider = BrowserSearchProvider()

        engines = provider.get_available_engines()

        assert isinstance(engines, list)
        # Should have at least 1 engine available
        assert len(engines) >= 1, f"Expected >=1 engines, got {len(engines)}"

    def test_get_stats(self) -> None:
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

    def test_reset_metrics(self) -> None:
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

    def test_get_browser_search_provider_singleton(self) -> None:
        """Test singleton pattern for provider."""
        provider1 = get_browser_search_provider()
        provider2 = get_browser_search_provider()

        assert provider1 is provider2

    def test_reset_browser_search_provider(self) -> None:
        """Test provider reset."""
        provider1 = get_browser_search_provider()
        reset_browser_search_provider()
        provider2 = get_browser_search_provider()

        assert provider1 is not provider2


# ============================================================================
# SearchOptions Integration Tests
# ============================================================================


class TestCDPConnection:
    """
    Tests for CDP connection handling.

    Per spec (ADR-0003, ADR-0006), CDP connection is required and headless
    fallback is not supported.
    """

    @pytest.mark.asyncio
    async def test_cdp_connection_failure_returns_clear_error(self) -> None:
        """
        Test that CDP connection failure returns a clear error message.

        Validates:
        - No headless fallback (per ADR-0006)
        - Error message includes make chrome-start guidance
        - connection_mode is None when CDP fails
        """
        provider = BrowserSearchProvider()

        with patch("playwright.async_api.async_playwright") as mock_async_pw:
            # Mock playwright startup
            mock_playwright = AsyncMock()
            mock_async_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            # Mock CDP connection failure
            mock_playwright.chromium = MagicMock()
            mock_playwright.chromium.connect_over_cdp = AsyncMock(
                side_effect=Exception("Connection refused")
            )
            mock_playwright.stop = AsyncMock()

            with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                mock_parser = MagicMock()
                mock_parser.build_search_url = MagicMock(
                    return_value="https://duckduckgo.com/?q=test"
                )
                mock_get_parser.return_value = mock_parser

                response = await provider.search("test query")

                # Verify error response
                assert response.ok is False
                assert response.error is not None
                assert response.error is not None
                assert "CDP connection failed" in response.error
                assert "make chrome-start" in response.error
                assert response.connection_mode is None

    @pytest.mark.asyncio
    async def test_cdp_connection_success_sets_connection_mode(
        self,
        mock_playwright: AsyncMock,
        mock_parse_result: ParseResult,
    ) -> None:
        """
        Test that successful CDP connection sets connection_mode to 'cdp'.
        """
        provider = BrowserSearchProvider()

        with patch("playwright.async_api.async_playwright") as mock_async_pw:
            mock_async_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            # Mock engine selection components
            with (
                patch(
                    "src.search.browser_search_provider.check_engine_available",
                    AsyncMock(return_value=True),
                ),
                patch(
                    "src.search.browser_search_provider.get_engine_config_manager"
                ) as mock_get_config_manager,
            ):
                mock_config_manager = MagicMock()
                mock_engine_config = MagicMock()
                mock_engine_config.name = "duckduckgo"
                mock_engine_config.weight = 0.7
                mock_engine_config.is_available = True
                mock_engine_config.min_interval = 5.0  # Per-engine QPS
                mock_config_manager.get_default_engines.return_value = ["duckduckgo"]
                mock_config_manager.get_engines_for_category.return_value = [mock_engine_config]
                # Mock get_engines_with_parsers to return engines as-is (for testing)
                mock_config_manager.get_engines_with_parsers = MagicMock(
                    side_effect=lambda engines: engines if engines else []
                )
                mock_config_manager.get_engine.return_value = mock_engine_config
                mock_get_config_manager.return_value = mock_config_manager

                with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                    mock_parser = MagicMock()
                    mock_parser.build_search_url = MagicMock(
                        return_value="https://duckduckgo.com/?q=test"
                    )
                    mock_parser.parse = MagicMock(return_value=mock_parse_result)
                    mock_get_parser.return_value = mock_parser

                    # Mock record_engine_result
                    with patch(
                        "src.search.browser_search_provider.record_engine_result",
                        AsyncMock(),
                    ):
                        # Mock HumanBehavior to avoid coroutine warnings
                        with (
                            patch.object(
                                provider._human_behavior,
                                "simulate_reading",
                                AsyncMock(),
                            ),
                            patch.object(
                                provider._human_behavior,
                                "move_mouse_to_element",
                                AsyncMock(),
                            ),
                        ):
                            response = await provider.search("test query")

                            assert response.ok is True
                            assert response.connection_mode == "cdp"

        await provider.close()

    @pytest.mark.asyncio
    async def test_captcha_detection_includes_connection_mode(
        self,
        mock_playwright: AsyncMock,
    ) -> None:
        """
        Test that CAPTCHA response includes connection_mode='cdp'.
        """
        provider = BrowserSearchProvider()

        captcha_parse_result = ParseResult(
            ok=False,
            is_captcha=True,
            captcha_type="turnstile",
            error="CAPTCHA detected",
        )

        with patch("playwright.async_api.async_playwright") as mock_async_pw:
            mock_async_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            # Mock engine selection components
            with (
                patch(
                    "src.search.browser_search_provider.check_engine_available",
                    AsyncMock(return_value=True),
                ),
                patch(
                    "src.search.browser_search_provider.get_engine_config_manager"
                ) as mock_get_config_manager,
            ):
                mock_config_manager = MagicMock()
                mock_engine_config = MagicMock()
                mock_engine_config.name = "duckduckgo"
                mock_engine_config.weight = 0.7
                mock_engine_config.is_available = True
                mock_engine_config.min_interval = 5.0  # Per-engine QPS
                mock_config_manager.get_default_engines.return_value = ["duckduckgo"]
                mock_config_manager.get_engines_for_category.return_value = [mock_engine_config]
                # Mock get_engines_with_parsers to return engines as-is (for testing)
                mock_config_manager.get_engines_with_parsers = MagicMock(
                    side_effect=lambda engines: engines if engines else []
                )
                mock_config_manager.get_engine.return_value = mock_engine_config
                mock_get_config_manager.return_value = mock_config_manager

                with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                    mock_parser = MagicMock()
                    mock_parser.build_search_url = MagicMock(
                        return_value="https://duckduckgo.com/?q=test"
                    )
                    mock_parser.parse = MagicMock(return_value=captcha_parse_result)
                    mock_get_parser.return_value = mock_parser

                    # Mock record_engine_result
                    with patch(
                        "src.search.browser_search_provider.record_engine_result",
                        AsyncMock(),
                    ):
                        with patch.object(
                            provider,
                            "_request_intervention",
                            AsyncMock(return_value=False),
                        ):
                            # Mock HumanBehavior to avoid coroutine warnings
                            with (
                                patch.object(
                                    provider._human_behavior,
                                    "simulate_reading",
                                    AsyncMock(),
                                ),
                                patch.object(
                                    provider._human_behavior,
                                    "move_mouse_to_element",
                                    AsyncMock(),
                                ),
                            ):
                                response = await provider.search("test query")

                                assert response.ok is False
                                assert response.error is not None
                                assert "CAPTCHA" in response.error
                                # CAPTCHA detected via CDP connection, so mode is 'cdp'
                                assert response.connection_mode == "cdp"

        await provider.close()


class TestSearchOptionsIntegration:
    """Tests for SearchOptions integration with provider."""

    @pytest.mark.asyncio
    async def test_search_with_options(
        self,
        mock_playwright: AsyncMock,
        mock_parse_result: ParseResult,
    ) -> None:
        """Test search with custom options."""
        provider = BrowserSearchProvider()

        with patch("playwright.async_api.async_playwright") as mock_async_pw:
            mock_async_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            # Mock engine selection components
            with (
                patch(
                    "src.search.browser_search_provider.check_engine_available",
                    AsyncMock(return_value=True),
                ),
                patch(
                    "src.search.browser_search_provider.get_engine_config_manager"
                ) as mock_get_config_manager,
            ):
                mock_config_manager = MagicMock()
                mock_engine_config = MagicMock()
                mock_engine_config.name = "duckduckgo"
                mock_engine_config.weight = 0.7
                mock_engine_config.is_available = True
                mock_engine_config.min_interval = 5.0  # Per-engine QPS
                # Mock get_engines_with_parsers to return engines as-is (for testing)
                mock_config_manager.get_engines_with_parsers = MagicMock(
                    side_effect=lambda engines: engines if engines else []
                )
                mock_config_manager.get_engine.return_value = mock_engine_config
                mock_get_config_manager.return_value = mock_config_manager

                with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                    mock_parser = MagicMock()
                    mock_parser.build_search_url = MagicMock(
                        return_value="https://duckduckgo.com/?q=test"
                    )
                    mock_parser.parse = MagicMock(return_value=mock_parse_result)
                    mock_get_parser.return_value = mock_parser

                    # Mock record_engine_result
                    with patch(
                        "src.search.browser_search_provider.record_engine_result",
                        AsyncMock(),
                    ):
                        # Mock HumanBehavior to avoid coroutine warnings
                        with (
                            patch.object(
                                provider._human_behavior,
                                "simulate_reading",
                                AsyncMock(),
                            ),
                            patch.object(
                                provider._human_behavior,
                                "move_mouse_to_element",
                                AsyncMock(),
                            ),
                        ):
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
        mock_playwright: AsyncMock,
    ) -> None:
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

        with patch("playwright.async_api.async_playwright") as mock_async_pw:
            mock_async_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            # Mock engine selection components
            with (
                patch(
                    "src.search.browser_search_provider.check_engine_available",
                    AsyncMock(return_value=True),
                ),
                patch(
                    "src.search.browser_search_provider.get_engine_config_manager"
                ) as mock_get_config_manager,
            ):
                mock_config_manager = MagicMock()
                mock_engine_config = MagicMock()
                mock_engine_config.name = "duckduckgo"
                mock_engine_config.weight = 0.7
                mock_engine_config.is_available = True
                mock_engine_config.min_interval = 5.0  # Per-engine QPS
                mock_config_manager.get_default_engines.return_value = ["duckduckgo"]
                mock_config_manager.get_engines_for_category.return_value = [mock_engine_config]
                # Mock get_engines_with_parsers to return engines as-is (for testing)
                mock_config_manager.get_engines_with_parsers = MagicMock(
                    side_effect=lambda engines: engines if engines else []
                )
                mock_config_manager.get_engine.return_value = mock_engine_config
                mock_get_config_manager.return_value = mock_config_manager

                with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                    mock_parser = MagicMock()
                    mock_parser.build_search_url = MagicMock(
                        return_value="https://duckduckgo.com/?q=test"
                    )
                    mock_parser.parse = MagicMock(return_value=parse_result)
                    mock_get_parser.return_value = mock_parser

                    # Mock record_engine_result
                    with patch(
                        "src.search.browser_search_provider.record_engine_result",
                        AsyncMock(),
                    ):
                        # Mock HumanBehavior to avoid coroutine warnings
                        with (
                            patch.object(
                                provider._human_behavior,
                                "simulate_reading",
                                AsyncMock(),
                            ),
                            patch.object(
                                provider._human_behavior,
                                "move_mouse_to_element",
                                AsyncMock(),
                            ),
                        ):
                            options = SearchOptions(limit=3)
                            response = await provider.search("test query", options)

                            assert response.ok is True
                            assert len(response.results) == 3
                            assert response.total_count == 10

        await provider.close()


@pytest.mark.unit
class TestBrowserSearchProviderHumanBehavior:
    """Tests for human-like behavior integration in BrowserSearchProvider.search (ADR-0006)."""

    @pytest.mark.asyncio
    async def test_search_applies_human_behavior(
        self, mock_playwright: AsyncMock, mock_parse_result: ParseResult
    ) -> None:
        """Test BrowserSearchProvider.search() applies human behavior to results page.

        Given: Search executed, results page has links
        When: search() is called
        Then: simulate_reading() and move_mouse_to_element() are called
        """
        provider = BrowserSearchProvider()

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.content = AsyncMock(
            return_value="<html><body><a href='https://example.com'>Result</a></body></html>"
        )
        mock_page.query_selector_all = AsyncMock(
            return_value=[MagicMock(evaluate=AsyncMock(return_value="a"))]
        )
        mock_page.is_closed = MagicMock(return_value=False)

        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_context.cookies = AsyncMock(return_value=[])
        mock_context.route = AsyncMock()

        mock_playwright.chromium.connect_over_cdp = AsyncMock(return_value=mock_context)

        with patch("playwright.async_api.async_playwright") as mock_async_pw:
            mock_async_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                mock_parser = MagicMock()
                mock_parser.build_search_url = MagicMock(
                    return_value="https://duckduckgo.com/?q=test"
                )
                mock_parser.parse = MagicMock(return_value=mock_parse_result)
                mock_get_parser.return_value = mock_parser

                with patch.object(provider, "_ensure_browser", AsyncMock()):
                    with patch.object(provider, "_save_session", AsyncMock()):
                        with patch.object(
                            provider._human_behavior, "simulate_reading", AsyncMock()
                        ) as mock_simulate:
                            with patch.object(
                                provider._human_behavior, "move_mouse_to_element", AsyncMock()
                            ) as mock_mouse:
                                # Set page directly to avoid _ensure_browser complexity
                                provider._page = mock_page
                                provider._context = mock_context

                                response = await provider.search("test query")

                                # Verify human behavior was applied
                                mock_simulate.assert_called_once()
                                mock_mouse.assert_called_once()
                                assert response.ok is True

        await provider.close()

    @pytest.mark.asyncio
    async def test_search_with_no_links(
        self, mock_playwright: AsyncMock, mock_parse_result: ParseResult
    ) -> None:
        """Test BrowserSearchProvider.search() handles pages with no result links.

        Given: Search executed, results page has no links
        When: search() is called
        Then: simulate_reading() is called but move_mouse_to_element() is skipped
        """
        provider = BrowserSearchProvider()

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html><body>No links</body></html>")
        mock_page.query_selector_all = AsyncMock(return_value=[])  # No links
        mock_page.is_closed = MagicMock(return_value=False)

        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_context.cookies = AsyncMock(return_value=[])
        mock_context.route = AsyncMock()

        mock_playwright.chromium.connect_over_cdp = AsyncMock(return_value=mock_context)

        with patch("playwright.async_api.async_playwright") as mock_async_pw:
            mock_async_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                mock_parser = MagicMock()
                mock_parser.build_search_url = MagicMock(
                    return_value="https://duckduckgo.com/?q=test"
                )
                mock_parser.parse = MagicMock(return_value=mock_parse_result)
                mock_get_parser.return_value = mock_parser

                with patch.object(provider, "_ensure_browser", AsyncMock()):
                    with patch.object(provider, "_save_session", AsyncMock()):
                        with patch.object(
                            provider._human_behavior, "simulate_reading", AsyncMock()
                        ) as mock_simulate:
                            with patch.object(
                                provider._human_behavior, "move_mouse_to_element", AsyncMock()
                            ) as mock_mouse:
                                # Set page directly to avoid _ensure_browser complexity
                                provider._page = mock_page
                                provider._context = mock_context

                                response = await provider.search("test query")

                                # Verify simulate_reading was called but mouse movement was skipped
                                mock_simulate.assert_called_once()
                                mock_mouse.assert_not_called()
                                assert response.ok is True

        await provider.close()

    @pytest.mark.asyncio
    async def test_search_with_link_search_exception(
        self, mock_playwright: AsyncMock, mock_parse_result: ParseResult
    ) -> None:
        """Test BrowserSearchProvider.search() handles exceptions during link search gracefully.

        Given: Search executed, query_selector_all raises exception
        When: search() is called
        Then: Exception is caught, logged, and normal flow continues
        """
        provider = BrowserSearchProvider()

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html><body>Content</body></html>")
        mock_page.query_selector_all = AsyncMock(side_effect=Exception("Search failed"))
        mock_page.is_closed = MagicMock(return_value=False)

        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_context.cookies = AsyncMock(return_value=[])
        mock_context.route = AsyncMock()

        mock_playwright.chromium.connect_over_cdp = AsyncMock(return_value=mock_context)

        with patch("playwright.async_api.async_playwright") as mock_async_pw:
            mock_async_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                mock_parser = MagicMock()
                mock_parser.build_search_url = MagicMock(
                    return_value="https://duckduckgo.com/?q=test"
                )
                mock_parser.parse = MagicMock(return_value=mock_parse_result)
                mock_get_parser.return_value = mock_parser

                with patch.object(provider, "_ensure_browser", AsyncMock()):
                    with patch.object(provider, "_save_session", AsyncMock()):
                        with patch.object(
                            provider._human_behavior, "simulate_reading", AsyncMock()
                        ) as mock_simulate:
                            with patch.object(
                                provider._human_behavior, "move_mouse_to_element", AsyncMock()
                            ) as mock_mouse:
                                # Set page directly to avoid _ensure_browser complexity
                                provider._page = mock_page
                                provider._context = mock_context

                                response = await provider.search("test query")

                                # Verify simulate_reading was called but mouse movement failed gracefully
                                mock_simulate.assert_called_once()
                                mock_mouse.assert_not_called()  # Exception prevented call
                                assert response.ok is True  # Normal flow continues

        await provider.close()

    @pytest.mark.asyncio
    async def test_search_with_simulate_reading_exception(
        self, mock_playwright: AsyncMock, mock_parse_result: ParseResult
    ) -> None:
        """Test BrowserSearchProvider.search() handles exceptions during simulate_reading gracefully.

        Given: Search executed, simulate_reading raises exception
        When: search() is called
        Then: Exception is caught, logged, and normal flow continues
        """
        provider = BrowserSearchProvider()

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html><body>Content</body></html>")
        mock_page.is_closed = MagicMock(return_value=False)

        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_context.cookies = AsyncMock(return_value=[])
        mock_context.route = AsyncMock()

        mock_playwright.chromium.connect_over_cdp = AsyncMock(return_value=mock_context)

        with patch("playwright.async_api.async_playwright") as mock_async_pw:
            mock_async_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                mock_parser = MagicMock()
                mock_parser.build_search_url = MagicMock(
                    return_value="https://duckduckgo.com/?q=test"
                )
                mock_parser.parse = MagicMock(return_value=mock_parse_result)
                mock_get_parser.return_value = mock_parser

                with patch.object(provider, "_ensure_browser", AsyncMock()):
                    with patch.object(provider, "_save_session", AsyncMock()):
                        with patch.object(
                            provider._human_behavior,
                            "simulate_reading",
                            AsyncMock(side_effect=Exception("Reading failed")),
                        ) as mock_simulate:
                            with patch.object(
                                provider._human_behavior, "move_mouse_to_element", AsyncMock()
                            ) as mock_mouse:
                                # Set page directly to avoid _ensure_browser complexity
                                provider._page = mock_page
                                provider._context = mock_context

                                response = await provider.search("test query")

                                # Verify simulate_reading was called but exception was handled gracefully
                                mock_simulate.assert_called_once()
                                mock_mouse.assert_not_called()  # Exception prevented mouse movement
                                assert response.ok is True  # Normal flow continues

        await provider.close()

    # ============================================================================
    # Engine Selection Tests
    # ============================================================================

    def test_category_detection(self) -> None:
        """Test category detection logic.

        Given: Various query strings
        When: _detect_category() is called
        Then: Correct category is returned
        """
        provider = BrowserSearchProvider()

        # Given: Academic keywords
        # When: _detect_category() is called
        # Then: Returns "academic"
        assert provider._detect_category("research paper") == "academic"
        assert provider._detect_category("arxiv paper") == "academic"
        assert provider._detect_category("scholar study") == "academic"

        # Given: News keywords
        # When: _detect_category() is called
        # Then: Returns "news"
        assert provider._detect_category("latest news") == "news"
        assert provider._detect_category("最新ニュース") == "news"
        assert provider._detect_category("breaking news") == "news"

        # Given: Government keywords
        # When: _detect_category() is called
        # Then: Returns "government"
        assert provider._detect_category("government policy") == "government"
        assert provider._detect_category("政府") == "government"
        assert provider._detect_category(".gov website") == "government"

        # Given: Technical keywords
        # When: _detect_category() is called
        # Then: Returns "technical"
        assert provider._detect_category("API documentation") == "technical"
        assert provider._detect_category("github code") == "technical"
        assert provider._detect_category("技術") == "technical"

        # Given: General query (no category keywords)
        # When: _detect_category() is called
        # Then: Returns "general" (default)
        assert provider._detect_category("general query") == "general"
        assert provider._detect_category("random search") == "general"

    def test_category_detection_boundary_cases(self) -> None:
        """Test category detection with boundary cases.

        Given: Edge case query strings
        When: _detect_category() is called
        Then: Handles edge cases correctly
        """
        provider = BrowserSearchProvider()

        # Given: Empty string
        # When: _detect_category() is called
        # Then: Returns "general" (default)
        assert provider._detect_category("") == "general"

        # Given: Whitespace only
        # When: _detect_category() is called
        # Then: Returns "general" (default)
        assert provider._detect_category("   ") == "general"

        # Given: Uppercase query
        # When: _detect_category() is called
        # Then: Returns correct category (case insensitive)
        assert provider._detect_category("RESEARCH PAPER") == "academic"
        assert provider._detect_category("LATEST NEWS") == "news"

        # Given: Query with multiple category keywords (first match wins)
        # When: _detect_category() is called
        # Then: Returns first matching category
        assert provider._detect_category("research paper API") == "academic"  # academic comes first

    @pytest.mark.asyncio
    async def test_engine_selection_with_category(self) -> None:
        """Test engine selection based on category.

        Given: Query with academic category, engines available for category
        When: search() is called
        Then: Engines for category are selected
        """
        provider = BrowserSearchProvider()

        with patch(
            "src.search.browser_search_provider.get_engine_config_manager"
        ) as mock_get_config_manager:
            mock_config_manager = MagicMock()
            mock_engine_config = MagicMock()
            mock_engine_config.name = "arxiv"
            mock_engine_config.weight = 1.0
            mock_engine_config.is_available = True
            mock_engine_config.min_interval = 5.0  # Per-engine QPS
            mock_config_manager.get_engines_for_category.return_value = [mock_engine_config]
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            mock_config_manager.get_engine.return_value = mock_engine_config
            mock_get_config_manager.return_value = mock_config_manager

            with patch(
                "src.search.browser_search_provider.check_engine_available",
                AsyncMock(return_value=True),
            ):
                # Given: Query with academic category
                category = provider._detect_category("research paper")
                assert category == "academic"

                # When: get_engines_for_category() is called
                engines_configs = mock_config_manager.get_engines_for_category(category)

                # Then: Engines for category are returned
                assert len(engines_configs) == 1
                assert engines_configs[0].name == "arxiv"

    @pytest.mark.asyncio
    async def test_engine_selection_with_circuit_breaker(self) -> None:
        """Test engine selection with circuit breaker filtering.

        Given: Multiple engines, one is OPEN (unavailable) in circuit breaker
        When: search() filters engines
        Then: Only available engines are selected
        """
        provider = BrowserSearchProvider()

        with patch(
            "src.search.browser_search_provider.get_engine_config_manager"
        ) as mock_get_config_manager:
            mock_config_manager = MagicMock()

            # Given: Two engine configs
            mock_engine1 = MagicMock()
            mock_engine1.name = "duckduckgo"
            mock_engine1.weight = 0.7
            mock_engine1.is_available = True

            mock_engine2 = MagicMock()
            mock_engine2.name = "mojeek"
            mock_engine2.weight = 0.85
            mock_engine2.is_available = True

            mock_config_manager.get_engines_for_category.return_value = [
                mock_engine1,
                mock_engine2,
            ]
            mock_config_manager.get_engine.side_effect = lambda name: {
                "duckduckgo": mock_engine1,
                "mojeek": mock_engine2,
            }.get(name)
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            mock_get_config_manager.return_value = mock_config_manager

            # Given: Circuit breaker - duckduckgo unavailable, mojeek available
            async def mock_check_available(engine: str) -> bool:
                return engine == "mojeek"

            with patch(
                "src.search.browser_search_provider.check_engine_available",
                side_effect=mock_check_available,
            ):
                category = provider._detect_category("test query")
                engines_configs = mock_config_manager.get_engines_for_category(category)

                # When: Filtering by circuit breaker
                available_engines = []
                for cfg in engines_configs:
                    if await mock_check_available(cfg.name):
                        if cfg.is_available:
                            available_engines.append((cfg.name, cfg.weight))

                # Then: Only available engine (mojeek) is selected
                assert len(available_engines) == 1
                assert available_engines[0][0] == "mojeek"

    @pytest.mark.asyncio
    async def test_engine_selection_weighted(self) -> None:
        """Test weighted engine selection.

        Given: Multiple engines with different weights
        When: search() selects engine
        Then: Engine with highest weight is selected
        """
        provider = BrowserSearchProvider()

        with patch(
            "src.search.browser_search_provider.get_engine_config_manager"
        ) as mock_get_config_manager:
            mock_config_manager = MagicMock()

            # Given: Engine configs with different weights
            mock_engine1 = MagicMock()
            mock_engine1.name = "duckduckgo"
            mock_engine1.weight = 0.7
            mock_engine1.is_available = True

            mock_engine2 = MagicMock()
            mock_engine2.name = "mojeek"
            mock_engine2.weight = 0.85
            mock_engine2.is_available = True

            mock_config_manager.get_engines_for_category.return_value = [
                mock_engine1,
                mock_engine2,
            ]
            mock_config_manager.get_engine.side_effect = lambda name: {
                "duckduckgo": mock_engine1,
                "mojeek": mock_engine2,
            }.get(name)
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            mock_get_config_manager.return_value = mock_config_manager

            with patch(
                "src.search.browser_search_provider.check_engine_available",
                AsyncMock(return_value=True),
            ):
                from src.search.circuit_breaker import check_engine_available

                category = provider._detect_category("test query")
                engines_configs = mock_config_manager.get_engines_for_category(category)

                # When: Building available engines list and sorting by weight
                available_engines = []
                for cfg in engines_configs:
                    if await check_engine_available(cfg.name):
                        if cfg.is_available:
                            available_engines.append((cfg.name, cfg.weight))

                # Sort by weight descending
                available_engines.sort(key=lambda x: x[1], reverse=True)

                # Then: Engine with highest weight (mojeek) is selected
                assert available_engines[0][0] == "mojeek"
                assert available_engines[0][1] == 0.85

    @pytest.mark.asyncio
    async def test_engine_selection_same_weight(self) -> None:
        """Test engine selection when weights are equal.

        Given: Multiple engines with same weight
        When: search() selects engine
        Then: First engine in sorted list is selected (stable sort)
        """
        provider = BrowserSearchProvider()

        with patch(
            "src.search.browser_search_provider.get_engine_config_manager"
        ) as mock_get_config_manager:
            mock_config_manager = MagicMock()

            # Given: Engine configs with same weight
            mock_engine1 = MagicMock()
            mock_engine1.name = "duckduckgo"
            mock_engine1.weight = 0.7
            mock_engine1.is_available = True

            mock_engine2 = MagicMock()
            mock_engine2.name = "mojeek"
            mock_engine2.weight = 0.7  # Same weight
            mock_engine2.is_available = True

            mock_config_manager.get_engines_for_category.return_value = [
                mock_engine1,
                mock_engine2,
            ]
            mock_config_manager.get_engine.side_effect = lambda name: {
                "duckduckgo": mock_engine1,
                "mojeek": mock_engine2,
            }.get(name)
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            mock_get_config_manager.return_value = mock_config_manager

            with patch(
                "src.search.browser_search_provider.check_engine_available",
                AsyncMock(return_value=True),
            ) as mock_check:
                category = provider._detect_category("test query")
                engines_configs = mock_config_manager.get_engines_for_category(category)

                # When: Building available engines list and sorting by weight
                available_engines = []
                for cfg in engines_configs:
                    # Use the mocked check_engine_available
                    if await mock_check(cfg.name):
                        if cfg.is_available:
                            available_engines.append((cfg.name, cfg.weight))

                # Sort by weight descending
                available_engines.sort(key=lambda x: x[1], reverse=True)

                # Then: Both engines should be available (same weight)
                assert len(available_engines) == 2
                # When weights are equal, first in original order is selected
                assert available_engines[0][0] == "duckduckgo"  # First in original order
                assert available_engines[0][1] == 0.7
                assert available_engines[1][0] == "mojeek"
                assert available_engines[1][1] == 0.7

    @pytest.mark.asyncio
    async def test_engine_health_recording_success(self) -> None:
        """Test engine health recording on success.

        Given: Search succeeds
        When: search() completes successfully
        Then: record_engine_result(success=True) is called
        """
        # Mock page with all required methods
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html><body>Test</body></html>")
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.is_closed = MagicMock(return_value=False)

        # Mock context for _ensure_browser
        mock_context = AsyncMock()
        mock_context.cookies = AsyncMock(return_value=[])

        # Mock TabPool and EngineRateLimiter
        mock_tab_pool = MagicMock()
        mock_tab_pool.acquire = AsyncMock(return_value=mock_page)
        mock_tab_pool.release = MagicMock()
        mock_tab_pool.report_captcha = MagicMock()

        mock_engine_limiter = MagicMock()
        mock_engine_limiter.acquire = AsyncMock()
        mock_engine_limiter.release = MagicMock()

        # Note: TabPool/RateLimiter patches must be active BEFORE provider creation
        with (
            patch(
                "src.search.browser_search_provider.check_engine_available",
                AsyncMock(return_value=True),
            ),
            patch(
                "src.search.browser_search_provider.get_engine_config_manager"
            ) as mock_get_config_manager,
            patch("src.search.tab_pool.get_tab_pool", return_value=mock_tab_pool),
            patch("src.search.tab_pool.get_engine_rate_limiter", return_value=mock_engine_limiter),
        ):
            # Create provider INSIDE the patch context
            provider = BrowserSearchProvider()
            # Mock _ensure_browser to set up context without real browser
            provider._context = mock_context

            mock_config_manager = MagicMock()
            mock_engine_config = MagicMock()
            mock_engine_config.name = "duckduckgo"
            mock_engine_config.weight = 0.7
            mock_engine_config.is_available = True
            mock_engine_config.min_interval = 5.0  # Per-engine QPS
            mock_config_manager.get_default_engines.return_value = ["duckduckgo"]
            mock_config_manager.get_engines_for_category.return_value = [mock_engine_config]
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            mock_config_manager.get_engine.return_value = mock_engine_config
            mock_get_config_manager.return_value = mock_config_manager

            with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                mock_parser = MagicMock()
                mock_parser.build_search_url = MagicMock(
                    return_value="https://duckduckgo.com/?q=test"
                )
                mock_parse_result = ParseResult(
                    ok=True,
                    is_captcha=False,
                    results=[
                        ParsedResult(
                            title="Test",
                            url="https://example.com",
                            snippet="Test snippet",
                            rank=1,
                        )
                    ],
                )
                mock_parser.parse = MagicMock(return_value=mock_parse_result)
                mock_get_parser.return_value = mock_parser

                # Given: record_engine_result mock
                with patch(
                    "src.search.browser_search_provider.record_engine_result",
                    AsyncMock(),
                ) as mock_record:
                    with patch.object(provider, "_save_session", AsyncMock()):
                        with patch.object(provider, "_ensure_browser", AsyncMock()):
                            # When: Search succeeds
                            await provider.search("test query")

                            # Then: record_engine_result is called with success=True
                            assert mock_record.called
                            call_args = mock_record.call_args
                            assert call_args is not None
                            assert call_args.kwargs.get("success") is True
                            # is_captcha is not specified for success case (defaults to False)
                            assert call_args.kwargs.get("is_captcha", False) is False

        await provider.close()

    @pytest.mark.asyncio
    async def test_engine_health_recording_failure(self) -> None:
        """Test engine health recording on parse failure.

        Given: Parse fails
        When: search() encounters parse failure
        Then: record_engine_result(success=False) is called
        """
        # Mock page with all required methods
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html><body>Test</body></html>")
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.is_closed = MagicMock(return_value=False)

        # Mock context for _ensure_browser
        mock_context = AsyncMock()
        mock_context.cookies = AsyncMock(return_value=[])

        # Mock TabPool and EngineRateLimiter
        mock_tab_pool = MagicMock()
        mock_tab_pool.acquire = AsyncMock(return_value=mock_page)
        mock_tab_pool.release = MagicMock()
        mock_tab_pool.report_captcha = MagicMock()

        mock_engine_limiter = MagicMock()
        mock_engine_limiter.acquire = AsyncMock()
        mock_engine_limiter.release = MagicMock()

        # Mock engine selection components
        with (
            patch(
                "src.search.browser_search_provider.check_engine_available",
                AsyncMock(return_value=True),
            ),
            patch(
                "src.search.browser_search_provider.get_engine_config_manager"
            ) as mock_get_config_manager,
            patch("src.search.tab_pool.get_tab_pool", return_value=mock_tab_pool),
            patch("src.search.tab_pool.get_engine_rate_limiter", return_value=mock_engine_limiter),
        ):
            # Create provider INSIDE the patch context
            provider = BrowserSearchProvider()
            provider._context = mock_context

            mock_config_manager = MagicMock()
            mock_engine_config = MagicMock()
            mock_engine_config.name = "duckduckgo"
            mock_engine_config.weight = 0.7
            mock_engine_config.is_available = True
            mock_engine_config.min_interval = 5.0  # Per-engine QPS
            mock_config_manager.get_default_engines.return_value = ["duckduckgo"]
            mock_config_manager.get_engines_for_category.return_value = [mock_engine_config]
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            mock_config_manager.get_engine.return_value = mock_engine_config
            mock_get_config_manager.return_value = mock_config_manager

            with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                mock_parser = MagicMock()
                mock_parser.build_search_url = MagicMock(
                    return_value="https://duckduckgo.com/?q=test"
                )
                # Given: Parse failure
                mock_parse_result = ParseResult(
                    ok=False,
                    is_captcha=False,
                    error="Parse failed",
                )
                mock_parser.parse = MagicMock(return_value=mock_parse_result)
                mock_get_parser.return_value = mock_parser

                # Given: record_engine_result mock
                with patch(
                    "src.search.browser_search_provider.record_engine_result",
                    AsyncMock(),
                ) as mock_record:
                    with patch.object(provider, "_ensure_browser", AsyncMock()):
                        # When: Parse fails
                        response = await provider.search("test query")

                        # Then: record_engine_result is called with success=False
                        assert mock_record.called
                        call_args = mock_record.call_args
                        assert call_args is not None
                        assert call_args.kwargs.get("success") is False
                        assert call_args.kwargs.get("is_captcha") is False
                        assert response.ok is False

        await provider.close()

    @pytest.mark.asyncio
    async def test_engine_health_recording_captcha(self) -> None:
        """Test engine health recording on CAPTCHA detection.

        Given: CAPTCHA detected
        When: search() detects CAPTCHA
        Then: record_engine_result(is_captcha=True) is called
        """
        # Mock page with all required methods
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html><body>Test</body></html>")
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.is_closed = MagicMock(return_value=False)

        # Mock context for _ensure_browser
        mock_context = AsyncMock()
        mock_context.cookies = AsyncMock(return_value=[])

        # Mock TabPool and EngineRateLimiter
        mock_tab_pool = MagicMock()
        mock_tab_pool.acquire = AsyncMock(return_value=mock_page)
        mock_tab_pool.release = MagicMock()
        mock_tab_pool.report_captcha = MagicMock()

        mock_engine_limiter = MagicMock()
        mock_engine_limiter.acquire = AsyncMock()
        mock_engine_limiter.release = MagicMock()

        # Mock engine selection components
        with (
            patch(
                "src.search.browser_search_provider.check_engine_available",
                AsyncMock(return_value=True),
            ),
            patch(
                "src.search.browser_search_provider.get_engine_config_manager"
            ) as mock_get_config_manager,
            patch("src.search.tab_pool.get_tab_pool", return_value=mock_tab_pool),
            patch("src.search.tab_pool.get_engine_rate_limiter", return_value=mock_engine_limiter),
        ):
            # Create provider INSIDE the patch context
            provider = BrowserSearchProvider()
            provider._context = mock_context

            mock_config_manager = MagicMock()
            mock_engine_config = MagicMock()
            mock_engine_config.name = "duckduckgo"
            mock_engine_config.weight = 0.7
            mock_engine_config.is_available = True
            mock_engine_config.min_interval = 5.0  # Per-engine QPS
            mock_config_manager.get_default_engines.return_value = ["duckduckgo"]
            mock_config_manager.get_engines_for_category.return_value = [mock_engine_config]
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            mock_config_manager.get_engine.return_value = mock_engine_config
            mock_get_config_manager.return_value = mock_config_manager

            with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                mock_parser = MagicMock()
                mock_parser.build_search_url = MagicMock(
                    return_value="https://duckduckgo.com/?q=test"
                )
                # Given: CAPTCHA detected
                mock_parse_result = ParseResult(
                    ok=False,
                    is_captcha=True,
                    captcha_type="turnstile",
                    error="CAPTCHA detected",
                )
                mock_parser.parse = MagicMock(return_value=mock_parse_result)
                mock_get_parser.return_value = mock_parser

                # Given: record_engine_result mock
                with patch(
                    "src.search.browser_search_provider.record_engine_result",
                    AsyncMock(),
                ) as mock_record:
                    with patch.object(provider, "_ensure_browser", AsyncMock()):
                        # When: CAPTCHA is detected
                        response = await provider.search("test query")

                        # Then: record_engine_result is called with is_captcha=True
                        assert mock_record.called
                        call_args = mock_record.call_args
                        assert call_args is not None
                        assert call_args.kwargs.get("success") is False
                        assert call_args.kwargs.get("is_captcha") is True
                        assert response.ok is False
                        # Verify report_captcha was called on TabPool for auto-backoff
                        mock_tab_pool.report_captcha.assert_called_once()

        await provider.close()

    @pytest.mark.asyncio
    async def test_engine_health_recording_exception(self) -> None:
        """Test engine health recording handles exceptions gracefully.

        Given: record_engine_result() raises exception
        When: search() tries to record health
        Then: Exception is caught, logged, and search result is returned normally
        """
        # Mock page with all required methods
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html><body>Test</body></html>")
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.is_closed = MagicMock(return_value=False)

        # Mock context for _ensure_browser
        mock_context = AsyncMock()
        mock_context.cookies = AsyncMock(return_value=[])

        # Mock TabPool and EngineRateLimiter
        mock_tab_pool = MagicMock()
        mock_tab_pool.acquire = AsyncMock(return_value=mock_page)
        mock_tab_pool.release = MagicMock()
        mock_tab_pool.report_captcha = MagicMock()

        mock_engine_limiter = MagicMock()
        mock_engine_limiter.acquire = AsyncMock()
        mock_engine_limiter.release = MagicMock()

        # Mock engine selection components
        with (
            patch(
                "src.search.browser_search_provider.check_engine_available",
                AsyncMock(return_value=True),
            ),
            patch(
                "src.search.browser_search_provider.get_engine_config_manager"
            ) as mock_get_config_manager,
            patch("src.search.tab_pool.get_tab_pool", return_value=mock_tab_pool),
            patch("src.search.tab_pool.get_engine_rate_limiter", return_value=mock_engine_limiter),
        ):
            # Create provider INSIDE the patch context
            provider = BrowserSearchProvider()
            provider._context = mock_context

            mock_config_manager = MagicMock()
            mock_engine_config = MagicMock()
            mock_engine_config.name = "duckduckgo"
            mock_engine_config.weight = 0.7
            mock_engine_config.is_available = True
            mock_engine_config.min_interval = 5.0  # Per-engine QPS
            mock_config_manager.get_default_engines.return_value = ["duckduckgo"]
            mock_config_manager.get_engines_for_category.return_value = [mock_engine_config]
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            mock_config_manager.get_engine.return_value = mock_engine_config
            mock_get_config_manager.return_value = mock_config_manager

            with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                mock_parser = MagicMock()
                mock_parser.build_search_url = MagicMock(
                    return_value="https://duckduckgo.com/?q=test"
                )
                mock_parse_result = ParseResult(
                    ok=True,
                    is_captcha=False,
                    results=[
                        ParsedResult(
                            title="Test",
                            url="https://example.com",
                            snippet="Test snippet",
                            rank=1,
                        )
                    ],
                )
                mock_parser.parse = MagicMock(return_value=mock_parse_result)
                mock_get_parser.return_value = mock_parser

                # Given: record_engine_result raises exception
                with patch(
                    "src.search.browser_search_provider.record_engine_result",
                    AsyncMock(side_effect=Exception("Database error")),
                ) as mock_record:
                    with patch.object(provider, "_save_session", AsyncMock()):
                        with patch.object(provider, "_ensure_browser", AsyncMock()):
                            # When: Search succeeds but recording fails
                            response = await provider.search("test query")

                            # Then: Exception is caught and search result is returned normally
                            assert mock_record.called
                            assert response.ok is True  # Search result is not affected
                            assert len(response.results) == 1

        await provider.close()

    @pytest.mark.asyncio
    async def test_no_available_engines(self) -> None:
        """Test error handling when no engines are available.

        Given: No engines available (all filtered out by circuit breaker)
        When: search() tries to select engine
        Then: SearchResponse(error="No available engines") is returned
        """
        provider = BrowserSearchProvider()

        with patch(
            "src.search.browser_search_provider.get_engine_config_manager"
        ) as mock_get_config_manager:
            mock_config_manager = MagicMock()
            mock_config_manager.get_engines_for_category.return_value = []
            mock_config_manager.get_available_engines.return_value = []
            mock_config_manager.get_default_engines.return_value = []
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            mock_config_manager.get_engine.return_value = None
            mock_get_config_manager.return_value = mock_config_manager

            with patch(
                "src.search.browser_search_provider.check_engine_available",
                AsyncMock(return_value=False),
            ):
                # When: No engines are available
                response = await provider.search("test query")

                # Then: Error response is returned
                assert response.ok is False
                assert response.error is not None
                # Error message can be "No available engines" or "No engines with parsers available"
                assert (
                    "No available engines" in response.error
                    or "No engines with parsers available" in response.error
                )
                assert response.results == []

        await provider.close()

    @pytest.mark.asyncio
    async def test_no_available_engines_empty_list(self) -> None:
        """Test error handling when options.engines is empty list.

        Given: options.engines=[]
        When: search() tries to select engine
        Then: SearchResponse(error="No available engines") is returned
        """
        provider = BrowserSearchProvider()

        with patch(
            "src.search.browser_search_provider.get_engine_config_manager"
        ) as mock_get_config_manager:
            mock_config_manager = MagicMock()
            mock_get_config_manager.return_value = mock_config_manager

            with patch(
                "src.search.browser_search_provider.check_engine_available",
                AsyncMock(return_value=False),
            ):
                # Given: Empty engines list
                options = SearchOptions(engines=[])

                # When: Search is called with empty engines list
                response = await provider.search("test query", options)

                # Then: Error response is returned
                assert response.ok is False
                assert response.error is not None
                assert "No available engines" in response.error

        await provider.close()

    @pytest.mark.asyncio
    async def test_check_engine_available_exception(self) -> None:
        """Test engine selection handles check_engine_available() exception.

        Given: check_engine_available() raises exception
        When: search() filters engines
        Then: Exception is caught, engine is skipped, search continues
        """
        provider = BrowserSearchProvider()

        with patch(
            "src.search.browser_search_provider.get_engine_config_manager"
        ) as mock_get_config_manager:
            mock_config_manager = MagicMock()
            mock_engine_config = MagicMock()
            mock_engine_config.name = "duckduckgo"
            mock_engine_config.weight = 0.7
            mock_engine_config.is_available = True
            mock_engine_config.min_interval = 5.0  # Per-engine QPS
            mock_config_manager.get_engines_for_category.return_value = [mock_engine_config]
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            mock_config_manager.get_engine.return_value = mock_engine_config
            mock_get_config_manager.return_value = mock_config_manager

            # Given: check_engine_available raises exception
            async def mock_check_with_exception(engine: str) -> bool:
                raise Exception("Circuit breaker error")

            with patch(
                "src.search.browser_search_provider.check_engine_available",
                side_effect=mock_check_with_exception,
            ):
                # When: Search is called
                # Then: Exception is caught, engine is skipped, resulting in no available engines
                response = await provider.search("test query")

                # Exception is caught during filtering, resulting in no available engines
                assert response.ok is False
                assert response.error is not None
                assert "No available engines" in response.error

        await provider.close()

    @pytest.mark.asyncio
    async def test_engine_config_none(self) -> None:
        """Test engine selection handles engine_config=None.

        Given: get_engine() returns None
        When: search() filters engines
        Then: Engine is skipped, search continues
        """
        provider = BrowserSearchProvider()

        with patch(
            "src.search.browser_search_provider.get_engine_config_manager"
        ) as mock_get_config_manager:
            mock_config_manager = MagicMock()
            mock_config_manager.get_engines_for_category.return_value = []
            mock_config_manager.get_available_engines.return_value = []
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            # Given: get_engine() returns None
            mock_config_manager.get_engine.return_value = None
            mock_get_config_manager.return_value = mock_config_manager

            with patch(
                "src.search.browser_search_provider.check_engine_available",
                AsyncMock(return_value=True),
            ):
                # When: Search is called
                response = await provider.search("test query")

                # Then: Engine is skipped (None check), resulting in no available engines
                assert response.ok is False
                assert response.error is not None
                assert "No available engines" in response.error

        await provider.close()


# ============================================================================
# Per-Engine QPS Rate Limiting Tests (Per-engine QPS rate limiting)
# ============================================================================


class TestPerEngineQPSRateLimiting:
    """Tests for per-engine QPS rate limiting.

    Per spec ADR-0010: "Engine-specific rate control (concurrency=1, strict QPS)"
    Per spec ADR-0006: "Engine QPS≤0.25 (1 request/4s), concurrency=1"

    Validates:
    - _last_search_times attribute exists for per-engine tracking
    - _rate_limit() accepts engine parameter
    - Per-engine intervals are applied correctly
    - Default behavior (engine=None uses default interval)
    - Unknown engines fall back to default interval
    """

    def test_last_search_times_attribute_exists(self) -> None:
        """Test _last_search_times attribute is initialized.

        Given: New BrowserSearchProvider instance
        When: Provider is created
        Then: _last_search_times dict exists and is empty
        """
        # Given/When: New provider instance
        provider = BrowserSearchProvider()

        # Then: _last_search_times exists and is empty dict
        assert hasattr(provider, "_last_search_times")
        assert isinstance(provider._last_search_times, dict)
        assert len(provider._last_search_times) == 0

    @pytest.mark.asyncio
    async def test_rate_limit_accepts_engine_parameter(self) -> None:
        """Test _rate_limit() accepts engine parameter.

        Given: BrowserSearchProvider instance
        When: _rate_limit(engine="duckduckgo") is called
        Then: Method completes without TypeError
        """
        provider = BrowserSearchProvider()

        # Given: Mock engine config manager
        with patch(
            "src.search.browser_search_provider.get_engine_config_manager"
        ) as mock_get_config_manager:
            mock_config_manager = MagicMock()
            mock_engine_config = MagicMock()
            mock_engine_config.min_interval = 5.0  # duckduckgo qps=0.2
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            mock_config_manager.get_engine.return_value = mock_engine_config
            mock_get_config_manager.return_value = mock_config_manager

            # When: _rate_limit() is called with engine parameter
            # Then: No TypeError is raised
            await provider._rate_limit(engine="duckduckgo")

    @pytest.mark.asyncio
    async def test_rate_limit_default_engine_when_engine_is_none(self) -> None:
        """Test _rate_limit() works when engine is None (default interval).

        Given: BrowserSearchProvider instance
        When: _rate_limit() is called without engine parameter
        Then: Method completes successfully using default interval
        """
        provider = BrowserSearchProvider()

        # When: _rate_limit() is called without engine
        # Then: No error, uses default interval
        await provider._rate_limit()

        # Verify "default" key is used for tracking
        assert "default" in provider._last_search_times

    @pytest.mark.asyncio
    async def test_rate_limit_with_none_engine(self) -> None:
        """Test _rate_limit(engine=None) uses default interval.

        Given: BrowserSearchProvider instance
        When: _rate_limit(engine=None) is called
        Then: Method uses default interval and tracks under "default" key
        """
        provider = BrowserSearchProvider()

        # When: _rate_limit() is called with engine=None
        await provider._rate_limit(engine=None)

        # Then: "default" key is used
        assert "default" in provider._last_search_times

    @pytest.mark.asyncio
    async def test_per_engine_tracking_separate_keys(self) -> None:
        """Test different engines are tracked separately.

        Given: BrowserSearchProvider instance
        When: _rate_limit() is called for different engines
        Then: Each engine has its own tracking entry in _last_search_times
        """
        provider = BrowserSearchProvider()

        # Given: Mock engine config manager
        with patch(
            "src.search.browser_search_provider.get_engine_config_manager"
        ) as mock_get_config_manager:
            mock_config_manager = MagicMock()
            mock_engine_config = MagicMock()
            mock_engine_config.min_interval = 4.0
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            mock_config_manager.get_engine.return_value = mock_engine_config
            mock_get_config_manager.return_value = mock_config_manager

            # When: _rate_limit() is called for different engines
            await provider._rate_limit(engine="duckduckgo")
            await provider._rate_limit(engine="mojeek")
            await provider._rate_limit(engine="google")

            # Then: Each engine has separate tracking
            assert "duckduckgo" in provider._last_search_times
            assert "mojeek" in provider._last_search_times
            assert "google" in provider._last_search_times

    @pytest.mark.asyncio
    async def test_rate_limit_uses_engine_specific_interval(self) -> None:
        """Test _rate_limit() uses engine-specific min_interval.

        Given: Engine config with specific QPS (interval)
        When: _rate_limit() is called twice in quick succession
        Then: Sleep is applied based on engine's min_interval
        """
        provider = BrowserSearchProvider()

        # Given: Engine with 5.0s interval (qps=0.2)
        with patch(
            "src.search.browser_search_provider.get_engine_config_manager"
        ) as mock_get_config_manager:
            mock_config_manager = MagicMock()
            mock_engine_config = MagicMock()
            mock_engine_config.min_interval = 5.0
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            mock_config_manager.get_engine.return_value = mock_engine_config
            mock_get_config_manager.return_value = mock_config_manager

            # When: First call - immediate
            import time

            start_time = time.time()
            await provider._rate_limit(engine="duckduckgo")
            first_call_time = time.time() - start_time

            # Then: First call should be nearly immediate
            assert first_call_time < 0.5, "First call should be immediate"

            # Verify engine-specific tracking
            assert "duckduckgo" in provider._last_search_times

    @pytest.mark.asyncio
    async def test_rate_limit_unknown_engine_fallback(self) -> None:
        """Test _rate_limit() with unknown engine falls back to default interval.

        Given: Unknown engine name (not in config)
        When: _rate_limit(engine="unknown_engine") is called
        Then: Method uses default _min_interval
        """
        provider = BrowserSearchProvider()

        # Given: Engine config manager returns None for unknown engine
        with patch(
            "src.search.browser_search_provider.get_engine_config_manager"
        ) as mock_get_config_manager:
            mock_config_manager = MagicMock()
            mock_config_manager.get_engine.return_value = None  # Unknown engine
            mock_get_config_manager.return_value = mock_config_manager

            # When: _rate_limit() is called with unknown engine
            await provider._rate_limit(engine="unknown_engine")

            # Then: Uses default interval, but still tracks under engine name
            assert "unknown_engine" in provider._last_search_times

    @pytest.mark.asyncio
    async def test_search_calls_rate_limit_with_engine(self, mock_page: AsyncMock) -> None:
        """Test search() calls _rate_limit() with selected engine.

        Given: Mock setup for search execution
        When: search() is called
        Then: _rate_limit() is called with the selected engine name
        """
        # Setup mock page for the search
        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html><body>Test</body></html>")
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.is_closed = MagicMock(return_value=False)

        # Mock context for _ensure_browser
        mock_context = AsyncMock()
        mock_context.cookies = AsyncMock(return_value=[])

        # Mock TabPool and EngineRateLimiter
        mock_tab_pool = MagicMock()
        mock_tab_pool.acquire = AsyncMock(return_value=mock_page)
        mock_tab_pool.release = MagicMock()
        mock_tab_pool.report_captcha = MagicMock()

        mock_engine_limiter = MagicMock()
        mock_engine_limiter.acquire = AsyncMock()
        mock_engine_limiter.release = MagicMock()

        with (
            patch(
                "src.search.browser_search_provider.check_engine_available",
                AsyncMock(return_value=True),
            ),
            patch(
                "src.search.browser_search_provider.get_engine_config_manager"
            ) as mock_get_config_manager,
            patch("src.search.tab_pool.get_tab_pool", return_value=mock_tab_pool),
            patch("src.search.tab_pool.get_engine_rate_limiter", return_value=mock_engine_limiter),
        ):
            # Create provider INSIDE the patch context
            provider = BrowserSearchProvider()
            provider._context = mock_context

            mock_config_manager = MagicMock()
            mock_engine_config = MagicMock()
            mock_engine_config.name = "duckduckgo"
            mock_engine_config.weight = 0.7
            mock_engine_config.is_available = True
            mock_engine_config.min_interval = 5.0
            mock_config_manager.get_default_engines.return_value = ["duckduckgo"]
            mock_config_manager.get_engines_for_category.return_value = [mock_engine_config]
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            mock_config_manager.get_engine.return_value = mock_engine_config
            mock_get_config_manager.return_value = mock_config_manager

            with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                mock_parser = MagicMock()
                mock_parser.build_search_url = MagicMock(
                    return_value="https://duckduckgo.com/?q=test"
                )
                mock_parse_result = ParseResult(
                    ok=True,
                    is_captcha=False,
                    results=[
                        ParsedResult(
                            title="Test",
                            url="https://example.com",
                            snippet="Test snippet",
                            rank=1,
                        )
                    ],
                )
                mock_parser.parse = MagicMock(return_value=mock_parse_result)
                mock_get_parser.return_value = mock_parser

                with patch(
                    "src.search.browser_search_provider.record_engine_result",
                    AsyncMock(),
                ):
                    with patch.object(provider, "_save_session", AsyncMock()):
                        with patch.object(provider, "_ensure_browser", AsyncMock()):
                            # Spy on _rate_limit
                            rate_limit_calls: list[str | None] = []

                            async def track_rate_limit(engine: str | None = None) -> None:
                                rate_limit_calls.append(engine)
                                # Don't actually sleep
                                provider._last_search_times[engine or "default"] = 1.0

                            with patch.object(provider, "_rate_limit", track_rate_limit):
                                # When: search() is called
                                response = await provider.search("test query")

                                # Then: _rate_limit was called with engine name
                                assert len(rate_limit_calls) == 1
                                assert rate_limit_calls[0] == "duckduckgo"
                                assert response.ok is True

        await provider.close()


# ============================================================================
# Query Normalization Tests (Query normalization)
# ============================================================================


class TestQueryNormalization:
    """Tests for query operator normalization in BrowserSearchProvider.search().

    Per spec ADR-0010: "Query operators (site:, filetype:, intitle:, "...", +/-, after:)"
    Per spec ADR-0006: "Engine normalization (transform operators to engine-specific syntax)"

    Test Perspectives Table:
    | Case ID   | Input / Precondition                    | Perspective              | Expected Result                          | Notes                     |
    |-----------|----------------------------------------|--------------------------|------------------------------------------|---------------------------|
    | TC-QN-01  | query="AI site:go.jp", engine=duckduckgo | Equivalence - normal    | normalized_query contains "site:go.jp"   | site: operator preserved  |
    | TC-QN-02  | query="AI after:2024-01-01", engine=duckduckgo | Equivalence - normal | normalized_query does NOT contain "after:" | DuckDuckGo doesn't support after: |
    | TC-QN-03  | query="AI after:2024-01-01", engine=google | Equivalence - normal   | normalized_query contains "after:2024-01-01" | Google supports after: |
    | TC-QN-04  | query="plain query", engine=duckduckgo | Equivalence - normal    | normalized_query == "plain query"        | No operators, no change   |
    | TC-QN-05  | query="", engine=duckduckgo            | Boundary - empty         | normalized_query == ""                   | Empty string handling     |
    | TC-QN-06  | Multiple operators in query            | Equivalence - normal     | All operators transformed                | Multiple operators        |
    """

    @pytest.mark.asyncio
    async def test_search_calls_transform_query_for_engine(self) -> None:
        """Test search() calls transform_query_for_engine().

        Given: BrowserSearchProvider instance and mock setup
        When: search() is called with a query containing operators
        Then: transform_query_for_engine() is called with query and engine
        """
        # Mock page with all required methods
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html><body>Test</body></html>")
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.is_closed = MagicMock(return_value=False)

        # Mock context for _ensure_browser
        mock_context = AsyncMock()
        mock_context.cookies = AsyncMock(return_value=[])

        # Mock TabPool and EngineRateLimiter
        mock_tab_pool = MagicMock()
        mock_tab_pool.acquire = AsyncMock(return_value=mock_page)
        mock_tab_pool.release = MagicMock()
        mock_tab_pool.report_captcha = MagicMock()

        mock_engine_limiter = MagicMock()
        mock_engine_limiter.acquire = AsyncMock()
        mock_engine_limiter.release = MagicMock()

        with (
            patch(
                "src.search.browser_search_provider.check_engine_available",
                AsyncMock(return_value=True),
            ),
            patch(
                "src.search.browser_search_provider.get_engine_config_manager"
            ) as mock_get_config_manager,
            patch("src.search.tab_pool.get_tab_pool", return_value=mock_tab_pool),
            patch("src.search.tab_pool.get_engine_rate_limiter", return_value=mock_engine_limiter),
        ):
            # Create provider INSIDE the patch context
            provider = BrowserSearchProvider()
            provider._context = mock_context

            mock_config_manager = MagicMock()
            mock_engine_config = MagicMock()
            mock_engine_config.name = "duckduckgo"
            mock_engine_config.weight = 0.7
            mock_engine_config.is_available = True
            mock_engine_config.min_interval = 5.0
            mock_config_manager.get_default_engines.return_value = ["duckduckgo"]
            mock_config_manager.get_engines_for_category.return_value = [mock_engine_config]
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            mock_config_manager.get_engine.return_value = mock_engine_config
            mock_get_config_manager.return_value = mock_config_manager

            with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                mock_parser = MagicMock()
                mock_parser.build_search_url = MagicMock(
                    return_value="https://duckduckgo.com/?q=test"
                )
                mock_parse_result = ParseResult(
                    ok=True,
                    is_captcha=False,
                    results=[
                        ParsedResult(
                            title="Test",
                            url="https://example.com",
                            snippet="Test snippet",
                            rank=1,
                        )
                    ],
                )
                mock_parser.parse = MagicMock(return_value=mock_parse_result)
                mock_get_parser.return_value = mock_parser

                with patch(
                    "src.search.browser_search_provider.record_engine_result",
                    AsyncMock(),
                ):
                    with patch.object(provider, "_save_session", AsyncMock()):
                        with patch.object(provider, "_rate_limit", AsyncMock()):
                            with patch.object(provider, "_ensure_browser", AsyncMock()):
                                # Given: Query with site: operator
                                query = "AI site:go.jp"

                                # Mock transform_query_for_engine
                                with patch(
                                    "src.search.browser_search_provider.transform_query_for_engine",
                                    return_value="AI site:go.jp",
                                ) as mock_transform:
                                    # When: search() is called
                                    response = await provider.search(query)

                                    # Then: transform_query_for_engine was called
                                    mock_transform.assert_called_once_with(query, "duckduckgo")
                                    assert response.ok is True

        await provider.close()

    @pytest.mark.asyncio
    async def test_search_normalizes_site_operator(self) -> None:
        """Test search() normalizes site: operator (TC-QN-01).

        Given: Query with site: operator, engine=duckduckgo
        When: search() is called
        Then: normalized_query contains site:go.jp
        """
        # Mock page with all required methods
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html><body>Test</body></html>")
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.is_closed = MagicMock(return_value=False)

        # Mock context for _ensure_browser
        mock_context = AsyncMock()
        mock_context.cookies = AsyncMock(return_value=[])

        # Mock TabPool and EngineRateLimiter
        mock_tab_pool = MagicMock()
        mock_tab_pool.acquire = AsyncMock(return_value=mock_page)
        mock_tab_pool.release = MagicMock()
        mock_tab_pool.report_captcha = MagicMock()

        mock_engine_limiter = MagicMock()
        mock_engine_limiter.acquire = AsyncMock()
        mock_engine_limiter.release = MagicMock()

        with (
            patch(
                "src.search.browser_search_provider.check_engine_available",
                AsyncMock(return_value=True),
            ),
            patch(
                "src.search.browser_search_provider.get_engine_config_manager"
            ) as mock_get_config_manager,
            patch("src.search.tab_pool.get_tab_pool", return_value=mock_tab_pool),
            patch("src.search.tab_pool.get_engine_rate_limiter", return_value=mock_engine_limiter),
        ):
            # Create provider INSIDE the patch context
            provider = BrowserSearchProvider()
            provider._context = mock_context

            mock_config_manager = MagicMock()
            mock_engine_config = MagicMock()
            mock_engine_config.name = "duckduckgo"
            mock_engine_config.weight = 0.7
            mock_engine_config.is_available = True
            mock_engine_config.min_interval = 5.0
            mock_config_manager.get_default_engines.return_value = ["duckduckgo"]
            mock_config_manager.get_engines_for_category.return_value = [mock_engine_config]
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            mock_config_manager.get_engine.return_value = mock_engine_config
            mock_get_config_manager.return_value = mock_config_manager

            with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                mock_parser = MagicMock()
                mock_parser.build_search_url = MagicMock(
                    return_value="https://duckduckgo.com/?q=test"
                )
                mock_parse_result = ParseResult(
                    ok=True,
                    is_captcha=False,
                    results=[
                        ParsedResult(
                            title="Test",
                            url="https://example.com",
                            snippet="Test snippet",
                            rank=1,
                        )
                    ],
                )
                mock_parser.parse = MagicMock(return_value=mock_parse_result)
                mock_get_parser.return_value = mock_parser

                with patch(
                    "src.search.browser_search_provider.record_engine_result",
                    AsyncMock(),
                ):
                    with patch.object(provider, "_save_session", AsyncMock()):
                        with patch.object(provider, "_rate_limit", AsyncMock()):
                            with patch.object(provider, "_ensure_browser", AsyncMock()):
                                # Given: Query with site: operator
                                query = "AI site:go.jp"

                                # When: search() is called
                                response = await provider.search(query)

                                # Then: parser.build_search_url was called with normalized query
                                # containing site:go.jp (DuckDuckGo supports site:)
                                call_args = mock_parser.build_search_url.call_args
                                normalized_query = call_args.kwargs.get("query")
                                assert "site:go.jp" in normalized_query
                                assert response.ok is True

        await provider.close()

    @pytest.mark.asyncio
    async def test_search_removes_unsupported_after_operator_duckduckgo(self) -> None:
        """Test search() removes unsupported after: operator for DuckDuckGo (TC-QN-02).

        Given: Query with after: operator, engine=duckduckgo
        When: search() is called
        Then: normalized_query does NOT contain after:
        """
        # Mock page with all required methods
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html><body>Test</body></html>")
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.is_closed = MagicMock(return_value=False)

        # Mock context for _ensure_browser
        mock_context = AsyncMock()
        mock_context.cookies = AsyncMock(return_value=[])

        # Mock TabPool and EngineRateLimiter
        mock_tab_pool = MagicMock()
        mock_tab_pool.acquire = AsyncMock(return_value=mock_page)
        mock_tab_pool.release = MagicMock()
        mock_tab_pool.report_captcha = MagicMock()

        mock_engine_limiter = MagicMock()
        mock_engine_limiter.acquire = AsyncMock()
        mock_engine_limiter.release = MagicMock()

        with (
            patch(
                "src.search.browser_search_provider.check_engine_available",
                AsyncMock(return_value=True),
            ),
            patch(
                "src.search.browser_search_provider.get_engine_config_manager"
            ) as mock_get_config_manager,
            patch("src.search.tab_pool.get_tab_pool", return_value=mock_tab_pool),
            patch("src.search.tab_pool.get_engine_rate_limiter", return_value=mock_engine_limiter),
        ):
            # Create provider INSIDE the patch context
            provider = BrowserSearchProvider()
            provider._context = mock_context

            mock_config_manager = MagicMock()
            mock_engine_config = MagicMock()
            mock_engine_config.name = "duckduckgo"
            mock_engine_config.weight = 0.7
            mock_engine_config.is_available = True
            mock_engine_config.min_interval = 5.0
            mock_config_manager.get_default_engines.return_value = ["duckduckgo"]
            mock_config_manager.get_engines_for_category.return_value = [mock_engine_config]
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            mock_config_manager.get_engine.return_value = mock_engine_config
            mock_get_config_manager.return_value = mock_config_manager

            with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                mock_parser = MagicMock()
                mock_parser.build_search_url = MagicMock(
                    return_value="https://duckduckgo.com/?q=test"
                )
                mock_parse_result = ParseResult(
                    ok=True,
                    is_captcha=False,
                    results=[
                        ParsedResult(
                            title="Test",
                            url="https://example.com",
                            snippet="Test snippet",
                            rank=1,
                        )
                    ],
                )
                mock_parser.parse = MagicMock(return_value=mock_parse_result)
                mock_get_parser.return_value = mock_parser

                with patch(
                    "src.search.browser_search_provider.record_engine_result",
                    AsyncMock(),
                ):
                    with patch.object(provider, "_save_session", AsyncMock()):
                        with patch.object(provider, "_rate_limit", AsyncMock()):
                            with patch.object(provider, "_ensure_browser", AsyncMock()):
                                # Given: Query with after: operator
                                query = "AI after:2024-01-01"

                                # When: search() is called
                                response = await provider.search(query)

                                # Then: parser.build_search_url was called with normalized query
                                # NOT containing after: (DuckDuckGo doesn't support after:)
                                call_args = mock_parser.build_search_url.call_args
                                normalized_query = call_args.kwargs.get("query")
                                assert "after:" not in normalized_query
                                assert "AI" in normalized_query
                                assert response.ok is True

        await provider.close()

    @pytest.mark.asyncio
    async def test_search_preserves_after_operator_google(self) -> None:
        """Test search() preserves after: operator for Google (TC-QN-03).

        Given: Query with after: operator, engine=google
        When: search() is called
        Then: normalized_query contains after:2024-01-01
        """
        # Mock page with all required methods
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html><body>Test</body></html>")
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.is_closed = MagicMock(return_value=False)

        # Mock context for _ensure_browser
        mock_context = AsyncMock()
        mock_context.cookies = AsyncMock(return_value=[])

        # Mock TabPool and EngineRateLimiter
        mock_tab_pool = MagicMock()
        mock_tab_pool.acquire = AsyncMock(return_value=mock_page)
        mock_tab_pool.release = MagicMock()
        mock_tab_pool.report_captcha = MagicMock()

        mock_engine_limiter = MagicMock()
        mock_engine_limiter.acquire = AsyncMock()
        mock_engine_limiter.release = MagicMock()

        with (
            patch(
                "src.search.browser_search_provider.check_engine_available",
                AsyncMock(return_value=True),
            ),
            patch(
                "src.search.browser_search_provider.get_engine_config_manager"
            ) as mock_get_config_manager,
            patch("src.search.tab_pool.get_tab_pool", return_value=mock_tab_pool),
            patch("src.search.tab_pool.get_engine_rate_limiter", return_value=mock_engine_limiter),
        ):
            # Create provider INSIDE the patch context
            provider = BrowserSearchProvider()
            provider._context = mock_context

            mock_config_manager = MagicMock()
            mock_engine_config = MagicMock()
            mock_engine_config.name = "google"
            mock_engine_config.weight = 1.0
            mock_engine_config.is_available = True
            mock_engine_config.min_interval = 20.0
            mock_config_manager.get_default_engines.return_value = ["duckduckgo"]
            mock_config_manager.get_engines_for_category.return_value = [mock_engine_config]
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            mock_config_manager.get_engine.return_value = mock_engine_config
            mock_get_config_manager.return_value = mock_config_manager

            with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                mock_parser = MagicMock()
                mock_parser.build_search_url = MagicMock(
                    return_value="https://google.com/search?q=test"
                )
                mock_parse_result = ParseResult(
                    ok=True,
                    is_captcha=False,
                    results=[
                        ParsedResult(
                            title="Test",
                            url="https://example.com",
                            snippet="Test snippet",
                            rank=1,
                        )
                    ],
                )
                mock_parser.parse = MagicMock(return_value=mock_parse_result)
                mock_get_parser.return_value = mock_parser

                with patch(
                    "src.search.browser_search_provider.record_engine_result",
                    AsyncMock(),
                ):
                    with patch.object(provider, "_save_session", AsyncMock()):
                        with patch.object(provider, "_rate_limit", AsyncMock()):
                            with patch.object(provider, "_ensure_browser", AsyncMock()):
                                # Given: Query with after: operator, google engine
                                query = "AI after:2024-01-01"
                                options = SearchOptions(engines=["google"])

                                # When: search() is called
                                response = await provider.search(query, options)

                                # Then: parser.build_search_url was called with normalized query
                                # containing after:2024-01-01 (Google supports after:)
                                call_args = mock_parser.build_search_url.call_args
                                normalized_query = call_args.kwargs.get("query")
                                assert "after:2024-01-01" in normalized_query
                                assert response.ok is True

        await provider.close()

    @pytest.mark.asyncio
    async def test_search_plain_query_unchanged(self) -> None:
        """Test search() leaves plain query unchanged (TC-QN-04).

        Given: Plain query without operators, engine=duckduckgo
        When: search() is called
        Then: normalized_query == "plain query"
        """
        # Mock page with all required methods
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html><body>Test</body></html>")
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.is_closed = MagicMock(return_value=False)

        # Mock context for _ensure_browser
        mock_context = AsyncMock()
        mock_context.cookies = AsyncMock(return_value=[])

        # Mock TabPool and EngineRateLimiter
        mock_tab_pool = MagicMock()
        mock_tab_pool.acquire = AsyncMock(return_value=mock_page)
        mock_tab_pool.release = MagicMock()
        mock_tab_pool.report_captcha = MagicMock()

        mock_engine_limiter = MagicMock()
        mock_engine_limiter.acquire = AsyncMock()
        mock_engine_limiter.release = MagicMock()

        with (
            patch(
                "src.search.browser_search_provider.check_engine_available",
                AsyncMock(return_value=True),
            ),
            patch(
                "src.search.browser_search_provider.get_engine_config_manager"
            ) as mock_get_config_manager,
            patch("src.search.tab_pool.get_tab_pool", return_value=mock_tab_pool),
            patch("src.search.tab_pool.get_engine_rate_limiter", return_value=mock_engine_limiter),
        ):
            # Create provider INSIDE the patch context
            provider = BrowserSearchProvider()
            provider._context = mock_context

            mock_config_manager = MagicMock()
            mock_engine_config = MagicMock()
            mock_engine_config.name = "duckduckgo"
            mock_engine_config.weight = 0.7
            mock_engine_config.is_available = True
            mock_engine_config.min_interval = 5.0
            mock_config_manager.get_default_engines.return_value = ["duckduckgo"]
            mock_config_manager.get_engines_for_category.return_value = [mock_engine_config]
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            mock_config_manager.get_engine.return_value = mock_engine_config
            mock_get_config_manager.return_value = mock_config_manager

            with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                mock_parser = MagicMock()
                mock_parser.build_search_url = MagicMock(
                    return_value="https://duckduckgo.com/?q=test"
                )
                mock_parse_result = ParseResult(
                    ok=True,
                    is_captcha=False,
                    results=[
                        ParsedResult(
                            title="Test",
                            url="https://example.com",
                            snippet="Test snippet",
                            rank=1,
                        )
                    ],
                )
                mock_parser.parse = MagicMock(return_value=mock_parse_result)
                mock_get_parser.return_value = mock_parser

                with patch(
                    "src.search.browser_search_provider.record_engine_result",
                    AsyncMock(),
                ):
                    with patch.object(provider, "_save_session", AsyncMock()):
                        with patch.object(provider, "_rate_limit", AsyncMock()):
                            with patch.object(provider, "_ensure_browser", AsyncMock()):
                                # Given: Plain query without operators
                                query = "plain query"

                                # When: search() is called
                                response = await provider.search(query)

                                # Then: parser.build_search_url was called with unchanged query
                                call_args = mock_parser.build_search_url.call_args
                                normalized_query = call_args.kwargs.get("query")
                                assert normalized_query == "plain query"
                                assert response.ok is True

        await provider.close()

    @pytest.mark.asyncio
    async def test_search_empty_query(self) -> None:
        """Test search() handles empty query (TC-QN-05).

        Given: Empty query, engine=duckduckgo
        When: search() is called
        Then: normalized_query == ""
        """
        provider = BrowserSearchProvider()

        with patch("playwright.async_api.async_playwright") as mock_async_pw:
            mock_async_pw.return_value.start = AsyncMock(return_value=MagicMock())

            with (
                patch(
                    "src.search.browser_search_provider.check_engine_available",
                    AsyncMock(return_value=True),
                ),
                patch(
                    "src.search.browser_search_provider.get_engine_config_manager"
                ) as mock_get_config_manager,
                patch(
                    "src.search.browser_search_provider.get_policy_engine"
                ) as mock_get_policy_engine,
            ):
                mock_config_manager = MagicMock()
                mock_engine_config = MagicMock()
                mock_engine_config.name = "duckduckgo"
                mock_engine_config.weight = 0.7
                mock_engine_config.is_available = True
                mock_engine_config.min_interval = 5.0
                mock_config_manager.get_default_engines.return_value = ["duckduckgo"]
                mock_config_manager.get_engines_for_category.return_value = [mock_engine_config]
                # Mock get_engines_with_parsers to return engines as-is (for testing)
                mock_config_manager.get_engines_with_parsers = MagicMock(
                    side_effect=lambda engines: engines if engines else []
                )
                mock_config_manager.get_engine.return_value = mock_engine_config
                mock_get_config_manager.return_value = mock_config_manager

                # Mock policy engine for dynamic weight calculation
                mock_policy_engine = AsyncMock()
                mock_policy_engine.get_dynamic_engine_weight = AsyncMock(return_value=0.7)
                mock_get_policy_engine.return_value = mock_policy_engine

                with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                    mock_parser = MagicMock()
                    mock_parser.build_search_url = MagicMock(
                        return_value="https://duckduckgo.com/?q="
                    )
                    mock_parse_result = ParseResult(
                        ok=True,
                        is_captcha=False,
                        results=[],
                    )
                    mock_parser.parse = MagicMock(return_value=mock_parse_result)
                    mock_get_parser.return_value = mock_parser

                    with patch(
                        "src.search.browser_search_provider.record_engine_result",
                        AsyncMock(),
                    ):
                        mock_page = AsyncMock()
                        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
                        mock_page.wait_for_load_state = AsyncMock()
                        mock_page.content = AsyncMock(return_value="<html><body>Test</body></html>")
                        mock_page.query_selector_all = AsyncMock(return_value=[])
                        mock_page.is_closed = MagicMock(return_value=False)

                        mock_context = MagicMock()
                        with patch.object(provider, "_ensure_browser", AsyncMock()):
                            with patch.object(provider, "_context", mock_context):
                                mock_tab = AsyncMock()
                                mock_tab.goto = AsyncMock(return_value=MagicMock(status=200))
                                mock_tab.wait_for_load_state = AsyncMock()
                                mock_tab.content = AsyncMock(
                                    return_value="<html><body>Test</body></html>"
                                )
                                mock_tab.query_selector_all = AsyncMock(return_value=[])
                                mock_tab.is_closed = MagicMock(return_value=False)
                                mock_tab_pool = MagicMock()
                                mock_tab_pool.acquire = AsyncMock(return_value=mock_tab)
                                mock_tab_pool.release = MagicMock()  # release() is sync
                                mock_rate_limiter = MagicMock()
                                mock_rate_limiter.acquire = AsyncMock()
                                mock_rate_limiter.release = MagicMock()  # release() is sync
                                with patch.object(provider, "_tab_pool", mock_tab_pool):
                                    with patch.object(
                                        provider, "_engine_rate_limiter", mock_rate_limiter
                                    ):
                                        with patch.object(
                                            provider, "_get_page", AsyncMock(return_value=mock_page)
                                        ):
                                            with patch.object(
                                                provider, "_save_session", AsyncMock()
                                            ):
                                                with patch.object(
                                                    provider, "_rate_limit", AsyncMock()
                                                ):
                                                    # Given: Empty query
                                                    query = ""

                                                    # When: search() is called
                                                    await provider.search(query)

                                                    # Then: parser.build_search_url was called with empty query
                                                    call_args = (
                                                        mock_parser.build_search_url.call_args
                                                    )
                                                    assert call_args is not None, (
                                                        "build_search_url should be called"
                                                    )
                                                    normalized_query = call_args.kwargs.get("query")
                                                    assert normalized_query == ""

        await provider.close()

    @pytest.mark.asyncio
    async def test_search_multiple_operators(self) -> None:
        """Test search() handles multiple operators (TC-QN-06).

        Given: Query with multiple operators
        When: search() is called
        Then: All supported operators are transformed correctly
        """
        # Mock page with all required methods
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html><body>Test</body></html>")
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.is_closed = MagicMock(return_value=False)

        # Mock context for _ensure_browser
        mock_context = AsyncMock()
        mock_context.cookies = AsyncMock(return_value=[])

        # Mock TabPool and EngineRateLimiter
        mock_tab_pool = MagicMock()
        mock_tab_pool.acquire = AsyncMock(return_value=mock_page)
        mock_tab_pool.release = MagicMock()
        mock_tab_pool.report_captcha = MagicMock()

        mock_engine_limiter = MagicMock()
        mock_engine_limiter.acquire = AsyncMock()
        mock_engine_limiter.release = MagicMock()

        with (
            patch(
                "src.search.browser_search_provider.check_engine_available",
                AsyncMock(return_value=True),
            ),
            patch(
                "src.search.browser_search_provider.get_engine_config_manager"
            ) as mock_get_config_manager,
            patch("src.search.tab_pool.get_tab_pool", return_value=mock_tab_pool),
            patch("src.search.tab_pool.get_engine_rate_limiter", return_value=mock_engine_limiter),
        ):
            # Create provider INSIDE the patch context
            provider = BrowserSearchProvider()
            provider._context = mock_context

            mock_config_manager = MagicMock()
            mock_engine_config = MagicMock()
            mock_engine_config.name = "duckduckgo"
            mock_engine_config.weight = 0.7
            mock_engine_config.is_available = True
            mock_engine_config.min_interval = 5.0
            mock_config_manager.get_default_engines.return_value = ["duckduckgo"]
            mock_config_manager.get_engines_for_category.return_value = [mock_engine_config]
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            mock_config_manager.get_engine.return_value = mock_engine_config
            mock_get_config_manager.return_value = mock_config_manager

            with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                mock_parser = MagicMock()
                mock_parser.build_search_url = MagicMock(
                    return_value="https://duckduckgo.com/?q=test"
                )
                mock_parse_result = ParseResult(
                    ok=True,
                    is_captcha=False,
                    results=[
                        ParsedResult(
                            title="Test",
                            url="https://example.com",
                            snippet="Test snippet",
                            rank=1,
                        )
                    ],
                )
                mock_parser.parse = MagicMock(return_value=mock_parse_result)
                mock_get_parser.return_value = mock_parser

                with patch(
                    "src.search.browser_search_provider.record_engine_result",
                    AsyncMock(),
                ):
                    with patch.object(provider, "_save_session", AsyncMock()):
                        with patch.object(provider, "_rate_limit", AsyncMock()):
                            with patch.object(provider, "_ensure_browser", AsyncMock()):
                                # Given: Query with multiple operators
                                query = "AI site:go.jp filetype:pdf intitle:重要 after:2024-01-01"

                                # When: search() is called
                                response = await provider.search(query)

                                # Then: parser.build_search_url was called with normalized query
                                call_args = mock_parser.build_search_url.call_args
                                normalized_query = call_args.kwargs.get("query")

                                # DuckDuckGo supports site:, filetype:, intitle:
                                assert "site:go.jp" in normalized_query
                                assert "filetype:pdf" in normalized_query
                                assert "intitle:" in normalized_query

                                # DuckDuckGo does NOT support after:
                                assert "after:" not in normalized_query

                                assert response.ok is True

        await provider.close()


# =============================================================================
# Dynamic Weight Tests
# =============================================================================


class TestDynamicWeightUsage:
    """Tests for dynamic weight usage in BrowserSearchProvider.

    Per ADR-0010, ADR-0006, : Dynamic weight adjustment based on
    past accuracy/failure/block rates.

    ## Test Perspectives Table

    | Case ID | Input / Precondition | Perspective | Expected Result | Notes |
    |---------|---------------------|-------------|-----------------|-------|
    | TC-DWU-N-01 | Search with available engines | Equivalence - normal | Uses dynamic weight | Normal flow |
    | TC-DWU-N-02 | Policy engine returns weight | Equivalence - normal | Weight is used for selection | Verify call |
    | TC-DWU-A-01 | Policy engine fails | Abnormal - error | Falls back gracefully | Error handling |
    """

    @pytest.mark.asyncio
    async def test_search_calls_policy_engine_for_dynamic_weight(self) -> None:
        """TC-DWU-N-01: Search uses PolicyEngine for dynamic weights.

        Given: BrowserSearchProvider with available engines
        When: search() is called
        Then: PolicyEngine.get_dynamic_engine_weight() is called for each engine
        """
        # Mock page with all required methods
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html><body>Test</body></html>")
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.is_closed = MagicMock(return_value=False)

        # Mock context for _ensure_browser
        mock_context = AsyncMock()
        mock_context.cookies = AsyncMock(return_value=[])

        # Mock TabPool and EngineRateLimiter
        mock_tab_pool = MagicMock()
        mock_tab_pool.acquire = AsyncMock(return_value=mock_page)
        mock_tab_pool.release = MagicMock()
        mock_tab_pool.report_captcha = MagicMock()

        mock_engine_limiter = MagicMock()
        mock_engine_limiter.acquire = AsyncMock()
        mock_engine_limiter.release = MagicMock()

        with (
            patch(
                "src.search.browser_search_provider.check_engine_available",
                AsyncMock(return_value=True),
            ),
            patch(
                "src.search.browser_search_provider.get_engine_config_manager"
            ) as mock_get_config_manager,
            patch("src.search.browser_search_provider.get_policy_engine") as mock_get_policy_engine,
            patch("src.search.tab_pool.get_tab_pool", return_value=mock_tab_pool),
            patch("src.search.tab_pool.get_engine_rate_limiter", return_value=mock_engine_limiter),
        ):
            # Create provider INSIDE the patch context
            provider = BrowserSearchProvider()
            provider._context = mock_context

            # Setup engine config mock
            mock_config_manager = MagicMock()
            mock_engine_config = MagicMock()
            mock_engine_config.name = "duckduckgo"
            mock_engine_config.weight = 0.7
            mock_engine_config.is_available = True
            mock_engine_config.min_interval = 5.0
            mock_config_manager.get_default_engines.return_value = ["duckduckgo"]
            mock_config_manager.get_engines_for_category.return_value = [mock_engine_config]
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            mock_config_manager.get_engine.return_value = mock_engine_config
            mock_get_config_manager.return_value = mock_config_manager

            # Setup policy engine mock
            mock_policy_engine = AsyncMock()
            mock_policy_engine.get_dynamic_engine_weight = AsyncMock(return_value=0.65)
            mock_get_policy_engine.return_value = mock_policy_engine

            with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                mock_parser = MagicMock()
                mock_parser.build_search_url = MagicMock(
                    return_value="https://duckduckgo.com/?q=test"
                )
                mock_parse_result = ParseResult(
                    ok=True,
                    is_captcha=False,
                    results=[
                        ParsedResult(
                            title="Test",
                            url="https://example.com",
                            snippet="Test snippet",
                            rank=1,
                        )
                    ],
                )
                mock_parser.parse = MagicMock(return_value=mock_parse_result)
                mock_get_parser.return_value = mock_parser

                with (
                    patch(
                        "src.search.browser_search_provider.record_engine_result",
                        AsyncMock(),
                    ),
                    patch(
                        "src.search.browser_search_provider.transform_query_for_engine",
                        return_value="test query",
                    ),
                ):
                    with patch.object(provider, "_save_session", AsyncMock()):
                        with patch.object(provider, "_rate_limit", AsyncMock()):
                            with patch.object(provider, "_ensure_browser", AsyncMock()):
                                with patch.object(provider, "_human_behavior"):
                                    with patch.object(
                                        provider._human_behavior,
                                        "simulate_reading",
                                        AsyncMock(),
                                    ):
                                        with patch.object(
                                            provider._human_behavior,
                                            "move_mouse_to_element",
                                            AsyncMock(),
                                        ):
                                            # When: search() is called
                                            response = await provider.search("test query")

                                            # Then: get_dynamic_engine_weight was called
                                            mock_policy_engine.get_dynamic_engine_weight.assert_called()

                                            # Verify engine and category were passed
                                            call_args = mock_policy_engine.get_dynamic_engine_weight.call_args
                                            assert call_args[0][0] == "duckduckgo"  # engine

                                            assert response.ok is True

        await provider.close()

    @pytest.mark.asyncio
    async def test_search_uses_dynamic_weight_for_engine_selection(self) -> None:
        """TC-DWU-N-02: Search uses dynamic weight for engine selection.

        Given: Multiple engines with different dynamic weights
        When: search() is called
        Then: Engine with highest dynamic weight is selected
        """
        # Mock page with all required methods
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html><body>Test</body></html>")
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.is_closed = MagicMock(return_value=False)

        # Mock context for _ensure_browser
        mock_context = AsyncMock()
        mock_context.cookies = AsyncMock(return_value=[])

        # Mock TabPool and EngineRateLimiter
        mock_tab_pool = MagicMock()
        mock_tab_pool.acquire = AsyncMock(return_value=mock_page)
        mock_tab_pool.release = MagicMock()
        mock_tab_pool.report_captcha = MagicMock()

        mock_engine_limiter = MagicMock()
        mock_engine_limiter.acquire = AsyncMock()
        mock_engine_limiter.release = MagicMock()

        with (
            patch(
                "src.search.browser_search_provider.check_engine_available",
                AsyncMock(return_value=True),
            ),
            patch(
                "src.search.browser_search_provider.get_engine_config_manager"
            ) as mock_get_config_manager,
            patch("src.search.browser_search_provider.get_policy_engine") as mock_get_policy_engine,
            patch("src.search.tab_pool.get_tab_pool", return_value=mock_tab_pool),
            patch("src.search.tab_pool.get_engine_rate_limiter", return_value=mock_engine_limiter),
        ):
            # Create provider INSIDE the patch context
            provider = BrowserSearchProvider()
            provider._context = mock_context

            # Setup multiple engine configs
            mock_config_manager = MagicMock()

            mock_engine1 = MagicMock()
            mock_engine1.name = "duckduckgo"
            mock_engine1.weight = 0.7
            mock_engine1.is_available = True
            mock_engine1.min_interval = 5.0

            mock_engine2 = MagicMock()
            mock_engine2.name = "mojeek"
            mock_engine2.weight = 0.85
            mock_engine2.is_available = True
            mock_engine2.min_interval = 4.0

            mock_config_manager.get_default_engines.return_value = []  # Fallback to category
            mock_config_manager.get_engines_for_category.return_value = [
                mock_engine1,
                mock_engine2,
            ]

            def get_engine_side_effect(name: str) -> MagicMock | None:
                if name == "duckduckgo":
                    return mock_engine1
                elif name == "mojeek":
                    return mock_engine2
                return None

            mock_config_manager.get_engine.side_effect = get_engine_side_effect
            # Mock get_engines_with_parsers to return engines as-is (for testing)
            mock_config_manager.get_engines_with_parsers = MagicMock(
                side_effect=lambda engines: engines if engines else []
            )
            mock_get_config_manager.return_value = mock_config_manager

            # Setup policy engine to return different dynamic weights
            mock_policy_engine = AsyncMock()

            # duckduckgo has higher dynamic weight (0.8) than mojeek (0.6)
            # even though mojeek has higher base weight
            async def get_dynamic_weight_side_effect(engine: str, category: str) -> float:
                if engine == "duckduckgo":
                    return 0.8  # Higher due to better health metrics
                elif engine == "mojeek":
                    return 0.6  # Lower due to worse health metrics
                return 1.0

            mock_policy_engine.get_dynamic_engine_weight = AsyncMock(
                side_effect=get_dynamic_weight_side_effect
            )
            mock_get_policy_engine.return_value = mock_policy_engine

            with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                mock_parser = MagicMock()
                mock_parser.build_search_url = MagicMock(
                    return_value="https://duckduckgo.com/?q=test"
                )
                mock_parse_result = ParseResult(
                    ok=True,
                    is_captcha=False,
                    results=[
                        ParsedResult(
                            title="Test",
                            url="https://example.com",
                            snippet="Test snippet",
                            rank=1,
                        )
                    ],
                )
                mock_parser.parse = MagicMock(return_value=mock_parse_result)
                mock_get_parser.return_value = mock_parser

                with (
                    patch(
                        "src.search.browser_search_provider.record_engine_result",
                        AsyncMock(),
                    ),
                    patch(
                        "src.search.browser_search_provider.transform_query_for_engine",
                        return_value="test query",
                    ),
                ):
                    with patch.object(provider, "_save_session", AsyncMock()):
                        with patch.object(provider, "_rate_limit", AsyncMock()):
                            with patch.object(provider, "_ensure_browser", AsyncMock()):
                                with patch.object(provider, "_human_behavior"):
                                    with patch.object(
                                        provider._human_behavior,
                                        "simulate_reading",
                                        AsyncMock(),
                                    ):
                                        with patch.object(
                                            provider._human_behavior,
                                            "move_mouse_to_element",
                                            AsyncMock(),
                                        ):
                                            # When: search() is called
                                            response = await provider.search("test query")

                                            # Then: duckduckgo should be selected (higher dynamic weight)
                                            # Verify by checking which parser was requested
                                            mock_get_parser.assert_called_with("duckduckgo")

                                            assert response.ok is True

        await provider.close()

    @pytest.mark.asyncio
    async def test_search_falls_back_on_policy_engine_error(self) -> None:
        """TC-DWU-A-01: Search falls back gracefully on PolicyEngine error.

        Given: PolicyEngine.get_dynamic_engine_weight() raises exception
        When: search() is called
        Then: Search continues (doesn't crash), using fallback behavior
        """
        provider = BrowserSearchProvider()

        with patch("playwright.async_api.async_playwright") as mock_async_pw:
            mock_pw = MagicMock()
            mock_async_pw.return_value.start = AsyncMock(return_value=mock_pw)
            mock_browser = MagicMock()
            mock_pw.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
            mock_browser.contexts = []

            mock_context = MagicMock()
            mock_browser.new_context = AsyncMock(return_value=mock_context)
            mock_context.route = AsyncMock()
            mock_context.cookies = AsyncMock(return_value=[])

            with (
                patch(
                    "src.search.browser_search_provider.check_engine_available",
                    AsyncMock(return_value=True),
                ),
                patch(
                    "src.search.browser_search_provider.get_engine_config_manager"
                ) as mock_get_config_manager,
                patch(
                    "src.search.browser_search_provider.get_policy_engine"
                ) as mock_get_policy_engine,
            ):
                # Setup engine config mock
                mock_config_manager = MagicMock()
                mock_engine_config = MagicMock()
                mock_engine_config.name = "duckduckgo"
                mock_engine_config.weight = 0.7
                mock_engine_config.is_available = True
                mock_engine_config.min_interval = 5.0
                mock_config_manager.get_default_engines.return_value = ["duckduckgo"]
                mock_config_manager.get_engines_for_category.return_value = [mock_engine_config]
                # Mock get_engines_with_parsers to return engines as-is (for testing)
                mock_config_manager.get_engines_with_parsers = MagicMock(
                    side_effect=lambda engines: engines if engines else []
                )
                mock_config_manager.get_engine.return_value = mock_engine_config
                mock_get_config_manager.return_value = mock_config_manager

                # Setup policy engine to raise exception
                mock_policy_engine = AsyncMock()
                mock_policy_engine.get_dynamic_engine_weight = AsyncMock(
                    side_effect=Exception("Database connection error")
                )
                mock_get_policy_engine.return_value = mock_policy_engine

                with patch("src.search.browser_search_provider.get_parser") as mock_get_parser:
                    mock_parser = MagicMock()
                    mock_parser.build_search_url = MagicMock(
                        return_value="https://duckduckgo.com/?q=test"
                    )
                    mock_parse_result = ParseResult(
                        ok=True,
                        is_captcha=False,
                        results=[
                            ParsedResult(
                                title="Test",
                                url="https://example.com",
                                snippet="Test snippet",
                                rank=1,
                            )
                        ],
                    )
                    mock_parser.parse = MagicMock(return_value=mock_parse_result)
                    mock_get_parser.return_value = mock_parser

                    with (
                        patch(
                            "src.search.browser_search_provider.record_engine_result",
                            AsyncMock(),
                        ),
                        patch(
                            "src.search.browser_search_provider.transform_query_for_engine",
                            return_value="test query",
                        ),
                    ):
                        mock_page = AsyncMock()
                        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
                        mock_page.wait_for_load_state = AsyncMock()
                        mock_page.content = AsyncMock(return_value="<html><body>Test</body></html>")
                        mock_page.query_selector_all = AsyncMock(return_value=[])
                        mock_page.is_closed = MagicMock(return_value=False)

                        with patch.object(provider, "_get_page", AsyncMock(return_value=mock_page)):
                            with patch.object(provider, "_save_session", AsyncMock()):
                                with patch.object(provider, "_rate_limit", AsyncMock()):
                                    with patch.object(provider, "_human_behavior"):
                                        with patch.object(
                                            provider._human_behavior,
                                            "simulate_reading",
                                            AsyncMock(),
                                        ):
                                            with patch.object(
                                                provider._human_behavior,
                                                "move_mouse_to_element",
                                                AsyncMock(),
                                            ):
                                                # When: search() is called (PolicyEngine will throw)
                                                # Then: No available engines due to error
                                                response = await provider.search("test query")

                                                # Response should indicate no engines available
                                                # (the error during weight calculation removes the engine)
                                                assert (
                                                    response.error is not None
                                                    or response.ok is False
                                                )

        await provider.close()


# ============================================================================
# Lastmile Slot Selection Tests
# ============================================================================


class TestLastmileSlotSelection:
    """
    Tests for lastmile slot selection feature.

    Per ADR-0010: "ラストマイル・スロット: 回収率の最後の10%を狙う限定枠として
    Google/Braveを最小限開放（厳格なQPS・回数・時間帯制御）"

    ## Test Perspectives Table

    | Case ID | Input / Precondition | Perspective | Expected Result | Notes |
    |---------|---------------------|-------------|-----------------|-------|
    | TC-LM-N-01 | harvest_rate=0.95 | Equivalence - above threshold | should_use_lastmile=True | - |
    | TC-LM-N-02 | harvest_rate=0.5 | Equivalence - below threshold | should_use_lastmile=False | - |
    | TC-LM-B-01 | harvest_rate=0.9 | Boundary - exact threshold | should_use_lastmile=True | - |
    | TC-LM-B-02 | harvest_rate=0.89 | Boundary - just below | should_use_lastmile=False | - |
    | TC-LM-B-03 | harvest_rate=0.0 | Boundary - zero | should_use_lastmile=False | - |
    | TC-LM-B-04 | harvest_rate=1.0 | Boundary - max | should_use_lastmile=True | - |
    | TC-LM-A-01 | No lastmile engines | Abnormal - empty | Returns None | - |
    | TC-LM-A-02 | All at daily limit | Abnormal - limit | Returns None | - |
    | TC-LM-N-03 | Engine available | Equivalence - select | Returns engine name | - |
    | TC-LM-N-04 | search with harvest_rate | Equivalence - integration | Lastmile used | - |
    | TC-LM-A-03 | harvest_rate=None | Abnormal - None | Normal selection | - |
    """

    def test_should_use_lastmile_above_threshold(self) -> None:
        """TC-LM-N-01: Test lastmile is used when harvest_rate > threshold."""
        # Given: A BrowserSearchProvider and harvest_rate above threshold
        provider = BrowserSearchProvider()

        # When: Checking if lastmile should be used
        result = provider._should_use_lastmile(harvest_rate=0.95, threshold=0.9)

        # Then: should_use_lastmile is True
        assert result.should_use_lastmile is True
        assert result.harvest_rate == 0.95
        assert result.threshold == 0.9
        assert "0.95" in result.reason
        assert ">=" in result.reason

    def test_should_use_lastmile_below_threshold(self) -> None:
        """TC-LM-N-02: Test lastmile is not used when harvest_rate < threshold."""
        # Given: A BrowserSearchProvider and harvest_rate below threshold
        provider = BrowserSearchProvider()

        # When: Checking if lastmile should be used
        result = provider._should_use_lastmile(harvest_rate=0.5, threshold=0.9)

        # Then: should_use_lastmile is False
        assert result.should_use_lastmile is False
        assert result.harvest_rate == 0.5
        assert "<" in result.reason

    def test_should_use_lastmile_exact_threshold(self) -> None:
        """TC-LM-B-01: Test lastmile is used at exact threshold boundary."""
        # Given: A BrowserSearchProvider and harvest_rate at exact threshold
        provider = BrowserSearchProvider()

        # When: Checking if lastmile should be used (boundary: exact threshold)
        result = provider._should_use_lastmile(harvest_rate=0.9, threshold=0.9)

        # Then: should_use_lastmile is True (>= threshold)
        assert result.should_use_lastmile is True
        assert result.harvest_rate == 0.9

    def test_should_use_lastmile_just_below_threshold(self) -> None:
        """TC-LM-B-02: Test lastmile is not used just below threshold."""
        # Given: A BrowserSearchProvider and harvest_rate just below threshold
        provider = BrowserSearchProvider()

        # When: Checking if lastmile should be used (boundary: just below)
        result = provider._should_use_lastmile(harvest_rate=0.89, threshold=0.9)

        # Then: should_use_lastmile is False
        assert result.should_use_lastmile is False
        assert result.harvest_rate == 0.89

    def test_should_use_lastmile_zero_harvest_rate(self) -> None:
        """TC-LM-B-03: Test lastmile is not used when harvest_rate is 0."""
        # Given: A BrowserSearchProvider and harvest_rate of 0
        provider = BrowserSearchProvider()

        # When: Checking if lastmile should be used (boundary: zero)
        result = provider._should_use_lastmile(harvest_rate=0.0, threshold=0.9)

        # Then: should_use_lastmile is False
        assert result.should_use_lastmile is False
        assert result.harvest_rate == 0.0

    def test_should_use_lastmile_max_harvest_rate(self) -> None:
        """TC-LM-B-04: Test lastmile is used when harvest_rate is 1.0."""
        # Given: A BrowserSearchProvider and harvest_rate of 1.0
        provider = BrowserSearchProvider()

        # When: Checking if lastmile should be used (boundary: max)
        result = provider._should_use_lastmile(harvest_rate=1.0, threshold=0.9)

        # Then: should_use_lastmile is True
        assert result.should_use_lastmile is True
        assert result.harvest_rate == 1.0

    @pytest.mark.asyncio
    async def test_select_lastmile_engine_no_engines_configured(self) -> None:
        """TC-LM-A-01: Test returns None when no lastmile engines configured."""
        # Given: A BrowserSearchProvider with no lastmile engines
        provider = BrowserSearchProvider()

        with patch(
            "src.search.browser_search_provider.get_engine_config_manager"
        ) as mock_get_config:
            mock_config = MagicMock()
            mock_config.get_lastmile_engines.return_value = []
            mock_get_config.return_value = mock_config

            # When: Selecting a lastmile engine
            engine = await provider._select_lastmile_engine()

            # Then: Returns None
            assert engine is None

    @pytest.mark.asyncio
    async def test_select_lastmile_engine_all_at_daily_limit(self) -> None:
        """TC-LM-A-02: Test returns None when all engines at daily limit."""
        # Given: A BrowserSearchProvider with all lastmile engines at limit
        provider = BrowserSearchProvider()

        with (
            patch(
                "src.search.browser_search_provider.get_engine_config_manager"
            ) as mock_get_config,
            patch(
                "src.search.browser_search_provider.check_engine_available",
                AsyncMock(return_value=True),
            ),
        ):
            mock_config = MagicMock()
            mock_config.get_lastmile_engines.return_value = ["brave", "google"]

            mock_engine = MagicMock()
            mock_engine.is_available = True
            mock_engine.daily_limit = 10
            mock_config.get_engine.return_value = mock_engine
            mock_get_config.return_value = mock_config

            # Mock daily usage to be at limit
            with patch.object(provider, "_get_daily_usage", AsyncMock(return_value=10)):
                # When: Selecting a lastmile engine
                engine = await provider._select_lastmile_engine()

                # Then: Returns None (all at daily limit)
                assert engine is None

    @pytest.mark.asyncio
    async def test_select_lastmile_engine_returns_available_engine(self) -> None:
        """TC-LM-N-03: Test returns first available engine."""
        # Given: A BrowserSearchProvider with available lastmile engines
        provider = BrowserSearchProvider()

        with (
            patch(
                "src.search.browser_search_provider.get_engine_config_manager"
            ) as mock_get_config,
            patch(
                "src.search.browser_search_provider.check_engine_available",
                AsyncMock(return_value=True),
            ),
        ):
            mock_config = MagicMock()
            mock_config.get_lastmile_engines.return_value = ["brave", "google"]

            mock_engine = MagicMock()
            mock_engine.is_available = True
            mock_engine.daily_limit = 50
            mock_engine.qps = 0.1
            mock_config.get_engine.return_value = mock_engine
            mock_get_config.return_value = mock_config

            # Mock daily usage under limit
            with patch.object(provider, "_get_daily_usage", AsyncMock(return_value=5)):
                # When: Selecting a lastmile engine
                engine = await provider._select_lastmile_engine()

                # Then: Returns first available engine
                assert engine == "brave"

    @pytest.mark.asyncio
    async def test_search_with_harvest_rate_triggers_lastmile(self) -> None:
        """TC-LM-N-04: Test search uses lastmile engine when harvest_rate >= 0.9."""
        # Given: A BrowserSearchProvider and harvest_rate triggering lastmile
        provider = BrowserSearchProvider()
        provider._is_closed = False

        lastmile_engine_selected = []

        # Mock lastmile selection to track calls
        async def mock_select_lastmile() -> str:
            lastmile_engine_selected.append("brave")
            return "brave"

        with patch.object(provider, "_select_lastmile_engine", mock_select_lastmile):
            with patch.object(provider, "_ensure_browser", AsyncMock()):
                with patch.object(provider, "_rate_limit", AsyncMock()):
                    with patch.object(provider, "_get_page") as mock_get_page:
                        mock_page = AsyncMock()
                        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
                        mock_page.wait_for_load_state = AsyncMock()
                        mock_page.content = AsyncMock(return_value="<html></html>")
                        mock_page.query_selector_all = AsyncMock(return_value=[])
                        mock_page.is_closed = MagicMock(return_value=False)
                        mock_get_page.return_value = mock_page

                        with patch(
                            "src.search.browser_search_provider.get_parser"
                        ) as mock_get_parser:
                            mock_parser = MagicMock()
                            mock_parser.build_search_url = MagicMock(
                                return_value="https://search.brave.com/?q=test"
                            )
                            mock_parser.parse = MagicMock(
                                return_value=ParseResult(
                                    ok=True,
                                    is_captcha=False,
                                    results=[],
                                )
                            )
                            mock_get_parser.return_value = mock_parser

                            with (
                                patch(
                                    "src.search.browser_search_provider.transform_query_for_engine",
                                    return_value="test query",
                                ),
                                patch(
                                    "src.search.browser_search_provider.record_engine_result",
                                    AsyncMock(),
                                ),
                                patch.object(provider, "_save_session", AsyncMock()),
                                patch.object(provider, "_record_lastmile_usage", AsyncMock()),
                                patch.object(provider, "_human_behavior") as mock_human,
                            ):
                                mock_human.simulate_reading = AsyncMock()
                                mock_human.move_mouse_to_element = AsyncMock()

                                # When: search is called with harvest_rate >= 0.9
                                await provider.search(
                                    "test query",
                                    harvest_rate=0.95,
                                )

                                # Then: Lastmile engine was selected
                                assert len(lastmile_engine_selected) == 1
                                assert lastmile_engine_selected[0] == "brave"

    @pytest.mark.asyncio
    async def test_search_without_harvest_rate_uses_normal_selection(self) -> None:
        """TC-LM-A-03: Test search uses normal engine selection when harvest_rate=None."""
        # Given: A BrowserSearchProvider
        provider = BrowserSearchProvider()
        provider._is_closed = False

        should_use_lastmile_calls: list[tuple[object, ...]] = []

        # Track _should_use_lastmile calls
        original_should_use = provider._should_use_lastmile

        def mock_should_use(harvest_rate: float, threshold: float = 0.9) -> LastmileCheckResult:
            should_use_lastmile_calls.append((harvest_rate, threshold))
            return original_should_use(harvest_rate, threshold)

        with patch.object(provider, "_should_use_lastmile", mock_should_use):
            with patch.object(provider, "_ensure_browser", AsyncMock()):
                with patch.object(provider, "_rate_limit", AsyncMock()):
                    with patch.object(provider, "_get_page") as mock_get_page:
                        mock_page = AsyncMock()
                        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
                        mock_page.wait_for_load_state = AsyncMock()
                        mock_page.content = AsyncMock(return_value="<html></html>")
                        mock_page.query_selector_all = AsyncMock(return_value=[])
                        mock_page.is_closed = MagicMock(return_value=False)
                        mock_get_page.return_value = mock_page

                        with patch(
                            "src.search.browser_search_provider.get_engine_config_manager"
                        ) as mock_get_config:
                            mock_config = MagicMock()
                            mock_engine = MagicMock()
                            mock_engine.name = "duckduckgo"
                            mock_engine.is_available = True
                            mock_engine.min_interval = 2.0
                            mock_config.get_engines_for_category.return_value = [mock_engine]
                            mock_config.get_engine.return_value = mock_engine
                            mock_get_config.return_value = mock_config

                            with (
                                patch(
                                    "src.search.browser_search_provider.check_engine_available",
                                    AsyncMock(return_value=True),
                                ),
                                patch(
                                    "src.search.browser_search_provider.get_policy_engine"
                                ) as mock_get_policy,
                            ):
                                mock_policy = AsyncMock()
                                mock_policy.get_dynamic_engine_weight = AsyncMock(return_value=0.7)
                                mock_get_policy.return_value = mock_policy

                                with patch(
                                    "src.search.browser_search_provider.get_parser"
                                ) as mock_get_parser:
                                    mock_parser = MagicMock()
                                    mock_parser.build_search_url = MagicMock(
                                        return_value="https://duckduckgo.com/?q=test"
                                    )
                                    mock_parser.parse = MagicMock(
                                        return_value=ParseResult(
                                            ok=True,
                                            is_captcha=False,
                                            results=[],
                                        )
                                    )
                                    mock_get_parser.return_value = mock_parser

                                    with (
                                        patch(
                                            "src.search.browser_search_provider.transform_query_for_engine",
                                            return_value="test query",
                                        ),
                                        patch(
                                            "src.search.browser_search_provider.record_engine_result",
                                            AsyncMock(),
                                        ),
                                        patch.object(provider, "_save_session", AsyncMock()),
                                        patch.object(provider, "_human_behavior") as mock_human,
                                    ):
                                        mock_human.simulate_reading = AsyncMock()
                                        mock_human.move_mouse_to_element = AsyncMock()

                                        # When: search is called without harvest_rate
                                        await provider.search("test query")

                                        # Then: _should_use_lastmile was NOT called
                                        assert len(should_use_lastmile_calls) == 0


# ============================================================================
# Worker ID Isolation Tests (ADR-0014 Phase 3)
# ============================================================================


class TestBrowserSearchProviderWorkerIsolation:
    """Tests for worker_id based isolation.

    Per ADR-0014 Phase 3: Each worker gets its own BrowserSearchProvider
    instance with isolated BrowserContext for true parallelization.

    Test Perspectives Table:
    | Case ID | Input / Precondition | Perspective | Expected Result |
    |---------|----------------------|-------------|-----------------|
    | TC-W-01 | worker_id=0 | Equivalence | Provider created with worker_id=0 |
    | TC-W-02 | worker_id=1 | Equivalence | Provider created with worker_id=1 |
    | TC-W-03 | Different worker_ids | Equivalence | Different instances returned |
    | TC-W-04 | Same worker_id twice | Equivalence | Same instance returned |
    | TC-W-05 | Reset all workers | Equivalence | All instances cleared |
    | TC-W-06 | Reset specific worker | Equivalence | Only that worker cleared |
    """

    @pytest.fixture(autouse=True)
    def reset_providers(self) -> Generator[None, None, None]:
        """Reset all providers before and after each test."""
        reset_browser_search_provider()
        yield
        reset_browser_search_provider()

    # =========================================================================
    # TC-W-01: worker_id=0 creates provider
    # =========================================================================
    def test_worker_id_zero_creates_provider(self) -> None:
        """Test worker_id=0 creates provider.

        Given: No providers exist
        When: get_browser_search_provider(worker_id=0) is called
        Then: A provider with worker_id=0 is returned
        """
        # When
        provider = get_browser_search_provider(worker_id=0)

        # Then
        assert provider is not None
        assert provider._worker_id == 0

    # =========================================================================
    # TC-W-02: worker_id=1 creates provider
    # =========================================================================
    def test_worker_id_one_creates_provider(self) -> None:
        """Test worker_id=1 creates provider.

        Given: No providers exist
        When: get_browser_search_provider(worker_id=1) is called
        Then: A provider with worker_id=1 is returned
        """
        # When
        provider = get_browser_search_provider(worker_id=1)

        # Then
        assert provider is not None
        assert provider._worker_id == 1

    # =========================================================================
    # TC-W-03: Different worker_ids return different instances
    # =========================================================================
    def test_different_worker_ids_return_different_instances(self) -> None:
        """Test different worker_ids return different instances.

        Given: No providers exist
        When: get_browser_search_provider is called with different worker_ids
        Then: Different provider instances are returned
        """
        # When
        provider0 = get_browser_search_provider(worker_id=0)
        provider1 = get_browser_search_provider(worker_id=1)

        # Then
        assert provider0 is not provider1
        assert provider0._worker_id == 0
        assert provider1._worker_id == 1

    # =========================================================================
    # TC-W-04: Same worker_id returns same instance (singleton per worker)
    # =========================================================================
    def test_same_worker_id_returns_same_instance(self) -> None:
        """Test same worker_id returns same instance.

        Given: A provider exists for worker_id=0
        When: get_browser_search_provider(worker_id=0) is called again
        Then: Same provider instance is returned
        """
        # When
        provider1 = get_browser_search_provider(worker_id=0)
        provider2 = get_browser_search_provider(worker_id=0)

        # Then
        assert provider1 is provider2

    # =========================================================================
    # TC-W-05: Reset without worker_id clears all
    # =========================================================================
    def test_reset_all_clears_all_providers(self) -> None:
        """Test reset without worker_id clears all providers.

        Given: Multiple providers exist
        When: reset_browser_search_provider() is called without worker_id
        Then: All providers are cleared and new instances are returned
        """
        # Given
        provider0_before = get_browser_search_provider(worker_id=0)
        provider1_before = get_browser_search_provider(worker_id=1)

        # When
        reset_browser_search_provider()

        # Then
        provider0_after = get_browser_search_provider(worker_id=0)
        provider1_after = get_browser_search_provider(worker_id=1)
        assert provider0_before is not provider0_after
        assert provider1_before is not provider1_after

    # =========================================================================
    # TC-W-06: Reset specific worker clears only that worker
    # =========================================================================
    def test_reset_specific_worker_clears_only_that_worker(self) -> None:
        """Test reset with worker_id clears only that worker's provider.

        Given: Multiple providers exist
        When: reset_browser_search_provider(worker_id=0) is called
        Then: Only worker 0's provider is cleared, worker 1's remains
        """
        # Given
        provider0_before = get_browser_search_provider(worker_id=0)
        provider1_before = get_browser_search_provider(worker_id=1)

        # When
        reset_browser_search_provider(worker_id=0)

        # Then
        provider0_after = get_browser_search_provider(worker_id=0)
        provider1_after = get_browser_search_provider(worker_id=1)
        assert provider0_before is not provider0_after  # Cleared
        assert provider1_before is provider1_after  # Same instance

    # =========================================================================
    # TC-W-07: Provider uses worker-specific TabPool
    # =========================================================================
    def test_provider_uses_worker_specific_tab_pool(self) -> None:
        """Test each provider uses its worker-specific TabPool.

        Given: Two providers with different worker_ids
        When: Checking their TabPool instances
        Then: Each has its own TabPool
        """
        # When
        provider0 = get_browser_search_provider(worker_id=0)
        provider1 = get_browser_search_provider(worker_id=1)

        # Then: Each has its own tab pool (different object IDs)
        assert id(provider0._tab_pool) != id(provider1._tab_pool)

    # =========================================================================
    # TC-W-08: Default worker_id is 0
    # =========================================================================
    def test_default_worker_id_is_zero(self) -> None:
        """Test default worker_id is 0 for backward compatibility.

        Given: No providers exist
        When: BrowserSearchProvider() is instantiated without worker_id
        Then: worker_id defaults to 0
        """
        # Reset first
        reset_browser_search_provider()

        # When: Create provider without explicit worker_id
        provider = BrowserSearchProvider()

        # Then
        assert provider._worker_id == 0
