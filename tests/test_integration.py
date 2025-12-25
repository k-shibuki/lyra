"""
Integration tests for Lyra.

Per .1.7: Integration tests use mocked external dependencies and should complete in <2min total.
These tests verify end-to-end workflows across multiple modules.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-INT-N-01 | Valid HTML content | Equivalence – normal | Extraction succeeds with text key | Content extraction |
| TC-INT-N-02 | Passage list for BM25 | Equivalence – normal | Scores array length matches input | BM25 ranking |
| TC-INT-N-03 | Task with query | Equivalence – normal | Context with entities and templates | ResearchContext |
| TC-INT-N-04 | Task with subquery | Equivalence – normal | Status tracks subquery progress | ExplorationState |
| TC-INT-N-05 | 3 sources + primary | Equivalence – satisfaction | Score >= 0.8, is_satisfied=True | ADR-0010 |
| TC-INT-N-06 | Claim + fragment | Equivalence – normal | Evidence retrieved with relationship | EvidenceGraph |
| TC-INT-N-07 | A→B→C→A citations | Equivalence – cycle | Loop detected with length=3 | Citation loop |
| TC-INT-N-08 | 3 primary + 1 secondary | Equivalence – ratio | Primary ratio=0.75, meets threshold | requirement |
| TC-INT-N-09 | A→B→A citations | Equivalence – round-trip | Round-trip detected, severity=high | |
| TC-INT-N-10 | Duplicate fragments | Equivalence – normal | Duplicates detected and removed | Deduplication |
| TC-INT-N-11 | Similar texts | Equivalence – normal | Returns list of duplicates | Hybrid dedup |
| TC-INT-N-12 | NLI model import | Equivalence – init | Model instantiated with 3 labels | NLI model |
| TC-INT-N-13 | Label strings | Equivalence – mapping | Correct label mapping | NLI labels |
| TC-INT-N-14 | Section title | Equivalence – normal | Valid slug generated | Anchor slug |
| TC-INT-N-15 | ReportGenerator import | Equivalence – init | Callable class | Report generator |
| TC-INT-N-16 | JobKind/Slot enums | Equivalence – init | Correct enum values | Scheduler enums |
| TC-INT-N-17 | Budget with budget_pages | Equivalence – normal | Remaining pages tracked | Budget tracking |
| TC-INT-B-01 | Budget at limit | Boundary – max | can_fetch_page=False | Budget exceeded |
| TC-INT-N-18 | Calibrator import | Equivalence – init | Instance created | Calibrator |
| TC-INT-N-19 | EscalationDecider import | Equivalence – init | Instance created | Escalation decider |
| TC-INT-N-20 | MetricsCollector import | Equivalence – init | Instance created | Metrics collector |
| TC-INT-N-21 | PolicyEngine import | Equivalence – init | Instance created | Policy engine |
| TC-INT-N-22 | InterventionManager import | Equivalence – init | Instance created | Intervention manager |
| TC-INT-N-23 | InterventionType enum | Equivalence – init | Correct enum values | Intervention types |
| TC-INT-N-24 | Full workflow simulation | Equivalence – integration | Task→Context→State→Graph works | Full pipeline |
"""

from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.mark.integration
import pytest
import pytest_asyncio

from src.storage.database import Database

import pytest

pytestmark = pytest.mark.integration


pytest.mark.integration
pytestmark = pytest.mark.integration


# =============================================================================
# Fixtures
# =============================================================================


@pytest_asyncio.fixture
async def integration_db(tmp_path: Path) -> AsyncGenerator[Database, None]:
    """Create a test database for integration tests."""
    db_path = tmp_path / "integration_test.db"
    db = Database(str(db_path))
    await db.connect()
    await db.initialize_schema()
    yield db
    await db.close()


@pytest.fixture
def mock_html_content() -> str:
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


class TestSearchToExtractPipeline:
    """Test the search → fetch → extract pipeline."""

    @pytest.mark.asyncio
    async def test_extract_content_from_html(self, mock_html_content: str) -> None:
        """Verify content extraction from HTML."""
        from src.extractor.content import extract_content

        # Given: Valid HTML content
        # When: Extract content from HTML
        result = await extract_content(html=mock_html_content, content_type="html")

        # Then: Extraction succeeds with text key
        assert result["ok"] is True
        assert "text" in result, f"Expected 'text' in result, got keys: {list(result.keys())}"

    @pytest.mark.asyncio
    async def test_rank_candidates_bm25(self, sample_passages: list[dict[str, str]]) -> None:
        """Verify BM25 ranking works."""
        from src.filter.ranking import BM25Ranker

        # Given: A list of passages to rank
        ranker = BM25Ranker()
        texts = [p["text"] for p in sample_passages]

        # When: Fit ranker and get scores for a query
        ranker.fit(texts)
        scores = ranker.get_scores("healthcare AI medical")

        # Then: Scores array matches input length with positive healthcare scores
        assert len(scores) == len(texts)
        healthcare_scores = [scores[0], scores[2], scores[4]]
        assert any(s > 0 for s in healthcare_scores), (
            f"Expected positive score for healthcare passages, got: {healthcare_scores}"
        )


# =============================================================================
# Exploration Control Engine Integration Tests
# =============================================================================


class TestExplorationControlFlow:
    """Test the exploration control engine workflow per ADR-0002."""

    @pytest.mark.asyncio
    async def test_research_context_provides_entities(self, integration_db: Database) -> None:
        """Verify research context extracts entities from query."""
        from src.research.context import ResearchContext

        # Given: A task with a query containing entities
        task_id = await integration_db.create_task(
            query="What are the environmental impacts of Toyota's EV production?",
        )

        context = ResearchContext(task_id)
        context._db = integration_db

        # When: Get research context
        result = await context.get_context()

        # Then: Context contains entities and templates
        assert result["ok"] is True
        assert (
            result["original_query"]
            == "What are the environmental impacts of Toyota's EV production?"
        )
        assert "extracted_entities" in result
        assert "applicable_templates" in result

    @pytest.mark.asyncio
    async def test_exploration_state_tracking(self, integration_db: Database) -> None:
        """Verify exploration state tracks subquery progress."""
        from src.research.state import ExplorationState, SearchStatus

        # Given: A task and exploration state
        task_id = await integration_db.create_task(query="Research X")

        state = ExplorationState(task_id)
        state._db = integration_db

        # When: Register and update a subquery
        state.register_subquery(
            subquery_id="sq_1",
            text="site:go.jp Topic X",
            priority="high",
        )

        sq = state.get_subquery("sq_1")
        assert sq is not None
        sq.status = SearchStatus.RUNNING

        status = await state.get_status()

        # Then: Status tracks the search
        assert "searches" in status
        assert len(status["searches"]) == 1
        assert status["searches"][0]["status"] == SearchStatus.RUNNING.value

    @pytest.mark.asyncio
    async def test_subquery_satisfaction_score(self, integration_db: Database) -> None:
        """Verify satisfaction score is calculated per ADR-0010."""
        from src.research.state import SearchState, SearchStatus

        # Given: A subquery with 3 independent sources and a primary source
        sq = SearchState(
            id="sq_test",
            text="Topic X research",
            status=SearchStatus.RUNNING,
            independent_sources=3,
            has_primary_source=True,
        )

        # When: Calculate satisfaction score
        score = sq.calculate_satisfaction_score()

        # Then: Score >= 0.8 and subquery is satisfied
        assert score >= 0.8, f"Expected score >= 0.8 with 3 sources + primary, got {score}"
        assert sq.is_satisfied() is True


# =============================================================================
# Evidence Graph Integration Tests
# =============================================================================


class TestEvidenceGraphIntegration:
    """Test evidence graph construction and analysis."""

    @pytest.mark.asyncio
    async def test_claim_evidence_flow(self, integration_db: Database) -> None:
        """Verify claim → evidence → source relationship tracking."""
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: An evidence graph with claim and fragment
        graph = EvidenceGraph(task_id="test_task_1")

        graph.add_node(
            NodeType.CLAIM,
            "claim_1",
            text="X leads to Y",
            confidence=0.8,
        )

        graph.add_node(
            NodeType.FRAGMENT,
            "frag_1",
            text="Research shows X leads to Y in 95% of cases",
            url="https://example.com/study",
        )

        # When: Add support relationship and retrieve evidence
        graph.add_edge(
            NodeType.FRAGMENT,
            "frag_1",
            NodeType.CLAIM,
            "claim_1",
            RelationType.SUPPORTS,
            confidence=0.9,
            nli_label="entailment",
            nli_confidence=0.92,
        )

        evidence = graph.get_supporting_evidence("claim_1")

        # Then: Evidence is retrieved with correct relationship
        assert len(evidence) == 1
        assert evidence[0]["obj_id"] == "frag_1"
        assert evidence[0]["relation"] == "supports"

    @pytest.mark.asyncio
    async def test_citation_loop_detection(self, integration_db: Database) -> None:
        """Verify citation loop detection per ."""
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: Pages with citation loop A → B → C → A
        graph = EvidenceGraph(task_id="test_loop")

        graph.add_node(NodeType.PAGE, "page_a", domain="site-a.com")
        graph.add_node(NodeType.PAGE, "page_b", domain="site-b.com")
        graph.add_node(NodeType.PAGE, "page_c", domain="site-c.com")

        graph.add_edge(NodeType.PAGE, "page_a", NodeType.PAGE, "page_b", RelationType.CITES)
        graph.add_edge(NodeType.PAGE, "page_b", NodeType.PAGE, "page_c", RelationType.CITES)
        graph.add_edge(NodeType.PAGE, "page_c", NodeType.PAGE, "page_a", RelationType.CITES)

        # When: Detect citation loops
        loops = graph.detect_citation_loops()

        # Then: Loop is detected with length 3
        assert len(loops) >= 1, "Should detect the citation loop"
        assert loops[0]["length"] == 3

    @pytest.mark.asyncio
    async def test_primary_source_ratio(self, integration_db: Database) -> None:
        """Verify primary source ratio calculation per requirements."""
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: 3 primary sources and 1 secondary source
        graph = EvidenceGraph(task_id="test_ratio")

        graph.add_node(NodeType.PAGE, "primary_1", domain="go.jp")
        graph.add_node(NodeType.PAGE, "primary_2", domain="who.int")
        graph.add_node(NodeType.PAGE, "primary_3", domain="arxiv.org")

        graph.add_node(NodeType.PAGE, "secondary_1", domain="news.com")
        graph.add_edge(NodeType.PAGE, "secondary_1", NodeType.PAGE, "primary_1", RelationType.CITES)

        # When: Calculate primary source ratio
        ratio_info = graph.get_primary_source_ratio()

        # Then: Ratio is 0.75 (3/4) and meets threshold
        assert ratio_info["primary_count"] == 3
        assert ratio_info["secondary_count"] == 1
        assert ratio_info["primary_ratio"] == 0.75
        assert ratio_info["meets_threshold"] is True

    @pytest.mark.asyncio
    async def test_round_trip_detection(self, integration_db: Database) -> None:
        """Verify round-trip citation detection per ."""
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: Pages with round-trip A → B → A
        graph = EvidenceGraph(task_id="test_roundtrip")

        graph.add_node(NodeType.PAGE, "site_a", domain="a.com")
        graph.add_node(NodeType.PAGE, "site_b", domain="b.com")

        graph.add_edge(NodeType.PAGE, "site_a", NodeType.PAGE, "site_b", RelationType.CITES)
        graph.add_edge(NodeType.PAGE, "site_b", NodeType.PAGE, "site_a", RelationType.CITES)

        # When: Detect round-trips
        round_trips = graph.detect_round_trips()

        # Then: Round-trip detected with high severity
        assert len(round_trips) == 1, "Should detect the round-trip"
        assert round_trips[0]["severity"] == "high"


# =============================================================================
# Deduplication Integration Tests
# =============================================================================


class TestDeduplicationIntegration:
    """Test deduplication across the pipeline."""

    @pytest.mark.asyncio
    async def test_fragment_deduplication(self) -> None:
        """Verify duplicate fragment detection."""
        from src.filter.deduplication import deduplicate_fragments

        # Given: Fragments with exact and near duplicates
        fragments = [
            {
                "id": "f1",
                "text": "Topic X has significant environmental implications for the region.",
            },
            {
                "id": "f2",
                "text": "Topic X has significant environmental implications for the region.",
            },
            {
                "id": "f3",
                "text": "Environmental implications of Topic X are significant for the area.",
            },
            {
                "id": "f4",
                "text": "Completely unrelated text about cooking recipes and ingredients.",
            },
        ]

        # When: Deduplicate fragments
        result = await deduplicate_fragments(fragments)

        # Then: Duplicates are detected and removed
        assert result["original_count"] == 4
        assert result["deduplicated_count"] <= 3
        assert result["duplicate_ratio"] > 0

    @pytest.mark.asyncio
    async def test_hybrid_deduplication(self) -> None:
        """Verify MinHash + SimHash hybrid deduplication."""
        from src.filter.deduplication import HybridDeduplicator

        # Given: A hybrid deduplicator with similar texts added
        dedup = HybridDeduplicator(
            minhash_threshold=0.5,
            simhash_max_distance=5,
        )

        dedup.add("t1", "The quick brown fox jumps over the lazy dog in the garden.")
        dedup.add("t2", "The quick brown fox jumps over the lazy dog in the yard.")
        dedup.add("t3", "Python is a programming language used for web development.")

        # When: Find duplicates of t1
        duplicates = dedup.find_duplicates("t1")

        # Then: Returns a list of potential duplicates
        assert isinstance(duplicates, list)


# =============================================================================
# NLI Integration Tests
# =============================================================================


class TestNLIIntegration:
    """Test NLI stance classification integration."""

    @pytest.mark.asyncio
    async def test_nli_model_initialization(self) -> None:
        """Verify NLI model can be instantiated."""
        from src.filter.nli import NLIModel

        # Given: NLI model class
        # When: Instantiate model
        model = NLIModel()

        # Then: Model has expected labels
        assert model is not None
        assert model.LABELS == ["supports", "refutes", "neutral"]

    @pytest.mark.asyncio
    async def test_nli_label_mapping(self) -> None:
        """Verify NLI label mapping works correctly."""
        from src.filter.nli import NLIModel

        # Given: An NLI model instance
        model = NLIModel()

        # When/Then: Label mapping returns correct values
        assert model._map_label("ENTAILMENT") == "supports"
        assert model._map_label("CONTRADICTION") == "refutes"
        assert model._map_label("NEUTRAL") == "neutral"


# =============================================================================
# Report Generation Integration Tests
# =============================================================================


class TestReportIntegration:
    """Test report generation integration."""

    @pytest.mark.asyncio
    async def test_anchor_slug_generation(self) -> None:
        """Verify deep link anchor slug generation per ADR-0005."""
        from src.report.generator import generate_anchor_slug

        # Given: A section title
        # When: Generate anchor slug
        slug = generate_anchor_slug("Section 3.1: Key Findings")

        # Then: Slug is correctly formatted
        assert slug == "section-31-key-findings"

        # Given: Japanese title
        # When: Generate anchor slug
        slug_ja = generate_anchor_slug("第1章 概要")

        # Then: Japanese characters are preserved
        assert "第1章" in slug_ja, f"Expected '第1章' in slug: {slug_ja}"
        assert "概要" in slug_ja, f"Expected '概要' in slug: {slug_ja}"

    @pytest.mark.asyncio
    async def test_report_generator_class_exists(self) -> None:
        """Verify ReportGenerator can be imported and is callable."""
        from src.report.generator import ReportGenerator

        # Given/When: Import ReportGenerator
        # Then: It is a callable class
        assert callable(ReportGenerator), "ReportGenerator should be a callable class"


# =============================================================================
# Scheduler Integration Tests
# =============================================================================


class TestSchedulerIntegration:
    """Test job scheduler integration."""

    @pytest.mark.asyncio
    async def test_job_kind_and_slot_enums(self) -> None:
        """Verify job enums are defined correctly."""
        from src.scheduler.jobs import JobKind, JobState, Slot

        # Given/When: Import enums
        # Then: Enum values are correct
        assert JobKind.SERP == "serp"
        assert Slot.GPU == "gpu"
        assert Slot.BROWSER_HEADFUL == "browser_headful"
        assert JobState.PENDING == "pending"

    @pytest.mark.asyncio
    async def test_budget_tracking(self, integration_db: Database) -> None:
        """Verify budget manager tracks resource usage."""
        from src.scheduler.budget import TaskBudget

        # Given: A budget with budget_pages=120
        budget = TaskBudget(
            task_id="task_1",
            budget_pages=120,
            max_time_seconds=1200,
        )

        # Then: Initial remaining pages is 120
        assert budget.remaining_pages == 120

        # When: Use 10 pages
        budget.pages_fetched = 10

        # Then: Remaining is 110 and can still fetch
        assert budget.remaining_pages == 110
        assert budget.can_fetch_page() is True

    @pytest.mark.asyncio
    async def test_budget_exceeded_detection(self) -> None:
        """Verify budget exceeded detection."""
        from src.scheduler.budget import TaskBudget

        # Given: A budget at its limit
        budget = TaskBudget(
            task_id="task_2",
            budget_pages=10,
        )

        budget.pages_fetched = 10

        # When/Then: Cannot fetch more pages
        assert budget.can_fetch_page() is False


# =============================================================================
# Calibration Integration Tests
# =============================================================================


class TestCalibrationIntegration:
    """Test calibration integration with LLM/NLI pipeline."""

    @pytest.mark.asyncio
    async def test_calibrator_initialization(self, tmp_path: Path) -> None:
        """Verify calibrator can be initialized."""
        with patch("src.utils.calibration.get_project_root") as mock_root:
            mock_root.return_value = tmp_path

            from src.utils.calibration import Calibrator

            # Given/When: Instantiate Calibrator
            calibrator = Calibrator()

            # Then: Instance is created
            assert isinstance(calibrator, Calibrator), (
                f"Expected Calibrator instance, got {type(calibrator)}"
            )


# =============================================================================
# Metrics and Policy Integration Tests
# =============================================================================


class TestMetricsPolicyIntegration:
    """Test metrics collection and policy adjustment integration."""

    @pytest.mark.asyncio
    async def test_metrics_collector_initialization(self) -> None:
        """Verify metrics collector can be initialized."""
        from src.utils.metrics import MetricsCollector

        # Given/When: Instantiate MetricsCollector
        collector = MetricsCollector()

        # Then: Instance is created
        assert isinstance(collector, MetricsCollector), (
            f"Expected MetricsCollector, got {type(collector)}"
        )

    @pytest.mark.asyncio
    async def test_policy_engine_initialization(self) -> None:
        """Verify policy engine can be initialized."""
        from src.utils.policy_engine import PolicyEngine

        # Given/When: Instantiate PolicyEngine
        policy = PolicyEngine()

        # Then: Instance is created
        assert isinstance(policy, PolicyEngine), f"Expected PolicyEngine, got {type(policy)}"


# =============================================================================
# Notification Integration Tests
# =============================================================================


class TestNotificationIntegration:
    """Test notification system integration."""

    @pytest.mark.asyncio
    async def test_intervention_manager_initialization(self) -> None:
        """Verify intervention manager can be initialized."""
        from src.utils.notification import InterventionManager

        # Given/When: Instantiate InterventionManager
        manager = InterventionManager()

        # Then: Instance is created
        assert isinstance(manager, InterventionManager), (
            f"Expected InterventionManager, got {type(manager)}"
        )

    @pytest.mark.asyncio
    async def test_intervention_types(self) -> None:
        """Verify intervention types are defined correctly."""
        from src.utils.notification import InterventionStatus, InterventionType

        # Given/When: Import enums
        # Then: Enum values are correct
        assert InterventionType.CLOUDFLARE.value == "cloudflare"
        assert InterventionType.CAPTCHA.value == "captcha"
        assert InterventionStatus.PENDING.value == "pending"
        assert InterventionStatus.SUCCESS.value == "success"


# =============================================================================
# Full Pipeline Simulation Test
# =============================================================================


class TestFullPipelineSimulation:
    """Simulated end-to-end pipeline test with mocks."""

    @pytest.mark.asyncio
    async def test_research_workflow_simulation(self, integration_db: Database) -> None:
        """Simulate a complete research workflow with mocked externals."""
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType
        from src.research.context import ResearchContext
        from src.research.state import ExplorationState, SearchStatus

        # Given: A research query
        task_id = await integration_db.create_task(
            query="What are the health effects of microplastics?"
        )

        # When: Get research context
        context = ResearchContext(task_id)
        context._db = integration_db
        ctx_result = await context.get_context()

        # Then: Context retrieval succeeds
        assert ctx_result["ok"] is True

        # Given: Exploration state with subqueries
        state = ExplorationState(task_id)
        state._db = integration_db

        subqueries = [
            ("sq_1", "microplastics health effects site:who.int"),
            ("sq_2", "microplastics toxicology research"),
            ("sq_3", "microplastics health criticism limitations"),
        ]
        for sq_id, sq_text in subqueries:
            state.register_subquery(sq_id, sq_text, priority="medium")

        # When: Simulate subquery execution
        sq = state.get_subquery("sq_1")
        assert sq is not None
        sq.status = SearchStatus.RUNNING
        sq.independent_sources = 3
        sq.has_primary_source = True
        sq.calculate_satisfaction_score()
        sq.update_status()

        # When: Build evidence graph
        graph = EvidenceGraph(task_id=task_id)
        graph.add_node(NodeType.CLAIM, "c1", text="Microplastics may affect human health")
        graph.add_node(NodeType.FRAGMENT, "f1", text="WHO report on microplastic health effects")
        graph.add_edge(
            NodeType.FRAGMENT, "f1", NodeType.CLAIM, "c1", RelationType.SUPPORTS, confidence=0.9
        )

        # Then: Final state has 3 subqueries and evidence
        final_status = await state.get_status()
        assert len(final_status["searches"]) == 3

        evidence = graph.get_supporting_evidence("c1")
        assert len(evidence) == 1
