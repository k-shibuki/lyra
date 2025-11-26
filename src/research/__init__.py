"""
Research exploration control module for Lancet.

This module implements the exploration control engine where:
- Cursor AI designs all queries/subqueries (strategic decisions)
- Lancet provides design support information and executes queries (operational work)

See requirements.md §2.1 for the responsibility matrix.
See requirements.md §3.1.1 for UCB1-based budget allocation and pivot exploration.
"""

from src.research.context import ResearchContext, EntityInfo, TemplateInfo
from src.research.state import (
    ExplorationState,
    SubqueryState,
    SubqueryStatus,
    TaskStatus,
)
from src.research.executor import SubqueryExecutor, SubqueryResult
from src.research.refutation import RefutationExecutor, RefutationResult
from src.research.ucb_allocator import UCBAllocator, SubqueryArm
from src.research.pivot import (
    PivotExpander,
    PivotSuggestion,
    PivotType,
    EntityType,
    detect_entity_type,
    get_pivot_expander,
)

__all__ = [
    # Context
    "ResearchContext",
    "EntityInfo",
    "TemplateInfo",
    # State
    "ExplorationState",
    "SubqueryState",
    "SubqueryStatus",
    "TaskStatus",
    # Executor
    "SubqueryExecutor",
    "SubqueryResult",
    # Refutation
    "RefutationExecutor",
    "RefutationResult",
    # UCB1 Budget Allocation (§3.1.1)
    "UCBAllocator",
    "SubqueryArm",
    # Pivot Exploration (§3.1.1)
    "PivotExpander",
    "PivotSuggestion",
    "PivotType",
    "EntityType",
    "detect_entity_type",
    "get_pivot_expander",
]




