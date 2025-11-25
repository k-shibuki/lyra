"""
Research exploration control module for Lancet.

This module implements the exploration control engine where:
- Cursor AI designs all queries/subqueries (strategic decisions)
- Lancet provides design support information and executes queries (operational work)

See requirements.md §2.1 for the responsibility matrix.
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
]

