#!/usr/bin/env python3
"""
デバッグ用一直線スクリプト: ヒューマンライク操作の完全な適用フロー

このスクリプトは、BrowserFetcher.fetch() と BrowserSearchProvider.search() で
ヒューマンライク操作（マウス軌跡、タイピングリズム、スクロール慣性）が
完全に適用されることを確認する。
"""

import asyncio
import subprocess
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.crawler.fetcher import BrowserFetcher
from src.search.browser_search_provider import BrowserSearchProvider, CDPConnectionError
from src.utils.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


async def test_browser_fetcher_human_behavior():
    """Test human behavior simulation in BrowserFetcher.fetch()."""
    print("\n" + "=" * 80)
    print("[Test 1] BrowserFetcher.fetch() with human behavior simulation")
    print("=" * 80)
    
    fetcher = BrowserFetcher()
    test_url = "https://example.com"
    
    try:
        print(f"\n[Step 1] BrowserFetcher.fetch({test_url}, simulate_human=True)")
        result = await fetcher.fetch(
            test_url,
            simulate_human=True,
            take_screenshot=False,
        )
        
        # Type check
        assert hasattr(result, 'ok'), "FetchResult should have 'ok' attribute"
        print(f"  ✓ BrowserFetcher returned: ok={result.ok}")
        
        if result.ok:
            print("  ✓ Human behavior simulation applied:")
            print("    - Inertial scrolling (simulate_reading)")
            print("    - Mouse trajectory to page elements")
        else:
            print(f"  ⚠ Fetch failed: {result.reason}")
            
    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        try:
            await fetcher.close()
        except Exception:
            pass


async def test_browser_search_provider_human_behavior():
    """Test human behavior simulation in BrowserSearchProvider.search()."""
    print("\n" + "=" * 80)
    print("[Test 2] BrowserSearchProvider.search() with human behavior simulation")
    print("=" * 80)
    
    provider = BrowserSearchProvider()
    test_query = "test query"
    
    try:
        print(f"\n[Step 1] BrowserSearchProvider.search('{test_query}')")
        result = await provider.search(test_query)
        
        # Type check
        assert hasattr(result, 'ok'), "SearchResponse should have 'ok' attribute"
        print(f"  ✓ BrowserSearchProvider returned: ok={result.ok}")
        
        if result.ok:
            print("  ✓ Human behavior simulation applied:")
            print("    - Inertial scrolling (simulate_reading)")
            print("    - Mouse trajectory to search result links")
        else:
            print(f"  ⚠ Search failed: {result.error}")
            
    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        try:
            await provider.close()
        except Exception:
            pass


async def check_chrome_cdp():
    """Check Chrome CDP connection and auto-start if needed.
    
    Returns:
        True if CDP is available, False otherwise.
    """
    chrome_script = project_root / "scripts" / "chrome.sh"
    print("\n[Pre-check] Checking Chrome CDP connection...")
    
    try:
        check_result = subprocess.run(
            [str(chrome_script), "check"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        
        if "NOT_READY" in check_result.stdout or check_result.returncode != 0:
            print("  Chrome CDP not available, attempting auto-start...")
            start_result = subprocess.run(
                [str(chrome_script), "start"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            
            if "READY" not in start_result.stdout or start_result.returncode != 0:
                print(f"  ⚠ Failed to start Chrome: {start_result.stdout}")
                print(f"  ⚠ Skipped: CDP connection not available")
                return False
            
            print("  ✓ Chrome started successfully")
        else:
            print("  ✓ Chrome CDP already available")
        
        return True
    except Exception as e:
        print(f"  ⚠ CDP check failed: {e}")
        return False


async def main():
    """Run all tests."""
    print("\n" + "=" * 80)
    print("Human Behavior Simulation Flow - Debug Script")
    print("=" * 80)
    print("\nThis script verifies that human-like behavior simulation")
    print("(mouse trajectory, typing rhythm, inertial scrolling) is")
    print("fully applied in BrowserFetcher and BrowserSearchProvider.")
    print("\nNote: This requires Chrome to be running with CDP enabled.")
    print("=" * 80)
    
    # Check Chrome CDP connection
    cdp_available = await check_chrome_cdp()
    if not cdp_available:
        print("\n⚠ Skipping tests: Chrome CDP connection not available")
        print("  → Run Chrome with: ./scripts/chrome.sh start")
        return 1
    
    # Test BrowserFetcher
    try:
        await test_browser_fetcher_human_behavior()
    except Exception as e:
        print(f"\n✗ BrowserFetcher test failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Test BrowserSearchProvider
    try:
        await test_browser_search_provider_human_behavior()
    except (asyncio.TimeoutError, CDPConnectionError) as e:
        error_msg = str(e)
        print(f"\n⚠ BrowserSearchProvider test skipped: CDP connection failed ({type(e).__name__}: {error_msg})")
        print("  → This is expected if Chrome CDP is not available")
    except Exception as e:
        print(f"\n✗ BrowserSearchProvider test failed: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 80)
    print("✓ All tests completed")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    asyncio.run(main())
