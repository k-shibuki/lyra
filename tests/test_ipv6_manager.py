"""
Tests for IPv6 Connection Management (§4.3).

Tests cover:
- IPv6/IPv4 address resolution with preference ordering
- Happy Eyeballs-style fallback logic
- Per-domain success rate learning (EMA)
- Automatic IPv6 disabling based on learning threshold
- Switch metrics tracking for acceptance criteria
- Integration with DNSPolicyManager

Per §7.1 test quality standards:
- No conditional assertions
- Specific expected values
- Mock external dependencies
- Proper test isolation

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-AR-01 | Resolve with IPv6 preference | Equivalence – preference | IPv6 first | - |
| TC-AR-02 | Resolve with IPv4 fallback | Equivalence – fallback | Falls back to IPv4 | - |
| TC-AR-03 | Resolve IPv6-only domain | Equivalence – v6 only | Returns IPv6 addresses | - |
| TC-AR-04 | Resolve IPv4-only domain | Boundary – v4 only | Returns IPv4 addresses | - |
| TC-HE-01 | Happy eyeballs race | Equivalence – racing | Fastest wins | - |
| TC-HE-02 | Happy eyeballs timeout | Boundary – timeout | Fallback triggered | - |
| TC-LR-01 | Learn IPv6 success | Equivalence – learning | Rate increases | - |
| TC-LR-02 | Learn IPv6 failure | Equivalence – learning | Rate decreases | - |
| TC-LR-03 | EMA calculation | Equivalence – EMA | Correct smoothing | - |
| TC-AD-01 | Auto-disable below threshold | Equivalence – threshold | IPv6 disabled | - |
| TC-AD-02 | Re-enable above threshold | Equivalence – recovery | IPv6 re-enabled | - |
| TC-SM-01 | Switch metrics tracking | Equivalence – metrics | Switches counted | - |
| TC-CF-01 | get_ipv6_manager | Equivalence – singleton | Returns manager | - |
"""


import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
import socket
from unittest.mock import MagicMock, patch

import pytest

from src.crawler.ipv6_manager import (
    AddressFamily,
    DomainIPv6Stats,
    IPv6Address,
    IPv6ConnectionManager,
    IPv6ConnectionResult,
    IPv6Metrics,
    IPv6Preference,
    get_ipv6_manager,
    resolve_with_ipv6_preference,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_settings():
    """Mock settings with IPv6 configuration."""
    settings = MagicMock()
    settings.ipv6.enabled = True
    settings.ipv6.preference = "ipv6_first"
    settings.ipv6.fallback_timeout = 5.0
    settings.ipv6.learning_threshold = 0.3
    settings.ipv6.min_samples = 5
    settings.ipv6.ema_alpha = 0.1
    return settings


@pytest.fixture
def ipv6_manager(mock_settings):
    """Create a fresh IPv6 connection manager."""
    with patch("src.crawler.ipv6_manager.get_settings", return_value=mock_settings):
        manager = IPv6ConnectionManager()
        return manager


# =============================================================================
# AddressFamily Tests
# =============================================================================


class TestAddressFamily:
    """Tests for AddressFamily enum."""

    def test_ipv4_value(self):
        """IPv4 should have correct value."""
        assert AddressFamily.IPV4.value == "ipv4"

    def test_ipv6_value(self):
        """IPv6 should have correct value."""
        assert AddressFamily.IPV6.value == "ipv6"

    def test_any_value(self):
        """ANY should have correct value."""
        assert AddressFamily.ANY.value == "any"


# =============================================================================
# IPv6Preference Tests
# =============================================================================


class TestIPv6Preference:
    """Tests for IPv6Preference enum."""

    def test_ipv6_first_value(self):
        """IPV6_FIRST should have correct value."""
        assert IPv6Preference.IPV6_FIRST.value == "ipv6_first"

    def test_ipv4_first_value(self):
        """IPV4_FIRST should have correct value."""
        assert IPv6Preference.IPV4_FIRST.value == "ipv4_first"

    def test_auto_value(self):
        """AUTO should have correct value."""
        assert IPv6Preference.AUTO.value == "auto"


# =============================================================================
# IPv6Address Tests
# =============================================================================


class TestIPv6Address:
    """Tests for IPv6Address dataclass."""

    def test_ipv6_address_is_ipv6(self):
        """IPv6 address should correctly report is_ipv6."""
        addr = IPv6Address(address="2001:db8::1", family=AddressFamily.IPV6)
        assert addr.is_ipv6 is True
        assert addr.is_ipv4 is False

    def test_ipv4_address_is_ipv4(self):
        """IPv4 address should correctly report is_ipv4."""
        addr = IPv6Address(address="192.168.1.1", family=AddressFamily.IPV4)
        assert addr.is_ipv4 is True
        assert addr.is_ipv6 is False


# =============================================================================
# IPv6ConnectionResult Tests
# =============================================================================


class TestIPv6ConnectionResult:
    """Tests for IPv6ConnectionResult dataclass."""

    def test_successful_result(self):
        """Successful connection result should have correct fields."""
        result = IPv6ConnectionResult(
            hostname="example.com",
            success=True,
            family_used=AddressFamily.IPV6,
            family_attempted=AddressFamily.IPV6,
            switched=False,
            switch_success=False,
            latency_ms=50.0,
        )
        assert result.success is True
        assert result.family_used == AddressFamily.IPV6
        assert result.switched is False

    def test_switched_result(self):
        """Switched connection result should have correct fields."""
        result = IPv6ConnectionResult(
            hostname="example.com",
            success=True,
            family_used=AddressFamily.IPV4,
            family_attempted=AddressFamily.IPV6,
            switched=True,
            switch_success=True,
            latency_ms=100.0,
        )
        assert result.switched is True
        assert result.switch_success is True
        assert result.family_attempted == AddressFamily.IPV6
        assert result.family_used == AddressFamily.IPV4

    def test_to_dict(self):
        """to_dict should return correct dictionary."""
        addresses = [
            IPv6Address("2001:db8::1", AddressFamily.IPV6),
            IPv6Address("192.168.1.1", AddressFamily.IPV4),
        ]
        result = IPv6ConnectionResult(
            hostname="example.com",
            success=True,
            family_used=AddressFamily.IPV6,
            family_attempted=AddressFamily.IPV6,
            switched=False,
            switch_success=False,
            latency_ms=25.0,
            addresses_resolved=addresses,
        )

        d = result.to_dict()

        assert d["hostname"] == "example.com"
        assert d["success"] is True
        assert d["family_used"] == "ipv6"
        assert d["latency_ms"] == 25.0
        assert len(d["addresses_resolved"]) == 2


# =============================================================================
# DomainIPv6Stats Tests
# =============================================================================


class TestDomainIPv6Stats:
    """Tests for DomainIPv6Stats dataclass."""

    def test_default_values(self):
        """Default values should be correctly set."""
        stats = DomainIPv6Stats(domain="example.com")

        assert stats.domain == "example.com"
        assert stats.ipv6_enabled is True
        assert stats.ipv6_success_rate == 0.5
        assert stats.ipv4_success_rate == 0.5
        assert stats.ipv6_preference == IPv6Preference.AUTO
        assert stats.switch_count == 0

    def test_get_preferred_family_ipv6_first(self):
        """get_preferred_family should return IPv6 when preference is IPv6_FIRST."""
        stats = DomainIPv6Stats(
            domain="example.com",
            ipv6_preference=IPv6Preference.IPV6_FIRST,
        )

        result = stats.get_preferred_family(IPv6Preference.AUTO)

        assert result == AddressFamily.IPV6

    def test_get_preferred_family_ipv4_first(self):
        """get_preferred_family should return IPv4 when preference is IPv4_FIRST."""
        stats = DomainIPv6Stats(
            domain="example.com",
            ipv6_preference=IPv6Preference.IPV4_FIRST,
        )

        result = stats.get_preferred_family(IPv6Preference.AUTO)

        assert result == AddressFamily.IPV4

    def test_get_preferred_family_disabled_ipv6(self):
        """get_preferred_family should return IPv4 when IPv6 is disabled."""
        stats = DomainIPv6Stats(
            domain="example.com",
            ipv6_enabled=False,
        )

        result = stats.get_preferred_family(IPv6Preference.IPV6_FIRST)

        assert result == AddressFamily.IPV4

    def test_get_preferred_family_auto_with_better_ipv6(self):
        """Auto preference should choose IPv6 when it has better success rate."""
        stats = DomainIPv6Stats(
            domain="example.com",
            ipv6_preference=IPv6Preference.AUTO,
            ipv6_success_rate=0.9,
            ipv4_success_rate=0.5,
            ipv6_attempts=10,
            ipv4_attempts=10,
        )

        result = stats.get_preferred_family(IPv6Preference.AUTO)

        assert result == AddressFamily.IPV6

    def test_get_preferred_family_auto_with_better_ipv4(self):
        """Auto preference should choose IPv4 when it has significantly better success rate."""
        stats = DomainIPv6Stats(
            domain="example.com",
            ipv6_preference=IPv6Preference.AUTO,
            ipv6_success_rate=0.3,
            ipv4_success_rate=0.9,
            ipv6_attempts=10,
            ipv4_attempts=10,
        )

        result = stats.get_preferred_family(IPv6Preference.AUTO)

        assert result == AddressFamily.IPV4

    def test_update_success_rate_ipv6_success(self):
        """update_success_rate should update IPv6 success rate on success."""
        stats = DomainIPv6Stats(domain="example.com", ipv6_success_rate=0.5)

        stats.update_success_rate(AddressFamily.IPV6, success=True, ema_alpha=0.1)

        # EMA: 0.1 * 1.0 + 0.9 * 0.5 = 0.55
        assert stats.ipv6_success_rate == pytest.approx(0.55)
        assert stats.ipv6_attempts == 1
        assert stats.ipv6_successes == 1
        # Success timestamp should be set (Unix timestamp as float)
        assert isinstance(stats.last_ipv6_success_at, (int, float)), (
            f"Expected numeric timestamp, got {type(stats.last_ipv6_success_at)}"
        )

    def test_update_success_rate_ipv6_failure(self):
        """update_success_rate should update IPv6 success rate on failure."""
        stats = DomainIPv6Stats(domain="example.com", ipv6_success_rate=0.5)

        stats.update_success_rate(AddressFamily.IPV6, success=False, ema_alpha=0.1)

        # EMA: 0.1 * 0.0 + 0.9 * 0.5 = 0.45
        assert stats.ipv6_success_rate == pytest.approx(0.45)
        assert stats.ipv6_attempts == 1
        assert stats.ipv6_successes == 0
        # Failure timestamp should be set (Unix timestamp as float)
        assert isinstance(stats.last_ipv6_failure_at, (int, float)), (
            f"Expected numeric timestamp, got {type(stats.last_ipv6_failure_at)}"
        )

    def test_update_success_rate_ipv4(self):
        """update_success_rate should update IPv4 success rate."""
        stats = DomainIPv6Stats(domain="example.com", ipv4_success_rate=0.5)

        stats.update_success_rate(AddressFamily.IPV4, success=True, ema_alpha=0.1)

        assert stats.ipv4_success_rate == pytest.approx(0.55)
        assert stats.ipv4_attempts == 1
        assert stats.ipv4_successes == 1

    def test_record_switch_success(self):
        """record_switch should track successful switches."""
        stats = DomainIPv6Stats(domain="example.com")

        stats.record_switch(success=True)

        assert stats.switch_count == 1
        assert stats.switch_success_count == 1
        assert stats.switch_success_rate == 1.0

    def test_record_switch_failure(self):
        """record_switch should track failed switches."""
        stats = DomainIPv6Stats(domain="example.com")

        stats.record_switch(success=False)

        assert stats.switch_count == 1
        assert stats.switch_success_count == 0
        assert stats.switch_success_rate == 0.0

    def test_switch_success_rate_multiple(self):
        """switch_success_rate should calculate correctly for multiple switches."""
        stats = DomainIPv6Stats(domain="example.com")

        stats.record_switch(success=True)
        stats.record_switch(success=True)
        stats.record_switch(success=False)
        stats.record_switch(success=True)

        assert stats.switch_count == 4
        assert stats.switch_success_count == 3
        assert stats.switch_success_rate == pytest.approx(0.75)

    def test_to_dict(self):
        """to_dict should return correct dictionary."""
        stats = DomainIPv6Stats(
            domain="example.com",
            ipv6_success_rate=0.8,
            switch_count=5,
        )

        d = stats.to_dict()

        assert d["domain"] == "example.com"
        assert d["ipv6_success_rate"] == 0.8
        assert d["switch_count"] == 5

    def test_from_dict(self):
        """from_dict should create correct object."""
        data = {
            "domain": "example.com",
            "ipv6_enabled": True,
            "ipv6_success_rate": 0.75,
            "ipv4_success_rate": 0.85,
            "ipv6_preference": "ipv4_first",
            "switch_count": 10,
            "switch_success_count": 8,
        }

        stats = DomainIPv6Stats.from_dict(data)

        assert stats.domain == "example.com"
        assert stats.ipv6_success_rate == 0.75
        assert stats.ipv6_preference == IPv6Preference.IPV4_FIRST
        assert stats.switch_success_rate == 0.8


# =============================================================================
# IPv6Metrics Tests
# =============================================================================


class TestIPv6Metrics:
    """Tests for IPv6Metrics dataclass."""

    def test_default_values(self):
        """Default values should be zero."""
        metrics = IPv6Metrics()

        assert metrics.total_ipv6_attempts == 0
        assert metrics.total_ipv6_successes == 0
        assert metrics.ipv6_success_rate == 0.0

    def test_record_ipv6_attempt_success(self):
        """record_attempt should track IPv6 success."""
        metrics = IPv6Metrics()

        metrics.record_attempt(AddressFamily.IPV6, success=True, latency_ms=50.0)

        assert metrics.total_ipv6_attempts == 1
        assert metrics.total_ipv6_successes == 1
        assert metrics.ipv6_success_rate == 1.0

    def test_record_ipv6_attempt_failure(self):
        """record_attempt should track IPv6 failure."""
        metrics = IPv6Metrics()

        metrics.record_attempt(AddressFamily.IPV6, success=False, latency_ms=5000.0)

        assert metrics.total_ipv6_attempts == 1
        assert metrics.total_ipv6_successes == 0
        assert metrics.ipv6_success_rate == 0.0

    def test_record_ipv4_attempt(self):
        """record_attempt should track IPv4 attempts."""
        metrics = IPv6Metrics()

        metrics.record_attempt(AddressFamily.IPV4, success=True, latency_ms=30.0)

        assert metrics.total_ipv4_attempts == 1
        assert metrics.total_ipv4_successes == 1
        assert metrics.ipv4_success_rate == 1.0

    def test_record_switch(self):
        """record_attempt should track switches."""
        metrics = IPv6Metrics()

        metrics.record_attempt(
            AddressFamily.IPV4,
            success=True,
            switched=True,
            switch_success=True,
        )

        assert metrics.total_switches == 1
        assert metrics.total_switch_successes == 1
        assert metrics.switch_success_rate == 1.0

    def test_switch_success_rate_acceptance_criteria(self):
        """Switch success rate should be trackable for acceptance criteria (≥80%)."""
        metrics = IPv6Metrics()

        # Simulate 100 switches, 85 successful
        for _ in range(85):
            metrics.record_attempt(
                AddressFamily.IPV4,
                success=True,
                switched=True,
                switch_success=True,
            )
        for _ in range(15):
            metrics.record_attempt(
                AddressFamily.IPV4,
                success=False,
                switched=True,
                switch_success=False,
            )

        assert metrics.switch_success_rate == pytest.approx(0.85)
        assert metrics.switch_success_rate >= 0.80  # Acceptance criteria

    def test_avg_latency(self):
        """avg_latency_ms should calculate correctly."""
        metrics = IPv6Metrics()

        metrics.record_attempt(AddressFamily.IPV6, success=True, latency_ms=10.0)
        metrics.record_attempt(AddressFamily.IPV6, success=True, latency_ms=20.0)
        metrics.record_attempt(AddressFamily.IPV6, success=True, latency_ms=30.0)

        assert metrics.avg_latency_ms == pytest.approx(20.0)

    def test_to_dict(self):
        """to_dict should return correct dictionary."""
        metrics = IPv6Metrics()
        metrics.record_attempt(AddressFamily.IPV6, success=True, latency_ms=50.0)

        d = metrics.to_dict()

        assert d["total_ipv6_attempts"] == 1
        assert d["ipv6_success_rate"] == 1.0
        assert "switch_success_rate" in d


# =============================================================================
# IPv6ConnectionManager Tests
# =============================================================================


class TestIPv6ConnectionManager:
    """Tests for IPv6ConnectionManager class."""

    @pytest.mark.asyncio
    async def test_get_domain_stats_creates_new(self, ipv6_manager):
        """get_domain_stats should create new stats for unknown domain."""
        stats = await ipv6_manager.get_domain_stats("newdomain.com")

        assert stats.domain == "newdomain.com"
        assert stats.ipv6_enabled is True
        assert stats.ipv6_success_rate == 0.5

    @pytest.mark.asyncio
    async def test_get_domain_stats_returns_existing(self, ipv6_manager):
        """get_domain_stats should return existing stats."""
        # Create stats
        stats1 = await ipv6_manager.get_domain_stats("example.com")
        stats1.ipv6_success_rate = 0.9
        await ipv6_manager.update_domain_stats("example.com", stats1)

        # Get again
        stats2 = await ipv6_manager.get_domain_stats("example.com")

        assert stats2.ipv6_success_rate == 0.9

    @pytest.mark.asyncio
    async def test_resolve_addresses_with_mock(self, mock_settings):
        """resolve_addresses should return IPv6 and IPv4 addresses."""
        mock_addr_info = [
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2001:db8::1", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.1", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.2", 0)),
        ]

        with patch("src.crawler.ipv6_manager.get_settings", return_value=mock_settings):
            with patch("socket.getaddrinfo", return_value=mock_addr_info):
                manager = IPv6ConnectionManager()
                ipv6_addrs, ipv4_addrs = await manager.resolve_addresses("example.com")

        assert len(ipv6_addrs) == 1
        assert ipv6_addrs[0].address == "2001:db8::1"
        assert ipv6_addrs[0].family == AddressFamily.IPV6

        assert len(ipv4_addrs) == 2
        assert ipv4_addrs[0].address == "192.168.1.1"
        assert ipv4_addrs[0].family == AddressFamily.IPV4

    @pytest.mark.asyncio
    async def test_get_preferred_addresses_ipv6_first(self, mock_settings):
        """get_preferred_addresses should return IPv6 first when preferred."""
        mock_addr_info = [
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2001:db8::1", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.1", 0)),
        ]

        with patch("src.crawler.ipv6_manager.get_settings", return_value=mock_settings):
            with patch("socket.getaddrinfo", return_value=mock_addr_info):
                manager = IPv6ConnectionManager()
                addresses = await manager.get_preferred_addresses("example.com", "example.com")

        # IPv6 should be first due to ipv6_first preference
        assert len(addresses) == 2
        assert addresses[0].family == AddressFamily.IPV6
        assert addresses[1].family == AddressFamily.IPV4

    @pytest.mark.asyncio
    async def test_get_preferred_addresses_ipv4_first(self, mock_settings):
        """get_preferred_addresses should return IPv4 first when preferred."""
        mock_settings.ipv6.preference = "ipv4_first"
        mock_addr_info = [
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2001:db8::1", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.1", 0)),
        ]

        with patch("src.crawler.ipv6_manager.get_settings", return_value=mock_settings):
            with patch("socket.getaddrinfo", return_value=mock_addr_info):
                manager = IPv6ConnectionManager()
                addresses = await manager.get_preferred_addresses("example.com", "example.com")

        # IPv4 should be first due to ipv4_first preference
        assert len(addresses) == 2
        assert addresses[0].family == AddressFamily.IPV4
        assert addresses[1].family == AddressFamily.IPV6

    @pytest.mark.asyncio
    async def test_record_connection_result_updates_stats(self, ipv6_manager):
        """record_connection_result should update domain stats."""
        result = IPv6ConnectionResult(
            hostname="example.com",
            success=True,
            family_used=AddressFamily.IPV6,
            family_attempted=AddressFamily.IPV6,
            switched=False,
            switch_success=False,
            latency_ms=50.0,
        )

        await ipv6_manager.record_connection_result("example.com", result)

        stats = await ipv6_manager.get_domain_stats("example.com")
        assert stats.ipv6_attempts == 1
        assert stats.ipv6_successes == 1

    @pytest.mark.asyncio
    async def test_record_connection_result_with_switch(self, ipv6_manager):
        """record_connection_result should track switches."""
        result = IPv6ConnectionResult(
            hostname="example.com",
            success=True,
            family_used=AddressFamily.IPV4,
            family_attempted=AddressFamily.IPV6,
            switched=True,
            switch_success=True,
            latency_ms=100.0,
        )

        await ipv6_manager.record_connection_result("example.com", result)

        stats = await ipv6_manager.get_domain_stats("example.com")
        assert stats.switch_count == 1
        assert stats.switch_success_count == 1

    @pytest.mark.asyncio
    async def test_auto_disable_ipv6_on_low_success(self, mock_settings):
        """IPv6 should be auto-disabled when success rate drops below threshold."""
        mock_settings.ipv6.learning_threshold = 0.3
        mock_settings.ipv6.min_samples = 5

        with patch("src.crawler.ipv6_manager.get_settings", return_value=mock_settings):
            manager = IPv6ConnectionManager()

            # Simulate 5 IPv6 failures
            for _ in range(5):
                result = IPv6ConnectionResult(
                    hostname="failing.com",
                    success=False,
                    family_used=AddressFamily.IPV6,
                    family_attempted=AddressFamily.IPV6,
                    switched=False,
                    switch_success=False,
                    latency_ms=5000.0,
                    error="Connection timeout",
                )
                await manager.record_connection_result("failing.com", result)

            stats = await manager.get_domain_stats("failing.com")

            # IPv6 should be disabled due to low success rate
            assert stats.ipv6_enabled is False

    @pytest.mark.asyncio
    async def test_try_connect_with_fallback_success_primary(self, mock_settings):
        """try_connect_with_fallback should succeed on primary family."""
        mock_addr_info = [
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2001:db8::1", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.1", 0)),
        ]

        async def mock_connect(address, family):
            return True, None

        with patch("src.crawler.ipv6_manager.get_settings", return_value=mock_settings):
            with patch("socket.getaddrinfo", return_value=mock_addr_info):
                manager = IPv6ConnectionManager()
                result = await manager.try_connect_with_fallback(
                    "example.com",
                    "example.com",
                    mock_connect,
                )

        assert result.success is True
        assert result.family_used == AddressFamily.IPV6
        assert result.switched is False

    @pytest.mark.asyncio
    async def test_try_connect_with_fallback_to_secondary(self, mock_settings):
        """try_connect_with_fallback should fallback when primary fails."""
        mock_addr_info = [
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2001:db8::1", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.1", 0)),
        ]

        call_count = 0

        async def mock_connect(address, family):
            nonlocal call_count
            call_count += 1
            # First call (IPv6) fails, second (IPv4) succeeds
            if call_count == 1:
                return False, "Connection refused"
            return True, None

        with patch("src.crawler.ipv6_manager.get_settings", return_value=mock_settings):
            with patch("socket.getaddrinfo", return_value=mock_addr_info):
                manager = IPv6ConnectionManager()
                result = await manager.try_connect_with_fallback(
                    "example.com",
                    "example.com",
                    mock_connect,
                )

        assert result.success is True
        assert result.family_used == AddressFamily.IPV4
        assert result.switched is True
        assert result.switch_success is True

    @pytest.mark.asyncio
    async def test_try_connect_with_fallback_all_fail(self, mock_settings):
        """try_connect_with_fallback should fail when all attempts fail."""
        mock_addr_info = [
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2001:db8::1", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.1", 0)),
        ]

        async def mock_connect(address, family):
            return False, "Connection refused"

        with patch("src.crawler.ipv6_manager.get_settings", return_value=mock_settings):
            with patch("socket.getaddrinfo", return_value=mock_addr_info):
                manager = IPv6ConnectionManager()
                result = await manager.try_connect_with_fallback(
                    "example.com",
                    "example.com",
                    mock_connect,
                )

        assert result.success is False
        assert result.switched is True
        assert result.switch_success is False
        assert result.error == "Connection refused"

    @pytest.mark.asyncio
    async def test_try_connect_no_addresses(self, mock_settings):
        """try_connect_with_fallback should handle no resolved addresses."""

        async def mock_connect(address, family):
            return True, None

        with patch("src.crawler.ipv6_manager.get_settings", return_value=mock_settings):
            with patch("socket.getaddrinfo", side_effect=socket.gaierror("Name resolution failed")):
                manager = IPv6ConnectionManager()
                result = await manager.try_connect_with_fallback(
                    "nonexistent.invalid",
                    "nonexistent.invalid",
                    mock_connect,
                )

        assert result.success is False
        assert result.error == "No addresses resolved"

    def test_is_ipv6_enabled(self, ipv6_manager):
        """is_ipv6_enabled should return global setting."""
        assert ipv6_manager.is_ipv6_enabled() is True

    @pytest.mark.asyncio
    async def test_is_ipv6_enabled_for_domain(self, ipv6_manager):
        """is_ipv6_enabled_for_domain should check domain-specific setting."""
        # Default should be enabled
        assert await ipv6_manager.is_ipv6_enabled_for_domain("example.com") is True

        # Disable for domain
        await ipv6_manager.enable_ipv6_for_domain("example.com", False)

        assert await ipv6_manager.is_ipv6_enabled_for_domain("example.com") is False

    @pytest.mark.asyncio
    async def test_set_domain_preference(self, ipv6_manager):
        """set_domain_preference should update preference."""
        await ipv6_manager.set_domain_preference("example.com", IPv6Preference.IPV4_FIRST)

        stats = await ipv6_manager.get_domain_stats("example.com")

        assert stats.ipv6_preference == IPv6Preference.IPV4_FIRST

    def test_metrics_property(self, ipv6_manager):
        """metrics property should return metrics object."""
        metrics = ipv6_manager.metrics

        assert isinstance(metrics, IPv6Metrics)
        assert metrics.total_ipv6_attempts == 0


# =============================================================================
# Global Function Tests
# =============================================================================


class TestGlobalFunctions:
    """Tests for global convenience functions."""

    def test_get_ipv6_manager_singleton(self, mock_settings):
        """get_ipv6_manager should return singleton."""
        import src.crawler.ipv6_manager as ipv6_module

        ipv6_module._ipv6_manager = None

        with patch("src.crawler.ipv6_manager.get_settings", return_value=mock_settings):
            manager1 = get_ipv6_manager()
            manager2 = get_ipv6_manager()

        assert manager1 is manager2

        # Cleanup
        ipv6_module._ipv6_manager = None

    @pytest.mark.asyncio
    async def test_resolve_with_ipv6_preference(self, mock_settings):
        """resolve_with_ipv6_preference should use manager."""
        import src.crawler.ipv6_manager as ipv6_module

        ipv6_module._ipv6_manager = None

        mock_addr_info = [
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2001:db8::1", 0)),
        ]

        with patch("src.crawler.ipv6_manager.get_settings", return_value=mock_settings):
            with patch("socket.getaddrinfo", return_value=mock_addr_info):
                addresses = await resolve_with_ipv6_preference("example.com")

        assert len(addresses) == 1
        assert addresses[0].family == AddressFamily.IPV6

        # Cleanup
        ipv6_module._ipv6_manager = None


# =============================================================================
# Integration Tests
# =============================================================================


class TestIPv6ManagerIntegration:
    """Integration tests for IPv6ConnectionManager."""

    @pytest.mark.asyncio
    async def test_learning_improves_preference(self, mock_settings):
        """Repeated successes should improve preference for that family (§4.3).

        EMA calculation with alpha=0.1, initial=0.5, 5 successes:
        - After 1: 0.1*1 + 0.9*0.5 = 0.55
        - After 2: 0.1*1 + 0.9*0.55 = 0.595
        - After 3: 0.1*1 + 0.9*0.595 = 0.6355
        - After 4: 0.1*1 + 0.9*0.6355 = 0.67195
        - After 5: 0.1*1 + 0.9*0.67195 = 0.704755
        """
        mock_settings.ipv6.min_samples = 3
        mock_settings.ipv6.ema_alpha = 0.1

        with patch("src.crawler.ipv6_manager.get_settings", return_value=mock_settings):
            manager = IPv6ConnectionManager()

            # Simulate successful IPv6 connections
            for _ in range(5):
                result = IPv6ConnectionResult(
                    hostname="ipv6-only.com",
                    success=True,
                    family_used=AddressFamily.IPV6,
                    family_attempted=AddressFamily.IPV6,
                    switched=False,
                    switch_success=False,
                    latency_ms=30.0,
                )
                await manager.record_connection_result("ipv6-only.com", result)

            stats = await manager.get_domain_stats("ipv6-only.com")

            # EMA after 5 successes: 0.704755 (calculated above)
            expected_rate = 0.704755
            assert stats.ipv6_success_rate == pytest.approx(expected_rate, rel=0.01), (
                f"Expected IPv6 success rate ~{expected_rate}, got {stats.ipv6_success_rate}"
            )
            assert stats.ipv6_enabled is True, "IPv6 should remain enabled after successes"

    @pytest.mark.asyncio
    async def test_switch_tracking_for_acceptance_criteria(self, mock_settings):
        """Switch success rate should be trackable per acceptance criteria."""
        with patch("src.crawler.ipv6_manager.get_settings", return_value=mock_settings):
            manager = IPv6ConnectionManager()

            # Simulate switches - 8 successful, 2 failed (80% success)
            for _ in range(8):
                result = IPv6ConnectionResult(
                    hostname="mixed.com",
                    success=True,
                    family_used=AddressFamily.IPV4,
                    family_attempted=AddressFamily.IPV6,
                    switched=True,
                    switch_success=True,
                    latency_ms=100.0,
                )
                await manager.record_connection_result("mixed.com", result)

            for _ in range(2):
                result = IPv6ConnectionResult(
                    hostname="mixed.com",
                    success=False,
                    family_used=AddressFamily.IPV4,
                    family_attempted=AddressFamily.IPV6,
                    switched=True,
                    switch_success=False,
                    latency_ms=5000.0,
                )
                await manager.record_connection_result("mixed.com", result)

            # Check metrics
            metrics = manager.metrics

            # §7 acceptance criteria: switch success rate ≥80%
            assert metrics.switch_success_rate == pytest.approx(0.8)

    @pytest.mark.asyncio
    async def test_happy_eyeballs_interleaving(self, mock_settings):
        """Addresses should be interleaved for Happy Eyeballs (§4.3)."""
        mock_addr_info = [
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2001:db8::1", 0)),
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2001:db8::2", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.1", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.2", 0)),
        ]

        with patch("src.crawler.ipv6_manager.get_settings", return_value=mock_settings):
            with patch("socket.getaddrinfo", return_value=mock_addr_info):
                manager = IPv6ConnectionManager()
                addresses = await manager.get_preferred_addresses("example.com", "example.com")

        # Should be interleaved: IPv6, IPv4, IPv6, IPv4
        assert len(addresses) == 4, f"Expected 4 addresses, got {len(addresses)}"
        assert addresses[0].family == AddressFamily.IPV6, "First address should be IPv6"
        assert addresses[1].family == AddressFamily.IPV4, "Second address should be IPv4"
        assert addresses[2].family == AddressFamily.IPV6, "Third address should be IPv6"
        assert addresses[3].family == AddressFamily.IPV4, "Fourth address should be IPv4"


# =============================================================================
# Boundary Condition Tests (§7.1.2.4)
# =============================================================================


class TestIPv6BoundaryConditions:
    """Boundary condition tests per §7.1.2.4."""

    @pytest.mark.asyncio
    async def test_empty_address_resolution(self, mock_settings):
        """Empty DNS resolution should return empty lists."""
        with patch("src.crawler.ipv6_manager.get_settings", return_value=mock_settings):
            with patch("socket.getaddrinfo", return_value=[]):
                manager = IPv6ConnectionManager()
                ipv6_addrs, ipv4_addrs = await manager.resolve_addresses("empty.example.com")

        assert ipv6_addrs == [], "IPv6 addresses should be empty"
        assert ipv4_addrs == [], "IPv4 addresses should be empty"

    @pytest.mark.asyncio
    async def test_single_ipv6_address_only(self, mock_settings):
        """Single IPv6-only resolution should work correctly."""
        mock_addr_info = [
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2001:db8::1", 0)),
        ]

        with patch("src.crawler.ipv6_manager.get_settings", return_value=mock_settings):
            with patch("socket.getaddrinfo", return_value=mock_addr_info):
                manager = IPv6ConnectionManager()
                addresses = await manager.get_preferred_addresses("ipv6only.example.com", "ipv6only.example.com")

        assert len(addresses) == 1, "Should have exactly 1 address"
        assert addresses[0].family == AddressFamily.IPV6, "Address should be IPv6"
        assert addresses[0].address == "2001:db8::1", "Address should match"

    @pytest.mark.asyncio
    async def test_single_ipv4_address_only(self, mock_settings):
        """Single IPv4-only resolution should work correctly."""
        mock_addr_info = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.1", 0)),
        ]

        with patch("src.crawler.ipv6_manager.get_settings", return_value=mock_settings):
            with patch("socket.getaddrinfo", return_value=mock_addr_info):
                manager = IPv6ConnectionManager()
                addresses = await manager.get_preferred_addresses("ipv4only.example.com", "ipv4only.example.com")

        assert len(addresses) == 1, "Should have exactly 1 address"
        assert addresses[0].family == AddressFamily.IPV4, "Address should be IPv4"
        assert addresses[0].address == "192.168.1.1", "Address should match"

    @pytest.mark.asyncio
    async def test_ipv6_only_with_ipv6_first_preference(self, mock_settings):
        """IPv6-only host with IPv6-first preference should succeed without fallback."""
        mock_settings.ipv6.preference = "ipv6_first"
        mock_addr_info = [
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2001:db8::1", 0)),
        ]

        async def mock_connect(address, family):
            return True, None

        with patch("src.crawler.ipv6_manager.get_settings", return_value=mock_settings):
            with patch("socket.getaddrinfo", return_value=mock_addr_info):
                manager = IPv6ConnectionManager()
                result = await manager.try_connect_with_fallback(
                    "ipv6only.example.com",
                    "ipv6only.example.com",
                    mock_connect,
                )

        assert result.success is True, "Connection should succeed"
        assert result.family_used == AddressFamily.IPV6, "Should use IPv6"
        assert result.switched is False, "Should not switch (no fallback available)"

    @pytest.mark.asyncio
    async def test_ipv4_only_with_ipv6_first_preference(self, mock_settings):
        """IPv4-only host with IPv6-first preference should succeed with IPv4."""
        mock_settings.ipv6.preference = "ipv6_first"
        mock_addr_info = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.1", 0)),
        ]

        async def mock_connect(address, family):
            return True, None

        with patch("src.crawler.ipv6_manager.get_settings", return_value=mock_settings):
            with patch("socket.getaddrinfo", return_value=mock_addr_info):
                manager = IPv6ConnectionManager()
                result = await manager.try_connect_with_fallback(
                    "ipv4only.example.com",
                    "ipv4only.example.com",
                    mock_connect,
                )

        assert result.success is True, "Connection should succeed"
        assert result.family_used == AddressFamily.IPV4, "Should use IPv4 (only option)"
        assert result.switched is False, "Should not count as switch (IPv4 is first available)"

    def test_domain_stats_zero_switch_count(self):
        """switch_success_rate should be 0.0 when no switches occurred."""
        stats = DomainIPv6Stats(domain="example.com")

        assert stats.switch_count == 0, "Initial switch count should be 0"
        assert stats.switch_success_rate == 0.0, "Rate should be 0.0 with no switches"

    def test_domain_stats_zero_attempts(self):
        """Success rates with zero attempts should use default values."""
        stats = DomainIPv6Stats(domain="example.com")

        assert stats.ipv6_attempts == 0, "Initial IPv6 attempts should be 0"
        assert stats.ipv4_attempts == 0, "Initial IPv4 attempts should be 0"
        # Default success rates are 0.5
        assert stats.ipv6_success_rate == 0.5, "Default IPv6 success rate should be 0.5"
        assert stats.ipv4_success_rate == 0.5, "Default IPv4 success rate should be 0.5"

    @pytest.mark.asyncio
    async def test_duplicate_address_deduplication(self, mock_settings):
        """Duplicate addresses should be deduplicated."""
        mock_addr_info = [
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2001:db8::1", 0)),
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2001:db8::1", 0)),  # Duplicate
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.1", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.1", 0)),  # Duplicate
        ]

        with patch("src.crawler.ipv6_manager.get_settings", return_value=mock_settings):
            with patch("socket.getaddrinfo", return_value=mock_addr_info):
                manager = IPv6ConnectionManager()
                ipv6_addrs, ipv4_addrs = await manager.resolve_addresses("example.com")

        assert len(ipv6_addrs) == 1, "Duplicate IPv6 addresses should be deduplicated"
        assert len(ipv4_addrs) == 1, "Duplicate IPv4 addresses should be deduplicated"

    def test_metrics_empty_latency_list(self):
        """avg_latency_ms should return 0.0 for empty latency list."""
        metrics = IPv6Metrics()

        assert metrics.avg_latency_ms == 0.0, "Average latency should be 0.0 with no data"

    def test_metrics_latency_window_limit(self):
        """Latency window should be limited to last 100 entries."""
        metrics = IPv6Metrics()

        # Record 150 attempts
        for i in range(150):
            metrics.record_attempt(
                AddressFamily.IPV6,
                success=True,
                latency_ms=float(i),
            )

        # Only last 100 should be kept (50-149)
        expected_avg = sum(range(50, 150)) / 100  # Average of 50-149 = 99.5
        assert metrics.avg_latency_ms == pytest.approx(expected_avg), (
            f"Expected avg latency {expected_avg}, got {metrics.avg_latency_ms}"
        )
