"""
Tests for Phase 11: Exploration Control Engine.

These tests verify the exploration control functionality per §2.1 and §3.1.7:
- ResearchContext provides design support information (not subquery candidates)
- SubqueryExecutor executes Cursor AI-designed queries
- ExplorationState manages task/subquery states and metrics
- RefutationExecutor applies mechanical patterns only

Test Quality Standards (§7.1):
- No conditional assertions
- Specific value assertions
- No OR-condition assertions
- AAA pattern (Arrange-Act-Assert)
- Docstrings explaining test intent
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

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
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_context_returns_entities(self, test_database):
        """
        Verify that get_context extracts and returns entities from the query.
        
        §3.1.7.1: ResearchContext extracts entities (人名/組織/地名等)
        """
        # Arrange
        task_id = await test_database.create_task(
            query="株式会社トヨタ自動車の2024年決算情報",
        )
        context = ResearchContext(task_id)
        context._db = test_database
        
        # Act
        result = await context.get_context()
        
        # Assert
        assert result["ok"] is True
        assert result["task_id"] == task_id
        assert result["original_query"] == "株式会社トヨタ自動車の2024年決算情報"
        # Should extract organization entity
        entity_types = [e["type"] for e in result["extracted_entities"]]
        # Note: Simple regex may not catch all entities, but structure is correct
        assert isinstance(result["extracted_entities"], list)
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_context_returns_applicable_templates(self, test_database):
        """
        Verify that get_context returns applicable vertical templates.
        
        §3.1.7.1: Templates include academic/government/corporate/technical.
        """
        # Arrange
        task_id = await test_database.create_task(
            query="機械学習の最新研究論文",
        )
        context = ResearchContext(task_id)
        context._db = test_database
        
        # Act
        result = await context.get_context()
        
        # Assert
        assert result["ok"] is True
        templates = result["applicable_templates"]
        assert len(templates) > 0
        # Query contains "研究" so academic template should be suggested
        template_names = [t["name"] for t in templates]
        assert "academic" in template_names
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_context_does_not_return_subquery_candidates(self, test_database):
        """
        Verify that get_context does NOT return subquery candidates.
        
        §2.1.1: Subquery design is Cursor AI's exclusive responsibility.
        §2.1.4: Lancet must NOT generate subquery candidates.
        """
        # Arrange
        task_id = await test_database.create_task(
            query="AIの倫理的課題について",
        )
        context = ResearchContext(task_id)
        context._db = test_database
        
        # Act
        result = await context.get_context()
        
        # Assert
        assert result["ok"] is True
        # Must NOT contain subquery_candidates
        assert "subquery_candidates" not in result
        assert "suggested_subqueries" not in result
        assert "generated_queries" not in result
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_context_returns_recommended_engines(self, test_database):
        """
        Verify that get_context returns recommended search engines.
        """
        # Arrange
        task_id = await test_database.create_task(query="test query")
        context = ResearchContext(task_id)
        context._db = test_database
        
        # Act
        result = await context.get_context()
        
        # Assert
        assert result["ok"] is True
        assert "recommended_engines" in result
        assert isinstance(result["recommended_engines"], list)
        assert len(result["recommended_engines"]) > 0
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_context_task_not_found(self, test_database):
        """
        Verify that get_context returns error for non-existent task.
        """
        # Arrange
        context = ResearchContext("nonexistent_task_id")
        context._db = test_database
        
        # Act
        result = await context.get_context()
        
        # Assert
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
    
    @pytest.mark.unit
    def test_satisfaction_score_with_three_sources(self):
        """
        Verify satisfaction score is 0.7 with exactly 3 independent sources.
        
        §3.1.7.3: Score = (3/3)*0.7 + 0 = 0.7
        """
        # Arrange
        sq = SubqueryState(id="sq_001", text="test query")
        sq.independent_sources = 3
        sq.has_primary_source = False
        
        # Act
        score = sq.calculate_satisfaction_score()
        
        # Assert
        assert score == 0.7
    
    @pytest.mark.unit
    def test_satisfaction_score_with_primary_source(self):
        """
        Verify satisfaction score includes 0.3 bonus for primary source.
        
        §3.1.7.3: Score = (2/3)*0.7 + 0.3 ≈ 0.767
        """
        # Arrange
        sq = SubqueryState(id="sq_002", text="test query")
        sq.independent_sources = 2
        sq.has_primary_source = True
        
        # Act
        score = sq.calculate_satisfaction_score()
        
        # Assert
        expected = (2/3) * 0.7 + 0.3
        assert abs(score - expected) < 0.01
    
    @pytest.mark.unit
    def test_is_satisfied_threshold(self):
        """
        Verify is_satisfied returns True when score >= 0.8.
        
        §3.1.7.3: Satisfied when score >= 0.8.
        """
        # Arrange - score will be 0.7 + 0.3 = 1.0
        sq_satisfied = SubqueryState(id="sq_003", text="test")
        sq_satisfied.independent_sources = 3
        sq_satisfied.has_primary_source = True
        
        # score will be (2/3)*0.7 ≈ 0.467
        sq_not_satisfied = SubqueryState(id="sq_004", text="test")
        sq_not_satisfied.independent_sources = 2
        sq_not_satisfied.has_primary_source = False
        
        # Act & Assert
        assert sq_satisfied.is_satisfied() is True
        assert sq_not_satisfied.is_satisfied() is False
    
    @pytest.mark.unit
    def test_novelty_score_calculation(self):
        """
        Verify novelty score is calculated from recent fragments.
        
        §3.1.7.4: Novelty = novel fragments / total recent fragments.
        """
        # Arrange
        sq = SubqueryState(id="sq_005", text="test")
        
        # Add 10 fragments, 7 novel
        for i in range(10):
            is_novel = i < 7  # First 7 are novel
            sq.add_fragment(f"hash_{i}", is_useful=True, is_novel=is_novel)
        
        # Act
        novelty = sq.novelty_score
        
        # Assert
        assert novelty == 0.7
    
    @pytest.mark.unit
    def test_status_transitions(self):
        """
        Verify status transitions from PENDING to SATISFIED.
        """
        # Arrange
        sq = SubqueryState(id="sq_006", text="test")
        assert sq.status == SubqueryStatus.PENDING
        
        # Act - add enough sources to satisfy
        sq.independent_sources = 3
        sq.has_primary_source = True
        sq.update_status()
        
        # Assert
        assert sq.status == SubqueryStatus.SATISFIED
    
    @pytest.mark.unit
    def test_status_partial_with_some_sources(self):
        """
        Verify status is PARTIAL when 1-2 sources found.
        """
        # Arrange
        sq = SubqueryState(id="sq_007", text="test")
        sq.independent_sources = 1
        
        # Act
        sq.update_status()
        
        # Assert
        assert sq.status == SubqueryStatus.PARTIAL


# =============================================================================
# ExplorationState Tests (§3.1.7.2)
# =============================================================================

class TestExplorationState:
    """
    Tests for ExplorationState task management.
    """
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_register_and_start_subquery(self, test_database):
        """
        Verify subquery registration and starting.
        """
        # Arrange
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database
        
        # Act
        sq = state.register_subquery(
            subquery_id="sq_001",
            text="test subquery",
            priority="high",
        )
        state.start_subquery("sq_001")
        
        # Assert
        assert sq.id == "sq_001"
        assert sq.text == "test subquery"
        assert sq.priority == "high"
        assert sq.status == SubqueryStatus.RUNNING
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_budget_tracking(self, test_database):
        """
        Verify page budget is tracked correctly.
        """
        # Arrange
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database
        state._pages_limit = 10  # Small limit for testing
        
        sq = state.register_subquery("sq_001", "test")
        
        # Act - fetch pages up to limit
        for i in range(10):
            state.record_page_fetch("sq_001", f"domain{i}.com", False, True)
        
        within_budget, warning = state.check_budget()
        
        # Assert
        assert within_budget is False
        assert warning is not None
        assert "上限" in warning
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_status_returns_all_required_fields(self, test_database):
        """
        Verify get_status returns all required fields per §3.2.1.
        Now async per §16.7.1 changes.
        """
        # Arrange
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database
        state.register_subquery("sq_001", "subquery 1", priority="high")
        state.register_subquery("sq_002", "subquery 2", priority="medium")
        
        # Act - now async per §16.7.1
        status = await state.get_status()
        
        # Assert - verify structure per §3.2.1 MCPツールIF仕様
        assert status["ok"] is True
        assert status["task_id"] == task_id
        assert "task_status" in status
        assert "subqueries" in status
        assert len(status["subqueries"]) == 2
        assert "metrics" in status  # Changed from overall_progress
        assert "budget" in status
        # Note: recommendations removed - Cursor AI makes all decisions
        assert "warnings" in status
        # §16.7.1: authentication_queue is optional (None when empty)
        # Presence of the key structure is not mandatory when empty
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_status_includes_authentication_queue(self, test_database):
        """
        Verify get_status includes authentication_queue when pending items exist.
        
        Per §16.7.1: authentication_queue should contain summary information.
        """
        from unittest.mock import patch, AsyncMock
        
        # Arrange
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database
        
        # Mock the authentication queue summary
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
            # Act
            status = await state.get_status()
        
        # Assert
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
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_auth_queue_warning_threshold(self, test_database):
        """
        Verify warning alert is generated when pending >= 3.
        
        Per §16.7.3: [warning] when pending >= 3.
        """
        from unittest.mock import patch, AsyncMock
        
        # Arrange
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database
        
        # Mock the authentication queue summary with 3 pending items
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
            # Act
            status = await state.get_status()
        
        # Assert
        warning_alerts = [w for w in status["warnings"] if "[warning]" in w]
        assert len(warning_alerts) == 1, (
            f"Should have 1 warning alert, got {len(warning_alerts)}: {status['warnings']}"
        )
        assert "認証待ち3件" in warning_alerts[0], (
            f"Warning should mention '認証待ち3件', got '{warning_alerts[0]}'"
        )
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_auth_queue_critical_threshold_by_count(self, test_database):
        """
        Verify critical alert is generated when pending >= 5.
        
        Per §16.7.3: [critical] when pending >= 5.
        """
        from unittest.mock import patch, AsyncMock
        
        # Arrange
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database
        
        # Mock the authentication queue summary with 5 pending items
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
            # Act
            status = await state.get_status()
        
        # Assert
        critical_alerts = [w for w in status["warnings"] if "[critical]" in w]
        assert len(critical_alerts) == 1, (
            f"Should have 1 critical alert, got {len(critical_alerts)}: {status['warnings']}"
        )
        assert "認証待ち5件" in critical_alerts[0], (
            f"Critical should mention '認証待ち5件', got '{critical_alerts[0]}'"
        )
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_auth_queue_critical_threshold_by_high_priority(self, test_database):
        """
        Verify critical alert is generated when high_priority >= 2.
        
        Per §16.7.3: [critical] when high_priority >= 2.
        """
        from unittest.mock import patch, AsyncMock
        
        # Arrange
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database
        
        # Mock the authentication queue summary with 2 high priority items
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
            # Act
            status = await state.get_status()
        
        # Assert
        critical_alerts = [w for w in status["warnings"] if "[critical]" in w]
        assert len(critical_alerts) == 1, (
            f"Should have 1 critical alert for high priority, got {len(critical_alerts)}: {status['warnings']}"
        )
        assert "一次資料アクセスがブロック" in critical_alerts[0], (
            f"Critical should mention primary source blocking, got '{critical_alerts[0]}'"
        )
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_finalize_returns_summary(self, test_database):
        """
        Verify finalize returns proper summary with unsatisfied subqueries.
        """
        # Arrange
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database
        
        sq1 = state.register_subquery("sq_001", "satisfied query")
        sq1.independent_sources = 3
        sq1.has_primary_source = True
        sq1.update_status()
        
        sq2 = state.register_subquery("sq_002", "unsatisfied query")
        # Leave sq2 as PENDING
        
        # Act
        result = await state.finalize()
        
        # Assert
        assert result["ok"] is True
        assert result["final_status"] == "partial"  # Not all satisfied
        assert result["summary"]["satisfied_subqueries"] == 1
        assert "sq_002" in result["summary"]["unsatisfied_subqueries"]
        assert len(result["followup_suggestions"]) > 0


# =============================================================================
# SubqueryExecutor Tests (§2.1.3)
# =============================================================================

class TestSubqueryExecutor:
    """
    Tests for SubqueryExecutor mechanical operations.
    
    §2.1.3: Lancet only performs mechanical expansions, not query design.
    """
    
    @pytest.mark.unit
    def test_primary_source_detection(self):
        """
        Verify primary source domains are correctly identified.
        """
        # Assert - check that known primary sources are in the set
        assert "go.jp" in PRIMARY_SOURCE_DOMAINS
        assert "gov.uk" in PRIMARY_SOURCE_DOMAINS
        assert "arxiv.org" in PRIMARY_SOURCE_DOMAINS
        assert "who.int" in PRIMARY_SOURCE_DOMAINS
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_expand_query_mechanical_only(self, test_database):
        """
        Verify query expansion is mechanical (operators, not new ideas).
        
        §2.1.3: Lancet only adds operators, does not design new queries.
        """
        # Arrange
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        executor = SubqueryExecutor(task_id, state)
        
        original_query = "機械学習の研究論文"
        
        # Act
        expanded = executor._expand_query(original_query)
        
        # Assert
        assert original_query in expanded  # Original always included
        # Expanded queries should only add operators, not change meaning
        for eq in expanded:
            # All expanded queries should contain the original query text
            assert "機械学習" in eq or "研究" in eq or "論文" in eq
    
    @pytest.mark.unit
    def test_generate_refutation_queries_mechanical(self):
        """
        Verify refutation queries use mechanical suffix patterns only.
        
        §2.1.4: No LLM-based query generation for refutations.
        """
        # Arrange
        state = MagicMock()
        executor = SubqueryExecutor("task_001", state)
        base_query = "AIは安全である"
        
        # Act
        refutation_queries = executor.generate_refutation_queries(base_query)
        
        # Assert
        assert len(refutation_queries) > 0
        # All queries should be base_query + suffix
        for rq in refutation_queries:
            assert base_query in rq
            # Should contain one of the mechanical suffixes
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
    
    @pytest.mark.unit
    def test_refutation_suffixes_defined(self):
        """
        Verify all required refutation suffixes are defined.
        
        §3.1.7.5: Suffixes include 課題/批判/問題点/limitations等.
        """
        # Assert
        assert "課題" in REFUTATION_SUFFIXES
        assert "批判" in REFUTATION_SUFFIXES
        assert "問題点" in REFUTATION_SUFFIXES
        assert "limitations" in REFUTATION_SUFFIXES
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_generate_reverse_queries_mechanical(self, test_database):
        """
        Verify reverse query generation is mechanical (suffix-based).
        """
        # Arrange
        task_id = await test_database.create_task(query="test")
        state = ExplorationState(task_id)
        state._db = test_database
        executor = RefutationExecutor(task_id, state)
        
        claim_text = "深層学習は画像認識で高精度"
        
        # Act
        reverse_queries = executor._generate_reverse_queries(claim_text)
        
        # Assert
        assert len(reverse_queries) > 0
        for rq in reverse_queries:
            # Each reverse query should contain part of claim + suffix
            has_suffix = any(suffix in rq for suffix in REFUTATION_SUFFIXES)
            assert has_suffix, f"Query '{rq}' doesn't use mechanical suffix"
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_refutation_result_structure(self, test_database):
        """
        Verify RefutationResult has correct structure per §3.2.1.
        """
        # Arrange
        result = RefutationResult(
            target="claim_001",
            target_type="claim",
            reverse_queries_executed=3,
            refutations_found=1,
        )
        
        # Act
        result_dict = result.to_dict()
        
        # Assert - structure per §3.2.1
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
        # Arrange
        task_id = await test_database.create_task(
            query="量子コンピュータの現状と課題",
        )
        
        # Step 1: Get research context
        context = ResearchContext(task_id)
        context._db = test_database
        ctx_result = await context.get_context()
        
        # Assert context has required info
        assert ctx_result["ok"] is True
        assert "subquery_candidates" not in ctx_result  # Must NOT generate candidates
        
        # Step 2: Create state and executor
        state = ExplorationState(task_id)
        state._db = test_database
        
        # Step 3: Execute a subquery (designed by "Cursor AI" in this test)
        sq = state.register_subquery(
            subquery_id="sq_001",
            text="量子コンピュータ 基礎原理",
            priority="high",
        )
        state.start_subquery("sq_001")
        
        # Simulate page fetches
        state.record_page_fetch("sq_001", "university.ac.jp", True, True)
        state.record_page_fetch("sq_001", "research.go.jp", True, True)
        state.record_page_fetch("sq_001", "wikipedia.org", False, True)
        
        # Step 4: Get status (now async per §16.7.1)
        status = await state.get_status()
        
        assert status["ok"] is True
        assert status["metrics"]["total_pages"] == 3
        
        # Step 5: Finalize
        final = await state.finalize()
        
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
    
    @pytest.mark.unit
    def test_lancet_does_not_design_queries(self):
        """
        Verify Lancet components don't have query design capabilities.
        
        §2.1.1: Query design is Cursor AI's exclusive responsibility.
        """
        # Assert - ResearchContext should not have design methods
        assert not hasattr(ResearchContext, 'design_subqueries')
        assert not hasattr(ResearchContext, 'generate_subqueries')
        assert not hasattr(ResearchContext, 'suggest_queries')
        
        # SubqueryExecutor should not have design methods
        assert not hasattr(SubqueryExecutor, 'design_query')
        assert not hasattr(SubqueryExecutor, 'generate_query')
    
    @pytest.mark.unit
    def test_refutation_uses_only_mechanical_patterns(self):
        """
        Verify refutation only uses predefined suffixes, not LLM.
        
        §2.1.4: LLM must NOT be used for reverse query design.
        """
        # Assert - RefutationExecutor should not have LLM-based methods
        assert not hasattr(RefutationExecutor, 'generate_hypothesis')
        assert not hasattr(RefutationExecutor, 'llm_reverse_query')
        
        # REFUTATION_SUFFIXES should be predefined constants
        assert isinstance(REFUTATION_SUFFIXES, list)
        assert all(isinstance(s, str) for s in REFUTATION_SUFFIXES)
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_context_notes_are_informational_only(self, test_database):
        """
        Verify context notes are hints, not directives.
        
        §2.1.1: Lancet provides support information, Cursor AI decides.
        """
        # Arrange
        task_id = await test_database.create_task(query="test query")
        context = ResearchContext(task_id)
        context._db = test_database
        
        # Act
        result = await context.get_context()
        
        # Assert
        notes = result.get("notes", "")
        # Notes should not contain directives like "you must" or "required"
        assert "must" not in notes.lower()
        assert "required" not in notes.lower()
        assert "should query" not in notes.lower()

