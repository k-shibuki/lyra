"""
Tests for DomainDailyBudgetManager (§4.3 - IP block prevention, Problem 11).

Test design follows §7.1 Test Code Quality Standards:
- No conditional assertions (§7.1.1)
- Specific assertions with concrete values (§7.1.2)
- Realistic test data (§7.1.3)
- AAA pattern (§7.1.5)

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-DB-N-01 | First request | Equivalence – normal | allowed=True, count=1 | - |
| TC-DB-N-02 | Within budget | Equivalence – normal | allowed=True | - |
| TC-DB-B-01 | Budget reached | Boundary – max | allowed=False | - |
| TC-DB-B-02 | Budget=0 (unlimited) | Boundary – zero | always allowed | - |
| TC-DB-B-03 | Budget=1 | Boundary – min | 1 request only | - |
| TC-DB-A-01 | Date change | Equivalence – reset | counters reset | - |
| TC-DB-N-03 | Multiple domains | Equivalence – normal | independent budgets | - |
| TC-DB-N-04 | Domain override | Equivalence – normal | uses override | - |
| TC-DB-A-02 | Unknown domain | Equivalence – default | uses defaults | - |
| TC-DB-N-05 | Record request | Equivalence – normal | request count += 1 | - |
| TC-DB-N-06 | Record page | Equivalence – normal | both counts += 1 | - |
| TC-DB-E-01 | Exception in check | Abnormal – error | fail-open (allowed) | - |
| TC-DB-N-07 | Page budget reached | Boundary – max | allowed=False (pages) | - |
| TC-DB-N-08 | Stats | Equivalence – normal | correct stats | - |
| TC-DB-N-09 | Get all budgets | Equivalence – normal | all domains returned | - |
| TC-DB-N-10 | Clear budgets | Equivalence – normal | budgets cleared | - |
| TC-SC-N-01 | Schema valid | Equivalence – normal | DomainDailyBudget | - |
| TC-SC-N-02 | Schema result | Equivalence – normal | DomainBudgetCheckResult | - |
| TC-SC-N-03 | Budget remaining | Equivalence – normal | correct calculation | - |
| TC-SC-B-01 | Unlimited remaining | Boundary – zero budget | MAX_INT | - |
| TC-SG-N-01 | Singleton | Equivalence – normal | same instance | - |
| TC-SG-N-02 | Reset singleton | Equivalence – normal | new instance | - |
| TC-CV-N-01 | can_request_to_domain | Equivalence – normal | returns result | - |
| TC-CV-N-02 | record_domain_request | Equivalence – normal | increments | - |
| TC-CV-N-03 | get_domain_daily_budget | Equivalence – normal | returns budget | - |
"""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

from src.scheduler.domain_budget import (
    DEFAULT_MAX_PAGES_PER_DAY,
    DEFAULT_MAX_REQUESTS_PER_DAY,
    DomainDailyBudgetManager,
    can_request_to_domain,
    get_domain_budget_manager,
    get_domain_daily_budget,
    record_domain_request,
    reset_domain_budget_manager,
)
from src.utils.schemas import DomainBudgetCheckResult, DomainDailyBudget

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def reset_manager() -> Generator[None, None, None]:
    """Reset singleton before each test."""
    reset_domain_budget_manager()
    yield
    reset_domain_budget_manager()


@pytest.fixture
def manager() -> DomainDailyBudgetManager:
    """Get a fresh DomainDailyBudgetManager instance."""
    return DomainDailyBudgetManager()


# =============================================================================
# Schema Tests (TC-SC-*)
# =============================================================================


class TestDomainDailyBudgetSchema:
    """Tests for DomainDailyBudget Pydantic model."""

    def test_tc_sc_n_01_valid_schema(self) -> None:
        """TC-SC-N-01: Valid schema creation."""
        # Given: Valid budget parameters
        # When: Creating a DomainDailyBudget
        budget = DomainDailyBudget(
            domain="example.com",
            requests_today=10,
            pages_today=5,
            max_requests_per_day=100,
            max_pages_per_day=50,
            date="2025-12-15",
        )

        # Then: All fields are set correctly
        assert budget.domain == "example.com"
        assert budget.requests_today == 10
        assert budget.pages_today == 5
        assert budget.max_requests_per_day == 100
        assert budget.max_pages_per_day == 50
        assert budget.date == "2025-12-15"

    def test_tc_sc_n_02_result_schema(self) -> None:
        """TC-SC-N-02: Valid result schema creation."""
        # Given: Valid result parameters
        # When: Creating a DomainBudgetCheckResult
        result = DomainBudgetCheckResult(
            allowed=True,
            reason=None,
            requests_remaining=150,
            pages_remaining=75,
        )

        # Then: All fields are set correctly
        assert result.allowed is True
        assert result.reason is None
        assert result.requests_remaining == 150
        assert result.pages_remaining == 75

    def test_tc_sc_n_03_budget_remaining_calculation(self) -> None:
        """TC-SC-N-03: Correct remaining calculation."""
        # Given: Budget with known values
        budget = DomainDailyBudget(
            domain="example.com",
            requests_today=50,
            pages_today=25,
            max_requests_per_day=200,
            max_pages_per_day=100,
            date="2025-12-15",
        )

        # When: Checking remaining
        # Then: Remaining values are correct
        assert budget.requests_remaining == 150
        assert budget.pages_remaining == 75

    def test_tc_sc_b_01_unlimited_remaining(self) -> None:
        """TC-SC-B-01: Unlimited budget returns MAX_INT."""
        # Given: Budget with 0 limits (unlimited)
        budget = DomainDailyBudget(
            domain="example.com",
            requests_today=1000,
            pages_today=500,
            max_requests_per_day=0,  # Unlimited
            max_pages_per_day=0,  # Unlimited
            date="2025-12-15",
        )

        # When: Checking remaining
        # Then: Returns large number for unlimited
        assert budget.requests_remaining == 2**31 - 1
        assert budget.pages_remaining == 2**31 - 1


# =============================================================================
# Manager Tests (TC-DB-*)
# =============================================================================


class TestDomainDailyBudgetManager:
    """Tests for DomainDailyBudgetManager."""

    def test_tc_db_n_01_first_request(self, manager: DomainDailyBudgetManager) -> None:
        """TC-DB-N-01: First request to domain is allowed."""
        # Given: Fresh manager with no requests
        # When: Checking first request
        result = manager.can_request_to_domain("example.com")

        # Then: Request is allowed
        assert result.allowed is True
        assert result.reason is None
        assert result.requests_remaining == DEFAULT_MAX_REQUESTS_PER_DAY
        assert result.pages_remaining == DEFAULT_MAX_PAGES_PER_DAY

    def test_tc_db_n_02_within_budget(self, manager: DomainDailyBudgetManager) -> None:
        """TC-DB-N-02: Requests within budget are allowed."""
        # Given: Some requests already made
        for _ in range(10):
            manager.record_domain_request("example.com")

        # When: Checking if more requests are allowed
        result = manager.can_request_to_domain("example.com")

        # Then: Still allowed
        assert result.allowed is True
        assert result.requests_remaining == DEFAULT_MAX_REQUESTS_PER_DAY - 10

    def test_tc_db_b_01_budget_reached(self, manager: DomainDailyBudgetManager) -> None:
        """TC-DB-B-01: Request denied when budget is reached."""
        # Given: Budget exactly at limit
        budget = manager._get_or_create_budget("example.com")
        budget.requests_today = budget.max_requests_per_day

        # When: Checking if more requests are allowed
        result = manager.can_request_to_domain("example.com")

        # Then: Denied
        assert result.allowed is False
        assert result.reason is not None
        assert "request_limit_exceeded" in result.reason
        assert result.requests_remaining == 0

    def test_tc_db_b_02_unlimited_budget(self, manager: DomainDailyBudgetManager) -> None:
        """TC-DB-B-02: Unlimited budget always allows requests."""
        # Given: Domain with unlimited budget (0 means unlimited)
        with patch.object(manager, "_get_domain_limits") as mock_limits:
            mock_limits.return_value = (0, 0)  # Unlimited

            # Clear budget to force re-creation
            manager.clear_budgets()

            # When: Making many requests
            for _ in range(1000):
                result = manager.can_request_to_domain("unlimited.com")
                manager.record_domain_request("unlimited.com")

        # Then: All allowed
        assert result.allowed is True

    def test_tc_db_b_03_budget_one(self, manager: DomainDailyBudgetManager) -> None:
        """TC-DB-B-03: Budget=1 allows exactly one request."""
        # Given: Domain with budget of 1
        with patch.object(manager, "_get_domain_limits") as mock_limits:
            mock_limits.return_value = (1, 1)  # Only 1 request allowed
            manager.clear_budgets()

            # When: First request
            result1 = manager.can_request_to_domain("single.com")
            manager.record_domain_request("single.com", is_page=True)

            # When: Second request
            result2 = manager.can_request_to_domain("single.com")

        # Then: First allowed, second denied
        assert result1.allowed is True
        assert result2.allowed is False

    def test_tc_db_a_01_date_change_resets(self, manager: DomainDailyBudgetManager) -> None:
        """TC-DB-A-01: Date change resets counters."""
        # Given: Budget with some requests
        manager.record_domain_request("example.com")
        manager.record_domain_request("example.com")
        budget_before = manager.get_domain_budget("example.com")
        assert budget_before.requests_today == 2

        # When: Date changes (must persist the mock for subsequent calls)
        with patch.object(manager, "_get_today", return_value="2099-01-01"):
            manager._check_date_reset()
            # Then: Counters reset
            budget_after = manager.get_domain_budget("example.com")
            assert budget_after.requests_today == 0
            assert budget_after.date == "2099-01-01"

    def test_tc_db_n_03_multiple_domains_independent(
        self, manager: DomainDailyBudgetManager
    ) -> None:
        """TC-DB-N-03: Different domains have independent budgets."""
        # Given: Two domains
        manager.record_domain_request("domain1.com")
        manager.record_domain_request("domain1.com")
        manager.record_domain_request("domain2.com")

        # When: Getting budgets
        budget1 = manager.get_domain_budget("domain1.com")
        budget2 = manager.get_domain_budget("domain2.com")

        # Then: Independent counts
        assert budget1.requests_today == 2
        assert budget2.requests_today == 1

    def test_tc_db_n_04_domain_override(self, manager: DomainDailyBudgetManager) -> None:
        """TC-DB-N-04: Domain-specific limits are respected."""
        # Given: Domain with override limits
        with patch.object(manager, "_get_domain_limits") as mock_limits:
            mock_limits.return_value = (50, 25)  # Custom limits
            manager.clear_budgets()

            # When: Creating budget
            budget = manager.get_domain_budget("custom.com")

        # Then: Uses custom limits
        assert budget.max_requests_per_day == 50
        assert budget.max_pages_per_day == 25

    def test_tc_db_a_02_unknown_domain_uses_defaults(
        self, manager: DomainDailyBudgetManager
    ) -> None:
        """TC-DB-A-02: Unknown domain uses default limits."""
        # Given: Unknown domain
        # When: Getting budget
        budget = manager.get_domain_budget("unknown-domain-12345.com")

        # Then: Uses defaults
        assert budget.max_requests_per_day == DEFAULT_MAX_REQUESTS_PER_DAY
        assert budget.max_pages_per_day == DEFAULT_MAX_PAGES_PER_DAY

    def test_tc_db_n_05_record_request(self, manager: DomainDailyBudgetManager) -> None:
        """TC-DB-N-05: Recording request increments counter."""
        # Given: Fresh budget
        budget_before = manager.get_domain_budget("example.com")
        assert budget_before.requests_today == 0

        # When: Recording request (not a page)
        manager.record_domain_request("example.com", is_page=False)

        # Then: Request counter incremented, page counter unchanged
        budget_after = manager.get_domain_budget("example.com")
        assert budget_after.requests_today == 1
        assert budget_after.pages_today == 0

    def test_tc_db_n_06_record_page(self, manager: DomainDailyBudgetManager) -> None:
        """TC-DB-N-06: Recording page increments both counters."""
        # Given: Fresh budget
        # When: Recording page
        manager.record_domain_request("example.com", is_page=True)

        # Then: Both counters incremented
        budget = manager.get_domain_budget("example.com")
        assert budget.requests_today == 1
        assert budget.pages_today == 1

    def test_tc_db_e_01_exception_failopen(self, manager: DomainDailyBudgetManager) -> None:
        """TC-DB-E-01: Exception during check results in fail-open."""
        # Given: Manager that will raise exception
        with patch.object(manager, "_get_or_create_budget", side_effect=RuntimeError("Test error")):
            # When: Checking budget
            result = manager.can_request_to_domain("error.com")

        # Then: Fail-open allows request
        assert result.allowed is True
        assert result.reason is not None
        assert "check_error_failopen" in result.reason

    def test_tc_db_n_07_page_budget_reached(self, manager: DomainDailyBudgetManager) -> None:
        """TC-DB-N-07: Request denied when page budget is reached."""
        # Given: Page budget at limit, request budget still available
        budget = manager._get_or_create_budget("example.com")
        budget.pages_today = budget.max_pages_per_day
        budget.requests_today = 10  # Still within request limit

        # When: Checking if more requests are allowed
        result = manager.can_request_to_domain("example.com")

        # Then: Denied due to page limit
        assert result.allowed is False
        assert result.reason is not None
        assert "page_limit_exceeded" in result.reason

    def test_tc_db_n_08_stats(self, manager: DomainDailyBudgetManager) -> None:
        """TC-DB-N-08: Stats return correct values."""
        # Given: Multiple domains with requests
        manager.record_domain_request("domain1.com", is_page=True)
        manager.record_domain_request("domain1.com", is_page=True)
        manager.record_domain_request("domain2.com", is_page=False)

        # When: Getting stats
        stats = manager.get_stats()

        # Then: Correct stats
        assert stats["domains_tracked"] == 2
        assert stats["total_requests_today"] == 3
        assert stats["total_pages_today"] == 2
        assert stats["exceeded_domains"] == []

    def test_tc_db_n_09_get_all_budgets(self, manager: DomainDailyBudgetManager) -> None:
        """TC-DB-N-09: Get all budgets returns all domains."""
        # Given: Multiple domains
        manager.record_domain_request("domain1.com")
        manager.record_domain_request("domain2.com")
        manager.record_domain_request("domain3.com")

        # When: Getting all budgets
        budgets = manager.get_all_budgets()

        # Then: All domains present
        assert len(budgets) == 3
        assert "domain1.com" in budgets
        assert "domain2.com" in budgets
        assert "domain3.com" in budgets

    def test_tc_db_n_10_clear_budgets(self, manager: DomainDailyBudgetManager) -> None:
        """TC-DB-N-10: Clear budgets removes all tracking."""
        # Given: Some budgets
        manager.record_domain_request("domain1.com")
        manager.record_domain_request("domain2.com")
        assert len(manager.get_all_budgets()) == 2

        # When: Clearing budgets
        manager.clear_budgets()

        # Then: All cleared
        assert len(manager.get_all_budgets()) == 0


# =============================================================================
# Singleton Tests (TC-SG-*)
# =============================================================================


class TestSingleton:
    """Tests for singleton behavior."""

    def test_tc_sg_n_01_singleton(self) -> None:
        """TC-SG-N-01: get_domain_budget_manager returns same instance."""
        # Given: Manager singleton
        # When: Getting manager multiple times
        manager1 = get_domain_budget_manager()
        manager2 = get_domain_budget_manager()

        # Then: Same instance
        assert manager1 is manager2

    def test_tc_sg_n_02_reset_creates_new(self) -> None:
        """TC-SG-N-02: Reset creates new instance."""
        # Given: Existing manager
        manager1 = get_domain_budget_manager()

        # When: Resetting
        reset_domain_budget_manager()
        manager2 = get_domain_budget_manager()

        # Then: Different instance
        assert manager1 is not manager2


# =============================================================================
# Convenience Function Tests (TC-CV-*)
# =============================================================================


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_tc_cv_n_01_can_request_to_domain(self) -> None:
        """TC-CV-N-01: can_request_to_domain returns result."""
        # Given: Module function
        # When: Calling
        result = can_request_to_domain("example.com")

        # Then: Returns DomainBudgetCheckResult
        assert isinstance(result, DomainBudgetCheckResult)
        assert result.allowed is True

    def test_tc_cv_n_02_record_domain_request(self) -> None:
        """TC-CV-N-02: record_domain_request increments counter."""
        # Given: Fresh state
        budget_before = get_domain_daily_budget("example.com")
        initial_count = budget_before.requests_today

        # When: Recording request
        record_domain_request("example.com")

        # Then: Counter incremented
        budget_after = get_domain_daily_budget("example.com")
        assert budget_after.requests_today == initial_count + 1

    def test_tc_cv_n_03_get_domain_daily_budget(self) -> None:
        """TC-CV-N-03: get_domain_daily_budget returns budget."""
        # Given: Module function
        # When: Calling
        budget = get_domain_daily_budget("example.com")

        # Then: Returns DomainDailyBudget
        assert isinstance(budget, DomainDailyBudget)
        assert budget.domain == "example.com"


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests for domain budget with policy manager."""

    def test_integration_with_domain_policy(self, manager: DomainDailyBudgetManager) -> None:
        """Test that domain policy limits are read correctly."""
        # Given: Manager with policy manager mock
        with patch("src.scheduler.domain_budget.get_domain_policy_manager") as mock_pm:
            mock_policy = MagicMock()
            mock_policy.max_requests_per_day = 300
            mock_policy.max_pages_per_day = 150
            mock_pm.return_value.get_policy.return_value = mock_policy
            manager.clear_budgets()

            # When: Getting domain budget
            budget = manager.get_domain_budget("custom.com")

        # Then: Uses policy values
        assert budget.max_requests_per_day == 300
        assert budget.max_pages_per_day == 150

    def test_budget_persists_across_requests(self, manager: DomainDailyBudgetManager) -> None:
        """Test that budget state persists correctly."""
        # Given: Initial requests
        for i in range(5):
            manager.record_domain_request("persist.com", is_page=(i % 2 == 0))

        # When: Getting budget
        budget = manager.get_domain_budget("persist.com")

        # Then: Correct totals
        assert budget.requests_today == 5
        assert budget.pages_today == 3  # 0, 2, 4 are pages

    def test_domain_normalization(self, manager: DomainDailyBudgetManager) -> None:
        """Test that domains are normalized correctly."""
        # Given: Same domain with different cases
        manager.record_domain_request("Example.COM")
        manager.record_domain_request("EXAMPLE.com")
        manager.record_domain_request("example.com")

        # When: Getting budget
        budget = manager.get_domain_budget("Example.COM")

        # Then: All count as same domain
        assert budget.domain == "example.com"
        assert budget.requests_today == 3


# =============================================================================
# Boundary Tests for Budget Limits
# =============================================================================


class TestBudgetBoundaries:
    """Boundary tests for budget limits."""

    def test_boundary_requests_minus_one(self, manager: DomainDailyBudgetManager) -> None:
        """Test: requests_today = max - 1 is allowed."""
        # Given: Budget one below limit
        budget = manager._get_or_create_budget("boundary.com")
        budget.requests_today = budget.max_requests_per_day - 1

        # When: Checking
        result = manager.can_request_to_domain("boundary.com")

        # Then: Allowed with 1 remaining
        assert result.allowed is True
        assert result.requests_remaining == 1

    def test_boundary_requests_at_limit(self, manager: DomainDailyBudgetManager) -> None:
        """Test: requests_today = max is denied."""
        # Given: Budget at limit
        budget = manager._get_or_create_budget("boundary.com")
        budget.requests_today = budget.max_requests_per_day

        # When: Checking
        result = manager.can_request_to_domain("boundary.com")

        # Then: Denied
        assert result.allowed is False
        assert result.requests_remaining == 0

    def test_boundary_pages_minus_one(self, manager: DomainDailyBudgetManager) -> None:
        """Test: pages_today = max - 1 is allowed."""
        # Given: Page budget one below limit
        budget = manager._get_or_create_budget("boundary.com")
        budget.pages_today = budget.max_pages_per_day - 1

        # When: Checking
        result = manager.can_request_to_domain("boundary.com")

        # Then: Allowed with 1 remaining
        assert result.allowed is True
        assert result.pages_remaining == 1

    def test_boundary_pages_at_limit(self, manager: DomainDailyBudgetManager) -> None:
        """Test: pages_today = max is denied."""
        # Given: Page budget at limit
        budget = manager._get_or_create_budget("boundary.com")
        budget.pages_today = budget.max_pages_per_day

        # When: Checking
        result = manager.can_request_to_domain("boundary.com")

        # Then: Denied
        assert result.allowed is False
        assert result.pages_remaining == 0


# =============================================================================
# Exception Handling Tests
# =============================================================================


class TestExceptionHandling:
    """Tests for exception handling."""

    def test_record_exception_is_silent(self, manager: DomainDailyBudgetManager) -> None:
        """Test that exceptions during recording don't propagate."""
        # Given: Manager with exception in budget access
        with patch.object(manager, "_get_or_create_budget", side_effect=RuntimeError("Test error")):
            # When: Recording (should not raise)
            manager.record_domain_request("error.com")

        # Then: No exception raised (implicit pass)

    def test_get_limits_exception_uses_defaults(self, manager: DomainDailyBudgetManager) -> None:
        """Test that exception in get_limits uses defaults."""
        # Given: Policy manager that raises
        with patch("src.scheduler.domain_budget.get_domain_policy_manager") as mock_pm:
            mock_pm.side_effect = RuntimeError("Policy error")
            manager.clear_budgets()

            # When: Getting limits
            limits = manager._get_domain_limits("error.com")

        # Then: Uses defaults
        assert limits == (DEFAULT_MAX_REQUESTS_PER_DAY, DEFAULT_MAX_PAGES_PER_DAY)
