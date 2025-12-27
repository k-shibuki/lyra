"""
HTTP/3 (QUIC) Policy Manager for Lyra.

Implements ADR-0006 HTTP/3(QUIC) policy:
- Browser route naturally uses HTTP/3 when site provides it
- HTTP client uses HTTP/2 by default to minimize behavioral differences
- Auto-increase browser route ratio for sites where HTTP/3 makes a difference

Key behaviors:
1. Detect HTTP/3 usage in browser fetches via CDP Network events
2. Track per-domain HTTP/3 availability and success rates
3. Automatically increase browser route ratio when HTTP/3 sites show
   behavioral differences between browser and HTTP client routes
4. Provide policy decisions for route selection
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class ProtocolVersion(Enum):
    """HTTP protocol versions."""

    HTTP_1_1 = "h1"
    HTTP_2 = "h2"
    HTTP_3 = "h3"
    UNKNOWN = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "ProtocolVersion":
        """Parse protocol version from string.

        Args:
            value: Protocol string (e.g., "h3", "h2", "HTTP/1.1", "h3-29")

        Returns:
            ProtocolVersion enum value.
        """
        if not value:
            return cls.UNKNOWN

        value_lower = value.lower()

        # HTTP/3 variants (h3, h3-29, h3-Q050, etc.)
        if value_lower.startswith("h3") or "quic" in value_lower:
            return cls.HTTP_3

        # HTTP/2
        if value_lower in ("h2", "http/2", "http/2.0"):
            return cls.HTTP_2

        # HTTP/1.1
        if value_lower in ("h1", "http/1.1", "http/1.0", "1.1", "1.0"):
            return cls.HTTP_1_1

        return cls.UNKNOWN


@dataclass
class HTTP3DomainStats:
    """Per-domain HTTP/3 statistics.

    Tracks HTTP/3 availability and behavioral differences
    to inform route selection policy.
    """

    domain: str

    # HTTP/3 availability
    http3_detected: bool = False
    http3_first_seen_at: datetime | None = None
    http3_last_seen_at: datetime | None = None

    # Request counts by route
    browser_requests: int = 0
    browser_http3_requests: int = 0
    browser_successes: int = 0

    http_client_requests: int = 0
    http_client_successes: int = 0

    # Behavioral difference tracking
    # "Difference" = success rate gap between browser (with HTTP/3) and HTTP client
    behavioral_difference_samples: int = 0
    behavioral_difference_sum: float = 0.0

    # EMA of behavioral difference (0.0 = no difference, 1.0 = always different)
    behavioral_difference_ema: float = 0.0

    # Browser route ratio adjustment
    browser_ratio_boost: float = 0.0  # Additional ratio added due to HTTP/3

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def http3_ratio(self) -> float:
        """Ratio of HTTP/3 requests in browser route."""
        if self.browser_requests == 0:
            return 0.0
        return self.browser_http3_requests / self.browser_requests

    @property
    def browser_success_rate(self) -> float:
        """Success rate for browser route."""
        if self.browser_requests == 0:
            return 0.5  # Default assumption
        return self.browser_successes / self.browser_requests

    @property
    def http_client_success_rate(self) -> float:
        """Success rate for HTTP client route."""
        if self.http_client_requests == 0:
            return 0.5  # Default assumption
        return self.http_client_successes / self.http_client_requests

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "domain": self.domain,
            "http3_detected": self.http3_detected,
            "http3_first_seen_at": (
                self.http3_first_seen_at.isoformat() if self.http3_first_seen_at else None
            ),
            "http3_last_seen_at": (
                self.http3_last_seen_at.isoformat() if self.http3_last_seen_at else None
            ),
            "browser_requests": self.browser_requests,
            "browser_http3_requests": self.browser_http3_requests,
            "browser_successes": self.browser_successes,
            "http_client_requests": self.http_client_requests,
            "http_client_successes": self.http_client_successes,
            "behavioral_difference_samples": self.behavioral_difference_samples,
            "behavioral_difference_sum": self.behavioral_difference_sum,
            "behavioral_difference_ema": self.behavioral_difference_ema,
            "browser_ratio_boost": self.browser_ratio_boost,
            "http3_ratio": self.http3_ratio,
            "browser_success_rate": self.browser_success_rate,
            "http_client_success_rate": self.http_client_success_rate,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HTTP3DomainStats":
        """Create from dictionary."""
        stats = cls(domain=data["domain"])
        stats.http3_detected = data.get("http3_detected", False)

        if data.get("http3_first_seen_at"):
            stats.http3_first_seen_at = datetime.fromisoformat(data["http3_first_seen_at"])
        if data.get("http3_last_seen_at"):
            stats.http3_last_seen_at = datetime.fromisoformat(data["http3_last_seen_at"])

        stats.browser_requests = data.get("browser_requests", 0)
        stats.browser_http3_requests = data.get("browser_http3_requests", 0)
        stats.browser_successes = data.get("browser_successes", 0)
        stats.http_client_requests = data.get("http_client_requests", 0)
        stats.http_client_successes = data.get("http_client_successes", 0)
        stats.behavioral_difference_samples = data.get("behavioral_difference_samples", 0)
        stats.behavioral_difference_sum = data.get("behavioral_difference_sum", 0.0)
        stats.behavioral_difference_ema = data.get("behavioral_difference_ema", 0.0)
        stats.browser_ratio_boost = data.get("browser_ratio_boost", 0.0)

        if data.get("created_at"):
            stats.created_at = datetime.fromisoformat(data["created_at"])
        if data.get("updated_at"):
            stats.updated_at = datetime.fromisoformat(data["updated_at"])

        return stats


@dataclass
class HTTP3RequestResult:
    """Result of a request with HTTP/3 information."""

    domain: str
    url: str
    route: str  # "browser" or "http_client"
    success: bool
    protocol: ProtocolVersion
    status_code: int | None = None
    error: str | None = None
    latency_ms: float | None = None


@dataclass
class HTTP3PolicyDecision:
    """Policy decision for route selection based on HTTP/3 availability."""

    domain: str

    # Recommendation
    prefer_browser: bool = False
    browser_ratio_boost: float = 0.0
    reason: str = ""

    # Stats summary
    http3_available: bool = False
    http3_ratio: float = 0.0
    behavioral_difference: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "domain": self.domain,
            "prefer_browser": self.prefer_browser,
            "browser_ratio_boost": self.browser_ratio_boost,
            "reason": self.reason,
            "http3_available": self.http3_available,
            "http3_ratio": self.http3_ratio,
            "behavioral_difference": self.behavioral_difference,
        }


class HTTP3PolicyManager:
    """Manages HTTP/3 policy decisions for route selection.

    Per ADR-0006:
    - Browser route naturally uses HTTP/3 when site provides it
    - HTTP client uses HTTP/2 by default
    - Auto-increase browser route ratio when HTTP/3 sites show behavioral differences
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._stats_cache: dict[str, HTTP3DomainStats] = {}
        self._lock = asyncio.Lock()

        # Configuration
        self._ema_alpha = (
            getattr(getattr(self._settings, "http3", None), "ema_alpha", 0.1)
            if hasattr(self._settings, "http3")
            else 0.1
        )

        self._difference_threshold = (
            getattr(getattr(self._settings, "http3", None), "difference_threshold", 0.15)
            if hasattr(self._settings, "http3")
            else 0.15
        )

        self._max_browser_boost = (
            getattr(getattr(self._settings, "http3", None), "max_browser_boost", 0.3)
            if hasattr(self._settings, "http3")
            else 0.3
        )

        self._min_samples = (
            getattr(getattr(self._settings, "http3", None), "min_samples", 5)
            if hasattr(self._settings, "http3")
            else 5
        )

    async def get_stats(self, domain: str) -> HTTP3DomainStats:
        """Get or create stats for a domain.

        Args:
            domain: Domain name.

        Returns:
            HTTP3DomainStats instance.
        """
        async with self._lock:
            if domain not in self._stats_cache:
                # Try to load from database
                stats = await self._load_stats_from_db(domain)
                if stats is None:
                    stats = HTTP3DomainStats(domain=domain)
                self._stats_cache[domain] = stats
            return self._stats_cache[domain]

    async def record_request(self, result: HTTP3RequestResult) -> None:
        """Record a request result for HTTP/3 tracking.

        Args:
            result: Request result with protocol information.
        """
        stats = await self.get_stats(result.domain)
        now = datetime.now(UTC)

        async with self._lock:
            stats.updated_at = now

            if result.route == "browser":
                stats.browser_requests += 1
                if result.success:
                    stats.browser_successes += 1

                # Track HTTP/3 usage
                if result.protocol == ProtocolVersion.HTTP_3:
                    stats.browser_http3_requests += 1

                    if not stats.http3_detected:
                        stats.http3_detected = True
                        stats.http3_first_seen_at = now
                        logger.info(
                            "HTTP/3 detected for domain",
                            domain=result.domain,
                        )

                    stats.http3_last_seen_at = now

            elif result.route == "http_client":
                stats.http_client_requests += 1
                if result.success:
                    stats.http_client_successes += 1

            # Update behavioral difference tracking
            await self._update_behavioral_difference(stats)

            # Save to database
            await self._save_stats_to_db(stats)

    async def _update_behavioral_difference(self, stats: HTTP3DomainStats) -> None:
        """Update behavioral difference EMA based on success rate gap.

        The behavioral difference measures how much better browser route
        (with HTTP/3) performs compared to HTTP client route.

        Args:
            stats: Domain stats to update.
        """
        # Need minimum samples for both routes
        if stats.browser_requests < self._min_samples:
            return
        if stats.http_client_requests < self._min_samples:
            return

        # Calculate success rate difference
        # Positive = browser is better, Negative = HTTP client is better
        difference = stats.browser_success_rate - stats.http_client_success_rate

        # Only consider positive differences (browser advantage)
        # and only when HTTP/3 is actually being used
        if difference > 0 and stats.http3_ratio > 0.5:
            # Update EMA
            stats.behavioral_difference_ema = (
                self._ema_alpha * difference
                + (1 - self._ema_alpha) * stats.behavioral_difference_ema
            )
            stats.behavioral_difference_samples += 1
            stats.behavioral_difference_sum += difference
        else:
            # Decay toward zero when no advantage
            stats.behavioral_difference_ema *= 1 - self._ema_alpha * 0.5

        # Update browser ratio boost based on behavioral difference
        if stats.behavioral_difference_ema > self._difference_threshold:
            # Scale boost proportionally to difference
            boost_factor = min(stats.behavioral_difference_ema / self._difference_threshold, 2.0)
            stats.browser_ratio_boost = min(
                self._max_browser_boost * (boost_factor - 1) / 1.0, self._max_browser_boost
            )

            logger.debug(
                "HTTP/3 browser boost updated",
                domain=stats.domain,
                difference=stats.behavioral_difference_ema,
                boost=stats.browser_ratio_boost,
            )
        else:
            # Gradually reduce boost
            stats.browser_ratio_boost = max(0.0, stats.browser_ratio_boost - 0.01)

    async def get_policy_decision(self, domain: str) -> HTTP3PolicyDecision:
        """Get policy decision for route selection.

        Args:
            domain: Domain name.

        Returns:
            HTTP3PolicyDecision with recommendations.
        """
        stats = await self.get_stats(domain)

        decision = HTTP3PolicyDecision(
            domain=domain,
            http3_available=stats.http3_detected,
            http3_ratio=stats.http3_ratio,
            behavioral_difference=stats.behavioral_difference_ema,
        )

        # Determine if browser route should be preferred
        if stats.http3_detected and stats.browser_ratio_boost > 0.05:
            decision.prefer_browser = True
            decision.browser_ratio_boost = stats.browser_ratio_boost
            decision.reason = (
                f"HTTP/3 available (ratio={stats.http3_ratio:.2f}), "
                f"behavioral difference={stats.behavioral_difference_ema:.2f}"
            )
        elif stats.http3_detected:
            decision.prefer_browser = False
            decision.browser_ratio_boost = 0.0
            decision.reason = "HTTP/3 available but no significant behavioral difference"
        else:
            decision.prefer_browser = False
            decision.browser_ratio_boost = 0.0
            decision.reason = "HTTP/3 not detected"

        return decision

    async def get_adjusted_browser_ratio(
        self,
        domain: str,
        base_ratio: float,
    ) -> float:
        """Get browser ratio adjusted for HTTP/3 policy.

        Args:
            domain: Domain name.
            base_ratio: Base browser ratio from domain policy.

        Returns:
            Adjusted browser ratio (capped at 1.0).
        """
        decision = await self.get_policy_decision(domain)

        adjusted = base_ratio + decision.browser_ratio_boost

        # Cap at 1.0
        return min(1.0, adjusted)

    async def _load_stats_from_db(self, domain: str) -> HTTP3DomainStats | None:
        """Load stats from database.

        Args:
            domain: Domain name.

        Returns:
            HTTP3DomainStats or None if not found.
        """
        try:
            from src.storage.database import get_database

            db = await get_database()

            row = await db.fetch_one(
                """
                SELECT
                    http3_detected,
                    http3_first_seen_at,
                    http3_last_seen_at,
                    browser_requests,
                    browser_http3_requests,
                    browser_successes,
                    http_client_requests,
                    http_client_successes,
                    behavioral_difference_ema,
                    browser_ratio_boost
                FROM domains
                WHERE domain = ?
                """,
                (domain,),
            )

            if row is None:
                return None

            stats = HTTP3DomainStats(domain=domain)
            stats.http3_detected = bool(row.get("http3_detected", False))

            if row.get("http3_first_seen_at"):
                try:
                    stats.http3_first_seen_at = datetime.fromisoformat(row["http3_first_seen_at"])
                except (ValueError, TypeError):
                    pass

            if row.get("http3_last_seen_at"):
                try:
                    stats.http3_last_seen_at = datetime.fromisoformat(row["http3_last_seen_at"])
                except (ValueError, TypeError):
                    pass

            stats.browser_requests = row.get("browser_requests", 0) or 0
            stats.browser_http3_requests = row.get("browser_http3_requests", 0) or 0
            stats.browser_successes = row.get("browser_successes", 0) or 0
            stats.http_client_requests = row.get("http_client_requests", 0) or 0
            stats.http_client_successes = row.get("http_client_successes", 0) or 0
            stats.behavioral_difference_ema = row.get("behavioral_difference_ema", 0.0) or 0.0
            stats.browser_ratio_boost = row.get("browser_ratio_boost", 0.0) or 0.0

            return stats

        except Exception as e:
            logger.debug(
                "Failed to load HTTP/3 stats from DB",
                domain=domain,
                error=str(e),
            )
            return None

    async def _save_stats_to_db(self, stats: HTTP3DomainStats) -> None:
        """Save stats to database.

        Args:
            stats: Stats to save.
        """
        try:
            from src.storage.database import get_database

            db = await get_database()

            # Update or insert domain record
            await db.execute(
                """
                INSERT INTO domains (
                    domain,
                    http3_detected,
                    http3_first_seen_at,
                    http3_last_seen_at,
                    browser_requests,
                    browser_http3_requests,
                    browser_successes,
                    http_client_requests,
                    http_client_successes,
                    behavioral_difference_ema,
                    browser_ratio_boost,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(domain) DO UPDATE SET
                    http3_detected = excluded.http3_detected,
                    http3_first_seen_at = COALESCE(domains.http3_first_seen_at, excluded.http3_first_seen_at),
                    http3_last_seen_at = excluded.http3_last_seen_at,
                    browser_requests = excluded.browser_requests,
                    browser_http3_requests = excluded.browser_http3_requests,
                    browser_successes = excluded.browser_successes,
                    http_client_requests = excluded.http_client_requests,
                    http_client_successes = excluded.http_client_successes,
                    behavioral_difference_ema = excluded.behavioral_difference_ema,
                    browser_ratio_boost = excluded.browser_ratio_boost,
                    updated_at = excluded.updated_at
                """,
                (
                    stats.domain,
                    stats.http3_detected,
                    stats.http3_first_seen_at.isoformat() if stats.http3_first_seen_at else None,
                    stats.http3_last_seen_at.isoformat() if stats.http3_last_seen_at else None,
                    stats.browser_requests,
                    stats.browser_http3_requests,
                    stats.browser_successes,
                    stats.http_client_requests,
                    stats.http_client_successes,
                    stats.behavioral_difference_ema,
                    stats.browser_ratio_boost,
                    stats.updated_at.isoformat(),
                ),
            )

        except Exception as e:
            logger.debug(
                "Failed to save HTTP/3 stats to DB",
                domain=stats.domain,
                error=str(e),
            )

    def get_all_stats(self) -> dict[str, HTTP3DomainStats]:
        """Get all cached stats.

        Returns:
            Dictionary of domain -> stats.
        """
        return dict(self._stats_cache)

    async def get_http3_domains(self) -> list[str]:
        """Get list of domains where HTTP/3 has been detected.

        Returns:
            List of domain names.
        """
        try:
            from src.storage.database import get_database

            db = await get_database()

            rows = await db.fetch_all(
                """
                SELECT domain
                FROM domains
                WHERE http3_detected = 1
                ORDER BY http3_last_seen_at DESC
                """,
            )

            return [row["domain"] for row in rows]

        except Exception as e:
            logger.debug("Failed to get HTTP/3 domains", error=str(e))
            return []

    async def get_metrics(self) -> dict[str, Any]:
        """Get HTTP/3 policy metrics.

        Returns:
            Dictionary of metrics.
        """
        http3_domains = await self.get_http3_domains()

        total_browser_requests = 0
        total_http3_requests = 0
        total_boosted_domains = 0

        for stats in self._stats_cache.values():
            total_browser_requests += stats.browser_requests
            total_http3_requests += stats.browser_http3_requests
            if stats.browser_ratio_boost > 0.05:
                total_boosted_domains += 1

        return {
            "http3_domains_count": len(http3_domains),
            "http3_domains": http3_domains[:10],  # Top 10
            "total_browser_requests": total_browser_requests,
            "total_http3_requests": total_http3_requests,
            "http3_usage_rate": (
                total_http3_requests / total_browser_requests if total_browser_requests > 0 else 0.0
            ),
            "boosted_domains_count": total_boosted_domains,
            "cached_domains_count": len(self._stats_cache),
        }


# Global instance
_http3_policy_manager: HTTP3PolicyManager | None = None


def get_http3_policy_manager() -> HTTP3PolicyManager:
    """Get or create HTTP/3 policy manager instance.

    Returns:
        HTTP3PolicyManager instance.
    """
    global _http3_policy_manager
    if _http3_policy_manager is None:
        _http3_policy_manager = HTTP3PolicyManager()
    return _http3_policy_manager


def reset_http3_policy_manager() -> None:
    """Reset the global HTTP/3 policy manager (for testing)."""
    global _http3_policy_manager
    _http3_policy_manager = None


async def detect_protocol_from_cdp_response(
    response_data: dict[str, Any],
) -> ProtocolVersion:
    """Detect HTTP protocol version from CDP Network.responseReceived data.

    CDP provides protocol information in the response object.

    Args:
        response_data: CDP Network.responseReceived response object.

    Returns:
        ProtocolVersion detected.
    """
    # CDP provides protocol in the response object
    protocol = response_data.get("protocol", "")

    if protocol:
        return ProtocolVersion.from_string(protocol)

    # Fallback: check headers for Alt-Svc (HTTP/3 advertisement)
    headers = response_data.get("headers", {})
    alt_svc = headers.get("alt-svc", "") or headers.get("Alt-Svc", "")

    if alt_svc and ("h3" in alt_svc.lower() or "quic" in alt_svc.lower()):
        # Site advertises HTTP/3 but we may not be using it
        # This is informational only
        pass

    return ProtocolVersion.UNKNOWN


async def detect_protocol_from_playwright_response(
    response: Any,  # Playwright Response object
) -> ProtocolVersion:
    """Detect HTTP protocol version from Playwright response.

    Playwright doesn't directly expose protocol version, but we can
    use CDP to get this information if needed.

    Args:
        response: Playwright Response object.

    Returns:
        ProtocolVersion detected.
    """
    # Playwright doesn't expose protocol directly
    # We need to use CDP for this information
    # For now, return UNKNOWN and rely on CDP event monitoring

    # Check for Alt-Svc header as a hint
    try:
        alt_svc = await response.header_value("alt-svc")
        if alt_svc and ("h3" in alt_svc.lower() or "quic" in alt_svc.lower()):
            # Site advertises HTTP/3 - we might be using it
            # This is a hint, not definitive
            return ProtocolVersion.HTTP_3
    except Exception:
        pass

    return ProtocolVersion.UNKNOWN

    return ProtocolVersion.UNKNOWN
