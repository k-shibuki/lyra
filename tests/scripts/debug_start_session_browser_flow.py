#!/usr/bin/env python3
"""
デバッグ用一直線スクリプト: start_sessionブラウザ起動フロー（問題5）

このスクリプトは、InterventionQueue.start_session() → BrowserSearchProvider → Page の
データフローを一直線で実行し、各ステップでエラーを検出する。

実行方法:
    python tests/scripts/debug_start_session_browser_flow.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.storage.database import get_database
from src.utils.logging import configure_logging, get_logger
from src.utils.notification import get_intervention_queue

configure_logging()
logger = get_logger(__name__)


async def main():
    """一直線でstart_sessionブラウザ起動フローを実行."""
    print("=" * 70)
    print("デバッグ: start_sessionブラウザ起動フロー（問題5）")
    print("=" * 70)

    # テスト用データ
    test_task_id = "debug_task_002"

    print("\n[Step 1] Create test task and authentication queue item")
    try:
        db = await get_database()
        queue = get_intervention_queue()

        # テスト用のtaskレコードを作成（外部キー制約のため）
        await db.execute(
            """
            INSERT OR IGNORE INTO tasks (id, query, status, created_at)
            VALUES (?, ?, ?, datetime('now'))
            """,
            [test_task_id, "Debug test query", "pending"],
        )
        print(f"  ✓ Created test task: {test_task_id}")

        # テスト用の認証待ちアイテムを作成
        queue_id = await queue.enqueue(
            task_id=test_task_id,
            url="https://example.com/captcha",
            domain="example.com",
            auth_type="captcha",
            priority="high",
        )
        print(f"  ✓ Created queue item: {queue_id}")
    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print(f"\n[Step 2] InterventionQueue.start_session({test_task_id})")
    print("  Testing Chrome auto-start functionality")
    print("  Expected flow:")
    print("    1. BrowserFetcher._ensure_browser(headful=True) called")
    print("    2. CDP connection attempt fails")
    print("    3. BrowserFetcher._auto_start_chrome() executes chrome.sh start")
    print("    4. Wait for CDP connection (max 15s, 0.5s interval)")
    print("    5. Connect to Chrome via CDP")
    print("    6. Open authentication URL in browser")
    try:
        # Add timeout for browser opening (Chrome auto-start may take time)
        result = await asyncio.wait_for(
            queue.start_session(
                task_id=test_task_id,
                priority_filter="high",
            ),
            timeout=45.0  # 45秒タイムアウト（Chrome自動起動を含む）
        )

        # 型チェック
        assert isinstance(result, dict), f"result should be dict, got {type(result)}"
        assert "ok" in result, "result should have 'ok' key"
        assert "session_started" in result, "result should have 'session_started' key"
        assert "count" in result, "result should have 'count' key"
        assert "items" in result, "result should have 'items' key"

        assert isinstance(result["ok"], bool), "ok should be bool"
        assert isinstance(result["session_started"], bool), "session_started should be bool"
        assert isinstance(result["count"], int), "count should be int"
        assert isinstance(result["items"], list), "items should be list"

        print(f"  ✓ start_session returned: ok={result['ok']}, session_started={result['session_started']}, count={result['count']}")

        if result["items"]:
            item = result["items"][0]
            assert "id" in item, "item should have 'id' key"
            assert "url" in item, "item should have 'url' key"
            assert "domain" in item, "item should have 'domain' key"
            print(f"  ✓ First item: id={item['id']}, url={item['url'][:50]}...")

            # ブラウザ起動処理はstart_session()内で実行される
            # BrowserFetcher._ensure_browser()がChrome自動起動を実行する
            # ログで確認: "Auto-starting Chrome", "Connected to Chrome via CDP after auto-start", "Opened authentication URL in browser"
            if result.get("session_started"):
                print("  ✓ Browser opening should have been triggered")
                print("  → Check logs above for Chrome auto-start messages:")
                print("    - 'Auto-starting Chrome'")
                print("    - 'Connected to Chrome via CDP after auto-start'")
                print("    - 'Opened authentication URL in browser'")
            else:
                print("  ⚠ Browser opening may have failed (check logs)")
        else:
            print("  ⚠ No items to process")

    except TimeoutError:
        print("  ⚠ Timeout: Browser opening took too long (45s)")
        print("  → This may indicate Chrome auto-start is working but taking time")
        print("  → Check logs for Chrome auto-start progress")
        return 1
    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print("\n[Step 3] Cleanup test data")
    try:
        # テストデータを削除
        await db.execute(
            "DELETE FROM intervention_queue WHERE task_id = ?",
            [test_task_id],
        )
        await db.execute(
            "DELETE FROM tasks WHERE id = ?",
            [test_task_id],
        )
        print("  ✓ Cleaned up test data")
    except Exception as e:
        print(f"  ⚠ Cleanup error (non-critical): {e}")

    print("\n" + "=" * 70)
    print("✓ All steps passed!")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

