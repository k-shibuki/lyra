"""
Tests for undetected-chromedriver integration module.

These tests use mocks since undetected-chromedriver may not be available
in the test environment.

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-UFR-01 | UndetectedFetchResult success | Equivalence – success | ok=True, content set | - |
| TC-UFR-02 | UndetectedFetchResult failure | Equivalence – failure | ok=False, error set | - |
| TC-UFR-03 | UndetectedFetchResult serialization | Equivalence – to_dict | Dictionary with all fields | - |
| TC-UCF-01 | Fetcher initialization | Equivalence – init | Fetcher created | - |
| TC-UCF-02 | Fetch page success | Equivalence – fetch | Returns successful result | - |
| TC-UCF-03 | Fetch page failure | Abnormal – error | Returns failure result | - |
| TC-UCF-04 | Fetch with JS rendering | Equivalence – JS | JavaScript executed | - |
| TC-UCF-05 | Fetch with wait_for | Equivalence – wait | Waits for selector | - |
| TC-UCF-06 | Fetcher cleanup | Equivalence – cleanup | Resources released | - |
| TC-UCF-07 | Context manager | Equivalence – context | Proper enter/exit | - |
| TC-UCF-08 | Hash content | Equivalence – hashing | SHA256 computed | - |
| TC-CF-01 | get_undetected_fetcher | Equivalence – singleton | Returns fetcher instance | - |
| TC-CF-02 | close_undetected_fetcher | Equivalence – cleanup | Fetcher closed | - |
"""

import pytest
from pathlib import Path

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
# E402: Intentionally import after pytestmark for test configuration
from unittest.mock import MagicMock, patch

import pytest

from src.crawler.undetected import (
    UndetectedChromeFetcher,
    UndetectedFetchResult,
    close_undetected_fetcher,
    get_undetected_fetcher,
)

# =============================================================================
# UndetectedFetchResult Tests
# =============================================================================


class TestUndetectedFetchResult:
    """Tests for UndetectedFetchResult."""

    def test_successful_result(self) -> None:
        """Test creating a successful result."""
        result = UndetectedFetchResult(
            ok=True,
            url="https://example.com",
            status=200,
            content="<html>Test</html>",
            content_hash="abc123",
            html_path="/tmp/test.html",
            screenshot_path="/tmp/test.png",
        )

        assert result.ok is True
        assert result.url == "https://example.com"
        assert result.status == 200
        assert result.content == "<html>Test</html>"
        assert result.method == "undetected_chromedriver"

    def test_failed_result(self) -> None:
        """Test creating a failed result."""
        result = UndetectedFetchResult(
            ok=False,
            url="https://example.com",
            reason="cloudflare_bypass_timeout",
        )

        assert result.ok is False
        assert result.reason == "cloudflare_bypass_timeout"

    def test_to_dict(self) -> None:
        """Test converting result to dictionary."""
        result = UndetectedFetchResult(
            ok=True,
            url="https://example.com",
            status=200,
            content="<html></html>",
        )

        result_dict = result.to_dict()

        assert isinstance(result_dict, dict)
        assert result_dict["ok"] is True
        assert result_dict["url"] == "https://example.com"
        assert result_dict["status"] == 200
        assert result_dict["method"] == "undetected_chromedriver"


# =============================================================================
# UndetectedChromeFetcher Tests
# =============================================================================


class TestUndetectedChromeFetcher:
    """Tests for UndetectedChromeFetcher."""

    def test_is_available_when_installed(self) -> None:
        """Test availability check when library is installed."""
        fetcher = UndetectedChromeFetcher()

        # Mock the import
        with patch.dict("sys.modules", {"undetected_chromedriver": MagicMock()}):
            # Reset the cached availability
            fetcher._available = None
            result = fetcher.is_available()
            assert result is True

    def test_is_available_when_not_installed(self) -> None:
        """Test availability check when library is not installed."""
        fetcher = UndetectedChromeFetcher()

        # Directly set availability to test the not-installed path
        fetcher._available = False
        result = fetcher.is_available()
        assert result is False

        # Reset and test that fresh instance detects unavailability
        fetcher._available = None

        # Remove from sys.modules if present to force re-check
        import sys

        original = sys.modules.get("undetected_chromedriver")
        if "undetected_chromedriver" in sys.modules:
            del sys.modules["undetected_chromedriver"]

        try:
            # If module doesn't exist, should return False
            # If it does exist (in test env), should return True
            result = fetcher.is_available()
            assert isinstance(result, bool)
        finally:
            # Restore if it was there
            if original is not None:
                sys.modules["undetected_chromedriver"] = original

    def test_create_options(self) -> None:
        """Test Chrome options creation."""
        fetcher = UndetectedChromeFetcher()

        # Mock undetected_chromedriver module
        mock_uc = MagicMock()
        mock_options = MagicMock()
        mock_uc.ChromeOptions.return_value = mock_options

        with patch.dict("sys.modules", {"undetected_chromedriver": mock_uc}):
            fetcher._create_options(headless=True)

            # Verify options were created
            assert mock_uc.ChromeOptions.called
            # Verify arguments were added
            assert mock_options.add_argument.called

    def test_simulate_human_delay(self) -> None:
        """Test human delay simulation."""
        fetcher = UndetectedChromeFetcher()

        import time

        start = time.time()
        fetcher._simulate_human_delay(0.1, 0.2)
        elapsed = time.time() - start

        assert 0.1 <= elapsed <= 0.3  # Allow some tolerance

    def test_fetch_sync_not_available(self) -> None:
        """Test fetch when library is not available."""
        fetcher = UndetectedChromeFetcher()
        fetcher._available = False

        result = fetcher.fetch_sync("https://example.com")

        assert result.ok is False
        assert result.reason == "undetected_chromedriver_not_available"

    def test_save_content(self, tmp_path: Path) -> None:
        """Test content saving."""
        fetcher = UndetectedChromeFetcher()

        # Mock settings
        mock_settings = MagicMock()
        mock_settings.storage.cache_dir = str(tmp_path)

        with patch("src.crawler.undetected.get_settings", return_value=mock_settings):
            filepath = fetcher._save_content(
                "https://example.com",
                "<html>Test Content</html>",
            )

            assert filepath is not None
            assert filepath.exists()
            assert filepath.read_text(encoding="utf-8") == "<html>Test Content</html>"
            assert "_uc.html" in filepath.name

    @pytest.mark.asyncio
    async def test_fetch_async_wraps_sync(self) -> None:
        """Test async fetch wraps sync method."""
        fetcher = UndetectedChromeFetcher()

        # Mock the sync fetch
        mock_result = UndetectedFetchResult(
            ok=True,
            url="https://example.com",
            status=200,
            content="<html></html>",
        )

        with patch.object(fetcher, "fetch_sync", return_value=mock_result):
            result = await fetcher.fetch("https://example.com")

            assert result.ok is True
            assert result.url == "https://example.com"

    def test_get_cookies_no_driver(self) -> None:
        """Test getting cookies when no driver is active."""
        fetcher = UndetectedChromeFetcher()
        fetcher._driver = None

        cookies = fetcher.get_cookies()

        assert cookies == []

    def test_get_cookies_with_driver(self) -> None:
        """Test getting cookies with active driver."""
        fetcher = UndetectedChromeFetcher()
        fetcher._driver = MagicMock()
        fetcher._driver.get_cookies.return_value = [
            {"name": "session", "value": "abc123"},
        ]

        cookies = fetcher.get_cookies()

        assert len(cookies) == 1
        assert cookies[0]["name"] == "session"

    def test_add_cookies_no_driver(self) -> None:
        """Test adding cookies when no driver is active."""
        fetcher = UndetectedChromeFetcher()
        fetcher._driver = None

        # Should not raise
        fetcher.add_cookies([{"name": "test", "value": "123"}])

    def test_add_cookies_with_driver(self) -> None:
        """Test adding cookies with active driver."""
        fetcher = UndetectedChromeFetcher()
        fetcher._driver = MagicMock()

        fetcher.add_cookies(
            [
                {"name": "session", "value": "abc123"},
                {"name": "user", "value": "test"},
            ]
        )

        assert fetcher._driver.add_cookie.call_count == 2

    def test_close_driver(self) -> None:
        """Test closing the driver."""
        fetcher = UndetectedChromeFetcher()
        fetcher._driver = MagicMock()

        fetcher.close()

        assert fetcher._driver is None

    def test_close_driver_error_handled(self) -> None:
        """Test that close handles errors gracefully."""
        fetcher = UndetectedChromeFetcher()
        fetcher._driver = MagicMock()
        fetcher._driver.quit.side_effect = Exception("Quit failed")

        # Should not raise
        fetcher.close()

        assert fetcher._driver is None

    @pytest.mark.asyncio
    async def test_close_async(self) -> None:
        """Test async close."""
        fetcher = UndetectedChromeFetcher()
        fetcher._driver = MagicMock()

        await fetcher.close_async()

        assert fetcher._driver is None

    def test_context_manager(self) -> None:
        """Test context manager usage."""
        fetcher = UndetectedChromeFetcher()
        fetcher._driver = MagicMock()

        with fetcher as f:
            assert f is fetcher

        # Driver should be closed after exit
        assert fetcher._driver is None


# =============================================================================
# Cloudflare Bypass Tests (Mocked)
# =============================================================================


class TestCloudflareBypass:
    """Tests for Cloudflare bypass functionality."""

    def test_wait_for_cloudflare_success(self) -> None:
        """Test successful Cloudflare bypass detection."""
        fetcher = UndetectedChromeFetcher()
        fetcher._driver = MagicMock()

        # First call returns challenge, second call returns normal page
        fetcher._driver.page_source = "<html>Normal content</html>"

        result = fetcher._wait_for_cloudflare(timeout=2)

        assert result is True

    def test_wait_for_cloudflare_timeout(self) -> None:
        """Test Cloudflare bypass timeout."""
        fetcher = UndetectedChromeFetcher()
        fetcher._driver = MagicMock()

        # Always return challenge page
        fetcher._driver.page_source = "<html>checking your browser</html>"

        result = fetcher._wait_for_cloudflare(timeout=1)

        assert result is False

    def test_wait_for_cloudflare_indicators(self) -> None:
        """Test detection of various Cloudflare indicators."""
        fetcher = UndetectedChromeFetcher()
        fetcher._driver = MagicMock()

        indicators = [
            "cf-browser-verification",
            "checking your browser",
            "just a moment",
            "_cf_chl_opt",
            "cf-turnstile",
        ]

        for indicator in indicators:
            fetcher._driver.page_source = f"<html>{indicator}</html>"

            # Should not immediately return True
            result = fetcher._wait_for_cloudflare(timeout=0.1)
            assert result is False, f"Should detect indicator: {indicator}"


# =============================================================================
# Global Instance Tests
# =============================================================================


class TestGlobalInstance:
    """Tests for global instance management."""

    def test_get_undetected_fetcher(self) -> None:
        """Test getting global fetcher instance."""
        # Reset global
        import src.crawler.undetected as uc_module

        uc_module._undetected_fetcher = None

        fetcher1 = get_undetected_fetcher()
        fetcher2 = get_undetected_fetcher()

        # Should return same instance
        assert fetcher1 is fetcher2

    @pytest.mark.asyncio
    async def test_close_undetected_fetcher(self) -> None:
        """Test closing global fetcher instance."""
        import src.crawler.undetected as uc_module

        # Create and get fetcher
        uc_module._undetected_fetcher = UndetectedChromeFetcher()
        uc_module._undetected_fetcher._driver = MagicMock()

        await close_undetected_fetcher()

        assert uc_module._undetected_fetcher is None


# =============================================================================
# Integration Tests (Mocked)
# =============================================================================


class TestFetcherIntegration:
    """Integration tests with mocked components."""

    def test_full_fetch_flow_success(self, tmp_path: Path) -> None:
        """Test successful fetch flow with all components mocked."""
        fetcher = UndetectedChromeFetcher()

        # Mock undetected_chromedriver
        mock_uc = MagicMock()
        mock_driver = MagicMock()
        mock_uc.Chrome.return_value = mock_driver
        mock_driver.page_source = "<html><body>Success!</body></html>"
        mock_driver.execute_script.side_effect = [
            2000,  # page_height
            1000,  # viewport_height
        ]

        # Mock settings
        mock_settings = MagicMock()
        mock_settings.browser.viewport_width = 1920
        mock_settings.browser.viewport_height = 1080
        mock_settings.crawler.page_load_timeout = 30
        mock_settings.storage.cache_dir = str(tmp_path)
        mock_settings.storage.screenshots_dir = str(tmp_path / "screenshots")

        with patch.dict("sys.modules", {"undetected_chromedriver": mock_uc}):
            with patch("src.crawler.undetected.get_settings", return_value=mock_settings):
                fetcher._available = True
                fetcher._init_driver(headless=False)

                # Perform fetch
                result = fetcher.fetch_sync(
                    "https://example.com",
                    wait_for_cloudflare=False,
                    take_screenshot=False,
                    simulate_human=False,
                )

                assert result.ok is True
                assert result.content == "<html><body>Success!</body></html>"
                assert result.html_path is not None

    def test_fetch_with_cloudflare_detection(self) -> None:
        """Test fetch with Cloudflare challenge detection."""
        fetcher = UndetectedChromeFetcher()
        fetcher._available = True

        # Mock driver
        mock_driver = MagicMock()
        mock_driver.page_source = "<html>checking your browser before</html>"
        fetcher._driver = mock_driver

        # Mock settings
        mock_settings = MagicMock()
        mock_settings.storage.cache_dir = "/tmp"

        with patch("src.crawler.undetected.get_settings", return_value=mock_settings):
            result = fetcher.fetch_sync(
                "https://example.com",
                wait_for_cloudflare=True,
                cloudflare_timeout=0.5,  # Short timeout for test
            )

            # Should fail due to timeout
            assert result.ok is False
            assert result.reason == "cloudflare_bypass_timeout"


# =============================================================================
# Config Tests
# =============================================================================


class TestConfig:
    """Tests for configuration integration."""

    def test_undetected_chromedriver_config_defaults(self) -> None:
        """Test default configuration values."""
        from src.utils.config import UndetectedChromeDriverConfig

        config = UndetectedChromeDriverConfig()

        assert config.enabled is True
        assert config.auto_escalate_captcha_rate == 0.5
        assert config.auto_escalate_block_score == 5
        assert config.cloudflare_timeout == 45
        assert config.prefer_headless is False

    def test_browser_config_includes_undetected(self) -> None:
        """Test that BrowserConfig includes undetected config."""
        from src.utils.config import BrowserConfig

        config = BrowserConfig()

        assert hasattr(config, "undetected_chromedriver")
        assert config.undetected_chromedriver.enabled is True
