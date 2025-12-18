#!/usr/bin/env python3
"""
Debug script for Pydantic Migration verification.

This is a "straight-line" debug script per §debug-integration rule.
Verifies that Pydantic models work correctly after migration from dataclass.

Usage:
    python tests/scripts/debug_pydantic_migration.py
"""

import sys
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, "/home/statuser/lancet")


def main():
    """Run Pydantic migration verification."""
    print("=" * 60)
    print("Pydantic Migration Debug Script")
    print("=" * 60)

    # =========================================================================
    # 1. Test session_transfer.py models
    # =========================================================================
    print("\n[1] Testing session_transfer.py models...")

    from src.crawler.session_transfer import CookieData, SessionData, TransferResult
    from pydantic import ValidationError

    # Test CookieData creation
    print("  - Creating CookieData...")
    cookie = CookieData(
        name="session_id",
        value="abc123",
        domain="example.com",
        secure=True,
        http_only=True,
    )
    print(f"    OK: {cookie.name}={cookie.value}")

    # Test CookieData validation
    print("  - Testing CookieData validation...")
    try:
        CookieData()  # Missing required fields
        print("    FAIL: Should have raised ValidationError")
        sys.exit(1)
    except ValidationError as e:
        print(f"    OK: ValidationError raised ({len(e.errors())} errors)")

    # Test CookieData methods
    print("  - Testing CookieData methods...")
    assert not cookie.is_expired()
    assert cookie.matches_domain("example.com")
    assert not cookie.matches_domain("other.com")
    assert cookie.to_header_value() == "session_id=abc123"
    print("    OK: All methods work")

    # Test SessionData creation
    print("  - Creating SessionData...")
    session = SessionData(
        domain="example.com",
        cookies=[cookie],
        etag='"v1"',
        user_agent="TestBot/1.0",
    )
    print(f"    OK: domain={session.domain}, cookies={len(session.cookies)}")

    # Test SessionData serialization round-trip
    print("  - Testing SessionData serialization...")
    session_dict = session.to_dict()
    session2 = SessionData.from_dict(session_dict)
    assert session2.domain == session.domain
    assert len(session2.cookies) == len(session.cookies)
    print("    OK: Round-trip works")

    # Test TransferResult
    print("  - Creating TransferResult...")
    result_ok = TransferResult(ok=True, headers={"Cookie": "test=1"})
    result_fail = TransferResult(ok=False, reason="test_error")
    assert result_ok.ok is True
    assert result_fail.ok is False
    print("    OK: TransferResult works")

    print("[1] session_transfer.py models: PASSED ✓")

    # =========================================================================
    # 2. Test provider.py models
    # =========================================================================
    print("\n[2] Testing provider.py models...")

    from src.search.provider import (
        SearchResult, SearchResponse, SearchOptions, HealthStatus,
        SourceTag, HealthState,
    )

    # Test SearchResult
    print("  - Creating SearchResult...")
    search_result = SearchResult(
        title="Test Result",
        url="https://example.com/page",
        snippet="This is a test snippet.",
        engine="duckduckgo",
        rank=1,
        source_tag=SourceTag.NEWS,
    )
    assert search_result.rank >= 0
    print(f"    OK: {search_result.title[:30]}...")

    # Test SearchResult from_dict
    print("  - Testing SearchResult serialization...")
    result_dict = search_result.to_dict()
    result2 = SearchResult.from_dict(result_dict)
    assert result2.title == search_result.title
    assert result2.source_tag == SourceTag.NEWS
    print("    OK: Serialization works")

    # Test SearchResponse
    print("  - Creating SearchResponse...")
    search_response = SearchResponse(
        results=[search_result],
        query="test query",
        provider="browser_search",
        total_count=1,
    )
    assert search_response.ok is True  # No error
    print(f"    OK: {len(search_response.results)} results, ok={search_response.ok}")

    # Test SearchOptions
    print("  - Creating SearchOptions...")
    options = SearchOptions(
        engines=["duckduckgo", "mojeek"],
        language="ja",
        limit=10,
    )
    assert options.limit >= 1
    assert options.page >= 1
    print(f"    OK: engines={options.engines}, limit={options.limit}")

    # Test HealthStatus
    print("  - Creating HealthStatus...")
    health = HealthStatus.healthy(latency_ms=150.0)
    assert health.state == HealthState.HEALTHY
    assert health.success_rate == 1.0
    print(f"    OK: state={health.state.value}, latency={health.latency_ms}ms")

    # Test HealthStatus factory methods
    degraded = HealthStatus.degraded(success_rate=0.8, message="Some issues")
    unhealthy = HealthStatus.unhealthy(message="Service down")
    assert degraded.state == HealthState.DEGRADED
    assert unhealthy.state == HealthState.UNHEALTHY
    print("    OK: Factory methods work")

    print("[2] provider.py models: PASSED ✓")

    # =========================================================================
    # 3. Test schemas.py Tor models
    # =========================================================================
    print("\n[3] Testing schemas.py Tor models...")

    from src.utils.schemas import TorUsageMetrics, DomainTorMetrics

    # Test TorUsageMetrics
    print("  - Creating TorUsageMetrics...")
    tor_metrics = TorUsageMetrics(
        total_requests=100,
        tor_requests=15,
        date="2025-12-15",
    )
    assert tor_metrics.usage_ratio == 0.15
    print(f"    OK: ratio={tor_metrics.usage_ratio*100:.1f}%")

    # Test TorUsageMetrics with zero
    print("  - Testing zero division handling...")
    zero_metrics = TorUsageMetrics(
        total_requests=0,
        tor_requests=0,
        date="2025-12-15",
    )
    assert zero_metrics.usage_ratio == 0.0
    print("    OK: Zero handled correctly")

    # Test DomainTorMetrics
    print("  - Creating DomainTorMetrics...")
    domain_metrics = DomainTorMetrics(
        domain="example.com",
        total_requests=50,
        tor_requests=10,
        date="2025-12-15",
    )
    assert domain_metrics.usage_ratio == 0.2
    print(f"    OK: domain={domain_metrics.domain}, ratio={domain_metrics.usage_ratio*100:.1f}%")

    print("[3] schemas.py Tor models: PASSED ✓")

    # =========================================================================
    # Summary
    # =========================================================================
    print("\n" + "=" * 60)
    print("All Pydantic Migration Tests PASSED ✓")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
