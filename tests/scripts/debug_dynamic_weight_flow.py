#!/usr/bin/env python3
"""
Debug script for dynamic weight learning flow.

This script verifies that BrowserSearchProvider correctly uses dynamic weights
from PolicyEngine based on engine health metrics with time decay.

Per spec:
- §3.1.1: "Stratify by category and learn weights based on past accuracy/failure/block rates"
- §3.1.4: "Store EMA (1h/24h) in engine_health table, auto-adjust weights/QPS/exploration slots"
- §4.6: "Event-driven: immediate feedback after each request/query completion"
"""

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.search.engine_config import get_engine_config_manager
from src.utils.logging import configure_logging, get_logger
from src.utils.policy_engine import PolicyEngine, get_policy_engine
from src.utils.schemas import DynamicWeightResult, EngineHealthMetrics

configure_logging()
logger = get_logger(__name__)


async def test_calculate_dynamic_weight_basic():
    """Test basic dynamic weight calculation."""
    print("\n" + "=" * 80)
    print("[Test 1] Basic Dynamic Weight Calculation")
    print("=" * 80)

    policy_engine = PolicyEngine()

    # Test case 1: Ideal metrics - weight should be close to base
    print("\n  Test 1.1: Ideal metrics (recent use)")
    base_weight = 0.7
    recent_time = datetime.now(UTC) - timedelta(hours=1)

    weight, confidence = policy_engine.calculate_dynamic_weight(
        base_weight=base_weight,
        success_rate_1h=1.0,
        success_rate_24h=1.0,
        captcha_rate=0.0,
        median_latency_ms=500.0,
        last_used_at=recent_time,
    )

    print(f"    Base weight: {base_weight}")
    print(f"    Dynamic weight: {weight:.3f}")
    print(f"    Confidence: {confidence:.3f}")

    # Weight should be in valid range with high confidence
    # Note: latency factor (1/(1+500/1000)=0.667) reduces weight
    ideal_ok = 0.4 <= weight <= 1.0 and confidence > 0.9
    status = "✓" if ideal_ok else "✗"
    print(f"    {status} Weight in expected range (0.4-1.0, accounting for latency factor)")

    # Test case 2: Degraded metrics
    print("\n  Test 1.2: Degraded metrics (recent use)")
    weight_degraded, conf_degraded = policy_engine.calculate_dynamic_weight(
        base_weight=base_weight,
        success_rate_1h=0.5,
        success_rate_24h=0.6,
        captcha_rate=0.3,
        median_latency_ms=2000.0,
        last_used_at=recent_time,
    )

    print(f"    Base weight: {base_weight}")
    print(f"    Dynamic weight: {weight_degraded:.3f}")
    print(f"    Confidence: {conf_degraded:.3f}")

    # Weight should be reduced with bad metrics
    degraded_ok = weight_degraded < weight
    status = "✓" if degraded_ok else "✗"
    print(f"    {status} Degraded metrics reduce weight ({weight_degraded:.3f} < {weight:.3f})")

    return ideal_ok and degraded_ok


async def test_time_decay():
    """Test time decay for stale metrics."""
    print("\n" + "=" * 80)
    print("[Test 2] Time Decay for Stale Metrics")
    print("=" * 80)

    policy_engine = PolicyEngine()
    base_weight = 0.7

    # Bad metrics that would normally reduce weight
    bad_metrics = {
        "success_rate_1h": 0.3,
        "success_rate_24h": 0.4,
        "captcha_rate": 0.5,
        "median_latency_ms": 3000.0,
    }

    test_cases = [
        ("Recent (1h)", timedelta(hours=1), "high"),
        ("12h ago", timedelta(hours=12), "medium"),
        ("24h ago", timedelta(hours=24), "low"),
        ("48h ago", timedelta(hours=48), "very_low"),
        ("72h ago (>48h)", timedelta(hours=72), "very_low"),
        ("Never used", None, "very_low"),
    ]

    results = []
    all_passed = True

    for name, time_delta, expected_confidence in test_cases:
        if time_delta is not None:
            last_used = datetime.now(UTC) - time_delta
        else:
            last_used = None

        weight, confidence = policy_engine.calculate_dynamic_weight(
            base_weight=base_weight,
            last_used_at=last_used,
            **bad_metrics,
        )

        results.append((name, weight, confidence))

        # Check confidence levels
        if expected_confidence == "high":
            conf_ok = confidence > 0.8
        elif expected_confidence == "medium":
            conf_ok = 0.5 <= confidence <= 0.8
        elif expected_confidence == "low":
            conf_ok = 0.3 <= confidence <= 0.6
        else:  # very_low
            conf_ok = confidence <= 0.3

        status = "✓" if conf_ok else "✗"
        if not conf_ok:
            all_passed = False

        print(f"  {status} {name}: weight={weight:.3f}, confidence={confidence:.3f}")

    # Check that weights increase with time decay (closer to base_weight)
    print("\n  Time decay effect on weight:")
    prev_weight = 0
    for name, weight, _confidence in results:
        trend = "↑" if weight > prev_weight else "=" if weight == prev_weight else "↓"
        print(f"    {name}: weight={weight:.3f} {trend}")
        prev_weight = weight

    # Verify time decay causes weights to approach base_weight
    recent_weight = results[0][1]
    old_weight = results[3][1]  # 48h ago

    time_decay_ok = old_weight > recent_weight  # Old metrics = closer to base_weight
    status = "✓" if time_decay_ok else "✗"
    print(f"\n  {status} Time decay causes weights to approach base_weight")

    return all_passed and time_decay_ok


async def test_boundary_values():
    """Test boundary value handling."""
    print("\n" + "=" * 80)
    print("[Test 3] Boundary Value Handling")
    print("=" * 80)

    policy_engine = PolicyEngine()
    recent_time = datetime.now(UTC) - timedelta(hours=1)

    all_passed = True

    # Test minimum clamping
    print("\n  Test 3.1: Minimum weight clamping")
    weight_min, _ = policy_engine.calculate_dynamic_weight(
        base_weight=0.7,
        success_rate_1h=0.0,
        success_rate_24h=0.0,
        captcha_rate=1.0,
        median_latency_ms=10000.0,
        last_used_at=recent_time,
    )

    min_ok = weight_min >= 0.1
    status = "✓" if min_ok else "✗"
    print(f"    {status} Minimum weight clamped to 0.1: {weight_min:.3f}")
    if not min_ok:
        all_passed = False

    # Test maximum clamping
    print("\n  Test 3.2: Maximum weight clamping")
    weight_max, _ = policy_engine.calculate_dynamic_weight(
        base_weight=2.0,  # High base weight
        success_rate_1h=1.0,
        success_rate_24h=1.0,
        captcha_rate=0.0,
        median_latency_ms=100.0,
        last_used_at=recent_time,
    )

    max_ok = weight_max <= 1.0
    status = "✓" if max_ok else "✗"
    print(f"    {status} Maximum weight clamped to 1.0: {weight_max:.3f}")
    if not max_ok:
        all_passed = False

    # Test zero latency (edge case)
    print("\n  Test 3.3: Zero latency handling")
    weight_zero_lat, _ = policy_engine.calculate_dynamic_weight(
        base_weight=0.7,
        success_rate_1h=1.0,
        success_rate_24h=1.0,
        captcha_rate=0.0,
        median_latency_ms=0.0,
        last_used_at=recent_time,
    )

    zero_lat_ok = 0.1 <= weight_zero_lat <= 1.0
    status = "✓" if zero_lat_ok else "✗"
    print(f"    {status} Zero latency handled: {weight_zero_lat:.3f}")
    if not zero_lat_ok:
        all_passed = False

    return all_passed


async def test_get_dynamic_engine_weight():
    """Test getting dynamic weight for actual engines."""
    print("\n" + "=" * 80)
    print("[Test 4] Get Dynamic Engine Weight")
    print("=" * 80)

    policy_engine = await get_policy_engine()
    config_manager = get_engine_config_manager()

    test_engines = ["duckduckgo", "mojeek", "wikipedia"]
    all_passed = True

    for engine_name in test_engines:
        print(f"\n  Engine: {engine_name}")

        engine_config = config_manager.get_engine(engine_name)
        if engine_config is None:
            print("    ⚠ Engine not found in config, skipping")
            continue

        base_weight = engine_config.weight
        print(f"    Base weight from config: {base_weight}")

        try:
            dynamic_weight = await policy_engine.get_dynamic_engine_weight(
                engine_name, category="general"
            )

            print(f"    Dynamic weight: {dynamic_weight:.3f}")

            # Dynamic weight should be valid
            weight_ok = 0.1 <= dynamic_weight <= 1.0
            status = "✓" if weight_ok else "✗"
            print(f"    {status} Weight in valid range (0.1-1.0)")

            if not weight_ok:
                all_passed = False

        except Exception as e:
            print(f"    ✗ Error getting dynamic weight: {e}")
            all_passed = False

    return all_passed


async def test_fallback_on_error():
    """Test fallback to base weight on error."""
    print("\n" + "=" * 80)
    print("[Test 5] Fallback on Error")
    print("=" * 80)

    policy_engine = await get_policy_engine()

    # Test with non-existent engine
    print("\n  Test 5.1: Non-existent engine")
    weight = await policy_engine.get_dynamic_engine_weight(
        "nonexistent_engine_xyz", category="general"
    )

    # Should return default weight (1.0) for unknown engine
    fallback_ok = weight == 1.0
    status = "✓" if fallback_ok else "✗"
    print(f"    {status} Non-existent engine returns default (1.0): {weight}")

    return fallback_ok


async def test_pydantic_models():
    """Test Pydantic model validation."""
    print("\n" + "=" * 80)
    print("[Test 6] Pydantic Model Validation")
    print("=" * 80)

    all_passed = True

    # Test EngineHealthMetrics
    print("\n  Test 6.1: EngineHealthMetrics creation")
    try:
        metrics = EngineHealthMetrics(
            engine="duckduckgo",
            success_rate_1h=0.95,
            success_rate_24h=0.90,
            captcha_rate=0.05,
            median_latency_ms=800.0,
            http_error_rate=0.02,
            last_used_at=datetime.now(UTC),
        )
        print(f"    ✓ EngineHealthMetrics created: engine={metrics.engine}")
    except Exception as e:
        print(f"    ✗ Error creating EngineHealthMetrics: {e}")
        all_passed = False

    # Test DynamicWeightResult
    print("\n  Test 6.2: DynamicWeightResult creation")
    try:
        result = DynamicWeightResult(
            engine="duckduckgo",
            base_weight=0.7,
            dynamic_weight=0.65,
            confidence=0.85,
            category="general",
            metrics_used=metrics,
        )
        print(f"    ✓ DynamicWeightResult created: weight={result.dynamic_weight}")
    except Exception as e:
        print(f"    ✗ Error creating DynamicWeightResult: {e}")
        all_passed = False

    # Test validation (invalid values)
    print("\n  Test 6.3: Pydantic validation")
    try:
        # This should raise validation error
        EngineHealthMetrics(
            engine="test",
            success_rate_1h=1.5,  # Invalid: > 1.0
        )
        print("    ✗ Validation should have failed for success_rate > 1.0")
        all_passed = False
    except Exception:
        print("    ✓ Validation correctly rejects invalid values")

    return all_passed


async def main():
    """Run all debug tests."""
    print("\n" + "=" * 80)
    print("Dynamic Weight Learning Flow Debug Script")
    print("=" * 80)
    print("\nPer spec:")
    print("- §3.1.1: Learn weights based on past accuracy/failure/block rates")
    print("- §3.1.4: Store EMA in engine_health table, auto-adjust weights")
    print("- §4.6: Event-driven immediate feedback")

    results = []

    # Test 1: Basic calculation
    results.append(("Basic calculation", await test_calculate_dynamic_weight_basic()))

    # Test 2: Time decay
    results.append(("Time decay", await test_time_decay()))

    # Test 3: Boundary values
    results.append(("Boundary values", await test_boundary_values()))

    # Test 4: Get dynamic weight
    results.append(("Get dynamic weight", await test_get_dynamic_engine_weight()))

    # Test 5: Fallback on error
    results.append(("Fallback on error", await test_fallback_on_error()))

    # Test 6: Pydantic models
    results.append(("Pydantic models", await test_pydantic_models()))

    # Summary
    print("\n" + "=" * 80)
    print("Summary")
    print("=" * 80)

    passed = 0
    failed = 0
    for name, result in results:
        status = "✓ PASSED" if result else "✗ FAILED"
        print(f"  {status}: {name}")
        if result:
            passed += 1
        else:
            failed += 1

    print(f"\nTotal: {passed} passed, {failed} failed")

    if failed > 0:
        print("\n⚠ Some tests failed. Check output above for details.")
        sys.exit(1)
    else:
        print("\n✓ All tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
