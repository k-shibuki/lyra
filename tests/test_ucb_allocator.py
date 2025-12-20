"""
Tests for UCB1-based budget allocation.

Tests the UCBAllocator class and its integration with ExplorationState.
See docs/REQUIREMENTS.md §3.1.1.

Note: "search" replaces the former "subquery" terminology per Phase M.3-3.

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-SA-01 | SearchArm initial state | Equivalence – defaults | All values at 0 | - |
| TC-SA-02 | SearchArm average_reward | Equivalence – calculation | Correct average | - |
| TC-SA-03 | SearchArm with 0 pulls | Boundary – zero | average=0 | - |
| TC-UA-01 | UCBAllocator initialization | Equivalence – init | Arms empty | - |
| TC-UA-02 | Add search arm | Equivalence – add | Arm registered | - |
| TC-UA-03 | Select arm initial | Boundary – unexplored | Unexplored first | - |
| TC-UA-04 | Select arm UCB1 | Equivalence – UCB1 | Highest UCB selected | - |
| TC-UA-05 | Update arm reward | Equivalence – update | Stats updated | - |
| TC-UA-06 | Allocate budget | Equivalence – allocation | Budget distributed | - |
| TC-UA-07 | Get best arm | Equivalence – best | Highest reward arm | - |
| TC-UA-08 | Arm exploitation ratio | Equivalence – ratio | Correct calculation | - |
| TC-UA-09 | Multiple arms selection | Equivalence – multi | Fair exploration | - |
"""

import math

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit

# E402: Intentionally import after pytestmark for test configuration
from src.research.ucb_allocator import SearchArm, UCBAllocator


class TestSearchArm:
    """Tests for SearchArm dataclass."""

    def test_initial_state(self) -> None:
        """Test arm initialization with default values."""
        arm = SearchArm(search_id="s_001")

        assert arm.search_id == "s_001"
        assert arm.pulls == 0
        assert arm.total_reward == 0.0
        assert arm.allocated_budget == 0
        assert arm.consumed_budget == 0
        assert arm.average_reward == 0.0

    def test_record_observation_useful(self) -> None:
        """Test recording useful observations."""
        arm = SearchArm(search_id="s_001")

        arm.record_observation(is_useful=True)

        assert arm.pulls == 1
        assert arm.total_reward == 1.0
        assert arm.consumed_budget == 1
        assert arm.average_reward == 1.0

    def test_record_observation_not_useful(self) -> None:
        """Test recording non-useful observations."""
        arm = SearchArm(search_id="s_001")

        arm.record_observation(is_useful=False)

        assert arm.pulls == 1
        assert arm.total_reward == 0.0
        assert arm.average_reward == 0.0

    def test_average_reward_calculation(self) -> None:
        """Test average reward with mixed observations."""
        arm = SearchArm(search_id="s_001")

        # 3 useful, 2 not useful
        for _ in range(3):
            arm.record_observation(is_useful=True)
        for _ in range(2):
            arm.record_observation(is_useful=False)

        assert arm.pulls == 5
        assert arm.total_reward == 3.0
        assert arm.average_reward == 0.6

    def test_remaining_budget(self) -> None:
        """Test remaining budget calculation."""
        arm = SearchArm(search_id="s_001", allocated_budget=10)

        assert arm.remaining_budget() == 10

        arm.record_observation(is_useful=True)
        arm.record_observation(is_useful=False)

        assert arm.remaining_budget() == 8

    def test_remaining_budget_exhausted(self) -> None:
        """Test remaining budget when exhausted."""
        arm = SearchArm(search_id="s_001", allocated_budget=2)

        arm.record_observation(is_useful=True)
        arm.record_observation(is_useful=True)
        arm.record_observation(is_useful=True)  # Over budget

        assert arm.remaining_budget() == 0  # Never negative

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        arm = SearchArm(search_id="s_001", allocated_budget=10, priority_boost=1.5)
        arm.record_observation(is_useful=True)

        result = arm.to_dict()

        assert result["search_id"] == "s_001"
        assert result["pulls"] == 1
        assert result["average_reward"] == 1.0
        assert result["allocated_budget"] == 10
        assert result["consumed_budget"] == 1
        assert result["remaining_budget"] == 9
        assert result["priority_boost"] == 1.5


class TestUCBAllocator:
    """Tests for UCBAllocator class."""

    def test_initialization(self) -> None:
        """Test allocator initialization."""
        allocator = UCBAllocator(
            total_budget=100,
            exploration_constant=1.5,
            min_budget_per_search=3,
            max_budget_ratio=0.5,
        )

        assert allocator.total_budget == 100
        assert allocator.exploration_constant == 1.5
        assert allocator.min_budget_per_search == 3
        assert allocator.max_budget_ratio == 0.5

    def test_default_exploration_constant(self) -> None:
        """Test default exploration constant is sqrt(2)."""
        allocator = UCBAllocator(total_budget=100)

        assert allocator.exploration_constant == pytest.approx(math.sqrt(2))

    def test_register_search(self) -> None:
        """Test registering a new search."""
        allocator = UCBAllocator(total_budget=100)

        arm = allocator.register_search("s_001", priority="high")

        assert arm.search_id == "s_001"
        assert arm.priority_boost == 1.5  # High priority boost

    def test_register_search_priority_boosts(self) -> None:
        """Test priority boosts for different priority levels."""
        allocator = UCBAllocator(total_budget=100)

        high_arm = allocator.register_search("sq_high", priority="high")
        medium_arm = allocator.register_search("sq_medium", priority="medium")
        low_arm = allocator.register_search("sq_low", priority="low")

        assert high_arm.priority_boost == 1.5
        assert medium_arm.priority_boost == 1.0
        assert low_arm.priority_boost == 0.7

    def test_register_search_with_initial_budget(self) -> None:
        """Test registering search with initial budget."""
        allocator = UCBAllocator(total_budget=100, max_budget_ratio=0.4)

        arm = allocator.register_search("sq_001", initial_budget=30)

        assert arm.allocated_budget == 30

    def test_register_search_budget_capped(self) -> None:
        """Test initial budget is capped at max_budget_ratio."""
        allocator = UCBAllocator(total_budget=100, max_budget_ratio=0.4)

        arm = allocator.register_search("sq_001", initial_budget=60)

        assert arm.allocated_budget == 40  # Capped at 40% of 100

    def test_record_observation(self) -> None:
        """Test recording observations updates allocator state."""
        allocator = UCBAllocator(total_budget=100)
        allocator.register_search("sq_001")

        allocator.record_observation("sq_001", is_useful=True)

        assert allocator._total_pulls == 1
        arm = allocator._arms["sq_001"]
        assert arm.pulls == 1
        assert arm.total_reward == 1.0

    def test_ucb_score_unplayed_arm(self) -> None:
        """Test UCB score for unplayed arm is infinity."""
        allocator = UCBAllocator(total_budget=100)
        allocator.register_search("sq_001")

        score = allocator.calculate_ucb_score("sq_001")

        assert math.isinf(score)

    def test_ucb_score_played_arm(self) -> None:
        """Test UCB score for played arm."""
        allocator = UCBAllocator(total_budget=100, exploration_constant=1.0)
        allocator.register_search("sq_001")

        # Record 10 observations, 6 useful (60% harvest rate)
        for i in range(10):
            allocator.record_observation("sq_001", is_useful=(i < 6))

        score = allocator.calculate_ucb_score("sq_001")

        # UCB = average_reward + C * sqrt(ln(total) / pulls)
        # = 0.6 + 1.0 * sqrt(ln(10) / 10)
        expected_exploitation = 0.6
        expected_exploration = math.sqrt(math.log(10) / 10)
        expected = expected_exploitation + expected_exploration

        assert score == pytest.approx(expected, rel=0.01)

    def test_ucb_score_with_priority_boost(self) -> None:
        """Test UCB score is multiplied by priority boost."""
        allocator = UCBAllocator(total_budget=100, exploration_constant=0)  # No exploration

        allocator.register_search("sq_high", priority="high")
        allocator.register_search("sq_low", priority="low")

        # Same harvest rate for both
        for _ in range(5):
            allocator.record_observation("sq_high", is_useful=True)
            allocator.record_observation("sq_low", is_useful=True)

        high_score = allocator.calculate_ucb_score("sq_high")
        low_score = allocator.calculate_ucb_score("sq_low")

        # High priority (1.5x) vs low priority (0.7x)
        assert high_score / low_score == pytest.approx(1.5 / 0.7, rel=0.01)

    def test_get_all_ucb_scores(self) -> None:
        """Test getting UCB scores for all subqueries."""
        allocator = UCBAllocator(total_budget=100)
        allocator.register_search("sq_001")
        allocator.register_search("sq_002")
        allocator.register_search("sq_003")

        scores = allocator.get_all_ucb_scores()

        assert len(scores) == 3
        assert "sq_001" in scores
        assert "sq_002" in scores
        assert "sq_003" in scores

    def test_reallocate_budget_unplayed_arms(self) -> None:
        """Test budget reallocation with unplayed arms."""
        allocator = UCBAllocator(
            total_budget=100,
            min_budget_per_search=5,
        )
        allocator.register_search("sq_001")
        allocator.register_search("sq_002")

        allocations = allocator.reallocate_budget()

        # Unplayed arms should get at least min_budget
        assert allocations["sq_001"] >= 5
        assert allocations["sq_002"] >= 5

    def test_reallocate_budget_based_on_harvest_rate(self) -> None:
        """Test budget reallocation favors high harvest rate subqueries."""
        allocator = UCBAllocator(
            total_budget=100,
            exploration_constant=0,  # Disable exploration for deterministic test
        )
        allocator.register_search("sq_high", priority="medium")
        allocator.register_search("sq_low", priority="medium")

        # sq_high: 80% harvest rate
        for i in range(10):
            allocator.record_observation("sq_high", is_useful=(i < 8))

        # sq_low: 20% harvest rate
        for i in range(10):
            allocator.record_observation("sq_low", is_useful=(i < 2))

        allocations = allocator.reallocate_budget()

        # Higher harvest rate should get more budget
        assert allocations["sq_high"] > allocations["sq_low"]

    def test_reallocate_budget_respects_max_ratio(self) -> None:
        """Test budget reallocation respects max_budget_ratio."""
        allocator = UCBAllocator(
            total_budget=100,
            max_budget_ratio=0.3,
        )
        allocator.register_search("sq_001")

        # Even with perfect harvest rate, max is 30% of total
        for _ in range(10):
            allocator.record_observation("sq_001", is_useful=True)

        allocations = allocator.reallocate_budget()

        # Max budget is 30 (30% of 100)
        # Consumed 10, so remaining should be at most 20
        assert allocations["sq_001"] <= 30 - 10

    def test_should_reallocate_interval(self) -> None:
        """Test should_reallocate triggers after interval."""
        allocator = UCBAllocator(total_budget=100, reallocation_interval=5)
        allocator.register_search("sq_001")

        # Initially should not trigger (unplayed arm is not "exhausted")
        assert not allocator.should_reallocate()

        for _ in range(5):
            allocator.record_observation("sq_001", is_useful=True)

        # After 5 pulls (= interval), should trigger
        assert allocator.should_reallocate()

    def test_should_reallocate_exhausted_budget(self) -> None:
        """Test should_reallocate triggers when budget exhausted."""
        allocator = UCBAllocator(total_budget=100, reallocation_interval=100)
        arm = allocator.register_search("sq_001", initial_budget=3)

        for _ in range(3):
            allocator.record_observation("sq_001", is_useful=True)

        assert arm.remaining_budget() == 0
        assert allocator.should_reallocate()

    def test_reallocate_and_get_budget(self) -> None:
        """Test reallocate_and_get_budget triggers reallocation when needed."""
        allocator = UCBAllocator(total_budget=100, reallocation_interval=5)
        allocator.register_search("sq_001", initial_budget=5)

        # Use all initial budget
        for _ in range(5):
            allocator.record_observation("sq_001", is_useful=True)

        # Should trigger reallocation and return new budget
        new_budget = allocator.reallocate_and_get_budget("sq_001")

        assert new_budget > 0  # Got new budget

    def test_get_recommended_search(self) -> None:
        """Test getting recommended search based on UCB score."""
        allocator = UCBAllocator(total_budget=100)
        allocator.register_search("sq_001")
        allocator.register_search("sq_002")

        # sq_002 unplayed should have infinity score
        # Both unplayed, so either could be recommended
        recommended = allocator.get_recommended_search()

        assert recommended in ("sq_001", "sq_002")

    def test_get_recommended_search_with_budget(self) -> None:
        """Test recommended search considers remaining budget."""
        allocator = UCBAllocator(total_budget=20, max_budget_ratio=0.5)
        allocator.register_search("sq_001", initial_budget=10)
        allocator.register_search("sq_002", initial_budget=10)

        # Exhaust sq_001's budget
        for _ in range(10):
            allocator.record_observation("sq_001", is_useful=True)

        # sq_001 has no remaining budget, so sq_002 should be recommended
        recommended = allocator.get_recommended_search()

        assert recommended == "sq_002"

    def test_get_status(self) -> None:
        """Test getting allocator status."""
        allocator = UCBAllocator(total_budget=100)
        allocator.register_search("sq_001")
        allocator.record_observation("sq_001", is_useful=True)

        status = allocator.get_status()

        assert status["total_budget"] == 100
        assert status["total_consumed"] == 1
        assert status["remaining_budget"] == 99
        assert status["total_pulls"] == 1
        assert "sq_001" in status["arms"]
        assert "ucb_score" in status["arms"]["sq_001"]

    def test_to_dict_and_from_dict(self) -> None:
        """Test serialization and deserialization."""
        allocator = UCBAllocator(
            total_budget=100,
            exploration_constant=1.5,
            min_budget_per_search=3,
        )
        allocator.register_search("sq_001", priority="high")
        allocator.record_observation("sq_001", is_useful=True)

        data = allocator.to_dict()
        restored = UCBAllocator.from_dict(data)

        assert restored.total_budget == 100
        assert restored.exploration_constant == 1.5
        assert restored.min_budget_per_search == 3
        assert restored._total_pulls == 1
        assert "sq_001" in restored._arms


class TestUCBAllocatorIntegration:
    """Integration tests for UCBAllocator with ExplorationState."""

    @pytest.mark.asyncio
    async def test_exploration_state_with_ucb(self) -> None:
        """Test ExplorationState with UCB allocation enabled."""
        from src.research.state import ExplorationState

        state = ExplorationState(
            task_id="test_task",
            enable_ucb_allocation=True,
        )

        assert state._ucb_allocator is not None

    @pytest.mark.asyncio
    async def test_exploration_state_without_ucb(self) -> None:
        """Test ExplorationState with UCB allocation disabled."""
        from src.research.state import ExplorationState

        state = ExplorationState(
            task_id="test_task",
            enable_ucb_allocation=False,
        )

        assert state._ucb_allocator is None

    @pytest.mark.asyncio
    async def test_register_search_updates_ucb(self) -> None:
        """Test registering search also registers with UCB allocator."""
        from src.research.state import ExplorationState

        state = ExplorationState(task_id="test_task", enable_ucb_allocation=True)
        state.register_search("sq_001", "test query", priority="high")

        assert "sq_001" in state._ucb_allocator._arms
        assert state._ucb_allocator._arms["sq_001"].priority_boost == 1.5

    @pytest.mark.asyncio
    async def test_record_fragment_updates_ucb(self) -> None:
        """Test recording fragment also updates UCB allocator."""
        from src.research.state import ExplorationState

        state = ExplorationState(task_id="test_task", enable_ucb_allocation=True)
        state.register_search("sq_001", "test query")

        state.record_fragment("sq_001", "hash123", is_useful=True, is_novel=True)

        arm = state._ucb_allocator._arms["sq_001"]
        assert arm.pulls == 1
        assert arm.total_reward == 1.0

    @pytest.mark.asyncio
    async def test_get_dynamic_budget(self) -> None:
        """Test getting dynamic budget from UCB allocator."""
        from src.research.state import ExplorationState

        state = ExplorationState(task_id="test_task", enable_ucb_allocation=True)
        state.register_search("sq_001", "test query")

        budget = state.get_dynamic_budget("sq_001")

        assert budget > 0

    @pytest.mark.asyncio
    async def test_get_dynamic_budget_without_ucb(self) -> None:
        """Test getting budget without UCB allocation uses static budget."""
        from src.research.state import ExplorationState

        state = ExplorationState(task_id="test_task", enable_ucb_allocation=False)
        state.register_search("sq_001", "test query", budget_pages=20)

        budget = state.get_dynamic_budget("sq_001")

        assert budget == 20

    @pytest.mark.asyncio
    async def test_get_ucb_recommended_search(self) -> None:
        """Test getting UCB recommended search."""
        from src.research.state import ExplorationState

        state = ExplorationState(task_id="test_task", enable_ucb_allocation=True)
        state.register_search("sq_001", "query 1")
        state.register_search("sq_002", "query 2")

        recommended = state.get_ucb_recommended_search()

        assert recommended in ("sq_001", "sq_002")

    @pytest.mark.asyncio
    async def test_get_ucb_scores(self) -> None:
        """Test getting UCB scores for all subqueries."""
        from src.research.state import ExplorationState

        state = ExplorationState(task_id="test_task", enable_ucb_allocation=True)
        state.register_search("sq_001", "query 1")
        state.register_search("sq_002", "query 2")

        scores = state.get_ucb_scores()

        assert "sq_001" in scores
        assert "sq_002" in scores

    @pytest.mark.asyncio
    async def test_get_status_includes_ucb_scores(self) -> None:
        """Test get_status includes UCB scores information (not recommendations)."""
        from src.research.state import ExplorationState

        state = ExplorationState(task_id="test_task", enable_ucb_allocation=True)
        state.register_search("sq_001", "query 1")

        status = await state.get_status()

        # ucb_scores contains raw data only (no recommendations)
        assert "ucb_scores" in status
        assert status["ucb_scores"]["enabled"] is True
        assert "arm_scores" in status["ucb_scores"]
        assert "arm_budgets" in status["ucb_scores"]

    @pytest.mark.asyncio
    async def test_trigger_budget_reallocation(self) -> None:
        """Test manual budget reallocation trigger."""
        from src.research.state import ExplorationState

        state = ExplorationState(task_id="test_task", enable_ucb_allocation=True)
        state.register_search("sq_001", "query 1")
        state.register_search("sq_002", "query 2")

        # Record some observations
        for _ in range(5):
            state.record_fragment("sq_001", f"hash_{_}", is_useful=True, is_novel=True)

        allocations = state.trigger_budget_reallocation()

        assert "sq_001" in allocations
        assert "sq_002" in allocations


class TestUCBAllocatorEdgeCases:
    """Edge case tests for UCBAllocator."""

    def test_empty_allocator(self) -> None:
        """Test operations on empty allocator."""
        allocator = UCBAllocator(total_budget=100)

        assert allocator.get_recommended_search() is None
        assert allocator.get_all_ucb_scores() == {}
        assert allocator.reallocate_budget() == {}

    def test_record_unknown_search(self) -> None:
        """Test recording observation for unknown search."""
        allocator = UCBAllocator(total_budget=100)

        # Should not raise, just log warning
        allocator.record_observation("unknown", is_useful=True)

        assert allocator._total_pulls == 0

    def test_get_budget_unknown_search(self) -> None:
        """Test getting budget for unknown search."""
        allocator = UCBAllocator(total_budget=100)

        budget = allocator.get_budget("unknown")

        assert budget == 0

    def test_ucb_score_unknown_search(self) -> None:
        """Test UCB score for unknown search."""
        allocator = UCBAllocator(total_budget=100)

        score = allocator.calculate_ucb_score("unknown")

        assert score == 0.0

    def test_duplicate_registration(self) -> None:
        """Test registering same search twice returns existing arm."""
        allocator = UCBAllocator(total_budget=100)

        arm1 = allocator.register_search("sq_001", priority="high")
        arm2 = allocator.register_search("sq_001", priority="low")  # Different priority

        assert arm1 is arm2
        assert arm1.priority_boost == 1.5  # Original priority preserved

    def test_budget_exhausted(self) -> None:
        """Test behavior when total budget is exhausted."""
        allocator = UCBAllocator(total_budget=10)
        allocator.register_search("sq_001", initial_budget=10)

        for _ in range(10):
            allocator.record_observation("sq_001", is_useful=True)

        allocations = allocator.reallocate_budget()

        # No remaining budget
        assert allocations["sq_001"] == 0

    def test_zero_total_pulls_ucb(self) -> None:
        """Test UCB calculation with zero total pulls."""
        allocator = UCBAllocator(total_budget=100)
        arm = allocator.register_search("sq_001")
        arm.pulls = 1  # Manually set to simulate edge case
        arm.total_reward = 0.5

        # total_pulls is still 0 (not recorded through record_observation)
        score = allocator.calculate_ucb_score("sq_001")

        # Should not divide by zero, exploration term is 0
        assert score == pytest.approx(0.5, rel=0.01)
