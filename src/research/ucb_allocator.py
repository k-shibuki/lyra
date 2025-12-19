"""
UCB1-based budget allocation for search exploration.

Implements UCB1 (Upper Confidence Bound) algorithm for dynamic budget reallocation
based on search harvest rates. High-yield searches receive more budget.

See docs/requirements.md §3.1.1:
- Dynamic budget reallocation based on harvest rate (useful fragments / fetched pages) per search (UCB1-style)
- Exploration tree control optimization

Note: "search" replaces the former "subquery" terminology per Phase M.3-3.
"""

import math
from dataclasses import dataclass
from typing import Any

from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SearchArm:
    """
    Represents a search as a bandit arm.

    Tracks exploration history and calculates UCB1 scores.
    """

    search_id: str

    # Counters
    pulls: int = 0  # Number of pages fetched
    total_reward: float = 0.0  # Sum of rewards (useful fragments)

    # Current allocation
    allocated_budget: int = 0  # Currently allocated pages
    consumed_budget: int = 0  # Pages actually fetched

    # Performance tracking
    last_harvest_rate: float = 0.0
    priority_boost: float = 1.0  # Multiplier for high priority searches

    @property
    def average_reward(self) -> float:
        """Average reward (harvest rate)."""
        if self.pulls == 0:
            return 0.0
        return self.total_reward / self.pulls

    def record_observation(self, is_useful: bool) -> None:
        """
        Record an observation (page fetch).

        Args:
            is_useful: Whether the fetch yielded useful fragments.
        """
        self.pulls += 1
        self.consumed_budget += 1
        if is_useful:
            self.total_reward += 1.0
        self.last_harvest_rate = self.average_reward

    def remaining_budget(self) -> int:
        """Get remaining budget for this search."""
        return max(0, self.allocated_budget - self.consumed_budget)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "search_id": self.search_id,
            "pulls": self.pulls,
            "average_reward": self.average_reward,
            "allocated_budget": self.allocated_budget,
            "consumed_budget": self.consumed_budget,
            "remaining_budget": self.remaining_budget(),
            "priority_boost": self.priority_boost,
        }


# Backward compatibility alias (deprecated, will be removed)
SubqueryArm = SearchArm


class UCBAllocator:
    """
    UCB1-based dynamic budget allocator for searches.

    Implements the UCB1 algorithm to balance exploration (trying new searches)
    and exploitation (focusing on high-yield searches).

    UCB1 formula:
        score = average_reward + C * sqrt(ln(total_pulls) / pulls)

    Where:
        - average_reward = useful_fragments / pages_fetched
        - C = exploration constant (default: sqrt(2) ≈ 1.41)
        - total_pulls = total pages fetched across all searches
        - pulls = pages fetched for this specific search

    Budget is allocated proportionally to UCB1 scores, with constraints:
        - Minimum budget per search (prevents starvation)
        - Maximum budget per search (prevents monopolization)
        - Priority boost for high-priority searches

    Example usage:
        allocator = UCBAllocator(total_budget=120)
        allocator.register_search("s_001", priority="high")
        allocator.register_search("s_002", priority="medium")

        # Get initial allocation
        budget = allocator.get_budget("s_001")

        # Record observations
        allocator.record_observation("s_001", is_useful=True)
        allocator.record_observation("s_001", is_useful=False)

        # Get reallocated budget
        new_budget = allocator.reallocate_and_get_budget("s_001")
    """

    def __init__(
        self,
        total_budget: int = 120,
        exploration_constant: float | None = None,
        min_budget_per_search: int = 5,
        max_budget_ratio: float = 0.4,
        reallocation_interval: int = 10,
        # Backward compatibility (deprecated)
        min_budget_per_subquery: int | None = None,
    ):
        """
        Initialize the UCB allocator.

        Args:
            total_budget: Total page budget for the task (§3.1: ≤120/task).
            exploration_constant: UCB1 exploration constant C. Default: sqrt(2).
            min_budget_per_search: Minimum pages per search to prevent starvation.
            max_budget_ratio: Maximum ratio of total budget a single search can get.
            reallocation_interval: Pages between budget reallocations.
        """
        self.total_budget = total_budget
        self.exploration_constant = exploration_constant if exploration_constant is not None else math.sqrt(2)
        # Support deprecated parameter
        self.min_budget_per_search = min_budget_per_subquery if min_budget_per_subquery is not None else min_budget_per_search
        self.max_budget_ratio = max_budget_ratio
        self.reallocation_interval = reallocation_interval

        self._arms: dict[str, SearchArm] = {}
        self._total_pulls: int = 0
        self._pulls_since_reallocation: int = 0
        self._allocated_budget: int = 0

        logger.info(
            "UCB allocator initialized",
            total_budget=total_budget,
            exploration_constant=self.exploration_constant,
            min_budget=self.min_budget_per_search,
            max_ratio=max_budget_ratio,
        )

    # Backward compatibility property (deprecated, will be removed)
    @property
    def min_budget_per_subquery(self) -> int:
        """Deprecated: Use min_budget_per_search instead."""
        return self.min_budget_per_search

    def register_search(
        self,
        search_id: str,
        priority: str = "medium",
        initial_budget: int | None = None,
    ) -> SearchArm:
        """
        Register a new search arm.

        Args:
            search_id: Unique identifier for the search.
            priority: Priority level (high/medium/low).
            initial_budget: Optional initial budget allocation.

        Returns:
            The created SearchArm.
        """
        if search_id in self._arms:
            logger.debug("Search already registered", search_id=search_id)
            return self._arms[search_id]

        # Priority boost: high=1.5, medium=1.0, low=0.7
        priority_boosts = {"high": 1.5, "medium": 1.0, "low": 0.7}
        boost = priority_boosts.get(priority, 1.0)

        arm = SearchArm(
            search_id=search_id,
            priority_boost=boost,
        )
        self._arms[search_id] = arm

        # Allocate initial budget if specified, otherwise defer to reallocation
        if initial_budget is not None:
            arm.allocated_budget = min(initial_budget, self._get_max_budget())
            self._allocated_budget += arm.allocated_budget

        logger.debug(
            "Registered search arm",
            search_id=search_id,
            priority=priority,
            boost=boost,
        )

        return arm

    # Backward compatibility alias (deprecated, will be removed)
    def register_subquery(
        self,
        subquery_id: str,
        priority: str = "medium",
        initial_budget: int | None = None,
    ) -> SearchArm:
        """Deprecated: Use register_search instead."""
        return self.register_search(
            search_id=subquery_id,
            priority=priority,
            initial_budget=initial_budget,
        )

    def record_observation(
        self,
        search_id: str,
        is_useful: bool,
    ) -> None:
        """
        Record an observation for a search.

        Args:
            search_id: The search ID.
            is_useful: Whether the fetch yielded useful fragments.
        """
        arm = self._arms.get(search_id)
        if not arm:
            logger.warning("Unknown search", search_id=search_id)
            return

        arm.record_observation(is_useful)
        self._total_pulls += 1
        self._pulls_since_reallocation += 1

    def calculate_ucb_score(self, search_id: str) -> float:
        """
        Calculate UCB1 score for a search.

        UCB1 = average_reward + C * sqrt(ln(total_pulls) / pulls) * priority_boost

        For unplayed arms, returns infinity to encourage exploration.

        Args:
            search_id: The search ID.

        Returns:
            UCB1 score.
        """
        arm = self._arms.get(search_id)
        if not arm:
            return 0.0

        # Unplayed arms get maximum score (exploration)
        if arm.pulls == 0:
            return float("inf")

        # UCB1 formula
        exploitation = arm.average_reward

        if self._total_pulls > 0:
            exploration = self.exploration_constant * math.sqrt(
                math.log(self._total_pulls) / arm.pulls
            )
        else:
            exploration = 0.0

        score = (exploitation + exploration) * arm.priority_boost

        return score

    def get_all_ucb_scores(self) -> dict[str, float]:
        """
        Get UCB1 scores for all searches.

        Returns:
            Dictionary mapping search_id to UCB1 score.
        """
        return {
            search_id: self.calculate_ucb_score(search_id)
            for search_id in self._arms
        }

    def _get_max_budget(self) -> int:
        """Get maximum budget per search."""
        return int(self.total_budget * self.max_budget_ratio)

    def get_budget(self, search_id: str) -> int:
        """
        Get current allocated budget for a search.

        For unplayed arms (pulls=0) with no allocated budget, returns
        min_budget_per_search to enable initial exploration.

        Args:
            search_id: The search ID.

        Returns:
            Currently allocated budget (pages).
        """
        arm = self._arms.get(search_id)
        if not arm:
            return 0

        remaining = arm.remaining_budget()

        # Unplayed arms need initial budget for exploration
        if arm.pulls == 0 and remaining == 0:
            return self.min_budget_per_search

        return remaining

    def reallocate_budget(self) -> dict[str, int]:
        """
        Reallocate budget based on UCB1 scores.

        Budget is allocated proportionally to UCB1 scores, subject to:
        - Minimum budget per search
        - Maximum budget per search
        - Remaining total budget

        Returns:
            Dictionary mapping search_id to new allocated budget.
        """
        if not self._arms:
            return {}

        # Calculate remaining budget
        total_consumed = sum(arm.consumed_budget for arm in self._arms.values())
        remaining_budget = max(0, self.total_budget - total_consumed)

        if remaining_budget <= 0:
            logger.debug("No remaining budget to allocate")
            return {sid: arm.remaining_budget() for sid, arm in self._arms.items()}

        # Get UCB scores for active searches (not exhausted)
        active_arms = [
            (sid, arm, self.calculate_ucb_score(sid))
            for sid, arm in self._arms.items()
            if arm.consumed_budget < self._get_max_budget()
        ]

        if not active_arms:
            return {sid: arm.remaining_budget() for sid, arm in self._arms.items()}

        # Handle infinite scores (unplayed arms)
        inf_arms = [(sid, arm, score) for sid, arm, score in active_arms if math.isinf(score)]
        finite_arms = [(sid, arm, score) for sid, arm, score in active_arms if not math.isinf(score)]

        allocations: dict[str, int] = {}

        # First, ensure minimum budget for all unplayed arms
        if inf_arms:
            budget_for_inf = min(
                remaining_budget,
                len(inf_arms) * self.min_budget_per_search
            )
            per_arm = budget_for_inf // len(inf_arms)

            for sid, arm, _ in inf_arms:
                new_alloc = min(per_arm, self._get_max_budget() - arm.consumed_budget)
                arm.allocated_budget = arm.consumed_budget + new_alloc
                allocations[sid] = arm.remaining_budget()

            remaining_budget -= budget_for_inf

        # Allocate remaining budget proportionally to finite UCB scores
        if finite_arms and remaining_budget > 0:
            total_score = sum(score for _, _, score in finite_arms)

            if total_score > 0:
                for sid, arm, score in finite_arms:
                    proportion = score / total_score
                    raw_alloc = int(remaining_budget * proportion)

                    # Apply min/max constraints
                    max_additional = self._get_max_budget() - arm.consumed_budget
                    new_alloc = max(
                        self.min_budget_per_search,
                        min(raw_alloc, max_additional)
                    )

                    arm.allocated_budget = arm.consumed_budget + new_alloc
                    allocations[sid] = arm.remaining_budget()
            else:
                # Equal distribution if all scores are 0
                per_arm = remaining_budget // len(finite_arms)
                for sid, arm, _ in finite_arms:
                    max_additional = self._get_max_budget() - arm.consumed_budget
                    new_alloc = min(per_arm, max_additional)
                    arm.allocated_budget = arm.consumed_budget + new_alloc
                    allocations[sid] = arm.remaining_budget()

        # Include non-active arms with 0 remaining
        for sid, arm in self._arms.items():
            if sid not in allocations:
                allocations[sid] = arm.remaining_budget()

        self._pulls_since_reallocation = 0
        self._allocated_budget = sum(
            arm.allocated_budget for arm in self._arms.values()
        )

        logger.debug(
            "Budget reallocated",
            allocations=allocations,
            remaining_total=remaining_budget,
        )

        return allocations

    def should_reallocate(self) -> bool:
        """
        Check if budget reallocation is needed.

        Reallocation is triggered:
        - Every `reallocation_interval` pulls
        - When a played search exhausts its budget (not unplayed arms)

        Returns:
            True if reallocation is recommended.
        """
        if self._pulls_since_reallocation >= self.reallocation_interval:
            return True

        # Check if any played search has exhausted its budget
        # Note: Unplayed arms (consumed_budget=0) with no allocation are NOT considered exhausted
        for arm in self._arms.values():
            if (arm.consumed_budget > 0 and
                arm.remaining_budget() <= 0 and
                arm.consumed_budget < self._get_max_budget()):
                return True

        return False

    def reallocate_and_get_budget(self, search_id: str) -> int:
        """
        Optionally reallocate and return budget for a search.

        Performs reallocation if `should_reallocate()` returns True.

        Args:
            search_id: The search ID.

        Returns:
            Available budget for the search.
        """
        if self.should_reallocate():
            self.reallocate_budget()

        return self.get_budget(search_id)

    def get_recommended_search(self) -> str | None:
        """
        Get the search with highest UCB score.

        Useful for deciding which search to execute next.

        Returns:
            Search ID with highest UCB score, or None if no searches.
        """
        if not self._arms:
            return None

        scores = self.get_all_ucb_scores()

        # Filter to searches with remaining budget
        available = [
            (sid, score)
            for sid, score in scores.items()
            if self._arms[sid].remaining_budget() > 0
            or self._arms[sid].pulls == 0  # Unplayed arms
        ]

        if not available:
            return None

        return max(available, key=lambda x: x[1])[0]

    # Backward compatibility alias (deprecated, will be removed)
    def get_recommended_subquery(self) -> str | None:
        """Deprecated: Use get_recommended_search instead."""
        return self.get_recommended_search()

    def get_status(self) -> dict[str, Any]:
        """
        Get current allocator status.

        Returns:
            Dictionary with allocator state and statistics.
        """
        total_consumed = sum(arm.consumed_budget for arm in self._arms.values())

        return {
            "total_budget": self.total_budget,
            "total_consumed": total_consumed,
            "remaining_budget": self.total_budget - total_consumed,
            "total_pulls": self._total_pulls,
            "exploration_constant": self.exploration_constant,
            "arms": {
                sid: {
                    **arm.to_dict(),
                    "ucb_score": self.calculate_ucb_score(sid),
                }
                for sid, arm in self._arms.items()
            },
            "recommended_next": self.get_recommended_search(),
        }

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for persistence."""
        return {
            "total_budget": self.total_budget,
            "exploration_constant": self.exploration_constant,
            "min_budget_per_search": self.min_budget_per_search,
            "max_budget_ratio": self.max_budget_ratio,
            "reallocation_interval": self.reallocation_interval,
            "total_pulls": self._total_pulls,
            "pulls_since_reallocation": self._pulls_since_reallocation,
            "arms": {sid: arm.to_dict() for sid, arm in self._arms.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UCBAllocator":
        """Restore from dictionary."""
        # Support both old and new key names
        min_budget = data.get("min_budget_per_search") or data.get("min_budget_per_subquery", 5)

        allocator = cls(
            total_budget=data.get("total_budget", 120),
            exploration_constant=data.get("exploration_constant"),
            min_budget_per_search=min_budget,
            max_budget_ratio=data.get("max_budget_ratio", 0.4),
            reallocation_interval=data.get("reallocation_interval", 10),
        )

        allocator._total_pulls = data.get("total_pulls", 0)
        allocator._pulls_since_reallocation = data.get("pulls_since_reallocation", 0)

        for sid, arm_data in data.get("arms", {}).items():
            # Support both old and new key names
            search_id = arm_data.get("search_id") or arm_data.get("subquery_id") or sid
            arm = SearchArm(
                search_id=search_id,
                pulls=arm_data.get("pulls", 0),
                total_reward=arm_data.get("pulls", 0) * arm_data.get("average_reward", 0),
                allocated_budget=arm_data.get("allocated_budget", 0),
                consumed_budget=arm_data.get("consumed_budget", 0),
                priority_boost=arm_data.get("priority_boost", 1.0),
            )
            allocator._arms[sid] = arm

        return allocator

