"""
Notification provider abstraction layer for Lyra.

Provides a unified interface for notification providers, enabling easy
switching between different backends (Linux notify-send, Windows Toast, WSL).
"""

import asyncio
import platform
import shutil
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from src.utils.logging import get_logger

logger = get_logger(__name__)


# ============================================================================
# Data Classes for Notifications
# ============================================================================


class NotificationUrgency(str, Enum):
    """Notification urgency levels."""

    LOW = "low"
    NORMAL = "normal"
    CRITICAL = "critical"


class NotificationHealthState(str, Enum):
    """Provider health states."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class Platform(str, Enum):
    """Supported platforms."""

    LINUX = "linux"
    WINDOWS = "windows"
    WSL = "wsl"
    MACOS = "macos"
    UNKNOWN = "unknown"


@dataclass
class NotificationOptions:
    """
    Options for notification requests.

    Attributes:
        timeout_seconds: Display duration in seconds.
        urgency: Notification urgency level.
        icon: Icon name or path (platform-specific).
        sound: Whether to play notification sound.
        category: Notification category hint.
    """

    timeout_seconds: int = 10
    urgency: NotificationUrgency = NotificationUrgency.NORMAL
    icon: str | None = None
    sound: bool = True
    category: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timeout_seconds": self.timeout_seconds,
            "urgency": self.urgency.value,
            "icon": self.icon,
            "sound": self.sound,
            "category": self.category,
        }


@dataclass
class NotificationResult:
    """
    Result of a notification send operation.

    Attributes:
        ok: Whether notification was sent successfully.
        provider: Provider name that sent the notification.
        message_id: Platform-specific message identifier (if available).
        error: Error message if notification failed.
        elapsed_ms: Time taken in milliseconds.
    """

    ok: bool
    provider: str
    message_id: str | None = None
    error: str | None = None
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "ok": self.ok,
            "provider": self.provider,
            "message_id": self.message_id,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
        }

    @classmethod
    def success(
        cls,
        provider: str,
        message_id: str | None = None,
        elapsed_ms: float = 0.0,
    ) -> NotificationResult:
        """Create a successful result."""
        return cls(
            ok=True,
            provider=provider,
            message_id=message_id,
            elapsed_ms=elapsed_ms,
        )

    @classmethod
    def failure(
        cls,
        provider: str,
        error: str,
        elapsed_ms: float = 0.0,
    ) -> NotificationResult:
        """Create a failure result."""
        return cls(
            ok=False,
            provider=provider,
            error=error,
            elapsed_ms=elapsed_ms,
        )


@dataclass
class NotificationHealthStatus:
    """
    Health status of a notification provider.

    Attributes:
        state: Current health state.
        available: Whether the provider is available on this platform.
        platform: Platform this provider targets.
        success_rate: Recent success rate (0.0 to 1.0).
        last_check: Last health check time.
        message: Optional status message.
        details: Additional health details.
    """

    state: NotificationHealthState
    available: bool = True
    platform: Platform = Platform.UNKNOWN
    success_rate: float = 1.0
    last_check: datetime | None = None
    message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def healthy(
        cls,
        platform: Platform,
        message: str | None = None,
    ) -> NotificationHealthStatus:
        """Create a healthy status."""
        return cls(
            state=NotificationHealthState.HEALTHY,
            available=True,
            platform=platform,
            success_rate=1.0,
            last_check=datetime.now(UTC),
            message=message,
        )

    @classmethod
    def degraded(
        cls,
        platform: Platform,
        success_rate: float,
        message: str | None = None,
    ) -> NotificationHealthStatus:
        """Create a degraded status."""
        return cls(
            state=NotificationHealthState.DEGRADED,
            available=True,
            platform=platform,
            success_rate=success_rate,
            message=message,
            last_check=datetime.now(UTC),
        )

    @classmethod
    def unhealthy(
        cls,
        platform: Platform,
        message: str | None = None,
    ) -> NotificationHealthStatus:
        """Create an unhealthy status."""
        return cls(
            state=NotificationHealthState.UNHEALTHY,
            available=False,
            platform=platform,
            success_rate=0.0,
            message=message,
            last_check=datetime.now(UTC),
        )

    @classmethod
    def unavailable(
        cls,
        platform: Platform,
        message: str | None = None,
    ) -> NotificationHealthStatus:
        """Create an unavailable status (platform/dependency not available)."""
        return cls(
            state=NotificationHealthState.UNHEALTHY,
            available=False,
            platform=platform,
            success_rate=0.0,
            message=message or "Provider not available on this platform",
            last_check=datetime.now(UTC),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "state": self.state.value,
            "available": self.available,
            "platform": self.platform.value,
            "success_rate": self.success_rate,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "message": self.message,
            "details": self.details,
        }


# ============================================================================
# Platform Detection
# ============================================================================


def detect_platform() -> Platform:
    """
    Detect the current platform.

    Returns:
        Platform enum indicating the current OS/environment.
    """
    system = platform.system().lower()

    if system == "linux":
        # Check for WSL
        try:
            with open("/proc/version") as f:
                if "microsoft" in f.read().lower():
                    return Platform.WSL
        except (FileNotFoundError, PermissionError):
            # Check kernel release as fallback
            if "microsoft" in platform.release().lower():
                return Platform.WSL
        return Platform.LINUX
    elif system == "windows":
        return Platform.WINDOWS
    elif system == "darwin":
        return Platform.MACOS
    else:
        return Platform.UNKNOWN


def is_wsl() -> bool:
    """Check if running in WSL."""
    return detect_platform() == Platform.WSL


# ============================================================================
# Notification Provider Protocol
# ============================================================================


@runtime_checkable
class NotificationProvider(Protocol):
    """
    Protocol for notification providers.

    Defines the interface that all notification providers must implement.
    Uses Python's Protocol for structural subtyping.

    Example implementation:
        class MyProvider:
            @property
            def name(self) -> str:
                return "my_provider"

            async def send(
                self,
                title: str,
                message: str,
                options: NotificationOptions | None = None,
            ) -> NotificationResult:
                # Implementation
                ...

            async def get_health(self) -> NotificationHealthStatus:
                return NotificationHealthStatus.healthy(Platform.LINUX)

            async def close(self) -> None:
                # Cleanup
                ...
    """

    @property
    def name(self) -> str:
        """Unique name of the provider."""
        ...

    @property
    def target_platform(self) -> Platform:
        """Target platform for this provider."""
        ...

    async def send(
        self,
        title: str,
        message: str,
        options: NotificationOptions | None = None,
    ) -> NotificationResult:
        """
        Send a notification.

        Args:
            title: Notification title.
            message: Notification body text.
            options: Notification options (timeout, urgency, etc.).

        Returns:
            NotificationResult with success/failure status.
        """
        ...

    async def get_health(self) -> NotificationHealthStatus:
        """
        Get current health status.

        Returns:
            NotificationHealthStatus indicating provider health.
        """
        ...

    async def close(self) -> None:
        """
        Close and cleanup provider resources.

        Should be called when the provider is no longer needed.
        """
        ...


class BaseNotificationProvider(ABC):
    """
    Abstract base class for notification providers.

    Provides common functionality and enforces the interface contract.
    Subclasses should implement the abstract methods.
    """

    def __init__(self, provider_name: str, target_platform: Platform):
        """
        Initialize base provider.

        Args:
            provider_name: Unique name for this provider.
            target_platform: Platform this provider targets.
        """
        self._name = provider_name
        self._target_platform = target_platform
        self._is_closed = False
        self._success_count = 0
        self._failure_count = 0

    @property
    def name(self) -> str:
        """Unique name of the provider."""
        return self._name

    @property
    def target_platform(self) -> Platform:
        """Target platform for this provider."""
        return self._target_platform

    @property
    def is_closed(self) -> bool:
        """Check if provider is closed."""
        return self._is_closed

    @property
    def success_rate(self) -> float:
        """Calculate success rate from recent operations."""
        total = self._success_count + self._failure_count
        if total == 0:
            return 1.0
        return self._success_count / total

    def _record_success(self) -> None:
        """Record a successful operation."""
        self._success_count += 1

    def _record_failure(self) -> None:
        """Record a failed operation."""
        self._failure_count += 1

    @abstractmethod
    async def send(
        self,
        title: str,
        message: str,
        options: NotificationOptions | None = None,
    ) -> NotificationResult:
        """Send a notification."""
        pass

    @abstractmethod
    async def get_health(self) -> NotificationHealthStatus:
        """Get current health status."""
        pass

    async def close(self) -> None:
        """Close and cleanup provider resources."""
        self._is_closed = True
        logger.debug("Notification provider closed", provider=self._name)

    def _check_closed(self) -> None:
        """Raise error if provider is closed."""
        if self._is_closed:
            raise RuntimeError(f"Provider '{self._name}' is closed")


# ============================================================================
# Linux Notification Provider (notify-send)
# ============================================================================


class LinuxNotifyProvider(BaseNotificationProvider):
    """
    Linux notification provider using notify-send.

    Uses libnotify/notify-send for desktop notifications on Linux.
    """

    def __init__(self) -> None:
        """Initialize Linux notification provider."""
        super().__init__("linux_notify", Platform.LINUX)
        self._notify_send_path: str | None = None

    def _find_notify_send(self) -> str | None:
        """Find notify-send executable path."""
        if self._notify_send_path is not None:
            return self._notify_send_path

        self._notify_send_path = shutil.which("notify-send")
        return self._notify_send_path

    async def send(
        self,
        title: str,
        message: str,
        options: NotificationOptions | None = None,
    ) -> NotificationResult:
        """
        Send notification using notify-send.

        Args:
            title: Notification title.
            message: Notification body.
            options: Notification options.

        Returns:
            NotificationResult with status.
        """
        self._check_closed()

        if options is None:
            options = NotificationOptions()

        start_time = time.time()

        notify_send = self._find_notify_send()
        if notify_send is None:
            self._record_failure()
            return NotificationResult.failure(
                provider=self.name,
                error="notify-send not found, install libnotify-bin",
            )

        # Build command
        cmd = [
            notify_send,
            "-t",
            str(options.timeout_seconds * 1000),  # Convert to ms
            "-u",
            self._map_urgency(options.urgency),
        ]

        if options.icon:
            cmd.extend(["-i", options.icon])
        else:
            cmd.extend(["-i", "dialog-information"])

        if options.category:
            cmd.extend(["-c", options.category])

        cmd.extend([title, message])

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=5.0,
            )

            elapsed_ms = (time.time() - start_time) * 1000

            if process.returncode == 0:
                self._record_success()
                return NotificationResult.success(
                    provider=self.name,
                    message_id=f"linux_{uuid.uuid4().hex[:8]}",
                    elapsed_ms=elapsed_ms,
                )
            else:
                self._record_failure()
                error_msg = stderr.decode().strip() if stderr else "Unknown error"
                return NotificationResult.failure(
                    provider=self.name,
                    error=f"notify-send failed: {error_msg}",
                    elapsed_ms=elapsed_ms,
                )

        except TimeoutError:
            self._record_failure()
            return NotificationResult.failure(
                provider=self.name,
                error="notify-send timed out",
                elapsed_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            self._record_failure()
            return NotificationResult.failure(
                provider=self.name,
                error=str(e),
                elapsed_ms=(time.time() - start_time) * 1000,
            )

    def _map_urgency(self, urgency: NotificationUrgency) -> str:
        """Map urgency to notify-send format."""
        mapping = {
            NotificationUrgency.LOW: "low",
            NotificationUrgency.NORMAL: "normal",
            NotificationUrgency.CRITICAL: "critical",
        }
        return mapping.get(urgency, "normal")

    async def get_health(self) -> NotificationHealthStatus:
        """Check if notify-send is available."""
        current_platform = detect_platform()

        if current_platform not in (Platform.LINUX,):
            return NotificationHealthStatus.unavailable(
                platform=self._target_platform,
                message=f"Linux provider not available on {current_platform.value}",
            )

        if self._find_notify_send() is None:
            return NotificationHealthStatus.unhealthy(
                platform=self._target_platform,
                message="notify-send not found",
            )

        if self.success_rate < 0.5:
            return NotificationHealthStatus.degraded(
                platform=self._target_platform,
                success_rate=self.success_rate,
                message="High failure rate",
            )

        return NotificationHealthStatus.healthy(
            platform=self._target_platform,
            message="notify-send available",
        )


# ============================================================================
# Windows Toast Notification Provider
# ============================================================================


class WindowsToastProvider(BaseNotificationProvider):
    """
    Windows notification provider using PowerShell Toast API.

    Uses Windows UWP Toast Notification API via PowerShell.
    """

    def __init__(self) -> None:
        """Initialize Windows toast provider."""
        super().__init__("windows_toast", Platform.WINDOWS)

    async def send(
        self,
        title: str,
        message: str,
        options: NotificationOptions | None = None,
    ) -> NotificationResult:
        """
        Send notification using Windows Toast API.

        Args:
            title: Notification title.
            message: Notification body.
            options: Notification options.

        Returns:
            NotificationResult with status.
        """
        self._check_closed()

        if options is None:
            options = NotificationOptions()

        start_time = time.time()

        # Escape special characters for PowerShell
        title_escaped = title.replace("'", "''").replace("`", "``")
        message_escaped = message.replace("'", "''").replace("`", "``").replace("\n", "&#10;")

        # Build PowerShell script for UWP Toast
        sound_element = (
            '<audio src="ms-winsoundevent:Notification.Reminder"/>'
            if options.sound
            else '<audio silent="true"/>'
        )

        ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

$template = @"
<toast duration="long" scenario="reminder">
    <visual>
        <binding template="ToastText02">
            <text id="1">{title_escaped}</text>
            <text id="2">{message_escaped}</text>
        </binding>
    </visual>
    {sound_element}
</toast>
"@

$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)

$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Lyra").Show($toast)
"""

        try:
            process = await asyncio.create_subprocess_exec(
                "powershell.exe",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps_script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=10.0,
            )

            elapsed_ms = (time.time() - start_time) * 1000

            if process.returncode == 0:
                self._record_success()
                return NotificationResult.success(
                    provider=self.name,
                    message_id=f"win_{uuid.uuid4().hex[:8]}",
                    elapsed_ms=elapsed_ms,
                )
            else:
                self._record_failure()
                error_msg = stderr.decode().strip() if stderr else "Unknown error"
                return NotificationResult.failure(
                    provider=self.name,
                    error=f"PowerShell toast failed: {error_msg}",
                    elapsed_ms=elapsed_ms,
                )

        except FileNotFoundError:
            self._record_failure()
            return NotificationResult.failure(
                provider=self.name,
                error="powershell.exe not found",
                elapsed_ms=(time.time() - start_time) * 1000,
            )
        except TimeoutError:
            self._record_failure()
            return NotificationResult.failure(
                provider=self.name,
                error="PowerShell toast timed out",
                elapsed_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            self._record_failure()
            return NotificationResult.failure(
                provider=self.name,
                error=str(e),
                elapsed_ms=(time.time() - start_time) * 1000,
            )

    async def get_health(self) -> NotificationHealthStatus:
        """Check if Windows Toast API is available."""
        current_platform = detect_platform()

        if current_platform != Platform.WINDOWS:
            return NotificationHealthStatus.unavailable(
                platform=self._target_platform,
                message=f"Windows provider not available on {current_platform.value}",
            )

        # Check if PowerShell is available
        if shutil.which("powershell.exe") is None:
            return NotificationHealthStatus.unhealthy(
                platform=self._target_platform,
                message="powershell.exe not found",
            )

        if self.success_rate < 0.5:
            return NotificationHealthStatus.degraded(
                platform=self._target_platform,
                success_rate=self.success_rate,
                message="High failure rate",
            )

        return NotificationHealthStatus.healthy(
            platform=self._target_platform,
            message="Windows Toast API available",
        )


# ============================================================================
# WSL Bridge Notification Provider
# ============================================================================


class WSLBridgeProvider(BaseNotificationProvider):
    """
    WSL notification provider bridging to Windows.

    Uses PowerShell via WSL interop to send Windows notifications.
    Supports BurntToast module if available, falls back to NotifyIcon.
    """

    def __init__(self) -> None:
        """Initialize WSL bridge provider."""
        super().__init__("wsl_bridge", Platform.WSL)

    async def send(
        self,
        title: str,
        message: str,
        options: NotificationOptions | None = None,
    ) -> NotificationResult:
        """
        Send notification from WSL to Windows.

        Args:
            title: Notification title.
            message: Notification body.
            options: Notification options.

        Returns:
            NotificationResult with status.
        """
        self._check_closed()

        if options is None:
            options = NotificationOptions()

        start_time = time.time()

        # Escape for PowerShell
        # For BurntToast: Use `n (backtick-n) for newlines in PowerShell strings
        # For NotifyIcon: Newlines work directly
        title_escaped = title.replace("'", "''").replace('"', '`"').replace("\n", " ")
        message_escaped = message.replace("'", "''").replace('"', '`"')
        # BurntToast uses backtick-n for newlines within PowerShell strings
        message_for_burnttoast = message_escaped.replace("\n", "`n")
        # NotifyIcon balloon tips work with actual newlines
        message_for_notifyicon = message_escaped

        # Try BurntToast first (better notifications), fallback to NotifyIcon
        ps_script = f"""
if (Get-Module -ListAvailable -Name BurntToast) {{
    Import-Module BurntToast
    New-BurntToastNotification -Text '{title_escaped}', '{message_for_burnttoast}' -Sound 'Reminder'
}} else {{
    Add-Type -AssemblyName System.Windows.Forms
    $balloon = New-Object System.Windows.Forms.NotifyIcon
    $balloon.Icon = [System.Drawing.SystemIcons]::Warning
    $balloon.BalloonTipTitle = '{title_escaped}'
    $balloon.BalloonTipText = '{message_for_notifyicon}'
    $balloon.BalloonTipIcon = 'Warning'
    $balloon.Visible = $true
    $balloon.ShowBalloonTip({options.timeout_seconds * 1000})
    Start-Sleep -Seconds {options.timeout_seconds + 1}
    $balloon.Dispose()
}}
"""

        try:
            await asyncio.create_subprocess_exec(
                "powershell.exe",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps_script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Don't wait for completion for balloon notifications
            # They run async and clean up themselves
            elapsed_ms = (time.time() - start_time) * 1000

            self._record_success()
            return NotificationResult.success(
                provider=self.name,
                message_id=f"wsl_{uuid.uuid4().hex[:8]}",
                elapsed_ms=elapsed_ms,
            )

        except FileNotFoundError:
            self._record_failure()
            return NotificationResult.failure(
                provider=self.name,
                error="powershell.exe not found (WSL interop may be disabled)",
                elapsed_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            self._record_failure()
            return NotificationResult.failure(
                provider=self.name,
                error=str(e),
                elapsed_ms=(time.time() - start_time) * 1000,
            )

    async def get_health(self) -> NotificationHealthStatus:
        """Check if WSL bridge is available."""
        current_platform = detect_platform()

        if current_platform != Platform.WSL:
            return NotificationHealthStatus.unavailable(
                platform=self._target_platform,
                message=f"WSL provider not available on {current_platform.value}",
            )

        # Check if PowerShell is accessible via WSL interop
        if shutil.which("powershell.exe") is None:
            return NotificationHealthStatus.unhealthy(
                platform=self._target_platform,
                message="powershell.exe not accessible (WSL interop may be disabled)",
            )

        if self.success_rate < 0.5:
            return NotificationHealthStatus.degraded(
                platform=self._target_platform,
                success_rate=self.success_rate,
                message="High failure rate",
            )

        return NotificationHealthStatus.healthy(
            platform=self._target_platform,
            message="WSL-Windows bridge available",
        )


# ============================================================================
# Provider Registry
# ============================================================================


class NotificationProviderRegistry:
    """
    Registry for notification providers.

    Manages registration, retrieval, and lifecycle of notification providers.
    Supports platform auto-detection and fallback selection.

    Example usage:
        registry = NotificationProviderRegistry()
        registry.auto_register()  # Auto-detect platform and register providers

        # Send notification
        result = await registry.send(title, message)

        # Or use specific provider
        provider = registry.get("linux_notify")
        result = await provider.send(title, message)
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._providers: dict[str, NotificationProvider] = {}
        self._default_name: str | None = None
        self._current_platform: Platform = detect_platform()

    @property
    def current_platform(self) -> Platform:
        """Get current platform."""
        return self._current_platform

    def register(
        self,
        provider: NotificationProvider,
        set_default: bool = False,
    ) -> None:
        """
        Register a notification provider.

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
            "Notification provider registered",
            provider=name,
            platform=provider.target_platform.value,
            is_default=set_default or self._default_name == name,
        )

    def unregister(self, name: str) -> NotificationProvider | None:
        """
        Unregister a provider by name.

        Args:
            name: Provider name to unregister.

        Returns:
            The unregistered provider, or None if not found.
        """
        provider = self._providers.pop(name, None)

        if provider is not None:
            logger.info("Notification provider unregistered", provider=name)

            # Update default if needed
            if self._default_name == name:
                self._default_name = next(iter(self._providers), None)

        return provider

    def get(self, name: str) -> NotificationProvider | None:
        """
        Get a provider by name.

        Args:
            name: Provider name.

        Returns:
            Provider instance or None if not found.
        """
        return self._providers.get(name)

    def get_default(self) -> NotificationProvider | None:
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
        logger.info("Default notification provider changed", provider=name)

    def list_providers(self) -> list[str]:
        """
        List all registered provider names.

        Returns:
            List of provider names.
        """
        return list(self._providers.keys())

    def auto_register(self) -> None:
        """
        Auto-detect platform and register appropriate providers.

        Registers providers suitable for the current platform and
        sets the most appropriate one as default.
        """
        platform = self._current_platform

        if platform == Platform.LINUX:
            self.register(LinuxNotifyProvider(), set_default=True)
        elif platform == Platform.WINDOWS:
            self.register(WindowsToastProvider(), set_default=True)
        elif platform == Platform.WSL:
            # WSL: Register WSL bridge as default, Linux as fallback
            self.register(WSLBridgeProvider(), set_default=True)
            self.register(LinuxNotifyProvider())
        else:
            logger.warning(
                "Unknown platform, no providers registered",
                platform=platform.value,
            )

    async def get_all_health(self) -> dict[str, NotificationHealthStatus]:
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
                health[name] = NotificationHealthStatus.unhealthy(
                    platform=provider.target_platform,
                    message=str(e),
                )
        return health

    async def send(
        self,
        title: str,
        message: str,
        options: NotificationOptions | None = None,
    ) -> NotificationResult:
        """
        Send notification using the default provider with fallback.

        Args:
            title: Notification title.
            message: Notification body.
            options: Notification options.

        Returns:
            NotificationResult from first successful provider.

        Raises:
            RuntimeError: If no providers available.
        """
        if not self._providers:
            raise RuntimeError("No notification providers registered")

        # Try default provider first
        errors = []
        provider_order = []

        if self._default_name:
            provider_order.append(self._default_name)
        provider_order.extend(n for n in self._providers if n not in provider_order)

        for name in provider_order:
            provider = self._providers.get(name)
            if provider is None:
                continue

            try:
                # Check health first
                health = await provider.get_health()
                if health.state == NotificationHealthState.UNHEALTHY:
                    logger.debug(
                        "Skipping unhealthy provider",
                        provider=name,
                        message=health.message,
                    )
                    errors.append(f"{name}: unhealthy ({health.message})")
                    continue

                # Send notification
                result = await provider.send(title, message, options)

                if result.ok:
                    return result

                # Send failed
                errors.append(f"{name}: {result.error}")
                logger.warning(
                    "Notification provider failed",
                    provider=name,
                    error=result.error,
                )

            except Exception as e:
                errors.append(f"{name}: {str(e)}")
                logger.error("Notification provider error", provider=name, error=str(e))

        # All providers failed
        error_msg = "; ".join(errors) if errors else "No providers available"
        return NotificationResult.failure(
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
        logger.info("All notification providers closed")


# ============================================================================
# Global Registry
# ============================================================================

_registry: NotificationProviderRegistry | None = None


def get_notification_registry() -> NotificationProviderRegistry:
    """
    Get the global notification provider registry.

    Returns:
        The global NotificationProviderRegistry instance.
    """
    global _registry
    if _registry is None:
        _registry = NotificationProviderRegistry()
        _registry.auto_register()
    return _registry


async def cleanup_notification_registry() -> None:
    """
    Cleanup the global registry.

    Closes all providers and resets the registry.
    """
    global _registry
    if _registry is not None:
        await _registry.close_all()
        _registry = None


def reset_notification_registry() -> None:
    """
    Reset the global registry without closing providers.

    For testing purposes only.
    """
    global _registry
    _registry = None
