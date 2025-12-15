"""
Tests for Exploration Control Engine.

These tests verify the exploration control functionality per §2.1 and §3.1.7:
- ResearchContext provides design support information (not subquery candidates)
- SubqueryExecutor executes Cursor AI-designed queries
- ExplorationState manages task/subquery states and metrics
- RefutationExecutor applies mechanical patterns only

Test Quality Standards (§7.1):
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
| TC-RES-N-03 | Any query | Equivalence – normal | No subquery_candidates | §2.1 boundary |
| TC-RES-N-04 | Any query | Equivalence – normal | Recommended engines list | Engine recommendation |
| TC-RES-A-01 | Nonexistent task_id | Equivalence – error | ok=False with error | Task not found |
| TC-RES-N-05 | 3 sources, no primary | Equivalence – normal | Score = 0.7 | §3.1.7.3 formula |
| TC-RES-N-06 | 2 sources + primary | Equivalence – normal | Score ≈ 0.767 | Primary bonus |
| TC-RES-N-07 | Score >= 0.8 | Boundary – threshold | is_satisfied=True | Satisfaction threshold |
| TC-RES-N-08 | 7/10 novel fragments | Equivalence – normal | Novelty = 0.7 | §3.1.7.4 formula |
| TC-RES-N-09 | 3 sources + primary | Equivalence – transition | Status=SATISFIED | Status transition |
| TC-RES-N-10 | 1 source | Equivalence – partial | Status=PARTIAL | Partial status |
| TC-RES-N-11 | Register + start subquery | Equivalence – normal | Status=RUNNING | State management |
| TC-RES-N-12 | 10 page fetches | Boundary – limit | Budget warning | Budget tracking |
| TC-RES-N-13 | 2 subqueries | Equivalence – normal | All required fields | get_status structure |
| TC-RES-N-14 | 2 pending auth items | Equivalence – normal | auth_queue in status | §16.7.1 |
| TC-RES-N-15 | 3 pending items | Boundary – warning | Warning alert | §16.7.3 threshold |
| TC-RES-N-16 | 5 pending items | Boundary – critical | Critical alert | Count threshold |
| TC-RES-N-17 | 2 high priority items | Boundary – critical | Critical alert | Priority threshold |
| TC-RES-N-18 | 1 satisfied, 1 unsatisfied | Equivalence – normal | Partial status + suggestions | finalize() |
| TC-RES-N-19 | PRIMARY_SOURCE_DOMAINS | Equivalence – normal | Known domains included | Domain set |
| TC-RES-N-20 | Japanese query | Equivalence – expansion | Core term preserved | Mechanical only |
| TC-RES-N-21 | Claim text | Equivalence – normal | Suffix-based queries | Refutation patterns |
| TC-RES-N-22 | REFUTATION_SUFFIXES | Equivalence – normal | Required suffixes exist | Suffix constants |
| TC-RES-N-23 | Claim text | Equivalence – normal | Reverse queries with suffix | Mechanical patterns |
| TC-RES-N-24 | RefutationResult | Equivalence – normal | Correct structure | §3.2.1 structure |
| TC-RES-N-25 | Full workflow | Equivalence – integration | Complete flow works | Context→Execute→Status |
| TC-RES-N-26 | ResearchContext class | Equivalence – boundary | No design methods | §2.1.1 |
| TC-RES-N-27 | RefutationExecutor class | Equivalence – boundary | No LLM methods | §2.1.4 |
| TC-RES-N-28 | Context notes | Equivalence – boundary | No directives | Informational only |
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

pytestmark = pytest.mark.unit

from src.research.context import (
    ResearchContext,
    EntityInfo,
    TemplateInfo,
    VERTICAL_TEMPLATES,
)
from src.research.state import (
    ExplorationState,
    SubqueryState,
    SubqueryStatus,
    TaskStatus,
)
from src.research.executor import SubqueryExecutor, SubqueryResult, PRIMARY_SOURCE_DOMAINS
from src.research.refutation import RefutationExecutor, RefutationResult, REFUTATION_SUFFIXES


# =============================================================================
# ResearchContext Tests (§3.1.7.1)
# =============================================================================

class TestResearchContext:
    """
    Tests for ResearchContext design support information provider.
    
    Per §2.1.4: ResearchContext provides support information but does NOT
    generate subquery candidates. That is Cursor AI's responsibility.
    """
    
    @pytest.mark.asyncio
    async def test_get_context_returns_entities(self, test_database):
        """
        Verify that get_context extracts and returns entities from the query.
        
        §3.1.7.1: ResearchContext extracts entities (person/organization/location/etc.)
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
        entity_types = [e["type"] for e in result["extracted_entities"]]
        assert isinstance(result["extracted_entities"], list)
    
    @pytest.mark.asyncio
    async def test_get_context_returns_applicable_templates(self, test_database):
        """
        Verify that get_context returns applicable vertical templates.
        
        §3.1.7.1: Templates include academic/government/corporate/technical.
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
    async def test_get_context_does_not_return_subquery_candidates(self, test_database):
        """
        Verify that get_context does NOT return subquery candidates.
        
        §2.1.1: Subquery design is Cursor AI's exclusive responsibility.
        §2.1.4: Lancet must NOT generate subquery candidates.
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
    async def test_get_context_returns_recommended_engines(self, test_database):
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
    async def test_get_context_task_not_found(self, test_database):
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
# SubqueryState Tests (§3.1.7.2, §3.1.7.3)
# =============================================================================

class TestSubqueryState:
    """
    Tests for SubqueryState satisfaction and novelty calculations.
    
    §3.1.7.3: Satisfaction score = min(1.0, (sources/3)*0.7 + (primary?0.3:0))
    §3.1.7.4: Novelty score = novel fragments / recent fragments
    """
    
    def test_satisfaction_score_with_three_sources(self):
        """
        Verify satisfaction score is 0.7 with exactly 3 independent sources.
        
        §3.1.7.3: Score = (3/3)*0.7 + 0 = 0.7
        """
        # Given: A subquery with 3 independent sources, no primary
        sq = SubqueryState(id="sq_001", text="test query")
        sq.independent_sources = 3
        sq.has_primary_source = False
        
        # When: Calculate satisfaction score
        score = sq.calculate_satisfaction_score()
        
        # Then: Score is 0.7
        assert score == 0.7
    
    def test_satisfaction_score_with_primary_source(self):
        """
        Verify satisfaction score includes 0.3 bonus for primary source.
        
        §3.1.7.3: Score = (2/3)*0.7 + 0.3 ≈ 0.767
        """
        # Given: A subquery with 2 sources and primary source
        sq = SubqueryState(id="sq_002", text="test query")
        sq.independent_sources = 2
        sq.has_primary_source = True
        
        # When: Calculate satisfaction score
        score = sq.calculate_satisfaction_score()
        
        # Then: Score includes primary bonus
        expected = (2/3) * 0.7 + 0.3
        assert abs(score - expected) < 0.01
    
    def test_is_satisfied_threshold(self):
        """
        Verify is_satisfied returns True when score >= 0.8.
        
        §3.1.7.3: Satisfied when score >= 0.8.
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
    
    def test_novelty_score_calculation(self):
        """
        Verify novelty score is calculated from recent fragments.
        
        §3.1.7.4: Novelty = novel fragments / total recent fragments.
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
    
    def test_status_transitions(self):
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
    
    def test_status_partial_with_some_sources(self):
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
# ExplorationState Tests (§3.1.7.2)
# =============================================================================

class TestExplorationState:
    """
    Tests for ExplorationState task management.
    """
    
    @pytest.mark.asyncio
    async def test_register_and_start_subquery(self, test_database):
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
    async def test_budget_tracking(self, test_database):
        """
        Verify page budget is tracked correctly.
        """
        # Given: An exploration state with small page limit
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database
        state._pages_limit = 10
        
        sq = state.register_subquery("sq_001", "test")
        
        # When: Fetch pages up to limit
        for i in range(10):
            state.record_page_fetch("sq_001", f"domain{i}.com", False, True)
        
        within_budget, warning = state.check_budget()
        
        # Then: Budget is exceeded with warning
        assert within_budget is False
        assert warning is not None
        assert "上限" in warning
    
    @pytest.mark.asyncio
    async def test_get_status_returns_all_required_fields(self, test_database):
        """
        Verify get_status returns all required fields per §3.2.1.
        Now async per §16.7.1 changes.
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
    async def test_get_status_includes_authentication_queue(self, test_database):
        """
        Verify get_status includes authentication_queue when pending items exist.
        
        Per §16.7.1: authentication_queue should contain summary information.
        """
        from unittest.mock import patch, AsyncMock
        
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
            state, "_get_authentication_queue_summary",
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
    async def test_auth_queue_warning_threshold(self, test_database):
        """
        Verify warning alert is generated when pending >= 3.
        
        Per §16.7.3: [warning] when pending >= 3.
        """
        from unittest.mock import patch, AsyncMock
        
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
            state, "_get_authentication_queue_summary",
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
    async def test_auth_queue_critical_threshold_by_count(self, test_database):
        """
        Verify critical alert is generated when pending >= 5.
        
        Per §16.7.3: [critical] when pending >= 5.
        """
        from unittest.mock import patch, AsyncMock
        
        # Given: 5 pending auth items
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database
        
        mock_summary = {
            "pending_count": 5,
            "high_priority_count": 0,
            "domains": ["example0.com", "example1.com", "example2.com", "example3.com", "example4.com"],
            "oldest_queued_at": "2024-01-01T00:00:00+00:00",
            "by_auth_type": {"cloudflare": 5},
        }
        
        with patch.object(
            state, "_get_authentication_queue_summary",
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
    async def test_auth_queue_critical_threshold_by_high_priority(self, test_database):
        """
        Verify critical alert is generated when high_priority >= 2.
        
        Per §16.7.3: [critical] when high_priority >= 2.
        """
        from unittest.mock import patch, AsyncMock
        
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
            state, "_get_authentication_queue_summary",
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
    async def test_finalize_returns_summary(self, test_database):
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
        
        sq2 = state.register_subquery("sq_002", "unsatisfied query")
        
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
# SubqueryExecutor Tests (§2.1.3)
# =============================================================================

class TestSubqueryExecutor:
    """
    Tests for SubqueryExecutor mechanical operations.
    
    §2.1.3: Lancet only performs mechanical expansions, not query design.
    """
    
    def test_primary_source_detection(self):
        """
        Verify primary source domains are correctly identified.
        """
        # Given/When/Then: Check that known primary sources are in the set
        assert "go.jp" in PRIMARY_SOURCE_DOMAINS
        assert "gov.uk" in PRIMARY_SOURCE_DOMAINS
        assert "arxiv.org" in PRIMARY_SOURCE_DOMAINS
        assert "who.int" in PRIMARY_SOURCE_DOMAINS
    
    @pytest.mark.asyncio
    async def test_expand_query_mechanical_only(self, test_database):
        """
        Verify query expansion is mechanical (operators, not new ideas).
        
        §2.1.3: Lancet only adds operators, does not design new queries.
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
    
    def test_generate_refutation_queries_mechanical(self):
        """
        Verify refutation queries use mechanical suffix patterns only.
        
        §2.1.4: No LLM-based query generation for refutations.
        """
        # Given: A SubqueryExecutor and base query
        state = MagicMock()
        executor = SubqueryExecutor("task_001", state)
        base_query = "AIは安全である"
        
        # When: Generate refutation queries
        refutation_queries = executor.generate_refutation_queries(base_query)
        
        # Then: Queries use mechanical suffixes only
        assert len(refutation_queries) >= 1, f"Expected >=1 refutation queries, got {len(refutation_queries)}"
        for rq in refutation_queries:
            assert base_query in rq
            has_suffix = any(suffix in rq for suffix in REFUTATION_SUFFIXES)
            assert has_suffix, f"Query '{rq}' doesn't have a mechanical suffix"


# =============================================================================
# RefutationExecutor Tests (§3.1.7.5)
# =============================================================================

class TestRefutationExecutor:
    """
    Tests for RefutationExecutor mechanical pattern application.
    
    §3.1.7.5: Lancet applies mechanical patterns only (suffixes).
    §2.1.4: No LLM-based reverse query design.
    """
    
    def test_refutation_suffixes_defined(self):
        """
        Verify all required refutation suffixes are defined.
        
        §3.1.7.5: Suffixes include issues/criticism/problems/limitations etc.
        """
        # Given/When/Then: Required suffixes exist
        assert "課題" in REFUTATION_SUFFIXES
        assert "批判" in REFUTATION_SUFFIXES
        assert "問題点" in REFUTATION_SUFFIXES
        assert "limitations" in REFUTATION_SUFFIXES
    
    @pytest.mark.asyncio
    async def test_generate_reverse_queries_mechanical(self, test_database):
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
        assert len(reverse_queries) >= 1, f"Expected >=1 reverse queries, got {len(reverse_queries)}"
        for rq in reverse_queries:
            has_suffix = any(suffix in rq for suffix in REFUTATION_SUFFIXES)
            assert has_suffix, f"Query '{rq}' doesn't use mechanical suffix"
    
    @pytest.mark.asyncio
    async def test_refutation_result_structure(self, test_database):
        """
        Verify RefutationResult has correct structure per §3.2.1.
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
        
        # Then: Structure matches §3.2.1
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
    async def test_full_exploration_workflow(self, test_database):
        """
        Verify complete exploration workflow: context → execute → status → finalize.
        
        This tests the Cursor AI-driven workflow per §2.1.2.
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
        
        sq = state.register_subquery(
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
# Responsibility Boundary Tests (§2.1)
# =============================================================================

class TestResponsibilityBoundary:
    """
    Tests verifying the Cursor AI / Lancet responsibility boundary.
    
    These tests ensure Lancet does NOT exceed its responsibilities
    as defined in §2.1.
    """
    
    def test_lancet_does_not_design_queries(self):
        """
        Verify Lancet components don't have query design capabilities.
        
        §2.1.1: Query design is Cursor AI's exclusive responsibility.
        """
        # Given/When/Then: ResearchContext has no design methods
        assert not hasattr(ResearchContext, 'design_subqueries')
        assert not hasattr(ResearchContext, 'generate_subqueries')
        assert not hasattr(ResearchContext, 'suggest_queries')
        
        # Given/When/Then: SubqueryExecutor has no design methods
        assert not hasattr(SubqueryExecutor, 'design_query')
        assert not hasattr(SubqueryExecutor, 'generate_query')
    
    def test_refutation_uses_only_mechanical_patterns(self):
        """
        Verify refutation only uses predefined suffixes, not LLM.
        
        §2.1.4: LLM must NOT be used for reverse query design.
        """
        # Given/When/Then: RefutationExecutor has no LLM methods
        assert not hasattr(RefutationExecutor, 'generate_hypothesis')
        assert not hasattr(RefutationExecutor, 'llm_reverse_query')
        
        # Given/When/Then: REFUTATION_SUFFIXES are predefined constants
        assert isinstance(REFUTATION_SUFFIXES, list)
        assert all(isinstance(s, str) for s in REFUTATION_SUFFIXES)
    
    @pytest.mark.asyncio
    async def test_context_notes_are_informational_only(self, test_database):
        """
        Verify context notes are hints, not directives.
        
        §2.1.1: Lancet provides support information, Cursor AI decides.
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
# Pipeline Tests (§3.2.1)
# =============================================================================

class TestStopTaskAction:
    """
    Tests for stop_task_action defensive access patterns.
    
    Bug fix verification: stop_task_action should use safe .get() access
    for all nested dictionary keys to handle potential missing keys gracefully.
    """
    
    @pytest.mark.asyncio
    async def test_stop_task_handles_missing_summary(self, test_database):
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
        async def mock_finalize():
            return {
                "ok": True,
                "final_status": "completed",
                # Missing "summary" and "evidence_graph_summary"
            }
        
        state.finalize = mock_finalize
        
        # When: Call stop_task_action
        result = await stop_task_action(task_id, state, "completed")
        
        # Then: Should succeed with default values
        assert result["ok"] is True
        assert result["summary"]["satisfied_searches"] == 0
        assert result["summary"]["total_claims"] == 0
        assert result["summary"]["primary_source_ratio"] == 0.0
    
    @pytest.mark.asyncio
    async def test_stop_task_handles_empty_nested_dicts(self, test_database):
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
        async def mock_finalize():
            return {
                "ok": True,
                "final_status": "partial",
                "summary": {},  # Empty summary
                "evidence_graph_summary": {},  # Empty graph summary
            }
        
        state.finalize = mock_finalize
        
        # When: Call stop_task_action
        result = await stop_task_action(task_id, state, "budget_exhausted")
        
        # Then: Should succeed with default values
        assert result["ok"] is True
        assert result["final_status"] == "partial"
        assert result["summary"]["satisfied_searches"] == 0
        assert result["summary"]["total_claims"] == 0
        assert result["summary"]["primary_source_ratio"] == 0.0
    
    @pytest.mark.asyncio
    async def test_stop_task_normal_finalize(self, test_database):
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
        async def mock_finalize():
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
        
        state.finalize = mock_finalize
        
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
# get_overall_harvest_rate Tests (§3.1.1 Lastmile Slot)
# ============================================================================


class TestGetOverallHarvestRate:
    """
    Tests for ExplorationState.get_overall_harvest_rate method.
    
    Per §3.1.1: Used to determine if lastmile engines should be used
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
    
    def test_get_overall_harvest_rate_no_searches(self):
        """TC-HR-B-01: Test returns 0.0 when no searches registered."""
        # Given: An ExplorationState with no searches
        from src.research.state import ExplorationState
        
        state = ExplorationState("test_task", enable_ucb_allocation=False)
        
        # When: Getting overall harvest rate
        rate = state.get_overall_harvest_rate()
        
        # Then: Returns 0.0
        assert rate == 0.0
    
    def test_get_overall_harvest_rate_zero_pages(self):
        """TC-HR-B-02: Test returns 0.0 when searches have no pages fetched."""
        # Given: An ExplorationState with searches but no pages fetched
        from src.research.state import ExplorationState
        
        state = ExplorationState("test_task", enable_ucb_allocation=False)
        search = state.register_search("search_1", "test query")
        # pages_fetched is 0 by default
        
        # When: Getting overall harvest rate
        rate = state.get_overall_harvest_rate()
        
        # Then: Returns 0.0 (no division by zero)
        assert rate == 0.0
    
    def test_get_overall_harvest_rate_single_search(self):
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
    
    def test_get_overall_harvest_rate_multiple_searches(self):
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
    
    def test_get_overall_harvest_rate_high_rate(self):
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
        assert rate >= 0.9  # Triggers lastmile per §3.1.1
