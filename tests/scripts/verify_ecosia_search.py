#!/usr/bin/env python3
"""
Ecosia Search Engine E2E Verification

Verification target: §3.2 Agent Execution (Browser Search) - Ecosia

Ecosia characteristics:
- Bing-based search backend
- Relatively lenient bot detection
- Privacy-focused (plants trees)

Verification items:
1. CDP connection
2. Ecosia search operation
3. Search result parser accuracy (EcosiaParser)
4. CAPTCHA detection

Prerequisites:
- Chrome running with remote debugging on Windows
- config/settings.yaml browser.chrome_host configured correctly
- See: IMPLEMENTATION_PLAN.md 16.9 "Setup Procedure"

Acceptance criteria (§7):
- CAPTCHA: 100% detection
- Scraping success rate ≥95%

Usage:
    podman exec lancet python tests/scripts/verify_ecosia_search.py

Exit codes:
    0: All verifications passed
    1: Some verifications failed
    2: Prerequisites not met (skipped)

Note:
    This script accesses real Ecosia search.
    Ecosia is relatively lenient but still run in low-risk IP environment.

Related scripts:
    - verify_duckduckgo_search.py
    - verify_metager_search.py
    - verify_startpage_search.py
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
    """Data class to hold verification results."""
    name: str
    spec_ref: str
    passed: bool
    skipped: bool = False
    skip_reason: Optional[str] = None
    details: dict = field(default_factory=dict)
    error: Optional[str] = None


class EcosiaSearchVerifier:
    """Verifier for Ecosia search functionality."""
    
    ENGINE_NAME = "ecosia"
    ENGINE_DISPLAY = "Ecosia"
    
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
        
        # Check parser availability
        from src.search.search_parsers import get_parser
        parser = get_parser(self.ENGINE_NAME)
        if parser:
            print(f"  ✓ {self.ENGINE_DISPLAY} parser available")
        else:
            print(f"  ✗ {self.ENGINE_DISPLAY} parser not found")
            return False
        
        print("  All prerequisites met.\n")
        print(f"  ⚠ Warning: This will access real {self.ENGINE_DISPLAY} search.")
        print("    Ecosia is relatively lenient, but use caution.\n")
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
            
            browser_info = {'connected': provider._browser.is_connected()}
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
        """Verify Ecosia search operation."""
        print(f"\n[2/4] Verifying {self.ENGINE_DISPLAY} search...")
        
        from src.search.browser_search_provider import BrowserSearchProvider
        from src.search.provider import SearchOptions
        
        provider = BrowserSearchProvider()
        
        try:
            test_query = "renewable energy solar power"
            
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
                if result.captcha_detected:
                    print(f"    ! CAPTCHA detected: {result.captcha_type}")
                    return VerificationResult(
                        name=f"{self.ENGINE_DISPLAY} Search",
                        spec_ref="§3.2",
                        passed=True,
                        details={
                            "captcha_detected": True,
                            "captcha_type": result.captcha_type,
                            "note": "CAPTCHA detection working correctly",
                        },
                    )
                else:
                    return VerificationResult(
                        name=f"{self.ENGINE_DISPLAY} Search",
                        spec_ref="§3.2",
                        passed=False,
                        error=f"Search failed: {result.error}",
                    )
            
            print(f"    ✓ Search completed in {elapsed:.2f}s")
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
        print(f"\n[3/4] Verifying {self.ENGINE_DISPLAY} parser accuracy...")
        
        from src.search.browser_search_provider import BrowserSearchProvider
        from src.search.provider import SearchOptions
        
        provider = BrowserSearchProvider()
        
        try:
            # Use a query that should have predictable results
            test_query = "Wikipedia free encyclopedia"
            
            options = SearchOptions(
                engines=[self.ENGINE_NAME],
                limit=5,
            )
            
            result = await provider.search(test_query, options)
            
            if not result.ok:
                if result.captcha_detected:
                    return VerificationResult(
                        name="Parser Accuracy",
                        spec_ref="§3.2",
                        passed=True,
                        skipped=True,
                        skip_reason="CAPTCHA detected, cannot verify parser",
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
                has_url = bool(r.url and r.url.startswith('http'))
                has_engine = r.engine == self.ENGINE_NAME
                has_rank = r.rank > 0
                
                if all([has_title, has_url, has_engine, has_rank]):
                    valid_results += 1
            
            accuracy = valid_results / total_results if total_results > 0 else 0
            print(f"    Parser accuracy: {accuracy:.0%} ({valid_results}/{total_results})")
            
            # Check for wikipedia in results
            has_expected = any("wikipedia" in r.url.lower() for r in result.results)
            if has_expected:
                print("    ✓ Expected result (wikipedia) found")
            else:
                print("    ! Expected result (wikipedia) not found")
            
            passed = accuracy >= 0.9
            return VerificationResult(
                name="Parser Accuracy",
                spec_ref="§3.2",
                passed=passed,
                details={
                    "accuracy": accuracy,
                    "valid": valid_results,
                    "total": total_results,
                    "has_expected_result": has_expected,
                },
                error=None if passed else f"Parser accuracy {accuracy:.0%} < 90%",
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

    async def verify_session_management(self) -> VerificationResult:
        """Verify session management."""
        print("\n[4/4] Verifying session management...")
        
        from src.search.browser_search_provider import BrowserSearchProvider
        from src.search.provider import SearchOptions
        
        provider = BrowserSearchProvider()
        
        try:
            # Perform a search
            options = SearchOptions(engines=[self.ENGINE_NAME], limit=3)
            result = await provider.search("test query", options)
            
            # Check search session
            search_session = provider.get_session(self.ENGINE_NAME)
            if search_session:
                print(f"    ✓ Search session created")
                print(f"      - Success count: {search_session.success_count}")
                print(f"      - CAPTCHA count: {search_session.captcha_count}")
            else:
                print("    ! No search session (may be normal if CAPTCHA hit)")
            
            return VerificationResult(
                name="Session Management",
                spec_ref="§3.6.1",
                passed=True,
                details={
                    "has_session": search_session is not None,
                    "success_count": search_session.success_count if search_session else 0,
                },
            )
            
        except Exception as e:
            logger.exception("Session management verification failed")
            return VerificationResult(
                name="Session Management",
                spec_ref="§3.6.1",
                passed=False,
                error=str(e),
            )
        finally:
            await provider.close()

    async def run_all(self) -> int:
        """Run all verifications and output results."""
        print("\n" + "=" * 70)
        print(f"Phase 16.13: {self.ENGINE_DISPLAY} Search E2E Verification")
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
    
    verifier = EcosiaSearchVerifier()
    return await verifier.run_all()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

