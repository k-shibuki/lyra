#!/usr/bin/env python3
"""
デバッグ用一直線スクリプト: 認証セッション再利用フロー（問題3）

このスクリプトは、BrowserFetcher → InterventionQueue → BrowserContext の
データフローを一直線で実行し、各ステップでエラーを検出する。

実行方法:
    python tests/scripts/debug_auth_session_reuse_flow.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.crawler.fetcher import BrowserFetcher
from src.utils.logging import configure_logging, get_logger
from src.utils.notification import get_intervention_queue

configure_logging()
logger = get_logger(__name__)


async def main():
    """一直線で認証セッション再利用フローを実行."""
    print("=" * 70)
    print("デバッグ: 認証セッション再利用フロー（問題3）")
    print("=" * 70)

    # テスト用URL（認証が必要なサイト）
    test_url = "https://example.com"
    test_domain = "example.com"
    test_task_id = "debug_task_001"

    print(f"\n[Step 1] InterventionQueue.get_session_for_domain({test_domain})")
    try:
        queue = get_intervention_queue()
        existing_session = await queue.get_session_for_domain(test_domain, task_id=test_task_id)

        # 型チェック
        assert existing_session is None or isinstance(existing_session, dict), (
            f"existing_session should be dict | None, got {type(existing_session)}"
        )

        if existing_session:
            assert "cookies" in existing_session, "existing_session should have 'cookies' key"
            assert isinstance(existing_session["cookies"], list), "cookies should be list"
            print(f"  ✓ Found existing session: {len(existing_session.get('cookies', []))} cookies")
        else:
            print("  ✓ No existing session found (expected for first run)")
    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print(f"\n[Step 2] BrowserFetcher.fetch({test_url}) with session reuse")
    try:
        browser_fetcher = BrowserFetcher()

        # 既存セッションがあればCookieを設定する処理をテスト
        # （実際の実装では、fetch()内でこの処理が行われる）
        if existing_session and existing_session.get("cookies"):
            print(f"  → Would apply {len(existing_session['cookies'])} cookies to browser context")
            # 実際のCookie適用はfetch()内で行われるため、ここではログのみ

        result = await browser_fetcher.fetch(
            test_url,
            task_id=test_task_id,
            allow_intervention=False,  # デバッグ中は介入を無効化
        )

        # 型チェック
        assert hasattr(result, 'ok'), "FetchResult should have 'ok' attribute"
        assert hasattr(result, 'url'), "FetchResult should have 'url' attribute"
        print(f"  ✓ BrowserFetcher returned: ok={result.ok}, reason={getattr(result, 'reason', None)}")

        if result.ok:
            print(f"  ✓ Fetch successful: status={getattr(result, 'status_code', 'N/A')}")
        else:
            print(f"  ⚠ Fetch failed: {getattr(result, 'reason', 'unknown')}")

    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print("\n" + "=" * 70)
    print("✓ All steps passed!")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

