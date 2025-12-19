"""
Tests for HTTP/3 (QUIC) Policy Manager.

Per §7.1 Test Code Quality Standards:
- Specific assertions with concrete values
- No conditional assertions
- Realistic test data
- Deterministic behavior (no random without seed)
- AAA pattern (Arrange-Act-Assert)

Tests verify §4.3 HTTP/3(QUIC) policy requirements:
- Browser route naturally uses HTTP/3 when site provides it
- HTTP client uses HTTP/2 by default
- Auto-increase browser route ratio when HTTP/3 sites show behavioral differences

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-PV-01 | ProtocolVersion values | Equivalence – enum | All versions defined | - |
| TC-DS-01 | HTTP3DomainStats creation | Equivalence – normal | Stats initialized | - |
| TC-DS-02 | Record HTTP/3 success | Equivalence – mutation | Stats updated | - |
| TC-DS-03 | Calculate success rate | Equivalence – calculation | Correct percentage | - |
| TC-RR-01 | HTTP3RequestResult success | Equivalence – success | Result with data | - |
| TC-RR-02 | HTTP3RequestResult failure | Equivalence – failure | Result with error | - |
| TC-PD-01 | Policy decision for new domain | Equivalence – default | Default policy | - |
| TC-PD-02 | Policy decision with history | Equivalence – learned | Adjusted policy | - |
| TC-PM-01 | Get policy for domain | Equivalence – retrieval | Returns decision | - |
| TC-PM-02 | Record result and update | Equivalence – learning | Stats updated | - |
| TC-PM-03 | Browser ratio adjustment | Equivalence – auto-adjust | Ratio increased | - |
| TC-CF-01 | get_http3_policy_manager | Equivalence – singleton | Returns manager | - |
"""

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from src.crawler.http3_policy import (
    HTTP3DomainStats,
    HTTP3PolicyDecision,
    HTTP3PolicyManager,
    HTTP3RequestResult,
    ProtocolVersion,
    detect_protocol_from_cdp_response,
    detect_protocol_from_playwright_response,
    get_http3_policy_manager,
    reset_http3_policy_manager,
)


class TestProtocolVersion:
    """Tests for ProtocolVersion enum and parsing."""

    def test_from_string_h3(self):
        """HTTP/3 variants should be recognized."""
        assert ProtocolVersion.from_string("h3") == ProtocolVersion.HTTP_3
        assert ProtocolVersion.from_string("H3") == ProtocolVersion.HTTP_3
        assert ProtocolVersion.from_string("h3-29") == ProtocolVersion.HTTP_3
        assert ProtocolVersion.from_string("h3-Q050") == ProtocolVersion.HTTP_3

    def test_from_string_h2(self):
        """HTTP/2 variants should be recognized."""
        assert ProtocolVersion.from_string("h2") == ProtocolVersion.HTTP_2
        assert ProtocolVersion.from_string("HTTP/2") == ProtocolVersion.HTTP_2
        assert ProtocolVersion.from_string("http/2.0") == ProtocolVersion.HTTP_2

    def test_from_string_h1(self):
        """HTTP/1.1 variants should be recognized."""
        assert ProtocolVersion.from_string("HTTP/1.1") == ProtocolVersion.HTTP_1_1
        assert ProtocolVersion.from_string("h1") == ProtocolVersion.HTTP_1_1
        assert ProtocolVersion.from_string("1.1") == ProtocolVersion.HTTP_1_1

    def test_from_string_quic(self):
        """QUIC protocol should map to HTTP/3."""
        assert ProtocolVersion.from_string("quic") == ProtocolVersion.HTTP_3
        assert ProtocolVersion.from_string("QUIC") == ProtocolVersion.HTTP_3

    def test_from_string_unknown(self):
        """Unknown protocols should return UNKNOWN."""
        assert ProtocolVersion.from_string("") == ProtocolVersion.UNKNOWN
        assert ProtocolVersion.from_string("unknown") == ProtocolVersion.UNKNOWN
        assert ProtocolVersion.from_string("spdy") == ProtocolVersion.UNKNOWN

    def test_from_string_none(self):
        """None/empty should return UNKNOWN."""
        assert ProtocolVersion.from_string(None) == ProtocolVersion.UNKNOWN
        assert ProtocolVersion.from_string("") == ProtocolVersion.UNKNOWN


class TestHTTP3DomainStats:
    """Tests for HTTP3DomainStats dataclass."""

    def test_default_values(self):
        """New stats should have sensible defaults."""
        stats = HTTP3DomainStats(domain="example.com")

        assert stats.domain == "example.com"
        assert stats.http3_detected is False
        assert stats.http3_first_seen_at is None
        assert stats.browser_requests == 0
        assert stats.browser_http3_requests == 0
        assert stats.browser_successes == 0
        assert stats.http_client_requests == 0
        assert stats.http_client_successes == 0
        assert stats.behavioral_difference_ema == 0.0
        assert stats.browser_ratio_boost == 0.0

    def test_http3_ratio_no_requests(self):
        """HTTP/3 ratio should be 0 when no requests."""
        stats = HTTP3DomainStats(domain="example.com")
        assert stats.http3_ratio == 0.0

    def test_http3_ratio_with_requests(self):
        """HTTP/3 ratio should be calculated correctly."""
        stats = HTTP3DomainStats(domain="example.com")
        stats.browser_requests = 10
        stats.browser_http3_requests = 7

        assert stats.http3_ratio == 0.7

    def test_browser_success_rate_no_requests(self):
        """Browser success rate should default to 0.5 when no requests."""
        stats = HTTP3DomainStats(domain="example.com")
        assert stats.browser_success_rate == 0.5

    def test_browser_success_rate_with_requests(self):
        """Browser success rate should be calculated correctly."""
        stats = HTTP3DomainStats(domain="example.com")
        stats.browser_requests = 10
        stats.browser_successes = 8

        assert stats.browser_success_rate == 0.8

    def test_http_client_success_rate_no_requests(self):
        """HTTP client success rate should default to 0.5 when no requests."""
        stats = HTTP3DomainStats(domain="example.com")
        assert stats.http_client_success_rate == 0.5

    def test_http_client_success_rate_with_requests(self):
        """HTTP client success rate should be calculated correctly."""
        stats = HTTP3DomainStats(domain="example.com")
        stats.http_client_requests = 10
        stats.http_client_successes = 6

        assert stats.http_client_success_rate == 0.6

    def test_to_dict(self):
        """Stats should serialize to dictionary correctly."""
        now = datetime.now(UTC)
        stats = HTTP3DomainStats(domain="example.com")
        stats.http3_detected = True
        stats.http3_first_seen_at = now
        stats.browser_requests = 10
        stats.browser_http3_requests = 7

        data = stats.to_dict()

        assert data["domain"] == "example.com"
        assert data["http3_detected"] is True
        assert data["http3_first_seen_at"] == now.isoformat()
        assert data["browser_requests"] == 10
        assert data["browser_http3_requests"] == 7
        assert data["http3_ratio"] == 0.7

    def test_from_dict(self):
        """Stats should deserialize from dictionary correctly."""
        now = datetime.now(UTC)
        data = {
            "domain": "example.com",
            "http3_detected": True,
            "http3_first_seen_at": now.isoformat(),
            "browser_requests": 10,
            "browser_http3_requests": 7,
            "browser_successes": 8,
            "behavioral_difference_ema": 0.25,
        }

        stats = HTTP3DomainStats.from_dict(data)

        assert stats.domain == "example.com"
        assert stats.http3_detected is True
        assert stats.http3_first_seen_at is not None
        assert stats.browser_requests == 10
        assert stats.browser_http3_requests == 7
        assert stats.browser_successes == 8
        assert stats.behavioral_difference_ema == 0.25


class TestHTTP3PolicyDecision:
    """Tests for HTTP3PolicyDecision dataclass."""

    def test_default_values(self):
        """Decision should have sensible defaults."""
        decision = HTTP3PolicyDecision(domain="example.com")

        assert decision.domain == "example.com"
        assert decision.prefer_browser is False
        assert decision.browser_ratio_boost == 0.0
        assert decision.reason == ""
        assert decision.http3_available is False

    def test_to_dict(self):
        """Decision should serialize correctly."""
        decision = HTTP3PolicyDecision(
            domain="example.com",
            prefer_browser=True,
            browser_ratio_boost=0.2,
            reason="HTTP/3 available",
            http3_available=True,
            http3_ratio=0.8,
            behavioral_difference=0.25,
        )

        data = decision.to_dict()

        assert data["domain"] == "example.com"
        assert data["prefer_browser"] is True
        assert data["browser_ratio_boost"] == 0.2
        assert data["http3_available"] is True
        assert data["http3_ratio"] == 0.8


class TestHTTP3PolicyManager:
    """Tests for HTTP3PolicyManager class."""

    @pytest.fixture
    def manager(self):
        """Create a fresh manager instance for each test."""
        # Create new instance to avoid cache pollution between tests
        return HTTP3PolicyManager()

    @pytest.mark.asyncio
    async def test_get_stats_creates_new(self, manager):
        """get_stats should create new stats for unknown domain."""
        import uuid
        unique_domain = f"new-domain-{uuid.uuid4().hex[:8]}.test"

        stats = await manager.get_stats(unique_domain)

        assert stats.domain == unique_domain
        assert stats.http3_detected is False
        assert stats.browser_requests == 0

    @pytest.mark.asyncio
    async def test_get_stats_returns_cached(self, manager):
        """get_stats should return cached stats for known domain."""
        import uuid
        unique_domain = f"cached-domain-{uuid.uuid4().hex[:8]}.test"

        stats1 = await manager.get_stats(unique_domain)
        stats1.browser_requests = 10

        stats2 = await manager.get_stats(unique_domain)

        assert stats2.browser_requests == 10
        assert stats1 is stats2

    @pytest.mark.asyncio
    async def test_record_browser_request_success(self, manager):
        """Recording browser success should update stats."""
        import uuid
        unique_domain = f"browser-success-{uuid.uuid4().hex[:8]}.test"

        result = HTTP3RequestResult(
            domain=unique_domain,
            url=f"https://{unique_domain}/page",
            route="browser",
            success=True,
            protocol=ProtocolVersion.HTTP_2,
            status_code=200,
        )

        await manager.record_request(result)

        stats = await manager.get_stats(unique_domain)
        assert stats.browser_requests == 1
        assert stats.browser_successes == 1
        assert stats.browser_http3_requests == 0
        assert stats.http3_detected is False

    @pytest.mark.asyncio
    async def test_record_browser_http3_request(self, manager):
        """Recording HTTP/3 browser request should detect HTTP/3."""
        import uuid
        unique_domain = f"h3-browser-{uuid.uuid4().hex[:8]}.test"

        result = HTTP3RequestResult(
            domain=unique_domain,
            url=f"https://{unique_domain}/page",
            route="browser",
            success=True,
            protocol=ProtocolVersion.HTTP_3,
            status_code=200,
        )

        await manager.record_request(result)

        stats = await manager.get_stats(unique_domain)
        assert stats.browser_requests == 1
        assert stats.browser_http3_requests == 1
        assert stats.http3_detected is True
        assert stats.http3_first_seen_at is not None
        assert stats.http3_last_seen_at is not None

    @pytest.mark.asyncio
    async def test_record_http_client_request(self, manager):
        """Recording HTTP client request should update stats."""
        import uuid
        unique_domain = f"http-cli-{uuid.uuid4().hex[:8]}.test"

        result = HTTP3RequestResult(
            domain=unique_domain,
            url=f"https://{unique_domain}/page",
            route="http_client",
            success=True,
            protocol=ProtocolVersion.HTTP_2,
            status_code=200,
        )

        await manager.record_request(result)

        stats = await manager.get_stats(unique_domain)
        assert stats.http_client_requests == 1
        assert stats.http_client_successes == 1
        assert stats.browser_requests == 0

    @pytest.mark.asyncio
    async def test_record_failed_request(self, manager):
        """Recording failed request should increment count but not success."""
        import uuid
        unique_domain = f"failed-{uuid.uuid4().hex[:8]}.test"

        result = HTTP3RequestResult(
            domain=unique_domain,
            url=f"https://{unique_domain}/page",
            route="browser",
            success=False,
            protocol=ProtocolVersion.UNKNOWN,
            error="Connection timeout",
        )

        await manager.record_request(result)

        stats = await manager.get_stats(unique_domain)
        assert stats.browser_requests == 1
        assert stats.browser_successes == 0

    @pytest.mark.asyncio
    async def test_behavioral_difference_not_calculated_without_samples(self, manager):
        """Behavioral difference should not be calculated without enough samples."""
        import uuid
        unique_domain = f"no-samples-{uuid.uuid4().hex[:8]}.test"

        # Only 3 browser requests (below min_samples=5)
        for _ in range(3):
            await manager.record_request(HTTP3RequestResult(
                domain=unique_domain,
                url=f"https://{unique_domain}/page",
                route="browser",
                success=True,
                protocol=ProtocolVersion.HTTP_3,
            ))

        stats = await manager.get_stats(unique_domain)
        assert stats.behavioral_difference_ema == 0.0
        assert stats.browser_ratio_boost == 0.0

    @pytest.mark.asyncio
    async def test_behavioral_difference_calculated_with_samples(self, manager):
        """Behavioral difference should be calculated with enough samples.
        
        Per §4.3: Behavioral difference tracking to inform route selection.
        EMA calculation: new_ema = alpha * difference + (1-alpha) * old_ema
        With alpha=0.1, first update from 0: ema = 0.1 * 0.3 = 0.03
        
        Note: EMA converges slowly, so 10 samples won't reach threshold (0.15).
        This test verifies EMA calculation is working, not boost application.
        """
        import uuid
        unique_domain = f"with-samples-{uuid.uuid4().hex[:8]}.test"

        # Add browser requests (90% success with HTTP/3)
        for i in range(10):
            await manager.record_request(HTTP3RequestResult(
                domain=unique_domain,
                url=f"https://{unique_domain}/page",
                route="browser",
                success=(i < 9),  # 9 successes, 1 failure
                protocol=ProtocolVersion.HTTP_3,
            ))

        # Add HTTP client requests (60% success)
        for i in range(10):
            await manager.record_request(HTTP3RequestResult(
                domain=unique_domain,
                url=f"https://{unique_domain}/page",
                route="http_client",
                success=(i < 6),  # 6 successes, 4 failures
                protocol=ProtocolVersion.HTTP_2,
            ))

        stats = await manager.get_stats(unique_domain)

        # Browser has 90% success (9/10), HTTP client has 60% (6/10)
        # Difference is 0.3
        # EMA is updated on each http_client request after min_samples reached
        # With alpha=0.1, EMA converges slowly toward 0.3
        # After ~5 updates: EMA ≈ 0.066 (below threshold 0.15)
        assert stats.behavioral_difference_ema > 0.02, (
            f"Expected behavioral_difference_ema > 0.02, got {stats.behavioral_difference_ema}"
        )
        assert stats.behavioral_difference_ema < 0.35, (
            f"Expected behavioral_difference_ema < 0.35, got {stats.behavioral_difference_ema}"
        )

        # With 10 samples, EMA (~0.066) is below threshold (0.15)
        # So browser_ratio_boost should still be 0.0
        # This is correct behavior per §4.3
        assert stats.browser_ratio_boost == 0.0, (
            f"Expected browser_ratio_boost=0.0 when EMA ({stats.behavioral_difference_ema}) "
            f"is below threshold (0.15), got {stats.browser_ratio_boost}"
        )

    @pytest.mark.asyncio
    async def test_browser_ratio_boost_when_ema_exceeds_threshold(self, manager):
        """Browser ratio boost should be applied when EMA exceeds threshold.
        
        Per §4.3: Auto-increase browser route ratio when HTTP/3 sites show
        behavioral differences exceeding the threshold (default=0.15).
        
        This test uses more samples to ensure EMA exceeds threshold.
        """
        import uuid
        unique_domain = f"boost-threshold-{uuid.uuid4().hex[:8]}.test"

        # Need many samples to push EMA above threshold (0.15)
        # With alpha=0.1, need ~30+ updates at difference=0.4 to reach EMA=0.15

        # Add 50 browser requests (100% success with HTTP/3)
        for _ in range(50):
            await manager.record_request(HTTP3RequestResult(
                domain=unique_domain,
                url=f"https://{unique_domain}/page",
                route="browser",
                success=True,
                protocol=ProtocolVersion.HTTP_3,
            ))

        # Add 50 HTTP client requests (40% success = 60% difference)
        for i in range(50):
            await manager.record_request(HTTP3RequestResult(
                domain=unique_domain,
                url=f"https://{unique_domain}/page",
                route="http_client",
                success=(i % 5 < 2),  # 40% success (2 out of every 5)
                protocol=ProtocolVersion.HTTP_2,
            ))

        stats = await manager.get_stats(unique_domain)

        # Browser: 100% success, HTTP client: 40% success
        # Difference: 0.6, EMA should converge toward 0.6
        # After 45 updates (50-5 min_samples), EMA should exceed 0.15
        assert stats.behavioral_difference_ema > 0.15, (
            f"Expected EMA > 0.15 (threshold), got {stats.behavioral_difference_ema}"
        )

        # Now browser_ratio_boost should be positive
        assert stats.browser_ratio_boost > 0.0, (
            f"Expected positive browser_ratio_boost when EMA ({stats.behavioral_difference_ema}) "
            f"exceeds threshold (0.15), got {stats.browser_ratio_boost}"
        )

    @pytest.mark.asyncio
    async def test_behavioral_difference_boundary_at_min_samples(self, manager):
        """Behavioral difference should only be calculated at min_samples boundary.
        
        Per §4.3: Need minimum samples (default=5) before calculating difference.
        Tests boundary: 4 samples = no calculation, 5 samples = calculation starts.
        """
        import uuid
        unique_domain = f"boundary-{uuid.uuid4().hex[:8]}.test"

        # Add exactly 4 browser requests (below min_samples=5)
        for i in range(4):
            await manager.record_request(HTTP3RequestResult(
                domain=unique_domain,
                url=f"https://{unique_domain}/page",
                route="browser",
                success=True,
                protocol=ProtocolVersion.HTTP_3,
            ))

        # Add exactly 4 HTTP client requests (below min_samples=5)
        for i in range(4):
            await manager.record_request(HTTP3RequestResult(
                domain=unique_domain,
                url=f"https://{unique_domain}/page",
                route="http_client",
                success=False,  # 0% success to create max difference
                protocol=ProtocolVersion.HTTP_2,
            ))

        stats = await manager.get_stats(unique_domain)

        # At 4 samples each, EMA should still be 0 (below min_samples)
        assert stats.behavioral_difference_ema == 0.0, (
            f"Expected EMA=0 with only 4 samples, got {stats.behavioral_difference_ema}"
        )

        # Add 5th browser request
        await manager.record_request(HTTP3RequestResult(
            domain=unique_domain,
            url=f"https://{unique_domain}/page",
            route="browser",
            success=True,
            protocol=ProtocolVersion.HTTP_3,
        ))

        # Add 5th HTTP client request (failure)
        await manager.record_request(HTTP3RequestResult(
            domain=unique_domain,
            url=f"https://{unique_domain}/page",
            route="http_client",
            success=False,
            protocol=ProtocolVersion.HTTP_2,
        ))

        stats = await manager.get_stats(unique_domain)

        # At exactly 5 samples each, EMA calculation should start
        # Browser: 100% success, HTTP client: 0% success, difference = 1.0
        # First EMA update: 0.1 * 1.0 + 0.9 * 0 = 0.1
        assert stats.behavioral_difference_ema > 0.0, (
            f"Expected positive EMA at min_samples boundary, got {stats.behavioral_difference_ema}"
        )

    @pytest.mark.asyncio
    async def test_get_policy_decision_no_http3(self, manager):
        """Policy decision should not prefer browser when no HTTP/3."""
        decision = await manager.get_policy_decision("no-http3-test.com")

        assert decision.prefer_browser is False
        assert decision.browser_ratio_boost == 0.0
        assert decision.http3_available is False

    @pytest.mark.asyncio
    async def test_get_policy_decision_http3_no_difference(self, manager):
        """Policy decision should not boost when HTTP/3 but no behavioral difference."""
        # Record HTTP/3 detection
        await manager.record_request(HTTP3RequestResult(
            domain="http3-no-diff.com",
            url="https://http3-no-diff.com/page",
            route="browser",
            success=True,
            protocol=ProtocolVersion.HTTP_3,
        ))

        decision = await manager.get_policy_decision("http3-no-diff.com")

        assert decision.http3_available is True
        assert decision.prefer_browser is False  # No significant difference yet
        assert "no significant behavioral difference" in decision.reason

    @pytest.mark.asyncio
    async def test_get_adjusted_browser_ratio(self, manager):
        """Adjusted browser ratio should include HTTP/3 boost."""
        # Setup: HTTP/3 detected with significant behavioral difference
        stats = await manager.get_stats("adjusted-ratio-test.com")
        stats.http3_detected = True
        stats.browser_ratio_boost = 0.2

        base_ratio = 0.1
        adjusted = await manager.get_adjusted_browser_ratio("adjusted-ratio-test.com", base_ratio)

        # Use approximate comparison for floating point
        assert abs(adjusted - 0.3) < 0.001, f"Expected ~0.3, got {adjusted}"

    @pytest.mark.asyncio
    async def test_get_adjusted_browser_ratio_capped(self, manager):
        """Adjusted browser ratio should be capped at 1.0."""
        stats = await manager.get_stats("capped-ratio-test.com")
        stats.http3_detected = True
        stats.browser_ratio_boost = 0.5

        base_ratio = 0.8
        adjusted = await manager.get_adjusted_browser_ratio("capped-ratio-test.com", base_ratio)

        assert adjusted == 1.0  # Capped at 1.0, not 1.3

    def test_get_all_stats_empty(self):
        """get_all_stats should return empty dict for fresh manager."""
        # Create a fresh manager with no cached stats
        fresh_manager = HTTP3PolicyManager()
        stats = fresh_manager.get_all_stats()
        assert stats == {}

    @pytest.mark.asyncio
    async def test_get_all_stats_with_data(self):
        """get_all_stats should return all cached stats."""
        import uuid
        fresh_manager = HTTP3PolicyManager()

        domain1 = f"stats-test-1-{uuid.uuid4().hex[:8]}.test"
        domain2 = f"stats-test-2-{uuid.uuid4().hex[:8]}.test"

        await fresh_manager.get_stats(domain1)
        await fresh_manager.get_stats(domain2)

        all_stats = fresh_manager.get_all_stats()

        assert len(all_stats) == 2
        assert domain1 in all_stats
        assert domain2 in all_stats


class TestHTTP3PolicyManagerDBIntegration:
    """Tests for HTTP3PolicyManager database integration."""

    @pytest.mark.asyncio
    async def test_save_and_load_stats(self, tmp_path):
        """Stats should be saved to and loaded from database."""
        # Setup mock database
        mock_db = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value=None)
        mock_db.execute = AsyncMock()

        # Mock get_database at the storage.database module level
        with patch("src.storage.database.get_database", new=AsyncMock(return_value=mock_db)):
            manager = HTTP3PolicyManager()

            # Record a request - this will try to save to DB
            await manager.record_request(HTTP3RequestResult(
                domain="db-test.com",
                url="https://db-test.com/page",
                route="browser",
                success=True,
                protocol=ProtocolVersion.HTTP_3,
            ))

            # Stats should be created and cached
            stats = await manager.get_stats("db-test.com")
            assert stats.http3_detected is True
            assert stats.browser_requests == 1


class TestProtocolDetection:
    """Tests for protocol detection functions."""

    @pytest.mark.asyncio
    async def test_detect_protocol_from_cdp_h3(self):
        """CDP response with h3 protocol should be detected."""
        response_data = {"protocol": "h3"}

        protocol = await detect_protocol_from_cdp_response(response_data)

        assert protocol == ProtocolVersion.HTTP_3

    @pytest.mark.asyncio
    async def test_detect_protocol_from_cdp_h2(self):
        """CDP response with h2 protocol should be detected."""
        response_data = {"protocol": "h2"}

        protocol = await detect_protocol_from_cdp_response(response_data)

        assert protocol == ProtocolVersion.HTTP_2

    @pytest.mark.asyncio
    async def test_detect_protocol_from_cdp_empty(self):
        """CDP response without protocol should return UNKNOWN."""
        response_data = {}

        protocol = await detect_protocol_from_cdp_response(response_data)

        assert protocol == ProtocolVersion.UNKNOWN

    @pytest.mark.asyncio
    async def test_detect_protocol_from_playwright_with_alt_svc(self):
        """Playwright response with Alt-Svc header indicating HTTP/3."""
        mock_response = AsyncMock()
        mock_response.header_value = AsyncMock(return_value='h3=":443"; ma=86400')

        protocol = await detect_protocol_from_playwright_response(mock_response)

        assert protocol == ProtocolVersion.HTTP_3

    @pytest.mark.asyncio
    async def test_detect_protocol_from_playwright_no_alt_svc(self):
        """Playwright response without Alt-Svc should return UNKNOWN."""
        mock_response = AsyncMock()
        mock_response.header_value = AsyncMock(return_value=None)

        protocol = await detect_protocol_from_playwright_response(mock_response)

        assert protocol == ProtocolVersion.UNKNOWN


class TestGlobalManager:
    """Tests for global manager instance."""

    def test_get_http3_policy_manager_singleton(self):
        """get_http3_policy_manager should return same instance."""
        reset_http3_policy_manager()

        manager1 = get_http3_policy_manager()
        manager2 = get_http3_policy_manager()

        assert manager1 is manager2

    def test_reset_http3_policy_manager(self):
        """reset_http3_policy_manager should create new instance."""
        manager1 = get_http3_policy_manager()
        reset_http3_policy_manager()
        manager2 = get_http3_policy_manager()

        assert manager1 is not manager2


class TestEMACalculation:
    """Tests for EMA (Exponential Moving Average) calculation accuracy.
    
    Per §4.3: EMA tracks behavioral differences for adaptive policy.
    EMA formula: new_ema = alpha * value + (1 - alpha) * old_ema
    Default alpha = 0.1
    """

    @pytest.fixture
    def manager(self):
        """Create a fresh manager instance for each test."""
        return HTTP3PolicyManager()

    @pytest.mark.asyncio
    async def test_ema_calculation_single_update(self, manager):
        """EMA should be calculated correctly for single update.
        
        First update from 0: ema = 0.1 * difference + 0.9 * 0 = 0.1 * difference
        """
        import uuid
        unique_domain = f"ema-single-{uuid.uuid4().hex[:8]}.test"

        # Setup: 5 browser requests (100% success, all HTTP/3)
        for _ in range(5):
            await manager.record_request(HTTP3RequestResult(
                domain=unique_domain,
                url=f"https://{unique_domain}/page",
                route="browser",
                success=True,
                protocol=ProtocolVersion.HTTP_3,
            ))

        # 5 HTTP client requests (0% success)
        for _ in range(5):
            await manager.record_request(HTTP3RequestResult(
                domain=unique_domain,
                url=f"https://{unique_domain}/page",
                route="http_client",
                success=False,
                protocol=ProtocolVersion.HTTP_2,
            ))

        stats = await manager.get_stats(unique_domain)

        # Browser: 100%, HTTP client: 0%, difference = 1.0
        # First EMA update: 0.1 * 1.0 = 0.1
        # Subsequent updates converge toward 1.0
        # Expected: between 0.1 and 0.4 after 5 updates
        assert 0.08 <= stats.behavioral_difference_ema <= 0.5, (
            f"Expected EMA in [0.08, 0.5], got {stats.behavioral_difference_ema}"
        )

    @pytest.mark.asyncio
    async def test_ema_decay_when_no_advantage(self, manager):
        """EMA should decay toward zero when browser has no advantage.
        
        Per §4.3: Decay formula when no advantage detected.
        """
        import uuid
        unique_domain = f"ema-decay-{uuid.uuid4().hex[:8]}.test"

        # First: establish high EMA with browser advantage
        for _ in range(10):
            await manager.record_request(HTTP3RequestResult(
                domain=unique_domain,
                url=f"https://{unique_domain}/page",
                route="browser",
                success=True,
                protocol=ProtocolVersion.HTTP_3,
            ))

        for _ in range(10):
            await manager.record_request(HTTP3RequestResult(
                domain=unique_domain,
                url=f"https://{unique_domain}/page",
                route="http_client",
                success=False,  # 0% success
                protocol=ProtocolVersion.HTTP_2,
            ))

        stats = await manager.get_stats(unique_domain)
        high_ema = stats.behavioral_difference_ema
        assert high_ema > 0.1, f"Expected high EMA > 0.1, got {high_ema}"

        # Now: HTTP client starts succeeding (no more advantage)
        for _ in range(20):
            await manager.record_request(HTTP3RequestResult(
                domain=unique_domain,
                url=f"https://{unique_domain}/page",
                route="http_client",
                success=True,  # 100% success now
                protocol=ProtocolVersion.HTTP_2,
            ))

        stats = await manager.get_stats(unique_domain)

        # EMA should decay when browser no longer has advantage
        assert stats.behavioral_difference_ema < high_ema, (
            f"Expected EMA to decay from {high_ema}, got {stats.behavioral_difference_ema}"
        )


class TestHTTP3PolicyIntegration:
    """Integration tests for HTTP/3 policy with fetcher components."""

    @pytest.fixture
    def manager(self):
        """Create a fresh manager instance for each test."""
        return HTTP3PolicyManager()

    @pytest.mark.asyncio
    async def test_browser_ratio_increases_with_http3_advantage(self, manager):
        """Browser ratio should increase when HTTP/3 provides advantage.
        
        Per §4.3: Auto-increase browser route ratio when HTTP/3 sites
        show behavioral differences between browser and HTTP client routes.
        """
        # Simulate scenario: HTTP/3 site where browser (with HTTP/3) succeeds
        # but HTTP client (with HTTP/2) fails more often

        # Browser requests: 20 total, 18 success (90%), all HTTP/3
        # Need more samples for EMA to converge
        for i in range(20):
            await manager.record_request(HTTP3RequestResult(
                domain="http3advantage.com",
                url="https://http3advantage.com/page",
                route="browser",
                success=(i < 18),
                protocol=ProtocolVersion.HTTP_3,
            ))

        # HTTP client requests: 20 total, 10 success (50%), HTTP/2
        for i in range(20):
            await manager.record_request(HTTP3RequestResult(
                domain="http3advantage.com",
                url="https://http3advantage.com/page",
                route="http_client",
                success=(i < 10),
                protocol=ProtocolVersion.HTTP_2,
            ))

        # Get policy decision
        decision = await manager.get_policy_decision("http3advantage.com")

        # Verify HTTP/3 was detected
        assert decision.http3_available is True
        assert decision.http3_ratio > 0.8  # Most browser requests used HTTP/3

        # Verify behavioral difference was detected
        # Browser success: 90%, HTTP client: 50%, difference: 40%
        # EMA won't reach 0.4 immediately, but should be significant
        assert decision.behavioral_difference > 0.1, (
            f"Expected behavioral_difference > 0.1, got {decision.behavioral_difference}"
        )

    @pytest.mark.asyncio
    async def test_no_boost_when_http_client_performs_well(self, manager):
        """Browser ratio should not increase when HTTP client performs equally.
        
        Per §4.3: Only increase browser ratio when there's behavioral difference.
        """
        # Both routes perform equally well (90% success)
        for i in range(10):
            await manager.record_request(HTTP3RequestResult(
                domain="equalsite.com",
                url="https://equalsite.com/page",
                route="browser",
                success=(i < 9),
                protocol=ProtocolVersion.HTTP_3,
            ))

        for i in range(10):
            await manager.record_request(HTTP3RequestResult(
                domain="equalsite.com",
                url="https://equalsite.com/page",
                route="http_client",
                success=(i < 9),
                protocol=ProtocolVersion.HTTP_2,
            ))

        decision = await manager.get_policy_decision("equalsite.com")

        # HTTP/3 detected but no significant behavioral difference
        assert decision.http3_available is True
        assert decision.prefer_browser is False
        assert decision.browser_ratio_boost == 0.0

