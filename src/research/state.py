"""
Exploration state management for Lancet.

Manages task and search states, calculates satisfaction and novelty scores.
Reports state to Cursor AI for decision making.

See requirements.md §3.1.7.2, §3.1.7.3, §3.1.7.4.

Note: "search" replaces the former "subquery" terminology per Phase M.3-3.
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TYPE_CHECKING
from collections import deque

from src.storage.database import get_database
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.research.ucb_allocator import UCBAllocator

logger = get_logger(__name__)


class SearchStatus(Enum):
    """Status of a search execution."""
    
    PENDING = "pending"      # Created but not executed
    RUNNING = "running"      # Currently executing
    SATISFIED = "satisfied"  # Sufficient sources found (≥3 independent or 1 primary + 1 secondary)
    PARTIAL = "partial"      # Some sources found (1-2 independent)
    EXHAUSTED = "exhausted"  # Budget consumed or novelty dropped
    SKIPPED = "skipped"      # Manually skipped by Cursor AI


# Backward compatibility alias (deprecated, will be removed)
SubqueryStatus = SearchStatus


class TaskStatus(Enum):
    """Status of a research task."""
    
    CREATED = "created"              # Task created, Cursor AI designing searches
    EXPLORING = "exploring"          # Exploration in progress
    AWAITING_DECISION = "awaiting_decision"  # Waiting for Cursor AI decision
    FINALIZING = "finalizing"        # Wrapping up exploration
    COMPLETED = "completed"          # Successfully completed
    FAILED = "failed"                # Failed with error


@dataclass
class SearchState:
    """State of a single search query."""
    
    id: str
    text: str
    status: SearchStatus = SearchStatus.PENDING
    priority: str = "medium"  # high, medium, low
    
    # Source tracking
    independent_sources: int = 0
    has_primary_source: bool = False
    source_domains: list[str] = field(default_factory=list)
    
    # Metrics
    pages_fetched: int = 0
    useful_fragments: int = 0
    harvest_rate: float = 0.0
    novelty_score: float = 1.0
    satisfaction_score: float = 0.0
    
    # Refutation
    refutation_status: str = "pending"  # pending, found, not_found
    refutation_count: int = 0
    
    # Budget
    budget_pages: int | None = None
    budget_time_seconds: int | None = None
    time_started: float | None = None
    
    # Recent fragments for novelty calculation
    recent_fragment_hashes: deque = field(default_factory=lambda: deque(maxlen=20))
    
    def calculate_satisfaction_score(self) -> float:
        """
        Calculate satisfaction score per §3.1.7.3.
        
        Formula: min(1.0, (independent_sources / 3) * 0.7 + (primary ? 0.3 : 0))
        Satisfied when score >= 0.8
        """
        source_component = min(1.0, self.independent_sources / 3) * 0.7
        primary_component = 0.3 if self.has_primary_source else 0.0
        self.satisfaction_score = min(1.0, source_component + primary_component)
        return self.satisfaction_score
    
    def is_satisfied(self) -> bool:
        """Check if search is satisfied (score >= 0.8)."""
        return self.calculate_satisfaction_score() >= 0.8
    
    def update_status(self) -> SearchStatus:
        """Update status based on current metrics."""
        if self.status == SearchStatus.SKIPPED:
            return self.status
        
        if self.is_satisfied():
            self.status = SearchStatus.SATISFIED
        elif self.independent_sources > 0:
            self.status = SearchStatus.PARTIAL
        elif self.novelty_score < 0.1 and self.pages_fetched > 10:
            self.status = SearchStatus.EXHAUSTED
        
        return self.status
    
    def add_fragment(self, fragment_hash: str, is_useful: bool, is_novel: bool) -> None:
        """Record a new fragment and update metrics."""
        self.recent_fragment_hashes.append((fragment_hash, is_useful, is_novel))
        
        if is_useful:
            self.useful_fragments += 1
        
        # Recalculate novelty score
        if len(self.recent_fragment_hashes) > 0:
            novel_count = sum(1 for _, _, novel in self.recent_fragment_hashes if novel)
            self.novelty_score = novel_count / len(self.recent_fragment_hashes)
        
        # Update harvest rate
        if self.pages_fetched > 0:
            self.harvest_rate = self.useful_fragments / self.pages_fetched
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "text": self.text,
            "status": self.status.value,
            "priority": self.priority,
            "independent_sources": self.independent_sources,
            "has_primary_source": self.has_primary_source,
            "pages_fetched": self.pages_fetched,
            "useful_fragments": self.useful_fragments,
            "harvest_rate": self.harvest_rate,
            "novelty_score": self.novelty_score,
            "satisfaction_score": self.satisfaction_score,
            "refutation_status": self.refutation_status,
        }


# Backward compatibility alias (deprecated, will be removed)
SubqueryState = SearchState


class ExplorationState:
    """
    Manages exploration state for a research task.
    
    Tracks search execution, calculates metrics, and provides
    status reports to Cursor AI for decision making.
    
    Integrates UCB1-based dynamic budget allocation (§3.1.1):
    - High-yield searches receive more budget
    - Budget is reallocated based on harvest rates
    """
    
    def __init__(
        self,
        task_id: str,
        enable_ucb_allocation: bool = True,
        ucb_exploration_constant: float | None = None,
    ):
        """Initialize exploration state for a task.
        
        Args:
            task_id: The task ID to manage state for.
            enable_ucb_allocation: Enable UCB1-based dynamic budget allocation.
            ucb_exploration_constant: UCB1 exploration constant (default: sqrt(2)).
        """
        self.task_id = task_id
        self._db = None
        self._task_status = TaskStatus.CREATED
        self._searches: dict[str, SearchState] = {}
        
        # Budget tracking
        self._pages_limit = 120
        self._time_limit_seconds = 3600  # 60 minutes
        self._pages_used = 0
        self._time_started: float | None = None
        
        # UCB1 allocation (§3.1.1)
        self._enable_ucb = enable_ucb_allocation
        self._ucb_allocator: "UCBAllocator | None" = None
        self._ucb_exploration_constant = ucb_exploration_constant
        
        if self._enable_ucb:
            self._init_ucb_allocator()
        
        # Overall metrics
        self._total_fragments = 0
        self._total_claims = 0
        self._verified_claims = 0
        self._refuted_claims = 0
        
        # Novelty tracking (last 2 cycles)
        self._novelty_history: list[float] = []
    
    def _init_ucb_allocator(self) -> None:
        """Initialize the UCB allocator."""
        from src.research.ucb_allocator import UCBAllocator
        
        self._ucb_allocator = UCBAllocator(
            total_budget=self._pages_limit,
            exploration_constant=self._ucb_exploration_constant,
            min_budget_per_search=5,
            max_budget_ratio=0.4,
            reallocation_interval=10,
        )
        logger.info(
            "UCB allocator enabled",
            task_id=self.task_id,
            total_budget=self._pages_limit,
        )
    
    async def _ensure_db(self) -> None:
        """Ensure database connection is available."""
        if self._db is None:
            self._db = await get_database()
    
    async def load_state(self) -> None:
        """Load state from database."""
        await self._ensure_db()
        
        task = await self._db.fetch_one(
            "SELECT * FROM tasks WHERE id = ?",
            (self.task_id,),
        )
        
        if task:
            status_str = task.get("status", "created")
            try:
                self._task_status = TaskStatus(status_str)
            except ValueError:
                self._task_status = TaskStatus.CREATED
        
        # Load existing searches
        queries = await self._db.fetch_all(
            """
            SELECT id, query_text, query_type, depth, harvest_rate
            FROM queries
            WHERE task_id = ?
            """,
            (self.task_id,),
        )
        
        for q in queries:
            search = SearchState(
                id=q["id"],
                text=q.get("query_text", ""),
                harvest_rate=q.get("harvest_rate", 0.0),
            )
            self._searches[search.id] = search
    
    async def save_state(self) -> None:
        """Save current state to database."""
        await self._ensure_db()
        
        await self._db.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (self._task_status.value, self.task_id),
        )
    
    def register_search(
        self,
        search_id: str,
        text: str,
        priority: str = "medium",
        budget_pages: int | None = None,
        budget_time_seconds: int | None = None,
    ) -> SearchState:
        """
        Register a new search for execution.
        
        Args:
            search_id: Unique identifier for the search.
            text: The search query text (designed by Cursor AI).
            priority: Execution priority (high/medium/low).
            budget_pages: Optional page budget for this search.
            budget_time_seconds: Optional time budget for this search.
            
        Returns:
            The created SearchState.
        """
        search = SearchState(
            id=search_id,
            text=text,
            priority=priority,
            budget_pages=budget_pages,
            budget_time_seconds=budget_time_seconds,
        )
        self._searches[search_id] = search
        
        # Register with UCB allocator (§3.1.1)
        if self._ucb_allocator:
            self._ucb_allocator.register_search(
                search_id=search_id,
                priority=priority,
                initial_budget=budget_pages,
            )
        
        logger.info(
            "Registered search",
            task_id=self.task_id,
            search_id=search_id,
            priority=priority,
        )
        
        return search
    
    # Backward compatibility alias (deprecated, will be removed)
    def register_subquery(
        self,
        subquery_id: str,
        text: str,
        priority: str = "medium",
        budget_pages: int | None = None,
        budget_time_seconds: int | None = None,
    ) -> SearchState:
        """Deprecated: Use register_search instead."""
        return self.register_search(
            search_id=subquery_id,
            text=text,
            priority=priority,
            budget_pages=budget_pages,
            budget_time_seconds=budget_time_seconds,
        )
    
    def start_search(self, search_id: str) -> SearchState | None:
        """Mark a search as running."""
        search = self._searches.get(search_id)
        if search:
            search.status = SearchStatus.RUNNING
            search.time_started = time.time()
            self._task_status = TaskStatus.EXPLORING
            
            if self._time_started is None:
                self._time_started = time.time()
        
        return search
    
    # Backward compatibility alias (deprecated, will be removed)
    def start_subquery(self, subquery_id: str) -> SearchState | None:
        """Deprecated: Use start_search instead."""
        return self.start_search(subquery_id)
    
    def get_search(self, search_id: str) -> SearchState | None:
        """Get a search by ID."""
        return self._searches.get(search_id)
    
    # Backward compatibility alias (deprecated, will be removed)
    def get_subquery(self, subquery_id: str) -> SearchState | None:
        """Deprecated: Use get_search instead."""
        return self.get_search(subquery_id)
    
    def record_page_fetch(
        self,
        search_id: str,
        domain: str,
        is_primary_source: bool,
        is_independent: bool,
    ) -> None:
        """
        Record a page fetch for a search.
        
        Args:
            search_id: The search ID.
            domain: Domain of the fetched page.
            is_primary_source: Whether this is a primary source (gov/academic/official).
            is_independent: Whether this is an independent source (new domain/cluster).
        """
        search = self._searches.get(search_id)
        if not search:
            return
        
        search.pages_fetched += 1
        self._pages_used += 1
        
        if is_independent:
            search.independent_sources += 1
            if domain not in search.source_domains:
                search.source_domains.append(domain)
        
        if is_primary_source:
            search.has_primary_source = True
        
        search.update_status()
    
    def record_fragment(
        self,
        search_id: str,
        fragment_hash: str,
        is_useful: bool,
        is_novel: bool,
    ) -> None:
        """Record a fragment extraction."""
        search = self._searches.get(search_id)
        if search:
            search.add_fragment(fragment_hash, is_useful, is_novel)
            self._total_fragments += 1
            
            # Record observation in UCB allocator (§3.1.1)
            if self._ucb_allocator:
                self._ucb_allocator.record_observation(search_id, is_useful)
    
    def record_claim(self, search_id: str, is_verified: bool = False, is_refuted: bool = False) -> None:
        """Record a claim extraction.
        
        Args:
            search_id: The search ID.
            is_verified: Whether the claim is verified (supported by evidence).
            is_refuted: Whether the claim is refuted by counter-evidence.
        """
        self._total_claims += 1
        if is_verified:
            self._verified_claims += 1
        if is_refuted:
            self._refuted_claims += 1
    
    def record_claim_verified(self, claim_id: str) -> None:
        """Record that a claim has been verified by NLI.
        
        Args:
            claim_id: The claim ID that was verified.
        """
        self._verified_claims += 1
    
    def record_claim_refuted(self, claim_id: str) -> None:
        """Record that a claim has been refuted by counter-evidence.
        
        Args:
            claim_id: The claim ID that was refuted.
        """
        self._refuted_claims += 1
    
    def check_budget(self) -> tuple[bool, str | None]:
        """
        Check if budget is exhausted.
        
        Returns:
            Tuple of (is_within_budget, warning_message).
        """
        # Check page budget
        if self._pages_used >= self._pages_limit:
            return False, "ページ数上限に達しました"
        
        # Check time budget
        if self._time_started:
            elapsed = time.time() - self._time_started
            if elapsed >= self._time_limit_seconds:
                return False, "時間上限に達しました"
        
        # Warnings
        pages_remaining_ratio = 1 - (self._pages_used / self._pages_limit)
        if pages_remaining_ratio < 0.2:
            return True, f"予算残り{int(pages_remaining_ratio * 100)}%"
        
        return True, None
    
    def get_dynamic_budget(self, search_id: str) -> int:
        """
        Get dynamic budget for a search using UCB1 allocation (§3.1.1).
        
        If UCB allocation is enabled, returns budget based on harvest rates.
        Otherwise, returns the static budget from SearchState.
        
        Args:
            search_id: The search ID.
            
        Returns:
            Available budget (pages) for the search.
        """
        search = self._searches.get(search_id)
        if not search:
            return 0
        
        if self._ucb_allocator:
            return self._ucb_allocator.reallocate_and_get_budget(search_id)
        
        # Fallback to static budget
        if search.budget_pages is not None:
            return max(0, search.budget_pages - search.pages_fetched)
        
        # Default budget per search
        return 15
    
    def get_ucb_recommended_search(self) -> str | None:
        """
        Get the search recommended by UCB1 for next execution.
        
        Returns:
            Search ID with highest UCB score, or None.
        """
        if not self._ucb_allocator:
            return None
        return self._ucb_allocator.get_recommended_search()
    
    # Backward compatibility alias (deprecated, will be removed)
    def get_ucb_recommended_subquery(self) -> str | None:
        """Deprecated: Use get_ucb_recommended_search instead."""
        return self.get_ucb_recommended_search()
    
    def get_ucb_scores(self) -> dict[str, float]:
        """
        Get UCB1 scores for all searches.
        
        Returns:
            Dictionary mapping search_id to UCB1 score.
        """
        if not self._ucb_allocator:
            return {}
        return self._ucb_allocator.get_all_ucb_scores()
    
    def trigger_budget_reallocation(self) -> dict[str, int]:
        """
        Manually trigger budget reallocation.
        
        Useful after significant changes in harvest rates.
        
        Returns:
            New budget allocations per search.
        """
        if not self._ucb_allocator:
            return {}
        return self._ucb_allocator.reallocate_budget()
    
    def check_novelty_stop_condition(self, search_id: str) -> bool:
        """
        Check if novelty stop condition is met (§3.1.7.4).
        
        Stop if novelty < 10% for 2 consecutive cycles.
        """
        search = self._searches.get(search_id)
        if not search:
            return False
        
        # Need at least 2 cycles (20 fragments)
        if search.pages_fetched < 20:
            return False
        
        # Check last 2 cycles
        if search.novelty_score < 0.1:
            self._novelty_history.append(search.novelty_score)
            if len(self._novelty_history) >= 2:
                if all(n < 0.1 for n in self._novelty_history[-2:]):
                    return True
        else:
            self._novelty_history.clear()
        
        return False
    
    async def get_status(self) -> dict[str, Any]:
        """
        Get current exploration status for Cursor AI.
        
        Returns metrics and state only - no recommendations.
        Cursor AI makes all decisions based on this data.
        
        Per §16.7.1: Now includes authentication_queue information.
        Per §16.7.3: Includes authentication threshold alerts in warnings.
        
        Returns:
            - Task status
            - All subquery states
            - Metrics (counts, pages, fragments, claims)
            - Budget information
            - UCB scores (raw data, not recommendations)
            - Authentication queue status (§16.7.1)
            - Warnings (including auth queue alerts per §16.7.3)
        """
        elapsed_seconds = 0
        if self._time_started:
            elapsed_seconds = int(time.time() - self._time_started)
        
        # Count search statuses
        satisfied = sum(1 for s in self._searches.values() if s.status == SearchStatus.SATISFIED)
        partial = sum(1 for s in self._searches.values() if s.status == SearchStatus.PARTIAL)
        pending = sum(1 for s in self._searches.values() if s.status == SearchStatus.PENDING)
        exhausted_count = sum(1 for s in self._searches.values() if s.status == SearchStatus.EXHAUSTED)
        
        # Generate warnings (factual alerts, not recommendations)
        warnings = []
        within_budget, budget_warning = self.check_budget()
        if budget_warning:
            warnings.append(budget_warning)
        
        if exhausted_count > 0:
            warnings.append(f"{exhausted_count}件の検索が収穫逓減で停止")
        
        # Get authentication queue summary (§16.7.1)
        authentication_queue = await self._get_authentication_queue_summary()
        
        # Add authentication queue alerts (§16.7.3)
        auth_warnings = self._generate_auth_queue_alerts(authentication_queue)
        warnings.extend(auth_warnings)
        
        # UCB scores (raw data only, no "recommended_next")
        ucb_scores = None
        if self._ucb_allocator:
            ucb_status = self._ucb_allocator.get_status()
            ucb_scores = {
                "enabled": True,
                "arm_scores": {
                    sid: arm.get("ucb_score", 0)
                    for sid, arm in ucb_status.get("arms", {}).items()
                },
                "arm_budgets": {
                    sid: arm.get("remaining_budget", 0)
                    for sid, arm in ucb_status.get("arms", {}).items()
                },
            }
        
        return {
            "ok": True,
            "task_id": self.task_id,
            "task_status": self._task_status.value,
            "searches": [s.to_dict() for s in self._searches.values()],
            "metrics": {
                "satisfied_count": satisfied,
                "partial_count": partial,
                "pending_count": pending,
                "exhausted_count": exhausted_count,
                "total_pages": self._pages_used,
                "total_fragments": self._total_fragments,
                "total_claims": self._total_claims,
                "elapsed_seconds": elapsed_seconds,
            },
            "budget": {
                "pages_used": self._pages_used,
                "pages_limit": self._pages_limit,
                "time_used_seconds": elapsed_seconds,
                "time_limit_seconds": self._time_limit_seconds,
            },
            "ucb_scores": ucb_scores,
            "authentication_queue": authentication_queue,
            "warnings": warnings,
        }
    
    async def _get_authentication_queue_summary(self) -> dict[str, Any] | None:
        """Get authentication queue summary for this task.
        
        Per §16.7.1: Provides authentication queue information.
        
        Returns:
            Authentication queue summary or None if no pending items.
        """
        try:
            from src.utils.notification import get_intervention_queue
            
            queue = get_intervention_queue()
            summary = await queue.get_authentication_queue_summary(self.task_id)
            
            # Only include if there are pending items
            if summary.get("pending_count", 0) == 0:
                return None
            
            return summary
        except Exception as e:
            logger.debug(
                "Failed to get authentication queue summary",
                task_id=self.task_id,
                error=str(e),
            )
            return None
    
    def _generate_auth_queue_alerts(
        self,
        auth_queue: dict[str, Any] | None,
    ) -> list[str]:
        """Generate alerts for authentication queue status.
        
        Per §16.7.3: Warning levels based on queue depth.
        - warning: pending auth ≥3 items
        - critical: pending auth ≥5 items OR high priority ≥2 items
        
        Args:
            auth_queue: Authentication queue summary.
            
        Returns:
            List of warning messages.
        """
        if auth_queue is None:
            return []
        
        alerts = []
        pending_count = auth_queue.get("pending_count", 0)
        high_priority_count = auth_queue.get("high_priority_count", 0)
        domains = auth_queue.get("domains", [])
        
        # Critical level: ≥5 pending OR ≥2 high priority
        if pending_count >= 5 or high_priority_count >= 2:
            if high_priority_count >= 2:
                alerts.append(
                    f"[critical] 認証待ち{pending_count}件（高優先度{high_priority_count}件）: "
                    f"一次資料アクセスがブロック中"
                )
            else:
                alerts.append(
                    f"[critical] 認証待ち{pending_count}件: 探索継続に影響"
                )
        # Warning level: ≥3 pending
        elif pending_count >= 3:
            domain_sample = ", ".join(domains[:3])
            if len(domains) > 3:
                domain_sample += f" 他{len(domains) - 3}件"
            alerts.append(
                f"[warning] 認証待ち{pending_count}件 ({domain_sample})"
            )
        
        return alerts
    
    def set_task_status(self, status: TaskStatus) -> None:
        """Set the task status."""
        self._task_status = status
    
    async def _get_evidence_graph_stats(self) -> dict[str, Any]:
        """Get statistics from the evidence graph.
        
        Returns:
            Dictionary with total_nodes and total_edges.
        """
        try:
            from src.filter.evidence_graph import EvidenceGraph
            
            graph = EvidenceGraph(task_id=self.task_id)
            await graph.load_from_db(task_id=self.task_id)
            
            return graph.get_stats()
        except Exception as e:
            logger.debug(
                "Failed to get evidence graph stats",
                task_id=self.task_id,
                error=str(e),
            )
            return {"total_nodes": 0, "total_edges": 0}
    
    async def finalize(self) -> dict[str, Any]:
        """
        Finalize exploration and return summary.
        
        Returns summary including:
        - Final status
        - Subquery completion summary
        - Unsatisfied subqueries
        - Followup suggestions
        """
        self._task_status = TaskStatus.COMPLETED
        
        satisfied_searches = [s for s in self._searches.values() if s.status == SearchStatus.SATISFIED]
        partial_searches = [s for s in self._searches.values() if s.status == SearchStatus.PARTIAL]
        unsatisfied_searches = [
            s for s in self._searches.values()
            if s.status in (SearchStatus.PENDING, SearchStatus.EXHAUSTED)
        ]
        
        followup_suggestions = []
        for s in unsatisfied_searches:
            if s.status == SearchStatus.EXHAUSTED:
                followup_suggestions.append(f"{s.id}: 収穫逓減で停止。別のクエリ戦略が必要")
            elif s.status == SearchStatus.PENDING:
                followup_suggestions.append(f"{s.id}: 未実行")
        
        for s in partial_searches:
            if not s.has_primary_source:
                followup_suggestions.append(f"{s.id}: 一次資料が見つかっていません")
        
        # Determine final status
        final_status = "completed" if not unsatisfied_searches else "partial"
        
        # Calculate refuted claims from searches with found refutations
        refuted_from_searches = sum(
            1 for s in self._searches.values()
            if s.refutation_status == "found"
        )
        total_refuted = max(self._refuted_claims, refuted_from_searches)
        
        # Calculate unverified claims
        unverified_claims = max(0, self._total_claims - self._verified_claims - total_refuted)
        
        # Get evidence graph stats if available
        evidence_graph_stats = await self._get_evidence_graph_stats()
        
        return {
            "ok": True,
            "task_id": self.task_id,
            "final_status": final_status,
            "summary": {
                "satisfied_searches": len(satisfied_searches),
                "partial_searches": len(partial_searches),
                "unsatisfied_searches": [s.id for s in unsatisfied_searches],
                "total_claims": self._total_claims,
                "verified_claims": self._verified_claims,
                "refuted_claims": total_refuted,
                "unverified_claims": unverified_claims,
            },
            "followup_suggestions": followup_suggestions,
            "evidence_graph_summary": {
                "nodes": evidence_graph_stats.get("total_nodes", self._total_fragments + self._total_claims),
                "edges": evidence_graph_stats.get("total_edges", 0),
                "primary_source_ratio": sum(1 for s in self._searches.values() if s.has_primary_source) / max(1, len(self._searches)),
            },
        }

