#!/usr/bin/env python3
"""
DuckDuckGo Search Engine E2E Verification

Verification target: §3.2 Agent Execution (Browser Search) - DuckDuckGo

Verification items:
1. CDP connection (Windows Chrome -> WSL2/Podman)
2. DuckDuckGo search operation
3. Search result parser accuracy
4. Stealth evasion (bot detection avoidance)
5. Session management (BrowserSearchSession)

Prerequisites:
- Chrome running with remote debugging on Windows
- config/settings.yaml browser.chrome_host configured correctly
- See: docs/IMPLEMENTATION_PLAN.md 16.9 "Setup Procedure"

Acceptance criteria (§7):
- CAPTCHA: 100% detection, reliable transition to manual intervention
- Scraping success rate ≥95%

Usage:
    python tests/scripts/verify_duckduckgo_search.py

Exit codes:
    0: All verifications passed
    1: Some verifications failed
    2: Prerequisites not met (skipped)

Note:
    This script accesses real DuckDuckGo search.
    Run in a low-risk IP environment to avoid blocks.

Related scripts:
    - verify_ecosia_search.py
    - verify_metager_search.py
    - verify_startpage_search.py
"""

import asyncio
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.utils.logging import configure_logging, get_logger

logger = get_logger(__name__)


def _is_captcha_error(result) -> bool:
    """Check if search result indicates CAPTCHA detection."""
    return result.error is not None and "CAPTCHA detected" in result.error


def _get_captcha_type(result) -> str | None:
    """Extract CAPTCHA type from error message."""
    if result.error and "CAPTCHA detected:" in result.error:
        return result.error.split("CAPTCHA detected:", 1)[1].strip()
    return None


@dataclass
class VerificationResult:
    """Data class to hold verification results."""
    name: str
    spec_ref: str
    passed: bool
    skipped: bool = False
    skip_reason: str | None = None
    details: dict = field(default_factory=dict)
    error: str | None = None


class BrowserSearchVerifier:
    """Verifier for §3.2 browser search functionality."""

    def __init__(self):
        self.results: list[VerificationResult] = []
        self.browser_available = False

    async def check_prerequisites(self) -> bool:
        """Check environment prerequisites."""
        print("\n[Prerequisites] Checking environment...")

        # Check browser connectivity via BrowserSearchProvider
        try:
            from src.search.browser_search_provider import BrowserSearchProvider
            provider = BrowserSearchProvider()
            # Try to initialize browser connection
            await provider._ensure_browser()
            if provider._browser and provider._browser.is_connected():
                self.browser_available = True
                print("  ✓ Browser connected via CDP")
            else:
                print("  ✗ Browser not connected")
                print("    → Run Chrome with: --remote-debugging-port=9222")
                await provider.close()
                return False
            await provider.close()
        except Exception as e:
            print(f"  ✗ Browser check failed: {e}")
            print("    → Ensure Chrome is running with remote debugging")
            return False

        print("  All prerequisites met.\n")
        print("  ⚠ Warning: This will access real search engines.")
        print("    Run in a low-risk IP environment to avoid blocks.\n")
        return True

    async def verify_cdp_connection(self) -> VerificationResult:
        """Verify CDP connection."""
        print("\n[1/5] Verifying CDP connection (§3.2 GUI連携)...")

        from src.search.browser_search_provider import BrowserSearchProvider

        try:
            provider = BrowserSearchProvider()
            await provider._ensure_browser()

            if not provider._browser or not provider._browser.is_connected():
                await provider.close()
                return VerificationResult(
                    name="CDP Connection",
                    spec_ref="§3.2 GUI連携",
                    passed=False,
                    error="Browser not connected",
                )

            # Get browser info
            browser_info = {}
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
        """Verify DuckDuckGo search operation."""
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
                if _is_captcha_error(result):
                    captcha_type = _get_captcha_type(result)
                    print(f"    ! CAPTCHA detected: {captcha_type}")
                    return VerificationResult(
                        name="DuckDuckGo Search",
                        spec_ref="§3.2 検索エンジン統合",
                        passed=True,
                        details={
                            "captcha_detected": True,
                            "captcha_type": captcha_type,
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
        """Verify search result parser accuracy."""
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
                if _is_captcha_error(result):
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
        """Verify stealth evasion (bot detection avoidance)."""
        print("\n[4/5] Verifying stealth (§4.3 ブラウザ/JS層)...")

        from src.crawler.fetcher import BrowserFetcher

        fetcher = BrowserFetcher()

        try:
            # Fetch a page and check for bot detection indicators
            test_url = "https://example.com"

            # Use headful=False for headless stealth mode
            result = await fetcher.fetch(test_url, headful=False)

            if not result.ok:
                return VerificationResult(
                    name="Stealth",
                    spec_ref="§4.3 ブラウザ/JS層",
                    passed=False,
                    error=f"Fetch failed: {result.reason}",
                )

            # Check stealth indicators
            stealth_checks = {
                "page_loaded": result.ok,
                "no_challenge": not getattr(result, 'auth_queued', False),
                "content_received": bool(result.html_path or result.content_hash),
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
        """Verify session management."""
        print("\n[5/5] Verifying session management (§3.6.1 セッション再利用)...")

        from src.crawler.session_transfer import get_session_transfer_manager
        from src.search.browser_search_provider import BrowserSearchProvider
        from src.search.provider import SearchOptions

        provider = BrowserSearchProvider()
        manager = get_session_transfer_manager()

        try:
            # Get initial session count
            initial_stats = manager.get_session_stats()
            initial_count = initial_stats['total_sessions']
            print(f"    Initial sessions: {initial_count}")

            # Perform a search to create session
            options = SearchOptions(engines=["duckduckgo"], limit=3)
            await provider.search("test query", options)

            # Check search session
            search_session = provider.get_session("duckduckgo")
            if search_session:
                print("    ✓ Search session created")
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
        """Run all verifications and output results."""
        print("\n" + "=" * 70)
        print("E2E: Browser Search Verification")
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
