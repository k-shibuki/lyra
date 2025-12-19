#!/usr/bin/env python3
"""
デバッグ用一直線スクリプト: Chrome自動起動機能（問題5の一部）

BrowserFetcher._ensure_browser(headful=True)がChrome自動起動を実行するか確認
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.crawler.fetcher import BrowserFetcher
from src.utils.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


async def main():
    print("=" * 70)
    print("デバッグ: Chrome自動起動機能")
    print("=" * 70)

    print("\n[Step 1] BrowserFetcher._ensure_browser(headful=True)")
    print("  Expected: CDP接続失敗 → chrome.sh start → CDP接続待機")

    try:
        browser_fetcher = BrowserFetcher()
        print("  → Calling _ensure_browser(headful=True)...")
        print("  → This may take up to 45 seconds (Chrome auto-start + CDP wait)")

        # Add timeout to prevent hanging
        browser, context = await asyncio.wait_for(
            browser_fetcher._ensure_browser(headful=True, task_id="debug_chrome_001"),
            timeout=45.0
        )

        print("  ✓ _ensure_browser() returned")
        print(f"    browser: {browser is not None}")
        print(f"    context: {context is not None}")

        if browser:
            print("  ✓ Browser obtained successfully")
        else:
            print("  ✗ Browser is None")

    except TimeoutError:
        print("  ⚠ Timeout: _ensure_browser() took longer than 45 seconds")
        print("  → This may indicate Chrome auto-start is working but taking time")
        return 1
    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print("\n" + "=" * 70)
    print("✓ Test completed!")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

