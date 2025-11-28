"""
Integration tests for Lancet.

Per §7.1.7: Integration tests use mocked external dependencies and should complete in <2min total.
These tests verify end-to-end workflows across multiple modules.
"""

import asyncio
import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from src.storage.database import Database


# =============================================================================
# Fixtures
# =============================================================================

@pytest_asyncio.fixture
async def integration_db(tmp_path):
    """Create a test database for integration tests."""
    db_path = tmp_path / "integration_test.db"
    db = Database(str(db_path))
    await db.connect()
    await db.initialize_schema()
    yield db
    await db.close()


@pytest.fixture
def mock_html_content():
    """Mock HTML content for extraction."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Government Report on Topic X</title></head>
    <body>
        <article>
            <h1>Official Government Report on Topic X</h1>
            <p>Published: June 1, 2024</p>
            <section>
                <h2>Key Findings</h2>
                <p>Our investigation found that Topic X has significant implications 
                for public policy. The evidence strongly supports the conclusion that
                X leads to Y under conditions Z.</p>
            </section>
            <section>
                <h2>Methodology</h2>
                <p>This report is based on analysis of 500 data points collected 
                over 24 months from reliable sources.</p>
            </section>
        </article>
    </body>
    </html>
    """


# =============================================================================
# Search to Extract Pipeline Integration Tests
# =============================================================================

@pytest.mark.integration
class TestSearchToExtractPipeline:
    """Test the search → fetch → extract pipeline."""
    
    @pytest.mark.asyncio
    async def test_extract_content_from_html(self, mock_html_content):
        """Verify content extraction from HTML."""
        from src.extractor.content import extract_content
        
        result = await extract_content(html=mock_html_content, content_type="html")
        
        assert result["ok"] is True
        # Should extract text content (returned as "text" key)
        assert "text" in result, f"Expected 'text' in result, got keys: {list(result.keys())}"
    
    @pytest.mark.asyncio
    async def test_rank_candidates_bm25(self, sample_passages):
        """Verify BM25 ranking works."""
        from src.filter.ranking import BM25Ranker
        
        ranker = BM25Ranker()
        texts = [p["text"] for p in sample_passages]
        
        ranker.fit(texts)
        scores = ranker.get_scores("healthcare AI medical")
        
        assert len(scores) == len(texts)
        # At least one healthcare-related passage should have a positive score
        healthcare_scores = [scores[0], scores[2], scores[4]]  # indices with healthcare content
        assert any(s > 0 for s in healthcare_scores), (
            f"Expected positive score for healthcare passages, got: {healthcare_scores}"
        )


# =============================================================================
# Exploration Control Engine Integration Tests (Phase 11)
# =============================================================================

@pytest.mark.integration
class TestExplorationControlFlow:
    """Test the exploration control engine workflow per §2.1."""
    
    @pytest.mark.asyncio
    async def test_research_context_provides_entities(self, integration_db):
        """Verify research context extracts entities from query."""
        from src.research.context import ResearchContext
        
        task_id = await integration_db.create_task(
            query="What are the environmental impacts of Toyota's EV production?",
        )
        
        context = ResearchContext(task_id)
        context._db = integration_db
        
        result = await context.get_context()
        
        assert result["ok"] is True
        assert result["original_query"] == "What are the environmental impacts of Toyota's EV production?"
        assert "extracted_entities" in result
        assert "applicable_templates" in result
    
    @pytest.mark.asyncio
    async def test_exploration_state_tracking(self, integration_db):
        """Verify exploration state tracks subquery progress."""
        from src.research.state import ExplorationState, SubqueryStatus
        
        task_id = await integration_db.create_task(query="Research X")
        
        state = ExplorationState(task_id)
        state._db = integration_db
        
        # Register a subquery
        state.register_subquery(
            subquery_id="sq_1",
            text="site:go.jp Topic X",
            priority="high",
        )
        
        # Get subquery and update its status
        sq = state.get_subquery("sq_1")
        assert sq is not None
        sq.status = SubqueryStatus.RUNNING
        
        status = await state.get_status()
        
        assert "subqueries" in status
        assert len(status["subqueries"]) == 1
        assert status["subqueries"][0]["status"] == SubqueryStatus.RUNNING.value
    
    @pytest.mark.asyncio
    async def test_subquery_satisfaction_score(self, integration_db):
        """Verify satisfaction score is calculated per §3.1.7.3."""
        from src.research.state import SubqueryState, SubqueryStatus
        
        # Create a subquery state with good metrics
        sq = SubqueryState(
            id="sq_test",
            text="Topic X research",
            status=SubqueryStatus.RUNNING,
            independent_sources=3,  # 3 independent sources
            has_primary_source=True,  # Has primary source
        )
        
        # Calculate satisfaction
        score = sq.calculate_satisfaction_score()
        
        # Per §3.1.7.3: score = min(1.0, (sources/3)*0.7 + (primary?0.3:0))
        # With 3 sources and primary: 1.0 * 0.7 + 0.3 = 1.0
        assert score >= 0.8, f"Expected score >= 0.8 with 3 sources + primary, got {score}"
        assert sq.is_satisfied() is True


# =============================================================================
# Evidence Graph Integration Tests
# =============================================================================

@pytest.mark.integration
class TestEvidenceGraphIntegration:
    """Test evidence graph construction and analysis."""
    
    @pytest.mark.asyncio
    async def test_claim_evidence_flow(self, integration_db):
        """Verify claim → evidence → source relationship tracking."""
        from src.filter.evidence_graph import (
            EvidenceGraph, NodeType, RelationType
        )
        
        graph = EvidenceGraph(task_id="test_task_1")
        
        # Add claim
        claim_id = graph.add_node(
            NodeType.CLAIM,
            "claim_1",
            text="X leads to Y",
            confidence=0.8,
        )
        
        # Add supporting fragment
        frag_id = graph.add_node(
            NodeType.FRAGMENT,
            "frag_1",
            text="Research shows X leads to Y in 95% of cases",
            url="https://example.com/study",
        )
        
        # Add support relationship
        graph.add_edge(
            NodeType.FRAGMENT, "frag_1",
            NodeType.CLAIM, "claim_1",
            RelationType.SUPPORTS,
            confidence=0.9,
            nli_label="entailment",
            nli_confidence=0.92,
        )
        
        # Verify evidence retrieval
        evidence = graph.get_supporting_evidence("claim_1")
        assert len(evidence) == 1
        assert evidence[0]["obj_id"] == "frag_1"
        assert evidence[0]["relation"] == "supports"
    
    @pytest.mark.asyncio
    async def test_citation_loop_detection(self, integration_db):
        """Verify citation loop detection per §3.3.3."""
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType
        
        graph = EvidenceGraph(task_id="test_loop")
        
        # Create citation loop: A → B → C → A
        graph.add_node(NodeType.PAGE, "page_a", domain="site-a.com")
        graph.add_node(NodeType.PAGE, "page_b", domain="site-b.com")
        graph.add_node(NodeType.PAGE, "page_c", domain="site-c.com")
        
        graph.add_edge(NodeType.PAGE, "page_a", NodeType.PAGE, "page_b", RelationType.CITES)
        graph.add_edge(NodeType.PAGE, "page_b", NodeType.PAGE, "page_c", RelationType.CITES)
        graph.add_edge(NodeType.PAGE, "page_c", NodeType.PAGE, "page_a", RelationType.CITES)
        
        # Detect loops
        loops = graph.detect_citation_loops()
        
        assert len(loops) >= 1, "Should detect the citation loop"
        assert loops[0]["length"] == 3
    
    @pytest.mark.asyncio
    async def test_primary_source_ratio(self, integration_db):
        """Verify primary source ratio calculation per §7 requirements."""
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType
        
        graph = EvidenceGraph(task_id="test_ratio")
        
        # Add primary sources (no outgoing citations)
        graph.add_node(NodeType.PAGE, "primary_1", domain="go.jp")
        graph.add_node(NodeType.PAGE, "primary_2", domain="who.int")
        graph.add_node(NodeType.PAGE, "primary_3", domain="arxiv.org")
        
        # Add secondary source (cites primary)
        graph.add_node(NodeType.PAGE, "secondary_1", domain="news.com")
        graph.add_edge(
            NodeType.PAGE, "secondary_1",
            NodeType.PAGE, "primary_1",
            RelationType.CITES
        )
        
        ratio_info = graph.get_primary_source_ratio()
        
        assert ratio_info["primary_count"] == 3
        assert ratio_info["secondary_count"] == 1
        assert ratio_info["primary_ratio"] == 0.75
        assert ratio_info["meets_threshold"] is True  # §7 requires ≥60%
    
    @pytest.mark.asyncio
    async def test_round_trip_detection(self, integration_db):
        """Verify round-trip citation detection per §3.3.3."""
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType
        
        graph = EvidenceGraph(task_id="test_roundtrip")
        
        # Create round-trip: A → B → A
        graph.add_node(NodeType.PAGE, "site_a", domain="a.com")
        graph.add_node(NodeType.PAGE, "site_b", domain="b.com")
        
        graph.add_edge(NodeType.PAGE, "site_a", NodeType.PAGE, "site_b", RelationType.CITES)
        graph.add_edge(NodeType.PAGE, "site_b", NodeType.PAGE, "site_a", RelationType.CITES)
        
        round_trips = graph.detect_round_trips()
        
        assert len(round_trips) == 1, "Should detect the round-trip"
        assert round_trips[0]["severity"] == "high"


# =============================================================================
# Deduplication Integration Tests
# =============================================================================

@pytest.mark.integration
class TestDeduplicationIntegration:
    """Test deduplication across the pipeline."""
    
    @pytest.mark.asyncio
    async def test_fragment_deduplication(self):
        """Verify duplicate fragment detection."""
        from src.filter.deduplication import deduplicate_fragments
        
        fragments = [
            {"id": "f1", "text": "Topic X has significant environmental implications for the region."},
            {"id": "f2", "text": "Topic X has significant environmental implications for the region."},  # Exact dup
            {"id": "f3", "text": "Environmental implications of Topic X are significant for the area."},  # Near dup
            {"id": "f4", "text": "Completely unrelated text about cooking recipes and ingredients."},
        ]
        
        result = await deduplicate_fragments(fragments)
        
        assert result["original_count"] == 4
        assert result["deduplicated_count"] <= 3  # At least the exact dup removed
        assert result["duplicate_ratio"] > 0
    
    @pytest.mark.asyncio
    async def test_hybrid_deduplication(self):
        """Verify MinHash + SimHash hybrid deduplication."""
        from src.filter.deduplication import HybridDeduplicator
        
        dedup = HybridDeduplicator(
            minhash_threshold=0.5,
            simhash_max_distance=5,
        )
        
        # Add similar texts
        dedup.add("t1", "The quick brown fox jumps over the lazy dog in the garden.")
        dedup.add("t2", "The quick brown fox jumps over the lazy dog in the yard.")  # Similar
        dedup.add("t3", "Python is a programming language used for web development.")  # Different
        
        # Find duplicates of t1
        duplicates = dedup.find_duplicates("t1")
        
        # Verify it runs without error
        assert isinstance(duplicates, list)


# =============================================================================
# NLI Integration Tests
# =============================================================================

@pytest.mark.integration
class TestNLIIntegration:
    """Test NLI stance classification integration."""
    
    @pytest.mark.asyncio
    async def test_nli_model_initialization(self):
        """Verify NLI model can be instantiated."""
        from src.filter.nli import NLIModel
        
        model = NLIModel()
        assert model is not None
        assert model.LABELS == ["supports", "refutes", "neutral"]
    
    @pytest.mark.asyncio
    async def test_nli_label_mapping(self):
        """Verify NLI label mapping works correctly."""
        from src.filter.nli import NLIModel
        
        model = NLIModel()
        
        assert model._map_label("ENTAILMENT") == "supports"
        assert model._map_label("CONTRADICTION") == "refutes"
        assert model._map_label("NEUTRAL") == "neutral"


# =============================================================================
# Report Generation Integration Tests
# =============================================================================

@pytest.mark.integration
class TestReportIntegration:
    """Test report generation integration."""
    
    @pytest.mark.asyncio
    async def test_anchor_slug_generation(self):
        """Verify deep link anchor slug generation per §3.4."""
        from src.report.generator import generate_anchor_slug
        
        # Test anchor slug generation
        slug = generate_anchor_slug("Section 3.1: Key Findings")
        assert slug == "section-31-key-findings"
        
        # Test with Japanese - should preserve characters
        slug_ja = generate_anchor_slug("第1章 概要")
        # Both Japanese terms should be in the slug
        assert "第1章" in slug_ja, f"Expected '第1章' in slug: {slug_ja}"
        assert "概要" in slug_ja, f"Expected '概要' in slug: {slug_ja}"
    
    @pytest.mark.asyncio
    async def test_report_generator_class_exists(self):
        """Verify ReportGenerator can be imported."""
        from src.report.generator import ReportGenerator
        
        assert ReportGenerator is not None


# =============================================================================
# Scheduler Integration Tests
# =============================================================================

@pytest.mark.integration
class TestSchedulerIntegration:
    """Test job scheduler integration."""
    
    @pytest.mark.asyncio
    async def test_job_kind_and_slot_enums(self):
        """Verify job enums are defined correctly."""
        from src.scheduler.jobs import JobKind, Slot, JobState
        
        assert JobKind.SERP == "serp"
        assert Slot.GPU == "gpu"
        assert Slot.BROWSER_HEADFUL == "browser_headful"
        assert JobState.PENDING == "pending"
    
    @pytest.mark.asyncio
    async def test_budget_tracking(self, integration_db):
        """Verify budget manager tracks resource usage."""
        from src.scheduler.budget import TaskBudget
        
        budget = TaskBudget(
            task_id="task_1",
            max_pages=120,
            max_time_seconds=1200,
        )
        
        # Check initial state
        assert budget.remaining_pages == 120
        
        # Use some budget
        budget.pages_fetched = 10
        
        assert budget.remaining_pages == 110
        assert budget.can_fetch_page() is True
    
    @pytest.mark.asyncio
    async def test_budget_exceeded_detection(self):
        """Verify budget exceeded detection."""
        from src.scheduler.budget import TaskBudget
        
        budget = TaskBudget(
            task_id="task_2",
            max_pages=10,
        )
        
        budget.pages_fetched = 10
        
        assert budget.can_fetch_page() is False


# =============================================================================
# Calibration Integration Tests
# =============================================================================

@pytest.mark.integration
class TestCalibrationIntegration:
    """Test calibration integration with LLM/NLI pipeline."""
    
    @pytest.mark.asyncio
    async def test_calibrator_initialization(self, tmp_path):
        """Verify calibrator can be initialized."""
        with patch("src.utils.calibration.get_project_root") as mock_root:
            mock_root.return_value = tmp_path
            
            from src.utils.calibration import Calibrator
            
            calibrator = Calibrator()
            assert calibrator is not None
    
    @pytest.mark.asyncio
    async def test_escalation_decider_initialization(self, tmp_path):
        """Verify escalation decider can be initialized."""
        with patch("src.utils.calibration.get_project_root") as mock_root:
            mock_root.return_value = tmp_path
            
            from src.utils.calibration import Calibrator, EscalationDecider
            
            calibrator = Calibrator()
            decider = EscalationDecider(calibrator=calibrator)
            
            assert decider is not None


# =============================================================================
# Metrics and Policy Integration Tests
# =============================================================================

@pytest.mark.integration
class TestMetricsPolicyIntegration:
    """Test metrics collection and policy adjustment integration."""
    
    @pytest.mark.asyncio
    async def test_metrics_collector_initialization(self):
        """Verify metrics collector can be initialized."""
        from src.utils.metrics import MetricsCollector
        
        collector = MetricsCollector()
        assert collector is not None
    
    @pytest.mark.asyncio
    async def test_policy_engine_initialization(self):
        """Verify policy engine can be initialized."""
        from src.utils.policy_engine import PolicyEngine
        
        policy = PolicyEngine()
        assert policy is not None


# =============================================================================
# Notification Integration Tests
# =============================================================================

@pytest.mark.integration
class TestNotificationIntegration:
    """Test notification system integration."""
    
    @pytest.mark.asyncio
    async def test_intervention_manager_initialization(self):
        """Verify intervention manager can be initialized."""
        from src.utils.notification import InterventionManager
        
        manager = InterventionManager()
        assert manager is not None
    
    @pytest.mark.asyncio
    async def test_intervention_types(self):
        """Verify intervention types are defined correctly."""
        from src.utils.notification import InterventionType, InterventionStatus
        
        assert InterventionType.CLOUDFLARE.value == "cloudflare"
        assert InterventionType.CAPTCHA.value == "captcha"
        assert InterventionStatus.PENDING.value == "pending"
        assert InterventionStatus.SUCCESS.value == "success"


# =============================================================================
# Full Pipeline Simulation Test
# =============================================================================

@pytest.mark.integration
class TestFullPipelineSimulation:
    """Simulated end-to-end pipeline test with mocks."""
    
    @pytest.mark.asyncio
    async def test_research_workflow_simulation(self, integration_db):
        """Simulate a complete research workflow with mocked externals."""
        from src.research.context import ResearchContext
        from src.research.state import ExplorationState, SubqueryState, SubqueryStatus
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType
        
        # Step 1: Create task
        task_id = await integration_db.create_task(
            query="What are the health effects of microplastics?"
        )
        
        # Step 2: Get research context
        context = ResearchContext(task_id)
        context._db = integration_db
        ctx_result = await context.get_context()
        assert ctx_result["ok"] is True
        
        # Step 3: Initialize exploration state
        state = ExplorationState(task_id)
        state._db = integration_db
        
        # Step 4: Register subqueries (as if designed by Cursor AI)
        subqueries = [
            ("sq_1", "microplastics health effects site:who.int"),
            ("sq_2", "microplastics toxicology research"),
            ("sq_3", "microplastics health criticism limitations"),
        ]
        for sq_id, sq_text in subqueries:
            state.register_subquery(sq_id, sq_text, priority="medium")
        
        # Step 5: Simulate execution - get subquery and update
        sq = state.get_subquery("sq_1")
        assert sq is not None
        sq.status = SubqueryStatus.RUNNING
        sq.independent_sources = 3
        sq.has_primary_source = True
        sq.calculate_satisfaction_score()
        sq.update_status()
        
        # Step 6: Build evidence graph
        graph = EvidenceGraph(task_id=task_id)
        graph.add_node(NodeType.CLAIM, "c1", text="Microplastics may affect human health")
        graph.add_node(NodeType.FRAGMENT, "f1", text="WHO report on microplastic health effects")
        graph.add_edge(NodeType.FRAGMENT, "f1", NodeType.CLAIM, "c1", RelationType.SUPPORTS, confidence=0.9)
        
        # Step 7: Verify final state
        final_status = await state.get_status()
        assert len(final_status["subqueries"]) == 3
        
        # Evidence should be present
        evidence = graph.get_supporting_evidence("c1")
        assert len(evidence) == 1
