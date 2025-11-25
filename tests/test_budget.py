"""
Unit tests for budget control module (src/scheduler/budget.py).

Tests §3.1 and §3.2.2 requirements:
- Task page limit: ≤120 pages/task
- Time limit: ≤20 minutes/task (GPU), ≤25 minutes (CPU)
- LLM time ratio: ≤30% of total processing time

Test quality: Follows §7.1 test code quality standards.
"""

import asyncio
import time
from unittest.mock import patch, MagicMock

import pytest

from src.scheduler.budget import (
    TaskBudget,
    BudgetManager,
    BudgetExceededReason,
    get_budget_manager,
    create_task_budget,
    check_budget,
    can_fetch_page,
    can_run_llm,
    stop_task_budget,
)


class TestTaskBudget:
    """Tests for TaskBudget dataclass (§3.1, §3.2.2)."""
    
    def test_init_defaults(self):
        """Test default initialization matches §3.1 requirements.
        
        Verifies default values:
        - max_pages=120 (§3.1: 総ページ数≤120/タスク)
        - max_llm_ratio=0.30 (§3.1: LLM処理≤30%)
        """
        budget = TaskBudget(task_id="test-1")
        
        assert budget.task_id == "test-1", "task_id should be set"
        assert budget.pages_fetched == 0, "pages_fetched should start at 0"
        assert budget.max_pages == 120, "default max_pages should be 120 (§3.1)"
        assert budget.llm_time_seconds == 0.0, "llm_time should start at 0"
        assert budget.max_llm_ratio == 0.30, "default max_llm_ratio should be 0.30 (§3.1)"
        assert budget.is_active is True, "new budget should be active"
        assert budget.exceeded_reason is None, "no exceeded reason initially"
    
    def test_remaining_pages(self):
        """Test remaining pages calculation."""
        budget = TaskBudget(task_id="test-1", max_pages=100)
        
        assert budget.remaining_pages == 100
        
        budget.pages_fetched = 30
        assert budget.remaining_pages == 70
        
        budget.pages_fetched = 100
        assert budget.remaining_pages == 0
        
        budget.pages_fetched = 150
        assert budget.remaining_pages == 0  # Never negative
    
    def test_remaining_time(self):
        """Test remaining time calculation."""
        budget = TaskBudget(
            task_id="test-1",
            max_time_seconds=60.0,
        )
        
        # Remaining time should be close to max minus small elapsed
        remaining = budget.remaining_time_seconds
        assert remaining > 0
        assert remaining <= 60.0
    
    def test_current_llm_ratio(self):
        """Test LLM ratio calculation."""
        budget = TaskBudget(task_id="test-1")
        budget.start_time = time.time() - 100  # 100 seconds ago
        
        # No LLM time
        assert budget.current_llm_ratio == 0.0
        
        # 10 seconds LLM / 100 seconds = 0.1
        budget.llm_time_seconds = 10.0
        ratio = budget.current_llm_ratio
        assert 0.09 <= ratio <= 0.11
    
    def test_available_llm_time(self):
        """Test available LLM time calculation."""
        budget = TaskBudget(
            task_id="test-1",
            max_llm_ratio=0.30,
        )
        budget.start_time = time.time() - 100  # 100 seconds elapsed
        
        # Max LLM time = 0.30 * 100 = 30 seconds
        budget.llm_time_seconds = 10.0
        available = budget.available_llm_time
        assert 19.0 <= available <= 21.0  # ~20 seconds remaining
    
    def test_can_fetch_page(self):
        """Test page fetch check."""
        budget = TaskBudget(task_id="test-1", max_pages=3)
        
        assert budget.can_fetch_page() is True
        
        budget.pages_fetched = 2
        assert budget.can_fetch_page() is True
        
        budget.pages_fetched = 3
        assert budget.can_fetch_page() is False
        
        # Inactive budget
        budget.pages_fetched = 0
        budget.is_active = False
        assert budget.can_fetch_page() is False
    
    def test_can_continue_page_limit(self):
        """Test can_continue with page limit exceeded (§3.1: 総ページ数≤120)."""
        budget = TaskBudget(task_id="test-1", max_pages=10)
        
        can_continue, reason = budget.can_continue()
        assert can_continue is True, "should continue when under limit"
        assert reason is None, "no reason when can continue"
        
        budget.pages_fetched = 10
        can_continue, reason = budget.can_continue()
        assert can_continue is False, "should stop at page limit"
        assert reason == BudgetExceededReason.PAGE_LIMIT, "reason should be PAGE_LIMIT"
    
    def test_can_continue_time_limit(self):
        """Test can_continue with time limit exceeded (§3.1: 総時間≤20分)."""
        budget = TaskBudget(
            task_id="test-1",
            max_time_seconds=60.0,
        )
        budget.start_time = time.time() - 120  # 120 seconds ago (> 60s limit)
        
        can_continue, reason = budget.can_continue()
        assert can_continue is False, "should stop when time exceeded"
        assert reason == BudgetExceededReason.TIME_LIMIT, "reason should be TIME_LIMIT"
    
    def test_can_run_llm(self):
        """Test LLM execution check.
        
        Note: LLM ratio check only applies after MIN_ELAPSED_FOR_RATIO_CHECK (30s).
        """
        budget = TaskBudget(
            task_id="test-1",
            max_llm_ratio=0.30,
        )
        budget.start_time = time.time() - 100  # 100 seconds elapsed
        
        # With no LLM time, can run
        assert budget.can_run_llm(10.0) is True
        
        # With 25 seconds LLM time (25%), adding 10 would exceed 30%
        budget.llm_time_seconds = 25.0
        # Projected: (25+10) / (100+10) = 35/110 = 0.318 > 0.30
        assert budget.can_run_llm(10.0) is False
        
        # But 3 seconds would be OK
        # Projected: (25+3) / (100+3) = 28/103 = 0.272 < 0.30
        assert budget.can_run_llm(3.0) is True
    
    def test_can_run_llm_early_task(self):
        """Test that LLM can always run during early task phase (<30s)."""
        budget = TaskBudget(
            task_id="test-1",
            max_llm_ratio=0.30,
        )
        budget.start_time = time.time() - 5  # Only 5 seconds elapsed
        
        # Even with high projected ratio, should allow during early phase
        budget.llm_time_seconds = 4.0  # Already 80% ratio
        assert budget.can_run_llm(10.0) is True  # Would push to >100% but allowed
    
    def test_record_page_fetch(self):
        """Test page fetch recording."""
        budget = TaskBudget(task_id="test-1")
        
        assert budget.pages_fetched == 0
        
        budget.record_page_fetch()
        assert budget.pages_fetched == 1
        
        budget.record_page_fetch()
        assert budget.pages_fetched == 2
    
    def test_record_llm_time(self):
        """Test LLM time recording."""
        budget = TaskBudget(task_id="test-1")
        
        assert budget.llm_time_seconds == 0.0
        
        budget.record_llm_time(5.0)
        assert budget.llm_time_seconds == 5.0
        
        budget.record_llm_time(3.5)
        assert budget.llm_time_seconds == 8.5
    
    def test_stop(self):
        """Test budget stop."""
        budget = TaskBudget(task_id="test-1")
        
        assert budget.is_active is True
        
        budget.stop(BudgetExceededReason.PAGE_LIMIT)
        
        assert budget.is_active is False
        assert budget.exceeded_reason == BudgetExceededReason.PAGE_LIMIT
    
    def test_to_dict(self):
        """Test serialization to dict contains all required fields with correct values."""
        budget = TaskBudget(task_id="test-1", max_pages=100)
        budget.pages_fetched = 5
        budget.llm_time_seconds = 2.5
        
        result = budget.to_dict()
        
        # Verify all fields are present and have correct values
        assert result["task_id"] == "test-1", "task_id mismatch"
        assert result["pages_fetched"] == 5, "pages_fetched mismatch"
        assert result["max_pages"] == 100, "max_pages mismatch"
        assert result["is_active"] is True, "is_active mismatch"
        assert result["remaining_pages"] == 95, "remaining_pages should be max-fetched"
        assert result["llm_time_seconds"] == 2.5, "llm_time_seconds mismatch"
        assert result["max_llm_ratio"] == 0.30, "max_llm_ratio mismatch"
        assert result["exceeded_reason"] is None, "exceeded_reason should be None"
        # Time-dependent fields: verify they exist and are reasonable
        assert result["elapsed_seconds"] >= 0, "elapsed_seconds should be non-negative"
        assert result["max_time_seconds"] > 0, "max_time_seconds should be positive"
        assert result["remaining_time_seconds"] >= 0, "remaining_time should be non-negative"
        assert result["current_llm_ratio"] >= 0, "current_llm_ratio should be non-negative"
        assert result["available_llm_time"] >= 0, "available_llm_time should be non-negative"


class TestTaskBudgetBoundaryConditions:
    """Boundary condition tests for TaskBudget (§7.1.2)."""
    
    def test_zero_max_pages(self):
        """Test budget with max_pages=0 (edge case)."""
        budget = TaskBudget(task_id="test-1", max_pages=0)
        
        assert budget.can_fetch_page() is False, "cannot fetch with max_pages=0"
        assert budget.remaining_pages == 0, "remaining should be 0"
        
        can_continue, reason = budget.can_continue()
        assert can_continue is False, "cannot continue with max_pages=0"
        assert reason == BudgetExceededReason.PAGE_LIMIT
    
    def test_single_page_budget(self):
        """Test budget with max_pages=1."""
        budget = TaskBudget(task_id="test-1", max_pages=1)
        
        assert budget.can_fetch_page() is True, "can fetch first page"
        budget.record_page_fetch()
        assert budget.can_fetch_page() is False, "cannot fetch after limit"
    
    def test_zero_llm_ratio(self):
        """Test budget with max_llm_ratio=0 (no LLM allowed)."""
        budget = TaskBudget(task_id="test-1", max_llm_ratio=0.0)
        budget.start_time = time.time() - 100  # Past threshold
        
        # Cannot run any LLM
        assert budget.can_run_llm(1.0) is False, "cannot run LLM with ratio=0"
        assert budget.available_llm_time == 0.0, "no LLM time available"
    
    def test_very_short_time_limit(self):
        """Test budget with very short time limit (1 second)."""
        budget = TaskBudget(task_id="test-1", max_time_seconds=1.0)
        budget.start_time = time.time() - 2  # Already expired
        
        can_continue, reason = budget.can_continue()
        assert can_continue is False
        assert reason == BudgetExceededReason.TIME_LIMIT
    
    def test_inactive_budget_operations(self):
        """Test that inactive budget rejects all operations."""
        budget = TaskBudget(task_id="test-1")
        budget.stop(BudgetExceededReason.PAGE_LIMIT)
        
        assert budget.can_fetch_page() is False, "inactive budget cannot fetch"
        assert budget.can_run_llm(1.0) is False, "inactive budget cannot run LLM"
        
        can_continue, reason = budget.can_continue()
        assert can_continue is False
        assert reason == BudgetExceededReason.PAGE_LIMIT


class TestBudgetManager:
    """Tests for BudgetManager class (§3.2.2)."""
    
    @pytest.fixture
    def mock_settings(self):
        """Mock settings for budget manager."""
        return {
            "task_limits": {
                "max_pages_per_task": 100,
                "max_time_minutes_gpu": 15,
                "max_time_minutes_cpu": 20,
                "llm_time_ratio_max": 0.25,
            }
        }
    
    @pytest.fixture
    def budget_manager(self, mock_settings):
        """Create budget manager with mocked settings."""
        with patch("src.scheduler.budget.get_settings", return_value=mock_settings):
            manager = BudgetManager()
        return manager
    
    @pytest.mark.asyncio
    async def test_create_budget(self, budget_manager):
        """Test budget creation."""
        budget = await budget_manager.create_budget("task-1")
        
        assert budget.task_id == "task-1"
        assert budget.max_pages == 100
        assert budget.max_llm_ratio == 0.25
        assert budget.is_active is True
    
    @pytest.mark.asyncio
    async def test_create_budget_idempotent(self, budget_manager):
        """Test that creating same budget returns existing one."""
        budget1 = await budget_manager.create_budget("task-1")
        budget2 = await budget_manager.create_budget("task-1")
        
        assert budget1 is budget2
    
    @pytest.mark.asyncio
    async def test_get_budget(self, budget_manager):
        """Test budget retrieval."""
        # Non-existent budget
        budget = await budget_manager.get_budget("nonexistent")
        assert budget is None
        
        # Create and retrieve
        await budget_manager.create_budget("task-1")
        budget = await budget_manager.get_budget("task-1")
        assert budget is not None
        assert budget.task_id == "task-1"
    
    @pytest.mark.asyncio
    async def test_check_and_update_record_page(self, budget_manager):
        """Test page recording through check_and_update."""
        await budget_manager.create_budget("task-1")
        
        can_continue, reason = await budget_manager.check_and_update(
            "task-1",
            record_page=True,
        )
        
        assert can_continue is True
        assert reason is None
        
        budget = await budget_manager.get_budget("task-1")
        assert budget.pages_fetched == 1
    
    @pytest.mark.asyncio
    async def test_check_and_update_record_llm(self, budget_manager):
        """Test LLM time recording through check_and_update."""
        await budget_manager.create_budget("task-1")
        
        can_continue, reason = await budget_manager.check_and_update(
            "task-1",
            llm_time_seconds=5.0,
        )
        
        assert can_continue is True
        
        budget = await budget_manager.get_budget("task-1")
        assert budget.llm_time_seconds == 5.0
    
    @pytest.mark.asyncio
    async def test_check_and_update_exceeds_pages(self, budget_manager):
        """Test budget stop when pages exceeded."""
        budget = await budget_manager.create_budget("task-1")
        budget.pages_fetched = 99  # One below limit
        
        # Record one more page
        can_continue, reason = await budget_manager.check_and_update(
            "task-1",
            record_page=True,
        )
        
        # Now at 100 pages (limit), should not continue
        can_continue, reason = await budget_manager.check_and_update("task-1")
        assert can_continue is False
        assert reason == BudgetExceededReason.PAGE_LIMIT
        assert budget.is_active is False
    
    @pytest.mark.asyncio
    async def test_can_fetch_page(self, budget_manager):
        """Test page fetch check."""
        await budget_manager.create_budget("task-1")
        
        # Can fetch initially
        assert await budget_manager.can_fetch_page("task-1") is True
        
        # Set pages to limit
        budget = await budget_manager.get_budget("task-1")
        budget.pages_fetched = 100
        
        assert await budget_manager.can_fetch_page("task-1") is False
    
    @pytest.mark.asyncio
    async def test_can_run_llm(self, budget_manager):
        """Test LLM run check (after 30s threshold)."""
        budget = await budget_manager.create_budget("task-1")
        budget.start_time = time.time() - 100  # 100 seconds elapsed (>30s threshold)
        
        # Can run initially (no LLM time)
        assert await budget_manager.can_run_llm("task-1", 10.0) is True
        
        # With high LLM time, cannot run more
        budget.llm_time_seconds = 24.0  # 24% already
        # Projected: (24+10) / (100+10) = 34/110 = 0.31 > 0.25
        assert await budget_manager.can_run_llm("task-1", 10.0) is False
    
    @pytest.mark.asyncio
    async def test_get_remaining_budget(self, budget_manager):
        """Test remaining budget retrieval."""
        await budget_manager.create_budget("task-1")
        
        remaining = await budget_manager.get_remaining_budget("task-1")
        
        assert remaining is not None
        assert remaining["remaining_pages"] == 100
        assert remaining["is_active"] is True
        assert "remaining_time_seconds" in remaining
        assert "available_llm_time" in remaining
    
    @pytest.mark.asyncio
    async def test_stop_budget(self, budget_manager):
        """Test budget stopping."""
        budget = await budget_manager.create_budget("task-1")
        
        assert budget.is_active is True
        
        await budget_manager.stop_budget(
            "task-1",
            BudgetExceededReason.TIME_LIMIT
        )
        
        assert budget.is_active is False
        assert budget.exceeded_reason == BudgetExceededReason.TIME_LIMIT
    
    @pytest.mark.asyncio
    async def test_remove_budget(self, budget_manager):
        """Test budget removal."""
        await budget_manager.create_budget("task-1")
        
        budget = await budget_manager.get_budget("task-1")
        assert budget is not None
        
        await budget_manager.remove_budget("task-1")
        
        budget = await budget_manager.get_budget("task-1")
        assert budget is None
    
    @pytest.mark.asyncio
    async def test_get_all_active_budgets(self, budget_manager):
        """Test getting all active budgets."""
        await budget_manager.create_budget("task-1")
        await budget_manager.create_budget("task-2")
        
        # Stop one budget
        await budget_manager.stop_budget("task-1", None)
        
        active = await budget_manager.get_all_active_budgets()
        
        assert len(active) == 1
        assert active[0]["task_id"] == "task-2"
    
    @pytest.mark.asyncio
    async def test_enforce_limits_no_action(self, budget_manager):
        """Test enforce_limits when within budget."""
        await budget_manager.create_budget("task-1")
        
        result = await budget_manager.enforce_limits("task-1")
        
        assert result["enforced"] is False
        assert "budget" in result
    
    @pytest.mark.asyncio
    async def test_enforce_limits_page_exceeded(self, budget_manager):
        """Test enforce_limits when pages exceeded."""
        budget = await budget_manager.create_budget("task-1")
        budget.pages_fetched = 100  # At limit
        
        result = await budget_manager.enforce_limits("task-1")
        
        assert result["enforced"] is True
        assert result["reason"] == BudgetExceededReason.PAGE_LIMIT.value
        assert budget.is_active is False
    
    @pytest.mark.asyncio
    async def test_no_budget_returns_true(self, budget_manager):
        """Test that non-existent budget allows all operations."""
        can_continue, reason = await budget_manager.check_and_update(
            "nonexistent",
            record_page=True,
        )
        
        assert can_continue is True
        assert reason is None
        
        assert await budget_manager.can_fetch_page("nonexistent") is True
        assert await budget_manager.can_run_llm("nonexistent", 100.0) is True


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""
    
    @pytest.fixture(autouse=True)
    def reset_global_manager(self):
        """Reset global budget manager between tests."""
        import src.scheduler.budget as budget_module
        budget_module._budget_manager = None
        yield
        budget_module._budget_manager = None
    
    @pytest.fixture
    def mock_settings(self):
        """Mock settings."""
        return {
            "task_limits": {
                "max_pages_per_task": 50,
                "max_time_minutes_gpu": 10,
                "max_time_minutes_cpu": 15,
                "llm_time_ratio_max": 0.30,
            }
        }
    
    @pytest.mark.asyncio
    async def test_create_task_budget(self, mock_settings):
        """Test create_task_budget function."""
        with patch("src.scheduler.budget.get_settings", return_value=mock_settings):
            budget = await create_task_budget("task-1")
        
        assert budget.task_id == "task-1"
        assert budget.max_pages == 50
    
    @pytest.mark.asyncio
    async def test_check_budget(self, mock_settings):
        """Test check_budget function."""
        with patch("src.scheduler.budget.get_settings", return_value=mock_settings):
            await create_task_budget("task-1")
            
            can_continue, reason = await check_budget(
                "task-1",
                record_page=True,
            )
            
            assert can_continue is True
            assert reason is None
    
    @pytest.mark.asyncio
    async def test_can_fetch_page_function(self, mock_settings):
        """Test can_fetch_page function."""
        with patch("src.scheduler.budget.get_settings", return_value=mock_settings):
            await create_task_budget("task-1")
            
            result = await can_fetch_page("task-1")
            assert result is True
    
    @pytest.mark.asyncio
    async def test_can_run_llm_function(self, mock_settings):
        """Test can_run_llm function."""
        with patch("src.scheduler.budget.get_settings", return_value=mock_settings):
            await create_task_budget("task-1")
            
            result = await can_run_llm("task-1", 5.0)
            assert result is True
    
    @pytest.mark.asyncio
    async def test_stop_task_budget_function(self, mock_settings):
        """Test stop_task_budget function."""
        with patch("src.scheduler.budget.get_settings", return_value=mock_settings):
            budget = await create_task_budget("task-1")
            
            assert budget.is_active is True
            
            await stop_task_budget(
                "task-1",
                BudgetExceededReason.PAGE_LIMIT
            )
            
            assert budget.is_active is False


class TestBudgetManagerGPUDetection:
    """Tests for GPU detection in BudgetManager."""
    
    def test_gpu_available_time_limit(self):
        """Test that GPU availability affects time limit."""
        settings = {
            "task_limits": {
                "max_pages_per_task": 100,
                "max_time_minutes_gpu": 20,
                "max_time_minutes_cpu": 25,
                "llm_time_ratio_max": 0.30,
            }
        }
        
        # Mock GPU available
        with patch("src.scheduler.budget.get_settings", return_value=settings):
            with patch.object(BudgetManager, "_check_gpu_available", return_value=True):
                manager = BudgetManager()
                assert manager._max_time == 20 * 60  # 20 minutes in seconds
        
        # Mock GPU not available
        with patch("src.scheduler.budget.get_settings", return_value=settings):
            with patch.object(BudgetManager, "_check_gpu_available", return_value=False):
                manager = BudgetManager()
                assert manager._max_time == 25 * 60  # 25 minutes in seconds


class TestBudgetIntegrationScenarios:
    """Integration-style tests for budget control scenarios (§3.1, §3.2.2)."""
    
    @pytest.fixture
    def mock_settings(self):
        """Settings for integration tests.
        
        Uses reduced limits for faster test execution while
        maintaining realistic proportions.
        """
        return {
            "task_limits": {
                "max_pages_per_task": 10,
                "max_time_minutes_gpu": 1,  # 1 minute for quick tests
                "max_time_minutes_cpu": 1,
                "llm_time_ratio_max": 0.30,
            }
        }
    
    @pytest.mark.asyncio
    async def test_typical_task_lifecycle(self, mock_settings):
        """Test a typical task budget lifecycle.
        
        Simulates a research task that:
        1. Creates budget
        2. Fetches pages progressively
        3. Records LLM processing time
        4. Hits page limit and stops
        
        Verifies §3.1 requirement: 総ページ数≤max_pages
        """
        with patch("src.scheduler.budget.get_settings", return_value=mock_settings):
            manager = BudgetManager()
            
            # Create budget
            budget = await manager.create_budget("task-1")
            assert budget.is_active is True, "budget should be active initially"
            
            # Fetch some pages
            for i in range(5):
                can_continue, _ = await manager.check_and_update(
                    "task-1",
                    record_page=True,
                )
                assert can_continue is True, f"should continue at page {i+1}"
            
            assert budget.pages_fetched == 5, "should have fetched 5 pages"
            
            # Record LLM time
            await manager.check_and_update(
                "task-1",
                llm_time_seconds=2.0,
            )
            
            # Continue fetching
            for i in range(4):
                await manager.check_and_update(
                    "task-1",
                    record_page=True,
                )
            
            assert budget.pages_fetched == 9, "should have fetched 9 pages"
            
            # One more should hit limit
            can_continue, reason = await manager.check_and_update(
                "task-1",
                record_page=True,
            )
            
            # Check again - should be at limit (10 pages)
            can_continue, reason = await manager.check_and_update("task-1")
            assert can_continue is False, "should stop at page limit"
            assert reason == BudgetExceededReason.PAGE_LIMIT, "reason should be PAGE_LIMIT"
    
    @pytest.mark.asyncio
    async def test_llm_ratio_enforcement(self, mock_settings):
        """Test LLM ratio enforcement scenario.
        
        Note: LLM ratio check only applies after MIN_ELAPSED_FOR_RATIO_CHECK (30s).
        """
        with patch("src.scheduler.budget.get_settings", return_value=mock_settings):
            manager = BudgetManager()
            budget = await manager.create_budget("task-1")
            
            # Simulate 50 seconds elapsed (above 30s threshold for ratio check)
            budget.start_time = time.time() - 50
            
            # 30% of 50s = 15s LLM time allowed
            # Try to use 10s - should be OK
            assert await manager.can_run_llm("task-1", 10.0) is True
            await manager.check_and_update("task-1", llm_time_seconds=10.0)
            
            # Now at 10s LLM / ~51s elapsed
            # Projected for 3s job: (10+3) / (51+3) = 13/54 = 0.24 < 0.30
            assert await manager.can_run_llm("task-1", 3.0) is True
            await manager.check_and_update("task-1", llm_time_seconds=3.0)
            
            # Now at 13s LLM / ~51s elapsed
            # Projected for 5s job: (13+5) / (51+5) = 18/56 = 0.32 > 0.30
            assert await manager.can_run_llm("task-1", 5.0) is False

