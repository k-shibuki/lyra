#!/usr/bin/env python3
"""Debug script to reproduce all identified bugs.

This script reproduces:
1. Browser fetch error for PDF URLs (E2)
2. Worker ID propagation issues (H6, H7)
3. Chrome CDP connection issues (H11, H12)
4. Wayback timeout issues (H9, H10)

Run with: timeout 180 uv run python scripts/debug_pdf_fetch.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_pdf_fetch() -> None:
    """Test 1: Reproduce PDF fetch error."""
    from src.crawler.browser_fetcher import BrowserFetcher

    print("\n" + "=" * 60)
    print("TEST 1: PDF Fetch (H2-H5)")
    print("=" * 60)

    # PDF URL from the error analysis
    pdf_url = "https://care.diabetesjournals.org/content/diacare/43/11/2859.full.pdf"
    print(f"URL: {pdf_url}")

    fetcher = BrowserFetcher(worker_id=0)

    try:
        result = await fetcher.fetch(
            pdf_url,
            headful=True,
            simulate_human=True,
            take_screenshot=False,
            task_id="debug_pdf_test",
        )

        print(f"\nResult: ok={result.ok}")
        print(f"Reason: {result.reason}")
        print(f"Method: {result.method}")
        if result.status:
            print(f"Status: {result.status}")

    except Exception as e:
        print(f"\nException: {type(e).__name__}: {e}")

    finally:
        await fetcher.close()


async def test_worker_id_propagation() -> None:
    """Test 2: Check Worker ID propagation using BrowserFetcher directly."""
    from src.crawler.browser_fetcher import BrowserFetcher

    print("\n" + "=" * 60)
    print("TEST 2: Worker ID Propagation (H6, H7)")
    print("=" * 60)

    test_url = "https://httpbin.org/get"  # Simple test endpoint

    # Test with worker_id=0
    print(f"\nFetching with worker_id=0: {test_url}")
    fetcher0 = BrowserFetcher(worker_id=0)
    try:
        result0 = await fetcher0.fetch(
            test_url,
            headful=True,
            simulate_human=False,
            take_screenshot=False,
            task_id="debug_worker_test_0",
        )
        print(f"Result: ok={result0.ok}, worker_id_used=0")
    except Exception as e:
        print(f"Exception: {type(e).__name__}: {e}")
    finally:
        await fetcher0.close()

    # Test with worker_id=1 (should connect to port 9223)
    print(f"\nFetching with worker_id=1: {test_url}")
    fetcher1 = BrowserFetcher(worker_id=1)
    try:
        result1 = await fetcher1.fetch(
            test_url,
            headful=True,
            simulate_human=False,
            take_screenshot=False,
            task_id="debug_worker_test_1",
        )
        print(f"Result: ok={result1.ok}, worker_id_used=1")
    except Exception as e:
        print(f"Exception: {type(e).__name__}: {e}")
    finally:
        await fetcher1.close()


async def test_wayback_timeout() -> None:
    """Test 3: Check Wayback Machine timeout."""
    from src.crawler.wayback import WaybackClient

    print("\n" + "=" * 60)
    print("TEST 3: Wayback Timeout (H9, H10)")
    print("=" * 60)

    # URL that triggered the timeout in the logs
    test_url = "https://www.reliasmedia.com/articles/143780-insulin-therapy-for-type-2-diabetes-"
    print(f"URL: {test_url}")

    client = WaybackClient()

    try:
        import time

        start = time.time()
        snapshots = await client.get_snapshots(test_url, limit=3)
        elapsed = time.time() - start

        print(f"\nResult: {len(snapshots)} snapshots found")
        print(f"Elapsed: {elapsed:.2f}s")

        if snapshots:
            for s in snapshots:
                print(f"  - {s.timestamp.isoformat()}: {s.wayback_url[:60]}...")

    except Exception as e:
        print(f"\nException: {type(e).__name__}: {e}")


async def test_chrome_flags() -> None:
    """Test 4: Check Chrome background throttling behavior."""
    from src.crawler.browser_fetcher import BrowserFetcher

    print("\n" + "=" * 60)
    print("TEST 4: Chrome Background Throttling (H1)")
    print("=" * 60)
    print("\n⚠️  For this test, ensure Chrome is in BACKGROUND!")
    print("   (Click on another window to make Chrome inactive)")

    # URL that requires JavaScript execution (sensitive to throttling)
    test_url = "https://httpbin.org/delay/2"  # 2 second delay response

    print(f"\nFetching URL with delay: {test_url}")
    print("If background throttling is active, this may take longer...")

    import time

    fetcher = BrowserFetcher(worker_id=0)
    try:
        start = time.time()
        result = await fetcher.fetch(
            test_url,
            headful=True,
            simulate_human=False,
            take_screenshot=False,
            task_id="debug_throttle_test",
        )
        elapsed = time.time() - start
        print(f"\nResult: ok={result.ok}")
        print(f"Elapsed: {elapsed:.2f}s (expected ~5s with wait, longer if throttled)")
    except Exception as e:
        print(f"\nException: {type(e).__name__}: {e}")
    finally:
        await fetcher.close()


async def main() -> None:
    """Run all debug tests."""
    from src.storage.isolation import isolated_database_path

    print("=" * 60)
    print("DEBUG: All Bug Reproduction Tests")
    print("=" * 60)
    print("\nHypotheses being tested:")
    print("  H2-H5: PDF navigation/content issues")
    print("  H6-H8: Worker ID propagation issues")
    print("  H9-H10: Wayback timeout issues")
    print("  H11-H12: Chrome CDP connection issues")

    # Use isolated DB to avoid lock contention with MCP server
    async with isolated_database_path():
        # Run tests sequentially to avoid resource conflicts
        await test_pdf_fetch()
        await test_worker_id_propagation()
        await test_wayback_timeout()
        await test_chrome_flags()

    print("\n" + "=" * 60)
    print("DEBUG COMPLETE")
    print("=" * 60)
    print("\nCheck debug logs at: .cursor/debug.log")
    print("Use: cat .cursor/debug.log | jq .")


if __name__ == "__main__":
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
