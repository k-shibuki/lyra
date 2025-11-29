"""
Browser provider abstraction layer for Lancet.

Provides a unified interface for browser automation providers, enabling easy
switching between different backends (Playwright, undetected-chromedriver).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from src.utils.logging import get_logger

logger = get_logger(__name__)


# ============================================================================
# Data Classes for Browser Operations
# ============================================================================


class BrowserMode(str, Enum):
    """Browser execution mode."""
    HEADLESS = "headless"
    HEADFUL = "headful"


class BrowserHealthState(str, Enum):
    """Provider health states."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class Cookie:
    """
    Browser cookie data structure.
    
    Attributes:
        name: Cookie name.
        value: Cookie value.
        domain: Cookie domain.
        path: Cookie path.
        expires: Expiration timestamp.
        http_only: HTTP only flag.
        secure: Secure flag.
        same_site: SameSite attribute.
    """
    name: str
    value: str
    domain: str = ""
    path: str = "/"
    expires: float | None = None
    http_only: bool = False
    secure: bool = False
    same_site: str = "Lax"
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for Playwright/Selenium compatibility."""
        result = {
            "name": self.name,
            "value": self.value,
            "domain": self.domain,
            "path": self.path,
            "httpOnly": self.http_only,
            "secure": self.secure,
            "sameSite": self.same_site,
        }
        if self.expires is not None:
            result["expires"] = self.expires
        return result
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Cookie":
        """Create from dictionary."""
        return cls(
            name=data.get("name", ""),
            value=data.get("value", ""),
            domain=data.get("domain", ""),
            path=data.get("path", "/"),
            expires=data.get("expires"),
            http_only=data.get("httpOnly", data.get("http_only", False)),
            secure=data.get("secure", False),
            same_site=data.get("sameSite", data.get("same_site", "Lax")),
        )


@dataclass
class BrowserOptions:
    """
    Options for browser navigation.
    
    Attributes:
        mode: Browser mode (headless/headful).
        timeout: Page load timeout in seconds.
        viewport_width: Viewport width in pixels.
        viewport_height: Viewport height in pixels.
        wait_until: Wait condition (domcontentloaded, load, networkidle).
        referer: Referer header.
        simulate_human: Whether to simulate human-like behavior.
        take_screenshot: Whether to capture screenshot after navigation.
        block_resources: Resource types to block (ads, trackers, media).
    """
    mode: BrowserMode = BrowserMode.HEADLESS
    timeout: float = 30.0
    viewport_width: int = 1920
    viewport_height: int = 1080
    wait_until: str = "domcontentloaded"
    referer: str | None = None
    simulate_human: bool = True
    take_screenshot: bool = True
    block_resources: bool = True
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "mode": self.mode.value,
            "timeout": self.timeout,
            "viewport_width": self.viewport_width,
            "viewport_height": self.viewport_height,
            "wait_until": self.wait_until,
            "referer": self.referer,
            "simulate_human": self.simulate_human,
            "take_screenshot": self.take_screenshot,
            "block_resources": self.block_resources,
        }


@dataclass
class PageResult:
    """
    Result of a browser navigation operation.
    
    Attributes:
        ok: Whether navigation was successful.
        url: Final URL after redirects.
        status: HTTP status code.
        content: Page HTML content.
        content_hash: SHA256 hash of content.
        cookies: Cookies from the page.
        screenshot_path: Path to screenshot if taken.
        html_path: Path to saved HTML.
        error: Error message if navigation failed.
        provider: Provider name that produced this result.
        mode: Browser mode used (headless/headful).
        elapsed_ms: Time taken in milliseconds.
        challenge_detected: Whether a challenge/CAPTCHA was detected.
        challenge_type: Type of challenge if detected.
    """
    ok: bool
    url: str
    status: int | None = None
    content: str | None = None
    content_hash: str | None = None
    cookies: list[Cookie] = field(default_factory=list)
    screenshot_path: str | None = None
    html_path: str | None = None
    error: str | None = None
    provider: str = ""
    mode: BrowserMode = BrowserMode.HEADLESS
    elapsed_ms: float = 0.0
    challenge_detected: bool = False
    challenge_type: str | None = None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "ok": self.ok,
            "url": self.url,
            "status": self.status,
            "content_hash": self.content_hash,
            "cookies_count": len(self.cookies),
            "screenshot_path": self.screenshot_path,
            "html_path": self.html_path,
            "error": self.error,
            "provider": self.provider,
            "mode": self.mode.value,
            "elapsed_ms": self.elapsed_ms,
            "challenge_detected": self.challenge_detected,
            "challenge_type": self.challenge_type,
        }
    
    @classmethod
    def success(
        cls,
        url: str,
        content: str,
        provider: str,
        *,
        status: int = 200,
        content_hash: str | None = None,
        cookies: list[Cookie] | None = None,
        screenshot_path: str | None = None,
        html_path: str | None = None,
        mode: BrowserMode = BrowserMode.HEADLESS,
        elapsed_ms: float = 0.0,
    ) -> "PageResult":
        """Create a successful result."""
        return cls(
            ok=True,
            url=url,
            status=status,
            content=content,
            content_hash=content_hash,
            cookies=cookies or [],
            screenshot_path=screenshot_path,
            html_path=html_path,
            provider=provider,
            mode=mode,
            elapsed_ms=elapsed_ms,
        )
    
    @classmethod
    def failure(
        cls,
        url: str,
        error: str,
        provider: str,
        *,
        status: int | None = None,
        mode: BrowserMode = BrowserMode.HEADLESS,
        challenge_detected: bool = False,
        challenge_type: str | None = None,
    ) -> "PageResult":
        """Create a failure result."""
        return cls(
            ok=False,
            url=url,
            status=status,
            error=error,
            provider=provider,
            mode=mode,
            challenge_detected=challenge_detected,
            challenge_type=challenge_type,
        )


@dataclass
class BrowserHealthStatus:
    """
    Health status of a browser provider.
    
    Attributes:
        state: Current health state.
        available: Whether the provider is available.
        success_rate: Recent success rate (0.0 to 1.0).
        latency_ms: Average latency in milliseconds.
        last_check: Last health check time.
        message: Optional status message.
        details: Additional health details.
    """
    state: BrowserHealthState
    available: bool = True
    success_rate: float = 1.0
    latency_ms: float = 0.0
    last_check: datetime | None = None
    message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def healthy(cls, latency_ms: float = 0.0) -> "BrowserHealthStatus":
        """Create a healthy status."""
        return cls(
            state=BrowserHealthState.HEALTHY,
            available=True,
            success_rate=1.0,
            latency_ms=latency_ms,
            last_check=datetime.now(timezone.utc),
        )
    
    @classmethod
    def degraded(
        cls,
        success_rate: float,
        message: str | None = None,
    ) -> "BrowserHealthStatus":
        """Create a degraded status."""
        return cls(
            state=BrowserHealthState.DEGRADED,
            available=True,
            success_rate=success_rate,
            message=message,
            last_check=datetime.now(timezone.utc),
        )
    
    @classmethod
    def unhealthy(cls, message: str | None = None) -> "BrowserHealthStatus":
        """Create an unhealthy status."""
        return cls(
            state=BrowserHealthState.UNHEALTHY,
            available=False,
            success_rate=0.0,
            message=message,
            last_check=datetime.now(timezone.utc),
        )
    
    @classmethod
    def unavailable(cls, message: str | None = None) -> "BrowserHealthStatus":
        """Create an unavailable status (dependency not installed)."""
        return cls(
            state=BrowserHealthState.UNHEALTHY,
            available=False,
            success_rate=0.0,
            message=message or "Provider not available",
            last_check=datetime.now(timezone.utc),
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "state": self.state.value,
            "available": self.available,
            "success_rate": self.success_rate,
            "latency_ms": self.latency_ms,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "message": self.message,
            "details": self.details,
        }


# ============================================================================
# Browser Provider Protocol
# ============================================================================


@runtime_checkable
class BrowserProvider(Protocol):
    """
    Protocol for browser automation providers.
    
    Defines the interface that all browser providers must implement.
    Uses Python's Protocol for structural subtyping.
    
    Example implementation:
        class MyProvider:
            @property
            def name(self) -> str:
                return "my_provider"
            
            async def navigate(self, url: str, options: BrowserOptions | None = None) -> PageResult:
                # Implementation
                ...
            
            async def get_health(self) -> BrowserHealthStatus:
                return BrowserHealthStatus.healthy()
            
            async def close(self) -> None:
                # Cleanup
                ...
    """
    
    @property
    def name(self) -> str:
        """Unique name of the provider."""
        ...
    
    async def navigate(
        self,
        url: str,
        options: BrowserOptions | None = None,
    ) -> PageResult:
        """
        Navigate to a URL and return the page content.
        
        Args:
            url: URL to navigate to.
            options: Navigation options.
            
        Returns:
            PageResult with page content or error.
        """
        ...
    
    async def execute_script(
        self,
        script: str,
        *args: Any,
    ) -> Any:
        """
        Execute JavaScript on the current page.
        
        Args:
            script: JavaScript code to execute.
            *args: Arguments to pass to the script.
            
        Returns:
            Result of script execution.
        """
        ...
    
    async def get_cookies(self, url: str | None = None) -> list[Cookie]:
        """
        Get cookies from the browser.
        
        Args:
            url: Filter cookies by URL (optional).
            
        Returns:
            List of cookies.
        """
        ...
    
    async def set_cookies(self, cookies: list[Cookie]) -> None:
        """
        Set cookies in the browser.
        
        Args:
            cookies: Cookies to set.
        """
        ...
    
    async def take_screenshot(
        self,
        path: str | None = None,
        full_page: bool = False,
    ) -> str | None:
        """
        Take a screenshot of the current page.
        
        Args:
            path: Path to save screenshot (auto-generated if None).
            full_page: Whether to capture full page or viewport only.
            
        Returns:
            Path to saved screenshot or None if failed.
        """
        ...
    
    async def get_health(self) -> BrowserHealthStatus:
        """
        Get current health status.
        
        Returns:
            BrowserHealthStatus indicating provider health.
        """
        ...
    
    async def close(self) -> None:
        """
        Close and cleanup provider resources.
        
        Should be called when the provider is no longer needed.
        """
        ...


class BaseBrowserProvider(ABC):
    """
    Abstract base class for browser providers.
    
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
        self._current_task_id: str | None = None
    
    @property
    def name(self) -> str:
        """Unique name of the provider."""
        return self._name
    
    @property
    def is_closed(self) -> bool:
        """Check if provider is closed."""
        return self._is_closed
    
    def set_task_id(self, task_id: str | None) -> None:
        """Set current task ID for lifecycle tracking."""
        self._current_task_id = task_id
    
    @abstractmethod
    async def navigate(
        self,
        url: str,
        options: BrowserOptions | None = None,
    ) -> PageResult:
        """Navigate to a URL and return the page content."""
        pass
    
    async def execute_script(
        self,
        script: str,
        *args: Any,
    ) -> Any:
        """Execute JavaScript (default: not supported)."""
        raise NotImplementedError(
            f"Provider '{self._name}' does not support script execution"
        )
    
    async def get_cookies(self, url: str | None = None) -> list[Cookie]:
        """Get cookies (default: empty list)."""
        return []
    
    async def set_cookies(self, cookies: list[Cookie]) -> None:
        """Set cookies (default: no-op)."""
        pass
    
    async def take_screenshot(
        self,
        path: str | None = None,
        full_page: bool = False,
    ) -> str | None:
        """Take screenshot (default: not supported)."""
        return None
    
    @abstractmethod
    async def get_health(self) -> BrowserHealthStatus:
        """Get current health status."""
        pass
    
    async def close(self) -> None:
        """Close and cleanup provider resources."""
        self._is_closed = True
        logger.debug("Browser provider closed", provider=self._name)
    
    def _check_closed(self) -> None:
        """Raise error if provider is closed."""
        if self._is_closed:
            raise RuntimeError(f"Provider '{self._name}' is closed")


# ============================================================================
# Provider Registry
# ============================================================================


class BrowserProviderRegistry:
    """
    Registry for browser providers.
    
    Manages registration, retrieval, and lifecycle of browser providers.
    Supports multiple providers with automatic fallback selection.
    
    Example usage:
        registry = BrowserProviderRegistry()
        registry.register(PlaywrightProvider())
        registry.register(UndetectedChromeProvider())
        
        # Get specific provider
        provider = registry.get("playwright")
        
        # Navigate with automatic fallback
        result = await registry.navigate_with_fallback(url)
    """
    
    def __init__(self):
        """Initialize empty registry."""
        self._providers: dict[str, BrowserProvider] = {}
        self._default_name: str | None = None
        self._fallback_order: list[str] = []
    
    def register(
        self,
        provider: BrowserProvider,
        set_default: bool = False,
    ) -> None:
        """
        Register a browser provider.
        
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
        self._fallback_order.append(name)
        
        if set_default or self._default_name is None:
            self._default_name = name
        
        logger.info(
            "Browser provider registered",
            provider=name,
            is_default=set_default or self._default_name == name,
        )
    
    def unregister(self, name: str) -> BrowserProvider | None:
        """
        Unregister a provider by name.
        
        Args:
            name: Provider name to unregister.
            
        Returns:
            The unregistered provider, or None if not found.
        """
        provider = self._providers.pop(name, None)
        
        if provider is not None:
            logger.info("Browser provider unregistered", provider=name)
            
            # Update fallback order
            if name in self._fallback_order:
                self._fallback_order.remove(name)
            
            # Update default if needed
            if self._default_name == name:
                self._default_name = next(iter(self._providers), None)
        
        return provider
    
    def get(self, name: str) -> BrowserProvider | None:
        """
        Get a provider by name.
        
        Args:
            name: Provider name.
            
        Returns:
            Provider instance or None if not found.
        """
        return self._providers.get(name)
    
    def get_default(self) -> BrowserProvider | None:
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
        logger.info("Default browser provider changed", provider=name)
    
    def set_fallback_order(self, order: list[str]) -> None:
        """
        Set the fallback order for providers.
        
        Args:
            order: List of provider names in fallback order.
            
        Raises:
            ValueError: If any provider name is not registered.
        """
        for name in order:
            if name not in self._providers:
                raise ValueError(f"Provider '{name}' not registered")
        
        self._fallback_order = order.copy()
        logger.info("Fallback order updated", order=self._fallback_order)
    
    def list_providers(self) -> list[str]:
        """
        List all registered provider names.
        
        Returns:
            List of provider names.
        """
        return list(self._providers.keys())
    
    async def get_all_health(self) -> dict[str, BrowserHealthStatus]:
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
                health[name] = BrowserHealthStatus.unhealthy(str(e))
        return health
    
    async def navigate_with_fallback(
        self,
        url: str,
        options: BrowserOptions | None = None,
        provider_order: list[str] | None = None,
    ) -> PageResult:
        """
        Navigate with automatic fallback to other providers on failure.
        
        Implements the fallback strategy per §4.3:
        - Try providers in order (default: playwright -> undetected)
        - On challenge detection, try next provider
        - On persistent failure, return error with details
        
        Args:
            url: URL to navigate to.
            options: Navigation options.
            provider_order: Order of providers to try.
            
        Returns:
            PageResult from first successful provider.
            
        Raises:
            RuntimeError: If no providers available.
        """
        if not self._providers:
            raise RuntimeError("No browser providers registered")
        
        # Determine provider order
        if provider_order is None:
            provider_order = self._fallback_order.copy()
            # Ensure default is first if not already in order
            if self._default_name and self._default_name not in provider_order:
                provider_order.insert(0, self._default_name)
        
        errors = []
        
        for name in provider_order:
            provider = self._providers.get(name)
            if provider is None:
                continue
            
            try:
                # Check health first
                health = await provider.get_health()
                if health.state == BrowserHealthState.UNHEALTHY:
                    logger.debug(
                        "Skipping unhealthy provider",
                        provider=name,
                        message=health.message,
                    )
                    errors.append(f"{name}: unhealthy ({health.message})")
                    continue
                
                # Execute navigation
                result = await provider.navigate(url, options)
                
                if result.ok:
                    return result
                
                # Navigation failed
                errors.append(f"{name}: {result.error}")
                
                # If challenge detected, try next provider with headful mode
                if result.challenge_detected and options:
                    logger.info(
                        "Challenge detected, trying next provider",
                        provider=name,
                        challenge_type=result.challenge_type,
                    )
                    options = BrowserOptions(
                        **{**options.to_dict(), "mode": BrowserMode.HEADFUL}
                    )
                    continue
                
                logger.warning(
                    "Browser provider navigation failed",
                    provider=name,
                    error=result.error,
                )
                
            except Exception as e:
                errors.append(f"{name}: {str(e)}")
                logger.error("Browser provider error", provider=name, error=str(e))
        
        # All providers failed
        error_msg = "; ".join(errors) if errors else "No providers available"
        return PageResult.failure(
            url=url,
            error=f"All providers failed: {error_msg}",
            provider="none",
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
        self._fallback_order.clear()
        logger.info("All browser providers closed")


# ============================================================================
# Global Registry
# ============================================================================

_registry: BrowserProviderRegistry | None = None


def get_browser_registry() -> BrowserProviderRegistry:
    """
    Get the global browser provider registry.
    
    Returns:
        The global BrowserProviderRegistry instance.
    """
    global _registry
    if _registry is None:
        _registry = BrowserProviderRegistry()
    return _registry


async def cleanup_browser_registry() -> None:
    """
    Cleanup the global registry.
    
    Closes all providers and resets the registry.
    """
    global _registry
    if _registry is not None:
        await _registry.close_all()
        _registry = None


def reset_browser_registry() -> None:
    """
    Reset the global registry without closing providers.
    
    For testing purposes only.
    """
    global _registry
    _registry = None

