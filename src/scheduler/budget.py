"""
Budget control for Lancet task execution.
Implements §3.1 and §3.2.2 requirements:
- Task page limit: ≤120 pages/task
- Time limit: ≤20 minutes/task (GPU), ≤25 minutes (CPU)
- LLM time ratio: ≤30% of total processing time
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class BudgetExceededReason(str, Enum):
    """Reasons for budget rejection."""
    PAGE_LIMIT = "page_limit_exceeded"
    TIME_LIMIT = "time_limit_exceeded"
    LLM_RATIO = "llm_ratio_exceeded"


@dataclass
class TaskBudget:
    """
    Budget tracker for a single task.
    Tracks pages fetched, time elapsed, and LLM processing time.
    """
    task_id: str
    created_at: float = field(default_factory=time.time)
    
    # Page tracking
    pages_fetched: int = 0
    max_pages: int = 120
    
    # Time tracking (seconds)
    start_time: float = field(default_factory=time.time)
    max_time_seconds: float = 1200.0  # 20 minutes default
    
    # LLM time tracking
    llm_time_seconds: float = 0.0
    max_llm_ratio: float = 0.30
    
    # State
    is_active: bool = True
    exceeded_reason: BudgetExceededReason | None = None
    
    @property
    def elapsed_seconds(self) -> float:
        """Total elapsed time since task start."""
        return time.time() - self.start_time
    
    @property
    def remaining_pages(self) -> int:
        """Number of pages remaining in budget."""
        return max(0, self.max_pages - self.pages_fetched)
    
    @property
    def remaining_time_seconds(self) -> float:
        """Time remaining in budget (seconds)."""
        return max(0.0, self.max_time_seconds - self.elapsed_seconds)
    
    @property
    def current_llm_ratio(self) -> float:
        """Current LLM time ratio."""
        elapsed = self.elapsed_seconds
        if elapsed <= 0:
            return 0.0
        return self.llm_time_seconds / elapsed
    
    @property
    def available_llm_time(self) -> float:
        """Remaining LLM time within ratio limit (seconds)."""
        # llm_time / elapsed <= max_ratio
        # llm_time <= max_ratio * elapsed
        # available = max_ratio * elapsed - llm_time
        max_llm_time = self.max_llm_ratio * self.elapsed_seconds
        return max(0.0, max_llm_time - self.llm_time_seconds)
    
    def can_fetch_page(self) -> bool:
        """Check if a page can be fetched within budget."""
        if not self.is_active:
            return False
        return self.pages_fetched < self.max_pages
    
    def can_continue(self) -> tuple[bool, BudgetExceededReason | None]:
        """
        Check if task can continue execution.
        
        Returns:
            Tuple of (can_continue, reason if not)
        """
        if not self.is_active:
            return False, self.exceeded_reason
        
        # Check page limit
        if self.pages_fetched >= self.max_pages:
            return False, BudgetExceededReason.PAGE_LIMIT
        
        # Check time limit
        if self.elapsed_seconds >= self.max_time_seconds:
            return False, BudgetExceededReason.TIME_LIMIT
        
        return True, None
    
    def can_run_llm(self, estimated_seconds: float = 10.0) -> bool:
        """
        Check if LLM job can run within ratio limit.
        
        Args:
            estimated_seconds: Estimated LLM processing time.
            
        Returns:
            True if LLM can run within budget.
        """
        if not self.is_active:
            return False
        
        # Project future ratio
        projected_llm_time = self.llm_time_seconds + estimated_seconds
        projected_elapsed = self.elapsed_seconds + estimated_seconds
        
        # For new tasks with very short elapsed time, allow LLM execution
        # The ratio check only makes sense after some baseline time has elapsed
        MIN_ELAPSED_FOR_RATIO_CHECK = 30.0  # 30 seconds minimum
        if projected_elapsed < MIN_ELAPSED_FOR_RATIO_CHECK:
            return True
        
        projected_ratio = projected_llm_time / projected_elapsed
        return projected_ratio <= self.max_llm_ratio
    
    def record_page_fetch(self) -> None:
        """Record a page fetch."""
        self.pages_fetched += 1
        logger.debug(
            "Page fetched",
            task_id=self.task_id,
            pages_fetched=self.pages_fetched,
            max_pages=self.max_pages,
        )
    
    def record_llm_time(self, seconds: float) -> None:
        """
        Record LLM processing time.
        
        Args:
            seconds: LLM processing time in seconds.
        """
        self.llm_time_seconds += seconds
        logger.debug(
            "LLM time recorded",
            task_id=self.task_id,
            llm_time=self.llm_time_seconds,
            current_ratio=self.current_llm_ratio,
            max_ratio=self.max_llm_ratio,
        )
    
    def stop(self, reason: BudgetExceededReason | None = None) -> None:
        """
        Stop the task budget.
        
        Args:
            reason: Reason for stopping (if budget exceeded).
        """
        self.is_active = False
        self.exceeded_reason = reason
        logger.info(
            "Task budget stopped",
            task_id=self.task_id,
            reason=reason.value if reason else "completed",
            pages_fetched=self.pages_fetched,
            elapsed_seconds=self.elapsed_seconds,
            llm_ratio=self.current_llm_ratio,
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "task_id": self.task_id,
            "pages_fetched": self.pages_fetched,
            "max_pages": self.max_pages,
            "elapsed_seconds": self.elapsed_seconds,
            "max_time_seconds": self.max_time_seconds,
            "llm_time_seconds": self.llm_time_seconds,
            "current_llm_ratio": self.current_llm_ratio,
            "max_llm_ratio": self.max_llm_ratio,
            "remaining_pages": self.remaining_pages,
            "remaining_time_seconds": self.remaining_time_seconds,
            "available_llm_time": self.available_llm_time,
            "is_active": self.is_active,
            "exceeded_reason": self.exceeded_reason.value if self.exceeded_reason else None,
        }


class BudgetManager:
    """
    Manages task budgets across the system.
    Provides budget allocation, tracking, and enforcement.
    """
    
    def __init__(self):
        self._settings = get_settings()
        self._budgets: dict[str, TaskBudget] = {}
        self._lock = asyncio.Lock()
        
        # Load limits from settings
        task_limits = self._settings.get("task_limits", {})
        self._max_pages = task_limits.get("max_pages_per_task", 120)
        self._max_time_gpu = task_limits.get("max_time_minutes_gpu", 20) * 60
        self._max_time_cpu = task_limits.get("max_time_minutes_cpu", 25) * 60
        self._max_llm_ratio = task_limits.get("llm_time_ratio_max", 0.30)
        
        # Detect GPU availability (simplified check)
        self._has_gpu = self._check_gpu_available()
        self._max_time = self._max_time_gpu if self._has_gpu else self._max_time_cpu
        
        logger.info(
            "Budget manager initialized",
            max_pages=self._max_pages,
            max_time_seconds=self._max_time,
            max_llm_ratio=self._max_llm_ratio,
            has_gpu=self._has_gpu,
        )
    
    def _check_gpu_available(self) -> bool:
        """Check if GPU is available."""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False
    
    async def create_budget(self, task_id: str) -> TaskBudget:
        """
        Create a new budget for a task.
        
        Args:
            task_id: Task identifier.
            
        Returns:
            New TaskBudget instance.
        """
        async with self._lock:
            if task_id in self._budgets:
                logger.warning("Budget already exists for task", task_id=task_id)
                return self._budgets[task_id]
            
            budget = TaskBudget(
                task_id=task_id,
                max_pages=self._max_pages,
                max_time_seconds=self._max_time,
                max_llm_ratio=self._max_llm_ratio,
            )
            self._budgets[task_id] = budget
            
            logger.info(
                "Budget created",
                task_id=task_id,
                max_pages=budget.max_pages,
                max_time_seconds=budget.max_time_seconds,
            )
            
            return budget
    
    async def get_budget(self, task_id: str) -> TaskBudget | None:
        """
        Get budget for a task.
        
        Args:
            task_id: Task identifier.
            
        Returns:
            TaskBudget or None if not found.
        """
        return self._budgets.get(task_id)
    
    async def check_and_update(
        self,
        task_id: str,
        *,
        record_page: bool = False,
        llm_time_seconds: float = 0.0,
    ) -> tuple[bool, BudgetExceededReason | None]:
        """
        Check budget and optionally update counters.
        
        Args:
            task_id: Task identifier.
            record_page: Whether to record a page fetch.
            llm_time_seconds: LLM time to record.
            
        Returns:
            Tuple of (can_continue, exceeded_reason)
        """
        async with self._lock:
            budget = self._budgets.get(task_id)
            if budget is None:
                # No budget means no limits (for backward compatibility)
                return True, None
            
            # Record updates
            if record_page:
                budget.record_page_fetch()
            
            if llm_time_seconds > 0:
                budget.record_llm_time(llm_time_seconds)
            
            # Check if can continue
            can_continue, reason = budget.can_continue()
            
            if not can_continue and budget.is_active:
                budget.stop(reason)
            
            return can_continue, reason
    
    async def can_fetch_page(self, task_id: str) -> bool:
        """
        Check if a page can be fetched.
        
        Args:
            task_id: Task identifier.
            
        Returns:
            True if page fetch is within budget.
        """
        budget = self._budgets.get(task_id)
        if budget is None:
            return True
        return budget.can_fetch_page()
    
    async def can_run_llm(
        self,
        task_id: str,
        estimated_seconds: float = 10.0,
    ) -> bool:
        """
        Check if LLM can run within ratio limit.
        
        Args:
            task_id: Task identifier.
            estimated_seconds: Estimated LLM processing time.
            
        Returns:
            True if LLM can run within budget.
        """
        budget = self._budgets.get(task_id)
        if budget is None:
            return True
        return budget.can_run_llm(estimated_seconds)
    
    async def get_remaining_budget(
        self,
        task_id: str,
    ) -> dict[str, Any] | None:
        """
        Get remaining budget for a task.
        
        Args:
            task_id: Task identifier.
            
        Returns:
            Dictionary with remaining budget info.
        """
        budget = self._budgets.get(task_id)
        if budget is None:
            return None
        
        return {
            "remaining_pages": budget.remaining_pages,
            "remaining_time_seconds": budget.remaining_time_seconds,
            "available_llm_time": budget.available_llm_time,
            "is_active": budget.is_active,
        }
    
    async def stop_budget(
        self,
        task_id: str,
        reason: BudgetExceededReason | None = None,
    ) -> None:
        """
        Stop a task's budget.
        
        Args:
            task_id: Task identifier.
            reason: Reason for stopping.
        """
        async with self._lock:
            budget = self._budgets.get(task_id)
            if budget:
                budget.stop(reason)
    
    async def remove_budget(self, task_id: str) -> None:
        """
        Remove a task's budget.
        
        Args:
            task_id: Task identifier.
        """
        async with self._lock:
            if task_id in self._budgets:
                del self._budgets[task_id]
                logger.debug("Budget removed", task_id=task_id)
    
    async def get_all_active_budgets(self) -> list[dict[str, Any]]:
        """
        Get all active task budgets.
        
        Returns:
            List of budget dictionaries.
        """
        return [
            budget.to_dict()
            for budget in self._budgets.values()
            if budget.is_active
        ]
    
    async def enforce_limits(self, task_id: str) -> dict[str, Any]:
        """
        Enforce budget limits and return status.
        Called periodically to check and stop tasks that exceed limits.
        
        Args:
            task_id: Task identifier.
            
        Returns:
            Status dict with enforcement results.
        """
        budget = self._budgets.get(task_id)
        if budget is None:
            return {"enforced": False, "reason": "no_budget"}
        
        can_continue, reason = budget.can_continue()
        
        if not can_continue and budget.is_active:
            budget.stop(reason)
            
            # Log enforcement action
            logger.warning(
                "Budget limit enforced",
                task_id=task_id,
                reason=reason.value if reason else "unknown",
                pages_fetched=budget.pages_fetched,
                elapsed_seconds=budget.elapsed_seconds,
                llm_ratio=budget.current_llm_ratio,
            )
            
            return {
                "enforced": True,
                "reason": reason.value if reason else "unknown",
                "budget": budget.to_dict(),
            }
        
        return {
            "enforced": False,
            "budget": budget.to_dict(),
        }


# Global budget manager instance
_budget_manager: BudgetManager | None = None


async def get_budget_manager() -> BudgetManager:
    """Get or create the global budget manager."""
    global _budget_manager
    if _budget_manager is None:
        _budget_manager = BudgetManager()
    return _budget_manager


# Convenience functions for use in other modules

async def create_task_budget(task_id: str) -> TaskBudget:
    """Create a budget for a new task."""
    manager = await get_budget_manager()
    return await manager.create_budget(task_id)


async def check_budget(
    task_id: str,
    *,
    record_page: bool = False,
    llm_time_seconds: float = 0.0,
) -> tuple[bool, BudgetExceededReason | None]:
    """Check and update task budget."""
    manager = await get_budget_manager()
    return await manager.check_and_update(
        task_id,
        record_page=record_page,
        llm_time_seconds=llm_time_seconds,
    )


async def can_fetch_page(task_id: str) -> bool:
    """Check if page fetch is within budget."""
    manager = await get_budget_manager()
    return await manager.can_fetch_page(task_id)


async def can_run_llm(task_id: str, estimated_seconds: float = 10.0) -> bool:
    """Check if LLM can run within ratio limit."""
    manager = await get_budget_manager()
    return await manager.can_run_llm(task_id, estimated_seconds)


async def stop_task_budget(
    task_id: str,
    reason: BudgetExceededReason | None = None,
) -> None:
    """Stop a task's budget."""
    manager = await get_budget_manager()
    await manager.stop_budget(task_id, reason)

