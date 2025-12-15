#!/usr/bin/env python3
"""
Debug script for Domain Daily Budget Flow (Problem 11).

This is a "straight-line" debug script per §debug-integration rule.
Verifies the domain daily budget checking and tracking functionality.

Per §4.3:
- Daily request/page limits per domain
- Automatic daily reset at midnight
- Fail-open on errors
- Integration with DomainPolicyManager

Usage:
    python tests/scripts/debug_domain_daily_budget_flow.py
"""

import sys
from datetime import date
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, "/home/statuser/lancet")


def main():
    """Run domain daily budget verification."""
    print("=" * 60)
    print("Domain Daily Budget Flow Debug Script")
    print("=" * 60)

    # =========================================================================
    # 1. Test DomainDailyBudget Schema
    # =========================================================================
    print("\n[1] Testing DomainDailyBudget Schema...")

    from src.utils.schemas import DomainBudgetCheckResult, DomainDailyBudget

    budget = DomainDailyBudget(
        domain="example.com",
        requests_today=50,
        pages_today=25,
        max_requests_per_day=200,
        max_pages_per_day=100,
        date="2025-12-15",
    )

    print(f"  - domain: {budget.domain}")
    print(f"  - requests_today: {budget.requests_today}")
    print(f"  - pages_today: {budget.pages_today}")
    print(f"  - max_requests_per_day: {budget.max_requests_per_day}")
    print(f"  - max_pages_per_day: {budget.max_pages_per_day}")
    print(f"  - requests_remaining: {budget.requests_remaining}")
    print(f"  - pages_remaining: {budget.pages_remaining}")

    assert budget.requests_remaining == 150
    assert budget.pages_remaining == 75

    print("[1] DomainDailyBudget Schema: PASSED ✓")

    # =========================================================================
    # 2. Test DomainDailyBudgetManager
    # =========================================================================
    print("\n[2] Testing DomainDailyBudgetManager...")

    from src.scheduler.domain_budget import (
        DEFAULT_MAX_PAGES_PER_DAY,
        DEFAULT_MAX_REQUESTS_PER_DAY,
        DomainDailyBudgetManager,
        reset_domain_budget_manager,
    )

    # Reset to ensure clean state
    reset_domain_budget_manager()

    manager = DomainDailyBudgetManager()

    # Test first request
    print("  - Testing first request...")
    result = manager.can_request_to_domain("test1.com")
    assert result.allowed is True
    assert result.reason is None
    print(
        f"    OK: allowed={result.allowed}, remaining={result.requests_remaining}/{result.pages_remaining}"
    )

    # Test recording requests
    print("  - Recording requests...")
    for i in range(5):
        manager.record_domain_request("test1.com", is_page=(i % 2 == 0))

    budget = manager.get_domain_budget("test1.com")
    print(
        f"    OK: requests={budget.requests_today}, pages={budget.pages_today}"
    )
    assert budget.requests_today == 5
    assert budget.pages_today == 3  # 0, 2, 4 are pages

    print("[2] DomainDailyBudgetManager: PASSED ✓")

    # =========================================================================
    # 3. Test Budget Limits
    # =========================================================================
    print("\n[3] Testing budget limits...")

    # Create manager with small limits
    reset_domain_budget_manager()
    manager = DomainDailyBudgetManager()

    # Override limits for testing
    with patch.object(manager, "_get_domain_limits") as mock_limits:
        mock_limits.return_value = (3, 2)  # Only 3 requests, 2 pages
        manager.clear_budgets()

        # Make requests up to limit
        print("  - Testing request limit...")
        for i in range(3):
            result = manager.can_request_to_domain("limited.com")
            assert result.allowed is True
            manager.record_domain_request("limited.com")

        # Next request should be denied
        result = manager.can_request_to_domain("limited.com")
        assert result.allowed is False
        assert "request_limit_exceeded" in result.reason
        print(f"    OK: request limit enforced, reason={result.reason}")

    # Test page limit
    reset_domain_budget_manager()
    manager = DomainDailyBudgetManager()

    with patch.object(manager, "_get_domain_limits") as mock_limits:
        mock_limits.return_value = (100, 2)  # 100 requests, but only 2 pages
        manager.clear_budgets()

        print("  - Testing page limit...")
        for i in range(2):
            result = manager.can_request_to_domain("pagelimited.com")
            assert result.allowed is True
            manager.record_domain_request("pagelimited.com", is_page=True)

        # Next request should be denied (page limit)
        result = manager.can_request_to_domain("pagelimited.com")
        assert result.allowed is False
        assert "page_limit_exceeded" in result.reason
        print(f"    OK: page limit enforced, reason={result.reason}")

    print("[3] Budget Limits: PASSED ✓")

    # =========================================================================
    # 4. Test Date Reset
    # =========================================================================
    print("\n[4] Testing date reset...")

    reset_domain_budget_manager()
    manager = DomainDailyBudgetManager()

    # Record some requests
    manager.record_domain_request("reset.com")
    manager.record_domain_request("reset.com")
    budget_before = manager.get_domain_budget("reset.com")
    print(f"  - Before reset: requests={budget_before.requests_today}")
    assert budget_before.requests_today == 2

    # Simulate date change
    with patch.object(manager, "_get_today", return_value="2099-01-01"):
        manager._check_date_reset()
        budget_after = manager.get_domain_budget("reset.com")

    print(f"  - After reset: requests={budget_after.requests_today}")
    assert budget_after.requests_today == 0
    print("[4] Date Reset: PASSED ✓")

    # =========================================================================
    # 5. Test Multiple Domains Independent
    # =========================================================================
    print("\n[5] Testing multiple domains independence...")

    reset_domain_budget_manager()
    manager = DomainDailyBudgetManager()

    manager.record_domain_request("domain1.com")
    manager.record_domain_request("domain1.com")
    manager.record_domain_request("domain1.com")
    manager.record_domain_request("domain2.com")

    budget1 = manager.get_domain_budget("domain1.com")
    budget2 = manager.get_domain_budget("domain2.com")

    print(f"  - domain1.com: {budget1.requests_today} requests")
    print(f"  - domain2.com: {budget2.requests_today} requests")

    assert budget1.requests_today == 3
    assert budget2.requests_today == 1

    print("[5] Multiple Domains Independence: PASSED ✓")

    # =========================================================================
    # 6. Test Fail-Open Behavior
    # =========================================================================
    print("\n[6] Testing fail-open behavior...")

    reset_domain_budget_manager()
    manager = DomainDailyBudgetManager()

    # Simulate exception during budget check
    with patch.object(
        manager, "_get_or_create_budget", side_effect=RuntimeError("Simulated error")
    ):
        result = manager.can_request_to_domain("error.com")

    print(f"  - On error: allowed={result.allowed}, reason={result.reason}")
    assert result.allowed is True
    assert "check_error_failopen" in result.reason

    print("[6] Fail-Open Behavior: PASSED ✓")

    # =========================================================================
    # 7. Test Stats
    # =========================================================================
    print("\n[7] Testing stats...")

    reset_domain_budget_manager()
    manager = DomainDailyBudgetManager()

    manager.record_domain_request("stat1.com", is_page=True)
    manager.record_domain_request("stat1.com", is_page=True)
    manager.record_domain_request("stat2.com", is_page=False)
    manager.record_domain_request("stat3.com", is_page=True)

    stats = manager.get_stats()
    print(f"  - domains_tracked: {stats['domains_tracked']}")
    print(f"  - total_requests_today: {stats['total_requests_today']}")
    print(f"  - total_pages_today: {stats['total_pages_today']}")

    assert stats["domains_tracked"] == 3
    assert stats["total_requests_today"] == 4
    assert stats["total_pages_today"] == 3

    print("[7] Stats: PASSED ✓")

    # =========================================================================
    # 8. Test Domain Policy Integration
    # =========================================================================
    print("\n[8] Testing domain policy integration...")

    from src.utils.domain_policy import (
        DomainPolicy,
        get_domain_policy_manager,
        reset_domain_policy_manager,
    )

    reset_domain_policy_manager()
    policy_manager = get_domain_policy_manager()

    # Check that domain policy has new fields
    policy = policy_manager.get_policy("wikipedia.org")
    print(f"  - wikipedia.org policy:")
    print(f"    - max_requests_per_day: {policy.max_requests_per_day}")
    print(f"    - max_pages_per_day: {policy.max_pages_per_day}")

    # These should be set from config/domains.yaml
    assert hasattr(policy, "max_requests_per_day")
    assert hasattr(policy, "max_pages_per_day")
    assert policy.max_requests_per_day > 0
    assert policy.max_pages_per_day > 0

    print("[8] Domain Policy Integration: PASSED ✓")

    # =========================================================================
    # Summary
    # =========================================================================
    print("\n" + "=" * 60)
    print("Domain Daily Budget Flow: ALL TESTS PASSED ✓")
    print("=" * 60)
    print("\nVerified functionality:")
    print("  1. DomainDailyBudget schema with remaining calculations")
    print("  2. DomainDailyBudgetManager request tracking")
    print("  3. Budget limit enforcement (requests and pages)")
    print("  4. Automatic date reset")
    print("  5. Multiple domains independence")
    print("  6. Fail-open behavior on errors")
    print("  7. Statistics tracking")
    print("  8. Domain policy integration")
    print("\nIP block prevention via daily budget limits is functional.")


if __name__ == "__main__":
    main()
