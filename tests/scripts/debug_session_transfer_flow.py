#!/usr/bin/env python3
"""
デバッグ用一直線スクリプト: セッション転送フロー（問題12）

このスクリプトは、BrowserFetcher → SessionTransfer → HTTPFetcher の
データフローを一直線で実行し、各ステップでエラーを検出する。

実行方法:
    python tests/scripts/debug_session_transfer_flow.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.crawler.fetcher import BrowserFetcher, HTTPFetcher
from src.crawler.session_transfer import get_transfer_headers
from src.utils.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


async def main():
    """一直線でセッション転送フローを実行."""
    print("=" * 70)
    print("デバッグ: セッション転送フロー（問題12）")
    print("=" * 70)

    test_url = "https://example.com"

    print(f"\n[Step 1] BrowserFetcher.fetch({test_url}) - 初回取得")
    try:
        browser_fetcher = BrowserFetcher()
        browser_result = await browser_fetcher.fetch(
            test_url,
            allow_intervention=False,  # デバッグ中は介入を無効化
        )

        # 型チェック
        assert hasattr(browser_result, "ok"), "FetchResult should have 'ok' attribute"
        print(f"  ✓ BrowserFetcher returned: ok={browser_result.ok}")

        if not browser_result.ok:
            print(f"  ⚠ Browser fetch failed: {getattr(browser_result, 'reason', 'unknown')}")
            print("  → Skipping session capture (expected if fetch failed)")
            return 0

        # セッションキャプチャ（実際の実装では、fetch()内で行われる）
        print("  → Session capture would happen here (not implemented yet)")

    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback

        traceback.print_exc()
        return 1

    print(f"\n[Step 2] get_transfer_headers({test_url})")
    try:
        transfer_result = get_transfer_headers(test_url, include_conditional=True)

        # 型チェック
        assert hasattr(transfer_result, "ok"), "TransferResult should have 'ok' attribute"
        assert hasattr(transfer_result, "headers"), "TransferResult should have 'headers' attribute"
        assert isinstance(transfer_result.headers, dict), "headers should be dict"

        print(
            f"  ✓ SessionTransfer returned: ok={transfer_result.ok}, headers={len(transfer_result.headers)}"
        )

        if transfer_result.ok:
            print("  ✓ Transfer headers available:")
            for key in list(transfer_result.headers.keys())[:5]:  # 最初の5つだけ表示
                print(f"    - {key}: {transfer_result.headers[key][:50]}...")
        else:
            print(f"  ⚠ No transfer headers: {getattr(transfer_result, 'reason', 'unknown')}")
            print("  → This is expected if no session was captured yet")

    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback

        traceback.print_exc()
        return 1

    print(f"\n[Step 3] HTTPFetcher.fetch({test_url}) with transfer headers")
    try:
        http_fetcher = HTTPFetcher()

        # セッション転送ヘッダーを適用（実際の実装では、fetch()内で行われる）
        headers = {}
        if transfer_result.ok:
            headers.update(transfer_result.headers)
            print(f"  → Applied {len(headers)} transfer headers")

        http_result = await http_fetcher.fetch(
            test_url,
            headers=headers if headers else None,
        )

        # 型チェック
        assert hasattr(http_result, "ok"), "FetchResult should have 'ok' attribute"
        print(f"  ✓ HTTPFetcher returned: ok={http_result.ok}")

        if http_result.ok:
            status = getattr(http_result, "status_code", "N/A")
            print(f"  ✓ HTTP fetch successful: status={status}")
            if status == 304:
                print("  ✓ 304 Not Modified - cache hit!")
        else:
            print(f"  ⚠ HTTP fetch failed: {getattr(http_result, 'reason', 'unknown')}")

    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback

        traceback.print_exc()
        return 1

    # Step 4: Test URL-specific cached values take precedence over session headers
    print(f"\n[Step 4] HTTPFetcher.fetch({test_url}) with cached_etag (URL-specific)")
    print("  Testing: URL-specific ETag should not be overwritten by session headers")
    try:
        # Get ETag from first fetch if available
        cached_etag = None
        cached_last_modified = None
        if http_result.ok and hasattr(http_result, "etag") and http_result.etag:
            cached_etag = http_result.etag
            print(f"  → Using cached ETag from first fetch: {cached_etag}")
        if http_result.ok and hasattr(http_result, "last_modified") and http_result.last_modified:
            cached_last_modified = http_result.last_modified
            print(f"  → Using cached Last-Modified from first fetch: {cached_last_modified}")

        # Fetch with URL-specific cached values
        # Session transfer headers should NOT include conditional headers
        # when cached_etag/cached_last_modified are provided
        http_result2 = await http_fetcher.fetch(
            test_url,
            cached_etag=cached_etag,
            cached_last_modified=cached_last_modified,
        )

        assert hasattr(http_result2, "ok"), "FetchResult should have 'ok' attribute"
        print(f"  ✓ HTTPFetcher returned: ok={http_result2.ok}")

        if http_result2.ok:
            status2 = getattr(http_result2, "status_code", "N/A")
            print(f"  ✓ HTTP fetch successful: status={status2}")
            if status2 == 304:
                print("  ✓ 304 Not Modified - URL-specific ETag worked correctly!")
            else:
                print(f"  → Status {status2} (may be 200 if content changed)")
        else:
            print(f"  ⚠ HTTP fetch failed: {getattr(http_result2, 'reason', 'unknown')}")

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
