#!/usr/bin/env python3
"""
Verification target: §3.6.1 Authentication Queue

Verification items:
1. CAPTCHA detection -> queue enqueue (§3.6.1 Queue Enqueue)
2. Domain batch resolution (§3.6.1 Domain-based Auth Management)
3. Parallel processing while auth pending (§3.6.1 Parallel Processing)
4. Priority management (§3.6.1 Priority Management)
5. Toast notification (§3.6 Notification)
6. Window foreground (§3.6.1 Safe Operation Policy)
7. Session reuse (§3.6.1 Session Reuse)

Prerequisites:
- Chrome running with remote debugging on Windows
- config/settings.yaml browser.chrome_host configured correctly
- See: IMPLEMENTATION_PLAN.md 16.9 "Setup Procedure"

Acceptance criteria (§7):
- Notification success rate ≥99%
- Window foreground success rate ≥95%
- Auth breakthrough: ≥80% success rate for auth session processed items

Usage:
    python tests/scripts/verify_captcha_flow.py

Exit codes:
    0: All verifications passed
    1: Some verifications failed
    2: Prerequisites not met (skipped)
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


class CAPTCHAFlowVerifier:
    """Verifier for §3.6.1 authentication queue functionality."""
    
    def __init__(self):
        self.results: list[VerificationResult] = []
        self.browser_available = False
        
    async def check_prerequisites(self) -> bool:
        """Check environment prerequisites."""
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
            print("    → Ensure Chrome is running with remote debugging")
            return False
        
        # Check notification system
        try:
            from src.utils.notification import InterventionManager
            manager = InterventionManager()
            print("  ✓ Notification system available")
        except Exception as e:
            print(f"  ✗ Notification system failed: {e}")
            return False
        
        # Check database
        try:
            from src.storage.database import get_database
            db = await get_database()
            print("  ✓ Database available")
        except Exception as e:
            print(f"  ✗ Database failed: {e}")
            return False
        
        print("  All prerequisites met.\n")
        return True

    async def verify_queue_enqueue(self) -> VerificationResult:
        """§3.6.1 Queue Enqueue: URLs requiring auth are queued."""
        print("\n[1/7] Verifying queue enqueue (§3.6.1 キュー積み)...")
        
        from src.utils.notification import get_intervention_queue
        from src.storage.database import get_database
        
        queue = get_intervention_queue()
        db = await get_database()
        
        # Test data - multiple URLs for same domain and different domains
        test_cases = [
            ("test_task_001", "https://example.com/page1", "example.com", "captcha", "high"),
            ("test_task_001", "https://example.com/page2", "example.com", "captcha", "medium"),
            ("test_task_002", "https://other.com/page1", "other.com", "cloudflare", "high"),
        ]
        
        queue_ids = []
        try:
            for task_id, url, domain, auth_type, priority in test_cases:
                queue_id = await queue.enqueue(
                    task_id=task_id,
                    url=url,
                    domain=domain,
                    auth_type=auth_type,
                    priority=priority,
                )
                queue_ids.append(queue_id)
                print(f"    ✓ Queued: {url} -> {queue_id}")
            
            # Verify all items are in queue
            pending = await queue.get_pending()
            pending_ids = {item['id'] for item in pending}
            
            all_queued = all(qid in pending_ids for qid in queue_ids)
            
            if all_queued:
                print(f"    ✓ All {len(queue_ids)} items found in pending queue")
                return VerificationResult(
                    name="Queue Enqueue",
                    spec_ref="§3.6.1 キュー積み",
                    passed=True,
                    details={"queued_count": len(queue_ids), "queue_ids": queue_ids},
                )
            else:
                missing = set(queue_ids) - pending_ids
                print(f"    ✗ Missing items: {missing}")
                return VerificationResult(
                    name="Queue Enqueue",
                    spec_ref="§3.6.1 キュー積み",
                    passed=False,
                    error=f"Missing items: {missing}",
                )
        except Exception as e:
            logger.exception("Queue enqueue verification failed")
            return VerificationResult(
                name="Queue Enqueue",
                spec_ref="§3.6.1 キュー積み",
                passed=False,
                error=str(e),
            )
        finally:
            # Cleanup
            for qid in queue_ids:
                try:
                    await queue.complete(queue_id=qid, success=False, session_data=None)
                except Exception:
                    pass

    async def verify_domain_batch_resolution(self) -> VerificationResult:
        """§3.6.1 Domain-based Auth: Batch resolution for same domain."""
        print("\n[2/7] Verifying domain batch resolution (§3.6.1 ドメインベース認証管理)...")
        
        from src.utils.notification import get_intervention_queue
        
        queue = get_intervention_queue()
        test_domain = "batch-test.example.com"
        
        # Queue multiple URLs for same domain
        queue_ids = []
        try:
            for i in range(3):
                queue_id = await queue.enqueue(
                    task_id=f"batch_task_{i}",
                    url=f"https://{test_domain}/page{i}",
                    domain=test_domain,
                    auth_type="cloudflare",
                    priority="medium",
                )
                queue_ids.append(queue_id)
            
            print(f"    Queued {len(queue_ids)} items for domain: {test_domain}")
            
            # Verify by_domain grouping
            by_domain = await queue.get_pending_by_domain()
            domain_info = next(
                (d for d in by_domain.get("domains", []) if d["domain"] == test_domain),
                None,
            )
            
            if not domain_info:
                return VerificationResult(
                    name="Domain Batch Resolution",
                    spec_ref="§3.6.1 ドメインベース認証管理",
                    passed=False,
                    error=f"Domain {test_domain} not found in by_domain response",
                )
            
            if domain_info["pending_count"] != 3:
                return VerificationResult(
                    name="Domain Batch Resolution",
                    spec_ref="§3.6.1 ドメインベース認証管理",
                    passed=False,
                    error=f"Expected 3 pending, got {domain_info['pending_count']}",
                )
            
            print(f"    ✓ Domain grouping correct: {domain_info['pending_count']} items")
            
            # Complete domain-wide authentication
            session_data = {"cf_clearance": "test_token_123"}
            result = await queue.complete_domain(
                domain=test_domain,
                success=True,
                session_data=session_data,
            )
            
            resolved_count = result.get("resolved_count", 0)
            if resolved_count != 3:
                return VerificationResult(
                    name="Domain Batch Resolution",
                    spec_ref="§3.6.1 ドメインベース認証管理",
                    passed=False,
                    error=f"Expected 3 resolved, got {resolved_count}",
                )
            
            print(f"    ✓ Domain batch resolution: {resolved_count} items resolved")
            
            # Verify session is stored for domain
            stored_session = await queue.get_session_for_domain(test_domain)
            if not stored_session:
                return VerificationResult(
                    name="Domain Batch Resolution",
                    spec_ref="§3.6.1 ドメインベース認証管理",
                    passed=False,
                    error="Session not stored after domain completion",
                )
            
            if stored_session.get("cf_clearance") != "test_token_123":
                return VerificationResult(
                    name="Domain Batch Resolution",
                    spec_ref="§3.6.1 ドメインベース認証管理",
                    passed=False,
                    error=f"Session data mismatch: {stored_session}",
                )
            
            print("    ✓ Session stored for domain reuse")
            
            return VerificationResult(
                name="Domain Batch Resolution",
                spec_ref="§3.6.1 ドメインベース認証管理",
                passed=True,
                details={
                    "domain": test_domain,
                    "resolved_count": resolved_count,
                    "session_stored": True,
                },
            )
            
        except Exception as e:
            logger.exception("Domain batch resolution verification failed")
            return VerificationResult(
                name="Domain Batch Resolution",
                spec_ref="§3.6.1 ドメインベース認証管理",
                passed=False,
                error=str(e),
            )

    async def verify_parallel_processing(self) -> VerificationResult:
        """§3.6.1 Parallel: Continue exploring auth-free sources while waiting."""
        print("\n[3/7] Verifying parallel processing (§3.6.1 並行処理)...")
        
        from src.utils.notification import get_intervention_queue
        from src.crawler.fetcher import BrowserFetcher, FetchPolicy
        
        queue = get_intervention_queue()
        
        try:
            # Queue an item that needs auth
            blocked_domain = "blocked.example.com"
            queue_id = await queue.enqueue(
                task_id="parallel_test",
                url=f"https://{blocked_domain}/blocked",
                domain=blocked_domain,
                auth_type="cloudflare",
                priority="high",
            )
            print(f"    Queued blocked URL: {blocked_domain}")
            
            # Verify we can still fetch unblocked URLs
            fetcher = BrowserFetcher()
            try:
                policy = FetchPolicy(use_browser=True, allow_headful=False)
                
                # Fetch a known-good URL
                start_time = time.time()
                result = await fetcher.fetch("https://example.com", policy=policy)
                elapsed = time.time() - start_time
                
                if result.ok:
                    print(f"    ✓ Unblocked URL fetched in {elapsed:.2f}s while auth pending")
                    
                    # Verify the blocked item is still pending
                    pending = await queue.get_pending()
                    still_pending = any(item['id'] == queue_id for item in pending)
                    
                    if still_pending:
                        print("    ✓ Blocked item still in queue (parallel processing works)")
                        return VerificationResult(
                            name="Parallel Processing",
                            spec_ref="§3.6.1 並行処理",
                            passed=True,
                            details={
                                "unblocked_fetch_time": elapsed,
                                "blocked_still_pending": True,
                            },
                        )
                    else:
                        return VerificationResult(
                            name="Parallel Processing",
                            spec_ref="§3.6.1 並行処理",
                            passed=False,
                            error="Blocked item was unexpectedly resolved",
                        )
                else:
                    return VerificationResult(
                        name="Parallel Processing",
                        spec_ref="§3.6.1 並行処理",
                        passed=False,
                        error=f"Unblocked fetch failed: {result.reason}",
                    )
            finally:
                await fetcher.close()
                # Cleanup
                await queue.complete(queue_id=queue_id, success=False, session_data=None)
                
        except Exception as e:
            logger.exception("Parallel processing verification failed")
            return VerificationResult(
                name="Parallel Processing",
                spec_ref="§3.6.1 並行処理",
                passed=False,
                error=str(e),
            )

    async def verify_priority_ordering(self) -> VerificationResult:
        """§3.6.1 Priority: High priority (primary sources) processed first."""
        print("\n[4/7] Verifying priority ordering (§3.6.1 優先度管理)...")
        
        from src.utils.notification import get_intervention_queue
        
        queue = get_intervention_queue()
        queue_ids = []
        
        try:
            # Queue items with different priorities (in random order)
            priorities = [
                ("low_url", "low"),
                ("high_url", "high"),
                ("medium_url", "medium"),
            ]
            
            for url_suffix, priority in priorities:
                queue_id = await queue.enqueue(
                    task_id="priority_test",
                    url=f"https://priority.example.com/{url_suffix}",
                    domain="priority.example.com",
                    auth_type="captcha",
                    priority=priority,
                )
                queue_ids.append((queue_id, priority))
                print(f"    Queued: {url_suffix} with priority {priority}")
            
            # Get pending sorted by priority
            pending = await queue.get_pending(task_id="priority_test")
            
            # Expected order: high, medium, low
            expected_order = ["high", "medium", "low"]
            actual_order = [item["priority"] for item in pending]
            
            if actual_order == expected_order:
                print(f"    ✓ Priority order correct: {actual_order}")
                return VerificationResult(
                    name="Priority Ordering",
                    spec_ref="§3.6.1 優先度管理",
                    passed=True,
                    details={"expected": expected_order, "actual": actual_order},
                )
            else:
                print(f"    ✗ Priority order incorrect: expected {expected_order}, got {actual_order}")
                return VerificationResult(
                    name="Priority Ordering",
                    spec_ref="§3.6.1 優先度管理",
                    passed=False,
                    error=f"Expected {expected_order}, got {actual_order}",
                )
                
        except Exception as e:
            logger.exception("Priority ordering verification failed")
            return VerificationResult(
                name="Priority Ordering",
                spec_ref="§3.6.1 優先度管理",
                passed=False,
                error=str(e),
            )
        finally:
            # Cleanup
            for qid, _ in queue_ids:
                try:
                    await queue.complete(queue_id=qid, success=False, session_data=None)
                except Exception:
                    pass

    async def verify_toast_notification(self) -> VerificationResult:
        """§3.6 Notification: Toast notification is sent."""
        print("\n[5/7] Verifying toast notification (§3.6 通知)...")
        
        from src.utils.notification import InterventionManager
        
        manager = InterventionManager()
        
        try:
            # Send test notification
            notification_count = 5
            success_count = 0
            
            for i in range(notification_count):
                sent = await manager.send_toast(
                    title=f"Lancet: Test Notification {i+1}",
                    message=f"This is test notification {i+1}/{notification_count}.\nVerifying notification system.",
                    timeout_seconds=2,
                )
                if sent:
                    success_count += 1
                await asyncio.sleep(0.5)
            
            success_rate = success_count / notification_count
            threshold = 0.99  # §7: ≥99%
            
            print(f"    Notification success rate: {success_rate:.1%} ({success_count}/{notification_count})")
            
            if success_rate >= threshold:
                print(f"    ✓ Meets threshold (≥{threshold:.0%})")
                return VerificationResult(
                    name="Toast Notification",
                    spec_ref="§3.6 通知",
                    passed=True,
                    details={
                        "success_rate": success_rate,
                        "threshold": threshold,
                        "sent": success_count,
                        "total": notification_count,
                    },
                )
            else:
                print(f"    ✗ Below threshold (<{threshold:.0%})")
                return VerificationResult(
                    name="Toast Notification",
                    spec_ref="§3.6 通知",
                    passed=False,
                    error=f"Success rate {success_rate:.1%} < {threshold:.0%}",
                )
                
        except Exception as e:
            logger.exception("Toast notification verification failed")
            return VerificationResult(
                name="Toast Notification",
                spec_ref="§3.6 通知",
                passed=False,
                error=str(e),
            )

    async def verify_window_foreground(self) -> VerificationResult:
        """§3.6.1 Safe Operation: Window foreground."""
        print("\n[6/7] Verifying window foreground (§3.6.1 安全運用方針)...")
        
        if not self.browser_available:
            return VerificationResult(
                name="Window Foreground",
                spec_ref="§3.6.1 安全運用方針",
                passed=False,
                skipped=True,
                skip_reason="Browser not available",
            )
        
        from src.utils.notification import InterventionManager
        
        manager = InterventionManager()
        
        try:
            # Test foreground functionality
            foreground_count = 3
            success_count = 0
            
            for i in range(foreground_count):
                success = await manager.bring_to_front(
                    url="https://example.com",
                    reason=f"Test foreground {i+1}",
                )
                if success:
                    success_count += 1
                await asyncio.sleep(1.0)
            
            success_rate = success_count / foreground_count
            threshold = 0.95  # §7: ≥95%
            
            print(f"    Foreground success rate: {success_rate:.1%} ({success_count}/{foreground_count})")
            
            if success_rate >= threshold:
                print(f"    ✓ Meets threshold (≥{threshold:.0%})")
                return VerificationResult(
                    name="Window Foreground",
                    spec_ref="§3.6.1 安全運用方針",
                    passed=True,
                    details={
                        "success_rate": success_rate,
                        "threshold": threshold,
                        "success": success_count,
                        "total": foreground_count,
                    },
                )
            else:
                print(f"    ✗ Below threshold (<{threshold:.0%})")
                return VerificationResult(
                    name="Window Foreground",
                    spec_ref="§3.6.1 安全運用方針",
                    passed=False,
                    error=f"Success rate {success_rate:.1%} < {threshold:.0%}",
                )
                
        except Exception as e:
            logger.exception("Window foreground verification failed")
            return VerificationResult(
                name="Window Foreground",
                spec_ref="§3.6.1 安全運用方針",
                passed=False,
                error=str(e),
            )

    async def verify_session_reuse(self) -> VerificationResult:
        """§3.6.1 Session Reuse: Authenticated sessions are reused."""
        print("\n[7/7] Verifying session reuse (§3.6.1 セッション再利用)...")
        
        from src.utils.notification import get_intervention_queue
        
        queue = get_intervention_queue()
        test_domain = "reuse.example.com"
        
        try:
            # First: complete authentication for domain
            queue_id_1 = await queue.enqueue(
                task_id="reuse_test_1",
                url=f"https://{test_domain}/page1",
                domain=test_domain,
                auth_type="cloudflare",
                priority="high",
            )
            
            session_data = {
                "cf_clearance": "reuse_token_abc",
                "authenticated_at": "2024-01-01T12:00:00Z",
            }
            
            await queue.complete(
                queue_id=queue_id_1,
                success=True,
                session_data=session_data,
            )
            print(f"    Completed first authentication for {test_domain}")
            
            # Verify session is stored
            stored = await queue.get_session_for_domain(test_domain)
            if not stored:
                return VerificationResult(
                    name="Session Reuse",
                    spec_ref="§3.6.1 セッション再利用",
                    passed=False,
                    error="Session not stored after completion",
                )
            
            print(f"    ✓ Session stored: {stored.get('cf_clearance', 'N/A')[:20]}...")
            
            # Second: new URL for same domain should find existing session
            queue_id_2 = await queue.enqueue(
                task_id="reuse_test_2",
                url=f"https://{test_domain}/page2",
                domain=test_domain,
                auth_type="cloudflare",
                priority="medium",
            )
            
            # Check if session is available for reuse
            reuse_session = await queue.get_session_for_domain(test_domain)
            
            if reuse_session and reuse_session.get("cf_clearance") == "reuse_token_abc":
                print("    ✓ Session available for reuse with correct data")
                
                # Cleanup
                await queue.complete(queue_id=queue_id_2, success=True, session_data=None)
                
                return VerificationResult(
                    name="Session Reuse",
                    spec_ref="§3.6.1 セッション再利用",
                    passed=True,
                    details={
                        "domain": test_domain,
                        "session_reused": True,
                        "original_token": "reuse_token_abc",
                    },
                )
            else:
                return VerificationResult(
                    name="Session Reuse",
                    spec_ref="§3.6.1 セッション再利用",
                    passed=False,
                    error=f"Session not available for reuse: {reuse_session}",
                )
                
        except Exception as e:
            logger.exception("Session reuse verification failed")
            return VerificationResult(
                name="Session Reuse",
                spec_ref="§3.6.1 セッション再利用",
                passed=False,
                error=str(e),
            )

    async def run_all(self) -> int:
        """Run all verifications and output results."""
        print("\n" + "=" * 70)
        print("E2E: CAPTCHA Flow Verification")
        print("検証対象: §3.6.1 認証待ちキュー")
        print("=" * 70)
        
        # Prerequisites
        if not await self.check_prerequisites():
            print("\n" + "=" * 70)
            print("SKIPPED: Prerequisites not met")
            print("=" * 70)
            return 2
        
        # Run verifications
        self.results.append(await self.verify_queue_enqueue())
        self.results.append(await self.verify_domain_batch_resolution())
        self.results.append(await self.verify_parallel_processing())
        self.results.append(await self.verify_priority_ordering())
        self.results.append(await self.verify_toast_notification())
        self.results.append(await self.verify_window_foreground())
        self.results.append(await self.verify_session_reuse())
        
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
    
    verifier = CAPTCHAFlowVerifier()
    return await verifier.run_all()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
