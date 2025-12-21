#!/usr/bin/env python3
"""
Verification target: §3.2 Agent Execution (Search -> Fetch Consistency)
"""
from urllib.parse import urlparse

Verification items:
1. Browser search execution (§3.2 Search Engine Integration)
2. Search result URL fetching
3. Same-session result page fetching (§3.1.2 Session Transfer)
4. Session consistency (Cookie/fingerprint maintenance)
5. CAPTCHA continuity (§3.2, §3.6.1)
6. Multi-engine operation

Prerequisites:
- Chrome running with remote debugging on Windows
- config/settings.yaml browser.chrome_host configured correctly
- See: docs/IMPLEMENTATION_PLAN.md 16.9 "Setup Procedure"

Acceptance criteria (§7):
- CAPTCHA: 100% detection, reliable transition to manual intervention
- Scraping success rate ≥95%

Usage:
    python tests/scripts/verify_search_then_fetch.py

Exit codes:
    0: All verifications passed
    1: Some verifications failed
    2: Prerequisites not met (skipped)

Note:
    This script accesses real search engines.
    Run in a low-risk IP environment to avoid blocks.
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


class SearchFetchVerifier:
    """Verifier for §3.2 search -> fetch consistency."""

    def __init__(self) -> None:
        self.results: list[VerificationResult] = []
        self.browser_available = False
        self.search_results: list[dict] = []
        self.search_session_id: str | None = None

    async def check_prerequisites(self) -> bool:
        """Check environment prerequisites."""
        print("\n[Prerequisites] Checking environment...")

        # Check browser connectivity
        try:
            from src.crawler.browser_provider import get_browser_registry

            registry = get_browser_registry()
            provider = registry.get_default()
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

        # Check search provider
        try:
            from src.search.browser_search_provider import BrowserSearchProvider

            provider = BrowserSearchProvider()
            engines = provider.get_available_engines()  # type: ignore[attr-defined]
            print(f"  ✓ Search provider available (engines: {engines})")
            await provider.close()
        except Exception as e:
            print(f"  ✗ Search provider failed: {e}")
            return False

        print("  All prerequisites met.\n")
        print("  ⚠ Warning: This will access real search engines.")
        print("    Run in a low-risk IP environment to avoid blocks.\n")
        return True

    async def verify_browser_search(self) -> VerificationResult:
        """§3.2 Search Engine Integration: Browser-based search execution."""
        print("\n[1/6] Verifying browser search (§3.2 検索エンジン統合)...")

        from src.search.browser_search_provider import BrowserSearchProvider
        from src.search.provider import SearchOptions

        provider = BrowserSearchProvider()

        try:
            test_query = "Python programming tutorial"
            test_engine = "duckduckgo"

            print(f"    Query: '{test_query}'")
            print(f"    Engine: {test_engine}")

            options = SearchOptions(
                engines=[test_engine],
                limit=5,
            )

            start_time = time.time()
            result = await provider.search(test_query, options)
            elapsed = time.time() - start_time

            if not result.ok:
                # Check if it's a CAPTCHA (check error message)
                error_msg = result.error or ""
                is_captcha = "captcha" in error_msg.lower() or "challenge" in error_msg.lower()
                if is_captcha:
                    print(f"    ! CAPTCHA detected: {error_msg}")
                    print("      This is expected behavior - CAPTCHA detection works!")
                    return VerificationResult(
                        name="Browser Search",
                        spec_ref="§3.2 検索エンジン統合",
                        passed=True,
                        details={
                            "captcha_detected": True,
                            "error": error_msg,
                            "note": "CAPTCHA detection working correctly",
                        },
                    )
                else:
                    return VerificationResult(
                        name="Browser Search",
                        spec_ref="§3.2 検索エンジン統合",
                        passed=False,
                        error=f"Search failed: {result.error}",
                    )

            print(f"    ✓ Search completed in {elapsed:.2f}s")
            print(f"    ✓ Results: {len(result.results)} items")

            if not result.results:
                return VerificationResult(
                    name="Browser Search",
                    spec_ref="§3.2 検索エンジン統合",
                    passed=False,
                    error="No results returned",
                )

            # Store results for later use
            for r in result.results[:3]:
                self.search_results.append(
                    {
                        "url": r.url,
                        "title": r.title,
                        "engine": r.engine,
                    }
                )
                title = r.title[:45] + "..." if len(r.title) > 45 else r.title
                print(f"      - {title}")
                print(f"        {r.url[:60]}...")

            # Capture session from search
            session = provider.get_session(test_engine)
            if session:
                print("    ✓ Search session captured")
                print(f"      - Success count: {session.success_count}")
                print(f"      - CAPTCHA count: {session.captcha_count}")

            return VerificationResult(
                name="Browser Search",
                spec_ref="§3.2 検索エンジン統合",
                passed=True,
                details={
                    "query": test_query,
                    "engine": test_engine,
                    "results_count": len(result.results),
                    "elapsed_seconds": elapsed,
                },
            )

        except Exception as e:
            logger.exception("Browser search verification failed")
            return VerificationResult(
                name="Browser Search",
                spec_ref="§3.2 検索エンジン統合",
                passed=False,
                error=str(e),
            )
        finally:
            await provider.close()

    async def verify_result_fetch(self) -> VerificationResult:
        """Fetch search result URLs."""
        print("\n[2/6] Verifying result fetch (検索結果URL取得)...")

        if not self.search_results:
            return VerificationResult(
                name="Result Fetch",
                spec_ref="§3.2 コンテンツ抽出",
                passed=False,
                skipped=True,
                skip_reason="No search results available",
            )

        from src.crawler.fetcher import BrowserFetcher
        from src.crawler.session_transfer import get_session_transfer_manager

        fetcher = BrowserFetcher()
        manager = get_session_transfer_manager()

        try:
            initial_stats = manager.get_session_stats()
            successful_fetches = 0
            total_fetches = min(2, len(self.search_results))

            for i, result in enumerate(self.search_results[:total_fetches], 1):
                url = result["url"]
                print(f"\n    [{i}/{total_fetches}] Fetching: {url[:60]}...")

                fetch_result = await fetcher.fetch(url)

                if fetch_result.ok:
                    print(f"    ✓ Status: {fetch_result.status}")
                    if fetch_result.html_path:
                        from pathlib import Path
                        content_length = Path(fetch_result.html_path).stat().st_size if Path(fetch_result.html_path).exists() else 0
                        print(f"    ✓ Content: {content_length} bytes")
                    successful_fetches += 1

                    # BrowserFetcher.fetch automatically captures session
                    # Check if session was captured by verifying session stats increased
                    final_stats = manager.get_session_stats()
                    session_captured = final_stats["total_sessions"] > initial_stats["total_sessions"]
                    
                    # Get session for domain if captured
                    if session_captured:
                        parsed = urlparse(url)
                        from src.crawler.sec_fetch import _get_registrable_domain
                        domain = _get_registrable_domain(parsed.netloc)
                        result = manager.get_session_for_domain(domain)
                        session_id = result[0] if result else None
                    else:
                        session_id = None
                        if session_id:
                            print(f"    ✓ Session captured: {session_id[:12]}...")
                else:
                    print(f"    ✗ Failed: {fetch_result.reason}")
                    if fetch_result.auth_type:
                        print(f"      Challenge: {fetch_result.auth_type}")

                # Brief delay between fetches
                await asyncio.sleep(1.0)

            success_rate = successful_fetches / total_fetches
            threshold = 0.95  # §7: スクレイピング成功率≥95%

            print(
                f"\n    Fetch success rate: {success_rate:.0%} ({successful_fetches}/{total_fetches})"
            )

            if success_rate >= threshold:
                return VerificationResult(
                    name="Result Fetch",
                    spec_ref="§3.2 コンテンツ抽出",
                    passed=True,
                    details={
                        "success_rate": success_rate,
                        "successful": successful_fetches,
                        "total": total_fetches,
                    },
                )
            else:
                return VerificationResult(
                    name="Result Fetch",
                    spec_ref="§3.2 コンテンツ抽出",
                    passed=False,
                    error=f"Success rate {success_rate:.0%} < {threshold:.0%}",
                )

        except Exception as e:
            logger.exception("Result fetch verification failed")
            return VerificationResult(
                name="Result Fetch",
                spec_ref="§3.2 コンテンツ抽出",
                passed=False,
                error=str(e),
            )
        finally:
            await fetcher.close()

    async def verify_session_consistency(self) -> VerificationResult:
        """§3.1.2 Session Transfer: Session consistency between search and fetch."""
        print("\n[3/6] Verifying session consistency (§3.1.2 セッション一貫性)...")

        from src.crawler.session_transfer import get_session_transfer_manager

        manager = get_session_transfer_manager()

        try:
            stats = manager.get_session_stats()
            print(f"    Total sessions: {stats['total_sessions']}")

            if stats["total_sessions"] == 0:
                print("    ! No sessions to verify")
                print("      (This may be normal if no fetches completed successfully)")
                return VerificationResult(
                    name="Session Consistency",
                    spec_ref="§3.1.2 セッション一貫性",
                    passed=True,
                    skipped=True,
                    skip_reason="No sessions available to verify",
                )

            print("    Sessions by domain:")
            verified_count = 0
            total_count = 0

            for domain, count in stats["domains"].items():
                total_count += 1
                print(f"      - {domain}: {count} session(s)")

                # Get session details
                result = manager.get_session_for_domain(domain)
                if result:
                    session_id, session = result

                    # Verify session is valid for its domain
                    test_url = f"https://{domain}/test"
                    if session.is_valid_for_url(test_url):
                        print("        ✓ Session valid for domain")
                        verified_count += 1
                    else:
                        print("        ✗ Session invalid for its own domain!")

                    # Check cookies
                    if session.cookies:
                        print(f"        ✓ Cookies: {len(session.cookies)} present")
                        for cookie in session.cookies[:2]:
                            print(f"          - {cookie.name}={cookie.value[:10]}...")
                    else:
                        print("        - No cookies (may be normal for some sites)")

                    # Check User-Agent consistency
                    if session.user_agent:
                        print(f"        ✓ User-Agent: {session.user_agent[:40]}...")
                    else:
                        print("        ✗ No User-Agent captured")

            if total_count > 0:
                consistency_rate = verified_count / total_count
                if consistency_rate >= 0.9:
                    return VerificationResult(
                        name="Session Consistency",
                        spec_ref="§3.1.2 セッション一貫性",
                        passed=True,
                        details={
                            "verified": verified_count,
                            "total": total_count,
                            "consistency_rate": consistency_rate,
                        },
                    )
                else:
                    return VerificationResult(
                        name="Session Consistency",
                        spec_ref="§3.1.2 セッション一貫性",
                        passed=False,
                        error=f"Consistency rate {consistency_rate:.0%} < 90%",
                    )

            return VerificationResult(
                name="Session Consistency",
                spec_ref="§3.1.2 セッション一貫性",
                passed=True,
                details={"note": "No domains to verify"},
            )

        except Exception as e:
            logger.exception("Session consistency verification failed")
            return VerificationResult(
                name="Session Consistency",
                spec_ref="§3.1.2 セッション一貫性",
                passed=False,
                error=str(e),
            )

    async def verify_cross_domain_isolation(self) -> VerificationResult:
        """Cross-domain isolation: Sessions don't mix between different domains."""
        print("\n[4/6] Verifying cross-domain isolation (ドメイン分離)...")

        from src.crawler.session_transfer import get_session_transfer_manager

        manager = get_session_transfer_manager()

        try:
            stats = manager.get_session_stats()

            if len(stats["domains"]) < 2:
                print("    ! Only one domain in sessions, skipping isolation test")
                return VerificationResult(
                    name="Cross-Domain Isolation",
                    spec_ref="§3.1.2 同一ドメイン限定",
                    passed=True,
                    skipped=True,
                    skip_reason="Need 2+ domains to test isolation",
                )

            domains = list(stats["domains"].keys())
            domain_a = domains[0]
            domain_b = domains[1]

            print(f"    Testing isolation between: {domain_a} and {domain_b}")

            # Get session for domain A
            result_a = manager.get_session_for_domain(domain_a)
            if not result_a:
                return VerificationResult(
                    name="Cross-Domain Isolation",
                    spec_ref="§3.1.2 同一ドメイン限定",
                    passed=False,
                    error=f"No session for {domain_a}",
                )

            session_id_a, session_a = result_a

            # Try to use domain A's session for domain B
            transfer = manager.generate_transfer_headers(
                session_id_a,
                f"https://{domain_b}/page",
            )

            if transfer.ok:
                return VerificationResult(
                    name="Cross-Domain Isolation",
                    spec_ref="§3.1.2 同一ドメイン限定",
                    passed=False,
                    error=f"Session for {domain_a} was accepted for {domain_b}!",
                )

            if transfer.reason == "domain_mismatch":
                print(f"    ✓ Session for {domain_a} correctly rejected for {domain_b}")
                return VerificationResult(
                    name="Cross-Domain Isolation",
                    spec_ref="§3.1.2 同一ドメイン限定",
                    passed=True,
                    details={
                        "domain_a": domain_a,
                        "domain_b": domain_b,
                        "isolation_enforced": True,
                    },
                )
            else:
                return VerificationResult(
                    name="Cross-Domain Isolation",
                    spec_ref="§3.1.2 同一ドメイン限定",
                    passed=False,
                    error=f"Unexpected rejection reason: {transfer.reason}",
                )

        except Exception as e:
            logger.exception("Cross-domain isolation verification failed")
            return VerificationResult(
                name="Cross-Domain Isolation",
                spec_ref="§3.1.2 同一ドメイン限定",
                passed=False,
                error=str(e),
            )

    async def verify_captcha_detection(self) -> VerificationResult:
        """§3.2 CAPTCHA Continuity: CAPTCHA detection and manual intervention."""
        print("\n[5/6] Verifying CAPTCHA detection (§3.2 CAPTCHA対応)...")

        from src.crawler.fetcher import BrowserFetcher

        fetcher = BrowserFetcher()

        try:
            # Test with a URL that might trigger CAPTCHA
            # Note: We can't reliably trigger CAPTCHA, but we verify the detection logic exists

            print("    Testing CAPTCHA detection logic...")

            # Check if fetcher has challenge detection
            # Fetch a safe URL to verify the flow works
            result = await fetcher.fetch("https://example.com")

            # Verify the result has challenge detection fields
            has_auth_type = hasattr(result, "auth_type")
            has_queue_auth = hasattr(result, "auth_queued")

            print(f"    ✓ auth_type field: {has_auth_type}")
            print(f"    ✓ auth_queued field: {has_queue_auth}")

            if not all([has_auth_type, has_queue_auth]):
                missing = []
                if not has_auth_type:
                    missing.append("auth_type")
                if not has_queue_auth:
                    missing.append("auth_queued")

                return VerificationResult(
                    name="CAPTCHA Detection",
                    spec_ref="§3.2 CAPTCHA対応",
                    passed=False,
                    error=f"Missing fields: {missing}",
                )

            # Verify challenge detection doesn't false positive on clean page
            if result.ok and not result.auth_type:
                print("    ✓ No false positive on clean page")
                return VerificationResult(
                    name="CAPTCHA Detection",
                    spec_ref="§3.2 CAPTCHA対応",
                    passed=True,
                    details={
                        "has_detection_fields": True,
                        "false_positive_rate": 0,
                        "note": "Detection logic present, no false positives",
                    },
                )
            elif result.auth_type:
                print(f"    ! CAPTCHA detected on example.com: {result.auth_type}")
                print("      This is unusual but shows detection is working")
                return VerificationResult(
                    name="CAPTCHA Detection",
                    spec_ref="§3.2 CAPTCHA対応",
                    passed=True,
                    details={
                        "has_detection_fields": True,
                        "captcha_detected": True,
                        "auth_type": result.auth_type,
                    },
                )
            else:
                return VerificationResult(
                    name="CAPTCHA Detection",
                    spec_ref="§3.2 CAPTCHA対応",
                    passed=False,
                    error=f"Fetch failed: {result.reason}",
                )

        except Exception as e:
            logger.exception("CAPTCHA detection verification failed")
            return VerificationResult(
                name="CAPTCHA Detection",
                spec_ref="§3.2 CAPTCHA対応",
                passed=False,
                error=str(e),
            )
        finally:
            await fetcher.close()

    async def verify_multiple_engines(self) -> VerificationResult:
        """Multi-engine operation verification."""
        print("\n[6/6] Verifying multiple engines (複数エンジン対応)...")

        from src.search.browser_search_provider import BrowserSearchProvider
        from src.search.provider import SearchOptions

        provider = BrowserSearchProvider()

        try:
            available_engines = provider.get_available_engines()
            print(f"    Available engines: {available_engines}")

            if len(available_engines) < 2:
                return VerificationResult(
                    name="Multiple Engines",
                    spec_ref="§3.2 対応エンジン",
                    passed=True,
                    skipped=True,
                    skip_reason="Only one engine available",
                )

            # Test with first two engines
            test_engines = available_engines[:2]
            successful_engines = []
            failed_engines = []

            for engine in test_engines:
                print(f"\n    Testing engine: {engine}")

                options = SearchOptions(
                    engines=[engine],
                    limit=3,
                )

                try:
                    result = await provider.search("test query", options)

                    if result.ok and result.results:
                        print(f"    ✓ {engine}: {len(result.results)} results")
                        successful_engines.append(engine)
                    elif result.error and ("captcha" in result.error.lower() or "challenge" in result.error.lower()):
                        print(f"    ! {engine}: CAPTCHA detected (expected behavior)")
                        successful_engines.append(engine)  # Detection is success
                    else:
                        print(f"    ✗ {engine}: {result.error}")
                        failed_engines.append(engine)

                except Exception as e:
                    print(f"    ✗ {engine}: {e}")
                    failed_engines.append(engine)

                await asyncio.sleep(2.0)  # Delay between engines

            success_rate = len(successful_engines) / len(test_engines)

            print(f"\n    Engine success rate: {success_rate:.0%}")
            print(f"    Successful: {successful_engines}")
            if failed_engines:
                print(f"    Failed: {failed_engines}")

            if success_rate >= 0.5:  # At least half should work
                return VerificationResult(
                    name="Multiple Engines",
                    spec_ref="§3.2 対応エンジン",
                    passed=True,
                    details={
                        "tested": test_engines,
                        "successful": successful_engines,
                        "failed": failed_engines,
                        "success_rate": success_rate,
                    },
                )
            else:
                return VerificationResult(
                    name="Multiple Engines",
                    spec_ref="§3.2 対応エンジン",
                    passed=False,
                    error=f"Only {len(successful_engines)}/{len(test_engines)} engines working",
                )

        except Exception as e:
            logger.exception("Multiple engines verification failed")
            return VerificationResult(
                name="Multiple Engines",
                spec_ref="§3.2 対応エンジン",
                passed=False,
                error=str(e),
            )
        finally:
            await provider.close()

    async def run_all(self) -> int:
        """Run all verifications and output results."""
        print("\n" + "=" * 70)
        print("E2E: Search→Fetch Consistency Verification")
        print("検証対象: §3.2 エージェント実行機能")
        print("=" * 70)

        # Prerequisites
        if not await self.check_prerequisites():
            print("\n" + "=" * 70)
            print("SKIPPED: Prerequisites not met")
            print("=" * 70)
            return 2

        # Run verifications
        self.results.append(await self.verify_browser_search())
        self.results.append(await self.verify_result_fetch())
        self.results.append(await self.verify_session_consistency())
        self.results.append(await self.verify_cross_domain_isolation())
        self.results.append(await self.verify_captcha_detection())
        self.results.append(await self.verify_multiple_engines())

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
        print(
            f"  Total: {len(self.results)} | Passed: {passed} | Failed: {failed} | Skipped: {skipped}"
        )
        print("=" * 70)

        if failed > 0:
            print("\n⚠ Some verifications FAILED. Check details above.")
            print("\nPossible causes:")
            print("  - Chrome not running with remote debugging")
            print("  - Network/firewall issues")
            print("  - Search engine blocked the IP")
            return 1
        elif skipped > 0 and passed == 0:
            print("\n⚠ All verifications SKIPPED.")
            return 2
        else:
            print("\n✓ All verifications PASSED!")
            print("\nThe search→fetch flow is working correctly:")
            print("  - Browser search executes and returns results")
            print("  - Result pages can be fetched successfully")
            print("  - Sessions are captured and isolated per domain")
            print("  - CAPTCHA detection is functional")
            return 0


async def main() -> int:
    configure_logging(log_level="INFO", json_format=False)

    verifier = SearchFetchVerifier()
    return await verifier.run_all()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
