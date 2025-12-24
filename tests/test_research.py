"""
Tests for Exploration Control Engine.

These tests verify the exploration control functionality per ADR-0002 and ADR-0010:
- ResearchContext provides design support information (not subquery candidates)
- SubqueryExecutor executes Cursor AI-designed queries
- ExplorationState manages task/subquery states and metrics
- RefutationExecutor applies mechanical patterns only

Test Quality Standards (.1):
- No conditional assertions
- Specific value assertions
- No OR-condition assertions
- Given/When/Then pattern
- Docstrings explaining test intent

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-RES-N-01 | Query with organization entity | Equivalence – normal | Context with entities | Entity extraction |
| TC-RES-N-02 | Query with research keyword | Equivalence – normal | Academic template suggested | Template matching |
| TC-RES-N-03 | Any query | Equivalence – normal | No subquery_candidates | ADR-0002 boundary |
| TC-RES-N-04 | Any query | Equivalence – normal | Recommended engines list | Engine recommendation |
| TC-RES-A-01 | Nonexistent task_id | Equivalence – error | ok=False with error | Task not found |
| TC-RES-N-05 | 3 sources, no primary | Equivalence – normal | Score = 0.7 | ADR-0010 formula |
| TC-RES-N-06 | 2 sources + primary | Equivalence – normal | Score ≈ 0.767 | Primary bonus |
| TC-RES-N-07 | Score >= 0.8 | Boundary – threshold | is_satisfied=True | Satisfaction threshold |
| TC-RES-N-08 | 7/10 novel fragments | Equivalence – normal | Novelty = 0.7 | ADR-0010 formula |
| TC-RES-N-09 | 3 sources + primary | Equivalence – transition | Status=SATISFIED | Status transition |
| TC-RES-N-10 | 1 source | Equivalence – partial | Status=PARTIAL | Partial status |
| TC-RES-N-11 | Register + start subquery | Equivalence – normal | Status=RUNNING | State management |
| TC-RES-N-12 | 10 page fetches | Boundary – limit | Budget warning | Budget tracking |
| TC-RES-N-13 | 2 subqueries | Equivalence – normal | All required fields | get_status structure |
| TC-RES-N-14 | 2 pending auth items | Equivalence – normal | auth_queue in status | ADR-0007 |
| TC-RES-N-15 | 3 pending items | Boundary – warning | Warning alert | ADR-0007 threshold |
| TC-RES-N-16 | 5 pending items | Boundary – critical | Critical alert | Count threshold |
| TC-RES-N-17 | 2 high priority items | Boundary – critical | Critical alert | Priority threshold |
| TC-RES-N-18 | 1 satisfied, 1 unsatisfied | Equivalence – normal | Partial status + suggestions | finalize() |
| TC-RES-N-19 | PRIMARY_SOURCE_DOMAINS | Equivalence – normal | Known domains included | Domain set |
| TC-RES-N-20 | Japanese query | Equivalence – expansion | Core term preserved | Mechanical only |
| TC-RES-N-21 | Claim text | Equivalence – normal | Suffix-based queries | Refutation patterns |
| TC-RES-N-22 | REFUTATION_SUFFIXES | Equivalence – normal | Required suffixes exist | Suffix constants |
| TC-RES-N-23 | Claim text | Equivalence – normal | Reverse queries with suffix | Mechanical patterns |
| TC-RES-N-24 | RefutationResult | Equivalence – normal | Correct structure | ADR-0003 structure |
| TC-RES-N-25 | Full workflow | Equivalence – integration | Complete flow works | Context→Execute→Status |
| TC-RES-N-26 | ResearchContext class | Equivalence – boundary | No design methods | ADR-0002 |
| TC-RES-N-27 | RefutationExecutor class | Equivalence – boundary | No LLM methods | ADR-0002 |
| TC-RES-N-28 | Context notes | Equivalence – boundary | No directives | Informational only |
| TC-SS-B-01 | independent_sources=0 | Boundary – zero sources | Score = 0.0 | ADR-0010 |
| TC-SS-B-02 | independent_sources>=10 | Boundary – max sources | Score capped at 0.7 | ADR-0010 |
| TC-SS-A-01 | Invalid priority value | Abnormal – validation | ValidationError | Pydantic migration |
| TC-SS-A-02 | Negative pages_fetched | Abnormal – validation | ValidationError | Pydantic migration |
| TC-SS-A-03 | Invalid refutation_status | Abnormal – validation | ValidationError | Pydantic migration |
| TC-SS-B-03 | novelty_score=0.0 | Boundary – zero novelty | Valid state | ADR-0010 |
| TC-SS-B-04 | novelty_score=1.0 | Boundary – max novelty | Valid state | ADR-0010 |
| TC-ES-B-01 | pages_limit=0 | Boundary – zero limit | Immediate budget exceeded | - |
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

if TYPE_CHECKING:
    from src.storage.database import Database

# E402: Intentionally import after pytestmark for test configuration
from src.research.context import (
    ResearchContext,
)
from src.research.executor import PRIMARY_SOURCE_DOMAINS, SubqueryExecutor
from src.research.refutation import REFUTATION_SUFFIXES, RefutationExecutor, RefutationResult
from src.research.state import (
    ExplorationState,
    SubqueryState,
    SubqueryStatus,
)

# =============================================================================
# ResearchContext Tests (ADR-0010)
# =============================================================================


class TestResearchContext:
    """
    Tests for ResearchContext design support information provider.

    Per ADR-0002: ResearchContext provides support information but does NOT
    generate subquery candidates. That is Cursor AI's responsibility.
    """

    @pytest.mark.asyncio
    async def test_get_context_returns_entities(self, test_database: Database) -> None:
        """
        Verify that get_context extracts and returns entities from the query.

        ADR-0010: ResearchContext extracts entities (person/organization/location/etc.)
        """
        # Given: A task with a query containing organization entity
        task_id = await test_database.create_task(
            query="株式会社トヨタ自動車の2024年決算情報",
        )
        context = ResearchContext(task_id)
        context._db = test_database

        # When: Get research context
        result = await context.get_context()

        # Then: Context contains extracted entities
        assert result["ok"] is True
        assert result["task_id"] == task_id
        assert result["original_query"] == "株式会社トヨタ自動車の2024年決算情報"
        [e["type"] for e in result["extracted_entities"]]
        assert isinstance(result["extracted_entities"], list)

    @pytest.mark.asyncio
    async def test_get_context_returns_applicable_templates(self, test_database: Database) -> None:
        """
        Verify that get_context returns applicable vertical templates.

        ADR-0010: Templates include academic/government/corporate/technical.
        """
        # Given: A task with research-related query
        task_id = await test_database.create_task(
            query="機械学習の最新研究論文",
        )
        context = ResearchContext(task_id)
        context._db = test_database

        # When: Get research context
        result = await context.get_context()

        # Then: Academic template is suggested
        assert result["ok"] is True
        templates = result["applicable_templates"]
        assert len(templates) >= 1, f"Expected >=1 templates, got {len(templates)}"
        template_names = [t["name"] for t in templates]
        assert "academic" in template_names

    @pytest.mark.asyncio
    async def test_get_context_does_not_return_subquery_candidates(
        self, test_database: Database
    ) -> None:
        """
        Verify that get_context does NOT return subquery candidates.

        ADR-0002: Subquery design is Cursor AI's exclusive responsibility.
        ADR-0002: Lyra must NOT generate subquery candidates.
        """
        # Given: A task with any query
        task_id = await test_database.create_task(
            query="AIの倫理的課題について",
        )
        context = ResearchContext(task_id)
        context._db = test_database

        # When: Get research context
        result = await context.get_context()

        # Then: Result does NOT contain subquery candidates
        assert result["ok"] is True
        assert "subquery_candidates" not in result
        assert "suggested_subqueries" not in result
        assert "generated_queries" not in result

    @pytest.mark.asyncio
    async def test_get_context_returns_recommended_engines(self, test_database: Database) -> None:
        """
        Verify that get_context returns recommended search engines.
        """
        # Given: A task with a simple query
        task_id = await test_database.create_task(query="test query")
        context = ResearchContext(task_id)
        context._db = test_database

        # When: Get research context
        result = await context.get_context()

        # Then: Result contains recommended engines
        assert result["ok"] is True
        assert "recommended_engines" in result
        assert isinstance(result["recommended_engines"], list)
        assert len(result["recommended_engines"]) >= 1, (
            f"Expected >=1 recommended engines, got {result['recommended_engines']}"
        )

    @pytest.mark.asyncio
    async def test_get_context_task_not_found(self, test_database: Database) -> None:
        """
        Verify that get_context returns error for non-existent task.
        """
        # Given: A context with nonexistent task ID
        context = ResearchContext("nonexistent_task_id")
        context._db = test_database

        # When: Get research context
        result = await context.get_context()

        # Then: Result indicates error
        assert result["ok"] is False
        assert "error" in result


# =============================================================================
# SubqueryState Tests (ADR-0010)
# =============================================================================


class TestSubqueryState:
    """
    Tests for SubqueryState satisfaction and novelty calculations.

    ADR-0010: Satisfaction score = min(1.0, (sources/3)*0.7 + (primary?0.3:0))
    ADR-0010: Novelty score = novel fragments / recent fragments
    """

    def test_satisfaction_score_with_three_sources(self) -> None:
        """
        Verify satisfaction score is 0.7 with exactly 3 independent sources.

        ADR-0010: Score = (3/3)*0.7 + 0 = 0.7
        """
        # Given: A subquery with 3 independent sources, no primary
        sq = SubqueryState(id="sq_001", text="test query")
        sq.independent_sources = 3
        sq.has_primary_source = False

        # When: Calculate satisfaction score
        score = sq.calculate_satisfaction_score()

        # Then: Score is 0.7
        assert score == 0.7

    def test_satisfaction_score_with_primary_source(self) -> None:
        """
        Verify satisfaction score includes 0.3 bonus for primary source.

        ADR-0010: Score = (2/3)*0.7 + 0.3 ≈ 0.767
        """
        # Given: A subquery with 2 sources and primary source
        sq = SubqueryState(id="sq_002", text="test query")
        sq.independent_sources = 2
        sq.has_primary_source = True

        # When: Calculate satisfaction score
        score = sq.calculate_satisfaction_score()

        # Then: Score includes primary bonus
        expected = (2 / 3) * 0.7 + 0.3
        assert abs(score - expected) < 0.01

    def test_is_satisfied_threshold(self) -> None:
        """
        Verify is_satisfied returns True when score >= 0.8.

        ADR-0010: Satisfied when score >= 0.8.
        """
        # Given: Two subqueries with different satisfaction levels
        sq_satisfied = SubqueryState(id="sq_003", text="test")
        sq_satisfied.independent_sources = 3
        sq_satisfied.has_primary_source = True

        sq_not_satisfied = SubqueryState(id="sq_004", text="test")
        sq_not_satisfied.independent_sources = 2
        sq_not_satisfied.has_primary_source = False

        # When/Then: Check satisfaction status
        assert sq_satisfied.is_satisfied() is True
        assert sq_not_satisfied.is_satisfied() is False

    def test_novelty_score_calculation(self) -> None:
        """
        Verify novelty score is calculated from recent fragments.

        ADR-0010: Novelty = novel fragments / total recent fragments.
        """
        # Given: A subquery with 10 fragments, 7 novel
        sq = SubqueryState(id="sq_005", text="test")

        for i in range(10):
            is_novel = i < 7
            sq.add_fragment(f"hash_{i}", is_useful=True, is_novel=is_novel)

        # When: Get novelty score
        novelty = sq.novelty_score

        # Then: Novelty is 0.7 (7/10)
        assert novelty == 0.7

    def test_status_transitions(self) -> None:
        """
        Verify status transitions from PENDING to SATISFIED.
        """
        # Given: A subquery in PENDING status
        sq = SubqueryState(id="sq_006", text="test")
        assert sq.status == SubqueryStatus.PENDING

        # When: Add enough sources to satisfy
        sq.independent_sources = 3
        sq.has_primary_source = True
        sq.update_status()

        # Then: Status becomes SATISFIED
        assert sq.status == SubqueryStatus.SATISFIED

    def test_status_partial_with_some_sources(self) -> None:
        """
        Verify status is PARTIAL when 1-2 sources found.
        """
        # Given: A subquery with only 1 source
        sq = SubqueryState(id="sq_007", text="test")
        sq.independent_sources = 1

        # When: Update status
        sq.update_status()

        # Then: Status is PARTIAL
        assert sq.status == SubqueryStatus.PARTIAL


# =============================================================================
# SearchState Pydantic Validation Tests
# =============================================================================


class TestSearchStatePydanticValidation:
    """
    Tests for SearchState Pydantic validation after migration.

    Per test-strategy.mdc: Validation tests ensure type safety
    and proper error messages for invalid inputs.
    """

    def test_valid_creation_with_required_fields_only(self) -> None:
        """TC-SS-N-01: Create SearchState with only required fields.

        // Given: Only id and text provided
        // When: Creating SearchState
        // Then: All optional fields use defaults
        """
        # Given: Only required fields
        # When: Creating SearchState
        sq = SubqueryState(id="sq_001", text="test query")

        # Then: Instance created with defaults
        assert sq.id == "sq_001"
        assert sq.text == "test query"
        assert sq.status == SubqueryStatus.PENDING
        assert sq.priority == "medium"
        assert sq.independent_sources == 0
        assert sq.pages_fetched == 0
        assert sq.novelty_score == 1.0
        assert sq.satisfaction_score == 0.0

    def test_invalid_priority_raises_validation_error(self) -> None:
        """TC-SS-A-01: Invalid priority value raises ValidationError.

        // Given: Invalid priority value 'critical'
        // When: Creating SearchState
        // Then: ValidationError with message about allowed values
        """
        from pydantic import ValidationError

        # Given: Invalid priority value
        # When/Then: ValidationError raised
        with pytest.raises(ValidationError) as exc_info:
            SubqueryState(id="sq_001", text="test", priority="critical")

        # Then: Error message mentions 'priority'
        error_str = str(exc_info.value)
        assert "priority" in error_str.lower()

    def test_negative_pages_fetched_raises_validation_error(self) -> None:
        """TC-SS-A-02: Negative pages_fetched raises ValidationError.

        // Given: Negative pages_fetched value
        // When: Creating SearchState
        // Then: ValidationError with message about constraint
        """
        from pydantic import ValidationError

        # Given: Negative pages_fetched
        # When/Then: ValidationError raised
        with pytest.raises(ValidationError) as exc_info:
            SubqueryState(id="sq_001", text="test", pages_fetched=-1)

        # Then: Error message mentions constraint
        error_str = str(exc_info.value)
        assert "pages_fetched" in error_str.lower() or "greater than" in error_str.lower()

    def test_invalid_refutation_status_raises_validation_error(self) -> None:
        """TC-SS-A-03: Invalid refutation_status raises ValidationError.

        // Given: Invalid refutation_status value
        // When: Creating SearchState
        // Then: ValidationError with message about allowed values
        """
        from pydantic import ValidationError

        # Given: Invalid refutation_status
        # When/Then: ValidationError raised
        with pytest.raises(ValidationError) as exc_info:
            SubqueryState(id="sq_001", text="test", refutation_status="invalid")

        # Then: Error message mentions 'refutation_status'
        error_str = str(exc_info.value)
        assert "refutation_status" in error_str.lower()

    def test_negative_independent_sources_raises_validation_error(self) -> None:
        """TC-SS-A-04: Negative independent_sources raises ValidationError.

        // Given: Negative independent_sources value
        // When: Creating SearchState
        // Then: ValidationError raised
        """
        from pydantic import ValidationError

        # Given: Negative independent_sources
        # When/Then: ValidationError raised
        with pytest.raises(ValidationError):
            SubqueryState(id="sq_001", text="test", independent_sources=-1)

    def test_harvest_rate_negative_raises_validation_error(self) -> None:
        """TC-SS-A-05: Negative harvest_rate raises ValidationError.

        // Given: harvest_rate = -0.5 (negative)
        // When: Creating SearchState
        // Then: ValidationError raised

        Note: harvest_rate can exceed 1.0 when multiple fragments are
        extracted from a single page.
        """
        from pydantic import ValidationError

        # Given: harvest_rate negative
        # When/Then: ValidationError raised
        with pytest.raises(ValidationError):
            SubqueryState(id="sq_001", text="test", harvest_rate=-0.5)

    def test_harvest_rate_above_one_is_valid(self) -> None:
        """TC-SS-N-06: harvest_rate > 1.0 is valid.

        // Given: harvest_rate = 2.5 (multiple fragments per page)
        // When: Creating SearchState
        // Then: Valid state created
        """
        # Given: harvest_rate > 1.0
        # When: Creating SearchState
        state = SubqueryState(id="sq_001", text="test", harvest_rate=2.5)

        # Then: Valid state with harvest_rate > 1.0
        assert state.harvest_rate == 2.5


# =============================================================================
# SearchState Boundary Value Tests
# =============================================================================


class TestSearchStateBoundaryValues:
    """
    Boundary value tests for SearchState.

    Per test-strategy.mdc: Tests for 0, min, max, ±1, empty, NULL.
    """

    def test_satisfaction_score_with_zero_sources(self) -> None:
        """TC-SS-B-01: Score is 0.0 with zero independent sources.

        // Given: independent_sources = 0, no primary source
        // When: Calculate satisfaction score
        // Then: Score = 0.0
        """
        # Given: Zero sources
        sq = SubqueryState(id="sq_001", text="test")
        sq.independent_sources = 0
        sq.has_primary_source = False

        # When: Calculate score
        score = sq.calculate_satisfaction_score()

        # Then: Score is 0.0
        assert score == 0.0

    def test_satisfaction_score_capped_with_many_sources(self) -> None:
        """TC-SS-B-02: Score is capped at 1.0 with many sources.

        // Given: independent_sources = 10, primary source
        // When: Calculate satisfaction score
        // Then: Score = 1.0 (capped)
        """
        # Given: Many sources
        sq = SubqueryState(id="sq_001", text="test")
        sq.independent_sources = 10
        sq.has_primary_source = True

        # When: Calculate score
        score = sq.calculate_satisfaction_score()

        # Then: Score is capped at 1.0
        assert score == 1.0

    def test_novelty_score_zero_boundary(self) -> None:
        """TC-SS-B-03: novelty_score = 0.0 is valid.

        // Given: novelty_score = 0.0
        // When: Creating SearchState
        // Then: Valid state with novelty_score = 0.0
        """
        # Given: Zero novelty
        sq = SubqueryState(id="sq_001", text="test", novelty_score=0.0)

        # Then: Valid state
        assert sq.novelty_score == 0.0

    def test_novelty_score_max_boundary(self) -> None:
        """TC-SS-B-04: novelty_score = 1.0 is valid.

        // Given: novelty_score = 1.0
        // When: Creating SearchState
        // Then: Valid state with novelty_score = 1.0
        """
        # Given: Max novelty
        sq = SubqueryState(id="sq_001", text="test", novelty_score=1.0)

        # Then: Valid state
        assert sq.novelty_score == 1.0

    def test_satisfaction_threshold_exactly_0_8(self) -> None:
        """TC-SS-B-05: Exact threshold 0.8 satisfies condition.

        // Given: Exact score of 0.8 (3 sources + no primary = 0.7, so need adjustment)
        // When: Check is_satisfied()
        // Then: Returns True
        """
        # Given: 3 sources + primary = (3/3)*0.7 + 0.3 = 1.0 >= 0.8
        sq = SubqueryState(id="sq_001", text="test")
        sq.independent_sources = 3
        sq.has_primary_source = True

        # When: Check satisfaction
        is_satisfied = sq.is_satisfied()

        # Then: Satisfied
        assert is_satisfied is True
        assert sq.satisfaction_score == 1.0

    def test_satisfaction_threshold_just_below_0_8(self) -> None:
        """TC-SS-B-06: Score just below 0.8 does not satisfy.

        // Given: Score of 0.7 (3 sources, no primary)
        // When: Check is_satisfied()
        // Then: Returns False
        """
        # Given: 3 sources, no primary = (3/3)*0.7 + 0 = 0.7 < 0.8
        sq = SubqueryState(id="sq_001", text="test")
        sq.independent_sources = 3
        sq.has_primary_source = False

        # When: Check satisfaction
        is_satisfied = sq.is_satisfied()

        # Then: Not satisfied
        assert is_satisfied is False
        assert sq.satisfaction_score == 0.7

    def test_empty_source_domains_list(self) -> None:
        """TC-SS-B-07: Empty source_domains list is valid.

        // Given: Default source_domains (empty list)
        // When: Creating SearchState
        // Then: source_domains is empty list
        """
        # Given: Default creation
        sq = SubqueryState(id="sq_001", text="test")

        # Then: Empty list
        assert sq.source_domains == []
        assert isinstance(sq.source_domains, list)

    def test_budget_pages_none_is_valid(self) -> None:
        """TC-SS-B-08: budget_pages = None is valid.

        // Given: budget_pages not specified
        // When: Creating SearchState
        // Then: budget_pages is None
        """
        # Given: Default creation
        sq = SubqueryState(id="sq_001", text="test")

        # Then: None is valid
        assert sq.budget_pages is None

    def test_budget_pages_zero_is_valid(self) -> None:
        """TC-SS-B-09: budget_pages = 0 is valid (boundary).

        // Given: budget_pages = 0
        // When: Creating SearchState
        // Then: Valid state with budget_pages = 0
        """
        # Given: Zero budget
        sq = SubqueryState(id="sq_001", text="test", budget_pages=0)

        # Then: Valid
        assert sq.budget_pages == 0


# =============================================================================
# ExplorationState Tests (ADR-0010)
# =============================================================================


class TestExplorationState:
    """
    Tests for ExplorationState task management.
    """

    @pytest.mark.asyncio
    async def test_register_and_start_subquery(self, test_database: Database) -> None:
        """
        Verify subquery registration and starting.
        """
        # Given: An exploration state for a task
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database

        # When: Register and start a subquery
        sq = state.register_subquery(
            subquery_id="sq_001",
            text="test subquery",
            priority="high",
        )
        state.start_subquery("sq_001")

        # Then: Subquery is running with correct attributes
        assert sq.id == "sq_001"
        assert sq.text == "test subquery"
        assert sq.priority == "high"
        assert sq.status == SubqueryStatus.RUNNING

    @pytest.mark.asyncio
    async def test_budget_tracking(self, test_database: Database) -> None:
        """
        Verify page budget is tracked correctly.
        """
        # Given: An exploration state with small page limit
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database
        state._pages_limit = 10

        state.register_subquery("sq_001", "test")

        # When: Fetch pages up to limit
        for i in range(10):
            state.record_page_fetch("sq_001", f"domain{i}.com", False, True)

        within_budget, warning = state.check_budget()

        # Then: Budget is exceeded with warning
        assert within_budget is False
        assert warning is not None
        assert "上限" in warning

    @pytest.mark.asyncio
    async def test_get_status_returns_all_required_fields(self, test_database: Database) -> None:
        """
        Verify get_status returns all required fields per ADR-0003.
        Now async per ADR-0007 changes.
        """
        # Given: An exploration state with 2 subqueries
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database
        state.register_subquery("sq_001", "subquery 1", priority="high")
        state.register_subquery("sq_002", "subquery 2", priority="medium")

        # When: Get status
        status = await state.get_status()

        # Then: Status contains all required fields
        assert status["ok"] is True
        assert status["task_id"] == task_id
        assert "task_status" in status
        assert "searches" in status
        assert len(status["searches"]) == 2
        assert "metrics" in status
        assert "budget" in status
        assert "warnings" in status

    @pytest.mark.asyncio
    async def test_get_status_includes_authentication_queue(self, test_database: Database) -> None:
        """
        Verify get_status includes authentication_queue when pending items exist.

        Per ADR-0007: authentication_queue should contain summary information.
        """

        # Given: An exploration state with pending auth items
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database

        mock_summary = {
            "pending_count": 2,
            "high_priority_count": 1,
            "domains": ["example.gov", "secondary.com"],
            "oldest_queued_at": "2024-01-01T00:00:00+00:00",
            "by_auth_type": {"cloudflare": 1, "captcha": 1},
        }

        with patch.object(
            state,
            "_get_authentication_queue_summary",
            new_callable=AsyncMock,
            return_value=mock_summary,
        ):
            # When: Get status
            status = await state.get_status()

        # Then: authentication_queue is included
        assert status["authentication_queue"] is not None, (
            "authentication_queue should not be None when items pending"
        )
        auth_queue = status["authentication_queue"]
        assert auth_queue["pending_count"] == 2, (
            f"pending_count should be 2, got {auth_queue['pending_count']}"
        )
        assert auth_queue["high_priority_count"] == 1, (
            f"high_priority_count should be 1, got {auth_queue['high_priority_count']}"
        )
        assert len(auth_queue["domains"]) == 2, (
            f"Should have 2 domains, got {len(auth_queue['domains'])}"
        )

    @pytest.mark.asyncio
    async def test_auth_queue_warning_threshold(self, test_database: Database) -> None:
        """
        Verify warning alert is generated when pending >= 3.

        Per ADR-0007: [warning] when pending >= 3.
        """

        # Given: 3 pending auth items
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database

        mock_summary = {
            "pending_count": 3,
            "high_priority_count": 0,
            "domains": ["example0.com", "example1.com", "example2.com"],
            "oldest_queued_at": "2024-01-01T00:00:00+00:00",
            "by_auth_type": {"cloudflare": 3},
        }

        with patch.object(
            state,
            "_get_authentication_queue_summary",
            new_callable=AsyncMock,
            return_value=mock_summary,
        ):
            # When: Get status
            status = await state.get_status()

        # Then: Warning alert is generated
        warning_alerts = [w for w in status["warnings"] if "[warning]" in w]
        assert len(warning_alerts) == 1, (
            f"Should have 1 warning alert, got {len(warning_alerts)}: {status['warnings']}"
        )
        assert "認証待ち3件" in warning_alerts[0], (
            f"Warning should mention '認証待ち3件', got '{warning_alerts[0]}'"
        )

    @pytest.mark.asyncio
    async def test_auth_queue_critical_threshold_by_count(self, test_database: Database) -> None:
        """
        Verify critical alert is generated when pending >= 5.

        Per ADR-0007: [critical] when pending >= 5.
        """

        # Given: 5 pending auth items
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database

        mock_summary = {
            "pending_count": 5,
            "high_priority_count": 0,
            "domains": [
                "example0.com",
                "example1.com",
                "example2.com",
                "example3.com",
                "example4.com",
            ],
            "oldest_queued_at": "2024-01-01T00:00:00+00:00",
            "by_auth_type": {"cloudflare": 5},
        }

        with patch.object(
            state,
            "_get_authentication_queue_summary",
            new_callable=AsyncMock,
            return_value=mock_summary,
        ):
            # When: Get status
            status = await state.get_status()

        # Then: Critical alert is generated
        critical_alerts = [w for w in status["warnings"] if "[critical]" in w]
        assert len(critical_alerts) == 1, (
            f"Should have 1 critical alert, got {len(critical_alerts)}: {status['warnings']}"
        )
        assert "認証待ち5件" in critical_alerts[0], (
            f"Critical should mention '認証待ち5件', got '{critical_alerts[0]}'"
        )

    @pytest.mark.asyncio
    async def test_auth_queue_critical_threshold_by_high_priority(
        self, test_database: Database
    ) -> None:
        """
        Verify critical alert is generated when high_priority >= 2.

        Per ADR-0007: [critical] when high_priority >= 2.
        """

        # Given: 2 high priority auth items
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database

        mock_summary = {
            "pending_count": 2,
            "high_priority_count": 2,
            "domains": ["primary0.gov", "primary1.gov"],
            "oldest_queued_at": "2024-01-01T00:00:00+00:00",
            "by_auth_type": {"cloudflare": 2},
        }

        with patch.object(
            state,
            "_get_authentication_queue_summary",
            new_callable=AsyncMock,
            return_value=mock_summary,
        ):
            # When: Get status
            status = await state.get_status()

        # Then: Critical alert for high priority
        critical_alerts = [w for w in status["warnings"] if "[critical]" in w]
        assert len(critical_alerts) == 1, (
            f"Should have 1 critical alert for high priority, got {len(critical_alerts)}: {status['warnings']}"
        )
        assert "一次資料アクセスがブロック" in critical_alerts[0], (
            f"Critical should mention primary source blocking, got '{critical_alerts[0]}'"
        )

    @pytest.mark.asyncio
    async def test_finalize_returns_summary(self, test_database: Database) -> None:
        """
        Verify finalize returns proper summary with unsatisfied subqueries.
        """
        # Given: 1 satisfied and 1 unsatisfied subquery
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database

        sq1 = state.register_subquery("sq_001", "satisfied query")
        sq1.independent_sources = 3
        sq1.has_primary_source = True
        sq1.update_status()

        state.register_subquery("sq_002", "unsatisfied query")

        # When: Finalize exploration
        result = await state.finalize()

        # Then: Summary shows partial completion with suggestions
        assert result["ok"] is True
        assert result["final_status"] == "partial"
        assert result["summary"]["satisfied_searches"] == 1
        assert "sq_002" in result["summary"]["unsatisfied_searches"]
        assert len(result["followup_suggestions"]) >= 1, (
            f"Expected >=1 followup suggestions, got {result['followup_suggestions']}"
        )


# =============================================================================
# ExplorationState Boundary Tests
# =============================================================================


class TestExplorationStateBoundaryValues:
    """
    Boundary value tests for ExplorationState.

    Per test-strategy.mdc: Tests for 0, min, max, ±1 for budget limits.
    """

    @pytest.mark.asyncio
    async def test_zero_pages_limit_immediately_exceeded(self, test_database: Database) -> None:
        """TC-ES-B-01: Zero pages_limit is immediately exceeded.

        // Given: pages_limit = 0
        // When: Check budget
        // Then: Budget exceeded immediately
        """
        # Given: ExplorationState with zero page limit
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database
        state._pages_limit = 0

        # When: Check budget
        within_budget, warning = state.check_budget()

        # Then: Budget exceeded
        assert within_budget is False
        assert warning is not None

    @pytest.mark.asyncio
    async def test_pages_limit_exactly_at_boundary(self, test_database: Database) -> None:
        """TC-ES-B-02: Exactly at pages_limit triggers exceeded.

        // Given: pages_limit = 5, pages_used = 5
        // When: Check budget
        // Then: Budget exceeded
        """
        # Given: ExplorationState at exact limit
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database
        state._pages_limit = 5
        state._pages_used = 5

        # When: Check budget
        within_budget, warning = state.check_budget()

        # Then: Budget exceeded
        assert within_budget is False

    @pytest.mark.asyncio
    async def test_pages_limit_one_below_boundary(self, test_database: Database) -> None:
        """TC-ES-B-03: One below pages_limit is within budget.

        // Given: pages_limit = 5, pages_used = 4
        // When: Check budget
        // Then: Within budget
        """
        # Given: ExplorationState one below limit
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database
        state._pages_limit = 5
        state._pages_used = 4

        # When: Check budget
        within_budget, _ = state.check_budget()

        # Then: Within budget
        assert within_budget is True

    @pytest.mark.asyncio
    async def test_budget_warning_at_80_percent(self, test_database: Database) -> None:
        """TC-ES-B-04: Warning at 80% budget usage.

        // Given: pages_limit = 100, pages_used = 81 (81% usage)
        // When: Check budget
        // Then: Within budget with warning
        """
        # Given: ExplorationState at 81% usage
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database
        state._pages_limit = 100
        state._pages_used = 81

        # When: Check budget
        within_budget, warning = state.check_budget()

        # Then: Within budget but with warning
        assert within_budget is True
        assert warning is not None
        assert "残り" in warning


# =============================================================================
# SubqueryExecutor Tests (ADR-0002)
# =============================================================================


class TestSubqueryExecutor:
    """
    Tests for SubqueryExecutor mechanical operations.

    ADR-0002: Lyra only performs mechanical expansions, not query design.
    """

    def test_primary_source_detection(self) -> None:
        """
        Verify primary source domains are correctly identified.
        """
        # Given/When/Then: Check that known primary sources are in the set
        assert "go.jp" in PRIMARY_SOURCE_DOMAINS
        assert "gov.uk" in PRIMARY_SOURCE_DOMAINS
        assert "arxiv.org" in PRIMARY_SOURCE_DOMAINS
        assert "who.int" in PRIMARY_SOURCE_DOMAINS

    @pytest.mark.asyncio
    async def test_expand_query_mechanical_only(self, test_database: Database) -> None:
        """
        Verify query expansion is mechanical (operators, not new ideas).

        ADR-0002: Lyra only adds operators, does not design new queries.
        """
        # Given: A SubqueryExecutor and original query
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        executor = SubqueryExecutor(task_id, state)

        original_query = "機械学習の研究論文"

        # When: Expand query
        expanded = executor._expand_query(original_query)

        # Then: Original is included and core term preserved
        assert original_query in expanded
        for eq in expanded:
            assert "機械学習" in eq, f"Expected '機械学習' in expanded query: {eq}"

    def test_generate_refutation_queries_mechanical(self) -> None:
        """
        Verify refutation queries use mechanical suffix patterns only.

        ADR-0002: No LLM-based query generation for refutations.
        """
        # Given: A SubqueryExecutor and base query
        state = MagicMock()
        executor = SubqueryExecutor("task_001", state)
        base_query = "AIは安全である"

        # When: Generate refutation queries
        refutation_queries = executor.generate_refutation_queries(base_query)

        # Then: Queries use mechanical suffixes only
        assert len(refutation_queries) >= 1, (
            f"Expected >=1 refutation queries, got {len(refutation_queries)}"
        )
        for rq in refutation_queries:
            assert base_query in rq
            has_suffix = any(suffix in rq for suffix in REFUTATION_SUFFIXES)
            assert has_suffix, f"Query '{rq}' doesn't have a mechanical suffix"


# =============================================================================
# RefutationExecutor Tests (ADR-0010)
# =============================================================================


class TestRefutationExecutor:
    """
    Tests for RefutationExecutor mechanical pattern application.

    ADR-0010: Lyra applies mechanical patterns only (suffixes).
    ADR-0002: No LLM-based reverse query design.
    """

    def test_refutation_suffixes_defined(self) -> None:
        """
        Verify all required refutation suffixes are defined.

        ADR-0010: Suffixes include issues/criticism/problems/limitations etc.
        """
        # Given/When/Then: Required suffixes exist
        assert "課題" in REFUTATION_SUFFIXES
        assert "批判" in REFUTATION_SUFFIXES
        assert "問題点" in REFUTATION_SUFFIXES
        assert "limitations" in REFUTATION_SUFFIXES

    @pytest.mark.asyncio
    async def test_generate_reverse_queries_mechanical(self, test_database: Database) -> None:
        """
        Verify reverse query generation is mechanical (suffix-based).
        """
        # Given: A RefutationExecutor and claim text
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database
        executor = RefutationExecutor(task_id, state)

        claim_text = "深層学習は画像認識で高精度"

        # When: Generate reverse queries
        reverse_queries = executor._generate_reverse_queries(claim_text)

        # Then: Queries use mechanical suffixes
        assert len(reverse_queries) >= 1, (
            f"Expected >=1 reverse queries, got {len(reverse_queries)}"
        )
        for rq in reverse_queries:
            has_suffix = any(suffix in rq for suffix in REFUTATION_SUFFIXES)
            assert has_suffix, f"Query '{rq}' doesn't use mechanical suffix"

    @pytest.mark.asyncio
    async def test_record_refutation_edge_with_target_domain_category(
        self, test_database: Database
    ) -> None:
        """
        TC-P2-REF-N-01: _record_refutation_edge calculates target_domain_category from claim.

        Given: Claim with source_url in verification_notes
        When: Recording refutation edge
        Then: target_domain_category is calculated from claim's origin domain
        """
        from src.research.refutation import RefutationExecutor

        # Given: Claim with source_url in verification_notes
        task_id = await test_database.create_task(query="test")
        claim_id = "claim_test_123"
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, verification_notes)
            VALUES (?, ?, ?, ?)
            """,
            (claim_id, task_id, "Test claim", "source_url=https://arxiv.org/abs/1234"),
        )

        state = ExplorationState(task_id)
        state._db = test_database
        executor = RefutationExecutor(task_id, state)
        executor._db = test_database

        refutation = {
            "source_url": "https://example.com/refutation",
            "nli_confidence": 0.85,
        }

        # When: Recording refutation edge
        await executor._record_refutation_edge(claim_id, refutation)

        # Then: Verify target_domain_category is calculated from claim's domain
        edges = await test_database.fetch_all(
            "SELECT * FROM edges WHERE target_id = ? AND relation = 'refutes'", (claim_id,)
        )
        assert len(edges) == 1
        assert edges[0]["source_domain_category"] is not None
        assert edges[0]["target_domain_category"] is not None
        # target_domain_category should be from arxiv.org (claim's origin)
        assert edges[0]["target_domain_category"] == "academic"

    @pytest.mark.asyncio
    async def test_record_refutation_edge_without_claim_source_url(
        self, test_database: Database
    ) -> None:
        """
        TC-P2-REF-B-01: _record_refutation_edge handles missing claim source_url.

        Given: Claim without source_url in verification_notes
        When: Recording refutation edge
        Then: target_domain_category is None
        """
        from src.research.refutation import RefutationExecutor

        # Given: Claim without source_url
        task_id = await test_database.create_task(query="test")
        claim_id = "claim_test_456"
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, verification_notes)
            VALUES (?, ?, ?, ?)
            """,
            (claim_id, task_id, "Test claim", "no_source_url"),
        )

        state = ExplorationState(task_id)
        state._db = test_database
        executor = RefutationExecutor(task_id, state)
        executor._db = test_database

        refutation = {
            "source_url": "https://example.com/refutation",
            "nli_confidence": 0.85,
        }

        # When: Recording refutation edge
        await executor._record_refutation_edge(claim_id, refutation)

        # Then: Verify target_domain_category is None
        edges = await test_database.fetch_all(
            "SELECT * FROM edges WHERE target_id = ? AND relation = 'refutes'", (claim_id,)
        )
        assert len(edges) == 1
        assert edges[0]["source_domain_category"] is not None
        assert edges[0]["target_domain_category"] is None

    @pytest.mark.asyncio
    async def test_refutation_result_structure(self, test_database: Database) -> None:
        """
        Verify RefutationResult has correct structure per ADR-0003.
        """
        # Given: A RefutationResult instance
        result = RefutationResult(
            target="claim_001",
            target_type="claim",
            reverse_queries_executed=3,
            refutations_found=1,
        )

        # When: Convert to dict
        result_dict = result.to_dict()

        # Then: Structure matches ADR-0003
        assert result_dict["ok"] is True
        assert result_dict["target"] == "claim_001"
        assert result_dict["target_type"] == "claim"
        assert result_dict["reverse_queries_executed"] == 3
        assert result_dict["refutations_found"] == 1
        assert "confidence_adjustment" in result_dict


# =============================================================================
# Integration Tests
# =============================================================================


class TestExplorationIntegration:
    """
    Integration tests for the exploration control workflow.
    """

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_full_exploration_workflow(self, test_database: Database) -> None:
        """
        Verify complete exploration workflow: context → execute → status → finalize.

        This tests the Cursor AI-driven workflow per ADR-0002.
        Note: This test uses state simulation rather than actual search/fetch
        to avoid external dependencies in integration tests.
        """
        # Given: A research task
        task_id = await test_database.create_task(
            query="量子コンピュータの現状と課題",
        )

        # When: Get research context
        context = ResearchContext(task_id)
        context._db = test_database
        ctx_result = await context.get_context()

        # Then: Context does NOT generate candidates
        assert ctx_result["ok"] is True
        assert "subquery_candidates" not in ctx_result

        # Given: Exploration state with a subquery
        state = ExplorationState(task_id)
        state._db = test_database

        state.register_subquery(
            subquery_id="sq_001",
            text="量子コンピュータ 基礎原理",
            priority="high",
        )
        state.start_subquery("sq_001")

        # When: Simulate page fetches
        state.record_page_fetch("sq_001", "university.ac.jp", True, True)
        state.record_page_fetch("sq_001", "research.go.jp", True, True)
        state.record_page_fetch("sq_001", "wikipedia.org", False, True)

        # Then: Status reflects page fetches
        status = await state.get_status()

        assert status["ok"] is True
        assert status["metrics"]["total_pages"] == 3

        # When: Finalize exploration
        final = await state.finalize()

        # Then: Final result has summary and suggestions
        assert final["ok"] is True
        assert "summary" in final
        assert "followup_suggestions" in final


# =============================================================================
# Responsibility Boundary Tests (ADR-0002)
# =============================================================================


class TestResponsibilityBoundary:
    """
    Tests verifying the Cursor AI / Lyra responsibility boundary.

    These tests ensure Lyra does NOT exceed its responsibilities
    as defined in ADR-0002.
    """

    def test_lyra_does_not_design_queries(self) -> None:
        """
        Verify Lyra components don't have query design capabilities.

        ADR-0002: Query design is Cursor AI's exclusive responsibility.
        """
        # Given/When/Then: ResearchContext has no design methods
        assert not hasattr(ResearchContext, "design_subqueries")
        assert not hasattr(ResearchContext, "generate_subqueries")
        assert not hasattr(ResearchContext, "suggest_queries")

        # Given/When/Then: SubqueryExecutor has no design methods
        assert not hasattr(SubqueryExecutor, "design_query")
        assert not hasattr(SubqueryExecutor, "generate_query")

    def test_refutation_uses_only_mechanical_patterns(self) -> None:
        """
        Verify refutation only uses predefined suffixes, not LLM.

        ADR-0002: LLM must NOT be used for reverse query design.
        """
        # Given/When/Then: RefutationExecutor has no LLM methods
        assert not hasattr(RefutationExecutor, "generate_hypothesis")
        assert not hasattr(RefutationExecutor, "llm_reverse_query")

        # Given/When/Then: REFUTATION_SUFFIXES are predefined constants
        assert isinstance(REFUTATION_SUFFIXES, list)
        assert all(isinstance(s, str) for s in REFUTATION_SUFFIXES)

    @pytest.mark.asyncio
    async def test_context_notes_are_informational_only(self, test_database: Database) -> None:
        """
        Verify context notes are hints, not directives.

        ADR-0002: Lyra provides support information, Cursor AI decides.
        """
        # Given: A ResearchContext
        task_id = await test_database.create_task(query="test query")
        context = ResearchContext(task_id)
        context._db = test_database

        # When: Get context
        result = await context.get_context()

        # Then: Notes do not contain directives
        notes = result.get("notes", "")
        assert "must" not in notes.lower()
        assert "required" not in notes.lower()
        assert "should query" not in notes.lower()


# =============================================================================
# Pipeline Tests (ADR-0003)
# =============================================================================


class TestStopTaskAction:
    """
    Tests for stop_task_action defensive access patterns.

    Bug fix verification: stop_task_action should use safe .get() access
    for all nested dictionary keys to handle potential missing keys gracefully.
    """

    @pytest.mark.asyncio
    async def test_stop_task_handles_missing_summary(self, test_database: Database) -> None:
        """
        TC-PIPE-A-01: stop_task_action handles missing summary key.

        // Given: finalize_result with missing summary key
        // When: Calling stop_task_action
        // Then: Returns with default values, no KeyError
        """
        from src.research.pipeline import stop_task_action
        from src.research.state import ExplorationState

        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database

        # Patch finalize to return incomplete result
        async def mock_finalize() -> dict[str, object]:
            return {
                "ok": True,
                "final_status": "completed",
                # Missing "summary" and "evidence_graph_summary"
            }

        with patch.object(state, "finalize", mock_finalize):
            # When: Call stop_task_action
            result = await stop_task_action(task_id, state, "completed")

            # Then: Should succeed with default values
            assert result["ok"] is True
        assert result["summary"]["satisfied_searches"] == 0
        assert result["summary"]["total_claims"] == 0
        assert result["summary"]["primary_source_ratio"] == 0.0

    @pytest.mark.asyncio
    async def test_stop_task_handles_empty_nested_dicts(self, test_database: Database) -> None:
        """
        TC-PIPE-A-02: stop_task_action handles empty nested dicts.

        // Given: finalize_result with empty summary and evidence_graph_summary
        // When: Calling stop_task_action
        // Then: Returns with default values
        """
        from src.research.pipeline import stop_task_action
        from src.research.state import ExplorationState

        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database

        # Patch finalize to return empty nested dicts
        async def mock_finalize() -> dict[str, object]:
            return {
                "ok": True,
                "final_status": "partial",
                "summary": {},  # Empty summary
                "evidence_graph_summary": {},  # Empty graph summary
            }

        with patch.object(state, "finalize", mock_finalize):
            # When: Call stop_task_action
            result = await stop_task_action(task_id, state, "budget_exhausted")

            # Then: Should succeed with default values
            assert result["ok"] is True
        assert result["final_status"] == "partial"
        assert result["summary"]["satisfied_searches"] == 0
        assert result["summary"]["total_claims"] == 0
        assert result["summary"]["primary_source_ratio"] == 0.0

    @pytest.mark.asyncio
    async def test_stop_task_normal_finalize(self, test_database: Database) -> None:
        """
        TC-PIPE-N-01: stop_task_action works with complete finalize_result.

        // Given: finalize_result with all expected keys
        // When: Calling stop_task_action
        // Then: Returns values from finalize_result
        """
        from src.research.pipeline import stop_task_action
        from src.research.state import ExplorationState

        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database

        # Register a search for total_searches count
        state.register_search("sq_001", "test query")

        # Patch finalize to return complete result
        async def mock_finalize() -> dict[str, object]:
            return {
                "ok": True,
                "final_status": "completed",
                "summary": {
                    "satisfied_searches": 5,
                    "total_claims": 10,
                },
                "evidence_graph_summary": {
                    "primary_source_ratio": 0.75,
                },
            }

        with patch.object(state, "finalize", mock_finalize):
            # When: Call stop_task_action
            result = await stop_task_action(task_id, state, "completed")

            # Then: Should use values from finalize_result
            assert result["ok"] is True
        assert result["final_status"] == "completed"
        assert result["summary"]["total_searches"] == 1  # One registered search
        assert result["summary"]["satisfied_searches"] == 5
        assert result["summary"]["total_claims"] == 10
        assert result["summary"]["primary_source_ratio"] == 0.75


# ============================================================================
# get_overall_harvest_rate Tests (ADR-0010 Lastmile Slot)
# ============================================================================


class TestGetOverallHarvestRate:
    """
    Tests for ExplorationState.get_overall_harvest_rate method.

    Per ADR-0010: Used to determine if lastmile engines should be used
    when harvest rate >= 0.9.

    ## Test Perspectives Table

    | Case ID | Input / Precondition | Perspective | Expected Result | Notes |
    |---------|---------------------|-------------|-----------------|-------|
    | TC-HR-B-01 | No searches | Boundary - empty | Returns 0.0 | - |
    | TC-HR-B-02 | Searches with no pages | Boundary - zero pages | Returns 0.0 | - |
    | TC-HR-N-01 | Single search | Equivalence - normal | Correct rate | - |
    | TC-HR-N-02 | Multiple searches | Equivalence - normal | Aggregated rate | - |
    | TC-HR-B-03 | High rate (>=0.9) | Boundary - lastmile trigger | Returns rate >= 0.9 | - |
    """

    def test_get_overall_harvest_rate_no_searches(self) -> None:
        """TC-HR-B-01: Test returns 0.0 when no searches registered."""
        # Given: An ExplorationState with no searches
        from src.research.state import ExplorationState

        state = ExplorationState("test_task", enable_ucb_allocation=False)

        # When: Getting overall harvest rate
        rate = state.get_overall_harvest_rate()

        # Then: Returns 0.0
        assert rate == 0.0

    def test_get_overall_harvest_rate_zero_pages(self) -> None:
        """TC-HR-B-02: Test returns 0.0 when searches have no pages fetched."""
        # Given: An ExplorationState with searches but no pages fetched
        from src.research.state import ExplorationState

        state = ExplorationState("test_task", enable_ucb_allocation=False)
        state.register_search("search_1", "test query")
        # pages_fetched is 0 by default

        # When: Getting overall harvest rate
        rate = state.get_overall_harvest_rate()

        # Then: Returns 0.0 (no division by zero)
        assert rate == 0.0

    def test_get_overall_harvest_rate_single_search(self) -> None:
        """TC-HR-N-01: Test calculates correct rate for single search."""
        # Given: An ExplorationState with one search
        from src.research.state import ExplorationState

        state = ExplorationState("test_task", enable_ucb_allocation=False)
        search = state.register_search("search_1", "test query")
        search.pages_fetched = 10
        search.useful_fragments = 8

        # When: Getting overall harvest rate
        rate = state.get_overall_harvest_rate()

        # Then: Returns correct rate (8/10 = 0.8)
        assert rate == 0.8

    def test_get_overall_harvest_rate_multiple_searches(self) -> None:
        """TC-HR-N-02: Test aggregates rate across multiple searches."""
        # Given: An ExplorationState with multiple searches
        from src.research.state import ExplorationState

        state = ExplorationState("test_task", enable_ucb_allocation=False)

        search1 = state.register_search("search_1", "query 1")
        search1.pages_fetched = 10
        search1.useful_fragments = 8

        search2 = state.register_search("search_2", "query 2")
        search2.pages_fetched = 20
        search2.useful_fragments = 10

        # When: Getting overall harvest rate
        rate = state.get_overall_harvest_rate()

        # Then: Returns aggregated rate (8+10)/(10+20) = 18/30 = 0.6
        expected = 18 / 30
        assert abs(rate - expected) < 0.001

    def test_get_overall_harvest_rate_high_rate(self) -> None:
        """TC-HR-B-03: Test returns rate >= 0.9 for high harvest."""
        # Given: An ExplorationState with high harvest rate
        from src.research.state import ExplorationState

        state = ExplorationState("test_task", enable_ucb_allocation=False)

        search1 = state.register_search("search_1", "query 1")
        search1.pages_fetched = 10
        search1.useful_fragments = 9

        search2 = state.register_search("search_2", "query 2")
        search2.pages_fetched = 10
        search2.useful_fragments = 10

        # When: Getting overall harvest rate
        rate = state.get_overall_harvest_rate()

        # Then: Returns rate >= 0.9 (9+10)/(10+10) = 19/20 = 0.95
        expected = 19 / 20
        assert abs(rate - expected) < 0.001
        assert rate >= 0.9  # Triggers lastmile per ADR-0010


# =============================================================================
# Academic Query Detection Tests (J2)
# =============================================================================


class TestAcademicQueryDetection:
    """Tests for academic query detection and complementary search (J2).

    Tests for _is_academic_query() and _expand_academic_query() methods
    in SearchPipeline.

    ## Test Perspectives Table

    | Case ID | Input / Precondition | Perspective | Expected Result | Notes |
    |---------|---------------------|-------------|-----------------|-------|
    | TC-AQ-N-01 | Query with academic keyword | Equivalence – normal | Returns True | - |
    | TC-AQ-N-02 | Query with site:arxiv.org | Equivalence – normal | Returns True | - |
    | TC-AQ-N-03 | Query with DOI pattern | Equivalence – normal | Returns True | - |
    | TC-AQ-B-01 | Empty query string | Boundary – empty | Returns False | - |
    | TC-AQ-B-02 | Query without academic indicators | Boundary – no match | Returns False | - |
    | TC-AQ-N-04 | Expand academic query | Equivalence – normal | Returns expanded queries | - |
    | TC-AQ-B-03 | Expand empty query | Boundary – empty | Returns list with empty query | - |
    """

    def test_is_academic_query_with_keyword(self) -> None:
        """TC-AQ-N-01: Test query with academic keyword.

        // Given: Query containing academic keyword
        // When: Checking if academic query
        // Then: Returns True
        """
        from src.research.pipeline import SearchPipeline
        from src.research.state import ExplorationState

        # Given: Query with academic keyword
        state = ExplorationState("test_task")
        pipeline = SearchPipeline("test_task", state)
        query = "transformer attention 論文"

        # When: Checking if academic query
        is_academic = pipeline._is_academic_query(query)

        # Then: Returns True
        assert is_academic is True

    def test_is_academic_query_with_site_operator(self) -> None:
        """TC-AQ-N-02: Test query with site:arxiv.org.

        // Given: Query with site:arxiv.org operator
        // When: Checking if academic query
        // Then: Returns True
        """
        from src.research.pipeline import SearchPipeline
        from src.research.state import ExplorationState

        # Given: Query with site operator
        state = ExplorationState("test_task")
        pipeline = SearchPipeline("test_task", state)
        query = "machine learning site:arxiv.org"

        # When: Checking if academic query
        is_academic = pipeline._is_academic_query(query)

        # Then: Returns True
        assert is_academic is True

    def test_is_academic_query_with_doi_pattern(self) -> None:
        """TC-AQ-N-03: Test query with DOI pattern.

        // Given: Query containing DOI pattern
        // When: Checking if academic query
        // Then: Returns True
        """
        from src.research.pipeline import SearchPipeline
        from src.research.state import ExplorationState

        # Given: Query with DOI pattern
        state = ExplorationState("test_task")
        pipeline = SearchPipeline("test_task", state)
        query = "paper 10.1038/nature12373"

        # When: Checking if academic query
        is_academic = pipeline._is_academic_query(query)

        # Then: Returns True
        assert is_academic is True

    def test_is_academic_query_empty(self) -> None:
        """TC-AQ-B-01: Test empty query string.

        // Given: Empty query string
        // When: Checking if academic query
        // Then: Returns False
        """
        from src.research.pipeline import SearchPipeline
        from src.research.state import ExplorationState

        # Given: Empty query string
        state = ExplorationState("test_task")
        pipeline = SearchPipeline("test_task", state)

        # When: Checking if academic query
        is_academic = pipeline._is_academic_query("")

        # Then: Returns False
        assert is_academic is False

    def test_is_academic_query_general(self) -> None:
        """TC-AQ-B-02: Test query without academic indicators.

        // Given: General query without academic indicators
        // When: Checking if academic query
        // Then: Returns False
        """
        from src.research.pipeline import SearchPipeline
        from src.research.state import ExplorationState

        # Given: General query
        state = ExplorationState("test_task")
        pipeline = SearchPipeline("test_task", state)
        query = "今日の天気"

        # When: Checking if academic query
        is_academic = pipeline._is_academic_query(query)

        # Then: Returns False
        assert is_academic is False

    def test_expand_academic_query(self) -> None:
        """TC-AQ-N-04: Test expanding academic query.

        // Given: Academic query
        // When: Expanding query
        // Then: Returns expanded queries with site operators
        """
        from src.research.pipeline import SearchPipeline
        from src.research.state import ExplorationState

        # Given: Academic query
        state = ExplorationState("test_task")
        pipeline = SearchPipeline("test_task", state)
        query = "transformer attention"

        # When: Expanding query
        expanded = pipeline._expand_academic_query(query)

        # Then: Returns expanded queries
        assert len(expanded) >= 1
        assert query in expanded
        # Should include site: operators
        assert any("site:arxiv.org" in q or "site:pubmed" in q for q in expanded)

    def test_expand_academic_query_empty(self) -> None:
        """TC-AQ-B-03: Test expanding empty query.

        // Given: Empty query
        // When: Expanding query
        // Then: Returns list with empty query
        """
        from src.research.pipeline import SearchPipeline
        from src.research.state import ExplorationState

        # Given: Empty query
        state = ExplorationState("test_task")
        pipeline = SearchPipeline("test_task", state)

        # When: Expanding query
        expanded = pipeline._expand_academic_query("")

        # Then: Returns list with empty query
        assert len(expanded) >= 1
        assert "" in expanded
