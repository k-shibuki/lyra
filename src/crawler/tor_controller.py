"""Tor circuit controller for URL fetcher."""

import asyncio
import time
from typing import TYPE_CHECKING, Any, cast

from src.crawler.dns_policy import get_dns_policy_manager
from src.utils.config import get_settings
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from stem.control import Controller

logger = get_logger(__name__)


class TorController:
    """Controls Tor circuits via Stem library.

    Provides circuit renewal and exit node management.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._controller: Controller | None = None
        self._last_renewal: dict[str, float] = {}  # domain -> timestamp
        self._lock = asyncio.Lock()

    async def connect(self) -> bool:
        """Connect to Tor control port.

        Returns:
            True if connected successfully.
        """
        if not self._settings.tor.enabled:
            return False

        try:
            from stem.control import Controller

            self._controller = Controller.from_port(
                address=self._settings.tor.socks_host,
                port=self._settings.tor.control_port,
            )

            # Try to authenticate (no password by default)
            if self._controller is not None:
                self._controller.authenticate()

            logger.info(
                "Connected to Tor control port",
                port=self._settings.tor.control_port,
            )
            return True

        except Exception as e:
            logger.warning("Tor control connection failed", error=str(e))
            self._controller = None
            return False

    async def renew_circuit(self, domain: str | None = None) -> bool:
        """Request a new Tor circuit.

        Args:
            domain: Optional domain for sticky circuit tracking.

        Returns:
            True if circuit renewed successfully.
        """
        async with self._lock:
            if self._controller is None:
                if not await self.connect():
                    return False

            try:
                # Check sticky period for domain
                if domain:
                    sticky_minutes = self._settings.tor.circuit_sticky_minutes
                    last = self._last_renewal.get(domain, 0)

                    if time.time() - last < sticky_minutes * 60:
                        logger.debug(
                            "Skipping circuit renewal (sticky period)",
                            domain=domain,
                        )
                        return True

                # Request new circuit
                if self._controller is not None:
                    self._controller.signal("NEWNYM")

                # Wait for circuit to establish
                await asyncio.sleep(2.0)

                if domain:
                    self._last_renewal[domain] = time.time()

                logger.info("Tor circuit renewed", domain=domain)
                return True

            except Exception as e:
                logger.error("Tor circuit renewal failed", error=str(e))
                return False

    async def get_exit_ip(self) -> str | None:
        """Get current Tor exit node IP.

        Uses socks5h:// to ensure DNS is resolved through Tor.

        Returns:
            Exit IP address or None.
        """
        try:
            from curl_cffi import requests as curl_requests

            # Use DNS policy manager to get proxy with socks5h:// for DNS leak prevention
            dns_manager = get_dns_policy_manager()
            proxies = dns_manager.get_proxy_dict(use_tor=True)

            response = curl_requests.get(
                "https://check.torproject.org/api/ip",
                proxies=cast(Any, proxies),
                timeout=10,
            )

            data = response.json()
            return cast(str | None, data.get("IP"))

        except Exception as e:
            logger.debug("Failed to get Tor exit IP", error=str(e))
            return None

    def close(self) -> None:
        """Close Tor controller connection."""
        if self._controller:
            try:
                self._controller.close()
            except Exception:
                pass
            self._controller = None


# Global Tor controller
_tor_controller: TorController | None = None


async def get_tor_controller() -> TorController:
    """Get or create Tor controller instance.

    Returns:
        TorController instance.
    """
    global _tor_controller
    if _tor_controller is None:
        _tor_controller = TorController()
    return _tor_controller


async def _can_use_tor(domain: str | None = None) -> bool:
    """Check if Tor can be used based on daily limits.

    Per ADR-0006 and : Check both global daily limit (20%) and domain-specific limit.

    Args:
        domain: Optional domain for domain-specific check.

    Returns:
        True if Tor can be used, False if limit reached.
    """
    try:
        from src.utils.config import get_settings
        from src.utils.metrics import get_metrics_collector

        settings = get_settings()
        max_ratio = settings.tor.max_usage_ratio  # 0.20

        collector = get_metrics_collector()
        metrics = collector.get_today_tor_metrics()

        # Check global daily limit
        if metrics.usage_ratio >= max_ratio:
            logger.debug(
                "Tor daily limit reached",
                current_ratio=metrics.usage_ratio,
                max_ratio=max_ratio,
                total_requests=metrics.total_requests,
                tor_requests=metrics.tor_requests,
            )
            return False

        # Check domain-specific Tor policy
        if domain:
            from src.utils.domain_policy import get_domain_policy

            domain_policy = get_domain_policy(domain)  # Sync function

            # Check if Tor is blocked for this domain
            if not domain_policy.tor_allowed or domain_policy.tor_blocked:
                logger.debug(
                    "Tor blocked for domain",
                    domain=domain,
                    tor_allowed=domain_policy.tor_allowed,
                    tor_blocked=domain_policy.tor_blocked,
                )
                return False

            # Check domain-specific usage ratio (use global max as fallback)
            domain_metrics = collector.get_domain_tor_metrics(domain)
            # Use the global max_ratio as domain limit
            if domain_metrics.usage_ratio >= max_ratio:
                logger.debug(
                    "Tor domain usage limit reached",
                    domain=domain,
                    current_ratio=domain_metrics.usage_ratio,
                    max_ratio=max_ratio,
                )
                return False

        return True

    except Exception as e:
        # Fail-open: if we can't check limits, allow Tor usage
        logger.warning(
            "Failed to check Tor limits, allowing usage",
            error=str(e),
        )
        return True
