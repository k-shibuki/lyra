#!/usr/bin/env python3
"""
Debug script for OpenAlex S2 ID handling and 404 caching.

Tests:
1. H-B: S2 paper IDs are skipped (not queried against OpenAlex)
2. H-C: 404 responses are cached to avoid repeated lookups

Usage:
    timeout 60 uv run python scripts/debug_openalex_s2.py
"""

import asyncio
import json
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

DEBUG_LOG_PATH = Path(__file__).parent.parent / ".cursor" / "debug.log"


def clear_debug_log() -> None:
    """Clear the debug log file."""
    DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_LOG_PATH.write_text("")
    print(f"Cleared debug log: {DEBUG_LOG_PATH}")


def read_debug_log() -> list[dict]:
    """Read and parse debug log entries."""
    if not DEBUG_LOG_PATH.exists():
        return []

    entries = []
    for line in DEBUG_LOG_PATH.read_text().strip().split("\n"):
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


async def main() -> None:
    """Run OpenAlex S2 ID and 404 cache tests."""
    print("=" * 60)
    print("OpenAlex S2 ID Handling & 404 Cache Test")
    print("=" * 60)

    # Clear debug log
    clear_debug_log()

    # Import after path setup
    from src.search.apis.openalex import OpenAlexClient, _404_cache

    client = OpenAlexClient()

    # Test 1: H-B - S2 paper IDs should be skipped
    print("\n[1] Testing H-B: S2 paper ID handling...")
    s2_paper_ids = [
        "s2:25bb7a1fae2d87fac3af0b792a5796ee027e0cb5",
        "s2:6ee3843bd13533a9a1983c9f8be831f614a609db",
        "s2:d837c4aebc68223daf6253940dc2a0208ef5f36b",
    ]

    for paper_id in s2_paper_ids:
        result = await client.get_paper(paper_id)
        print(f"    {paper_id[:30]}... → {result}")

    # Verify no API calls were made for S2 IDs
    entries = read_debug_log()
    s2_skip_entries = [e for e in entries if e.get("location", "").endswith("get_paper_s2_skip")]
    s2_error_entries = [e for e in entries if e.get("hypothesisId") == "H-C" and e.get("location", "").endswith("get_paper_error")]

    print(f"\n    S2 skip log entries: {len(s2_skip_entries)}")
    print(f"    S2 error entries (should be 0): {len(s2_error_entries)}")

    if len(s2_skip_entries) == len(s2_paper_ids) and len(s2_error_entries) == 0:
        print("    ✅ H-B PASS: S2 paper IDs correctly skipped")
    else:
        print("    ❌ H-B FAIL: S2 paper IDs not properly handled")

    # Test 2: H-C - 404 responses should be cached
    print("\n[2] Testing H-C: 404 negative cache...")

    # Use an invalid OpenAlex ID that will return 404
    invalid_paper_id = "W9999999999999999"  # Non-existent

    print(f"    First request for {invalid_paper_id}...")
    start_time = time.time()
    result1 = await client.get_paper(invalid_paper_id)
    first_request_time = time.time() - start_time
    print(f"    Result: {result1}, Time: {first_request_time:.2f}s")

    # Check if 404 was cached
    print(f"    404 cache size: {len(_404_cache)}")
    print(f"    {invalid_paper_id} in cache: {invalid_paper_id in _404_cache}")

    # Second request should hit cache (much faster, no API call)
    print(f"\n    Second request for {invalid_paper_id}...")
    start_time = time.time()
    result2 = await client.get_paper(invalid_paper_id)
    second_request_time = time.time() - start_time
    print(f"    Result: {result2}, Time: {second_request_time:.4f}s")

    # Verify cache hit
    entries_after = read_debug_log()
    cache_hit_entries = [e for e in entries_after if e.get("location", "").endswith("get_paper_404_cache_hit")]

    print(f"\n    Cache hit log entries: {len(cache_hit_entries)}")

    # Second request should be at least 10x faster (cached)
    if second_request_time < first_request_time / 10 and len(cache_hit_entries) >= 1:
        print("    ✅ H-C PASS: 404 correctly cached, second request was fast")
    else:
        print("    ❌ H-C FAIL: 404 caching not working as expected")

    # Test 3: Valid OpenAlex ID should work normally
    print("\n[3] Testing valid OpenAlex ID...")
    valid_paper_id = "W2741809807"  # A known valid OpenAlex work ID

    result3 = await client.get_paper(valid_paper_id)
    if result3:
        print(f"    ✅ Valid paper retrieved: {result3.title[:50]}...")
    else:
        print("    ⚠️ Valid paper not retrieved (may be network issue)")

    # Cleanup
    await client.close()

    # Summary
    print("\n" + "=" * 60)
    print("Debug Log Summary")
    print("=" * 60)

    all_entries = read_debug_log()
    print(f"Total entries: {len(all_entries)}")

    # Group by location
    by_location: dict[str, int] = {}
    for e in all_entries:
        loc = e.get("location", "unknown")
        by_location[loc] = by_location.get(loc, 0) + 1

    print("\nEntries by location:")
    for loc, count in sorted(by_location.items()):
        print(f"  {loc}: {count}")

    print("\n" + "=" * 60)
    print("Test Complete")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
