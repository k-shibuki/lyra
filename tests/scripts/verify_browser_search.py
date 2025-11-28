#!/usr/bin/env python3
"""
Phase 16.9: ブラウザ検索（BrowserSearchProvider）の手動検証スクリプト。

検証項目:
1. CDP接続（Windows Chrome → WSL2/Podman）
2. DuckDuckGo検索の動作
3. 検索結果パーサー
4. Stealth偽装（bot検知回避）
5. セッション管理（BrowserSearchSession）

前提条件:
- Windows側でChromeをリモートデバッグモードで起動済み
- config/settings.yaml の browser.chrome_host が正しく設定済み
- 詳細: IMPLEMENTATION_PLAN.md 16.9「検証環境セットアップ手順」参照

Usage:
    podman exec lancet python tests/scripts/verify_browser_search.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.logging import get_logger, configure_logging

logger = get_logger(__name__)


async def test_browser_search():
    """Test browser-based search with DuckDuckGo."""
    from src.search.browser_search_provider import BrowserSearchProvider
    from src.search.provider import SearchOptions
    
    print("\n" + "=" * 60)
    print("Phase 16.9 Manual E2E Test")
    print("=" * 60)
    
    provider = BrowserSearchProvider()
    
    try:
        print("\n[1/4] Provider configuration...")
        print(f"      - Available engines: {provider.get_available_engines()}")
        print("      - Browser will be initialized on first search")
        
        # Execute search
        print("\n[2/4] Executing search (DuckDuckGo, 1 query)...")
        print("      Query: 'Python programming language'")
        print("      If CAPTCHA appears, please solve it manually.")
        print("      Waiting for results...")
        
        options = SearchOptions(
            engines=["duckduckgo"],
            limit=5,
            time_range=None,
        )
        
        result = await provider.search("Python programming language", options)
        
        if result.ok:
            print(f"\n      ✓ Search successful!")
            print(f"      - Results: {len(result.results)} items")
            print(f"      - Provider: {result.provider}")
            print(f"      - Query: {result.query}")
            print(f"      - Elapsed: {result.elapsed_ms:.1f}ms")
            
            if result.results:
                print("\n      First 3 results:")
                for i, r in enumerate(result.results[:3], 1):
                    title = r.title[:50] + "..." if len(r.title) > 50 else r.title
                    print(f"        {i}. {title}")
                    print(f"           {r.url[:60]}...")
                    print(f"           Engine: {r.engine}, Rank: {r.rank}")
        else:
            print(f"\n      ✗ Search failed: {result.error}")
            print(f"      - Provider: {result.provider}")
        
        # Check stealth and session status
        print("\n[3/4] Checking stealth and session status...")
        session = provider.get_session("duckduckgo")
        if session:
            print(f"      ✓ BrowserSearchSession for duckduckgo exists")
            print(f"        - Captcha count: {session.captcha_count}")
            print(f"        - Success count: {session.success_count}")
        else:
            print("      ! No session for duckduckgo yet")
        
        # Check session transfer capability
        print("\n[4/4] Checking session transfer...")
        from src.crawler.session_transfer import get_session_transfer_manager
        
        manager = get_session_transfer_manager()
        sessions = manager._sessions
        
        if sessions:
            print(f"      ✓ {len(sessions)} session(s) stored")
            for sid, session in list(sessions.items())[:3]:
                print(f"        - Domain: {session.domain}")
                print(f"          Cookies: {len(session.cookies)}")
                print(f"          UA: {session.user_agent[:50] if session.user_agent else 'N/A'}...")
        else:
            print("      ! No sessions captured yet")
            print("        (This is OK if search was fast and didn't create session)")
        
        print("\n" + "=" * 60)
        print("Test completed!")
        print("=" * 60)
        
        return result.ok
        
    except Exception as e:
        logger.exception("Test failed with exception")
        print(f"\n      ✗ Exception: {e}")
        return False
        
    finally:
        await provider.close()


async def main():
    configure_logging(log_level="INFO", json_format=False)
    
    print("\nStarting manual E2E test...")
    print("This will open a browser window and perform a real search.")
    print("If CAPTCHA appears, you will need to solve it manually.\n")
    
    success = await test_browser_search()
    
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

