"""
IPv6 Connection Management for Lancet.

Implements IPv6 connection policies per §4.3:
- IPv6-first with IPv4 fallback (Happy Eyeballs-style)
- Per-domain success rate learning
- Automatic preference switching based on learned performance
- Metrics tracking for acceptance criteria

Key Design:
- Default to IPv6 when available, fallback to IPv4 on failure
- Learn per-domain success rates and adjust preferences
- Track metrics for acceptance criteria (IPv6 success rate ≥80%, switch success ≥80%)
"""

import asyncio
import socket
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

from src.utils.config import get_settings

logger = structlog.get_logger(__name__)


class AddressFamily(Enum):
    """IP address family."""
    IPV4 = "ipv4"
    IPV6 = "ipv6"
    ANY = "any"


class IPv6Preference(Enum):
    """IPv6/IPv4 preference strategy."""
    IPV6_FIRST = "ipv6_first"  # Try IPv6 first, fallback to IPv4
    IPV4_FIRST = "ipv4_first"  # Try IPv4 first, fallback to IPv6
    AUTO = "auto"  # Automatically select based on learned success rates


@dataclass
class IPv6Address:
    """Resolved IP address with family information."""
    address: str
    family: AddressFamily
    
    @property
    def is_ipv6(self) -> bool:
        """Check if this is an IPv6 address."""
        return self.family == AddressFamily.IPV6
    
    @property
    def is_ipv4(self) -> bool:
        """Check if this is an IPv4 address."""
        return self.family == AddressFamily.IPV4


@dataclass
class IPv6ConnectionResult:
    """Result of an IPv6/IPv4 connection attempt."""
    hostname: str
    success: bool
    family_used: AddressFamily
    family_attempted: AddressFamily
    switched: bool  # True if we switched from primary to fallback
    switch_success: bool  # True if switch resulted in success
    latency_ms: float
    error: str | None = None
    addresses_resolved: list[IPv6Address] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "hostname": self.hostname,
            "success": self.success,
            "family_used": self.family_used.value,
            "family_attempted": self.family_attempted.value,
            "switched": self.switched,
            "switch_success": self.switch_success,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "addresses_resolved": [
                {"address": a.address, "family": a.family.value}
                for a in self.addresses_resolved
            ],
        }


@dataclass
class DomainIPv6Stats:
    """Per-domain IPv6 statistics."""
    domain: str
    ipv6_enabled: bool = True
    ipv6_success_rate: float = 0.5  # EMA of IPv6 success rate
    ipv4_success_rate: float = 0.5  # EMA of IPv4 success rate
    ipv6_preference: IPv6Preference = IPv6Preference.AUTO
    ipv6_attempts: int = 0
    ipv6_successes: int = 0
    ipv4_attempts: int = 0
    ipv4_successes: int = 0
    switch_count: int = 0  # Number of times we switched family
    switch_success_count: int = 0  # Number of successful switches
    last_ipv6_success_at: float | None = None
    last_ipv6_failure_at: float | None = None
    last_ipv4_success_at: float | None = None
    last_ipv4_failure_at: float | None = None
    
    def get_preferred_family(self, global_preference: IPv6Preference) -> AddressFamily:
        """Determine preferred address family based on stats and settings.
        
        Args:
            global_preference: Global preference setting.
            
        Returns:
            Preferred address family.
        """
        # If IPv6 is disabled for this domain, always use IPv4
        if not self.ipv6_enabled:
            return AddressFamily.IPV4
        
        # Use explicit preference if set
        preference = self.ipv6_preference
        if preference == IPv6Preference.IPV6_FIRST:
            return AddressFamily.IPV6
        elif preference == IPv6Preference.IPV4_FIRST:
            return AddressFamily.IPV4
        
        # Auto mode - use learned success rates
        if preference == IPv6Preference.AUTO or global_preference == IPv6Preference.AUTO:
            # Need minimum samples for reliable comparison
            min_samples = 5
            if self.ipv6_attempts < min_samples and self.ipv4_attempts < min_samples:
                # Not enough data - use global preference
                if global_preference == IPv6Preference.IPV4_FIRST:
                    return AddressFamily.IPV4
                return AddressFamily.IPV6  # Default to IPv6
            
            # Compare success rates with some margin
            if self.ipv6_success_rate > self.ipv4_success_rate + 0.1:
                return AddressFamily.IPV6
            elif self.ipv4_success_rate > self.ipv6_success_rate + 0.1:
                return AddressFamily.IPV4
            else:
                # Similar rates - prefer IPv6
                return AddressFamily.IPV6
        
        # Default based on global preference
        if global_preference == IPv6Preference.IPV4_FIRST:
            return AddressFamily.IPV4
        return AddressFamily.IPV6
    
    def update_success_rate(
        self,
        family: AddressFamily,
        success: bool,
        ema_alpha: float = 0.1,
    ) -> None:
        """Update success rate with EMA.
        
        Args:
            family: Address family used.
            success: Whether connection succeeded.
            ema_alpha: EMA smoothing factor.
        """
        now = time.time()
        value = 1.0 if success else 0.0
        
        if family == AddressFamily.IPV6:
            self.ipv6_attempts += 1
            if success:
                self.ipv6_successes += 1
                self.last_ipv6_success_at = now
            else:
                self.last_ipv6_failure_at = now
            
            # Update EMA
            self.ipv6_success_rate = (
                ema_alpha * value + (1 - ema_alpha) * self.ipv6_success_rate
            )
        else:
            self.ipv4_attempts += 1
            if success:
                self.ipv4_successes += 1
                self.last_ipv4_success_at = now
            else:
                self.last_ipv4_failure_at = now
            
            # Update EMA
            self.ipv4_success_rate = (
                ema_alpha * value + (1 - ema_alpha) * self.ipv4_success_rate
            )
    
    def record_switch(self, success: bool) -> None:
        """Record a family switch event.
        
        Args:
            success: Whether the switch resulted in success.
        """
        self.switch_count += 1
        if success:
            self.switch_success_count += 1
    
    @property
    def switch_success_rate(self) -> float:
        """Calculate switch success rate."""
        if self.switch_count == 0:
            return 0.0
        return self.switch_success_count / self.switch_count
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            "domain": self.domain,
            "ipv6_enabled": self.ipv6_enabled,
            "ipv6_success_rate": self.ipv6_success_rate,
            "ipv4_success_rate": self.ipv4_success_rate,
            "ipv6_preference": self.ipv6_preference.value,
            "ipv6_attempts": self.ipv6_attempts,
            "ipv6_successes": self.ipv6_successes,
            "ipv4_attempts": self.ipv4_attempts,
            "ipv4_successes": self.ipv4_successes,
            "switch_count": self.switch_count,
            "switch_success_count": self.switch_success_count,
            "last_ipv6_success_at": self.last_ipv6_success_at,
            "last_ipv6_failure_at": self.last_ipv6_failure_at,
            "last_ipv4_success_at": self.last_ipv4_success_at,
            "last_ipv4_failure_at": self.last_ipv4_failure_at,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DomainIPv6Stats":
        """Create from dictionary."""
        preference = data.get("ipv6_preference", "auto")
        if isinstance(preference, str):
            preference = IPv6Preference(preference)
        
        return cls(
            domain=data["domain"],
            ipv6_enabled=data.get("ipv6_enabled", True),
            ipv6_success_rate=data.get("ipv6_success_rate", 0.5),
            ipv4_success_rate=data.get("ipv4_success_rate", 0.5),
            ipv6_preference=preference,
            ipv6_attempts=data.get("ipv6_attempts", 0),
            ipv6_successes=data.get("ipv6_successes", 0),
            ipv4_attempts=data.get("ipv4_attempts", 0),
            ipv4_successes=data.get("ipv4_successes", 0),
            switch_count=data.get("switch_count", 0),
            switch_success_count=data.get("switch_success_count", 0),
            last_ipv6_success_at=data.get("last_ipv6_success_at"),
            last_ipv6_failure_at=data.get("last_ipv6_failure_at"),
            last_ipv4_success_at=data.get("last_ipv4_success_at"),
            last_ipv4_failure_at=data.get("last_ipv4_failure_at"),
        )


@dataclass
class IPv6Metrics:
    """Global IPv6 metrics for monitoring."""
    total_ipv6_attempts: int = 0
    total_ipv6_successes: int = 0
    total_ipv4_attempts: int = 0
    total_ipv4_successes: int = 0
    total_switches: int = 0
    total_switch_successes: int = 0
    _latencies: list[float] = field(default_factory=list)
    
    def record_attempt(
        self,
        family: AddressFamily,
        success: bool,
        switched: bool = False,
        switch_success: bool = False,
        latency_ms: float = 0.0,
    ) -> None:
        """Record a connection attempt.
        
        Args:
            family: Address family used.
            success: Whether connection succeeded.
            switched: Whether we switched family.
            switch_success: Whether switch resulted in success.
            latency_ms: Connection latency.
        """
        if family == AddressFamily.IPV6:
            self.total_ipv6_attempts += 1
            if success:
                self.total_ipv6_successes += 1
        else:
            self.total_ipv4_attempts += 1
            if success:
                self.total_ipv4_successes += 1
        
        if switched:
            self.total_switches += 1
            if switch_success:
                self.total_switch_successes += 1
        
        # Track latencies (keep last 100)
        self._latencies.append(latency_ms)
        if len(self._latencies) > 100:
            self._latencies.pop(0)
    
    @property
    def ipv6_success_rate(self) -> float:
        """Global IPv6 success rate."""
        if self.total_ipv6_attempts == 0:
            return 0.0
        return self.total_ipv6_successes / self.total_ipv6_attempts
    
    @property
    def ipv4_success_rate(self) -> float:
        """Global IPv4 success rate."""
        if self.total_ipv4_attempts == 0:
            return 0.0
        return self.total_ipv4_successes / self.total_ipv4_attempts
    
    @property
    def switch_success_rate(self) -> float:
        """Global switch success rate (acceptance criteria: ≥80%)."""
        if self.total_switches == 0:
            return 0.0
        return self.total_switch_successes / self.total_switches
    
    @property
    def avg_latency_ms(self) -> float:
        """Average connection latency."""
        if not self._latencies:
            return 0.0
        return sum(self._latencies) / len(self._latencies)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_ipv6_attempts": self.total_ipv6_attempts,
            "total_ipv6_successes": self.total_ipv6_successes,
            "total_ipv4_attempts": self.total_ipv4_attempts,
            "total_ipv4_successes": self.total_ipv4_successes,
            "total_switches": self.total_switches,
            "total_switch_successes": self.total_switch_successes,
            "ipv6_success_rate": self.ipv6_success_rate,
            "ipv4_success_rate": self.ipv4_success_rate,
            "switch_success_rate": self.switch_success_rate,
            "avg_latency_ms": self.avg_latency_ms,
        }


class IPv6ConnectionManager:
    """Manages IPv6/IPv4 connection preferences per domain.
    
    Implements Happy Eyeballs-style connection logic:
    1. Resolve both IPv6 and IPv4 addresses
    2. Try preferred family first
    3. Fall back to alternative family on failure
    4. Learn success rates per domain and adjust preferences
    """
    
    def __init__(self):
        self._settings = get_settings()
        self._domain_stats: dict[str, DomainIPv6Stats] = {}
        self._metrics = IPv6Metrics()
        self._lock = asyncio.Lock()
    
    @property
    def metrics(self) -> IPv6Metrics:
        """Get global IPv6 metrics."""
        return self._metrics
    
    def _get_ipv6_settings(self) -> dict[str, Any]:
        """Get IPv6 settings with defaults."""
        # Handle case where ipv6 settings might not exist
        if hasattr(self._settings, 'ipv6'):
            return {
                "enabled": getattr(self._settings.ipv6, 'enabled', True),
                "preference": getattr(self._settings.ipv6, 'preference', 'ipv6_first'),
                "fallback_timeout": getattr(self._settings.ipv6, 'fallback_timeout', 5.0),
                "learning_threshold": getattr(self._settings.ipv6, 'learning_threshold', 0.3),
                "min_samples": getattr(self._settings.ipv6, 'min_samples', 5),
            }
        # Default settings if ipv6 section doesn't exist
        return {
            "enabled": True,
            "preference": "ipv6_first",
            "fallback_timeout": 5.0,
            "learning_threshold": 0.3,
            "min_samples": 5,
        }
    
    def _get_global_preference(self) -> IPv6Preference:
        """Get global IPv6 preference from settings."""
        settings = self._get_ipv6_settings()
        preference_str = settings.get("preference", "ipv6_first")
        try:
            return IPv6Preference(preference_str)
        except ValueError:
            return IPv6Preference.IPV6_FIRST
    
    async def get_domain_stats(self, domain: str) -> DomainIPv6Stats:
        """Get or create domain stats.
        
        Args:
            domain: Domain name.
            
        Returns:
            Domain IPv6 statistics.
        """
        async with self._lock:
            if domain not in self._domain_stats:
                self._domain_stats[domain] = DomainIPv6Stats(domain=domain)
            return self._domain_stats[domain]
    
    async def update_domain_stats(
        self,
        domain: str,
        stats: DomainIPv6Stats,
    ) -> None:
        """Update domain stats.
        
        Args:
            domain: Domain name.
            stats: Updated statistics.
        """
        async with self._lock:
            self._domain_stats[domain] = stats
    
    async def resolve_addresses(
        self,
        hostname: str,
    ) -> tuple[list[IPv6Address], list[IPv6Address]]:
        """Resolve hostname to IPv6 and IPv4 addresses.
        
        Args:
            hostname: Hostname to resolve.
            
        Returns:
            Tuple of (ipv6_addresses, ipv4_addresses).
        """
        ipv6_addresses: list[IPv6Address] = []
        ipv4_addresses: list[IPv6Address] = []
        
        loop = asyncio.get_event_loop()
        
        try:
            # Try to resolve both IPv6 and IPv4
            # Use AF_UNSPEC to get both
            addr_info = await loop.run_in_executor(
                None,
                lambda: socket.getaddrinfo(
                    hostname,
                    None,
                    socket.AF_UNSPEC,
                    socket.SOCK_STREAM,
                ),
            )
            
            seen = set()
            for info in addr_info:
                family = info[0]
                addr = info[4][0]
                
                if addr in seen:
                    continue
                seen.add(addr)
                
                if family == socket.AF_INET6:
                    ipv6_addresses.append(IPv6Address(
                        address=addr,
                        family=AddressFamily.IPV6,
                    ))
                elif family == socket.AF_INET:
                    ipv4_addresses.append(IPv6Address(
                        address=addr,
                        family=AddressFamily.IPV4,
                    ))
                    
        except socket.gaierror as e:
            logger.debug("DNS resolution failed", hostname=hostname, error=str(e))
        except Exception as e:
            logger.warning("Unexpected DNS error", hostname=hostname, error=str(e))
        
        return ipv6_addresses, ipv4_addresses
    
    async def get_preferred_addresses(
        self,
        hostname: str,
        domain: str | None = None,
    ) -> list[IPv6Address]:
        """Get addresses ordered by preference for a hostname.
        
        Implements Happy Eyeballs-style ordering:
        - Returns addresses sorted by preference (primary family first)
        - Interleaves IPv6 and IPv4 for parallel connection attempts
        
        Args:
            hostname: Hostname to resolve.
            domain: Domain for per-domain preference lookup.
            
        Returns:
            List of addresses sorted by preference.
        """
        ipv6_addrs, ipv4_addrs = await self.resolve_addresses(hostname)
        
        if not ipv6_addrs and not ipv4_addrs:
            return []
        
        # Get domain stats if available
        if domain:
            stats = await self.get_domain_stats(domain)
            preferred = stats.get_preferred_family(self._get_global_preference())
        else:
            global_pref = self._get_global_preference()
            if global_pref == IPv6Preference.IPV4_FIRST:
                preferred = AddressFamily.IPV4
            else:
                preferred = AddressFamily.IPV6
        
        # Sort addresses by preference
        # Interleave for Happy Eyeballs-style parallel attempts
        result: list[IPv6Address] = []
        
        if preferred == AddressFamily.IPV6:
            primary, secondary = ipv6_addrs, ipv4_addrs
        else:
            primary, secondary = ipv4_addrs, ipv6_addrs
        
        # Interleave: primary[0], secondary[0], primary[1], secondary[1], ...
        max_len = max(len(primary), len(secondary))
        for i in range(max_len):
            if i < len(primary):
                result.append(primary[i])
            if i < len(secondary):
                result.append(secondary[i])
        
        return result
    
    async def record_connection_result(
        self,
        domain: str,
        result: IPv6ConnectionResult,
    ) -> None:
        """Record connection result and update stats.
        
        Args:
            domain: Domain name.
            result: Connection result.
        """
        stats = await self.get_domain_stats(domain)
        
        # Update success rate for the family used
        stats.update_success_rate(result.family_used, result.success)
        
        # Record switch if applicable
        if result.switched:
            stats.record_switch(result.switch_success)
        
        # Update global metrics
        self._metrics.record_attempt(
            family=result.family_used,
            success=result.success,
            switched=result.switched,
            switch_success=result.switch_success,
            latency_ms=result.latency_ms,
        )
        
        # Check if we should disable IPv6 for this domain
        settings = self._get_ipv6_settings()
        threshold = settings.get("learning_threshold", 0.3)
        min_samples = settings.get("min_samples", 5)
        
        if stats.ipv6_attempts >= min_samples:
            if stats.ipv6_success_rate < threshold:
                # Disable IPv6 for this domain due to poor performance
                stats.ipv6_enabled = False
                logger.info(
                    "Disabling IPv6 for domain due to low success rate",
                    domain=domain,
                    ipv6_success_rate=stats.ipv6_success_rate,
                    threshold=threshold,
                )
        
        await self.update_domain_stats(domain, stats)
        
        logger.debug(
            "Recorded IPv6 connection result",
            domain=domain,
            family_used=result.family_used.value,
            success=result.success,
            switched=result.switched,
            ipv6_success_rate=stats.ipv6_success_rate,
            ipv4_success_rate=stats.ipv4_success_rate,
        )
    
    async def try_connect_with_fallback(
        self,
        hostname: str,
        domain: str,
        connect_func,
        timeout: float | None = None,
    ) -> IPv6ConnectionResult:
        """Try to connect with automatic IPv6/IPv4 fallback.
        
        Implements Happy Eyeballs-style connection:
        1. Get preferred addresses
        2. Try primary family first
        3. Fall back to alternative on failure
        
        Args:
            hostname: Hostname to connect to.
            domain: Domain for preference lookup.
            connect_func: Async function that takes (address, family) and returns (success, error).
            timeout: Connection timeout per attempt.
            
        Returns:
            Connection result.
        """
        settings = self._get_ipv6_settings()
        if timeout is None:
            timeout = settings.get("fallback_timeout", 5.0)
        
        # Get addresses sorted by preference
        addresses = await self.get_preferred_addresses(hostname, domain)
        
        if not addresses:
            return IPv6ConnectionResult(
                hostname=hostname,
                success=False,
                family_used=AddressFamily.ANY,
                family_attempted=AddressFamily.ANY,
                switched=False,
                switch_success=False,
                latency_ms=0,
                error="No addresses resolved",
                addresses_resolved=[],
            )
        
        # Determine primary family
        stats = await self.get_domain_stats(domain)
        primary_family = stats.get_preferred_family(self._get_global_preference())
        
        start_time = time.time()
        last_error: str | None = None
        switched = False
        
        for i, addr in enumerate(addresses):
            try:
                # Check if we're switching family
                if i > 0 and addr.family != addresses[0].family:
                    switched = True
                
                # Try connection with timeout
                success, error = await asyncio.wait_for(
                    connect_func(addr.address, addr.family),
                    timeout=timeout,
                )
                
                latency_ms = (time.time() - start_time) * 1000
                
                if success:
                    result = IPv6ConnectionResult(
                        hostname=hostname,
                        success=True,
                        family_used=addr.family,
                        family_attempted=primary_family,
                        switched=switched,
                        switch_success=switched,  # Switched and succeeded
                        latency_ms=latency_ms,
                        addresses_resolved=addresses,
                    )
                    await self.record_connection_result(domain, result)
                    return result
                
                last_error = error
                
            except asyncio.TimeoutError:
                last_error = f"Timeout ({timeout}s)"
                logger.debug(
                    "Connection timeout",
                    hostname=hostname,
                    address=addr.address,
                    family=addr.family.value,
                )
            except Exception as e:
                last_error = str(e)
                logger.debug(
                    "Connection error",
                    hostname=hostname,
                    address=addr.address,
                    family=addr.family.value,
                    error=str(e),
                )
        
        # All attempts failed
        latency_ms = (time.time() - start_time) * 1000
        
        # Record failure for primary family
        result = IPv6ConnectionResult(
            hostname=hostname,
            success=False,
            family_used=addresses[0].family if addresses else AddressFamily.ANY,
            family_attempted=primary_family,
            switched=switched,
            switch_success=False,  # Switched but still failed
            latency_ms=latency_ms,
            error=last_error,
            addresses_resolved=addresses,
        )
        await self.record_connection_result(domain, result)
        return result
    
    def is_ipv6_enabled(self) -> bool:
        """Check if IPv6 is globally enabled.
        
        Returns:
            True if IPv6 is enabled.
        """
        settings = self._get_ipv6_settings()
        return settings.get("enabled", True)
    
    async def is_ipv6_enabled_for_domain(self, domain: str) -> bool:
        """Check if IPv6 is enabled for a specific domain.
        
        Args:
            domain: Domain name.
            
        Returns:
            True if IPv6 is enabled for this domain.
        """
        if not self.is_ipv6_enabled():
            return False
        
        stats = await self.get_domain_stats(domain)
        return stats.ipv6_enabled
    
    async def set_domain_preference(
        self,
        domain: str,
        preference: IPv6Preference,
    ) -> None:
        """Set IPv6 preference for a domain.
        
        Args:
            domain: Domain name.
            preference: Preference to set.
        """
        stats = await self.get_domain_stats(domain)
        stats.ipv6_preference = preference
        await self.update_domain_stats(domain, stats)
        
        logger.info(
            "Set domain IPv6 preference",
            domain=domain,
            preference=preference.value,
        )
    
    async def enable_ipv6_for_domain(self, domain: str, enabled: bool = True) -> None:
        """Enable or disable IPv6 for a domain.
        
        Args:
            domain: Domain name.
            enabled: Whether to enable IPv6.
        """
        stats = await self.get_domain_stats(domain)
        stats.ipv6_enabled = enabled
        await self.update_domain_stats(domain, stats)
        
        logger.info(
            "Set domain IPv6 enabled",
            domain=domain,
            enabled=enabled,
        )
    
    def get_all_domain_stats(self) -> dict[str, DomainIPv6Stats]:
        """Get all domain statistics.
        
        Returns:
            Dictionary of domain -> stats.
        """
        return self._domain_stats.copy()
    
    async def load_domain_stats_from_db(self, db) -> int:
        """Load domain stats from database.
        
        Args:
            db: Database instance.
            
        Returns:
            Number of domains loaded.
        """
        try:
            rows = await db.fetch_all(
                """
                SELECT domain, ipv6_enabled, ipv6_success_rate, ipv4_success_rate,
                       ipv6_preference, ipv6_attempts, ipv6_successes,
                       ipv4_attempts, ipv4_successes, switch_count, switch_success_count,
                       last_ipv6_success_at, last_ipv6_failure_at,
                       last_ipv4_success_at, last_ipv4_failure_at
                FROM domains
                WHERE ipv6_enabled IS NOT NULL
                """
            )
            
            async with self._lock:
                for row in rows:
                    stats = DomainIPv6Stats.from_dict(dict(row))
                    self._domain_stats[stats.domain] = stats
            
            return len(rows)
        except Exception as e:
            logger.warning("Failed to load domain IPv6 stats from DB", error=str(e))
            return 0
    
    async def save_domain_stats_to_db(self, db, domain: str) -> bool:
        """Save domain stats to database.
        
        Args:
            db: Database instance.
            domain: Domain to save.
            
        Returns:
            True if saved successfully.
        """
        try:
            stats = await self.get_domain_stats(domain)
            data = stats.to_dict()
            
            # Update or insert into domains table
            await db.execute(
                """
                INSERT INTO domains (
                    domain, ipv6_enabled, ipv6_success_rate, ipv4_success_rate,
                    ipv6_preference, ipv6_attempts, ipv6_successes,
                    ipv4_attempts, ipv4_successes, switch_count, switch_success_count,
                    last_ipv6_success_at, last_ipv6_failure_at,
                    last_ipv4_success_at, last_ipv4_failure_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(domain) DO UPDATE SET
                    ipv6_enabled = excluded.ipv6_enabled,
                    ipv6_success_rate = excluded.ipv6_success_rate,
                    ipv4_success_rate = excluded.ipv4_success_rate,
                    ipv6_preference = excluded.ipv6_preference,
                    ipv6_attempts = excluded.ipv6_attempts,
                    ipv6_successes = excluded.ipv6_successes,
                    ipv4_attempts = excluded.ipv4_attempts,
                    ipv4_successes = excluded.ipv4_successes,
                    switch_count = excluded.switch_count,
                    switch_success_count = excluded.switch_success_count,
                    last_ipv6_success_at = excluded.last_ipv6_success_at,
                    last_ipv6_failure_at = excluded.last_ipv6_failure_at,
                    last_ipv4_success_at = excluded.last_ipv4_success_at,
                    last_ipv4_failure_at = excluded.last_ipv4_failure_at,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    data["domain"],
                    data["ipv6_enabled"],
                    data["ipv6_success_rate"],
                    data["ipv4_success_rate"],
                    data["ipv6_preference"],
                    data["ipv6_attempts"],
                    data["ipv6_successes"],
                    data["ipv4_attempts"],
                    data["ipv4_successes"],
                    data["switch_count"],
                    data["switch_success_count"],
                    data["last_ipv6_success_at"],
                    data["last_ipv6_failure_at"],
                    data["last_ipv4_success_at"],
                    data["last_ipv4_failure_at"],
                ),
            )
            return True
        except Exception as e:
            logger.warning("Failed to save domain IPv6 stats", domain=domain, error=str(e))
            return False


# Global IPv6 connection manager instance
_ipv6_manager: IPv6ConnectionManager | None = None


def get_ipv6_manager() -> IPv6ConnectionManager:
    """Get the global IPv6 connection manager instance.
    
    Returns:
        IPv6ConnectionManager instance.
    """
    global _ipv6_manager
    if _ipv6_manager is None:
        _ipv6_manager = IPv6ConnectionManager()
    return _ipv6_manager


async def resolve_with_ipv6_preference(
    hostname: str,
    domain: str | None = None,
) -> list[IPv6Address]:
    """Convenience function to resolve hostname with IPv6 preference.
    
    Args:
        hostname: Hostname to resolve.
        domain: Domain for per-domain preference.
        
    Returns:
        List of addresses sorted by preference.
    """
    manager = get_ipv6_manager()
    return await manager.get_preferred_addresses(hostname, domain)

