"""
Research exploration control module for Lancet.

This module implements the exploration control engine where:
- Cursor AI designs all search queries (strategic decisions)
- Lancet provides design support information and executes queries (operational work)

See requirements.md §2.1 for the responsibility matrix.
See requirements.md §3.1.1 for UCB1-based budget allocation and pivot exploration.

Note: "search" replaces the former "subquery" terminology per Phase M.3-3.
"""

from src.research.context import ResearchContext, EntityInfo, TemplateInfo
from src.research.state import (
    ExplorationState,
    SearchState,
    SearchStatus,
    TaskStatus,
    # Backward compatibility aliases (deprecated, will be removed)
    SubqueryState,
    SubqueryStatus,
)
from src.research.executor import (
    SearchExecutor,
    SearchResult as ExecutorSearchResult,
    # Backward compatibility aliases (deprecated, will be removed)
    SubqueryExecutor,
    SubqueryResult,
)
from src.research.refutation import RefutationExecutor, RefutationResult
from src.research.ucb_allocator import (
    UCBAllocator,
    SearchArm,
    # Backward compatibility alias (deprecated, will be removed)
    SubqueryArm,
)
from src.research.pivot import (
    PivotExpander,
    PivotSuggestion,
    PivotType,
    EntityType,
    detect_entity_type,
    get_pivot_expander,
)
from src.research.pipeline import (
    SearchPipeline,
    SearchResult,
    SearchOptions,
    search_action,
    stop_task_action,
)

__all__ = [
    # Context
    "ResearchContext",
    "EntityInfo",
    "TemplateInfo",
    # State (new names)
    "ExplorationState",
    "SearchState",
    "SearchStatus",
    "TaskStatus",
    # State (deprecated aliases)
    "SubqueryState",
    "SubqueryStatus",
    # Executor (new names)
    "SearchExecutor",
    "ExecutorSearchResult",
    # Executor (deprecated aliases)
    "SubqueryExecutor",
    "SubqueryResult",
    # Refutation
    "RefutationExecutor",
    "RefutationResult",
    # UCB1 Budget Allocation (§3.1.1, new names)
    "UCBAllocator",
    "SearchArm",
    # UCB1 (deprecated alias)
    "SubqueryArm",
    # Pivot Exploration (§3.1.1)
    "PivotExpander",
    "PivotSuggestion",
    "PivotType",
    "EntityType",
    "detect_entity_type",
    "get_pivot_expander",
    # Pipeline (Phase M)
    "SearchPipeline",
    "SearchResult",
    "SearchOptions",
    "search_action",
    "stop_task_action",
]




