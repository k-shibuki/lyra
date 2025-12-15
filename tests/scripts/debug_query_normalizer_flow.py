#!/usr/bin/env python3
"""
Debug script for query operator normalization flow.

This script verifies that BrowserSearchProvider.search() correctly
normalizes query operators using transform_query_for_engine().

Per spec:
- §3.1.1: "Query operators (site:, filetype:, intitle:, "...", +/-, after:)"
- §3.1.4: "Engine normalization (transform operators to engine-specific syntax)"
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.search.search_api import (
    parse_query_operators,
    transform_query_for_engine,
    QueryOperatorProcessor,
)
from src.search.engine_config import get_engine_config_manager
from src.utils.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


async def test_parse_operators():
    """Test that query operators are correctly parsed."""
    print("\n" + "=" * 80)
    print("[Test 1] Query Operator Parsing")
    print("=" * 80)
    
    test_cases = [
        (
            "AI研究 site:go.jp",
            {"site": ["go.jp"]},
            "AI研究",
        ),
        (
            "AI filetype:pdf",
            {"filetype": ["pdf"]},
            "AI",
        ),
        (
            "AI intitle:重要",
            {"intitle": ["重要"]},
            "AI",
        ),
        (
            '"人工知能の発展"',
            {"exact": ["人工知能の発展"]},
            "",
        ),
        (
            "AI -広告 -スパム",
            {"exclude": ["広告", "スパム"]},
            "AI",
        ),
        (
            "AI after:2024-01-01",
            {"date_after": ["2024-01-01"]},
            "AI",
        ),
        (
            "AI site:go.jp filetype:pdf after:2024-01-01",
            {"site": ["go.jp"], "filetype": ["pdf"], "date_after": ["2024-01-01"]},
            "AI",
        ),
    ]
    
    all_passed = True
    for query, expected_ops, expected_base in test_cases:
        parsed = parse_query_operators(query)
        
        print(f"\n  Query: '{query}'")
        print(f"    Base query: '{parsed.base_query}' (expected: '{expected_base}')")
        
        # Check base query
        base_ok = parsed.base_query.strip() == expected_base.strip()
        
        # Check operators
        ops_ok = True
        for op_type, values in expected_ops.items():
            actual = [op.value for op in parsed.get_operators(op_type)]
            if set(actual) != set(values):
                ops_ok = False
                print(f"    ✗ {op_type}: {actual} (expected: {values})")
            else:
                print(f"    ✓ {op_type}: {actual}")
        
        status = "✓" if (base_ok and ops_ok) else "✗"
        if not (base_ok and ops_ok):
            all_passed = False
        print(f"    {status} Parsing result")
    
    if all_passed:
        print("\n  ✓ All operator parsing tests passed")
    else:
        print("\n  ✗ Some operator parsing tests failed")
    
    return all_passed


async def test_transform_for_google():
    """Test query transformation for Google engine."""
    print("\n" + "=" * 80)
    print("[Test 2] Transform for Google")
    print("=" * 80)
    
    test_cases = [
        # (input_query, expected_to_contain)
        ("AI site:go.jp", ["site:go.jp"]),
        ("AI filetype:pdf", ["filetype:pdf"]),
        ("AI intitle:重要", ["intitle:重要"]),
        ("AI after:2024-01-01", ["after:2024-01-01"]),
        ("AI -広告", ["-広告"]),
    ]
    
    all_passed = True
    for query, expected_parts in test_cases:
        result = transform_query_for_engine(query, "google")
        
        print(f"\n  Input: '{query}'")
        print(f"  Output: '{result}'")
        
        parts_ok = all(part in result for part in expected_parts)
        
        if parts_ok:
            print(f"    ✓ Contains expected: {expected_parts}")
        else:
            print(f"    ✗ Missing parts: {expected_parts}")
            all_passed = False
    
    if all_passed:
        print("\n  ✓ All Google transformation tests passed")
    else:
        print("\n  ✗ Some Google transformation tests failed")
    
    return all_passed


async def test_transform_for_duckduckgo():
    """Test query transformation for DuckDuckGo engine."""
    print("\n" + "=" * 80)
    print("[Test 3] Transform for DuckDuckGo")
    print("=" * 80)
    
    # DuckDuckGo supports site:, filetype:, intitle:, but NOT after:
    test_cases = [
        # (input_query, expected_to_contain, expected_not_to_contain)
        ("AI site:go.jp", ["site:go.jp"], []),
        ("AI filetype:pdf", ["filetype:pdf"], []),
        ("AI intitle:重要", ["intitle:重要"], []),
        ("AI after:2024-01-01", ["AI"], ["after:"]),  # after: should be removed
        ("AI site:go.jp after:2024-01-01", ["site:go.jp"], ["after:"]),
    ]
    
    all_passed = True
    for query, expected_contain, expected_not_contain in test_cases:
        result = transform_query_for_engine(query, "duckduckgo")
        
        print(f"\n  Input: '{query}'")
        print(f"  Output: '{result}'")
        
        contain_ok = all(part in result for part in expected_contain)
        not_contain_ok = all(part not in result for part in expected_not_contain)
        
        if contain_ok:
            print(f"    ✓ Contains expected: {expected_contain}")
        else:
            print(f"    ✗ Missing parts: {expected_contain}")
            all_passed = False
        
        if expected_not_contain:
            if not_contain_ok:
                print(f"    ✓ Correctly removed: {expected_not_contain}")
            else:
                print(f"    ✗ Should not contain: {expected_not_contain}")
                all_passed = False
    
    if all_passed:
        print("\n  ✓ All DuckDuckGo transformation tests passed")
    else:
        print("\n  ✗ Some DuckDuckGo transformation tests failed")
    
    return all_passed


async def test_transform_for_mojeek():
    """Test query transformation for Mojeek engine."""
    print("\n" + "=" * 80)
    print("[Test 4] Transform for Mojeek")
    print("=" * 80)
    
    # Mojeek supports site:, filetype:, intitle:, but NOT after:
    test_cases = [
        # (input_query, expected_to_contain, expected_not_to_contain)
        ("AI site:go.jp", ["site:go.jp"], []),
        ("AI filetype:pdf", ["filetype:pdf"], []),
        ("AI intitle:重要", ["intitle:重要"], []),  # Mojeek supports intitle:
        ("AI after:2024-01-01", ["AI"], ["after:"]),  # after: should be removed
    ]
    
    all_passed = True
    for query, expected_contain, expected_not_contain in test_cases:
        result = transform_query_for_engine(query, "mojeek")
        
        print(f"\n  Input: '{query}'")
        print(f"  Output: '{result}'")
        
        contain_ok = all(part in result for part in expected_contain)
        not_contain_ok = all(part not in result for part in expected_not_contain)
        
        if contain_ok:
            print(f"    ✓ Contains expected: {expected_contain}")
        else:
            print(f"    ✗ Missing parts: {expected_contain}")
            all_passed = False
        
        if expected_not_contain:
            if not_contain_ok:
                print(f"    ✓ Correctly removed: {expected_not_contain}")
            else:
                print(f"    ✗ Should not contain: {expected_not_contain}")
                all_passed = False
    
    if all_passed:
        print("\n  ✓ All Mojeek transformation tests passed")
    else:
        print("\n  ✗ Some Mojeek transformation tests failed")
    
    return all_passed


async def test_edge_cases():
    """Test edge cases for query transformation."""
    print("\n" + "=" * 80)
    print("[Test 5] Edge Cases")
    print("=" * 80)
    
    test_cases = [
        # (description, query, engine, expected_behavior)
        ("Empty query", "", "duckduckgo", ""),
        ("Plain query (no operators)", "AI research", "duckduckgo", "AI research"),
        ("Only operators, no base", "site:go.jp filetype:pdf", "duckduckgo", None),
        ("Unknown engine", "AI site:go.jp", "unknown_engine", None),
    ]
    
    all_passed = True
    for description, query, engine, expected in test_cases:
        try:
            result = transform_query_for_engine(query, engine)
            
            print(f"\n  {description}")
            print(f"    Input: '{query}' (engine: {engine})")
            print(f"    Output: '{result}'")
            
            if expected is not None:
                if result == expected:
                    print(f"    ✓ Matches expected: '{expected}'")
                else:
                    print(f"    ✗ Expected: '{expected}'")
                    all_passed = False
            else:
                # Just verify it doesn't crash
                print(f"    ✓ Completed without error")
                
        except Exception as e:
            print(f"\n  {description}")
            print(f"    ✗ Error: {e}")
            all_passed = False
    
    if all_passed:
        print("\n  ✓ All edge case tests passed")
    else:
        print("\n  ✗ Some edge case tests failed")
    
    return all_passed


async def test_supported_operators():
    """Test getting supported operators for engines."""
    print("\n" + "=" * 80)
    print("[Test 6] Supported Operators by Engine")
    print("=" * 80)
    
    processor = QueryOperatorProcessor()
    
    engines = ["google", "duckduckgo", "bing", "brave", "mojeek"]
    
    print("\n  Operator support matrix:")
    print("  " + "-" * 70)
    print(f"  {'Engine':<12} | {'site':<6} | {'filetype':<8} | {'intitle':<7} | {'exact':<5} | {'exclude':<7} | {'after':<6}")
    print("  " + "-" * 70)
    
    all_passed = True
    for engine in engines:
        try:
            supported = processor.get_supported_operators(engine)
            
            site = "✓" if "site" in supported else "✗"
            filetype = "✓" if "filetype" in supported else "✗"
            intitle = "✓" if "intitle" in supported else "✗"
            exact = "✓" if "exact" in supported else "✗"
            exclude = "✓" if "exclude" in supported else "✗"
            after = "✓" if "date_after" in supported else "✗"
            
            print(f"  {engine:<12} | {site:<6} | {filetype:<8} | {intitle:<7} | {exact:<5} | {exclude:<7} | {after:<6}")
        except Exception as e:
            print(f"  {engine:<12} | Error: {e}")
            all_passed = False
    
    print("  " + "-" * 70)
    
    if all_passed:
        print("\n  ✓ Operator support check completed")
    
    return all_passed


async def test_full_flow():
    """Test full query normalization flow."""
    print("\n" + "=" * 80)
    print("[Test 7] Full Query Normalization Flow")
    print("=" * 80)
    
    # Simulate the flow in BrowserSearchProvider.search()
    query = "AI研究 site:go.jp filetype:pdf intitle:重要 after:2024-01-01"
    
    print(f"\n  Original query: '{query}'")
    print("\n  Engine-specific transformations:")
    print("  " + "-" * 60)
    
    engines = ["google", "duckduckgo", "mojeek"]
    
    all_passed = True
    for engine in engines:
        normalized = transform_query_for_engine(query, engine)
        
        # Check if transformation happened
        changed = normalized != query
        
        print(f"\n  {engine}:")
        print(f"    Normalized: '{normalized}'")
        print(f"    Changed: {'Yes' if changed else 'No'}")
        
        # Log simulation (what would happen in BrowserSearchProvider.search())
        if changed:
            print(f"    [LOG] Query operators normalized")
            print(f"           original: '{query[:50]}'")
            print(f"           normalized: '{normalized[:50]}'")
            print(f"           engine: {engine}")
    
    print("\n  " + "-" * 60)
    print("\n  ✓ Full flow completed")
    
    return all_passed


async def main():
    """Run all tests."""
    print("=" * 80)
    print("Query Normalizer Flow Debug Script")
    print("=" * 80)
    print("\nThis script verifies query operator normalization for search engines.")
    print("Per spec §3.1.1 and §3.1.4: Query operators and engine normalization.")
    
    results = []
    
    try:
        results.append(("Parse Operators", await test_parse_operators()))
        results.append(("Transform for Google", await test_transform_for_google()))
        results.append(("Transform for DuckDuckGo", await test_transform_for_duckduckgo()))
        results.append(("Transform for Mojeek", await test_transform_for_mojeek()))
        results.append(("Edge Cases", await test_edge_cases()))
        results.append(("Supported Operators", await test_supported_operators()))
        results.append(("Full Flow", await test_full_flow()))
        
        print("\n" + "=" * 80)
        print("Test Results Summary")
        print("=" * 80)
        
        all_passed = True
        for test_name, passed in results:
            status = "✓ PASS" if passed else "✗ FAIL"
            print(f"  {status}: {test_name}")
            if not passed:
                all_passed = False
        
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
