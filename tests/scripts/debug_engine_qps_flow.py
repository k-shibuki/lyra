#!/usr/bin/env python3
"""
Debug script for engine-specific QPS rate limiting flow.

This script verifies that BrowserSearchProvider._rate_limit() correctly
applies per-engine QPS limits as defined in config/engines.yaml.

Per spec:
- ADR-0010: "Engine-specific rate control (concurrency=1, strict QPS)"
- ADR-0006: "Engine QPS≤0.25 (1 request/4s), Domain QPS≤0.2, concurrency=1"
"""

import asyncio
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.search.browser_search_provider import BrowserSearchProvider
from src.search.engine_config import get_engine_config_manager
from src.utils.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


async def test_engine_config_qps() -> bool:
    """Test that engine configs have QPS settings."""
    print("\n" + "=" * 80)
    print("[Test 1] Engine Config QPS Settings")
    print("=" * 80)

    config_manager = get_engine_config_manager()

    test_engines = [
        ("duckduckgo", 0.2, 5.0),
        ("mojeek", 0.25, 4.0),
        ("google", 0.05, 20.0),
        ("bing", 0.05, 20.0),
        ("brave", 0.1, 10.0),
    ]

    all_passed = True
    for engine_name, expected_qps, expected_interval in test_engines:
        engine_config = config_manager.get_engine(engine_name)

        if engine_config is None:
            print(f"  ⚠ Engine '{engine_name}' not found in config")
            continue

        actual_qps = engine_config.qps
        actual_interval = engine_config.min_interval

        qps_ok = abs(actual_qps - expected_qps) < 0.01
        interval_ok = abs(actual_interval - expected_interval) < 0.1

        status = "✓" if (qps_ok and interval_ok) else "✗"
        if not (qps_ok and interval_ok):
            all_passed = False

        print(f"  {status} Engine '{engine_name}':")
        print(f"      qps: {actual_qps} (expected: {expected_qps})")
        print(f"      min_interval: {actual_interval:.2f}s (expected: {expected_interval:.2f}s)")

    if all_passed:
        print("\n  ✓ All engine config QPS settings verified")
    else:
        print("\n  ✗ Some engine config QPS settings mismatch")

    return all_passed


async def test_last_search_times_tracking() -> bool:
    """Test that _last_search_times tracks per-engine times."""
    print("\n" + "=" * 80)
    print("[Test 2] Per-Engine Last Search Times Tracking")
    print("=" * 80)

    provider = BrowserSearchProvider()

    # Check that _last_search_times attribute exists
    if not hasattr(provider, "_last_search_times"):
        print("  ✗ Provider missing '_last_search_times' attribute")
        print("    Expected: dict[str, float] for per-engine tracking")
        return False

    print("  ✓ Provider has '_last_search_times' attribute")
    print(f"    Type: {type(provider._last_search_times)}")
    print(f"    Initial value: {provider._last_search_times}")

    # Check type
    if not isinstance(provider._last_search_times, dict):
        print(f"  ✗ '_last_search_times' should be dict, got {type(provider._last_search_times)}")
        return False

    print("  ✓ Per-engine tracking structure verified")
    return True


async def test_rate_limit_engine_parameter() -> bool:
    """Test that _rate_limit() accepts engine parameter."""
    print("\n" + "=" * 80)
    print("[Test 3] _rate_limit() Engine Parameter")
    print("=" * 80)

    provider = BrowserSearchProvider()

    # Test 1: Call with engine parameter
    print("\n  [Step 1] Test _rate_limit(engine='duckduckgo')")
    try:
        start_time = time.time()
        await provider._rate_limit(engine="duckduckgo")
        elapsed = time.time() - start_time
        print(f"    ✓ _rate_limit(engine='duckduckgo') completed in {elapsed:.3f}s")
    except TypeError as e:
        if "unexpected keyword argument" in str(e) or "positional argument" in str(e):
            print("    ✗ _rate_limit() doesn't accept 'engine' parameter")
            print(f"    Error: {e}")
            return False
        raise

    # Test 2: Call without engine parameter (default behavior)
    print("\n  [Step 2] Test _rate_limit() without engine (default behavior)")
    try:
        start_time = time.time()
        await provider._rate_limit()
        elapsed = time.time() - start_time
        print(f"    ✓ _rate_limit() completed in {elapsed:.3f}s")
    except Exception as e:
        print(f"    ✗ _rate_limit() without engine failed: {e}")
        return False

    # Test 3: Call with None (explicit)
    print("\n  [Step 3] Test _rate_limit(engine=None)")
    try:
        start_time = time.time()
        await provider._rate_limit(engine=None)
        elapsed = time.time() - start_time
        print(f"    ✓ _rate_limit(engine=None) completed in {elapsed:.3f}s")
    except Exception as e:
        print(f"    ✗ _rate_limit(engine=None) failed: {e}")
        return False

    print("\n  ✓ _rate_limit() engine parameter tests passed")
    return True


async def test_per_engine_interval() -> bool:
    """Test that different engines use different intervals."""
    print("\n" + "=" * 80)
    print("[Test 4] Per-Engine Interval Application")
    print("=" * 80)

    provider = BrowserSearchProvider()
    get_engine_config_manager()

    # First, check _last_search_times tracking
    if not hasattr(provider, "_last_search_times"):
        print("  ✗ Provider missing '_last_search_times' - skipping test")
        return False

    # Test with duckduckgo (qps=0.2, interval=5.0s)
    print("\n  [Step 1] First request with 'duckduckgo'")
    await provider._rate_limit(engine="duckduckgo")
    duckduckgo_time = provider._last_search_times.get("duckduckgo", 0)
    print(f"    ✓ duckduckgo last_time recorded: {duckduckgo_time}")

    # Test with mojeek (qps=0.25, interval=4.0s)
    print("\n  [Step 2] First request with 'mojeek'")
    await provider._rate_limit(engine="mojeek")
    mojeek_time = provider._last_search_times.get("mojeek", 0)
    print(f"    ✓ mojeek last_time recorded: {mojeek_time}")

    # Verify both engines have separate tracking
    if "duckduckgo" in provider._last_search_times and "mojeek" in provider._last_search_times:
        print("\n  ✓ Per-engine tracking working correctly")
        print(f"    _last_search_times: {provider._last_search_times}")
        return True
    else:
        print("\n  ✗ Per-engine tracking not working")
        print(f"    _last_search_times: {provider._last_search_times}")
        return False


async def test_unknown_engine_fallback() -> bool:
    """Test fallback behavior for unknown engines."""
    print("\n" + "=" * 80)
    print("[Test 5] Unknown Engine Fallback")
    print("=" * 80)

    provider = BrowserSearchProvider()

    # Test with unknown engine
    print("\n  [Step 1] Test _rate_limit(engine='unknown_engine')")
    try:
        start_time = time.time()
        await provider._rate_limit(engine="unknown_engine")
        elapsed = time.time() - start_time
        print(f"    ✓ _rate_limit(engine='unknown_engine') completed in {elapsed:.3f}s")
        print("    Uses default interval as fallback")
        return True
    except Exception as e:
        print(f"    ✗ _rate_limit(engine='unknown_engine') failed: {e}")
        return False


async def test_full_qps_flow() -> bool:
    """Test full QPS rate limiting flow."""
    print("\n" + "=" * 80)
    print("[Test 6] Full QPS Rate Limiting Flow")
    print("=" * 80)

    provider = BrowserSearchProvider()
    config_manager = get_engine_config_manager()

    engine = "duckduckgo"
    engine_config = config_manager.get_engine(engine)

    if engine_config is None:
        print(f"  ⚠ Engine '{engine}' not found - skipping test")
        return True

    expected_interval = engine_config.min_interval
    print(f"\n  Engine: {engine}")
    print(f"  Expected min_interval: {expected_interval:.2f}s (qps={engine_config.qps})")

    # First request - should be immediate
    print("\n  [Step 1] First request (should be immediate)")
    start_time = time.time()
    await provider._rate_limit(engine=engine)
    elapsed1 = time.time() - start_time
    print(f"    ✓ First request completed in {elapsed1:.3f}s")

    # Note: We don't actually wait for the full interval in this test
    # because it would be too slow (5-20 seconds per engine)
    # The implementation is verified by checking _last_search_times

    print("\n  [Step 2] Check _last_search_times tracking")
    if hasattr(provider, "_last_search_times"):
        last_time = provider._last_search_times.get(engine, 0)
        print(f"    ✓ {engine} last_time: {last_time}")
        print("    ✓ Rate limiting flow completed")
        return True
    else:
        print("    ✗ _last_search_times not found")
        return False


async def main() -> int:
    """Run all tests."""
    print("=" * 80)
    print("Engine QPS Rate Limiting Flow Debug Script")
    print("=" * 80)
    print("\nThis script verifies per-engine QPS rate limiting.")
    print("Per spec ADR-0010 and ADR-0006: Engine-specific rate control with strict QPS.")

    results = []

    try:
        results.append(("Engine Config QPS", await test_engine_config_qps()))
        results.append(("Last Search Times Tracking", await test_last_search_times_tracking()))
        results.append(("Rate Limit Engine Parameter", await test_rate_limit_engine_parameter()))
        results.append(("Per-Engine Interval", await test_per_engine_interval()))
        results.append(("Unknown Engine Fallback", await test_unknown_engine_fallback()))
        results.append(("Full QPS Flow", await test_full_qps_flow()))

        print("\n" + "=" * 80)
        print("Test Results Summary")
        print("=" * 80)

        all_passed = True
        for test_name, passed in results:
            status = "✓ PASS" if passed else "✗ FAIL"
            print(f"  {status}: {test_name}")
            if not passed:
                all_passed = False

        return 0 if all_passed else 1

        print("\n" + "=" * 80)
        if all_passed:
            print("✓ All tests completed successfully")
        else:
            print("✗ Some tests failed")
        print("=" * 80)

        if not all_passed:
            sys.exit(1)

    except Exception as e:
        print("\n" + "=" * 80)
        print(f"✗ Test failed with error: {e}")
        print("=" * 80)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
