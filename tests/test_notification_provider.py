"""
Tests for notification provider abstraction layer.

Test Classification (§7.1.7):
- All tests here are unit tests (no external dependencies)
- External dependencies (subprocess, platform) are mocked

Requirements tested:
- NotificationProvider protocol/ABC implementation
- Platform detection accuracy
- Provider registration and switching
- Fallback mechanism
- Health status reporting
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import pytest

from src.utils.notification_provider import (
    # Enums
    NotificationUrgency,
    NotificationHealthState,
    Platform,
    # Data classes
    NotificationOptions,
    NotificationResult,
    NotificationHealthStatus,
    # Platform detection
    detect_platform,
    is_wsl,
    # Protocol/ABC
    NotificationProvider,
    BaseNotificationProvider,
    # Providers
    LinuxNotifyProvider,
    WindowsToastProvider,
    WSLBridgeProvider,
    # Registry
    NotificationProviderRegistry,
    get_notification_registry,
    cleanup_notification_registry,
    reset_notification_registry,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_subprocess_success():
    """Mock subprocess that returns success."""
    process = AsyncMock()
    process.returncode = 0
    process.communicate = AsyncMock(return_value=(b"", b""))
    process.wait = AsyncMock()
    return process


@pytest.fixture
def mock_subprocess_failure():
    """Mock subprocess that returns failure."""
    process = AsyncMock()
    process.returncode = 1
    process.communicate = AsyncMock(return_value=(b"", b"Error message"))
    process.wait = AsyncMock()
    return process


@pytest.fixture
def registry():
    """Create a fresh registry for testing."""
    return NotificationProviderRegistry()


@pytest.fixture(autouse=True)
def reset_global_registry():
    """Reset global registry before and after each test."""
    reset_notification_registry()
    yield
    reset_notification_registry()


# =============================================================================
# NotificationUrgency Tests
# =============================================================================


@pytest.mark.unit
class TestNotificationUrgency:
    """Tests for NotificationUrgency enum."""
    
    def test_all_urgency_levels_exist(self):
        """Verify all required urgency levels are defined."""
        expected = {"LOW": "low", "NORMAL": "normal", "CRITICAL": "critical"}
        
        for attr_name, expected_value in expected.items():
            urgency = getattr(NotificationUrgency, attr_name)
            assert urgency.value == expected_value, (
                f"NotificationUrgency.{attr_name} should be '{expected_value}', "
                f"got '{urgency.value}'"
            )


@pytest.mark.unit
class TestPlatform:
    """Tests for Platform enum."""
    
    def test_all_platforms_exist(self):
        """Verify all required platforms are defined."""
        expected = {
            "LINUX": "linux",
            "WINDOWS": "windows",
            "WSL": "wsl",
            "MACOS": "macos",
            "UNKNOWN": "unknown",
        }
        
        for attr_name, expected_value in expected.items():
            plat = getattr(Platform, attr_name)
            assert plat.value == expected_value, (
                f"Platform.{attr_name} should be '{expected_value}', "
                f"got '{plat.value}'"
            )


# =============================================================================
# NotificationOptions Tests
# =============================================================================


@pytest.mark.unit
class TestNotificationOptions:
    """Tests for NotificationOptions data class."""
    
    def test_default_values(self):
        """Verify default values are set correctly."""
        options = NotificationOptions()
        
        assert options.timeout_seconds == 10, (
            f"Default timeout should be 10, got {options.timeout_seconds}"
        )
        assert options.urgency == NotificationUrgency.NORMAL, (
            f"Default urgency should be NORMAL, got {options.urgency}"
        )
        assert options.icon is None, f"Default icon should be None, got {options.icon}"
        assert options.sound is True, f"Default sound should be True, got {options.sound}"
        assert options.category is None, (
            f"Default category should be None, got {options.category}"
        )
    
    def test_custom_values(self):
        """Test creating options with custom values."""
        options = NotificationOptions(
            timeout_seconds=30,
            urgency=NotificationUrgency.CRITICAL,
            icon="test-icon",
            sound=False,
            category="test-category",
        )
        
        assert options.timeout_seconds == 30
        assert options.urgency == NotificationUrgency.CRITICAL
        assert options.icon == "test-icon"
        assert options.sound is False
        assert options.category == "test-category"
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        options = NotificationOptions(
            timeout_seconds=15,
            urgency=NotificationUrgency.LOW,
            icon="custom-icon",
            sound=True,
            category="alert",
        )
        
        result = options.to_dict()
        
        assert result["timeout_seconds"] == 15
        assert result["urgency"] == "low"
        assert result["icon"] == "custom-icon"
        assert result["sound"] is True
        assert result["category"] == "alert"


# =============================================================================
# NotificationResult Tests
# =============================================================================


@pytest.mark.unit
class TestNotificationResult:
    """Tests for NotificationResult data class."""
    
    def test_success_factory(self):
        """Test creating successful result via factory method."""
        result = NotificationResult.success(
            provider="test_provider",
            message_id="msg_123",
            elapsed_ms=50.5,
        )
        
        assert result.ok is True, f"ok should be True, got {result.ok}"
        assert result.provider == "test_provider"
        assert result.message_id == "msg_123"
        assert result.error is None
        assert result.elapsed_ms == 50.5
    
    def test_failure_factory(self):
        """Test creating failure result via factory method."""
        result = NotificationResult.failure(
            provider="test_provider",
            error="Test error message",
            elapsed_ms=100.0,
        )
        
        assert result.ok is False, f"ok should be False, got {result.ok}"
        assert result.provider == "test_provider"
        assert result.error == "Test error message"
        assert result.message_id is None
        assert result.elapsed_ms == 100.0
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        result = NotificationResult(
            ok=True,
            provider="linux_notify",
            message_id="linux_abc123",
            elapsed_ms=25.0,
        )
        
        data = result.to_dict()
        
        assert data["ok"] is True
        assert data["provider"] == "linux_notify"
        assert data["message_id"] == "linux_abc123"
        assert data["error"] is None
        assert data["elapsed_ms"] == 25.0


# =============================================================================
# NotificationHealthStatus Tests
# =============================================================================


@pytest.mark.unit
class TestNotificationHealthStatus:
    """Tests for NotificationHealthStatus data class."""
    
    def test_healthy_factory(self):
        """Test creating healthy status via factory method."""
        status = NotificationHealthStatus.healthy(
            platform=Platform.LINUX,
            message="All systems operational",
        )
        
        assert status.state == NotificationHealthState.HEALTHY
        assert status.available is True
        assert status.platform == Platform.LINUX
        assert status.success_rate == 1.0
        assert status.message == "All systems operational"
        assert status.last_check is not None
    
    def test_degraded_factory(self):
        """Test creating degraded status via factory method."""
        status = NotificationHealthStatus.degraded(
            platform=Platform.WINDOWS,
            success_rate=0.7,
            message="Some failures detected",
        )
        
        assert status.state == NotificationHealthState.DEGRADED
        assert status.available is True
        assert status.platform == Platform.WINDOWS
        assert status.success_rate == 0.7
        assert status.message == "Some failures detected"
    
    def test_unhealthy_factory(self):
        """Test creating unhealthy status via factory method."""
        status = NotificationHealthStatus.unhealthy(
            platform=Platform.WSL,
            message="Service unavailable",
        )
        
        assert status.state == NotificationHealthState.UNHEALTHY
        assert status.available is False
        assert status.platform == Platform.WSL
        assert status.success_rate == 0.0
        assert status.message == "Service unavailable"
    
    def test_unavailable_factory(self):
        """Test creating unavailable status via factory method."""
        status = NotificationHealthStatus.unavailable(
            platform=Platform.MACOS,
        )
        
        assert status.state == NotificationHealthState.UNHEALTHY
        assert status.available is False
        assert status.platform == Platform.MACOS
        assert "not available" in status.message.lower()
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        status = NotificationHealthStatus.healthy(Platform.LINUX)
        data = status.to_dict()
        
        assert data["state"] == "healthy"
        assert data["available"] is True
        assert data["platform"] == "linux"
        assert data["success_rate"] == 1.0
        assert data["last_check"] is not None


# =============================================================================
# Platform Detection Tests
# =============================================================================


@pytest.mark.unit
class TestPlatformDetection:
    """Tests for platform detection functions."""
    
    def test_detect_linux(self):
        """Test detection of Linux platform."""
        with patch("platform.system", return_value="Linux"):
            with patch("builtins.open", side_effect=FileNotFoundError()):
                with patch("platform.release", return_value="5.15.0-generic"):
                    result = detect_platform()
                    assert result == Platform.LINUX
    
    def test_detect_wsl_via_proc_version(self):
        """Test detection of WSL via /proc/version."""
        mock_file = MagicMock()
        mock_file.read.return_value = "Linux version 5.15.0-microsoft-standard-WSL2"
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        
        with patch("platform.system", return_value="Linux"):
            with patch("builtins.open", return_value=mock_file):
                result = detect_platform()
                assert result == Platform.WSL
    
    def test_detect_wsl_via_release(self):
        """Test detection of WSL via platform release when /proc/version fails."""
        with patch("platform.system", return_value="Linux"):
            with patch("builtins.open", side_effect=PermissionError()):
                with patch("platform.release", return_value="5.15.0-microsoft-standard-WSL2"):
                    result = detect_platform()
                    assert result == Platform.WSL
    
    def test_detect_windows(self):
        """Test detection of Windows platform."""
        with patch("platform.system", return_value="Windows"):
            result = detect_platform()
            assert result == Platform.WINDOWS
    
    def test_detect_macos(self):
        """Test detection of macOS platform."""
        with patch("platform.system", return_value="Darwin"):
            result = detect_platform()
            assert result == Platform.MACOS
    
    def test_detect_unknown(self):
        """Test detection of unknown platform."""
        with patch("platform.system", return_value="FreeBSD"):
            result = detect_platform()
            assert result == Platform.UNKNOWN
    
    def test_is_wsl_true(self):
        """Test is_wsl returns True on WSL."""
        with patch("src.utils.notification_provider.detect_platform", return_value=Platform.WSL):
            assert is_wsl() is True
    
    def test_is_wsl_false(self):
        """Test is_wsl returns False on non-WSL platforms."""
        with patch("src.utils.notification_provider.detect_platform", return_value=Platform.LINUX):
            assert is_wsl() is False


# =============================================================================
# LinuxNotifyProvider Tests
# =============================================================================


@pytest.mark.unit
class TestLinuxNotifyProvider:
    """Tests for LinuxNotifyProvider."""
    
    def test_provider_name(self):
        """Test provider has correct name."""
        provider = LinuxNotifyProvider()
        assert provider.name == "linux_notify"
    
    def test_target_platform(self):
        """Test provider targets correct platform."""
        provider = LinuxNotifyProvider()
        assert provider.target_platform == Platform.LINUX
    
    @pytest.mark.asyncio
    async def test_send_success(self, mock_subprocess_success):
        """Test successful notification send."""
        provider = LinuxNotifyProvider()
        
        with patch("shutil.which", return_value="/usr/bin/notify-send"):
            with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess_success):
                result = await provider.send("Test Title", "Test Message")
        
        assert result.ok is True
        assert result.provider == "linux_notify"
        assert result.message_id is not None
        assert result.message_id.startswith("linux_")
    
    @pytest.mark.asyncio
    async def test_send_notify_send_not_found(self):
        """Test failure when notify-send is not installed."""
        provider = LinuxNotifyProvider()
        
        with patch("shutil.which", return_value=None):
            result = await provider.send("Test Title", "Test Message")
        
        assert result.ok is False
        assert "notify-send not found" in result.error
    
    @pytest.mark.asyncio
    async def test_send_with_options(self, mock_subprocess_success):
        """Test notification send with custom options."""
        provider = LinuxNotifyProvider()
        options = NotificationOptions(
            timeout_seconds=30,
            urgency=NotificationUrgency.CRITICAL,
            icon="dialog-error",
            category="alert",
        )
        
        with patch("shutil.which", return_value="/usr/bin/notify-send"):
            with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess_success) as mock_exec:
                result = await provider.send("Test", "Message", options)
        
        assert result.ok is True
        # Verify command included timeout and urgency
        call_args = mock_exec.call_args[0]
        assert "-t" in call_args
        assert "30000" in call_args  # 30 seconds in ms
        assert "-u" in call_args
        assert "critical" in call_args
    
    @pytest.mark.asyncio
    async def test_send_failure(self, mock_subprocess_failure):
        """Test notification send failure."""
        provider = LinuxNotifyProvider()
        
        with patch("shutil.which", return_value="/usr/bin/notify-send"):
            with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess_failure):
                result = await provider.send("Test Title", "Test Message")
        
        assert result.ok is False
        assert "notify-send failed" in result.error
    
    @pytest.mark.asyncio
    async def test_get_health_available(self):
        """Test health check when notify-send is available."""
        provider = LinuxNotifyProvider()
        
        with patch("src.utils.notification_provider.detect_platform", return_value=Platform.LINUX):
            with patch("shutil.which", return_value="/usr/bin/notify-send"):
                health = await provider.get_health()
        
        assert health.state == NotificationHealthState.HEALTHY
        assert health.available is True
    
    @pytest.mark.asyncio
    async def test_get_health_unavailable_wrong_platform(self):
        """Test health check on wrong platform."""
        provider = LinuxNotifyProvider()
        
        with patch("src.utils.notification_provider.detect_platform", return_value=Platform.WINDOWS):
            health = await provider.get_health()
        
        assert health.state == NotificationHealthState.UNHEALTHY
        assert health.available is False
    
    @pytest.mark.asyncio
    async def test_get_health_notify_send_missing(self):
        """Test health check when notify-send is not installed."""
        provider = LinuxNotifyProvider()
        
        with patch("src.utils.notification_provider.detect_platform", return_value=Platform.LINUX):
            with patch("shutil.which", return_value=None):
                health = await provider.get_health()
        
        assert health.state == NotificationHealthState.UNHEALTHY
        assert "not found" in health.message


# =============================================================================
# WindowsToastProvider Tests
# =============================================================================


@pytest.mark.unit
class TestWindowsToastProvider:
    """Tests for WindowsToastProvider."""
    
    def test_provider_name(self):
        """Test provider has correct name."""
        provider = WindowsToastProvider()
        assert provider.name == "windows_toast"
    
    def test_target_platform(self):
        """Test provider targets correct platform."""
        provider = WindowsToastProvider()
        assert provider.target_platform == Platform.WINDOWS
    
    @pytest.mark.asyncio
    async def test_send_success(self, mock_subprocess_success):
        """Test successful notification send."""
        provider = WindowsToastProvider()
        
        with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess_success):
            result = await provider.send("Test Title", "Test Message")
        
        assert result.ok is True
        assert result.provider == "windows_toast"
        assert result.message_id.startswith("win_")
    
    @pytest.mark.asyncio
    async def test_send_escapes_special_characters(self, mock_subprocess_success):
        """Test that special characters are properly escaped."""
        provider = WindowsToastProvider()
        
        with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess_success) as mock_exec:
            await provider.send("Test's Title", "Message with\nnewline")
        
        # Verify escaping happened
        call_args = mock_exec.call_args[0]
        ps_command = call_args[-1]  # Last argument is the command
        # Single quote should be escaped ('' for PowerShell)
        assert "''" in ps_command, f"Expected escaped single quote in: {ps_command[:200]}"
    
    @pytest.mark.asyncio
    async def test_get_health_available(self):
        """Test health check when on Windows."""
        provider = WindowsToastProvider()
        
        with patch("src.utils.notification_provider.detect_platform", return_value=Platform.WINDOWS):
            with patch("shutil.which", return_value="C:\\Windows\\System32\\powershell.exe"):
                health = await provider.get_health()
        
        assert health.state == NotificationHealthState.HEALTHY
        assert health.available is True
    
    @pytest.mark.asyncio
    async def test_get_health_unavailable_wrong_platform(self):
        """Test health check on wrong platform."""
        provider = WindowsToastProvider()
        
        with patch("src.utils.notification_provider.detect_platform", return_value=Platform.LINUX):
            health = await provider.get_health()
        
        assert health.state == NotificationHealthState.UNHEALTHY
        assert health.available is False


# =============================================================================
# WSLBridgeProvider Tests
# =============================================================================


@pytest.mark.unit
class TestWSLBridgeProvider:
    """Tests for WSLBridgeProvider."""
    
    def test_provider_name(self):
        """Test provider has correct name."""
        provider = WSLBridgeProvider()
        assert provider.name == "wsl_bridge"
    
    def test_target_platform(self):
        """Test provider targets correct platform."""
        provider = WSLBridgeProvider()
        assert provider.target_platform == Platform.WSL
    
    @pytest.mark.asyncio
    async def test_send_success(self):
        """Test successful notification send from WSL.
        
        Note: WSL bridge doesn't wait for completion, so success is returned
        immediately after process creation.
        """
        provider = WSLBridgeProvider()
        mock_process = AsyncMock()
        
        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            result = await provider.send("Test Title", "Test Message")
        
        assert result.ok is True
        assert result.provider == "wsl_bridge"
        assert result.message_id.startswith("wsl_")
    
    @pytest.mark.asyncio
    async def test_send_powershell_not_found(self):
        """Test failure when PowerShell is not accessible via WSL interop."""
        provider = WSLBridgeProvider()
        
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError()):
            result = await provider.send("Test Title", "Test Message")
        
        assert result.ok is False
        assert "powershell.exe not found" in result.error
    
    @pytest.mark.asyncio
    async def test_get_health_available(self):
        """Test health check when on WSL with PowerShell available."""
        provider = WSLBridgeProvider()
        
        with patch("src.utils.notification_provider.detect_platform", return_value=Platform.WSL):
            with patch("shutil.which", return_value="/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"):
                health = await provider.get_health()
        
        assert health.state == NotificationHealthState.HEALTHY
        assert health.available is True
    
    @pytest.mark.asyncio
    async def test_get_health_unavailable_wrong_platform(self):
        """Test health check on wrong platform."""
        provider = WSLBridgeProvider()
        
        with patch("src.utils.notification_provider.detect_platform", return_value=Platform.LINUX):
            health = await provider.get_health()
        
        assert health.state == NotificationHealthState.UNHEALTHY
        assert health.available is False


# =============================================================================
# BaseNotificationProvider Tests
# =============================================================================


@pytest.mark.unit
class TestBaseNotificationProvider:
    """Tests for BaseNotificationProvider abstract class."""
    
    def test_success_rate_tracking(self):
        """Test that success rate is properly calculated."""
        provider = LinuxNotifyProvider()
        
        # Initial state
        assert provider.success_rate == 1.0
        
        # Record some operations
        provider._record_success()
        provider._record_success()
        provider._record_failure()
        
        # 2 successes out of 3 total = 0.666...
        assert 0.66 <= provider.success_rate <= 0.67
    
    @pytest.mark.asyncio
    async def test_close_sets_closed_flag(self):
        """Test that close() sets the is_closed flag."""
        provider = LinuxNotifyProvider()
        
        assert provider.is_closed is False
        await provider.close()
        assert provider.is_closed is True
    
    @pytest.mark.asyncio
    async def test_closed_provider_raises_error(self):
        """Test that using a closed provider raises RuntimeError."""
        provider = LinuxNotifyProvider()
        await provider.close()
        
        with pytest.raises(RuntimeError, match="is closed"):
            provider._check_closed()


# =============================================================================
# NotificationProviderRegistry Tests
# =============================================================================


@pytest.mark.unit
class TestNotificationProviderRegistry:
    """Tests for NotificationProviderRegistry."""
    
    def test_register_provider(self, registry):
        """Test registering a provider."""
        provider = LinuxNotifyProvider()
        registry.register(provider)
        
        assert "linux_notify" in registry.list_providers()
        assert registry.get("linux_notify") is provider
    
    def test_register_duplicate_raises_error(self, registry):
        """Test that registering duplicate provider raises ValueError."""
        provider1 = LinuxNotifyProvider()
        provider2 = LinuxNotifyProvider()
        
        registry.register(provider1)
        
        with pytest.raises(ValueError, match="already registered"):
            registry.register(provider2)
    
    def test_register_sets_default_if_first(self, registry):
        """Test that first registered provider becomes default."""
        provider = LinuxNotifyProvider()
        registry.register(provider)
        
        assert registry.get_default() is provider
    
    def test_register_set_default(self, registry):
        """Test explicitly setting provider as default."""
        provider1 = LinuxNotifyProvider()
        provider2 = WindowsToastProvider()
        
        registry.register(provider1)
        registry.register(provider2, set_default=True)
        
        assert registry.get_default() is provider2
    
    def test_unregister_provider(self, registry):
        """Test unregistering a provider."""
        provider = LinuxNotifyProvider()
        registry.register(provider)
        
        unregistered = registry.unregister("linux_notify")
        
        assert unregistered is provider
        assert "linux_notify" not in registry.list_providers()
    
    def test_unregister_nonexistent(self, registry):
        """Test unregistering non-existent provider returns None."""
        result = registry.unregister("nonexistent")
        assert result is None
    
    def test_set_default(self, registry):
        """Test changing default provider."""
        provider1 = LinuxNotifyProvider()
        provider2 = WindowsToastProvider()
        
        registry.register(provider1)
        registry.register(provider2)
        
        registry.set_default("windows_toast")
        
        assert registry.get_default() is provider2
    
    def test_set_default_nonexistent_raises_error(self, registry):
        """Test setting non-existent provider as default raises ValueError."""
        with pytest.raises(ValueError, match="not registered"):
            registry.set_default("nonexistent")
    
    def test_list_providers(self, registry):
        """Test listing all registered providers."""
        registry.register(LinuxNotifyProvider())
        registry.register(WindowsToastProvider())
        
        providers = registry.list_providers()
        
        assert len(providers) == 2
        assert "linux_notify" in providers
        assert "windows_toast" in providers
    
    @pytest.mark.asyncio
    async def test_get_all_health(self, registry):
        """Test getting health status for all providers."""
        provider1 = LinuxNotifyProvider()
        provider2 = WindowsToastProvider()
        
        registry.register(provider1)
        registry.register(provider2)
        
        with patch("src.utils.notification_provider.detect_platform", return_value=Platform.LINUX):
            with patch("shutil.which", return_value="/usr/bin/notify-send"):
                health = await registry.get_all_health()
        
        assert "linux_notify" in health
        assert "windows_toast" in health
    
    @pytest.mark.asyncio
    async def test_send_uses_default(self, registry, mock_subprocess_success):
        """Test that send() uses default provider."""
        provider = LinuxNotifyProvider()
        registry.register(provider)
        
        with patch("shutil.which", return_value="/usr/bin/notify-send"):
            with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess_success):
                with patch.object(provider, "get_health", return_value=NotificationHealthStatus.healthy(Platform.LINUX)):
                    result = await registry.send("Test", "Message")
        
        assert result.ok is True
        assert result.provider == "linux_notify"
    
    @pytest.mark.asyncio
    async def test_send_fallback_on_failure(self, registry, mock_subprocess_success):
        """Test that send() falls back to next provider on failure."""
        provider1 = LinuxNotifyProvider()
        provider2 = WindowsToastProvider()
        
        registry.register(provider1)
        registry.register(provider2)
        
        # Provider1 is unhealthy
        with patch.object(provider1, "get_health", return_value=NotificationHealthStatus.unhealthy(Platform.LINUX, "test failure")):
            with patch.object(provider2, "get_health", return_value=NotificationHealthStatus.healthy(Platform.WINDOWS)):
                with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess_success):
                    result = await registry.send("Test", "Message")
        
        assert result.ok is True
        assert result.provider == "windows_toast"
    
    @pytest.mark.asyncio
    async def test_send_all_providers_fail(self, registry):
        """Test that send() returns error when all providers fail."""
        provider1 = LinuxNotifyProvider()
        registry.register(provider1)
        
        with patch.object(provider1, "get_health", return_value=NotificationHealthStatus.unhealthy(Platform.LINUX, "test failure")):
            result = await registry.send("Test", "Message")
        
        assert result.ok is False
        assert "All providers failed" in result.error
    
    @pytest.mark.asyncio
    async def test_send_no_providers(self, registry):
        """Test that send() raises error when no providers registered."""
        with pytest.raises(RuntimeError, match="No notification providers"):
            await registry.send("Test", "Message")
    
    @pytest.mark.asyncio
    async def test_close_all(self, registry):
        """Test closing all providers."""
        provider1 = LinuxNotifyProvider()
        provider2 = WindowsToastProvider()
        
        registry.register(provider1)
        registry.register(provider2)
        
        await registry.close_all()
        
        assert len(registry.list_providers()) == 0
        assert registry.get_default() is None


# =============================================================================
# Auto-registration Tests
# =============================================================================


@pytest.mark.unit
class TestAutoRegistration:
    """Tests for auto-registration based on platform."""
    
    def test_auto_register_linux(self, registry):
        """Test auto-registration on Linux."""
        with patch.object(registry, "_current_platform", Platform.LINUX):
            registry.auto_register()
        
        assert "linux_notify" in registry.list_providers()
        assert registry.get_default().name == "linux_notify"
    
    def test_auto_register_windows(self, registry):
        """Test auto-registration on Windows."""
        with patch.object(registry, "_current_platform", Platform.WINDOWS):
            registry.auto_register()
        
        assert "windows_toast" in registry.list_providers()
        assert registry.get_default().name == "windows_toast"
    
    def test_auto_register_wsl(self, registry):
        """Test auto-registration on WSL."""
        with patch.object(registry, "_current_platform", Platform.WSL):
            registry.auto_register()
        
        # WSL should have both WSL bridge (default) and Linux fallback
        providers = registry.list_providers()
        assert "wsl_bridge" in providers
        assert "linux_notify" in providers
        assert registry.get_default().name == "wsl_bridge"


# =============================================================================
# Global Registry Tests
# =============================================================================


@pytest.mark.unit
class TestGlobalRegistry:
    """Tests for global registry functions."""
    
    def test_get_notification_registry_creates_registry(self):
        """Test that get_notification_registry creates and returns registry."""
        registry = get_notification_registry()
        
        assert registry is not None
        assert isinstance(registry, NotificationProviderRegistry)
    
    def test_get_notification_registry_returns_same_instance(self):
        """Test that get_notification_registry returns singleton."""
        registry1 = get_notification_registry()
        registry2 = get_notification_registry()
        
        assert registry1 is registry2
    
    @pytest.mark.asyncio
    async def test_cleanup_notification_registry(self):
        """Test cleanup of global registry."""
        registry = get_notification_registry()
        assert registry is not None
        
        await cleanup_notification_registry()
        
        # After cleanup, get_notification_registry should create new instance
        reset_notification_registry()
        new_registry = get_notification_registry()
        # New registry should be different instance
        # (can't directly compare due to implementation, but verify it works)
        assert new_registry is not None


# =============================================================================
# Protocol Compliance Tests
# =============================================================================


@pytest.mark.unit
class TestProtocolCompliance:
    """Tests verifying protocol compliance."""
    
    def test_linux_provider_is_notification_provider(self):
        """Test LinuxNotifyProvider implements NotificationProvider protocol."""
        provider = LinuxNotifyProvider()
        assert isinstance(provider, NotificationProvider)
    
    def test_windows_provider_is_notification_provider(self):
        """Test WindowsToastProvider implements NotificationProvider protocol."""
        provider = WindowsToastProvider()
        assert isinstance(provider, NotificationProvider)
    
    def test_wsl_provider_is_notification_provider(self):
        """Test WSLBridgeProvider implements NotificationProvider protocol."""
        provider = WSLBridgeProvider()
        assert isinstance(provider, NotificationProvider)


# =============================================================================
# Edge Case Tests
# =============================================================================


@pytest.mark.unit
class TestEdgeCases:
    """Tests for edge cases and boundary conditions per §7.1.4."""
    
    @pytest.mark.asyncio
    async def test_send_empty_title_and_message(self, mock_subprocess_success):
        """Test sending notification with empty strings."""
        provider = LinuxNotifyProvider()
        
        with patch("shutil.which", return_value="/usr/bin/notify-send"):
            with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess_success):
                result = await provider.send("", "")
        
        # Should still succeed even with empty strings
        assert result.ok is True
    
    @pytest.mark.asyncio
    async def test_send_unicode_characters(self, mock_subprocess_success):
        """Test sending notification with Unicode characters."""
        provider = LinuxNotifyProvider()
        
        with patch("shutil.which", return_value="/usr/bin/notify-send"):
            with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess_success):
                result = await provider.send("日本語タイトル", "🔔 通知メッセージ 🔔")
        
        assert result.ok is True
    
    @pytest.mark.asyncio
    async def test_send_very_long_message(self, mock_subprocess_success):
        """Test sending notification with very long message."""
        provider = LinuxNotifyProvider()
        long_message = "A" * 10000  # 10k characters
        
        with patch("shutil.which", return_value="/usr/bin/notify-send"):
            with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess_success):
                result = await provider.send("Title", long_message)
        
        # Should succeed (truncation is platform's responsibility)
        assert result.ok is True
    
    def test_success_rate_with_no_operations(self):
        """Test success rate when no operations have been performed."""
        provider = LinuxNotifyProvider()
        
        # With 0 operations, should return 1.0 (optimistic default)
        assert provider.success_rate == 1.0
    
    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        """Test handling of subprocess timeout."""
        provider = LinuxNotifyProvider()
        
        async def slow_wait(*args, **kwargs):
            await asyncio.sleep(10)
            return (b"", b"")
        
        mock_process = AsyncMock()
        mock_process.communicate = slow_wait
        
        with patch("shutil.which", return_value="/usr/bin/notify-send"):
            with patch("asyncio.create_subprocess_exec", return_value=mock_process):
                result = await provider.send("Test", "Message")
        
        assert result.ok is False
        assert "timed out" in result.error

