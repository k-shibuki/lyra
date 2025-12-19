#!/usr/bin/env python3
"""
Bing Search Engine E2E Verification

Verification target: §3.2 Agent Execution (Browser Search) - Bing

Bing characteristics:
- Microsoft's search engine
- High block risk (aggressive bot detection)
- Very low priority (priority: 10 in engines.yaml)
- Daily limit: 10 queries
- Last-mile engine (use only when others fail)
- Consider using Ecosia instead (Bing-based, more lenient)

Verification items:
1. CDP connection
2. Bing search operation
3. Search result parser accuracy (BingParser)
4. CAPTCHA detection

Prerequisites:
- Chrome running with remote debugging on Windows
- config/settings.yaml browser.chrome_host configured correctly

Acceptance criteria (§7):
- CAPTCHA: 100% detection
- Scraping success rate ≥95% (when not blocked)

Usage:
    python tests/scripts/verify_bing_search.py

Exit codes:
    0: All verifications passed
    1: Some verifications failed
    2: Prerequisites not met (skipped)

WARNING:
    Bing has aggressive bot detection!
    - CAPTCHA is expected and considered success
    - Daily limit: 10 queries
    - Prefer Ecosia for Bing results (more lenient)

Related scripts:
    - verify_ecosia_search.py (Bing proxy, safer)
    - verify_duckduckgo_search.py
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


class BingSearchVerifier:
    """Verifier for Bing search functionality."""

    ENGINE_NAME = "bing"
    ENGINE_DISPLAY = "Bing"

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

        # Check parser availability
        from src.search.search_parsers import get_parser

        parser = get_parser(self.ENGINE_NAME)
        if parser:
            print(f"  ✓ {self.ENGINE_DISPLAY} parser available")
        else:
            print(f"  ✗ {self.ENGINE_DISPLAY} parser not found")
            return False

        print("  All prerequisites met.\n")
        print(f"  ⚠ WARNING: {self.ENGINE_DISPLAY} has aggressive bot detection!")
        print("    - CAPTCHA is expected and counts as successful detection")
        print("    - Daily limit: 10 queries")
        print("    - Prefer Ecosia for Bing results (more lenient)\n")
        return True

    async def verify_cdp_connection(self) -> VerificationResult:
        """Verify CDP connection."""
        print("\n[1/4] Verifying CDP connection...")

        from src.search.browser_search_provider import BrowserSearchProvider

        try:
            provider = BrowserSearchProvider()
            await provider._ensure_browser()

            if not provider._browser or not provider._browser.is_connected():
                await provider.close()
                return VerificationResult(
                    name="CDP Connection",
                    spec_ref="§3.2",
                    passed=False,
                    error="Browser not connected",
                )

            browser_info = {"connected": provider._browser.is_connected()}
            print(f"    ✓ Browser connected: {browser_info.get('connected', False)}")
            await provider.close()

            return VerificationResult(
                name="CDP Connection",
                spec_ref="§3.2",
                passed=True,
                details=browser_info,
            )

        except Exception as e:
            logger.exception("CDP connection verification failed")
            return VerificationResult(
                name="CDP Connection",
                spec_ref="§3.2",
                passed=False,
                error=str(e),
            )

    async def verify_search(self) -> VerificationResult:
        """Verify Bing search operation."""
        print(f"\n[2/4] Verifying {self.ENGINE_DISPLAY} search...")
        print("    ⚠ CAPTCHA is expected - counts as successful detection")

        from src.search.browser_search_provider import BrowserSearchProvider
        from src.search.provider import SearchOptions

        provider = BrowserSearchProvider()

        try:
            test_query = "Microsoft Windows operating system"

            print(f"    Query: '{test_query}'")

            options = SearchOptions(
                engines=[self.ENGINE_NAME],
                limit=5,
                time_range=None,
            )

            start_time = time.time()
            result = await provider.search(test_query, options)
            elapsed = time.time() - start_time

            if not result.ok:
                if _is_captcha_error(result):
                    captcha_type = _get_captcha_type(result)
                    print(f"    ✓ CAPTCHA detected (expected): {captcha_type}")
                    return VerificationResult(
                        name=f"{self.ENGINE_DISPLAY} Search",
                        spec_ref="§3.2",
                        passed=True,
                        details={
                            "captcha_detected": True,
                            "captcha_type": captcha_type,
                            "note": "CAPTCHA expected for Bing - detection working",
                        },
                    )
                else:
                    return VerificationResult(
                        name=f"{self.ENGINE_DISPLAY} Search",
                        spec_ref="§3.2",
                        passed=False,
                        error=f"Search failed: {result.error}",
                    )

            print(f"    ✓ Search completed in {elapsed:.2f}s (no CAPTCHA!)")
            print(f"    ✓ Results: {len(result.results)} items")

            if not result.results:
                return VerificationResult(
                    name=f"{self.ENGINE_DISPLAY} Search",
                    spec_ref="§3.2",
                    passed=False,
                    error="No results returned",
                )

            # Display first few results
            for i, r in enumerate(result.results[:3], 1):
                title = r.title[:45] + "..." if len(r.title) > 45 else r.title
                print(f"      {i}. {title}")
                print(f"         {r.url[:55]}...")

            return VerificationResult(
                name=f"{self.ENGINE_DISPLAY} Search",
                spec_ref="§3.2",
                passed=True,
                details={
                    "query": test_query,
                    "results_count": len(result.results),
                    "elapsed_seconds": elapsed,
                    "captcha_detected": False,
                },
            )

        except Exception as e:
            logger.exception(f"{self.ENGINE_DISPLAY} search verification failed")
            return VerificationResult(
                name=f"{self.ENGINE_DISPLAY} Search",
                spec_ref="§3.2",
                passed=False,
                error=str(e),
            )
        finally:
            await provider.close()

    async def verify_parser_accuracy(self) -> VerificationResult:
        """Verify search result parser accuracy."""
        print("\n[3/4] Verifying parser accuracy...")

        from src.search.browser_search_provider import BrowserSearchProvider
        from src.search.provider import SearchOptions

        provider = BrowserSearchProvider()

        try:
            test_query = "Wikipedia encyclopedia"

            options = SearchOptions(
                engines=[self.ENGINE_NAME],
                limit=5,
            )

            result = await provider.search(test_query, options)

            if not result.ok:
                if _is_captcha_error(result):
                    return VerificationResult(
                        name="Parser Accuracy",
                        spec_ref="§3.2",
                        passed=True,
                        skipped=True,
                        skip_reason="CAPTCHA detected (expected for Bing)",
                    )
                return VerificationResult(
                    name="Parser Accuracy",
                    spec_ref="§3.2",
                    passed=False,
                    error=f"Search failed: {result.error}",
                )

            if not result.results:
                return VerificationResult(
                    name="Parser Accuracy",
                    spec_ref="§3.2",
                    passed=False,
                    error="No results to verify",
                )

            # Verify parsed fields
            valid_results = 0
            total_results = len(result.results)

            for r in result.results:
                has_title = bool(r.title and len(r.title) > 0)
                has_url = bool(r.url and r.url.startswith("http"))
                has_engine = r.engine == self.ENGINE_NAME
                has_rank = r.rank > 0

                if all([has_title, has_url, has_engine, has_rank]):
                    valid_results += 1

            accuracy = valid_results / total_results
            print(f"    Parser accuracy: {accuracy:.0%} ({valid_results}/{total_results})")

            # Check for wikipedia.org in results
            has_expected = any("wikipedia.org" in r.url for r in result.results)
            if has_expected:
                print("    ✓ Expected result (wikipedia.org) found")
            else:
                print("    ! Expected result (wikipedia.org) not found")

            if accuracy >= 0.9:
                return VerificationResult(
                    name="Parser Accuracy",
                    spec_ref="§3.2",
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
                    spec_ref="§3.2",
                    passed=False,
                    error=f"Parser accuracy {accuracy:.0%} < 90%",
                )

        except Exception as e:
            logger.exception("Parser accuracy verification failed")
            return VerificationResult(
                name="Parser Accuracy",
                spec_ref="§3.2",
                passed=False,
                error=str(e),
            )
        finally:
            await provider.close()

    async def verify_captcha_detection(self) -> VerificationResult:
        """Verify CAPTCHA detection capability."""
        print("\n[4/4] Verifying CAPTCHA detection...")

        from src.search.search_parsers import get_parser

        try:
            parser = get_parser(self.ENGINE_NAME)
            if not parser:
                return VerificationResult(
                    name="CAPTCHA Detection",
                    spec_ref="§3.6.1",
                    passed=False,
                    error="Parser not available",
                )

            # Test with known CAPTCHA patterns
            test_cases = [
                ("<html><body><div class='g-recaptcha'></div></body></html>", True, "recaptcha"),
                ("<html><body>unusual traffic from your network</body></html>", True, "rate_limit"),
                ("<html><body>automated queries</body></html>", True, "blocked"),
                ("<html><body>captcha required</body></html>", True, "captcha"),
                ("<html><body>Normal search results</body></html>", False, None),
            ]

            all_passed = True
            for html, expected_captcha, _expected_type in test_cases:
                is_captcha, captcha_type = parser.detect_captcha(html)
                if is_captcha != expected_captcha:
                    all_passed = False
                    print(f"    ✗ Detection mismatch for: {html[:40]}...")

            if all_passed:
                print("    ✓ CAPTCHA patterns correctly detected")
                return VerificationResult(
                    name="CAPTCHA Detection",
                    spec_ref="§3.6.1",
                    passed=True,
                    details={"test_cases": len(test_cases)},
                )
            else:
                return VerificationResult(
                    name="CAPTCHA Detection",
                    spec_ref="§3.6.1",
                    passed=False,
                    error="Some CAPTCHA patterns not detected",
                )

        except Exception as e:
            logger.exception("CAPTCHA detection verification failed")
            return VerificationResult(
                name="CAPTCHA Detection",
                spec_ref="§3.6.1",
                passed=False,
                error=str(e),
            )

    async def run_all(self) -> int:
        """Run all verifications and output results."""
        print("\n" + "=" * 70)
        print(f"E2E: {self.ENGINE_DISPLAY} Search Verification")
        print("検証対象: §3.2 エージェント実行機能（ブラウザ検索）")
        print("⚠ HIGH BLOCK RISK - CAPTCHA expected")
        print("=" * 70)

        # Prerequisites
        if not await self.check_prerequisites():
            print("\n" + "=" * 70)
            print("SKIPPED: Prerequisites not met")
            print("=" * 70)
            return 2

        # Run verifications
        self.results.append(await self.verify_cdp_connection())
        self.results.append(await self.verify_search())
        self.results.append(await self.verify_parser_accuracy())
        self.results.append(await self.verify_captcha_detection())

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
            return 1
        elif skipped > 0 and passed == 0:
            print("\n⚠ All verifications SKIPPED.")
            return 2
        else:
            print("\n✓ All verifications PASSED!")
            print("  Note: CAPTCHA detection counts as success for Bing.")
            return 0


async def main():
    configure_logging(log_level="INFO", json_format=False)

    verifier = BingSearchVerifier()
    return await verifier.run_all()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
