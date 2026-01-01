"""
Research exploration control module for Lyra.

This module implements the exploration control engine where:
- Cursor AI designs all search queries (strategic decisions)
- Lyra provides design support information and executes queries (operational work)

See ADR-0002 for the responsibility matrix.
See ADR-0010 for UCB1-based budget allocation and pivot exploration.

Note: This module uses "search" terminology.
"""

from src.research.context import EntityInfo, ResearchContext, TemplateInfo
from src.research.executor import (
    SearchExecutionResult,
    SearchExecutor,
)
from src.research.pipeline import (
    SearchOptions,
    SearchPipeline,
    SearchResult,
    search_action,
    stop_task_action,
)
from src.research.pivot import (
    EntityType,
    PivotExpander,
    PivotSuggestion,
    PivotType,
    detect_entity_type,
    get_pivot_expander,
)
from src.research.refutation import RefutationExecutor, RefutationResult
from src.research.state import (
    ExplorationState,
    SearchState,
    SearchStatus,
    TaskStatus,
)
from src.research.ucb_allocator import (
    SearchArm,
    UCBAllocator,
)

__all__ = [
    # Context
    "ResearchContext",
    "EntityInfo",
    "TemplateInfo",
    # State
    "ExplorationState",
    "SearchState",
    "SearchStatus",
    "TaskStatus",
    # Executor
    "SearchExecutor",
    "SearchExecutionResult",
    # Refutation
    "RefutationExecutor",
    "RefutationResult",
    # UCB1 Budget Allocation (ADR-0010)
    "UCBAllocator",
    "SearchArm",
    # Pivot Exploration (ADR-0010)
    "PivotExpander",
    "PivotSuggestion",
    "PivotType",
    "EntityType",
    "detect_entity_type",
    "get_pivot_expander",
    # Pipeline (ADR-0003)
    "SearchPipeline",
    "SearchResult",
    "SearchOptions",
    "search_action",
    "stop_task_action",
]
