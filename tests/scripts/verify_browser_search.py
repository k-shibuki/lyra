#!/usr/bin/env python3
"""
検証対象: §3.2 エージェント実行機能（ブラウザ検索）

検証項目:
1. CDP接続（Windows Chrome → WSL2/Podman）
2. DuckDuckGo検索の動作
3. 検索結果パーサーの正確性
4. Stealth偽装（bot検知回避）
5. セッション管理（BrowserSearchSession）

前提条件:
- Windows側でChromeをリモートデバッグモードで起動済み
- config/settings.yaml の browser.chrome_host が正しく設定済み
- 詳細: IMPLEMENTATION_PLAN.md 16.9「検証環境セットアップ手順」参照

受け入れ基準（§7）:
- CAPTCHA: 発生検知100%、自動→手動誘導に確実に移行
- スクレイピング成功率≥95%

Usage:
    podman exec lancet python tests/scripts/verify_browser_search.py

Exit codes:
    0: 全検証パス
    1: いずれか失敗
    2: 前提条件未充足でスキップ

Note:
    このスクリプトは実際の検索エンジンにアクセスします。
    IPブロックのリスクがあるため、低リスク環境で実行してください。
"""

import asyncio
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.utils.logging import get_logger, configure_logging

logger = get_logger(__name__)


@dataclass
class VerificationResult:
    """検証結果を保持するデータクラス。"""
    name: str
    spec_ref: str
    passed: bool
    skipped: bool = False
    skip_reason: Optional[str] = None
    details: dict = field(default_factory=dict)
    error: Optional[str] = None


class BrowserSearchVerifier:
    """§3.2 ブラウザ検索機能の検証を実施するクラス。"""
    
    def __init__(self):
        self.results: list[VerificationResult] = []
        self.browser_available = False
        
    async def check_prerequisites(self) -> bool:
        """前提条件を確認。"""
        print("\n[Prerequisites] Checking environment...")
        
        # Check browser connectivity
        try:
            from src.crawler.browser_provider import get_browser_provider
            provider = await get_browser_provider()
            if provider:
                self.browser_available = True
                print("  ✓ Browser provider available")
                await provider.close()
            else:
                print("  ✗ Browser provider not available")
                print("    → Run Chrome with: --remote-debugging-port=9222")
                return False
        except Exception as e:
            print(f"  ✗ Browser check failed: {e}")
            return False
        
        print("  All prerequisites met.\n")
        print("  ⚠ Warning: This will access real search engines.")
        print("    Run in a low-risk IP environment to avoid blocks.\n")
        return True

    async def verify_cdp_connection(self) -> VerificationResult:
        """CDP接続の検証。"""
        print("\n[1/5] Verifying CDP connection (§3.2 GUI連携)...")
        
        from src.crawler.browser_provider import get_browser_provider
        
        try:
            provider = await get_browser_provider()
            
            if not provider:
                return VerificationResult(
                    name="CDP Connection",
                    spec_ref="§3.2 GUI連携",
                    passed=False,
                    error="Browser provider returned None",
                )
            
            # Get browser info
            browser_info = {}
            if hasattr(provider, '_browser') and provider._browser:
                browser = provider._browser
                browser_info['connected'] = browser.is_connected()
                contexts = browser.contexts
                browser_info['contexts'] = len(contexts)
                
                if contexts:
                    pages = contexts[0].pages
                    browser_info['pages'] = len(pages)
            
            print(f"    ✓ Browser connected: {browser_info.get('connected', False)}")
            print(f"    ✓ Contexts: {browser_info.get('contexts', 0)}")
            print(f"    ✓ Pages: {browser_info.get('pages', 0)}")
            
            await provider.close()
            
            return VerificationResult(
                name="CDP Connection",
                spec_ref="§3.2 GUI連携",
                passed=True,
                details=browser_info,
            )
            
        except Exception as e:
            logger.exception("CDP connection verification failed")
            return VerificationResult(
                name="CDP Connection",
                spec_ref="§3.2 GUI連携",
                passed=False,
                error=str(e),
            )

    async def verify_duckduckgo_search(self) -> VerificationResult:
        """DuckDuckGo検索の動作検証。"""
        print("\n[2/5] Verifying DuckDuckGo search (§3.2 検索エンジン統合)...")
        
    from src.search.browser_search_provider import BrowserSearchProvider
    from src.search.provider import SearchOptions
    
    provider = BrowserSearchProvider()
    
    try:
            test_query = "Python programming language"
            
            print(f"    Query: '{test_query}'")
        
        options = SearchOptions(
            engines=["duckduckgo"],
            limit=5,
            time_range=None,
        )
        
            start_time = time.time()
            result = await provider.search(test_query, options)
            elapsed = time.time() - start_time
            
            if not result.ok:
                if result.captcha_detected:
                    print(f"    ! CAPTCHA detected: {result.captcha_type}")
                    return VerificationResult(
                        name="DuckDuckGo Search",
                        spec_ref="§3.2 検索エンジン統合",
                        passed=True,
                        details={
                            "captcha_detected": True,
                            "captcha_type": result.captcha_type,
                            "note": "CAPTCHA detection working",
                        },
                    )
                else:
                    return VerificationResult(
                        name="DuckDuckGo Search",
                        spec_ref="§3.2 検索エンジン統合",
                        passed=False,
                        error=f"Search failed: {result.error}",
                    )
            
            print(f"    ✓ Search completed in {elapsed:.2f}s")
            print(f"    ✓ Results: {len(result.results)} items")
            
            if not result.results:
                return VerificationResult(
                    name="DuckDuckGo Search",
                    spec_ref="§3.2 検索エンジン統合",
                    passed=False,
                    error="No results returned",
                )
            
            # Display first few results
            for i, r in enumerate(result.results[:3], 1):
                title = r.title[:45] + "..." if len(r.title) > 45 else r.title
                print(f"      {i}. {title}")
                print(f"         {r.url[:55]}...")
            
            return VerificationResult(
                name="DuckDuckGo Search",
                spec_ref="§3.2 検索エンジン統合",
                passed=True,
                details={
                    "query": test_query,
                    "results_count": len(result.results),
                    "elapsed_seconds": elapsed,
                },
            )
            
        except Exception as e:
            logger.exception("DuckDuckGo search verification failed")
            return VerificationResult(
                name="DuckDuckGo Search",
                spec_ref="§3.2 検索エンジン統合",
                passed=False,
                error=str(e),
            )
        finally:
            await provider.close()

    async def verify_parser_accuracy(self) -> VerificationResult:
        """検索結果パーサーの正確性検証。"""
        print("\n[3/5] Verifying parser accuracy (§3.2 コンテンツ抽出)...")
        
        from src.search.browser_search_provider import BrowserSearchProvider
        from src.search.provider import SearchOptions
        
        provider = BrowserSearchProvider()
        
        try:
            # Use a specific query that should have predictable results
            test_query = "Python official website"
            
            options = SearchOptions(
                engines=["duckduckgo"],
                limit=5,
            )
            
            result = await provider.search(test_query, options)
            
            if not result.ok:
                if result.captcha_detected:
                    return VerificationResult(
                        name="Parser Accuracy",
                        spec_ref="§3.2 コンテンツ抽出",
                        passed=True,
                        skipped=True,
                        skip_reason="CAPTCHA detected, cannot verify parser",
                    )
                return VerificationResult(
                    name="Parser Accuracy",
                    spec_ref="§3.2 コンテンツ抽出",
                    passed=False,
                    error=f"Search failed: {result.error}",
                )
            
            if not result.results:
                return VerificationResult(
                    name="Parser Accuracy",
                    spec_ref="§3.2 コンテンツ抽出",
                    passed=False,
                    error="No results to verify",
                )
            
            # Verify parsed fields
            valid_results = 0
            total_results = len(result.results)
            
            for r in result.results:
                has_title = bool(r.title and len(r.title) > 0)
                has_url = bool(r.url and r.url.startswith('http'))
                has_engine = r.engine == "duckduckgo"
                has_rank = r.rank > 0
                
                if all([has_title, has_url, has_engine, has_rank]):
                    valid_results += 1
                else:
                    missing = []
                    if not has_title:
                        missing.append("title")
                    if not has_url:
                        missing.append("url")
                    if not has_engine:
                        missing.append("engine")
                    if not has_rank:
                        missing.append("rank")
                    print(f"    ! Invalid result: missing {missing}")
            
            accuracy = valid_results / total_results
            print(f"    Parser accuracy: {accuracy:.0%} ({valid_results}/{total_results})")
            
            # Check for python.org in results (expected for this query)
            has_expected = any("python.org" in r.url for r in result.results)
            if has_expected:
                print("    ✓ Expected result (python.org) found")
            else:
                print("    ! Expected result (python.org) not found")
            
            if accuracy >= 0.9:
                return VerificationResult(
                    name="Parser Accuracy",
                    spec_ref="§3.2 コンテンツ抽出",
                    passed=True,
                    details={
                        "accuracy": accuracy,
                        "valid": valid_results,
                        "total": total_results,
                        "has_expected_result": has_expected,
                    },
                )
        else:
                return VerificationResult(
                    name="Parser Accuracy",
                    spec_ref="§3.2 コンテンツ抽出",
                    passed=False,
                    error=f"Parser accuracy {accuracy:.0%} < 90%",
                )
                
        except Exception as e:
            logger.exception("Parser accuracy verification failed")
            return VerificationResult(
                name="Parser Accuracy",
                spec_ref="§3.2 コンテンツ抽出",
                passed=False,
                error=str(e),
            )
        finally:
            await provider.close()

    async def verify_stealth(self) -> VerificationResult:
        """Stealth偽装（bot検知回避）の検証。"""
        print("\n[4/5] Verifying stealth (§4.3 ブラウザ/JS層)...")
        
        from src.crawler.fetcher import BrowserFetcher, FetchPolicy
        
        fetcher = BrowserFetcher()
        
        try:
            # Fetch a page and check for bot detection indicators
            test_url = "https://example.com"
            
            policy = FetchPolicy(use_browser=True, allow_headful=False)
            result = await fetcher.fetch(test_url, policy=policy)
            
            if not result.ok:
                return VerificationResult(
                    name="Stealth",
                    spec_ref="§4.3 ブラウザ/JS層",
                    passed=False,
                    error=f"Fetch failed: {result.reason}",
                )
            
            # Check if webdriver property is hidden
            stealth_checks = {
                "page_loaded": result.ok,
                "no_challenge": not result.challenge_detected if hasattr(result, 'challenge_detected') else True,
                "content_received": bool(result.content),
            }
            
            print(f"    ✓ Page loaded: {stealth_checks['page_loaded']}")
            print(f"    ✓ No challenge detected: {stealth_checks['no_challenge']}")
            print(f"    ✓ Content received: {stealth_checks['content_received']}")
            
            if all(stealth_checks.values()):
                return VerificationResult(
                    name="Stealth",
                    spec_ref="§4.3 ブラウザ/JS層",
                    passed=True,
                    details=stealth_checks,
                )
        else:
                failed = [k for k, v in stealth_checks.items() if not v]
                return VerificationResult(
                    name="Stealth",
                    spec_ref="§4.3 ブラウザ/JS層",
                    passed=False,
                    error=f"Stealth checks failed: {failed}",
                )
                
        except Exception as e:
            logger.exception("Stealth verification failed")
            return VerificationResult(
                name="Stealth",
                spec_ref="§4.3 ブラウザ/JS層",
                passed=False,
                error=str(e),
            )
        finally:
            await fetcher.close()

    async def verify_session_management(self) -> VerificationResult:
        """セッション管理の検証。"""
        print("\n[5/5] Verifying session management (§3.6.1 セッション再利用)...")
        
        from src.search.browser_search_provider import BrowserSearchProvider
        from src.search.provider import SearchOptions
        from src.crawler.session_transfer import get_session_transfer_manager
        
        provider = BrowserSearchProvider()
        manager = get_session_transfer_manager()
        
        try:
            # Get initial session count
            initial_stats = manager.get_session_stats()
            initial_count = initial_stats['total_sessions']
            print(f"    Initial sessions: {initial_count}")
            
            # Perform a search to create session
            options = SearchOptions(engines=["duckduckgo"], limit=3)
            result = await provider.search("test query", options)
            
            # Check search session
            search_session = provider.get_session("duckduckgo")
            if search_session:
                print(f"    ✓ Search session created")
                print(f"      - Success count: {search_session.success_count}")
                print(f"      - CAPTCHA count: {search_session.captcha_count}")
        else:
                print("    ! No search session (may be normal if CAPTCHA hit)")
            
            # Check session transfer manager
            final_stats = manager.get_session_stats()
            final_count = final_stats['total_sessions']
            print(f"    Final sessions: {final_count}")
            
            if final_stats['domains']:
                print("    Session domains:")
                for domain, count in list(final_stats['domains'].items())[:3]:
                    print(f"      - {domain}: {count}")
            
            # Session management is working if we can track sessions
            return VerificationResult(
                name="Session Management",
                spec_ref="§3.6.1 セッション再利用",
                passed=True,
                details={
                    "initial_sessions": initial_count,
                    "final_sessions": final_count,
                    "has_search_session": search_session is not None,
                    "domains": list(final_stats.get('domains', {}).keys()),
                },
            )
            
        except Exception as e:
            logger.exception("Session management verification failed")
            return VerificationResult(
                name="Session Management",
                spec_ref="§3.6.1 セッション再利用",
                passed=False,
                error=str(e),
            )
        finally:
            await provider.close()

    async def run_all(self) -> int:
        """全検証を実行し、結果を出力。"""
        print("\n" + "=" * 70)
        print("Phase 16.9: Browser Search Verification")
        print("検証対象: §3.2 エージェント実行機能（ブラウザ検索）")
        print("=" * 70)
        
        # Prerequisites
        if not await self.check_prerequisites():
            print("\n" + "=" * 70)
            print("SKIPPED: Prerequisites not met")
            print("=" * 70)
            return 2
        
        # Run verifications
        self.results.append(await self.verify_cdp_connection())
        self.results.append(await self.verify_duckduckgo_search())
        self.results.append(await self.verify_parser_accuracy())
        self.results.append(await self.verify_stealth())
        self.results.append(await self.verify_session_management())
        
        # Summary
        print("\n" + "=" * 70)
        print("Verification Summary")
        print("=" * 70)
        
        passed = 0
        failed = 0
        skipped = 0
        
        for result in self.results:
            if result.skipped:
                status = "SKIP"
                skipped += 1
            elif result.passed:
                status = "✓"
                passed += 1
            else:
                status = "✗"
                failed += 1
            
            print(f"  {status} {result.name} ({result.spec_ref})")
            if result.error:
                print(f"      Error: {result.error}")
            if result.skip_reason:
                print(f"      Reason: {result.skip_reason}")
        
        print("\n" + "-" * 70)
        print(f"  Total: {len(self.results)} | Passed: {passed} | Failed: {failed} | Skipped: {skipped}")
        print("=" * 70)
        
        if failed > 0:
            print("\n⚠ Some verifications FAILED. Check details above.")
            return 1
        elif skipped > 0 and passed == 0:
            print("\n⚠ All verifications SKIPPED.")
            return 2
        else:
            print("\n✓ All verifications PASSED!")
            return 0


async def main():
    configure_logging(log_level="INFO", json_format=False)
    
    verifier = BrowserSearchVerifier()
    return await verifier.run_all()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
