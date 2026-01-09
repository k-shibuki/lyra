"""
Unit tests for budget control module (src/scheduler/budget.py).

Tests ADR-0010 and ADR-0003 requirements:
- Task page limit: ≤120 pages/task
- Time limit: ≤60 minutes/task (GPU), ≤75 minutes (CPU)
- LLM time ratio: ≤30% of total processing time

Test quality: Follows .1 test code quality standards.

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-TB-01 | TaskBudget with defaults | Equivalence – default values | All fields initialized to spec defaults | - |
| TC-TB-02 | TaskBudget with fetched pages | Equivalence – calculation | remaining_pages correctly computed | - |
| TC-TB-03 | TaskBudget with elapsed time | Equivalence – calculation | remaining_time correctly computed | - |
| TC-TB-04 | TaskBudget with LLM time | Equivalence – calculation | current_llm_ratio correctly computed | - |
| TC-TB-05 | TaskBudget with partial LLM time | Equivalence – calculation | available_llm_time correctly computed | - |
| TC-TB-06 | TaskBudget within page limit | Equivalence – page check | can_fetch_page returns True | - |
| TC-TB-07 | TaskBudget at page limit | Boundary – page limit | can_fetch_page returns False | - |
| TC-TB-08 | Inactive TaskBudget | Abnormal – inactive | can_fetch_page returns False | - |
| TC-TB-09 | TaskBudget within limits | Equivalence – continuation | can_continue returns (True, None) | - |
| TC-TB-10 | TaskBudget at page limit | Boundary – page limit | can_continue returns (False, PAGE_LIMIT) | - |
| TC-TB-11 | TaskBudget past time limit | Boundary – time limit | can_continue returns (False, TIME_LIMIT) | - |
| TC-TB-12 | TaskBudget within LLM ratio | Equivalence – LLM check | can_run_llm returns True | - |
| TC-TB-13 | TaskBudget exceeding LLM ratio | Boundary – LLM ratio | can_run_llm returns False | - |
| TC-TB-14 | TaskBudget early phase (<30s) | Equivalence – early exemption | can_run_llm returns True regardless of ratio | - |
| TC-TB-15 | Record page fetch | Equivalence – mutation | pages_fetched increments | - |
| TC-TB-16 | Record LLM time | Equivalence – mutation | llm_time_seconds adds up | - |
| TC-TB-17 | Stop budget | Equivalence – termination | is_active=False, exceeded_reason set | - |
| TC-TB-18 | Serialize TaskBudget | Equivalence – serialization | to_dict returns all fields | - |
| TC-TB-BC-01 | budget_pages=0 | Boundary – zero limit | Cannot fetch, cannot continue | - |
| TC-TB-BC-02 | budget_pages=1 | Boundary – single page | One fetch allowed, then blocked | - |
| TC-TB-BC-03 | max_llm_ratio=0 | Boundary – zero ratio | No LLM allowed | - |
| TC-TB-BC-04 | max_time_seconds=1 (expired) | Boundary – short time | Cannot continue | - |
| TC-TB-BC-05 | Inactive budget operations | Abnormal – inactive | All operations rejected | - |
| TC-BM-01 | Create new budget | Equivalence – creation | Budget created with settings | - |
| TC-BM-02 | Create existing task_id | Equivalence – idempotent | Returns same budget | - |
| TC-BM-03 | Get existing budget | Equivalence – retrieval | Returns correct budget | - |
| TC-BM-04 | Get non-existent budget | Boundary – not found | Returns None | - |
| TC-BM-05 | check_and_update record_page | Equivalence – page recording | Increments and continues | - |
| TC-BM-06 | check_and_update llm_time | Equivalence – LLM recording | Adds time and continues | - |
| TC-BM-07 | check_and_update exceeds pages | Boundary – page limit | Stops budget, returns reason | - |
| TC-BM-08 | can_fetch_page via manager | Equivalence – delegation | Returns budget's status | - |
| TC-BM-09 | can_run_llm via manager | Equivalence – delegation | Returns budget's status | - |
| TC-BM-10 | get_remaining_budget | Equivalence – status | Returns dict with remaining values | - |
| TC-BM-11 | stop_budget | Equivalence – termination | Budget stopped with reason | - |
| TC-BM-12 | remove_budget | Equivalence – removal | Budget no longer retrievable | - |
| TC-BM-13 | get_all_active_budgets | Equivalence – filtering | Returns only active budgets | - |
| TC-BM-14 | enforce_limits within budget | Equivalence – no action | enforced=False | - |
| TC-BM-15 | enforce_limits page exceeded | Boundary – enforcement | enforced=True, budget stopped | - |
| TC-BM-16 | Operations on non-existent | Abnormal – missing | All operations allowed | - |
| TC-CF-01 | create_task_budget function | Equivalence – convenience | Creates budget from settings | - |
| TC-CF-02 | check_budget function | Equivalence – convenience | Updates and returns status | - |
| TC-CF-03 | can_fetch_page function | Equivalence – convenience | Returns fetch status | - |
| TC-CF-04 | can_run_llm function | Equivalence – convenience | Returns LLM status | - |
| TC-CF-05 | stop_task_budget function | Equivalence – convenience | Stops budget | - |
| TC-GPU-01 | GPU available | Equivalence – detection | Uses GPU time limit | - |
| TC-GPU-02 | GPU not available | Equivalence – detection | Uses CPU time limit | - |
| TC-INT-01 | Typical task lifecycle | Integration – full flow | Pages fetched, LLM recorded, stops at limit | - |
| TC-INT-02 | LLM ratio enforcement | Integration – ratio | LLM restricted after threshold | - |
"""

import time
from collections.abc import Generator
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit

from src.scheduler.budget import (
    BudgetExceededReason,
    BudgetManager,
    TaskBudget,
    can_fetch_page,
    can_run_llm,
    check_budget,
    create_task_budget,
    stop_task_budget,
)


class TestTaskBudget:
    """Tests for TaskBudget dataclass (ADR-0010, ADR-0003)."""

    def test_init_defaults(self) -> None:
        """Test default initialization matches ADR-0010 requirements.

        Verifies default values:
        - budget_pages=500 (default for longer research sessions)
        - max_llm_ratio=0.30 (ADR-0010: LLM processing ≤30%)
        """
        # Given: No specific configuration
        # When: Creating TaskBudget with only task_id
        budget = TaskBudget(task_id="test-1")
        # Then: All defaults match requirements

        assert budget.task_id == "test-1", "task_id should be set"
        assert budget.pages_fetched == 0, "pages_fetched should start at 0"
        assert budget.budget_pages == 500, "default budget_pages should be 500"
        assert budget.llm_time_seconds == 0.0, "llm_time should start at 0"
        assert budget.max_llm_ratio == 0.30, "default max_llm_ratio should be 0.30 (ADR-0010)"
        assert budget.is_active is True, "new budget should be active"
        assert budget.exceeded_reason is None, "no exceeded reason initially"

    def test_remaining_pages(self) -> None:
        """Test remaining pages calculation."""
        # Given: TaskBudget with budget_pages=100
        budget = TaskBudget(task_id="test-1", budget_pages=100)

        # When/Then: remaining_pages reflects fetched count
        assert budget.remaining_pages == 100

        budget.pages_fetched = 30
        assert budget.remaining_pages == 70

        budget.pages_fetched = 100
        assert budget.remaining_pages == 0

        # When: pages_fetched exceeds max
        # Then: remaining_pages is 0 (never negative)
        budget.pages_fetched = 150
        assert budget.remaining_pages == 0

    def test_remaining_time(self) -> None:
        """Test remaining time calculation."""
        # Given: TaskBudget with 60 second time limit
        budget = TaskBudget(
            task_id="test-1",
            max_time_seconds=60.0,
        )

        # When: Checking remaining time
        remaining = budget.remaining_time_seconds
        # Then: Remaining time should be close to max minus small elapsed
        assert remaining > 0
        assert remaining <= 60.0

    def test_current_llm_ratio(self) -> None:
        """Test LLM ratio calculation."""
        # Given: TaskBudget with 100 seconds elapsed
        budget = TaskBudget(task_id="test-1")
        budget.start_time = time.time() - 100

        # When: No LLM time used
        # Then: Ratio is 0.0
        assert budget.current_llm_ratio == 0.0

        # When: 10 seconds LLM time used
        budget.llm_time_seconds = 10.0
        ratio = budget.current_llm_ratio
        # Then: Ratio is ~0.1 (10/100)
        assert 0.09 <= ratio <= 0.11

    def test_available_llm_time(self) -> None:
        """Test available LLM time calculation."""
        # Given: TaskBudget with 30% LLM ratio and 100 seconds elapsed
        budget = TaskBudget(
            task_id="test-1",
            max_llm_ratio=0.30,
        )
        budget.start_time = time.time() - 100

        # When: 10 seconds LLM time already used (max=30s)
        budget.llm_time_seconds = 10.0
        available = budget.available_llm_time
        # Then: ~20 seconds remaining
        assert 19.0 <= available <= 21.0

    def test_can_fetch_page(self) -> None:
        """Test page fetch check."""
        # Given: TaskBudget with budget_pages=3
        budget = TaskBudget(task_id="test-1", budget_pages=3)

        # When: No pages fetched
        # Then: Can fetch
        assert budget.can_fetch_page() is True

        # When: 2 pages fetched
        budget.pages_fetched = 2
        # Then: Still can fetch
        assert budget.can_fetch_page() is True

        # When: At limit (3 pages)
        budget.pages_fetched = 3
        # Then: Cannot fetch
        assert budget.can_fetch_page() is False

        # When: Budget is inactive
        budget.pages_fetched = 0
        budget.is_active = False
        # Then: Cannot fetch
        assert budget.can_fetch_page() is False

    def test_can_continue_page_limit(self) -> None:
        """Test can_continue with page limit exceeded (ADR-0010: Total pages ≤120)."""
        # Given: TaskBudget with budget_pages=10
        budget = TaskBudget(task_id="test-1", budget_pages=10)

        # When: Under limit
        can_continue, reason = budget.can_continue()
        # Then: Can continue
        assert can_continue is True, "should continue when under limit"
        assert reason is None, "no reason when can continue"

        # When: At limit
        budget.pages_fetched = 10
        can_continue, reason = budget.can_continue()
        # Then: Cannot continue, PAGE_LIMIT reason
        assert can_continue is False, "should stop at page limit"
        assert reason == BudgetExceededReason.PAGE_LIMIT, "reason should be PAGE_LIMIT"

    def test_can_continue_time_limit(self) -> None:
        """Test can_continue with time limit exceeded (ADR-0010: Total time ≤20min)."""
        # Given: TaskBudget with 60 second limit, 120 seconds elapsed
        budget = TaskBudget(
            task_id="test-1",
            max_time_seconds=60.0,
        )
        budget.start_time = time.time() - 120

        # When: Checking continuation
        can_continue, reason = budget.can_continue()
        # Then: Cannot continue, TIME_LIMIT reason
        assert can_continue is False, "should stop when time exceeded"
        assert reason == BudgetExceededReason.TIME_LIMIT, "reason should be TIME_LIMIT"

    def test_can_run_llm(self) -> None:
        """Test LLM execution check.

        Note: LLM ratio check only applies after MIN_ELAPSED_FOR_RATIO_CHECK (30s).
        """
        # Given: TaskBudget with 30% LLM ratio, 100 seconds elapsed
        budget = TaskBudget(
            task_id="test-1",
            max_llm_ratio=0.30,
        )
        budget.start_time = time.time() - 100

        # When: No LLM time used
        # Then: Can run 10s LLM job
        assert budget.can_run_llm(10.0) is True

        # When: 25 seconds LLM time (25%) already used
        budget.llm_time_seconds = 25.0
        # Then: Adding 10s would exceed 30% ((25+10)/(100+10)=0.318)
        assert budget.can_run_llm(10.0) is False

        # When: Requesting only 3s more
        # Then: OK ((25+3)/(100+3)=0.272 < 0.30)
        assert budget.can_run_llm(3.0) is True

    def test_can_run_llm_early_task(self) -> None:
        """Test that LLM can always run during early task phase (<30s)."""
        # Given: TaskBudget with only 5 seconds elapsed (early phase)
        budget = TaskBudget(
            task_id="test-1",
            max_llm_ratio=0.30,
        )
        budget.start_time = time.time() - 5

        # When: Already at 80% ratio
        budget.llm_time_seconds = 4.0
        # Then: Can still run LLM during early phase
        assert budget.can_run_llm(10.0) is True

    def test_record_page_fetch(self) -> None:
        """Test page fetch recording."""
        # Given: Fresh TaskBudget
        budget = TaskBudget(task_id="test-1")
        assert budget.pages_fetched == 0

        # When: Recording page fetches
        budget.record_page_fetch()
        # Then: Count increments
        assert budget.pages_fetched == 1

        budget.record_page_fetch()
        assert budget.pages_fetched == 2

    def test_record_llm_time(self) -> None:
        """Test LLM time recording."""
        # Given: Fresh TaskBudget
        budget = TaskBudget(task_id="test-1")
        assert budget.llm_time_seconds == 0.0

        # When: Recording LLM time
        budget.record_llm_time(5.0)
        # Then: Time accumulates
        assert budget.llm_time_seconds == 5.0

        budget.record_llm_time(3.5)
        assert budget.llm_time_seconds == 8.5

    def test_stop(self) -> None:
        """Test budget stop."""
        # Given: Active TaskBudget
        budget = TaskBudget(task_id="test-1")
        assert budget.is_active is True

        # When: Stopping with PAGE_LIMIT reason
        budget.stop(BudgetExceededReason.PAGE_LIMIT)

        # Then: Budget is inactive with reason
        assert budget.is_active is False
        assert budget.exceeded_reason == BudgetExceededReason.PAGE_LIMIT

    def test_to_dict(self) -> None:
        """Test serialization to dict contains all required fields with correct values."""
        # Given: TaskBudget with some activity
        budget = TaskBudget(task_id="test-1", budget_pages=100)
        budget.pages_fetched = 5
        budget.llm_time_seconds = 2.5

        # When: Serializing to dict
        result = budget.to_dict()

        # Then: All fields present with correct values
        assert result["task_id"] == "test-1", "task_id mismatch"
        assert result["pages_fetched"] == 5, "pages_fetched mismatch"
        assert result["budget_pages"] == 100, "budget_pages mismatch"
        assert result["is_active"] is True, "is_active mismatch"
        assert result["remaining_pages"] == 95, "remaining_pages should be max-fetched"
        assert result["llm_time_seconds"] == 2.5, "llm_time_seconds mismatch"
        assert result["max_llm_ratio"] == 0.30, "max_llm_ratio mismatch"
        assert result["exceeded_reason"] is None, "exceeded_reason should be None"
        assert result["elapsed_seconds"] >= 0, "elapsed_seconds should be non-negative"
        assert result["max_time_seconds"] > 0, "max_time_seconds should be positive"
        assert result["remaining_time_seconds"] >= 0, "remaining_time should be non-negative"
        assert result["current_llm_ratio"] >= 0, "current_llm_ratio should be non-negative"
        assert result["available_llm_time"] >= 0, "available_llm_time should be non-negative"


class TestTaskBudgetBoundaryConditions:
    """Boundary condition tests for TaskBudget (.1.2)."""

    def test_zero_budget_pages(self) -> None:
        """Test budget with budget_pages=0 (edge case)."""
        # Given: TaskBudget with budget_pages=0
        budget = TaskBudget(task_id="test-1", budget_pages=0)

        # When/Then: Cannot fetch, remaining is 0
        assert budget.can_fetch_page() is False, "cannot fetch with budget_pages=0"
        assert budget.remaining_pages == 0, "remaining should be 0"

        # When/Then: Cannot continue
        can_continue, reason = budget.can_continue()
        assert can_continue is False, "cannot continue with budget_pages=0"
        assert reason == BudgetExceededReason.PAGE_LIMIT

    def test_single_page_budget(self) -> None:
        """Test budget with budget_pages=1."""
        # Given: TaskBudget with budget_pages=1
        budget = TaskBudget(task_id="test-1", budget_pages=1)

        # When: Before fetching
        # Then: Can fetch
        assert budget.can_fetch_page() is True, "can fetch first page"

        # When: After fetching one page
        budget.record_page_fetch()
        # Then: Cannot fetch more
        assert budget.can_fetch_page() is False, "cannot fetch after limit"

    def test_zero_llm_ratio(self) -> None:
        """Test budget with max_llm_ratio=0 (no LLM allowed)."""
        # Given: TaskBudget with max_llm_ratio=0, past threshold
        budget = TaskBudget(task_id="test-1", max_llm_ratio=0.0)
        budget.start_time = time.time() - 100

        # When/Then: Cannot run any LLM
        assert budget.can_run_llm(1.0) is False, "cannot run LLM with ratio=0"
        assert budget.available_llm_time == 0.0, "no LLM time available"

    def test_very_short_time_limit(self) -> None:
        """Test budget with very short time limit (1 second)."""
        # Given: TaskBudget with 1s limit, 2s elapsed (already expired)
        budget = TaskBudget(task_id="test-1", max_time_seconds=1.0)
        budget.start_time = time.time() - 2

        # When/Then: Cannot continue
        can_continue, reason = budget.can_continue()
        assert can_continue is False
        assert reason == BudgetExceededReason.TIME_LIMIT

    def test_inactive_budget_operations(self) -> None:
        """Test that inactive budget rejects all operations."""
        # Given: TaskBudget that has been stopped
        budget = TaskBudget(task_id="test-1")
        budget.stop(BudgetExceededReason.PAGE_LIMIT)

        # When/Then: All operations rejected
        assert budget.can_fetch_page() is False, "inactive budget cannot fetch"
        assert budget.can_run_llm(1.0) is False, "inactive budget cannot run LLM"

        can_continue, reason = budget.can_continue()
        assert can_continue is False
        assert reason == BudgetExceededReason.PAGE_LIMIT


class TestBudgetManager:
    """Tests for BudgetManager class (ADR-0003)."""

    @pytest.fixture
    def mock_settings(self) -> SimpleNamespace:
        """Mock settings for budget manager."""
        return SimpleNamespace(
            task_limits=SimpleNamespace(
                max_budget_pages_per_task=100,
                max_time_minutes_gpu=15,
                max_time_minutes_cpu=20,
                llm_time_ratio_max=0.25,
            )
        )

    @pytest.fixture
    def budget_manager(self, mock_settings: SimpleNamespace) -> BudgetManager:
        """Create budget manager with mocked settings."""
        with patch("src.scheduler.budget.get_settings", return_value=mock_settings):
            manager = BudgetManager()
        return manager

    @pytest.mark.asyncio
    async def test_create_budget(self, budget_manager: BudgetManager) -> None:
        """Test budget creation."""
        # Given: BudgetManager with mock settings
        # When: Creating budget for task-1
        budget = await budget_manager.create_budget("task-1")

        # Then: Budget created with settings values
        assert budget.task_id == "task-1"
        assert budget.budget_pages == 100
        assert budget.max_llm_ratio == 0.25
        assert budget.is_active is True

    @pytest.mark.asyncio
    async def test_create_budget_idempotent(self, budget_manager: BudgetManager) -> None:
        """Test that creating same budget returns existing one."""
        # Given: BudgetManager
        # When: Creating budget twice for same task
        budget1 = await budget_manager.create_budget("task-1")
        budget2 = await budget_manager.create_budget("task-1")

        # Then: Same budget instance returned
        assert budget1 is budget2

    @pytest.mark.asyncio
    async def test_get_budget(self, budget_manager: BudgetManager) -> None:
        """Test budget retrieval."""
        # Given: BudgetManager
        # When: Getting non-existent budget
        budget = await budget_manager.get_budget("nonexistent")
        # Then: Returns None
        assert budget is None

        # When: Creating and retrieving budget
        await budget_manager.create_budget("task-1")
        budget = await budget_manager.get_budget("task-1")
        # Then: Returns the budget
        assert budget is not None
        assert budget.task_id == "task-1"

    @pytest.mark.asyncio
    async def test_check_and_update_record_page(self, budget_manager: BudgetManager) -> None:
        """Test page recording through check_and_update."""
        # Given: Budget for task-1
        await budget_manager.create_budget("task-1")

        # When: Recording a page fetch
        can_continue, reason = await budget_manager.check_and_update(
            "task-1",
            record_page=True,
        )

        # Then: Can continue, page count incremented
        assert can_continue is True
        assert reason is None

        budget = await budget_manager.get_budget("task-1")
        assert budget is not None
        assert budget.pages_fetched == 1

    @pytest.mark.asyncio
    async def test_check_and_update_record_llm(self, budget_manager: BudgetManager) -> None:
        """Test LLM time recording through check_and_update."""
        # Given: Budget for task-1
        await budget_manager.create_budget("task-1")

        # When: Recording LLM time
        can_continue, reason = await budget_manager.check_and_update(
            "task-1",
            llm_time_seconds=5.0,
        )

        # Then: Can continue, LLM time recorded
        assert can_continue is True

        budget = await budget_manager.get_budget("task-1")
        assert budget is not None
        assert budget.llm_time_seconds == 5.0

    @pytest.mark.asyncio
    async def test_check_and_update_exceeds_pages(self, budget_manager: BudgetManager) -> None:
        """Test budget stop when pages exceeded."""
        # Given: Budget at 99 pages (one below limit of 100)
        budget = await budget_manager.create_budget("task-1")
        budget.pages_fetched = 99

        # When: Recording one more page
        can_continue, reason = await budget_manager.check_and_update(
            "task-1",
            record_page=True,
        )

        # When: Checking continuation at limit
        can_continue, reason = await budget_manager.check_and_update("task-1")
        # Then: Cannot continue, budget stopped
        assert can_continue is False
        assert reason == BudgetExceededReason.PAGE_LIMIT
        assert budget.is_active is False

    @pytest.mark.asyncio
    async def test_can_fetch_page(self, budget_manager: BudgetManager) -> None:
        """Test page fetch check."""
        # Given: Budget for task-1
        await budget_manager.create_budget("task-1")

        # When: Initially
        # Then: Can fetch
        assert await budget_manager.can_fetch_page("task-1") is True

        # When: At page limit
        budget = await budget_manager.get_budget("task-1")
        assert budget is not None
        budget.pages_fetched = 100
        # Then: Cannot fetch
        assert await budget_manager.can_fetch_page("task-1") is False

    @pytest.mark.asyncio
    async def test_can_run_llm(self, budget_manager: BudgetManager) -> None:
        """Test LLM run check (after 30s threshold)."""
        # Given: Budget with 100 seconds elapsed
        budget = await budget_manager.create_budget("task-1")
        budget.start_time = time.time() - 100

        # When: No LLM time used
        # Then: Can run
        assert await budget_manager.can_run_llm("task-1", 10.0) is True

        # When: 24% LLM time already used
        budget.llm_time_seconds = 24.0
        # Then: Adding 10s would exceed 25% limit
        assert await budget_manager.can_run_llm("task-1", 10.0) is False

    @pytest.mark.asyncio
    async def test_get_remaining_budget(self, budget_manager: BudgetManager) -> None:
        """Test remaining budget retrieval."""
        # Given: Budget for task-1
        await budget_manager.create_budget("task-1")

        # When: Getting remaining budget
        remaining = await budget_manager.get_remaining_budget("task-1")

        # Then: Contains all required fields
        assert remaining is not None
        assert remaining["remaining_pages"] == 100
        assert remaining["is_active"] is True
        assert "remaining_time_seconds" in remaining
        assert "available_llm_time" in remaining

    @pytest.mark.asyncio
    async def test_stop_budget(self, budget_manager: BudgetManager) -> None:
        """Test budget stopping."""
        # Given: Active budget
        budget = await budget_manager.create_budget("task-1")
        assert budget.is_active is True

        # When: Stopping with TIME_LIMIT reason
        await budget_manager.stop_budget("task-1", BudgetExceededReason.TIME_LIMIT)

        # Then: Budget inactive with reason
        assert budget.is_active is False
        assert budget.exceeded_reason == BudgetExceededReason.TIME_LIMIT

    @pytest.mark.asyncio
    async def test_remove_budget(self, budget_manager: BudgetManager) -> None:
        """Test budget removal."""
        # Given: Budget for task-1
        await budget_manager.create_budget("task-1")
        budget = await budget_manager.get_budget("task-1")
        assert budget is not None

        # When: Removing budget
        await budget_manager.remove_budget("task-1")

        # Then: Budget no longer retrievable
        budget = await budget_manager.get_budget("task-1")
        assert budget is None

    @pytest.mark.asyncio
    async def test_get_all_active_budgets(self, budget_manager: BudgetManager) -> None:
        """Test getting all active budgets."""
        # Given: Two budgets, one stopped
        await budget_manager.create_budget("task-1")
        await budget_manager.create_budget("task-2")
        await budget_manager.stop_budget("task-1", None)

        # When: Getting all active budgets
        active = await budget_manager.get_all_active_budgets()

        # Then: Only active budget returned
        assert len(active) == 1
        assert active[0]["task_id"] == "task-2"

    @pytest.mark.asyncio
    async def test_enforce_limits_no_action(self, budget_manager: BudgetManager) -> None:
        """Test enforce_limits when within budget."""
        # Given: Fresh budget within limits
        await budget_manager.create_budget("task-1")

        # When: Enforcing limits
        result = await budget_manager.enforce_limits("task-1")

        # Then: No enforcement needed
        assert result["enforced"] is False
        assert "budget" in result

    @pytest.mark.asyncio
    async def test_enforce_limits_page_exceeded(self, budget_manager: BudgetManager) -> None:
        """Test enforce_limits when pages exceeded."""
        # Given: Budget at page limit
        budget = await budget_manager.create_budget("task-1")
        budget.pages_fetched = 100

        # When: Enforcing limits
        result = await budget_manager.enforce_limits("task-1")

        # Then: Enforcement triggered
        assert result["enforced"] is True
        assert result["reason"] == BudgetExceededReason.PAGE_LIMIT.value
        assert budget.is_active is False

    @pytest.mark.asyncio
    async def test_no_budget_returns_true(self, budget_manager: BudgetManager) -> None:
        """Test that non-existent budget allows all operations."""
        # Given: No budget for "nonexistent"
        # When: Performing operations
        can_continue, reason = await budget_manager.check_and_update(
            "nonexistent",
            record_page=True,
        )

        # Then: All operations allowed
        assert can_continue is True
        assert reason is None
        assert await budget_manager.can_fetch_page("nonexistent") is True
        assert await budget_manager.can_run_llm("nonexistent", 100.0) is True


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    @pytest.fixture(autouse=True)
    def reset_global_manager(self) -> Generator[None]:
        """Reset global budget manager between tests."""
        import src.scheduler.budget as budget_module

        budget_module._budget_manager = None
        yield
        budget_module._budget_manager = None

    @pytest.fixture
    def mock_settings(self) -> SimpleNamespace:
        """Mock settings."""
        return SimpleNamespace(
            task_limits=SimpleNamespace(
                max_budget_pages_per_task=50,
                max_time_minutes_gpu=10,
                max_time_minutes_cpu=15,
                llm_time_ratio_max=0.30,
            )
        )

    @pytest.mark.asyncio
    async def test_create_task_budget(self, mock_settings: SimpleNamespace) -> None:
        """Test create_task_budget function."""
        # Given: Mock settings
        # When: Creating task budget via convenience function
        with patch("src.scheduler.budget.get_settings", return_value=mock_settings):
            budget = await create_task_budget("task-1")

        # Then: Budget created with settings values
        assert budget.task_id == "task-1"
        assert budget.budget_pages == 50

    @pytest.mark.asyncio
    async def test_check_budget(self, mock_settings: SimpleNamespace) -> None:
        """Test check_budget function."""
        # Given: Existing budget
        with patch("src.scheduler.budget.get_settings", return_value=mock_settings):
            await create_task_budget("task-1")

            # When: Checking budget with page record
            can_continue, reason = await check_budget(
                "task-1",
                record_page=True,
            )

            # Then: Can continue
            assert can_continue is True
            assert reason is None

    @pytest.mark.asyncio
    async def test_can_fetch_page_function(self, mock_settings: SimpleNamespace) -> None:
        """Test can_fetch_page function."""
        # Given: Existing budget
        with patch("src.scheduler.budget.get_settings", return_value=mock_settings):
            await create_task_budget("task-1")

            # When: Checking if can fetch
            result = await can_fetch_page("task-1")
            # Then: Can fetch
            assert result is True

    @pytest.mark.asyncio
    async def test_can_run_llm_function(self, mock_settings: SimpleNamespace) -> None:
        """Test can_run_llm function."""
        # Given: Existing budget
        with patch("src.scheduler.budget.get_settings", return_value=mock_settings):
            await create_task_budget("task-1")

            # When: Checking if can run LLM
            result = await can_run_llm("task-1", 5.0)
            # Then: Can run
            assert result is True

    @pytest.mark.asyncio
    async def test_stop_task_budget_function(self, mock_settings: SimpleNamespace) -> None:
        """Test stop_task_budget function."""
        # Given: Active budget
        with patch("src.scheduler.budget.get_settings", return_value=mock_settings):
            budget = await create_task_budget("task-1")
            assert budget.is_active is True

            # When: Stopping via convenience function
            await stop_task_budget("task-1", BudgetExceededReason.PAGE_LIMIT)

            # Then: Budget is inactive
            assert budget.is_active is False


class TestBudgetManagerGPUDetection:
    """Tests for GPU detection in BudgetManager."""

    def test_gpu_available_time_limit(self) -> None:
        """Test that GPU availability affects time limit."""
        from types import SimpleNamespace

        # Given: Settings with different GPU/CPU time limits
        settings = SimpleNamespace(
            task_limits=SimpleNamespace(
                max_budget_pages_per_task=100,
                max_time_minutes_gpu=60,
                max_time_minutes_cpu=75,
                llm_time_ratio_max=0.30,
            )
        )

        # When: GPU is available
        with patch("src.scheduler.budget.get_settings", return_value=settings):
            with patch.object(BudgetManager, "_check_gpu_available", return_value=True):
                manager = BudgetManager()
                # Then: Uses GPU time limit
                assert manager._max_time == 60 * 60

        # When: GPU is not available
        with patch("src.scheduler.budget.get_settings", return_value=settings):
            with patch.object(BudgetManager, "_check_gpu_available", return_value=False):
                manager = BudgetManager()
                # Then: Uses CPU time limit
                assert manager._max_time == 75 * 60


class TestBudgetIntegrationScenarios:
    """Integration-style tests for budget control scenarios (ADR-0010, ADR-0003)."""

    @pytest.fixture
    def mock_settings(self) -> SimpleNamespace:
        """Settings for integration tests.

        Uses reduced limits for faster test execution while
        maintaining realistic proportions.
        """
        return SimpleNamespace(
            task_limits=SimpleNamespace(
                max_budget_pages_per_task=10,
                max_time_minutes_gpu=1,  # 1 minute for quick tests
                max_time_minutes_cpu=1,
                llm_time_ratio_max=0.30,
            )
        )

    @pytest.mark.asyncio
    async def test_typical_task_lifecycle(self, mock_settings: SimpleNamespace) -> None:
        """Test a typical task budget lifecycle.

        Simulates a research task that:
        1. Creates budget
        2. Fetches pages progressively
        3. Records LLM processing time
        4. Hits page limit and stops

        Verifies ADR-0010 requirement: Total pages ≤budget_pages.
        """
        with patch("src.scheduler.budget.get_settings", return_value=mock_settings):
            # Given: BudgetManager with budget_pages=10
            manager = BudgetManager()

            # When: Creating budget
            budget = await manager.create_budget("task-1")
            # Then: Budget is active
            assert budget.is_active is True, "budget should be active initially"

            # When: Fetching first 5 pages
            for i in range(5):
                can_continue, _ = await manager.check_and_update(
                    "task-1",
                    record_page=True,
                )
                assert can_continue is True, f"should continue at page {i + 1}"

            # Then: 5 pages recorded
            assert budget.pages_fetched == 5, "should have fetched 5 pages"

            # When: Recording LLM time
            await manager.check_and_update(
                "task-1",
                llm_time_seconds=2.0,
            )

            # When: Fetching more pages
            for _i in range(4):
                await manager.check_and_update(
                    "task-1",
                    record_page=True,
                )

            # Then: 9 pages recorded
            assert budget.pages_fetched == 9, "should have fetched 9 pages"

            # When: Fetching 10th page (at limit)
            can_continue, reason = await manager.check_and_update(
                "task-1",
                record_page=True,
            )

            # When: Checking continuation at limit
            can_continue, reason = await manager.check_and_update("task-1")
            # Then: Cannot continue
            assert can_continue is False, "should stop at page limit"
            assert reason == BudgetExceededReason.PAGE_LIMIT, "reason should be PAGE_LIMIT"

    @pytest.mark.asyncio
    async def test_llm_ratio_enforcement(self, mock_settings: SimpleNamespace) -> None:
        """Test LLM ratio enforcement scenario.

        Note: LLM ratio check only applies after MIN_ELAPSED_FOR_RATIO_CHECK (30s).
        """
        with patch("src.scheduler.budget.get_settings", return_value=mock_settings):
            # Given: Budget with 50 seconds elapsed (above 30s threshold)
            manager = BudgetManager()
            budget = await manager.create_budget("task-1")
            budget.start_time = time.time() - 50

            # When: Trying to use 10s LLM (30% of 50s = 15s allowed)
            # Then: Can run
            assert await manager.can_run_llm("task-1", 10.0) is True
            await manager.check_and_update("task-1", llm_time_seconds=10.0)

            # When: Trying to use 3s more (projected 13/54 = 0.24 < 0.30)
            # Then: Can run
            assert await manager.can_run_llm("task-1", 3.0) is True
            await manager.check_and_update("task-1", llm_time_seconds=3.0)

            # When: Trying to use 5s more (projected 18/56 = 0.32 > 0.30)
            # Then: Cannot run
            assert await manager.can_run_llm("task-1", 5.0) is False
