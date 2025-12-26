#!/usr/bin/env python3
"""
Debug script for SERP Pagination Flow.

See ADR-0010 and ADR-0014 for pagination design.

Validates the end-to-end flow including:
1. PaginationConfig/Strategy initialization
2. URL building with serp_page parameter
3. Cache key generation with serp_max_pages
4. SearchOptions propagation

Usage:
    ./.venv/bin/python tests/scripts/debug_serp_pagination_flow.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


async def test_pagination_config() -> None:
    """Test PaginationConfig and PaginationStrategy."""
    print("\n=== Test 1: PaginationConfig/Strategy ===")

    from src.search.pagination_strategy import (
        PaginationConfig,
        PaginationContext,
        PaginationStrategy,
    )

    # Test config creation
    config = PaginationConfig(
        serp_max_pages=5,
        min_novelty_rate=0.1,
        min_harvest_rate=0.05,
        strategy="auto",
    )
    print(f"✓ PaginationConfig created: max_pages={config.serp_max_pages}")

    # Test strategy
    strategy = PaginationStrategy(config)

    # Test should_fetch_next with high novelty
    context = PaginationContext(current_page=2, novelty_rate=0.5)
    result = strategy.should_fetch_next(context)
    print(f"✓ should_fetch_next(page=2, novelty=0.5) = {result}")
    assert result is True, "Should continue with high novelty"

    # Test should_fetch_next with low novelty
    context = PaginationContext(current_page=3, novelty_rate=0.05)
    result = strategy.should_fetch_next(context)
    print(f"✓ should_fetch_next(page=3, novelty=0.05) = {result}")
    assert result is False, "Should stop with low novelty"

    # Test novelty rate calculation
    new_urls = ["https://a.com", "https://b.com", "https://c.com"]
    seen_urls = {"https://a.com"}
    novelty = strategy.calculate_novelty_rate(new_urls, seen_urls)
    print(f"✓ calculate_novelty_rate(3 urls, 1 seen) = {novelty:.3f}")
    assert abs(novelty - 2 / 3) < 0.001, "Novelty should be 2/3"

    print("✓ PaginationConfig/Strategy tests passed")


async def test_url_building() -> None:
    """Test URL building with serp_page parameter."""
    print("\n=== Test 2: URL Building with serp_page ===")

    from src.search.parser_config import get_parser_config_manager

    manager = get_parser_config_manager()

    # Test DuckDuckGo (offset-based)
    ddg_config = manager.get_engine_config("duckduckgo")
    if ddg_config:
        url1 = ddg_config.build_search_url("test query", serp_page=1)
        url2 = ddg_config.build_search_url("test query", serp_page=2)
        print(f"✓ DuckDuckGo page 1: {url1[:80]}...")
        print(f"✓ DuckDuckGo page 2: {url2[:80]}...")
        # Verify offset is different
        assert "s=" in url2 or url1 != url2, "Page 2 URL should differ"
    else:
        print("⚠ DuckDuckGo parser not configured")

    # Test Mojeek (page-based)
    mojeek_config = manager.get_engine_config("mojeek")
    if mojeek_config:
        url1 = mojeek_config.build_search_url("test query", serp_page=1)
        url2 = mojeek_config.build_search_url("test query", serp_page=2)
        print(f"✓ Mojeek page 1: {url1[:80]}...")
        print(f"✓ Mojeek page 2: {url2[:80]}...")
    else:
        print("⚠ Mojeek parser not configured")

    print("✓ URL building tests passed")


async def test_cache_key() -> None:
    """Test cache key generation with serp_max_pages."""
    print("\n=== Test 3: Cache Key Generation ===")

    from src.search.search_api import _get_cache_key

    # Test different serp_max_pages values
    key1 = _get_cache_key("test", None, "all", serp_max_pages=1)
    key2 = _get_cache_key("test", None, "all", serp_max_pages=3)
    key3 = _get_cache_key("test", None, "all", serp_max_pages=1)

    print(f"✓ Cache key (max_pages=1): {key1}")
    print(f"✓ Cache key (max_pages=3): {key2}")
    print(f"✓ Cache key (max_pages=1): {key3}")

    assert key1 != key2, "Different serp_max_pages should produce different keys"
    assert key1 == key3, "Same params should produce same key"

    print("✓ Cache key tests passed")


async def test_search_options() -> None:
    """Test SearchOptions propagation."""
    print("\n=== Test 4: SearchOptions Propagation ===")

    from src.search.provider import SearchOptions

    # Test default values
    options = SearchOptions()
    assert options.serp_page == 1, "Default serp_page should be 1"
    assert options.serp_max_pages == 1, "Default serp_max_pages should be 1"
    print(
        f"✓ Default options: serp_page={options.serp_page}, serp_max_pages={options.serp_max_pages}"
    )

    # Test custom values
    options = SearchOptions(serp_page=2, serp_max_pages=5)
    assert options.serp_page == 2
    assert options.serp_max_pages == 5
    print(
        f"✓ Custom options: serp_page={options.serp_page}, serp_max_pages={options.serp_max_pages}"
    )

    # Test validation
    try:
        SearchOptions(serp_max_pages=11)
        print("✗ Should have rejected serp_max_pages=11")
    except Exception:
        print("✓ Correctly rejected serp_max_pages=11 (max is 10)")

    print("✓ SearchOptions tests passed")


async def test_page_number_propagation() -> None:
    """Test page_number propagation through SearchResult (R_SERP_ENHANCEMENT Issue 1)."""
    print("\n=== Test 5: page_number Propagation ===")

    from src.search.provider import SearchResult
    from src.search.search_parsers import ParsedResult

    # Test ParsedResult.to_search_result with serp_page
    parsed = ParsedResult(
        title="Test",
        url="https://example.com",
        snippet="Test snippet",
        rank=1,
    )

    # Default serp_page=1
    result1 = parsed.to_search_result("test_engine")
    assert result1.page_number == 1, "Default page_number should be 1"
    print(f"✓ Default page_number: {result1.page_number}")

    # Custom serp_page=3
    result3 = parsed.to_search_result("test_engine", serp_page=3)
    assert result3.page_number == 3, "Custom page_number should be 3"
    print(f"✓ Custom page_number: {result3.page_number}")

    # Test to_dict includes page_number
    result_dict = result3.to_dict()
    assert "page_number" in result_dict, "to_dict should include page_number"
    assert result_dict["page_number"] == 3, "page_number in dict should be 3"
    print(f"✓ to_dict includes page_number: {result_dict['page_number']}")

    # Test from_dict preserves page_number
    restored = SearchResult.from_dict(result_dict)
    assert restored.page_number == 3, "from_dict should preserve page_number"
    print(f"✓ from_dict preserves page_number: {restored.page_number}")

    # Test from_dict with missing page_number (backward compatibility)
    dict_without_page = {
        "title": "Test",
        "url": "https://example.com",
        "snippet": "Test",
        "engine": "test",
        "rank": 1,
        "source_tag": "unknown",
    }
    restored_default = SearchResult.from_dict(dict_without_page)
    assert restored_default.page_number == 1, "Missing page_number should default to 1"
    print(f"✓ Missing page_number defaults to 1: {restored_default.page_number}")

    print("✓ page_number propagation tests passed")


async def test_harvest_rate_propagation() -> None:
    """Test harvest_rate propagation to PaginationContext (R_SERP_ENHANCEMENT Issue 2)."""
    print("\n=== Test 6: harvest_rate Propagation ===")

    from src.search.pagination_strategy import (
        PaginationConfig,
        PaginationContext,
        PaginationStrategy,
    )

    config = PaginationConfig(
        serp_max_pages=10,
        min_harvest_rate=0.05,
        strategy="auto",
    )
    strategy = PaginationStrategy(config)

    # Test with harvest_rate provided
    context_with_rate = PaginationContext(
        current_page=2,
        novelty_rate=0.5,
        harvest_rate=0.08,  # Above threshold
    )
    result = strategy.should_fetch_next(context_with_rate)
    assert result is True, "Should continue with harvest_rate > threshold"
    print(f"✓ harvest_rate=0.08 (> 0.05): should_fetch_next={result}")

    # Test with low harvest_rate
    context_low_rate = PaginationContext(
        current_page=2,
        novelty_rate=0.5,
        harvest_rate=0.03,  # Below threshold
    )
    result = strategy.should_fetch_next(context_low_rate)
    assert result is False, "Should stop with harvest_rate < threshold"
    print(f"✓ harvest_rate=0.03 (< 0.05): should_fetch_next={result}")

    # Test with None harvest_rate (should continue)
    context_none_rate = PaginationContext(
        current_page=2,
        novelty_rate=0.5,
        harvest_rate=None,
    )
    result = strategy.should_fetch_next(context_none_rate)
    assert result is True, "Should continue with None harvest_rate"
    print(f"✓ harvest_rate=None: should_fetch_next={result}")

    print("✓ harvest_rate propagation tests passed")


async def main() -> int:
    """Run all debug tests."""
    print("=" * 60)
    print("SERP Pagination Flow Debug")
    print("=" * 60)

    try:
        await test_pagination_config()
        await test_url_building()
        await test_cache_key()
        await test_search_options()
        await test_page_number_propagation()
        await test_harvest_rate_propagation()

        print("\n" + "=" * 60)
        print("All debug tests PASSED ✓")
        print("=" * 60)
        return 0
    except AssertionError as e:
        print(f"\n✗ Assertion failed: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
