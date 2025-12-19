#!/usr/bin/env python3
"""
Debug script for Tor Daily Limit Flow (Problem 10).

This is a "straight-line" debug script per §debug-integration rule.
Verifies the Tor daily usage limit checking and tracking functionality.

Per §4.3 and §7:
- Global daily limit: 20% (max_usage_ratio)
- Domain-specific limits via domain policy
- Daily reset at midnight

Usage:
    python tests/scripts/debug_tor_daily_limit_flow.py
"""

import asyncio
import sys
from datetime import date
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, "/home/statuser/lyra")


async def main():
    """Run Tor daily limit verification."""
    print("=" * 60)
    print("Tor Daily Limit Flow Debug Script")
    print("=" * 60)

    # =========================================================================
    # 1. Test MetricsCollector Tor tracking
    # =========================================================================
    print("\n[1] Testing MetricsCollector Tor tracking...")

    from src.utils.metrics import MetricsCollector

    collector = MetricsCollector()

    # Check initial state
    print("  - Checking initial state...")
    metrics = collector.get_today_tor_metrics()
    assert metrics.total_requests == 0
    assert metrics.tor_requests == 0
    assert metrics.date == date.today().isoformat()
    print(f"    OK: total=0, tor=0, date={metrics.date}")

    # Record some requests
    print("  - Recording requests...")
    for _i in range(10):
        collector.record_request("example.com")
    for _i in range(2):
        collector.record_tor_usage("example.com")

    metrics = collector.get_today_tor_metrics()
    assert metrics.total_requests == 10
    assert metrics.tor_requests == 2
    assert metrics.usage_ratio == 0.2
    print(
        f"    OK: total={metrics.total_requests}, tor={metrics.tor_requests}, ratio={metrics.usage_ratio * 100:.1f}%"
    )

    # Check domain metrics
    print("  - Checking domain metrics...")
    domain_metrics = collector.get_domain_tor_metrics("example.com")
    assert domain_metrics.total_requests == 10
    assert domain_metrics.tor_requests == 2
    print(
        f"    OK: domain={domain_metrics.domain}, total={domain_metrics.total_requests}, tor={domain_metrics.tor_requests}"
    )

    print("[1] MetricsCollector Tor tracking: PASSED ✓")

    # =========================================================================
    # 2. Test _can_use_tor() function
    # =========================================================================
    print("\n[2] Testing _can_use_tor() function...")

    from src.crawler.fetcher import _can_use_tor

    # Test with fresh collector (0% usage)
    print("  - Testing with 0% usage...")
    fresh_collector = MetricsCollector()

    with patch("src.utils.metrics.get_metrics_collector", return_value=fresh_collector):
        result = await _can_use_tor()
        assert result is True
        print(f"    OK: _can_use_tor() returned {result} (0% < 20%)")

    # Test with 19% usage (below limit)
    print("  - Testing with 19% usage...")
    collector_19pct = MetricsCollector()
    collector_19pct._tor_daily_total_requests = 100
    collector_19pct._tor_daily_tor_requests = 19

    with patch("src.utils.metrics.get_metrics_collector", return_value=collector_19pct):
        result = await _can_use_tor()
        assert result is True
        print(f"    OK: _can_use_tor() returned {result} (19% < 20%)")

    # Test with 20% usage (at limit)
    print("  - Testing with 20% usage...")
    collector_20pct = MetricsCollector()
    collector_20pct._tor_daily_total_requests = 100
    collector_20pct._tor_daily_tor_requests = 20

    with patch("src.utils.metrics.get_metrics_collector", return_value=collector_20pct):
        result = await _can_use_tor()
        assert result is False
        print(f"    OK: _can_use_tor() returned {result} (20% >= 20%)")

    # Test with 25% usage (above limit)
    print("  - Testing with 25% usage...")
    collector_25pct = MetricsCollector()
    collector_25pct._tor_daily_total_requests = 100
    collector_25pct._tor_daily_tor_requests = 25

    with patch("src.utils.metrics.get_metrics_collector", return_value=collector_25pct):
        result = await _can_use_tor()
        assert result is False
        print(f"    OK: _can_use_tor() returned {result} (25% >= 20%)")

    print("[2] _can_use_tor() function: PASSED ✓")

    # =========================================================================
    # 3. Test domain-specific limits
    # =========================================================================
    print("\n[3] Testing domain-specific limits...")

    # Test domain with Tor blocked
    print("  - Testing domain with Tor blocked...")
    collector_ok = MetricsCollector()
    collector_ok._tor_daily_total_requests = 100
    collector_ok._tor_daily_tor_requests = 10  # 10% global

    mock_policy_blocked = MagicMock()
    mock_policy_blocked.tor_allowed = False
    mock_policy_blocked.tor_blocked = True

    with patch("src.utils.metrics.get_metrics_collector", return_value=collector_ok):
        with patch("src.utils.domain_policy.get_domain_policy", return_value=mock_policy_blocked):
            result = await _can_use_tor("cloudflare-site.com")
            assert result is False
            print(f"    OK: _can_use_tor('cloudflare-site.com') returned {result} (Tor blocked)")

    # Test domain with Tor allowed
    print("  - Testing domain with Tor allowed...")
    mock_policy_allowed = MagicMock()
    mock_policy_allowed.tor_allowed = True
    mock_policy_allowed.tor_blocked = False

    with patch("src.utils.metrics.get_metrics_collector", return_value=collector_ok):
        with patch("src.utils.domain_policy.get_domain_policy", return_value=mock_policy_allowed):
            result = await _can_use_tor("friendly-site.com")
            assert result is True
            print(f"    OK: _can_use_tor('friendly-site.com') returned {result} (Tor allowed)")

    print("[3] Domain-specific limits: PASSED ✓")

    # =========================================================================
    # 4. Test date reset
    # =========================================================================
    print("\n[4] Testing date reset...")

    old_collector = MetricsCollector()
    old_collector._tor_daily_date = "2025-01-01"  # Old date
    old_collector._tor_daily_total_requests = 1000
    old_collector._tor_daily_tor_requests = 500

    print(
        f"  - Before reset: date={old_collector._tor_daily_date}, total={old_collector._tor_daily_total_requests}"
    )

    # Getting metrics should trigger reset
    metrics = old_collector.get_today_tor_metrics()

    assert metrics.date == date.today().isoformat()
    assert metrics.total_requests == 0
    assert metrics.tor_requests == 0
    print(f"  - After reset: date={metrics.date}, total={metrics.total_requests}")
    print("    OK: Counters reset on date change")

    print("[4] Date reset: PASSED ✓")

    # =========================================================================
    # 5. Test fail-open behavior
    # =========================================================================
    print("\n[5] Testing fail-open behavior...")

    with patch("src.utils.metrics.get_metrics_collector", side_effect=Exception("Test error")):
        result = await _can_use_tor()
        assert result is True
        print(f"    OK: _can_use_tor() returned {result} on error (fail-open)")

    print("[5] Fail-open behavior: PASSED ✓")

    # =========================================================================
    # Summary
    # =========================================================================
    print("\n" + "=" * 60)
    print("All Tor Daily Limit Flow Tests PASSED ✓")
    print("=" * 60)
    print("\nKey findings:")
    print("  - MetricsCollector tracks global and domain Tor usage")
    print("  - _can_use_tor() checks 20% global limit")
    print("  - Domain policies (tor_allowed/tor_blocked) are respected")
    print("  - Daily counters reset at midnight")
    print("  - Fail-open behavior on errors")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
