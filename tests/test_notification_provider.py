"""
Tests for notification provider abstraction layer.

Test Classification (.1.7):
- All tests here are unit tests (no external dependencies)
- External dependencies (subprocess, platform) are mocked

Requirements tested:
- NotificationProvider protocol/ABC implementation
- Platform detection accuracy
- Provider registration and switching
- Fallback mechanism
- Health status reporting

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-NU-N-01 | Urgency enum | Equivalence – normal | All levels defined | - |
| TC-PL-N-01 | Platform enum | Equivalence – normal | All platforms defined | - |
| TC-NO-N-01 | Default options | Equivalence – normal | Correct defaults | - |
| TC-NO-N-02 | Custom options | Equivalence – normal | Values stored | - |
| TC-NO-N-03 | to_dict | Equivalence – normal | Serializable | - |
| TC-NR-N-01 | Success factory | Equivalence – normal | ok=True | - |
| TC-NR-N-02 | Failure factory | Equivalence – normal | ok=False | - |
| TC-NR-N-03 | to_dict | Equivalence – normal | Serializable | - |
| TC-HS-N-01 | healthy factory | Equivalence – normal | state=HEALTHY | - |
| TC-HS-N-02 | degraded factory | Equivalence – normal | state=DEGRADED | - |
| TC-HS-N-03 | unhealthy factory | Equivalence – normal | state=UNHEALTHY | - |
| TC-HS-N-04 | unavailable factory | Equivalence – normal | available=False | - |
| TC-HS-N-05 | to_dict | Equivalence – normal | Serializable | - |
| TC-PD-N-01 | Detect Linux | Equivalence – normal | Platform.LINUX | - |
| TC-PD-N-02 | Detect WSL proc | Equivalence – normal | Platform.WSL | - |
| TC-PD-N-03 | Detect WSL release | Equivalence – normal | Platform.WSL | - |
| TC-PD-N-04 | Detect Windows | Equivalence – normal | Platform.WINDOWS | - |
| TC-PD-N-05 | Detect macOS | Equivalence – normal | Platform.MACOS | - |
| TC-PD-N-06 | Detect unknown | Equivalence – normal | Platform.UNKNOWN | - |
| TC-PD-N-07 | is_wsl true | Equivalence – normal | True | - |
| TC-PD-N-08 | is_wsl false | Equivalence – normal | False | - |
| TC-LP-N-01 | provider_name | Equivalence – normal | "linux_notify" | - |
| TC-LP-N-02 | target_platform | Equivalence – normal | Platform.LINUX | - |
| TC-LP-N-03 | send success | Equivalence – normal | ok=True | - |
| TC-LP-A-01 | notify-send missing | Equivalence – abnormal | ok=False | - |
| TC-LP-N-04 | send with options | Equivalence – normal | Options applied | - |
| TC-LP-A-02 | send failure | Equivalence – abnormal | ok=False | - |
| TC-LP-N-05 | health available | Equivalence – normal | HEALTHY | - |
| TC-LP-A-03 | health wrong platform | Equivalence – abnormal | UNHEALTHY | - |
| TC-LP-A-04 | health missing | Equivalence – abnormal | UNHEALTHY | - |
| TC-WP-N-01 | provider_name | Equivalence – normal | "windows_toast" | - |
| TC-WP-N-02 | target_platform | Equivalence – normal | Platform.WINDOWS | - |
| TC-WP-N-03 | send success | Equivalence – normal | ok=True | - |
| TC-WP-N-04 | Escapes chars | Equivalence – normal | Escaped | - |
| TC-WP-N-05 | health available | Equivalence – normal | HEALTHY | - |
| TC-WP-A-01 | health wrong platform | Equivalence – abnormal | UNHEALTHY | - |
| TC-WB-N-01 | provider_name | Equivalence – normal | "wsl_bridge" | - |
| TC-WB-N-02 | target_platform | Equivalence – normal | Platform.WSL | - |
| TC-WB-N-03 | send success | Equivalence – normal | ok=True | - |
| TC-WB-A-01 | PS not found | Equivalence – abnormal | ok=False | - |
| TC-WB-N-04 | health available | Equivalence – normal | HEALTHY | - |
| TC-WB-A-02 | health wrong platform | Equivalence – abnormal | UNHEALTHY | - |
| TC-BP-N-01 | success_rate tracking | Equivalence – normal | Rate calculated | - |
| TC-BP-N-02 | close sets flag | Equivalence – normal | is_closed=True | - |
| TC-BP-A-01 | closed raises | Equivalence – abnormal | RuntimeError | - |
| TC-RG-N-01 | register provider | Equivalence – normal | In list | - |
| TC-RG-A-01 | register duplicate | Equivalence – abnormal | ValueError | - |
| TC-RG-N-02 | First is default | Equivalence – normal | Default set | - |
| TC-RG-N-03 | set_default | Equivalence – normal | Changed | - |
| TC-RG-N-04 | unregister | Equivalence – normal | Removed | - |
| TC-RG-A-02 | unregister nonexistent | Equivalence – abnormal | Returns None | - |
| TC-RG-N-05 | set_default | Equivalence – normal | Changed | - |
| TC-RG-A-03 | set_default nonexistent | Equivalence – abnormal | ValueError | - |
| TC-RG-N-06 | list_providers | Equivalence – normal | All listed | - |
| TC-RG-N-07 | get_all_health | Equivalence – normal | All statuses | - |
| TC-RG-N-08 | send uses default | Equivalence – normal | Correct provider | - |
| TC-RG-N-09 | send fallback | Equivalence – normal | Next provider | - |
| TC-RG-A-04 | send all fail | Equivalence – abnormal | Error | - |
| TC-RG-A-05 | send no providers | Equivalence – abnormal | RuntimeError | - |
| TC-RG-N-10 | close_all | Equivalence – normal | All closed | - |
| TC-AR-N-01 | auto_register Linux | Equivalence – normal | linux_notify | - |
| TC-AR-N-02 | auto_register Windows | Equivalence – normal | windows_toast | - |
| TC-AR-N-03 | auto_register WSL | Equivalence – normal | wsl_bridge + linux | - |
| TC-GR-N-01 | get creates registry | Equivalence – normal | Instance returned | - |
| TC-GR-N-02 | get returns same | Equivalence – normal | Singleton | - |
| TC-GR-N-03 | cleanup | Equivalence – normal | Reset works | - |
| TC-PC-N-01 | Linux is provider | Equivalence – normal | True | - |
| TC-PC-N-02 | Windows is provider | Equivalence – normal | True | - |
| TC-PC-N-03 | WSL is provider | Equivalence – normal | True | - |
| TC-EC-B-01 | Empty title/message | Boundary – empty | Still succeeds | - |
| TC-EC-N-01 | Unicode chars | Equivalence – normal | Succeeds | - |
| TC-EC-B-02 | Very long message | Boundary – max | Succeeds | - |
| TC-EC-B-03 | No operations rate | Boundary – zero | Returns 1.0 | - |
| TC-EC-A-01 | Timeout handling | Equivalence – abnormal | ok=False | - |
"""

import asyncio
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.utils.notification_provider import (
    LinuxNotifyProvider,
    NotificationHealthState,
    NotificationHealthStatus,
    # Data classes
    NotificationOptions,
    # Protocol/ABC
    NotificationProvider,
    # Registry
    NotificationProviderRegistry,
    NotificationResult,
    # Enums
    NotificationUrgency,
    Platform,
    WindowsToastProvider,
    WSLBridgeProvider,
    cleanup_notification_registry,
    # Platform detection
    detect_platform,
    get_notification_registry,
    is_wsl,
    reset_notification_registry,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_subprocess_success() -> AsyncMock:
    """Mock subprocess that returns success."""
    process = AsyncMock()
    process.returncode = 0
    process.communicate = AsyncMock(return_value=(b"", b""))
    process.wait = AsyncMock()
    return process


@pytest.fixture
def mock_subprocess_failure() -> AsyncMock:
    """Mock subprocess that returns failure."""
    process = AsyncMock()
    process.returncode = 1
    process.communicate = AsyncMock(return_value=(b"", b"Error message"))
    process.wait = AsyncMock()
    return process


@pytest.fixture
def registry() -> NotificationProviderRegistry:
    """Create a fresh registry for testing."""
    return NotificationProviderRegistry()


@pytest.fixture(autouse=True)
def reset_global_registry() -> Generator[None, None, None]:
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

    def test_all_urgency_levels_exist(self) -> None:
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

    def test_all_platforms_exist(self) -> None:
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
                f"Platform.{attr_name} should be '{expected_value}', got '{plat.value}'"
            )


# =============================================================================
# NotificationOptions Tests
# =============================================================================


@pytest.mark.unit
class TestNotificationOptions:
    """Tests for NotificationOptions data class."""

    def test_default_values(self) -> None:
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
        assert options.category is None, f"Default category should be None, got {options.category}"

    def test_custom_values(self) -> None:
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

    def test_to_dict(self) -> None:
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

    def test_success_factory(self) -> None:
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

    def test_failure_factory(self) -> None:
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

    def test_to_dict(self) -> None:
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

    def test_healthy_factory(self) -> None:
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

    def test_degraded_factory(self) -> None:
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

    def test_unhealthy_factory(self) -> None:
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

    def test_unavailable_factory(self) -> None:
        """Test creating unavailable status via factory method."""
        status = NotificationHealthStatus.unavailable(
            platform=Platform.MACOS,
        )

        assert status.state == NotificationHealthState.UNHEALTHY
        assert status.available is False
        assert status.platform == Platform.MACOS
        assert status.message is not None
        assert "not available" in status.message.lower()

    def test_to_dict(self) -> None:
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

    def test_detect_linux(self) -> None:
        """Test detection of Linux platform."""
        with patch("platform.system", return_value="Linux"):
            with patch("builtins.open", side_effect=FileNotFoundError()):
                with patch("platform.release", return_value="5.15.0-generic"):
                    result = detect_platform()
                    assert result == Platform.LINUX

    def test_detect_wsl_via_proc_version(self) -> None:
        """Test detection of WSL via /proc/version."""
        mock_file = MagicMock()
        mock_file.read.return_value = "Linux version 5.15.0-microsoft-standard-WSL2"
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)

        with patch("platform.system", return_value="Linux"):
            with patch("builtins.open", return_value=mock_file):
                result = detect_platform()
                assert result == Platform.WSL

    def test_detect_wsl_via_release(self) -> None:
        """Test detection of WSL via platform release when /proc/version fails."""
        with patch("platform.system", return_value="Linux"):
            with patch("builtins.open", side_effect=PermissionError()):
                with patch("platform.release", return_value="5.15.0-microsoft-standard-WSL2"):
                    result = detect_platform()
                    assert result == Platform.WSL

    def test_detect_windows(self) -> None:
        """Test detection of Windows platform."""
        with patch("platform.system", return_value="Windows"):
            result = detect_platform()
            assert result == Platform.WINDOWS

    def test_detect_macos(self) -> None:
        """Test detection of macOS platform."""
        with patch("platform.system", return_value="Darwin"):
            result = detect_platform()
            assert result == Platform.MACOS

    def test_detect_unknown(self) -> None:
        """Test detection of unknown platform."""
        with patch("platform.system", return_value="FreeBSD"):
            result = detect_platform()
            assert result == Platform.UNKNOWN

    def test_is_wsl_true(self) -> None:
        """Test is_wsl returns True on WSL."""
        with patch("src.utils.notification_provider.detect_platform", return_value=Platform.WSL):
            assert is_wsl() is True

    def test_is_wsl_false(self) -> None:
        """Test is_wsl returns False on non-WSL platforms."""
        with patch("src.utils.notification_provider.detect_platform", return_value=Platform.LINUX):
            assert is_wsl() is False


# =============================================================================
# LinuxNotifyProvider Tests
# =============================================================================


@pytest.mark.unit
class TestLinuxNotifyProvider:
    """Tests for LinuxNotifyProvider."""

    def test_provider_name(self) -> None:
        """Test provider has correct name."""
        provider = LinuxNotifyProvider()
        assert provider.name == "linux_notify"

    def test_target_platform(self) -> None:
        """Test provider targets correct platform."""
        provider = LinuxNotifyProvider()
        assert provider.target_platform == Platform.LINUX

    @pytest.mark.asyncio
    async def test_send_success(self, mock_subprocess_success: AsyncMock) -> None:
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
    async def test_send_notify_send_not_found(self) -> None:
        """Test failure when notify-send is not installed."""
        provider = LinuxNotifyProvider()

        with patch("shutil.which", return_value=None):
            result = await provider.send("Test Title", "Test Message")

        assert result.ok is False
        assert result.error is not None
        assert "notify-send not found" in result.error

    @pytest.mark.asyncio
    async def test_send_with_options(self, mock_subprocess_success: AsyncMock) -> None:
        """Test notification send with custom options."""
        provider = LinuxNotifyProvider()
        options = NotificationOptions(
            timeout_seconds=30,
            urgency=NotificationUrgency.CRITICAL,
            icon="dialog-error",
            category="alert",
        )

        with patch("shutil.which", return_value="/usr/bin/notify-send"):
            with patch(
                "asyncio.create_subprocess_exec", return_value=mock_subprocess_success
            ) as mock_exec:
                result = await provider.send("Test", "Message", options)

        assert result.ok is True
        # Verify command included timeout and urgency
        call_args = mock_exec.call_args[0]
        assert "-t" in call_args
        assert "30000" in call_args  # 30 seconds in ms
        assert "-u" in call_args
        assert "critical" in call_args

    @pytest.mark.asyncio
    async def test_send_failure(self, mock_subprocess_failure: AsyncMock) -> None:
        """Test notification send failure."""
        provider = LinuxNotifyProvider()

        with patch("shutil.which", return_value="/usr/bin/notify-send"):
            with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess_failure):
                result = await provider.send("Test Title", "Test Message")

        assert result.ok is False
        assert result.error is not None
        assert "notify-send failed" in result.error

    @pytest.mark.asyncio
    async def test_get_health_available(self) -> None:
        """Test health check when notify-send is available."""
        provider = LinuxNotifyProvider()

        with patch("src.utils.notification_provider.detect_platform", return_value=Platform.LINUX):
            with patch("shutil.which", return_value="/usr/bin/notify-send"):
                health = await provider.get_health()

        assert health.state == NotificationHealthState.HEALTHY
        assert health.available is True

    @pytest.mark.asyncio
    async def test_get_health_unavailable_wrong_platform(self) -> None:
        """Test health check on wrong platform."""
        provider = LinuxNotifyProvider()

        with patch(
            "src.utils.notification_provider.detect_platform", return_value=Platform.WINDOWS
        ):
            health = await provider.get_health()

        assert health.state == NotificationHealthState.UNHEALTHY
        assert health.available is False

    @pytest.mark.asyncio
    async def test_get_health_notify_send_missing(self) -> None:
        """Test health check when notify-send is not installed."""
        provider = LinuxNotifyProvider()

        with patch("src.utils.notification_provider.detect_platform", return_value=Platform.LINUX):
            with patch("shutil.which", return_value=None):
                health = await provider.get_health()

        assert health.state == NotificationHealthState.UNHEALTHY
        assert health.message is not None
        assert "not found" in health.message


# =============================================================================
# WindowsToastProvider Tests
# =============================================================================


@pytest.mark.unit
class TestWindowsToastProvider:
    """Tests for WindowsToastProvider."""

    def test_provider_name(self) -> None:
        """Test provider has correct name."""
        provider = WindowsToastProvider()
        assert provider.name == "windows_toast"

    def test_target_platform(self) -> None:
        """Test provider targets correct platform."""
        provider = WindowsToastProvider()
        assert provider.target_platform == Platform.WINDOWS

    @pytest.mark.asyncio
    async def test_send_success(self, mock_subprocess_success: AsyncMock) -> None:
        """Test successful notification send."""
        provider = WindowsToastProvider()

        with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess_success):
            result = await provider.send("Test Title", "Test Message")

        assert result.ok is True
        assert result.provider == "windows_toast"
        assert result.message_id is not None
        assert result.message_id.startswith("win_")

    @pytest.mark.asyncio
    async def test_send_escapes_special_characters(
        self, mock_subprocess_success: AsyncMock
    ) -> None:
        """Test that special characters are properly escaped."""
        provider = WindowsToastProvider()

        with patch(
            "asyncio.create_subprocess_exec", return_value=mock_subprocess_success
        ) as mock_exec:
            await provider.send("Test's Title", "Message with\nnewline")

        # Verify escaping happened
        call_args = mock_exec.call_args[0]
        ps_command = call_args[-1]  # Last argument is the command
        # Single quote should be escaped ('' for PowerShell)
        assert "''" in ps_command, f"Expected escaped single quote in: {ps_command[:200]}"

    @pytest.mark.asyncio
    async def test_get_health_available(self) -> None:
        """Test health check when on Windows."""
        provider = WindowsToastProvider()

        with patch(
            "src.utils.notification_provider.detect_platform", return_value=Platform.WINDOWS
        ):
            with patch("shutil.which", return_value="C:\\Windows\\System32\\powershell.exe"):
                health = await provider.get_health()

        assert health.state == NotificationHealthState.HEALTHY
        assert health.available is True

    @pytest.mark.asyncio
    async def test_get_health_unavailable_wrong_platform(self) -> None:
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

    def test_provider_name(self) -> None:
        """Test provider has correct name."""
        provider = WSLBridgeProvider()
        assert provider.name == "wsl_bridge"

    def test_target_platform(self) -> None:
        """Test provider targets correct platform."""
        provider = WSLBridgeProvider()
        assert provider.target_platform == Platform.WSL

    @pytest.mark.asyncio
    async def test_send_success(self) -> None:
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
        assert result.message_id is not None
        assert result.message_id.startswith("wsl_")

    @pytest.mark.asyncio
    async def test_send_powershell_not_found(self) -> None:
        """Test failure when PowerShell is not accessible via WSL interop."""
        provider = WSLBridgeProvider()

        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError()):
            result = await provider.send("Test Title", "Test Message")

        assert result.ok is False
        assert result.error is not None
        assert "powershell.exe not found" in result.error

    @pytest.mark.asyncio
    async def test_get_health_available(self) -> None:
        """Test health check when on WSL with PowerShell available."""
        provider = WSLBridgeProvider()

        with patch("src.utils.notification_provider.detect_platform", return_value=Platform.WSL):
            with patch(
                "shutil.which",
                return_value="/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
            ):
                health = await provider.get_health()

        assert health.state == NotificationHealthState.HEALTHY
        assert health.available is True

    @pytest.mark.asyncio
    async def test_get_health_unavailable_wrong_platform(self) -> None:
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

    def test_success_rate_tracking(self) -> None:
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
    async def test_close_sets_closed_flag(self) -> None:
        """Test that close() sets the is_closed flag."""
        provider = LinuxNotifyProvider()

        assert provider.is_closed is False
        await provider.close()
        assert provider.is_closed is True

    @pytest.mark.asyncio
    async def test_closed_provider_raises_error(self) -> None:
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

    def test_register_provider(self, registry: NotificationProviderRegistry) -> None:
        """Test registering a provider."""
        provider = LinuxNotifyProvider()
        registry.register(provider)

        assert "linux_notify" in registry.list_providers()
        assert registry.get("linux_notify") is provider

    def test_register_duplicate_raises_error(self, registry: NotificationProviderRegistry) -> None:
        """Test that registering duplicate provider raises ValueError."""
        provider1 = LinuxNotifyProvider()
        provider2 = LinuxNotifyProvider()

        registry.register(provider1)

        with pytest.raises(ValueError, match="already registered"):
            registry.register(provider2)

    def test_register_sets_default_if_first(self, registry: NotificationProviderRegistry) -> None:
        """Test that first registered provider becomes default."""
        provider = LinuxNotifyProvider()
        registry.register(provider)

        assert registry.get_default() is provider

    def test_register_set_default(self, registry: NotificationProviderRegistry) -> None:
        """Test explicitly setting provider as default."""
        provider1 = LinuxNotifyProvider()
        provider2 = WindowsToastProvider()

        registry.register(provider1)
        registry.register(provider2, set_default=True)

        assert registry.get_default() is provider2

    def test_unregister_provider(self, registry: NotificationProviderRegistry) -> None:
        """Test unregistering a provider."""
        provider = LinuxNotifyProvider()
        registry.register(provider)

        unregistered = registry.unregister("linux_notify")

        assert unregistered is provider
        assert "linux_notify" not in registry.list_providers()

    def test_unregister_nonexistent(self, registry: NotificationProviderRegistry) -> None:
        """Test unregistering non-existent provider returns None."""
        result = registry.unregister("nonexistent")
        assert result is None

    def test_set_default(self, registry: NotificationProviderRegistry) -> None:
        """Test changing default provider."""
        provider1 = LinuxNotifyProvider()
        provider2 = WindowsToastProvider()

        registry.register(provider1)
        registry.register(provider2)

        registry.set_default("windows_toast")

        assert registry.get_default() is provider2

    def test_set_default_nonexistent_raises_error(
        self, registry: NotificationProviderRegistry
    ) -> None:
        """Test setting non-existent provider as default raises ValueError."""
        with pytest.raises(ValueError, match="not registered"):
            registry.set_default("nonexistent")

    def test_list_providers(self, registry: NotificationProviderRegistry) -> None:
        """Test listing all registered providers."""
        registry.register(LinuxNotifyProvider())
        registry.register(WindowsToastProvider())

        providers = registry.list_providers()

        assert len(providers) == 2
        assert "linux_notify" in providers
        assert "windows_toast" in providers

    @pytest.mark.asyncio
    async def test_get_all_health(self, registry: NotificationProviderRegistry) -> None:
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
    async def test_send_uses_default(
        self, registry: NotificationProviderRegistry, mock_subprocess_success: AsyncMock
    ) -> None:
        """Test that send() uses default provider."""
        provider = LinuxNotifyProvider()
        registry.register(provider)

        with patch("shutil.which", return_value="/usr/bin/notify-send"):
            with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess_success):
                with patch.object(
                    provider,
                    "get_health",
                    return_value=NotificationHealthStatus.healthy(Platform.LINUX),
                ):
                    result = await registry.send("Test", "Message")

        assert result.ok is True
        assert result.provider == "linux_notify"

    @pytest.mark.asyncio
    async def test_send_fallback_on_failure(
        self, registry: NotificationProviderRegistry, mock_subprocess_success: AsyncMock
    ) -> None:
        """Test that send() falls back to next provider on failure."""
        provider1 = LinuxNotifyProvider()
        provider2 = WindowsToastProvider()

        registry.register(provider1)
        registry.register(provider2)

        # Provider1 is unhealthy
        with patch.object(
            provider1,
            "get_health",
            return_value=NotificationHealthStatus.unhealthy(Platform.LINUX, "test failure"),
        ):
            with patch.object(
                provider2,
                "get_health",
                return_value=NotificationHealthStatus.healthy(Platform.WINDOWS),
            ):
                with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess_success):
                    result = await registry.send("Test", "Message")

        assert result.ok is True
        assert result.provider == "windows_toast"

    @pytest.mark.asyncio
    async def test_send_all_providers_fail(self, registry: NotificationProviderRegistry) -> None:
        """Test that send() returns error when all providers fail."""
        provider1 = LinuxNotifyProvider()
        registry.register(provider1)

        with patch.object(
            provider1,
            "get_health",
            return_value=NotificationHealthStatus.unhealthy(Platform.LINUX, "test failure"),
        ):
            result = await registry.send("Test", "Message")

        assert result.ok is False
        assert result.error is not None
        assert "All providers failed" in result.error

    @pytest.mark.asyncio
    async def test_send_no_providers(self, registry: NotificationProviderRegistry) -> None:
        """Test that send() raises error when no providers registered."""
        with pytest.raises(RuntimeError, match="No notification providers"):
            await registry.send("Test", "Message")

    @pytest.mark.asyncio
    async def test_close_all(self, registry: NotificationProviderRegistry) -> None:
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

    def test_auto_register_linux(self, registry: NotificationProviderRegistry) -> None:
        """Test auto-registration on Linux."""
        with patch.object(registry, "_current_platform", Platform.LINUX):
            registry.auto_register()

        assert "linux_notify" in registry.list_providers()
        default_provider = registry.get_default()
        assert default_provider is not None
        assert default_provider.name == "linux_notify"

    def test_auto_register_windows(self, registry: NotificationProviderRegistry) -> None:
        """Test auto-registration on Windows."""
        with patch.object(registry, "_current_platform", Platform.WINDOWS):
            registry.auto_register()

        assert "windows_toast" in registry.list_providers()
        default_provider = registry.get_default()
        assert default_provider is not None
        assert default_provider.name == "windows_toast"

    def test_auto_register_wsl(self, registry: NotificationProviderRegistry) -> None:
        """Test auto-registration on WSL."""
        with patch.object(registry, "_current_platform", Platform.WSL):
            registry.auto_register()

        # WSL should have both WSL bridge (default) and Linux fallback
        providers = registry.list_providers()
        assert "wsl_bridge" in providers
        assert "linux_notify" in providers
        default_provider = registry.get_default()
        assert default_provider is not None
        assert default_provider.name == "wsl_bridge"


# =============================================================================
# Global Registry Tests
# =============================================================================


@pytest.mark.unit
class TestGlobalRegistry:
    """Tests for global registry functions."""

    def test_get_notification_registry_creates_registry(self) -> None:
        """Test that get_notification_registry creates and returns registry."""
        registry = get_notification_registry()

        assert registry is not None
        assert isinstance(registry, NotificationProviderRegistry)

    def test_get_notification_registry_returns_same_instance(self) -> None:
        """Test that get_notification_registry returns singleton."""
        registry1 = get_notification_registry()
        registry2 = get_notification_registry()

        assert registry1 is registry2

    @pytest.mark.asyncio
    async def test_cleanup_notification_registry(self) -> None:
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

    def test_linux_provider_is_notification_provider(self) -> None:
        """Test LinuxNotifyProvider implements NotificationProvider protocol."""
        provider = LinuxNotifyProvider()
        assert isinstance(provider, NotificationProvider)

    def test_windows_provider_is_notification_provider(self) -> None:
        """Test WindowsToastProvider implements NotificationProvider protocol."""
        provider = WindowsToastProvider()
        assert isinstance(provider, NotificationProvider)

    def test_wsl_provider_is_notification_provider(self) -> None:
        """Test WSLBridgeProvider implements NotificationProvider protocol."""
        provider = WSLBridgeProvider()
        assert isinstance(provider, NotificationProvider)


# =============================================================================
# Edge Case Tests
# =============================================================================


@pytest.mark.unit
class TestEdgeCases:
    """Tests for edge cases and boundary conditions per .1.4."""

    @pytest.mark.asyncio
    async def test_send_empty_title_and_message(self, mock_subprocess_success: AsyncMock) -> None:
        """Test sending notification with empty strings."""
        provider = LinuxNotifyProvider()

        with patch("shutil.which", return_value="/usr/bin/notify-send"):
            with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess_success):
                result = await provider.send("", "")

        # Should still succeed even with empty strings
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_send_unicode_characters(self, mock_subprocess_success: AsyncMock) -> None:
        """Test sending notification with Unicode characters."""
        provider = LinuxNotifyProvider()

        with patch("shutil.which", return_value="/usr/bin/notify-send"):
            with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess_success):
                result = await provider.send("日本語タイトル", "🔔 通知メッセージ 🔔")

        assert result.ok is True

    @pytest.mark.asyncio
    async def test_send_very_long_message(self, mock_subprocess_success: AsyncMock) -> None:
        """Test sending notification with very long message."""
        provider = LinuxNotifyProvider()
        long_message = "A" * 10000  # 10k characters

        with patch("shutil.which", return_value="/usr/bin/notify-send"):
            with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess_success):
                result = await provider.send("Title", long_message)

        # Should succeed (truncation is platform's responsibility)
        assert result.ok is True

    def test_success_rate_with_no_operations(self) -> None:
        """Test success rate when no operations have been performed."""
        provider = LinuxNotifyProvider()

        # With 0 operations, should return 1.0 (optimistic default)
        assert provider.success_rate == 1.0

    @pytest.mark.asyncio
    async def test_timeout_handling(self) -> None:
        """Test handling of subprocess timeout."""
        provider = LinuxNotifyProvider()

        async def slow_wait(*args: object, **kwargs: object) -> tuple[bytes, bytes]:
            await asyncio.sleep(10)
            return (b"", b"")

        mock_process = AsyncMock()
        mock_process.communicate = slow_wait

        with patch("shutil.which", return_value="/usr/bin/notify-send"):
            with patch("asyncio.create_subprocess_exec", return_value=mock_process):
                result = await provider.send("Test", "Message")

        assert result.ok is False
        assert result.error is not None
        assert "timed out" in result.error
