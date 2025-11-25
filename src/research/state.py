"""
Exploration state management for Lancet.

Manages task and subquery states, calculates satisfaction and novelty scores.
Reports state to Cursor AI for decision making.

See requirements.md §3.1.7.2, §3.1.7.3, §3.1.7.4.
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from collections import deque

from src.storage.database import get_database
from src.utils.logging import get_logger

logger = get_logger(__name__)


class SubqueryStatus(Enum):
    """Status of a subquery execution."""
    
    PENDING = "pending"      # Created but not executed
    RUNNING = "running"      # Currently executing
    SATISFIED = "satisfied"  # Sufficient sources found (≥3 independent or 1 primary + 1 secondary)
    PARTIAL = "partial"      # Some sources found (1-2 independent)
    EXHAUSTED = "exhausted"  # Budget consumed or novelty dropped
    SKIPPED = "skipped"      # Manually skipped by Cursor AI


class TaskStatus(Enum):
    """Status of a research task."""
    
    CREATED = "created"              # Task created, Cursor AI designing subqueries
    EXPLORING = "exploring"          # Exploration in progress
    AWAITING_DECISION = "awaiting_decision"  # Waiting for Cursor AI decision
    FINALIZING = "finalizing"        # Wrapping up exploration
    COMPLETED = "completed"          # Successfully completed
    FAILED = "failed"                # Failed with error


@dataclass
class SubqueryState:
    """State of a single subquery."""
    
    id: str
    text: str
    status: SubqueryStatus = SubqueryStatus.PENDING
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
        """Check if subquery is satisfied (score >= 0.8)."""
        return self.calculate_satisfaction_score() >= 0.8
    
    def update_status(self) -> SubqueryStatus:
        """Update status based on current metrics."""
        if self.status == SubqueryStatus.SKIPPED:
            return self.status
        
        if self.is_satisfied():
            self.status = SubqueryStatus.SATISFIED
        elif self.independent_sources > 0:
            self.status = SubqueryStatus.PARTIAL
        elif self.novelty_score < 0.1 and self.pages_fetched > 10:
            self.status = SubqueryStatus.EXHAUSTED
        
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


class ExplorationState:
    """
    Manages exploration state for a research task.
    
    Tracks subquery execution, calculates metrics, and provides
    status reports to Cursor AI for decision making.
    """
    
    def __init__(self, task_id: str):
        """Initialize exploration state for a task.
        
        Args:
            task_id: The task ID to manage state for.
        """
        self.task_id = task_id
        self._db = None
        self._task_status = TaskStatus.CREATED
        self._subqueries: dict[str, SubqueryState] = {}
        
        # Budget tracking
        self._pages_limit = 120
        self._time_limit_seconds = 3600  # 60 minutes
        self._pages_used = 0
        self._time_started: float | None = None
        
        # Overall metrics
        self._total_fragments = 0
        self._total_claims = 0
        self._verified_claims = 0
        self._refuted_claims = 0
        
        # Novelty tracking (last 2 cycles)
        self._novelty_history: list[float] = []
    
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
        
        # Load existing subqueries
        queries = await self._db.fetch_all(
            """
            SELECT id, query_text, query_type, depth, harvest_rate
            FROM queries
            WHERE task_id = ?
            """,
            (self.task_id,),
        )
        
        for q in queries:
            sq = SubqueryState(
                id=q["id"],
                text=q.get("query_text", ""),
                harvest_rate=q.get("harvest_rate", 0.0),
            )
            self._subqueries[sq.id] = sq
    
    async def save_state(self) -> None:
        """Save current state to database."""
        await self._ensure_db()
        
        await self._db.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (self._task_status.value, self.task_id),
        )
    
    def register_subquery(
        self,
        subquery_id: str,
        text: str,
        priority: str = "medium",
        budget_pages: int | None = None,
        budget_time_seconds: int | None = None,
    ) -> SubqueryState:
        """
        Register a new subquery for execution.
        
        Args:
            subquery_id: Unique identifier for the subquery.
            text: The subquery text (designed by Cursor AI).
            priority: Execution priority (high/medium/low).
            budget_pages: Optional page budget for this subquery.
            budget_time_seconds: Optional time budget for this subquery.
            
        Returns:
            The created SubqueryState.
        """
        sq = SubqueryState(
            id=subquery_id,
            text=text,
            priority=priority,
            budget_pages=budget_pages,
            budget_time_seconds=budget_time_seconds,
        )
        self._subqueries[subquery_id] = sq
        
        logger.info(
            "Registered subquery",
            task_id=self.task_id,
            subquery_id=subquery_id,
            priority=priority,
        )
        
        return sq
    
    def start_subquery(self, subquery_id: str) -> SubqueryState | None:
        """Mark a subquery as running."""
        sq = self._subqueries.get(subquery_id)
        if sq:
            sq.status = SubqueryStatus.RUNNING
            sq.time_started = time.time()
            self._task_status = TaskStatus.EXPLORING
            
            if self._time_started is None:
                self._time_started = time.time()
        
        return sq
    
    def get_subquery(self, subquery_id: str) -> SubqueryState | None:
        """Get a subquery by ID."""
        return self._subqueries.get(subquery_id)
    
    def record_page_fetch(
        self,
        subquery_id: str,
        domain: str,
        is_primary_source: bool,
        is_independent: bool,
    ) -> None:
        """
        Record a page fetch for a subquery.
        
        Args:
            subquery_id: The subquery ID.
            domain: Domain of the fetched page.
            is_primary_source: Whether this is a primary source (gov/academic/official).
            is_independent: Whether this is an independent source (new domain/cluster).
        """
        sq = self._subqueries.get(subquery_id)
        if not sq:
            return
        
        sq.pages_fetched += 1
        self._pages_used += 1
        
        if is_independent:
            sq.independent_sources += 1
            if domain not in sq.source_domains:
                sq.source_domains.append(domain)
        
        if is_primary_source:
            sq.has_primary_source = True
        
        sq.update_status()
    
    def record_fragment(
        self,
        subquery_id: str,
        fragment_hash: str,
        is_useful: bool,
        is_novel: bool,
    ) -> None:
        """Record a fragment extraction."""
        sq = self._subqueries.get(subquery_id)
        if sq:
            sq.add_fragment(fragment_hash, is_useful, is_novel)
            self._total_fragments += 1
    
    def record_claim(self, subquery_id: str, is_verified: bool = False, is_refuted: bool = False) -> None:
        """Record a claim extraction.
        
        Args:
            subquery_id: The subquery ID.
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
    
    def check_novelty_stop_condition(self, subquery_id: str) -> bool:
        """
        Check if novelty stop condition is met (§3.1.7.4).
        
        Stop if novelty < 10% for 2 consecutive cycles.
        """
        sq = self._subqueries.get(subquery_id)
        if not sq:
            return False
        
        # Need at least 2 cycles (20 fragments)
        if sq.pages_fetched < 20:
            return False
        
        # Check last 2 cycles
        if sq.novelty_score < 0.1:
            self._novelty_history.append(sq.novelty_score)
            if len(self._novelty_history) >= 2:
                if all(n < 0.1 for n in self._novelty_history[-2:]):
                    return True
        else:
            self._novelty_history.clear()
        
        return False
    
    def get_status(self) -> dict[str, Any]:
        """
        Get current exploration status for Cursor AI.
        
        Returns comprehensive status including:
        - Task status
        - All subquery states
        - Overall progress
        - Budget information
        - Recommendations (informational only)
        - Warnings
        """
        elapsed_seconds = 0
        if self._time_started:
            elapsed_seconds = int(time.time() - self._time_started)
        
        # Count subquery statuses
        satisfied = sum(1 for sq in self._subqueries.values() if sq.status == SubqueryStatus.SATISFIED)
        partial = sum(1 for sq in self._subqueries.values() if sq.status == SubqueryStatus.PARTIAL)
        pending = sum(1 for sq in self._subqueries.values() if sq.status == SubqueryStatus.PENDING)
        
        # Generate warnings
        warnings = []
        within_budget, budget_warning = self.check_budget()
        if budget_warning:
            warnings.append(budget_warning)
        
        # Check for exhausted subqueries
        exhausted = [sq for sq in self._subqueries.values() if sq.status == SubqueryStatus.EXHAUSTED]
        if exhausted:
            warnings.append(f"{len(exhausted)}件のサブクエリが収穫逓減で停止")
        
        # Recommendations (informational, Cursor AI makes the decision)
        recommendations = []
        
        # Suggest high-priority pending subqueries
        high_priority_pending = [
            sq for sq in self._subqueries.values()
            if sq.status == SubqueryStatus.PENDING and sq.priority == "high"
        ]
        if high_priority_pending:
            recommendations.append({
                "action": "execute_subquery",
                "target": high_priority_pending[0].id,
                "reason": "高優先度の未実行サブクエリ",
            })
        
        # Suggest refutation for satisfied subqueries
        satisfied_no_refutation = [
            sq for sq in self._subqueries.values()
            if sq.status == SubqueryStatus.SATISFIED and sq.refutation_status == "pending"
        ]
        if satisfied_no_refutation:
            recommendations.append({
                "action": "refute",
                "target": satisfied_no_refutation[0].id,
                "reason": "充足済みサブクエリの反証探索を推奨",
            })
        
        # Suggest finalization
        all_done = all(
            sq.status in (SubqueryStatus.SATISFIED, SubqueryStatus.EXHAUSTED, SubqueryStatus.SKIPPED)
            for sq in self._subqueries.values()
        ) if self._subqueries else False
        
        if all_done:
            recommendations.append({
                "action": "finalize",
                "target": None,
                "reason": "すべてのサブクエリが完了",
            })
        
        return {
            "ok": True,
            "task_id": self.task_id,
            "task_status": self._task_status.value,
            "subqueries": [sq.to_dict() for sq in self._subqueries.values()],
            "overall_progress": {
                "satisfied_count": satisfied,
                "partial_count": partial,
                "pending_count": pending,
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
            "recommendations": recommendations,
            "warnings": warnings,
        }
    
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
        
        satisfied_sqs = [sq for sq in self._subqueries.values() if sq.status == SubqueryStatus.SATISFIED]
        partial_sqs = [sq for sq in self._subqueries.values() if sq.status == SubqueryStatus.PARTIAL]
        unsatisfied_sqs = [
            sq for sq in self._subqueries.values()
            if sq.status in (SubqueryStatus.PENDING, SubqueryStatus.EXHAUSTED)
        ]
        
        followup_suggestions = []
        for sq in unsatisfied_sqs:
            if sq.status == SubqueryStatus.EXHAUSTED:
                followup_suggestions.append(f"{sq.id}: 収穫逓減で停止。別のクエリ戦略が必要")
            elif sq.status == SubqueryStatus.PENDING:
                followup_suggestions.append(f"{sq.id}: 未実行")
        
        for sq in partial_sqs:
            if not sq.has_primary_source:
                followup_suggestions.append(f"{sq.id}: 一次資料が見つかっていません")
        
        # Determine final status
        final_status = "completed" if not unsatisfied_sqs else "partial"
        
        # Calculate refuted claims from subqueries with found refutations
        refuted_from_subqueries = sum(
            1 for sq in self._subqueries.values()
            if sq.refutation_status == "found"
        )
        total_refuted = max(self._refuted_claims, refuted_from_subqueries)
        
        # Calculate unverified claims
        unverified_claims = max(0, self._total_claims - self._verified_claims - total_refuted)
        
        # Get evidence graph stats if available
        evidence_graph_stats = await self._get_evidence_graph_stats()
        
        return {
            "ok": True,
            "task_id": self.task_id,
            "final_status": final_status,
            "summary": {
                "satisfied_subqueries": len(satisfied_sqs),
                "partial_subqueries": len(partial_sqs),
                "unsatisfied_subqueries": [sq.id for sq in unsatisfied_sqs],
                "total_claims": self._total_claims,
                "verified_claims": self._verified_claims,
                "refuted_claims": total_refuted,
                "unverified_claims": unverified_claims,
            },
            "followup_suggestions": followup_suggestions,
            "evidence_graph_summary": {
                "nodes": evidence_graph_stats.get("total_nodes", self._total_fragments + self._total_claims),
                "edges": evidence_graph_stats.get("total_edges", 0),
                "primary_source_ratio": sum(1 for sq in self._subqueries.values() if sq.has_primary_source) / max(1, len(self._subqueries)),
            },
        }

