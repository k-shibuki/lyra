"""
DNS Policy Management for Lancet.

Implements DNS policies per §4.3:
- Resolve DNS through Tor SOCKS proxy when using Tor route (socks5h://)
- Disable EDNS Client Subnet (ECS) to prevent location leakage
- Respect DNS cache TTL to reduce exposure from frequent re-resolution
- DNS leak detection metrics
- IPv6/IPv4 preference with Happy Eyeballs-style fallback

Key Design:
- When using Tor, DNS MUST be resolved through the Tor network (socks5h://)
  to prevent DNS leaks where the local resolver reveals the user's IP.
- For direct routes, use OS resolver with ECS disabled where possible.
- Cache DNS results respecting TTL to minimize exposure.
- IPv6-first with automatic fallback based on learned success rates.
"""

import asyncio
import socket
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import structlog

from src.utils.config import get_settings

if TYPE_CHECKING:
    from src.crawler.ipv6_manager import (
        AddressFamily,
        IPv6Address,
    )

logger = structlog.get_logger(__name__)


class DNSRoute(Enum):
    """DNS resolution route."""
    DIRECT = "direct"  # OS resolver
    TOR = "tor"  # Through Tor SOCKS proxy


class DNSLeakType(Enum):
    """Types of DNS leaks that can be detected."""
    NONE = "none"
    LOCAL_RESOLUTION_DURING_TOR = "local_resolution_during_tor"
    ECS_ENABLED = "ecs_enabled"


@dataclass
class DNSCacheEntry:
    """Cached DNS resolution result."""
    hostname: str
    addresses: list[str]  # IPv4 and/or IPv6 addresses
    resolved_at: float
    ttl: int  # TTL in seconds
    route: DNSRoute  # How it was resolved

    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        return time.time() > self.resolved_at + self.ttl


@dataclass
class DNSResolutionResult:
    """Result of DNS resolution."""
    hostname: str
    addresses: list[str]
    route: DNSRoute
    from_cache: bool
    resolution_time_ms: float
    leak_detected: DNSLeakType = DNSLeakType.NONE

    @property
    def success(self) -> bool:
        """Check if resolution was successful."""
        return len(self.addresses) > 0


@dataclass
class DNSMetrics:
    """Metrics for DNS operations."""
    total_resolutions: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    tor_resolutions: int = 0
    direct_resolutions: int = 0
    leaks_detected: int = 0
    resolution_errors: int = 0
    avg_resolution_time_ms: float = 0.0
    _resolution_times: list[float] = field(default_factory=list)

    def record_resolution(
        self,
        route: DNSRoute,
        from_cache: bool,
        time_ms: float,
        leak_detected: bool = False,
        error: bool = False,
    ) -> None:
        """Record a DNS resolution event."""
        self.total_resolutions += 1

        if from_cache:
            self.cache_hits += 1
        else:
            self.cache_misses += 1

        if route == DNSRoute.TOR:
            self.tor_resolutions += 1
        else:
            self.direct_resolutions += 1

        if leak_detected:
            self.leaks_detected += 1

        if error:
            self.resolution_errors += 1

        # Update average resolution time (keep last 100)
        self._resolution_times.append(time_ms)
        if len(self._resolution_times) > 100:
            self._resolution_times.pop(0)
        self.avg_resolution_time_ms = sum(self._resolution_times) / len(self._resolution_times)

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "total_resolutions": self.total_resolutions,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": self.cache_hits / max(1, self.total_resolutions),
            "tor_resolutions": self.tor_resolutions,
            "direct_resolutions": self.direct_resolutions,
            "leaks_detected": self.leaks_detected,
            "leak_rate": self.leaks_detected / max(1, self.total_resolutions),
            "resolution_errors": self.resolution_errors,
            "avg_resolution_time_ms": self.avg_resolution_time_ms,
        }


class DNSPolicyManager:
    """Manages DNS resolution policies per §4.3.

    Key responsibilities:
    - Select appropriate DNS route (direct vs Tor)
    - Generate correct SOCKS proxy URL (socks5:// vs socks5h://)
    - Cache DNS results respecting TTL
    - Detect potential DNS leaks
    """

    def __init__(self):
        self._settings = get_settings()
        self._cache: dict[str, DNSCacheEntry] = {}
        self._cache_lock = asyncio.Lock()
        self._metrics = DNSMetrics()

    @property
    def metrics(self) -> DNSMetrics:
        """Get DNS metrics."""
        return self._metrics

    def get_socks_proxy_url(
        self,
        use_tor: bool,
        resolve_dns_through_proxy: bool | None = None,
    ) -> str | None:
        """Get the appropriate SOCKS proxy URL.

        This is the critical method for preventing DNS leaks.

        When using Tor:
        - socks5h:// = DNS resolved through proxy (SAFE, no DNS leak)
        - socks5:// = DNS resolved locally (UNSAFE, DNS leak!)

        Args:
            use_tor: Whether to use Tor proxy.
            resolve_dns_through_proxy: Override DNS resolution setting.
                If None, uses config setting.

        Returns:
            Proxy URL or None if not using proxy.
        """
        if not use_tor or not self._settings.tor.enabled:
            return None

        tor_settings = self._settings.tor
        dns_settings = tor_settings.dns

        # Determine if DNS should be resolved through proxy
        resolve_through = resolve_dns_through_proxy
        if resolve_through is None:
            resolve_through = dns_settings.resolve_through_tor

        # Choose protocol based on DNS resolution preference
        # socks5h = DNS resolution through SOCKS (h = hostname)
        # socks5 = local DNS resolution (potential leak!)
        protocol = "socks5h" if resolve_through else "socks5"

        proxy_url = f"{protocol}://{tor_settings.socks_host}:{tor_settings.socks_port}"

        logger.debug(
            "Generated SOCKS proxy URL",
            protocol=protocol,
            resolve_dns_through_proxy=resolve_through,
            proxy_url=proxy_url,
        )

        return proxy_url

    def get_proxy_dict(
        self,
        use_tor: bool,
        resolve_dns_through_proxy: bool | None = None,
    ) -> dict[str, str] | None:
        """Get proxy dictionary for requests/curl_cffi.

        Args:
            use_tor: Whether to use Tor proxy.
            resolve_dns_through_proxy: Override DNS resolution setting.

        Returns:
            Proxy dictionary or None.
        """
        proxy_url = self.get_socks_proxy_url(use_tor, resolve_dns_through_proxy)
        if proxy_url is None:
            return None

        return {"http": proxy_url, "https": proxy_url}

    async def resolve_hostname(
        self,
        hostname: str,
        route: DNSRoute,
        use_cache: bool = True,
    ) -> DNSResolutionResult:
        """Resolve hostname with caching and leak detection.

        Note: When route is TOR, actual DNS resolution should be done
        by the SOCKS proxy (socks5h://). This method is primarily for
        caching and metrics purposes with direct routes.

        Args:
            hostname: Hostname to resolve.
            route: DNS resolution route.
            use_cache: Whether to use cache.

        Returns:
            Resolution result.
        """
        start_time = time.time()
        dns_settings = self._settings.tor.dns

        # Check cache first
        async with self._cache_lock:
            cache_key = f"{hostname}:{route.value}"
            if use_cache and cache_key in self._cache:
                entry = self._cache[cache_key]
                if not entry.is_expired():
                    resolution_time_ms = (time.time() - start_time) * 1000
                    self._metrics.record_resolution(
                        route=route,
                        from_cache=True,
                        time_ms=resolution_time_ms,
                    )
                    return DNSResolutionResult(
                        hostname=hostname,
                        addresses=entry.addresses,
                        route=route,
                        from_cache=True,
                        resolution_time_ms=resolution_time_ms,
                    )

        # Resolve hostname
        addresses: list[str] = []
        leak_detected = DNSLeakType.NONE
        error = False

        try:
            if route == DNSRoute.TOR:
                # For Tor route, we shouldn't resolve locally at all!
                # This is just for validation - actual resolution happens via socks5h://
                logger.warning(
                    "Local DNS resolution attempted for Tor route - potential leak!",
                    hostname=hostname,
                )
                leak_detected = DNSLeakType.LOCAL_RESOLUTION_DURING_TOR
                self._metrics.record_resolution(
                    route=route,
                    from_cache=False,
                    time_ms=0,
                    leak_detected=True,
                )
                # Don't actually resolve - return empty to signal proxy should resolve
                return DNSResolutionResult(
                    hostname=hostname,
                    addresses=[],
                    route=route,
                    from_cache=False,
                    resolution_time_ms=0,
                    leak_detected=leak_detected,
                )
            else:
                # Direct route - resolve using OS resolver
                # Note: getaddrinfo is blocking, run in executor
                loop = asyncio.get_running_loop()
                addr_info = await loop.run_in_executor(
                    None,
                    lambda: socket.getaddrinfo(
                        hostname,
                        None,
                        socket.AF_UNSPEC,  # Both IPv4 and IPv6
                        socket.SOCK_STREAM,
                    ),
                )

                # Extract unique addresses
                seen = set()
                for info in addr_info:
                    addr = info[4][0]
                    if addr not in seen:
                        addresses.append(addr)
                        seen.add(addr)

        except socket.gaierror as e:
            logger.debug("DNS resolution failed", hostname=hostname, error=str(e))
            error = True
        except Exception as e:
            logger.warning("Unexpected DNS error", hostname=hostname, error=str(e))
            error = True

        resolution_time_ms = (time.time() - start_time) * 1000

        # Cache the result if successful
        if addresses and dns_settings.respect_cache_ttl:
            # Use a reasonable default TTL (we can't get actual TTL from getaddrinfo)
            # In a full implementation, we'd use dnspython to get TTL
            default_ttl = 300  # 5 minutes
            ttl = max(dns_settings.min_cache_ttl, min(default_ttl, dns_settings.max_cache_ttl))

            async with self._cache_lock:
                self._cache[cache_key] = DNSCacheEntry(
                    hostname=hostname,
                    addresses=addresses,
                    resolved_at=time.time(),
                    ttl=ttl,
                    route=route,
                )

        # Record metrics
        self._metrics.record_resolution(
            route=route,
            from_cache=False,
            time_ms=resolution_time_ms,
            leak_detected=leak_detected != DNSLeakType.NONE,
            error=error,
        )

        return DNSResolutionResult(
            hostname=hostname,
            addresses=addresses,
            route=route,
            from_cache=False,
            resolution_time_ms=resolution_time_ms,
            leak_detected=leak_detected,
        )

    def extract_hostname(self, url: str) -> str:
        """Extract hostname from URL.

        Args:
            url: URL to parse.

        Returns:
            Hostname.
        """
        parsed = urlparse(url)
        return parsed.hostname or ""

    def should_use_tor_dns(self, use_tor: bool) -> bool:
        """Check if DNS should be resolved through Tor.

        Args:
            use_tor: Whether Tor is being used for the request.

        Returns:
            True if DNS should go through Tor.
        """
        if not use_tor:
            return False

        dns_settings = self._settings.tor.dns
        return dns_settings.resolve_through_tor

    async def clear_cache(self) -> int:
        """Clear DNS cache.

        Returns:
            Number of entries cleared.
        """
        async with self._cache_lock:
            count = len(self._cache)
            self._cache.clear()
            return count

    async def prune_expired_cache(self) -> int:
        """Remove expired cache entries.

        Returns:
            Number of entries pruned.
        """
        async with self._cache_lock:
            time.time()
            expired_keys = [
                key for key, entry in self._cache.items()
                if entry.is_expired()
            ]
            for key in expired_keys:
                del self._cache[key]
            return len(expired_keys)

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Cache statistics dictionary.
        """
        total_entries = len(self._cache)
        expired_entries = sum(1 for e in self._cache.values() if e.is_expired())
        active_entries = total_entries - expired_entries

        return {
            "total_entries": total_entries,
            "active_entries": active_entries,
            "expired_entries": expired_entries,
        }

    def detect_dns_leak(
        self,
        url: str,
        use_tor: bool,
        local_resolution_attempted: bool,
    ) -> DNSLeakType:
        """Detect potential DNS leak.

        Args:
            url: URL being accessed.
            use_tor: Whether Tor is being used.
            local_resolution_attempted: Whether local DNS was attempted.

        Returns:
            Type of DNS leak detected, if any.
        """
        if not self._settings.tor.dns.leak_detection_enabled:
            return DNSLeakType.NONE

        # If using Tor but local DNS was attempted, that's a leak
        if use_tor and local_resolution_attempted:
            hostname = self.extract_hostname(url)
            logger.warning(
                "DNS leak detected: local resolution during Tor route",
                hostname=hostname,
                url=url,
            )
            return DNSLeakType.LOCAL_RESOLUTION_DURING_TOR

        return DNSLeakType.NONE

    # =========================================================================
    # IPv6 Integration (§4.3)
    # =========================================================================

    async def resolve_with_ipv6_preference(
        self,
        hostname: str,
        domain: str | None = None,
    ) -> list["IPv6Address"]:
        """Resolve hostname with IPv6 preference.

        Integrates with IPv6ConnectionManager for Happy Eyeballs-style
        address resolution with learned preferences.

        Args:
            hostname: Hostname to resolve.
            domain: Domain for per-domain preference lookup.

        Returns:
            List of addresses sorted by preference.
        """
        from src.crawler.ipv6_manager import get_ipv6_manager

        manager = get_ipv6_manager()
        return await manager.get_preferred_addresses(hostname, domain)

    def get_preferred_address_family(
        self,
        domain: str | None = None,
    ) -> "AddressFamily":
        """Get preferred address family for a domain.

        Args:
            domain: Domain to check (optional).

        Returns:
            Preferred address family.
        """
        from src.crawler.ipv6_manager import (
            AddressFamily,
            IPv6Preference,
            get_ipv6_manager,
        )

        manager = get_ipv6_manager()

        if not manager.is_ipv6_enabled():
            return AddressFamily.IPV4

        # Get global preference from settings
        ipv6_settings = manager._get_ipv6_settings()
        preference_str = ipv6_settings.get("preference", "ipv6_first")

        try:
            global_preference = IPv6Preference(preference_str)
        except ValueError:
            global_preference = IPv6Preference.IPV6_FIRST

        # Without domain info, use global preference
        if not domain:
            if global_preference == IPv6Preference.IPV4_FIRST:
                return AddressFamily.IPV4
            return AddressFamily.IPV6

        # With domain, use manager's logic (will be async in actual usage)
        # This is a synchronous approximation for simple cases
        if global_preference == IPv6Preference.IPV4_FIRST:
            return AddressFamily.IPV4
        return AddressFamily.IPV6

    async def get_preferred_address_family_async(
        self,
        domain: str,
    ) -> "AddressFamily":
        """Get preferred address family for a domain (async version).

        Args:
            domain: Domain to check.

        Returns:
            Preferred address family based on learned stats.
        """
        from src.crawler.ipv6_manager import (
            AddressFamily,
            IPv6Preference,
            get_ipv6_manager,
        )

        manager = get_ipv6_manager()

        if not manager.is_ipv6_enabled():
            return AddressFamily.IPV4

        if not await manager.is_ipv6_enabled_for_domain(domain):
            return AddressFamily.IPV4

        # Get global preference
        ipv6_settings = manager._get_ipv6_settings()
        preference_str = ipv6_settings.get("preference", "ipv6_first")

        try:
            global_preference = IPv6Preference(preference_str)
        except ValueError:
            global_preference = IPv6Preference.IPV6_FIRST

        # Get domain stats and determine preference
        stats = await manager.get_domain_stats(domain)
        return stats.get_preferred_family(global_preference)


# Global DNS policy manager instance
_dns_policy_manager: DNSPolicyManager | None = None


def get_dns_policy_manager() -> DNSPolicyManager:
    """Get the global DNS policy manager instance.

    Returns:
        DNSPolicyManager instance.
    """
    global _dns_policy_manager
    if _dns_policy_manager is None:
        _dns_policy_manager = DNSPolicyManager()
    return _dns_policy_manager


async def get_socks_proxy_for_request(use_tor: bool) -> dict[str, str] | None:
    """Convenience function to get proxy dict for a request.

    Uses the global DNS policy manager to ensure DNS is resolved
    through Tor when using Tor route (socks5h://).

    Args:
        use_tor: Whether to use Tor.

    Returns:
        Proxy dictionary or None.
    """
    manager = get_dns_policy_manager()
    return manager.get_proxy_dict(use_tor)





