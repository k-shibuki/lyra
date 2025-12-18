"""
Unit tests for Tor Daily Usage Limit (Problem 10).

Tests the Tor daily usage limit functionality per §4.3 and §7:
- Global daily limit (20%)
- Domain-specific limits
- Metrics tracking and reset

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-TOR-N-01 | 0% usage | Equivalence – normal | _can_use_tor() returns True | Fresh start |
| TC-TOR-N-02 | 19% usage | Boundary – below limit | _can_use_tor() returns True | Just under |
| TC-TOR-B-01 | 20% usage | Boundary – at limit | _can_use_tor() returns False | Exact limit |
| TC-TOR-B-02 | 21% usage | Boundary – above limit | _can_use_tor() returns False | Over limit |
| TC-TOR-N-03 | Domain limit exceeded | Equivalence – domain | _can_use_tor(domain) returns False | Domain check |
| TC-TOR-N-04 | New day reset | Equivalence – reset | Metrics reset to 0 | Date change |
| TC-TOR-A-01 | Metrics retrieval fails | Equivalence – error | _can_use_tor() returns True | Fail-open |
| TC-TOR-N-05 | First request of day | Boundary – 0 requests | _can_use_tor() returns True | No requests yet |
| TC-TOR-N-06 | record_request increments | Equivalence – normal | total_requests += 1 | Counter update |
| TC-TOR-N-07 | record_tor_usage increments | Equivalence – normal | tor_requests += 1 | Counter update |
| TC-TOR-N-08 | Domain metrics tracking | Equivalence – domain | Domain counters updated | Per-domain |
"""

import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit


# =============================================================================
# TorUsageMetrics Tests
# =============================================================================

class TestTorUsageMetrics:
    """Tests for TorUsageMetrics Pydantic model."""

    def test_usage_ratio_zero_requests(self):
        """
        Usage ratio should be 0.0 when no requests have been made.

        // Given: TorUsageMetrics with 0 total requests
        // When: Accessing usage_ratio property
        // Then: Returns 0.0 (not division by zero)
        """
        from src.utils.schemas import TorUsageMetrics

        metrics = TorUsageMetrics(
            total_requests=0,
            tor_requests=0,
            date="2025-12-15",
        )

        assert metrics.usage_ratio == 0.0

    def test_usage_ratio_calculation(self):
        """
        Usage ratio should be correctly calculated.

        // Given: TorUsageMetrics with 100 total, 20 tor requests
        // When: Accessing usage_ratio property
        // Then: Returns 0.2 (20%)
        """
        from src.utils.schemas import TorUsageMetrics

        metrics = TorUsageMetrics(
            total_requests=100,
            tor_requests=20,
            date="2025-12-15",
        )

        assert metrics.usage_ratio == 0.2

    def test_validation_non_negative(self):
        """
        TorUsageMetrics should reject negative values.

        // Given: Negative request counts
        // When: Creating TorUsageMetrics
        // Then: ValidationError is raised
        """
        from pydantic import ValidationError
        from src.utils.schemas import TorUsageMetrics

        with pytest.raises(ValidationError):
            TorUsageMetrics(
                total_requests=-1,
                tor_requests=0,
                date="2025-12-15",
            )


# =============================================================================
# DomainTorMetrics Tests
# =============================================================================

class TestDomainTorMetrics:
    """Tests for DomainTorMetrics Pydantic model."""

    def test_domain_usage_ratio(self):
        """
        Domain usage ratio should be correctly calculated.

        // Given: DomainTorMetrics with 50 total, 10 tor requests
        // When: Accessing usage_ratio property
        // Then: Returns 0.2 (20%)
        """
        from src.utils.schemas import DomainTorMetrics

        metrics = DomainTorMetrics(
            domain="example.com",
            total_requests=50,
            tor_requests=10,
            date="2025-12-15",
        )

        assert metrics.usage_ratio == 0.2
        assert metrics.domain == "example.com"


# =============================================================================
# MetricsCollector Tor Tracking Tests
# =============================================================================

class TestMetricsCollectorTorTracking:
    """Tests for MetricsCollector Tor tracking methods."""

    @pytest.fixture
    def fresh_collector(self):
        """Create a fresh MetricsCollector for each test."""
        from src.utils.metrics import MetricsCollector
        return MetricsCollector()

    def test_get_today_tor_metrics_initial(self, fresh_collector):
        """
        Initial Tor metrics should have zero counts.

        // Given: Fresh MetricsCollector
        // When: Getting today's Tor metrics
        // Then: Both counts are 0
        """
        metrics = fresh_collector.get_today_tor_metrics()

        assert metrics.total_requests == 0
        assert metrics.tor_requests == 0
        assert metrics.date == date.today().isoformat()

    def test_record_request_increments_total(self, fresh_collector):
        """
        record_request should increment total_requests.

        // Given: Fresh MetricsCollector
        // When: Recording a request
        // Then: total_requests incremented by 1
        """
        fresh_collector.record_request("example.com")

        metrics = fresh_collector.get_today_tor_metrics()
        assert metrics.total_requests == 1
        assert metrics.tor_requests == 0

    def test_record_tor_usage_increments_tor(self, fresh_collector):
        """
        record_tor_usage should increment tor_requests.

        // Given: Fresh MetricsCollector
        // When: Recording a Tor usage
        // Then: tor_requests incremented by 1
        """
        fresh_collector.record_tor_usage("example.com")

        metrics = fresh_collector.get_today_tor_metrics()
        assert metrics.tor_requests == 1

    def test_domain_metrics_tracking(self, fresh_collector):
        """
        Domain-specific metrics should be tracked separately.

        // Given: Fresh MetricsCollector
        // When: Recording requests for different domains
        // Then: Each domain has separate counts
        """
        fresh_collector.record_request("example.com")
        fresh_collector.record_request("example.com")
        fresh_collector.record_tor_usage("example.com")
        fresh_collector.record_request("other.com")

        example_metrics = fresh_collector.get_domain_tor_metrics("example.com")
        other_metrics = fresh_collector.get_domain_tor_metrics("other.com")

        assert example_metrics.total_requests == 2
        assert example_metrics.tor_requests == 1
        assert other_metrics.total_requests == 1
        assert other_metrics.tor_requests == 0

    def test_domain_case_insensitive(self, fresh_collector):
        """
        Domain metrics should be case-insensitive.

        // Given: Fresh MetricsCollector
        // When: Recording with different case domains
        // Then: Same domain is used (lowercase)
        """
        fresh_collector.record_request("Example.COM")
        fresh_collector.record_request("example.com")

        metrics = fresh_collector.get_domain_tor_metrics("EXAMPLE.com")
        assert metrics.total_requests == 2
        assert metrics.domain == "example.com"

    def test_date_reset_on_new_day(self, fresh_collector):
        """
        Metrics should reset when date changes.

        // Given: Collector with old date
        // When: Getting metrics on new day
        // Then: Counters are reset to 0
        """
        # Set up old date
        fresh_collector._tor_daily_date = "2025-01-01"
        fresh_collector._tor_daily_total_requests = 100
        fresh_collector._tor_daily_tor_requests = 20

        # Get metrics (triggers date check)
        metrics = fresh_collector.get_today_tor_metrics()

        assert metrics.total_requests == 0
        assert metrics.tor_requests == 0
        assert metrics.date == date.today().isoformat()


# =============================================================================
# _can_use_tor() Tests
# =============================================================================

class TestCanUseTor:
    """Tests for _can_use_tor() function."""

    @pytest.mark.asyncio
    async def test_can_use_tor_zero_usage(self):
        """
        _can_use_tor should return True when no Tor has been used.

        // Given: 0% Tor usage
        // When: Calling _can_use_tor()
        // Then: Returns True
        """
        from src.crawler.fetcher import _can_use_tor
        from src.utils.metrics import MetricsCollector

        mock_collector = MetricsCollector()

        with patch('src.utils.metrics.get_metrics_collector', return_value=mock_collector):
            result = await _can_use_tor()

        assert result is True

    @pytest.mark.asyncio
    async def test_can_use_tor_below_limit(self):
        """
        _can_use_tor should return True when usage is below 20%.

        // Given: 19% Tor usage (19 tor / 100 total)
        // When: Calling _can_use_tor()
        // Then: Returns True
        """
        from src.crawler.fetcher import _can_use_tor
        from src.utils.metrics import MetricsCollector

        mock_collector = MetricsCollector()
        mock_collector._tor_daily_total_requests = 100
        mock_collector._tor_daily_tor_requests = 19

        with patch('src.utils.metrics.get_metrics_collector', return_value=mock_collector):
            result = await _can_use_tor()

        assert result is True

    @pytest.mark.asyncio
    async def test_can_use_tor_at_limit(self):
        """
        _can_use_tor should return False when usage is at 20%.

        // Given: 20% Tor usage (20 tor / 100 total)
        // When: Calling _can_use_tor()
        // Then: Returns False (limit reached)
        """
        from src.crawler.fetcher import _can_use_tor
        from src.utils.metrics import MetricsCollector

        mock_collector = MetricsCollector()
        mock_collector._tor_daily_total_requests = 100
        mock_collector._tor_daily_tor_requests = 20

        with patch('src.utils.metrics.get_metrics_collector', return_value=mock_collector):
            result = await _can_use_tor()

        assert result is False

    @pytest.mark.asyncio
    async def test_can_use_tor_above_limit(self):
        """
        _can_use_tor should return False when usage exceeds 20%.

        // Given: 25% Tor usage (25 tor / 100 total)
        // When: Calling _can_use_tor()
        // Then: Returns False
        """
        from src.crawler.fetcher import _can_use_tor
        from src.utils.metrics import MetricsCollector

        mock_collector = MetricsCollector()
        mock_collector._tor_daily_total_requests = 100
        mock_collector._tor_daily_tor_requests = 25

        with patch('src.utils.metrics.get_metrics_collector', return_value=mock_collector):
            result = await _can_use_tor()

        assert result is False

    @pytest.mark.asyncio
    async def test_can_use_tor_domain_blocked(self):
        """
        _can_use_tor should return False when domain has Tor blocked.

        // Given: Global OK but domain has tor_blocked=True
        // When: Calling _can_use_tor(domain)
        // Then: Returns False due to domain policy
        """
        from src.crawler.fetcher import _can_use_tor
        from src.utils.metrics import MetricsCollector

        mock_collector = MetricsCollector()
        # Global is OK (15%)
        mock_collector._tor_daily_total_requests = 100
        mock_collector._tor_daily_tor_requests = 15

        # Mock domain policy to have Tor blocked
        mock_policy = MagicMock()
        mock_policy.tor_allowed = False
        mock_policy.tor_blocked = True

        with patch('src.utils.metrics.get_metrics_collector', return_value=mock_collector):
            with patch('src.utils.domain_policy.get_domain_policy', return_value=mock_policy):
                result = await _can_use_tor("cloudflare-site.com")

        assert result is False

    @pytest.mark.asyncio
    async def test_can_use_tor_domain_usage_limit(self):
        """
        _can_use_tor should check domain-specific usage limit.

        // Given: Global OK but domain usage at limit
        // When: Calling _can_use_tor(domain)
        // Then: Returns False due to domain usage limit
        """
        from src.crawler.fetcher import _can_use_tor
        from src.utils.metrics import MetricsCollector

        mock_collector = MetricsCollector()
        # Global is OK (10%)
        mock_collector._tor_daily_total_requests = 100
        mock_collector._tor_daily_tor_requests = 10
        # Domain is at limit (20%)
        mock_collector._tor_domain_metrics["example.com"] = {"total": 100, "tor": 20}

        # Mock domain policy to allow Tor
        mock_policy = MagicMock()
        mock_policy.tor_allowed = True
        mock_policy.tor_blocked = False

        with patch('src.utils.metrics.get_metrics_collector', return_value=mock_collector):
            with patch('src.utils.domain_policy.get_domain_policy', return_value=mock_policy):
                result = await _can_use_tor("example.com")

        assert result is False

    @pytest.mark.asyncio
    async def test_can_use_tor_fail_open(self):
        """
        _can_use_tor should return True on error (fail-open).

        // Given: Exception during limit check
        // When: Calling _can_use_tor()
        // Then: Returns True (fail-open behavior)
        """
        from src.crawler.fetcher import _can_use_tor

        with patch('src.utils.metrics.get_metrics_collector', side_effect=Exception("test error")):
            result = await _can_use_tor()

        assert result is True

    @pytest.mark.asyncio
    async def test_can_use_tor_first_request(self):
        """
        _can_use_tor should return True for first request of day.

        // Given: No requests yet today
        // When: Calling _can_use_tor()
        // Then: Returns True
        """
        from src.crawler.fetcher import _can_use_tor
        from src.utils.metrics import MetricsCollector

        mock_collector = MetricsCollector()
        # Fresh collector has 0 requests

        with patch('src.utils.metrics.get_metrics_collector', return_value=mock_collector):
            result = await _can_use_tor()

        assert result is True


# =============================================================================
# Integration Tests
# =============================================================================

class TestTorLimitIntegration:
    """Integration tests for Tor daily limit."""

    @pytest.mark.asyncio
    async def test_can_use_tor_with_real_collector(self):
        """
        Full flow: _can_use_tor with real MetricsCollector.

        // Given: Real MetricsCollector with recorded requests
        // When: Checking Tor availability
        // Then: Correct result based on usage ratio
        """
        from src.crawler.fetcher import _can_use_tor
        from src.utils.metrics import MetricsCollector

        # Use a fresh collector for isolation
        collector = MetricsCollector()

        # Simulate 100 requests with 19 Tor (19% - under limit)
        # Note: record_request and record_tor_usage are separate counters
        for _ in range(100):
            collector.record_request("example.com")
        for _ in range(19):
            collector.record_tor_usage("example.com")

        # Mock domain policy to allow Tor
        mock_policy = MagicMock()
        mock_policy.tor_allowed = True
        mock_policy.tor_blocked = False

        with patch('src.utils.metrics.get_metrics_collector', return_value=collector):
            with patch('src.utils.domain_policy.get_domain_policy', return_value=mock_policy):
                # Should be allowed (19% < 20%)
                result = await _can_use_tor("example.com")
                assert result is True

                # Add one more Tor request to hit 20% (20/100 = 20%)
                collector.record_tor_usage("example.com")

                # Now should be blocked (20% >= 20%)
                result = await _can_use_tor("example.com")
                assert result is False

    def test_metrics_collector_global_singleton(self):
        """
        Global MetricsCollector maintains state across calls.

        // Given: Global MetricsCollector
        // When: Recording requests
        // Then: State persists
        """
        from src.utils.metrics import get_metrics_collector

        # Get the global collector
        collector1 = get_metrics_collector()
        initial_requests = collector1.get_today_tor_metrics().total_requests

        # Record a request
        collector1.record_request("test.com")

        # Get collector again - should be same instance
        collector2 = get_metrics_collector()

        # Should see the recorded request
        assert collector2.get_today_tor_metrics().total_requests == initial_requests + 1
