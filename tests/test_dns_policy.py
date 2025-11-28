"""
Tests for DNS policy management (§4.3).

Tests cover:
- SOCKS proxy URL generation (socks5:// vs socks5h://)
- DNS leak prevention when using Tor
- DNS cache with TTL respect
- Metrics collection
"""

import asyncio
import time
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from src.crawler.dns_policy import (
    DNSRoute,
    DNSLeakType,
    DNSCacheEntry,
    DNSResolutionResult,
    DNSMetrics,
    DNSPolicyManager,
    get_dns_policy_manager,
    get_socks_proxy_for_request,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def dns_manager():
    """Create a fresh DNS policy manager for each test."""
    return DNSPolicyManager()


@pytest.fixture
def mock_settings():
    """Mock settings with DNS policy configuration."""
    settings = MagicMock()
    settings.tor.enabled = True
    settings.tor.socks_host = "127.0.0.1"
    settings.tor.socks_port = 9050
    settings.tor.dns.resolve_through_tor = True
    settings.tor.dns.disable_edns_client_subnet = True
    settings.tor.dns.respect_cache_ttl = True
    settings.tor.dns.min_cache_ttl = 60
    settings.tor.dns.max_cache_ttl = 3600
    settings.tor.dns.leak_detection_enabled = True
    return settings


# =============================================================================
# DNSCacheEntry Tests
# =============================================================================


class TestDNSCacheEntry:
    """Tests for DNSCacheEntry."""

    def test_cache_entry_not_expired_within_ttl(self):
        """Cache entry should not be expired within TTL."""
        entry = DNSCacheEntry(
            hostname="example.com",
            addresses=["93.184.216.34"],
            resolved_at=time.time(),
            ttl=300,
            route=DNSRoute.DIRECT,
        )
        assert not entry.is_expired()

    def test_cache_entry_expired_after_ttl(self):
        """Cache entry should be expired after TTL."""
        entry = DNSCacheEntry(
            hostname="example.com",
            addresses=["93.184.216.34"],
            resolved_at=time.time() - 400,  # 400 seconds ago
            ttl=300,  # 5 minute TTL
            route=DNSRoute.DIRECT,
        )
        assert entry.is_expired()


# =============================================================================
# DNSResolutionResult Tests
# =============================================================================


class TestDNSResolutionResult:
    """Tests for DNSResolutionResult."""

    def test_success_with_addresses(self):
        """Result with addresses should be successful."""
        result = DNSResolutionResult(
            hostname="example.com",
            addresses=["93.184.216.34"],
            route=DNSRoute.DIRECT,
            from_cache=False,
            resolution_time_ms=10.5,
        )
        assert result.success

    def test_failure_without_addresses(self):
        """Result without addresses should not be successful."""
        result = DNSResolutionResult(
            hostname="nonexistent.invalid",
            addresses=[],
            route=DNSRoute.DIRECT,
            from_cache=False,
            resolution_time_ms=50.0,
        )
        assert not result.success

    def test_leak_detected_flag(self):
        """Leak detection should be properly set."""
        result = DNSResolutionResult(
            hostname="example.com",
            addresses=[],
            route=DNSRoute.TOR,
            from_cache=False,
            resolution_time_ms=0,
            leak_detected=DNSLeakType.LOCAL_RESOLUTION_DURING_TOR,
        )
        assert result.leak_detected == DNSLeakType.LOCAL_RESOLUTION_DURING_TOR


# =============================================================================
# DNSMetrics Tests
# =============================================================================


class TestDNSMetrics:
    """Tests for DNSMetrics."""

    def test_record_resolution_increments_counts(self):
        """Recording resolution should update counts."""
        metrics = DNSMetrics()
        
        metrics.record_resolution(
            route=DNSRoute.DIRECT,
            from_cache=False,
            time_ms=10.0,
        )
        
        assert metrics.total_resolutions == 1
        assert metrics.cache_misses == 1
        assert metrics.direct_resolutions == 1
        assert metrics.cache_hits == 0
        assert metrics.tor_resolutions == 0

    def test_record_cache_hit(self):
        """Recording cache hit should update cache_hits."""
        metrics = DNSMetrics()
        
        metrics.record_resolution(
            route=DNSRoute.DIRECT,
            from_cache=True,
            time_ms=0.1,
        )
        
        assert metrics.cache_hits == 1
        assert metrics.cache_misses == 0

    def test_record_tor_resolution(self):
        """Recording Tor resolution should update tor_resolutions."""
        metrics = DNSMetrics()
        
        metrics.record_resolution(
            route=DNSRoute.TOR,
            from_cache=False,
            time_ms=50.0,
        )
        
        assert metrics.tor_resolutions == 1
        assert metrics.direct_resolutions == 0

    def test_record_leak_detected(self):
        """Recording leak should update leaks_detected."""
        metrics = DNSMetrics()
        
        metrics.record_resolution(
            route=DNSRoute.TOR,
            from_cache=False,
            time_ms=0,
            leak_detected=True,
        )
        
        assert metrics.leaks_detected == 1

    def test_average_resolution_time(self):
        """Average resolution time should be calculated correctly."""
        metrics = DNSMetrics()
        
        for t in [10.0, 20.0, 30.0]:
            metrics.record_resolution(
                route=DNSRoute.DIRECT,
                from_cache=False,
                time_ms=t,
            )
        
        assert metrics.avg_resolution_time_ms == pytest.approx(20.0)

    def test_to_dict(self):
        """Metrics should be convertible to dictionary."""
        metrics = DNSMetrics()
        metrics.record_resolution(DNSRoute.DIRECT, from_cache=True, time_ms=5.0)
        metrics.record_resolution(DNSRoute.TOR, from_cache=False, time_ms=10.0)
        
        result = metrics.to_dict()
        
        assert result["total_resolutions"] == 2
        assert result["cache_hits"] == 1
        assert result["cache_misses"] == 1
        assert result["tor_resolutions"] == 1
        assert result["direct_resolutions"] == 1
        assert "cache_hit_rate" in result
        assert "leak_rate" in result


# =============================================================================
# DNSPolicyManager Tests - Proxy URL Generation
# =============================================================================


class TestDNSPolicyManagerProxyGeneration:
    """Tests for SOCKS proxy URL generation."""

    def test_socks5h_used_when_resolve_through_tor_enabled(self, mock_settings):
        """socks5h:// should be used when resolve_through_tor is True."""
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            manager = DNSPolicyManager()
            proxy_url = manager.get_socks_proxy_url(use_tor=True)
            
            assert proxy_url is not None
            assert proxy_url.startswith("socks5h://")
            assert "127.0.0.1:9050" in proxy_url

    def test_socks5_used_when_resolve_through_tor_disabled(self, mock_settings):
        """socks5:// should be used when resolve_through_tor is False."""
        mock_settings.tor.dns.resolve_through_tor = False
        
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            manager = DNSPolicyManager()
            proxy_url = manager.get_socks_proxy_url(use_tor=True)
            
            assert proxy_url is not None
            assert proxy_url.startswith("socks5://")
            assert not proxy_url.startswith("socks5h://")

    def test_override_resolve_dns_through_proxy(self, mock_settings):
        """Override parameter should take precedence over config."""
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            manager = DNSPolicyManager()
            
            # Config says True, but we override to False
            proxy_url = manager.get_socks_proxy_url(
                use_tor=True,
                resolve_dns_through_proxy=False,
            )
            assert proxy_url.startswith("socks5://")
            
            # Config says True, and we explicitly set True
            proxy_url = manager.get_socks_proxy_url(
                use_tor=True,
                resolve_dns_through_proxy=True,
            )
            assert proxy_url.startswith("socks5h://")

    def test_no_proxy_when_use_tor_false(self, mock_settings):
        """No proxy should be returned when use_tor is False."""
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            manager = DNSPolicyManager()
            proxy_url = manager.get_socks_proxy_url(use_tor=False)
            
            assert proxy_url is None

    def test_no_proxy_when_tor_disabled(self, mock_settings):
        """No proxy should be returned when Tor is disabled in settings."""
        mock_settings.tor.enabled = False
        
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            manager = DNSPolicyManager()
            proxy_url = manager.get_socks_proxy_url(use_tor=True)
            
            assert proxy_url is None

    def test_get_proxy_dict(self, mock_settings):
        """get_proxy_dict should return proper dictionary."""
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            manager = DNSPolicyManager()
            proxy_dict = manager.get_proxy_dict(use_tor=True)
            
            assert proxy_dict is not None
            assert "http" in proxy_dict
            assert "https" in proxy_dict
            assert proxy_dict["http"] == proxy_dict["https"]
            assert proxy_dict["http"].startswith("socks5h://")

    def test_get_proxy_dict_none_when_not_using_tor(self, mock_settings):
        """get_proxy_dict should return None when not using Tor."""
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            manager = DNSPolicyManager()
            proxy_dict = manager.get_proxy_dict(use_tor=False)
            
            assert proxy_dict is None


# =============================================================================
# DNSPolicyManager Tests - DNS Resolution
# =============================================================================


class TestDNSPolicyManagerResolution:
    """Tests for DNS resolution functionality."""

    @pytest.mark.asyncio
    async def test_tor_route_returns_leak_warning(self, mock_settings):
        """Resolving with TOR route should return leak warning."""
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            manager = DNSPolicyManager()
            result = await manager.resolve_hostname(
                "example.com",
                DNSRoute.TOR,
            )
            
            # Should detect potential leak since we're trying to resolve locally
            assert result.leak_detected == DNSLeakType.LOCAL_RESOLUTION_DURING_TOR
            assert result.addresses == []  # Should not resolve locally

    @pytest.mark.asyncio
    async def test_direct_route_resolves_hostname(self, mock_settings):
        """Direct route should resolve hostname."""
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            manager = DNSPolicyManager()
            
            # Use a hostname that should resolve
            result = await manager.resolve_hostname(
                "localhost",
                DNSRoute.DIRECT,
            )
            
            # localhost should resolve to 127.0.0.1 or ::1
            assert result.success
            assert len(result.addresses) > 0
            assert result.leak_detected == DNSLeakType.NONE

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_result(self, mock_settings):
        """Second resolution should return cached result."""
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            manager = DNSPolicyManager()
            
            # First resolution
            result1 = await manager.resolve_hostname(
                "localhost",
                DNSRoute.DIRECT,
            )
            assert not result1.from_cache
            
            # Second resolution should be from cache
            result2 = await manager.resolve_hostname(
                "localhost",
                DNSRoute.DIRECT,
            )
            assert result2.from_cache
            assert result2.addresses == result1.addresses

    @pytest.mark.asyncio
    async def test_cache_bypass_with_use_cache_false(self, mock_settings):
        """Setting use_cache=False should bypass cache."""
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            manager = DNSPolicyManager()
            
            # First resolution
            await manager.resolve_hostname(
                "localhost",
                DNSRoute.DIRECT,
            )
            
            # Second resolution with cache disabled
            result2 = await manager.resolve_hostname(
                "localhost",
                DNSRoute.DIRECT,
                use_cache=False,
            )
            assert not result2.from_cache


# =============================================================================
# DNSPolicyManager Tests - Cache Management
# =============================================================================


class TestDNSPolicyManagerCache:
    """Tests for DNS cache management."""

    @pytest.mark.asyncio
    async def test_clear_cache(self, mock_settings):
        """clear_cache should remove all entries."""
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            manager = DNSPolicyManager()
            
            # Add some cache entries
            await manager.resolve_hostname("localhost", DNSRoute.DIRECT)
            
            # Clear cache
            count = await manager.clear_cache()
            assert count >= 1
            
            # Next resolution should not be from cache
            result = await manager.resolve_hostname("localhost", DNSRoute.DIRECT)
            assert not result.from_cache

    @pytest.mark.asyncio
    async def test_prune_expired_cache(self, mock_settings):
        """prune_expired_cache should remove expired entries."""
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            manager = DNSPolicyManager()
            
            # Manually add an expired entry
            manager._cache["test:direct"] = DNSCacheEntry(
                hostname="test",
                addresses=["1.2.3.4"],
                resolved_at=time.time() - 7200,  # 2 hours ago
                ttl=300,  # 5 minute TTL (expired)
                route=DNSRoute.DIRECT,
            )
            
            count = await manager.prune_expired_cache()
            assert count == 1

    def test_get_cache_stats(self, mock_settings):
        """get_cache_stats should return cache statistics."""
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            manager = DNSPolicyManager()
            
            # Add entries
            manager._cache["active:direct"] = DNSCacheEntry(
                hostname="active",
                addresses=["1.2.3.4"],
                resolved_at=time.time(),
                ttl=300,
                route=DNSRoute.DIRECT,
            )
            manager._cache["expired:direct"] = DNSCacheEntry(
                hostname="expired",
                addresses=["5.6.7.8"],
                resolved_at=time.time() - 7200,
                ttl=300,
                route=DNSRoute.DIRECT,
            )
            
            stats = manager.get_cache_stats()
            
            assert stats["total_entries"] == 2
            assert stats["active_entries"] == 1
            assert stats["expired_entries"] == 1


# =============================================================================
# DNSPolicyManager Tests - Leak Detection
# =============================================================================


class TestDNSPolicyManagerLeakDetection:
    """Tests for DNS leak detection."""

    def test_detect_leak_during_tor_route(self, mock_settings):
        """Should detect leak when local resolution happens during Tor route."""
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            manager = DNSPolicyManager()
            
            leak = manager.detect_dns_leak(
                url="https://example.com/page",
                use_tor=True,
                local_resolution_attempted=True,
            )
            
            assert leak == DNSLeakType.LOCAL_RESOLUTION_DURING_TOR

    def test_no_leak_with_direct_route(self, mock_settings):
        """No leak should be detected with direct route."""
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            manager = DNSPolicyManager()
            
            leak = manager.detect_dns_leak(
                url="https://example.com/page",
                use_tor=False,
                local_resolution_attempted=True,
            )
            
            assert leak == DNSLeakType.NONE

    def test_no_leak_when_detection_disabled(self, mock_settings):
        """No leak should be detected when detection is disabled."""
        mock_settings.tor.dns.leak_detection_enabled = False
        
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            manager = DNSPolicyManager()
            
            leak = manager.detect_dns_leak(
                url="https://example.com/page",
                use_tor=True,
                local_resolution_attempted=True,
            )
            
            assert leak == DNSLeakType.NONE


# =============================================================================
# DNSPolicyManager Tests - Utility Functions
# =============================================================================


class TestDNSPolicyManagerUtility:
    """Tests for utility functions."""

    def test_extract_hostname(self, mock_settings):
        """extract_hostname should correctly parse URL."""
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            manager = DNSPolicyManager()
            
            assert manager.extract_hostname("https://example.com/path") == "example.com"
            assert manager.extract_hostname("http://sub.example.org:8080/") == "sub.example.org"
            assert manager.extract_hostname("https://localhost:3000") == "localhost"

    def test_should_use_tor_dns(self, mock_settings):
        """should_use_tor_dns should return correct value."""
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            manager = DNSPolicyManager()
            
            # When using Tor and config says resolve through Tor
            assert manager.should_use_tor_dns(use_tor=True) is True
            
            # When not using Tor
            assert manager.should_use_tor_dns(use_tor=False) is False

    def test_should_use_tor_dns_respects_config(self, mock_settings):
        """should_use_tor_dns should respect configuration."""
        mock_settings.tor.dns.resolve_through_tor = False
        
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            manager = DNSPolicyManager()
            
            # Even when using Tor, if config says not to resolve through Tor
            assert manager.should_use_tor_dns(use_tor=True) is False


# =============================================================================
# Global Function Tests
# =============================================================================


class TestGlobalFunctions:
    """Tests for global convenience functions."""

    def test_get_dns_policy_manager_returns_singleton(self):
        """get_dns_policy_manager should return singleton instance."""
        # Reset global state
        import src.crawler.dns_policy as dns_module
        dns_module._dns_policy_manager = None
        
        manager1 = get_dns_policy_manager()
        manager2 = get_dns_policy_manager()
        
        assert manager1 is manager2

    @pytest.mark.asyncio
    async def test_get_socks_proxy_for_request(self, mock_settings):
        """get_socks_proxy_for_request should return proper proxy dict."""
        import src.crawler.dns_policy as dns_module
        dns_module._dns_policy_manager = None
        
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            proxy_dict = await get_socks_proxy_for_request(use_tor=True)
            
            assert proxy_dict is not None
            assert "http" in proxy_dict
            assert proxy_dict["http"].startswith("socks5h://")
            
            # Clean up
            dns_module._dns_policy_manager = None

    @pytest.mark.asyncio
    async def test_get_socks_proxy_for_request_none_when_not_using_tor(self, mock_settings):
        """get_socks_proxy_for_request should return None when not using Tor."""
        import src.crawler.dns_policy as dns_module
        dns_module._dns_policy_manager = None
        
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            proxy_dict = await get_socks_proxy_for_request(use_tor=False)
            
            assert proxy_dict is None
            
            # Clean up
            dns_module._dns_policy_manager = None


# =============================================================================
# Integration-style Tests
# =============================================================================


class TestDNSPolicyIntegration:
    """Integration-style tests for DNS policy."""

    @pytest.mark.asyncio
    async def test_full_resolution_flow_with_metrics(self, mock_settings):
        """Test full DNS resolution flow with metrics tracking."""
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            manager = DNSPolicyManager()
            
            # Initial state
            assert manager.metrics.total_resolutions == 0
            
            # First resolution (cache miss)
            result1 = await manager.resolve_hostname("localhost", DNSRoute.DIRECT)
            assert result1.success
            assert not result1.from_cache
            assert manager.metrics.cache_misses == 1
            
            # Second resolution (cache hit)
            result2 = await manager.resolve_hostname("localhost", DNSRoute.DIRECT)
            assert result2.success
            assert result2.from_cache
            assert manager.metrics.cache_hits == 1
            
            # Metrics should be accurate
            assert manager.metrics.total_resolutions == 2

    @pytest.mark.asyncio
    async def test_tor_route_prevents_local_resolution(self, mock_settings):
        """Test that Tor route prevents local DNS resolution."""
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            manager = DNSPolicyManager()
            
            # Attempting to resolve via Tor route should:
            # 1. Return empty addresses (don't actually resolve locally)
            # 2. Set leak detection flag
            # 3. Record the leak in metrics
            result = await manager.resolve_hostname("example.com", DNSRoute.TOR)
            
            assert result.addresses == []
            assert result.leak_detected == DNSLeakType.LOCAL_RESOLUTION_DURING_TOR
            assert manager.metrics.leaks_detected == 1

    def test_proxy_url_prevents_dns_leak(self, mock_settings):
        """Test that generated proxy URL uses socks5h:// to prevent DNS leaks."""
        with patch("src.crawler.dns_policy.get_settings", return_value=mock_settings):
            manager = DNSPolicyManager()
            
            # When using Tor with default settings, should use socks5h://
            proxy_url = manager.get_socks_proxy_url(use_tor=True)
            
            # socks5h:// ensures DNS is resolved through the SOCKS proxy
            # This is the key mechanism for preventing DNS leaks
            assert "socks5h://" in proxy_url, \
                "SOCKS proxy URL must use socks5h:// protocol to prevent DNS leaks"




