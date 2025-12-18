"""
Tests for browser provider abstraction layer.

Implements §7.1 test quality standards:
- Specific assertions (no vague len > 0 checks)
- Production-like test data
- Mock strategy for external dependencies
- Clear test structure (Arrange-Act-Assert)

Tests cover:
- Protocol compliance
- Registry functionality (register/unregister/fallback)
- Data class serialization
- Provider lifecycle management

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-CK-N-01 | Cookie with all fields | Equivalence – normal | Dict with all fields | Cookie serialize |
| TC-CK-N-02 | Cookie with expires | Equivalence – normal | expires in dict | Expires field |
| TC-CK-N-03 | Playwright format dict | Equivalence – normal | Cookie created | from_dict |
| TC-CK-N-04 | Selenium format dict | Equivalence – normal | Cookie created | snake_case |
| TC-BO-N-01 | Default options | Equivalence – normal | Sensible defaults | Defaults |
| TC-BO-N-02 | Options to_dict | Equivalence – normal | All fields included | Serialize |
| TC-PR-N-01 | Success result | Equivalence – normal | ok=True | PageResult |
| TC-PR-N-02 | Failure result | Equivalence – normal | ok=False | PageResult |
| TC-PR-N-03 | to_dict excludes content | Equivalence – normal | No content in dict | Serialize |
| TC-HS-N-01 | Healthy status | Equivalence – normal | HEALTHY state | Health |
| TC-HS-N-02 | Degraded status | Equivalence – normal | DEGRADED state | Health |
| TC-HS-N-03 | Unhealthy status | Equivalence – normal | UNHEALTHY state | Health |
| TC-HS-N-04 | Unavailable status | Equivalence – normal | UNHEALTHY state | Missing dep |
| TC-PP-N-01 | Mock implements protocol | Equivalence – normal | Protocol check passes | Protocol |
| TC-PP-N-02 | Navigate returns PageResult | Equivalence – normal | PageResult instance | Navigate |
| TC-PP-N-03 | Navigate records calls | Equivalence – normal | Calls recorded | History |
| TC-PP-N-04 | Challenge detection | Equivalence – normal | challenge_detected=True | Challenge |
| TC-PP-A-01 | Closed provider navigate | Abnormal – closed | RuntimeError raised | Closed |
| TC-PP-N-05 | Get health | Equivalence – normal | BrowserHealthStatus | Health |
| TC-PP-N-06 | Set/get cookies | Equivalence – normal | Cookies stored | Cookies |
| TC-PP-N-07 | Execute script | Equivalence – normal | Result returned | Script |
| TC-RG-N-01 | Register provider | Equivalence – normal | Provider in list | Register |
| TC-RG-N-02 | First is default | Equivalence – normal | First as default | Default |
| TC-RG-N-03 | Explicit default | Equivalence – normal | Override default | set_default |
| TC-RG-A-01 | Duplicate name | Abnormal – conflict | ValueError raised | Duplicate |
| TC-RG-N-04 | Unregister provider | Equivalence – normal | Provider removed | Unregister |
| TC-RG-N-05 | Unregister updates default | Equivalence – normal | Next becomes default | Default update |
| TC-RG-N-06 | Set default | Equivalence – normal | Default changed | set_default |
| TC-RG-A-02 | Unknown default | Abnormal – not found | ValueError raised | Unknown |
| TC-RG-N-07 | Set fallback order | Equivalence – normal | Order stored | Fallback |
| TC-RG-N-08 | Get all health | Equivalence – normal | Health for all | Health |
| TC-RG-N-09 | Navigate with fallback success | Equivalence – normal | First success | Fallback |
| TC-RG-N-10 | Fallback on failure | Equivalence – normal | Tries next | Fallback |
| TC-RG-N-11 | Skip unhealthy | Equivalence – normal | Unhealthy skipped | Fallback |
| TC-RG-N-12 | All fail | Equivalence – normal | Error result | Fallback |
| TC-RG-A-03 | No providers | Abnormal – empty | RuntimeError raised | Empty |
| TC-RG-N-13 | Custom order | Equivalence – normal | Order respected | Fallback |
| TC-RG-N-14 | Close all | Equivalence – normal | All closed | Cleanup |
| TC-GR-N-01 | Singleton registry | Equivalence – normal | Same instance | Singleton |
| TC-GR-N-02 | Reset registry | Equivalence – normal | New instance | Reset |
| TC-PW-N-01 | Playwright health open | Equivalence – normal | HEALTHY | Health |
| TC-PW-N-02 | Playwright health closed | Equivalence – normal | UNHEALTHY | Health |
| TC-UC-N-01 | Undetected no module | Equivalence – normal | unavailable | Health |
| TC-UC-N-02 | Undetected navigate unavail | Equivalence – normal | Failure result | Navigate |
"""

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.crawler.browser_provider import (
    BaseBrowserProvider,
    BrowserHealthState,
    BrowserHealthStatus,
    BrowserMode,
    BrowserOptions,
    BrowserProvider,
    BrowserProviderRegistry,
    Cookie,
    PageResult,
    get_browser_registry,
    reset_browser_registry,
)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def reset_registry():
    """Reset global registry before and after each test."""
    reset_browser_registry()
    yield
    reset_browser_registry()


class MockBrowserProvider(BaseBrowserProvider):
    """Mock browser provider for testing.

    Simulates browser behavior without actual browser dependency.
    """

    def __init__(
        self,
        name: str = "mock",
        *,
        should_succeed: bool = True,
        challenge_type: str | None = None,
        health_state: BrowserHealthState = BrowserHealthState.HEALTHY,
    ):
        super().__init__(name)
        self.should_succeed = should_succeed
        self.challenge_type = challenge_type
        self.health_state = health_state
        self.navigate_calls: list[tuple[str, BrowserOptions | None]] = []
        self.script_calls: list[str] = []
        self.cookies: list[Cookie] = []

    async def navigate(
        self,
        url: str,
        options: BrowserOptions | None = None,
    ) -> PageResult:
        """Mock navigation."""
        self._check_closed()
        self.navigate_calls.append((url, options))

        if self.challenge_type:
            return PageResult.failure(
                url=url,
                error=f"challenge_detected:{self.challenge_type}",
                provider=self.name,
                mode=options.mode if options else BrowserMode.HEADLESS,
                challenge_detected=True,
                challenge_type=self.challenge_type,
            )

        if self.should_succeed:
            return PageResult.success(
                url=url,
                content="<html><body>Mock content</body></html>",
                provider=self.name,
                status=200,
                content_hash="abc123",
                mode=options.mode if options else BrowserMode.HEADLESS,
                elapsed_ms=100.0,
            )
        else:
            return PageResult.failure(
                url=url,
                error="mock_failure",
                provider=self.name,
                mode=options.mode if options else BrowserMode.HEADLESS,
            )

    async def execute_script(self, script: str, *args) -> str:
        """Mock script execution."""
        self._check_closed()
        self.script_calls.append(script)
        return "mock_result"

    async def get_cookies(self, url: str | None = None) -> list[Cookie]:
        """Return mock cookies."""
        return self.cookies

    async def set_cookies(self, cookies: list[Cookie]) -> None:
        """Store mock cookies."""
        self.cookies = cookies

    async def get_health(self) -> BrowserHealthStatus:
        """Return configured health status."""
        if self.health_state == BrowserHealthState.HEALTHY:
            return BrowserHealthStatus.healthy()
        elif self.health_state == BrowserHealthState.DEGRADED:
            return BrowserHealthStatus.degraded(0.7, "Mock degraded")
        else:
            return BrowserHealthStatus.unhealthy("Mock unhealthy")


# ============================================================================
# Data Class Tests
# ============================================================================


class TestCookie:
    """Tests for Cookie data class."""

    def test_cookie_to_dict_basic(self):
        """Cookie.to_dict() returns Playwright/Selenium compatible format (TC-CK-N-01)."""
        # Given: A Cookie with all fields set
        cookie = Cookie(
            name="session_id",
            value="abc123",
            domain=".example.com",
            path="/",
            http_only=True,
            secure=True,
        )

        # When: Converting to dict
        result = cookie.to_dict()

        # Then: All fields should be present with correct values
        assert result["name"] == "session_id"
        assert result["value"] == "abc123"
        assert result["domain"] == ".example.com"
        assert result["path"] == "/"
        assert result["httpOnly"] is True
        assert result["secure"] is True
        assert result["sameSite"] == "Lax"
        assert "expires" not in result

    def test_cookie_to_dict_with_expires(self):
        """Cookie.to_dict() includes expires when set (TC-CK-N-02)."""
        # Given: A Cookie with expires set
        cookie = Cookie(
            name="token",
            value="xyz",
            expires=1700000000.0,
        )

        # When: Converting to dict
        result = cookie.to_dict()

        # Then: expires should be included
        assert result["expires"] == 1700000000.0

    def test_cookie_from_dict_playwright_format(self):
        """Cookie.from_dict() handles Playwright cookie format (TC-CK-N-03)."""
        # Given: A dict in Playwright format (camelCase)
        data = {
            "name": "auth",
            "value": "token123",
            "domain": "example.com",
            "path": "/api",
            "httpOnly": True,
            "secure": False,
            "sameSite": "Strict",
            "expires": 1700000000.0,
        }

        # When: Creating Cookie from dict
        cookie = Cookie.from_dict(data)

        # Then: All fields should be parsed correctly
        assert cookie.name == "auth"
        assert cookie.value == "token123"
        assert cookie.domain == "example.com"
        assert cookie.path == "/api"
        assert cookie.http_only is True
        assert cookie.secure is False
        assert cookie.same_site == "Strict"
        assert cookie.expires == 1700000000.0

    def test_cookie_from_dict_selenium_format(self):
        """Cookie.from_dict() handles Selenium cookie format (snake_case) (TC-CK-N-04)."""
        # Given: A dict in Selenium format (snake_case)
        data = {
            "name": "sess",
            "value": "val",
            "http_only": True,
            "same_site": "Lax",
        }

        # When: Creating Cookie from dict
        cookie = Cookie.from_dict(data)

        # Then: snake_case fields should be parsed correctly
        assert cookie.name == "sess"
        assert cookie.http_only is True
        assert cookie.same_site == "Lax"


class TestBrowserOptions:
    """Tests for BrowserOptions data class."""

    def test_default_options(self):
        """BrowserOptions has sensible defaults (TC-BO-N-01)."""
        # Given: No constructor arguments
        # When: Creating BrowserOptions with defaults
        options = BrowserOptions()

        # Then: Should have sensible default values
        assert options.mode == BrowserMode.HEADLESS
        assert options.timeout == 30.0
        assert options.viewport_width == 1920
        assert options.viewport_height == 1080
        assert options.wait_until == "domcontentloaded"
        assert options.referer is None
        assert options.simulate_human is True
        assert options.take_screenshot is True
        assert options.block_resources is True

    def test_options_to_dict(self):
        """BrowserOptions.to_dict() includes all fields (TC-BO-N-02)."""
        # Given: BrowserOptions with custom values
        options = BrowserOptions(
            mode=BrowserMode.HEADFUL,
            timeout=60.0,
            referer="https://example.com",
        )

        # When: Converting to dict
        result = options.to_dict()

        # Then: All fields should be included
        assert result["mode"] == "headful"
        assert result["timeout"] == 60.0
        assert result["referer"] == "https://example.com"


class TestPageResult:
    """Tests for PageResult data class."""

    def test_success_result(self):
        """PageResult.success() creates correct success result (TC-PR-N-01)."""
        # Given: Success result parameters
        # When: Creating success PageResult
        result = PageResult.success(
            url="https://example.com",
            content="<html>Test</html>",
            provider="test_provider",
            status=200,
            content_hash="hash123",
            elapsed_ms=150.5,
        )

        # Then: All success fields should be set correctly
        assert result.ok is True
        assert result.url == "https://example.com"
        assert result.content == "<html>Test</html>"
        assert result.provider == "test_provider"
        assert result.status == 200
        assert result.content_hash == "hash123"
        assert result.elapsed_ms == 150.5
        assert result.error is None
        assert result.challenge_detected is False

    def test_failure_result(self):
        """PageResult.failure() creates correct failure result (TC-PR-N-02)."""
        # Given: Failure result parameters
        # When: Creating failure PageResult
        result = PageResult.failure(
            url="https://example.com",
            error="connection_timeout",
            provider="test_provider",
            status=None,
            challenge_detected=True,
            challenge_type="cloudflare",
        )

        # Then: All failure fields should be set correctly
        assert result.ok is False
        assert result.url == "https://example.com"
        assert result.error == "connection_timeout"
        assert result.provider == "test_provider"
        assert result.challenge_detected is True
        assert result.challenge_type == "cloudflare"
        assert result.content is None

    def test_result_to_dict_excludes_content(self):
        """PageResult.to_dict() excludes full content for serialization (TC-PR-N-03)."""
        # Given: A PageResult with content
        result = PageResult.success(
            url="https://example.com",
            content="<html>Long content...</html>",
            provider="test",
        )

        # When: Converting to dict
        data = result.to_dict()

        # Then: Content should be excluded (too large for serialization)
        assert "content" not in data
        assert data["content_hash"] is None
        assert data["cookies_count"] == 0


class TestBrowserHealthStatus:
    """Tests for BrowserHealthStatus data class."""

    def test_healthy_status(self):
        """BrowserHealthStatus.healthy() creates correct status (TC-HS-N-01)."""
        # Given: Latency measurement
        # When: Creating healthy status
        status = BrowserHealthStatus.healthy(latency_ms=50.0)

        # Then: Should indicate healthy state
        assert status.state == BrowserHealthState.HEALTHY
        assert status.available is True
        assert status.success_rate == 1.0
        assert status.latency_ms == 50.0
        assert status.last_check is not None

    def test_degraded_status(self):
        """BrowserHealthStatus.degraded() creates correct status (TC-HS-N-02)."""
        # Given: Success rate and message
        # When: Creating degraded status
        status = BrowserHealthStatus.degraded(0.75, "High latency")

        # Then: Should indicate degraded state
        assert status.state == BrowserHealthState.DEGRADED
        assert status.available is True
        assert status.success_rate == 0.75
        assert status.message == "High latency"

    def test_unhealthy_status(self):
        """BrowserHealthStatus.unhealthy() creates correct status (TC-HS-N-03)."""
        # Given: Error message
        # When: Creating unhealthy status
        status = BrowserHealthStatus.unhealthy("Connection failed")

        # Then: Should indicate unhealthy state
        assert status.state == BrowserHealthState.UNHEALTHY
        assert status.available is False
        assert status.success_rate == 0.0
        assert status.message == "Connection failed"

    def test_unavailable_status(self):
        """BrowserHealthStatus.unavailable() for missing dependencies (TC-HS-N-04)."""
        # Given: Missing dependency message
        # When: Creating unavailable status
        status = BrowserHealthStatus.unavailable("Playwright not installed")

        # Then: Should indicate unhealthy/unavailable state
        assert status.state == BrowserHealthState.UNHEALTHY
        assert status.available is False
        assert status.message == "Playwright not installed"


# ============================================================================
# Provider Protocol Tests
# ============================================================================


class TestBrowserProviderProtocol:
    """Tests for BrowserProvider protocol compliance."""

    def test_mock_provider_implements_protocol(self):
        """MockBrowserProvider implements BrowserProvider protocol."""
        provider = MockBrowserProvider()

        # Protocol check via isinstance
        assert isinstance(provider, BrowserProvider)

    @pytest.mark.asyncio
    async def test_provider_navigate_returns_page_result(self):
        """Provider.navigate() returns PageResult."""
        provider = MockBrowserProvider()

        result = await provider.navigate("https://example.com")

        assert isinstance(result, PageResult)
        assert result.ok is True
        assert result.url == "https://example.com"
        assert result.provider == "mock"

    @pytest.mark.asyncio
    async def test_provider_navigate_records_calls(self):
        """Provider.navigate() records call history for verification."""
        provider = MockBrowserProvider()
        options = BrowserOptions(mode=BrowserMode.HEADFUL)

        await provider.navigate("https://example.com", options)
        await provider.navigate("https://test.com")

        assert len(provider.navigate_calls) == 2
        assert provider.navigate_calls[0][0] == "https://example.com"
        assert provider.navigate_calls[0][1].mode == BrowserMode.HEADFUL
        assert provider.navigate_calls[1][0] == "https://test.com"

    @pytest.mark.asyncio
    async def test_provider_handles_challenge(self):
        """Provider returns challenge info when detected."""
        provider = MockBrowserProvider(challenge_type="cloudflare")

        result = await provider.navigate("https://protected.com")

        assert result.ok is False
        assert result.challenge_detected is True
        assert result.challenge_type == "cloudflare"
        assert "challenge_detected" in result.error

    @pytest.mark.asyncio
    async def test_provider_closed_raises_error(self):
        """Closed provider raises RuntimeError on navigate."""
        provider = MockBrowserProvider()
        await provider.close()

        with pytest.raises(RuntimeError, match="is closed"):
            await provider.navigate("https://example.com")

    @pytest.mark.asyncio
    async def test_provider_get_health(self):
        """Provider.get_health() returns BrowserHealthStatus."""
        provider = MockBrowserProvider(health_state=BrowserHealthState.DEGRADED)

        health = await provider.get_health()

        assert isinstance(health, BrowserHealthStatus)
        assert health.state == BrowserHealthState.DEGRADED

    @pytest.mark.asyncio
    async def test_provider_set_and_get_cookies(self):
        """Provider.set_cookies() and get_cookies() work correctly."""
        provider = MockBrowserProvider()

        test_cookies = [
            Cookie(name="session", value="abc123", domain="example.com"),
            Cookie(name="auth", value="xyz789", domain="example.com", http_only=True),
        ]

        await provider.set_cookies(test_cookies)
        retrieved = await provider.get_cookies()

        assert len(retrieved) == 2
        assert retrieved[0].name == "session"
        assert retrieved[0].value == "abc123"
        assert retrieved[1].name == "auth"
        assert retrieved[1].http_only is True

    @pytest.mark.asyncio
    async def test_provider_execute_script(self):
        """Provider.execute_script() executes and returns result."""
        provider = MockBrowserProvider()

        result = await provider.execute_script("return document.title")

        assert result == "mock_result"
        assert "return document.title" in provider.script_calls


# ============================================================================
# Registry Tests
# ============================================================================


class TestBrowserProviderRegistry:
    """Tests for BrowserProviderRegistry."""

    def test_register_provider(self, reset_registry):
        """Registry registers provider correctly."""
        registry = BrowserProviderRegistry()
        provider = MockBrowserProvider("test_provider")

        registry.register(provider)

        assert "test_provider" in registry.list_providers()
        assert registry.get("test_provider") is provider

    def test_register_sets_first_as_default(self, reset_registry):
        """First registered provider becomes default."""
        registry = BrowserProviderRegistry()
        provider1 = MockBrowserProvider("provider1")
        provider2 = MockBrowserProvider("provider2")

        registry.register(provider1)
        registry.register(provider2)

        assert registry.get_default() is provider1

    def test_register_explicit_default(self, reset_registry):
        """set_default=True overrides automatic default."""
        registry = BrowserProviderRegistry()
        provider1 = MockBrowserProvider("provider1")
        provider2 = MockBrowserProvider("provider2")

        registry.register(provider1)
        registry.register(provider2, set_default=True)

        assert registry.get_default() is provider2

    def test_register_duplicate_raises_error(self, reset_registry):
        """Registering duplicate name raises ValueError."""
        registry = BrowserProviderRegistry()
        provider1 = MockBrowserProvider("same_name")
        provider2 = MockBrowserProvider("same_name")

        registry.register(provider1)

        with pytest.raises(ValueError, match="already registered"):
            registry.register(provider2)

    def test_unregister_provider(self, reset_registry):
        """Registry unregisters provider correctly."""
        registry = BrowserProviderRegistry()
        provider = MockBrowserProvider("to_remove")
        registry.register(provider)

        removed = registry.unregister("to_remove")

        assert removed is provider
        assert "to_remove" not in registry.list_providers()
        assert registry.get("to_remove") is None

    def test_unregister_updates_default(self, reset_registry):
        """Unregistering default updates to next available."""
        registry = BrowserProviderRegistry()
        provider1 = MockBrowserProvider("provider1")
        provider2 = MockBrowserProvider("provider2")
        registry.register(provider1)
        registry.register(provider2)

        registry.unregister("provider1")

        assert registry.get_default() is provider2

    def test_set_default(self, reset_registry):
        """set_default() changes default provider."""
        registry = BrowserProviderRegistry()
        provider1 = MockBrowserProvider("provider1")
        provider2 = MockBrowserProvider("provider2")
        registry.register(provider1)
        registry.register(provider2)

        registry.set_default("provider2")

        assert registry.get_default() is provider2

    def test_set_default_unknown_raises_error(self, reset_registry):
        """set_default() with unknown name raises ValueError."""
        registry = BrowserProviderRegistry()

        with pytest.raises(ValueError, match="not registered"):
            registry.set_default("unknown")

    def test_set_fallback_order(self, reset_registry):
        """set_fallback_order() configures fallback sequence."""
        registry = BrowserProviderRegistry()
        provider1 = MockBrowserProvider("first")
        provider2 = MockBrowserProvider("second")
        provider3 = MockBrowserProvider("third")
        registry.register(provider1)
        registry.register(provider2)
        registry.register(provider3)

        registry.set_fallback_order(["third", "first", "second"])

        # Verify order is stored (internal state)
        assert registry._fallback_order == ["third", "first", "second"]

    @pytest.mark.asyncio
    async def test_get_all_health(self, reset_registry):
        """get_all_health() returns health for all providers."""
        registry = BrowserProviderRegistry()
        healthy_provider = MockBrowserProvider("healthy")
        unhealthy_provider = MockBrowserProvider(
            "unhealthy",
            health_state=BrowserHealthState.UNHEALTHY,
        )
        registry.register(healthy_provider)
        registry.register(unhealthy_provider)

        health = await registry.get_all_health()

        assert len(health) == 2
        assert health["healthy"].state == BrowserHealthState.HEALTHY
        assert health["unhealthy"].state == BrowserHealthState.UNHEALTHY

    @pytest.mark.asyncio
    async def test_navigate_with_fallback_success(self, reset_registry):
        """navigate_with_fallback() returns first successful result."""
        registry = BrowserProviderRegistry()
        provider1 = MockBrowserProvider("provider1", should_succeed=True)
        registry.register(provider1)

        result = await registry.navigate_with_fallback("https://example.com")

        assert result.ok is True
        assert result.provider == "provider1"
        assert len(provider1.navigate_calls) == 1

    @pytest.mark.asyncio
    async def test_navigate_with_fallback_tries_next_on_failure(self, reset_registry):
        """navigate_with_fallback() tries next provider on failure."""
        registry = BrowserProviderRegistry()
        failing_provider = MockBrowserProvider("failing", should_succeed=False)
        success_provider = MockBrowserProvider("success", should_succeed=True)
        registry.register(failing_provider)
        registry.register(success_provider)

        result = await registry.navigate_with_fallback("https://example.com")

        assert result.ok is True
        assert result.provider == "success"
        assert len(failing_provider.navigate_calls) == 1
        assert len(success_provider.navigate_calls) == 1

    @pytest.mark.asyncio
    async def test_navigate_with_fallback_skips_unhealthy(self, reset_registry):
        """navigate_with_fallback() skips unhealthy providers."""
        registry = BrowserProviderRegistry()
        unhealthy = MockBrowserProvider(
            "unhealthy",
            health_state=BrowserHealthState.UNHEALTHY,
        )
        healthy = MockBrowserProvider("healthy", should_succeed=True)
        registry.register(unhealthy)
        registry.register(healthy)

        result = await registry.navigate_with_fallback("https://example.com")

        assert result.ok is True
        assert result.provider == "healthy"
        # Unhealthy provider should not have been called
        assert len(unhealthy.navigate_calls) == 0

    @pytest.mark.asyncio
    async def test_navigate_with_fallback_all_fail(self, reset_registry):
        """navigate_with_fallback() returns error when all fail."""
        registry = BrowserProviderRegistry()
        provider1 = MockBrowserProvider("provider1", should_succeed=False)
        provider2 = MockBrowserProvider("provider2", should_succeed=False)
        registry.register(provider1)
        registry.register(provider2)

        result = await registry.navigate_with_fallback("https://example.com")

        assert result.ok is False
        assert "All providers failed" in result.error
        assert result.provider == "none"

    @pytest.mark.asyncio
    async def test_navigate_with_fallback_no_providers_raises(self, reset_registry):
        """navigate_with_fallback() raises error when no providers."""
        registry = BrowserProviderRegistry()

        with pytest.raises(RuntimeError, match="No browser providers"):
            await registry.navigate_with_fallback("https://example.com")

    @pytest.mark.asyncio
    async def test_navigate_with_fallback_custom_order(self, reset_registry):
        """navigate_with_fallback() respects custom provider order."""
        registry = BrowserProviderRegistry()
        provider1 = MockBrowserProvider("provider1", should_succeed=True)
        provider2 = MockBrowserProvider("provider2", should_succeed=True)
        registry.register(provider1)
        registry.register(provider2)

        result = await registry.navigate_with_fallback(
            "https://example.com",
            provider_order=["provider2", "provider1"],
        )

        assert result.ok is True
        assert result.provider == "provider2"
        # Only provider2 should have been called
        assert len(provider2.navigate_calls) == 1
        assert len(provider1.navigate_calls) == 0

    @pytest.mark.asyncio
    async def test_close_all(self, reset_registry):
        """close_all() closes all providers."""
        registry = BrowserProviderRegistry()
        provider1 = MockBrowserProvider("provider1")
        provider2 = MockBrowserProvider("provider2")
        registry.register(provider1)
        registry.register(provider2)

        await registry.close_all()

        assert provider1.is_closed is True
        assert provider2.is_closed is True
        assert len(registry.list_providers()) == 0


# ============================================================================
# Global Registry Tests
# ============================================================================


class TestGlobalRegistry:
    """Tests for global registry functions."""

    def test_get_browser_registry_singleton(self, reset_registry):
        """get_browser_registry() returns singleton instance."""
        registry1 = get_browser_registry()
        registry2 = get_browser_registry()

        assert registry1 is registry2

    def test_reset_browser_registry(self, reset_registry):
        """reset_browser_registry() creates new instance."""
        registry1 = get_browser_registry()
        registry1.register(MockBrowserProvider("test"))

        reset_browser_registry()
        registry2 = get_browser_registry()

        assert registry1 is not registry2
        assert len(registry2.list_providers()) == 0


# ============================================================================
# Integration Tests (with mocked Playwright)
# ============================================================================


class TestPlaywrightProviderMocked:
    """Tests for PlaywrightProvider with mocked Playwright."""

    @pytest.mark.asyncio
    async def test_playwright_provider_health_returns_healthy_when_not_closed(self):
        """PlaywrightProvider.get_health() returns HEALTHY when provider is not closed.

        The health check does not require Playwright to be initialized - it only
        checks if the provider is closed and if imports would succeed.
        """
        from src.crawler.playwright_provider import PlaywrightProvider

        provider = PlaywrightProvider()

        health = await provider.get_health()

        # Provider should report healthy since it's not closed
        # and Playwright can be imported (it's installed in test env)
        assert health.state == BrowserHealthState.HEALTHY
        assert health.available is True

    @pytest.mark.asyncio
    async def test_playwright_provider_health_after_close(self):
        """PlaywrightProvider.get_health() returns UNHEALTHY after close()."""
        from src.crawler.playwright_provider import PlaywrightProvider

        provider = PlaywrightProvider()
        await provider.close()

        health = await provider.get_health()

        assert health.state == BrowserHealthState.UNHEALTHY
        assert health.available is False
        assert "closed" in health.message


class TestUndetectedProviderMocked:
    """Tests for UndetectedChromeProvider with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_undetected_provider_health_without_module(self):
        """UndetectedChromeProvider returns unavailable when module not installed."""
        from src.crawler.undetected_provider import UndetectedChromeProvider

        provider = UndetectedChromeProvider()
        provider._available = False  # Simulate module not available

        health = await provider.get_health()

        assert health.state == BrowserHealthState.UNHEALTHY
        assert health.available is False
        assert "not installed" in health.message

    @pytest.mark.asyncio
    async def test_undetected_provider_navigate_unavailable(self):
        """UndetectedChromeProvider returns failure when module unavailable."""
        from src.crawler.undetected_provider import UndetectedChromeProvider

        provider = UndetectedChromeProvider()
        provider._available = False

        result = await provider.navigate("https://example.com")

        assert result.ok is False
        assert "not available" in result.error

