"""
Exploration state management for Lyra.

Manages task and search states, calculates satisfaction and novelty scores.
Reports state to Cursor AI for decision making.

See ADR-0010.

Note: This module uses "search" terminology.
"""

import asyncio
import time
from collections import deque
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.storage.database import get_database
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.research.ucb_allocator import UCBAllocator
    from src.storage.database import Database

logger = get_logger(__name__)


class SearchStatus(Enum):
    """Status of a search execution."""

    PENDING = "pending"  # Created but not executed
    RUNNING = "running"  # Currently executing
    SATISFIED = "satisfied"  # Sufficient sources found (≥3 independent or 1 primary + 1 secondary)
    PARTIAL = "partial"  # Some sources found (1-2 independent)
    EXHAUSTED = "exhausted"  # Budget consumed or novelty dropped
    SKIPPED = "skipped"  # Manually skipped by Cursor AI


class TaskStatus(Enum):
    """Status of a research task.

    Lifecycle:
    - CREATED: Task created, waiting for searches to be queued.
    - EXPLORING: Exploration in progress (searches running).
    - AWAITING_DECISION: Paused, waiting for Cursor AI decision.
    - PAUSED: Session ended; task is resumable (can queue more searches).
    - FAILED: Failed with error (terminal state).

    Note: FINALIZING and COMPLETED are deprecated; use PAUSED instead.
    PAUSED indicates "this session ended" but the task can be resumed later.
    """

    CREATED = "created"  # Task created, Cursor AI designing searches
    EXPLORING = "exploring"  # Exploration in progress
    AWAITING_DECISION = "awaiting_decision"  # Waiting for Cursor AI decision
    PAUSED = "paused"  # Session ended; resumable (replaces COMPLETED)
    FAILED = "failed"  # Failed with error
    # Deprecated: kept for backward compatibility when reading from DB
    FINALIZING = "finalizing"  # (deprecated) Use PAUSED
    COMPLETED = "completed"  # (deprecated) Use PAUSED


class SearchState(BaseModel):
    """State of a single search query.

    Per ADR-0010: Tracks source count, satisfaction score,
    and novelty metrics for Cursor AI decision making.

    Migrated from dataclass to Pydantic BaseModel for type safety
    and validation in module-to-module data exchange.
    """

    model_config = ConfigDict(
        arbitrary_types_allowed=True,  # For deque type
        validate_assignment=True,  # Validate on attribute assignment
    )

    # Required fields
    id: str = Field(..., description="Unique search identifier")
    text: str = Field(..., description="Search query text")

    # Status and priority
    status: SearchStatus = Field(
        default=SearchStatus.PENDING, description="Current execution status"
    )
    priority: str = Field(default="medium", description="Execution priority (high/medium/low)")

    # Source tracking
    independent_sources: int = Field(
        default=0, ge=0, description="Count of independent sources found"
    )
    has_primary_source: bool = Field(
        default=False, description="Whether a gov/academic primary source was found"
    )
    source_domains: list[str] = Field(
        default_factory=list, description="List of unique source domains"
    )

    # Metrics
    pages_fetched: int = Field(default=0, ge=0, description="Number of pages fetched")
    useful_fragments: int = Field(
        default=0, ge=0, description="Number of useful fragments extracted"
    )
    harvest_rate: float = Field(
        default=0.0,
        ge=0.0,
        description="Useful fragments per page (can exceed 1.0 if multiple fragments per page)",
    )
    novelty_score: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Ratio of novel fragments in recent window"
    )
    satisfaction_score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Source satisfaction score"
    )

    # Refutation
    refutation_status: str = Field(
        default="pending", description="Refutation status (pending/found/not_found)"
    )
    refutation_count: int = Field(default=0, ge=0, description="Number of refutations found")

    # Budget
    budget_pages: int | None = Field(
        default=None, ge=0, description="Optional page budget for this search"
    )
    budget_time_seconds: int | None = Field(
        default=None, ge=0, description="Optional time budget in seconds"
    )
    time_started: float | None = Field(
        default=None, description="Unix timestamp when search started"
    )

    # Recent fragments for novelty calculation (not serialized)
    recent_fragment_hashes: deque = Field(
        default_factory=lambda: deque(maxlen=20),
        exclude=True,  # Exclude from serialization
        description="Recent fragment hashes for novelty calculation",
    )

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        """Validate priority is one of the allowed values."""
        allowed = {"high", "medium", "low"}
        if v not in allowed:
            raise ValueError(f"priority must be one of {allowed}, got '{v}'")
        return v

    @field_validator("refutation_status")
    @classmethod
    def validate_refutation_status(cls, v: str) -> str:
        """Validate refutation_status is one of the allowed values."""
        allowed = {"pending", "found", "not_found"}
        if v not in allowed:
            raise ValueError(f"refutation_status must be one of {allowed}, got '{v}'")
        return v

    def calculate_satisfaction_score(self) -> float:
        """
        Calculate satisfaction score per ADR-0010.

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
        """Convert to dictionary for serialization.

        Note: Uses Pydantic's model_dump() internally but formats
        status as string value for API compatibility.
        """
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

    Tracks search execution, calculates metrics, and provides
    status reports to Cursor AI for decision making.

    Integrates UCB1-based dynamic budget allocation (ADR-0010):
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
        self._db: Database | None = None
        self._task_status = TaskStatus.CREATED
        self._searches: dict[str, SearchState] = {}

        # Task hypothesis for context (used by llm_extract for focus, ADR-0017)
        self.task_hypothesis: str = ""

        # Budget tracking
        self._budget_pages_limit = 120
        self._time_limit_seconds = 3600  # 60 minutes
        self._budget_pages_used = 0
        self._time_started: float | None = None

        # UCB1 allocation (ADR-0010)
        self._enable_ucb = enable_ucb_allocation
        self._ucb_allocator: UCBAllocator | None = None
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

        # Activity tracking for ADR-0002 Cursor AI idle timeout
        self._last_activity_at: float = time.time()

        # Long polling support (ADR-0010)
        # Event is set when status changes (search complete/failed/cancelled)
        self._status_changed: asyncio.Event = asyncio.Event()

    def _init_ucb_allocator(self) -> None:
        """Initialize the UCB allocator."""
        from src.research.ucb_allocator import UCBAllocator

        self._ucb_allocator = UCBAllocator(
            total_budget=self._budget_pages_limit,
            exploration_constant=self._ucb_exploration_constant,
            min_budget_per_search=5,
            max_budget_ratio=0.4,
            reallocation_interval=10,
        )
        logger.info(
            "UCB allocator enabled",
            task_id=self.task_id,
            total_budget=self._budget_pages_limit,
        )

    def record_activity(self) -> None:
        """Record activity timestamp for ADR-0002 idle timeout tracking."""
        self._last_activity_at = time.time()

    def get_idle_seconds(self) -> float:
        """Get seconds since last activity.

        Returns:
            Seconds elapsed since last activity (search, status check, etc.).
        """
        return time.time() - self._last_activity_at

    def notify_status_change(self) -> None:
        """Notify waiting clients that status has changed.

        Called by SearchQueueWorker when a search completes, fails, or is cancelled.
        Wakes up any get_status(wait=N) calls waiting on this task.

        Per ADR-0010: Long polling implementation using asyncio.Event.
        """
        self._status_changed.set()

    async def wait_for_change(self, timeout: float) -> bool:
        """Wait for status change or timeout.

        Used by get_status(wait=N) for long polling.

        Args:
            timeout: Maximum seconds to wait for a status change.

        Returns:
            True if a change occurred, False if timeout expired.

        Per ADR-0010: Long polling implementation.
        """
        try:
            await asyncio.wait_for(self._status_changed.wait(), timeout)
            self._status_changed.clear()
            return True
        except TimeoutError:
            return False

    async def _ensure_db(self) -> None:
        """Ensure database connection is available."""
        if self._db is None:
            self._db = await get_database()

    async def load_state(self) -> None:
        """Load state from database."""
        await self._ensure_db()
        assert self._db is not None  # Guaranteed by _ensure_db

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

            # Load original query for context (used by llm_extract)
            # ADR-0017: hypothesis is the central claim to verify
            self.task_hypothesis = task.get("hypothesis", "")

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

        # Load metrics from database
        await self._load_metrics_from_db()

    async def _load_metrics_from_db(self) -> None:
        """Load accumulated metrics from database.

        Restores total_claims, total_fragments, and budget_pages_used
        from the database so that get_status returns accurate values
        even after MCP server restart.
        """
        assert self._db is not None

        # Count claims directly (claims table has task_id)
        claims_count = await self._db.fetch_one(
            "SELECT COUNT(*) as cnt FROM claims WHERE task_id = ?",
            (self.task_id,),
        )
        if claims_count:
            self._total_claims = claims_count.get("cnt", 0) or 0

        # Count fragments and pages via the query chain:
        # queries -> serp_items -> pages -> fragments
        metrics = await self._db.fetch_one(
            """
            SELECT
                COUNT(DISTINCT p.id) as page_count,
                COUNT(DISTINCT f.id) as fragment_count
            FROM queries q
            JOIN serp_items s ON s.query_id = q.id
            JOIN pages p ON p.url = s.url
            LEFT JOIN fragments f ON f.page_id = p.id
            WHERE q.task_id = ?
            """,
            (self.task_id,),
        )
        if metrics:
            self._budget_pages_used = metrics.get("page_count", 0) or 0
            self._total_fragments = metrics.get("fragment_count", 0) or 0

        logger.debug(
            "Loaded metrics from DB",
            task_id=self.task_id,
            claims=self._total_claims,
            pages=self._budget_pages_used,
            fragments=self._total_fragments,
        )

    async def save_state(self) -> None:
        """Save current state to database."""
        await self._ensure_db()
        assert self._db is not None  # Guaranteed by _ensure_db

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

        # Register with UCB allocator (ADR-0010)
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

    def get_search(self, search_id: str) -> SearchState | None:
        """Get a search by ID."""
        return self._searches.get(search_id)

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
        self._budget_pages_used += 1

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

            # Record observation in UCB allocator (ADR-0010)
            if self._ucb_allocator:
                self._ucb_allocator.record_observation(search_id, is_useful)

    def record_claim(
        self, search_id: str, is_verified: bool = False, is_refuted: bool = False
    ) -> None:
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
        if self._budget_pages_used >= self._budget_pages_limit:
            return False, "ページ数上限に達しました"

        # Check time budget
        if self._time_started:
            elapsed = time.time() - self._time_started
            if elapsed >= self._time_limit_seconds:
                return False, "時間上限に達しました"

        # Warnings
        pages_remaining_ratio = 1 - (self._budget_pages_used / self._budget_pages_limit)
        if pages_remaining_ratio < 0.2:
            return True, f"予算残り{int(pages_remaining_ratio * 100)}%"

        return True, None

    def get_dynamic_budget(self, search_id: str) -> int:
        """
        Get dynamic budget for a search using UCB1 allocation (ADR-0010).

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

    def get_overall_harvest_rate(self) -> float:
        """
        Calculate overall harvest rate across all searches.

        Per ADR-0010: Used for lastmile slot determination.
        Lastmile engines are activated when harvest rate >= 0.9.

        Returns:
            Overall harvest rate (0.0-1.0).
        """
        if not self._searches:
            return 0.0

        total_useful = sum(s.useful_fragments for s in self._searches.values())
        total_pages = sum(s.pages_fetched for s in self._searches.values())

        if total_pages == 0:
            return 0.0

        return total_useful / total_pages

    def check_novelty_stop_condition(self, search_id: str) -> bool:
        """
        Check if novelty stop condition is met (ADR-0010).

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

        Per ADR-0007: Now includes authentication_queue information.
        Per ADR-0007: Includes authentication threshold alerts in warnings.

        Returns:
            - Task status
            - All search states
            - Metrics (counts, pages, fragments, claims)
            - Budget information
            - UCB scores (raw data, not recommendations)
            - Authentication queue status (ADR-0007)
            - Warnings (including auth queue alerts per ADR-0007)
        """
        elapsed_seconds = 0
        if self._time_started:
            elapsed_seconds = int(time.time() - self._time_started)

        # Count search statuses
        satisfied = sum(1 for s in self._searches.values() if s.status == SearchStatus.SATISFIED)
        partial = sum(1 for s in self._searches.values() if s.status == SearchStatus.PARTIAL)
        pending = sum(1 for s in self._searches.values() if s.status == SearchStatus.PENDING)
        exhausted_count = sum(
            1 for s in self._searches.values() if s.status == SearchStatus.EXHAUSTED
        )

        # Generate warnings (factual alerts, not recommendations)
        warnings = []
        within_budget, budget_warning = self.check_budget()
        if budget_warning:
            warnings.append(budget_warning)

        if exhausted_count > 0:
            warnings.append(f"{exhausted_count}件の検索が収穫逓減で停止")

        # Get authentication queue summary (ADR-0007)
        authentication_queue = await self._get_authentication_queue_summary()

        # Add authentication queue alerts (ADR-0007)
        auth_warnings = self._generate_auth_queue_alerts(authentication_queue)
        warnings.extend(auth_warnings)

        # Add idle time warning (ADR-0002)
        idle_seconds = self.get_idle_seconds()
        from src.utils.config import get_settings

        settings = get_settings()
        idle_timeout = settings.task_limits.cursor_idle_timeout_seconds
        if idle_seconds >= idle_timeout:
            warnings.append(
                f"Task idle for {int(idle_seconds)} seconds (timeout: {idle_timeout}s). "
                "Consider resuming or stopping."
            )

        # UCB scores (raw data only, no "recommended_next")
        ucb_scores = None
        if self._ucb_allocator:
            ucb_status = self._ucb_allocator.get_status()
            ucb_scores = {
                "enabled": True,
                "arm_scores": {
                    sid: arm.get("ucb_score", 0) for sid, arm in ucb_status.get("arms", {}).items()
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
                "total_pages": self._budget_pages_used,
                "total_fragments": self._total_fragments,
                "total_claims": self._total_claims,
                "elapsed_seconds": elapsed_seconds,
            },
            "budget": {
                "budget_pages_used": self._budget_pages_used,
                "budget_pages_limit": self._budget_pages_limit,
                "time_used_seconds": elapsed_seconds,
                "time_limit_seconds": self._time_limit_seconds,
            },
            "ucb_scores": ucb_scores,
            "authentication_queue": authentication_queue,
            "warnings": warnings,
            "idle_seconds": int(idle_seconds),  # ADR-0002: Cursor AI idle timeout tracking
        }

    async def _get_authentication_queue_summary(self) -> dict[str, Any] | None:
        """Get authentication queue summary for this task.

        Per ADR-0007: Provides authentication queue information.

        Returns:
            Authentication queue summary or None if no pending items.
        """
        try:
            from src.utils.intervention_queue import get_intervention_queue

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

        Per ADR-0007: Warning levels based on queue depth.
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
                alerts.append(f"[critical] 認証待ち{pending_count}件: 探索継続に影響")
        # Warning level: ≥3 pending
        elif pending_count >= 3:
            domain_sample = ", ".join(domains[:3])
            if len(domains) > 3:
                domain_sample += f" 他{len(domains) - 3}件"
            alerts.append(f"[warning] 認証待ち{pending_count}件 ({domain_sample})")

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

    async def finalize(self, reason: str = "session_completed") -> dict[str, Any]:
        """
        Finalize exploration session and return summary.

        This marks the current session as ended. The task transitions to PAUSED,
        meaning it can be resumed later with additional searches.

        Args:
            reason: Stop reason. Determines final_status:
                - "session_completed" -> "paused" (default, resumable)
                - "budget_exhausted" -> "paused" (resumable after budget increase)
                - "user_cancelled" -> "cancelled" (explicit user stop)

        Returns:
            Summary including final status, search completion stats,
            unsatisfied searches, and followup suggestions.
        """
        # Map reason to final_status and TaskStatus
        if reason == "user_cancelled":
            final_status = "cancelled"
            self._task_status = TaskStatus.PAUSED  # Still resumable if user changes mind
        else:
            # session_completed, budget_exhausted -> paused
            final_status = "paused"
            self._task_status = TaskStatus.PAUSED

        satisfied_searches = [
            s for s in self._searches.values() if s.status == SearchStatus.SATISFIED
        ]
        partial_searches = [s for s in self._searches.values() if s.status == SearchStatus.PARTIAL]
        unsatisfied_searches = [
            s
            for s in self._searches.values()
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

        # Calculate refuted claims from searches with found refutations
        refuted_from_searches = sum(
            1 for s in self._searches.values() if s.refutation_status == "found"
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
                "nodes": evidence_graph_stats.get(
                    "total_nodes", self._total_fragments + self._total_claims
                ),
                "edges": evidence_graph_stats.get("total_edges", 0),
                "primary_source_ratio": sum(
                    1 for s in self._searches.values() if s.has_primary_source
                )
                / max(1, len(self._searches)),
            },
            "is_resumable": True,  # Task can always be resumed with more searches
        }
