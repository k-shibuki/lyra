#!/usr/bin/env python3
"""
デバッグ用一直線スクリプト: エンジン選択フロー

このスクリプトは、BrowserSearchProvider.search() で
エンジン選択ロジック（カテゴリ判定、重み付け、サーキットブレーカ）が
正しく動作することを確認する。
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.search.browser_search_provider import BrowserSearchProvider
from src.search.circuit_breaker import check_engine_available, record_engine_result
from src.search.engine_config import get_engine_config_manager
from src.utils.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


async def test_category_detection():
    """Test category detection logic."""
    print("\n" + "=" * 80)
    print("[Test 1] Category Detection")
    print("=" * 80)
    
    provider = BrowserSearchProvider()
    
    test_cases = [
        ("research paper on AI", "academic"),
        ("最新ニュース", "news"),
        ("government policy", "government"),
        ("API documentation", "technical"),
        ("general query", "general"),
    ]
    
    for query, expected_category in test_cases:
        category = provider._detect_category(query)
        status = "✓" if category == expected_category else "✗"
        print(f"  {status} Query: '{query}' -> Category: {category} (expected: {expected_category})")
        assert category == expected_category, f"Category mismatch: {category} != {expected_category}"
    
    print("\n  ✓ All category detection tests passed")


async def test_engine_selection_with_category():
    """Test engine selection based on category."""
    print("\n" + "=" * 80)
    print("[Test 2] Engine Selection with Category")
    print("=" * 80)
    
    provider = BrowserSearchProvider()
    config_manager = get_engine_config_manager()
    
    test_cases = [
        ("research paper", "academic"),
        ("latest news", "news"),
        ("government regulation", "government"),
        ("API tutorial", "technical"),
    ]
    
    for query, expected_category in test_cases:
        category = provider._detect_category(query)
        print(f"\n  Query: '{query}' -> Category: {category}")
        
        engines_configs = config_manager.get_engines_for_category(category)
        engine_names = [cfg.name for cfg in engines_configs]
        
        print(f"    Engines for category '{category}': {engine_names}")
        
        if engines_configs:
            print(f"    ✓ Found {len(engines_configs)} engines for category")
        else:
            print(f"    ⚠ No engines for category, will use default engines")
    
    print("\n  ✓ Engine selection with category tests completed")


async def test_circuit_breaker_integration():
    """Test circuit breaker integration."""
    print("\n" + "=" * 80)
    print("[Test 3] Circuit Breaker Integration")
    print("=" * 80)
    
    test_engines = ["duckduckgo", "mojeek", "marginalia"]
    
    for engine_name in test_engines:
        is_available = await check_engine_available(engine_name)
        status = "✓" if is_available else "✗"
        print(f"  {status} Engine '{engine_name}': available={is_available}")
    
    print("\n  ✓ Circuit breaker integration tests completed")


async def test_engine_health_recording():
    """Test engine health recording."""
    print("\n" + "=" * 80)
    print("[Test 4] Engine Health Recording")
    print("=" * 80)
    
    test_engine = "duckduckgo"
    
    # Test success recording
    print(f"\n  [Step 1] Record success for '{test_engine}'")
    try:
        await record_engine_result(
            engine=test_engine,
            success=True,
            latency_ms=500.0,
        )
        print(f"    ✓ Success recorded")
    except Exception as e:
        print(f"    ✗ Error recording success: {e}")
        import traceback
        traceback.print_exc()
    
    # Test failure recording
    print(f"\n  [Step 2] Record failure for '{test_engine}'")
    try:
        await record_engine_result(
            engine=test_engine,
            success=False,
            latency_ms=1000.0,
            is_captcha=False,
        )
        print(f"    ✓ Failure recorded")
    except Exception as e:
        print(f"    ✗ Error recording failure: {e}")
        import traceback
        traceback.print_exc()
    
    # Test CAPTCHA recording
    print(f"\n  [Step 3] Record CAPTCHA for '{test_engine}'")
    try:
        await record_engine_result(
            engine=test_engine,
            success=False,
            latency_ms=2000.0,
            is_captcha=True,
        )
        print(f"    ✓ CAPTCHA recorded")
    except Exception as e:
        print(f"    ✗ Error recording CAPTCHA: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n  ✓ Engine health recording tests completed")


async def test_full_engine_selection_flow():
    """Test full engine selection flow (without actual search)."""
    print("\n" + "=" * 80)
    print("[Test 5] Full Engine Selection Flow")
    print("=" * 80)
    
    provider = BrowserSearchProvider()
    config_manager = get_engine_config_manager()
    
    test_query = "research paper on machine learning"
    
    print(f"\n  Query: '{test_query}'")
    
    # Step 1: Category detection
    category = provider._detect_category(test_query)
    print(f"  [Step 1] Category: {category}")
    
    # Step 2: Get engines for category
    candidate_engines_configs = config_manager.get_engines_for_category(category)
    if not candidate_engines_configs:
        candidate_engines_configs = config_manager.get_available_engines()
    candidate_engines = [cfg.name for cfg in candidate_engines_configs]
    print(f"  [Step 2] Candidate engines: {candidate_engines}")
    
    # Step 3: Filter by circuit breaker
    available_engines: list[tuple[str, float]] = []
    for engine_name in candidate_engines:
        if await check_engine_available(engine_name):
            engine_config = config_manager.get_engine(engine_name)
            if engine_config and engine_config.is_available:
                available_engines.append((engine_name, engine_config.weight))
    
    print(f"  [Step 3] Available engines (with weights): {available_engines}")
    
    # Step 4: Weighted selection
    if available_engines:
        available_engines.sort(key=lambda x: x[1], reverse=True)
        selected_engine = available_engines[0][0]
        selected_weight = available_engines[0][1]
        print(f"  [Step 4] Selected engine: {selected_engine} (weight: {selected_weight})")
        print(f"    ✓ Engine selection completed")
    else:
        print(f"  [Step 4] ✗ No available engines")
    
    print("\n  ✓ Full engine selection flow tests completed")


async def main():
    """Run all tests."""
    print("=" * 80)
    print("Engine Selection Flow Debug Script")
    print("=" * 80)
    
    try:
        await test_category_detection()
        await test_engine_selection_with_category()
        await test_circuit_breaker_integration()
        await test_engine_health_recording()
        await test_full_engine_selection_flow()
        
        print("\n" + "=" * 80)
        print("✓ All tests completed successfully")
        print("=" * 80)
        
    except Exception as e:
        print("\n" + "=" * 80)
        print(f"✗ Test failed: {e}")
        print("=" * 80)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
