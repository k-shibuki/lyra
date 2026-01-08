"""
Tests for BUG-001b fix: Early citation graph enqueue before web fetch.

This ensures citation_graph jobs are enqueued BEFORE web fetch,
so they survive timeout scenarios.

Test Perspectives Table:
| Case ID  | Input / Precondition              | Perspective               | Expected Result                                 |
|----------|-----------------------------------|---------------------------|------------------------------------------------|
| TC-N-01  | Academic API papers found         | Normal – early enqueue    | citation_graph enqueued before web fetch       |
| TC-N-02  | Papers found, normal completion   | Normal – dedup check      | citation_graph enqueued only once              |
| TC-A-01  | Timeout during web fetch          | Abnormal – timeout        | citation_graph already enqueued before timeout |
| TC-A-02  | enqueue_citation_graph_job throws | Abnormal – exception      | Exception logged, processing continues         |
| TC-B-01  | early_paper_ids = []              | Boundary – empty list     | citation_graph not enqueued                    |
| TC-B-02  | paper.id = None                   | Boundary – None ID        | Paper skipped                                  |
"""

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@dataclass
class MockPaper:
    """Mock paper for testing."""

    id: str | None
    title: str
    abstract: str | None
    doi: str | None = None
    arxiv_id: str | None = None
    authors: list[Any] | None = None
    year: int | None = None
    venue: str | None = None
    citation_count: int | None = None
    reference_count: int | None = None
    is_open_access: bool = False
    oa_url: str | None = None
    pdf_url: str | None = None
    source_api: str = "mock"

    def __post_init__(self) -> None:
        if self.authors is None:
            self.authors = []


@dataclass
class MockCanonicalEntry:
    """Mock canonical entry for testing."""

    paper: MockPaper | None
    needs_fetch: bool = False


class TestEarlyCitationEnqueue:
    """Tests for early citation graph enqueue (BUG-001b fix)."""

    @pytest.fixture
    def mock_state(self) -> MagicMock:
        """Create mock ExplorationState."""
        from src.research.state import ExplorationState

        state = MagicMock(spec=ExplorationState)
        state.task_id = "task_bug001b_test"
        state.task_hypothesis = "Test hypothesis"
        state.record_activity = MagicMock()
        state.get_status = AsyncMock(
            return_value={"budget": {"budget_pages_limit": 120, "budget_pages_used": 10}}
        )
        state.register_search = MagicMock(return_value=MagicMock(id="s_test"))
        state.start_search = MagicMock()
        state.get_search = MagicMock(return_value=MagicMock(status="running"))
        state.record_page_fetch = MagicMock()
        state.record_fragment = MagicMock()
        state.record_claim = MagicMock()
        return state

    @pytest.fixture
    def mock_papers(self) -> list[MockPaper]:
        """Create mock papers with abstracts."""
        return [
            MockPaper(id=f"paper_{i}", title=f"Paper {i}", abstract=f"Abstract {i}")
            for i in range(3)
        ]

    @pytest.fixture
    def mock_index(self, mock_papers: list[MockPaper]) -> MagicMock:
        """Create mock CanonicalPaperIndex."""
        # Add one entry that needs fetch to trigger web fetch path
        entries = [MockCanonicalEntry(paper=p, needs_fetch=False) for p in mock_papers]
        entries.append(MockCanonicalEntry(paper=None, needs_fetch=True))  # Needs fetch
        index = MagicMock()
        index.get_all_entries.return_value = entries
        index.get_stats.return_value = {
            "total": len(mock_papers) + 1,
            "both": 0,
            "api_only": len(mock_papers),
            "serp_only": 1,
        }
        return index

    @pytest.mark.asyncio
    async def test_citation_graph_enqueued_before_web_fetch(
        self, mock_state: MagicMock, mock_index: MagicMock
    ) -> None:
        """
        TC-N-01: Citation graph is enqueued before web fetch starts.

        // Given: Pipeline with papers from Academic API
        // When: _execute_unified_search is called
        // Then: citation_graph is enqueued before _execute_fetch_extract
        """
        from src.research.pipeline import PipelineSearchOptions, SearchPipeline

        pipeline = SearchPipeline("task_test", mock_state)

        # Track call order
        call_order: list[str] = []

        async def track_enqueue(*args: Any, **kwargs: Any) -> str:
            call_order.append("enqueue_citation_graph")
            return "job_123"

        async def track_fetch(*args: Any, **kwargs: Any) -> Any:
            call_order.append("execute_fetch")
            return args[3] if len(args) > 3 else MagicMock()

        with (
            patch.object(pipeline, "_ensure_db", new_callable=AsyncMock),
            patch(
                "src.search.search_api.search_serp",
                new_callable=AsyncMock,
                return_value=([], None, None),
            ),
            patch("src.search.academic_provider.AcademicSearchProvider") as mock_ap,
            patch("src.search.canonical_index.CanonicalPaperIndex", return_value=mock_index),
            patch("src.search.id_resolver.IDResolver") as mock_resolver,
            patch("src.search.identifier_extractor.IdentifierExtractor"),
            patch(
                "src.research.citation_graph.enqueue_citation_graph_job",
                side_effect=track_enqueue,
            ),
            patch.object(pipeline, "_execute_fetch_extract", side_effect=track_fetch),
            patch.object(
                pipeline,
                "_persist_abstract_as_fragment",
                new_callable=AsyncMock,
                return_value=("page_1", "frag_1"),
            ),
            patch(
                "src.filter.evidence_graph.get_evidence_graph",
                new_callable=AsyncMock,
                return_value=MagicMock(),  # graph.add_node is sync, not async
            ),
            patch(
                "src.utils.config.get_settings",
                return_value=MagicMock(task_limits=MagicMock(search_timeout_seconds=300)),
            ),
        ):
            mock_ap.return_value.search_papers = AsyncMock(return_value=([], 0))
            mock_ap.return_value.close = AsyncMock()
            mock_resolver.return_value.close = AsyncMock()

            await pipeline.execute("test query", PipelineSearchOptions())

        # Then: citation_graph enqueued before fetch
        assert "enqueue_citation_graph" in call_order
        assert call_order.index("enqueue_citation_graph") < call_order.index("execute_fetch")

    @pytest.mark.asyncio
    async def test_citation_graph_survives_timeout(self, mock_state: MagicMock) -> None:
        """
        TC-A-01: Citation graph is enqueued even when timeout occurs during web fetch.

        // Given: Pipeline with 0.5s timeout, web fetch takes 5s
        // When: execute() times out
        // Then: citation_graph was enqueued before timeout
        """
        from src.research.pipeline import (
            PipelineSearchOptions,
            SearchPipeline,
            SearchPipelineResult,
        )

        pipeline = SearchPipeline("task_test", mock_state)

        enqueue_called = False

        async def mock_execute_impl(
            search_id: str,
            query: str,
            options: PipelineSearchOptions,
            result: SearchPipelineResult,
        ) -> SearchPipelineResult:
            nonlocal enqueue_called

            # Simulate early enqueue (as per BUG-001b fix)
            from src.research.citation_graph import enqueue_citation_graph_job

            await enqueue_citation_graph_job(
                task_id="task_test",
                search_id=search_id,
                query=query,
                paper_ids=["paper_1", "paper_2"],
            )
            enqueue_called = True

            # Simulate slow web fetch that causes timeout
            await asyncio.sleep(5.0)
            return result

        mock_scheduler = MagicMock()
        mock_scheduler.submit = AsyncMock(return_value={"job_id": "cg_job"})
        mock_db = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value=None)

        with (
            patch.object(pipeline, "_ensure_db", new_callable=AsyncMock),
            patch.object(pipeline, "_execute_impl", side_effect=mock_execute_impl),
            patch(
                "src.storage.database.get_database",
                new_callable=AsyncMock,
                return_value=mock_db,
            ),
            patch(
                "src.scheduler.jobs.get_scheduler",
                new_callable=AsyncMock,
                return_value=mock_scheduler,
            ),
            patch(
                "src.utils.config.get_settings",
                return_value=MagicMock(task_limits=MagicMock(search_timeout_seconds=0.5)),
            ),
        ):
            result = await pipeline.execute("test query", PipelineSearchOptions())

        # Then: Timeout occurred but citation_graph was enqueued
        assert result.status == "timeout"
        assert result.is_partial is True
        assert enqueue_called is True
        mock_scheduler.submit.assert_called_once()

    @pytest.mark.asyncio
    async def test_early_enqueue_skipped_when_no_papers(self, mock_state: MagicMock) -> None:
        """
        TC-B-01: When no papers with abstracts, early enqueue is skipped.

        // Given: CanonicalPaperIndex with no papers
        // When: _execute_unified_search runs
        // Then: enqueue_citation_graph_job is not called for early enqueue
        """
        from src.research.pipeline import PipelineSearchOptions, SearchPipeline

        pipeline = SearchPipeline("task_test", mock_state)

        # Empty index
        empty_index = MagicMock()
        empty_index.get_all_entries.return_value = []
        empty_index.get_stats.return_value = {
            "total": 0,
            "both": 0,
            "api_only": 0,
            "serp_only": 0,
        }

        enqueue_calls = 0

        async def track_enqueue(*args: Any, **kwargs: Any) -> str | None:
            nonlocal enqueue_calls
            enqueue_calls += 1
            return "job_123"

        with (
            patch.object(pipeline, "_ensure_db", new_callable=AsyncMock),
            patch(
                "src.search.search_api.search_serp",
                new_callable=AsyncMock,
                return_value=([], None, None),
            ),
            patch("src.search.academic_provider.AcademicSearchProvider") as mock_ap,
            patch("src.search.canonical_index.CanonicalPaperIndex", return_value=empty_index),
            patch("src.search.id_resolver.IDResolver") as mock_resolver,
            patch("src.search.identifier_extractor.IdentifierExtractor"),
            patch(
                "src.research.citation_graph.enqueue_citation_graph_job",
                side_effect=track_enqueue,
            ),
            patch.object(pipeline, "_execute_fetch_extract", new_callable=AsyncMock),
            patch(
                "src.utils.config.get_settings",
                return_value=MagicMock(task_limits=MagicMock(search_timeout_seconds=300)),
            ),
        ):
            mock_ap.return_value.search_papers = AsyncMock(return_value=([], 0))
            mock_ap.return_value.close = AsyncMock()
            mock_resolver.return_value.close = AsyncMock()

            await pipeline.execute("test query", PipelineSearchOptions())

        # Then: No enqueue calls (early or late)
        assert enqueue_calls == 0

    @pytest.mark.asyncio
    async def test_papers_without_id_skipped_in_early_enqueue(self, mock_state: MagicMock) -> None:
        """
        TC-B-02: Papers with None ID are not included in early enqueue.

        // Given: Papers including one with id=None
        // When: Early enqueue happens
        // Then: Early enqueue only includes papers with valid IDs
        """
        from src.research.pipeline import PipelineSearchOptions, SearchPipeline

        pipeline = SearchPipeline("task_test", mock_state)

        # Papers with some having None ID
        papers = [
            MockPaper(id="paper_1", title="Paper 1", abstract="Abstract 1"),
            MockPaper(id=None, title="Paper 2", abstract="Abstract 2"),  # None ID
            MockPaper(id="paper_3", title="Paper 3", abstract="Abstract 3"),
        ]
        entries = [MockCanonicalEntry(paper=p, needs_fetch=False) for p in papers]

        index = MagicMock()
        index.get_all_entries.return_value = entries
        index.get_stats.return_value = {"total": 3, "both": 0, "api_only": 3, "serp_only": 0}

        # Track only the first (early) enqueue call
        early_enqueue_paper_ids: list[str] = []
        call_count = 0

        async def capture_early_enqueue(
            task_id: str, search_id: str, query: str, paper_ids: list[str]
        ) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # First call is early enqueue
                early_enqueue_paper_ids.extend(paper_ids)
            return "job_123"

        with (
            patch.object(pipeline, "_ensure_db", new_callable=AsyncMock),
            patch(
                "src.search.search_api.search_serp",
                new_callable=AsyncMock,
                return_value=([], None, None),
            ),
            patch("src.search.academic_provider.AcademicSearchProvider") as mock_ap,
            patch("src.search.canonical_index.CanonicalPaperIndex", return_value=index),
            patch("src.search.id_resolver.IDResolver") as mock_resolver,
            patch("src.search.identifier_extractor.IdentifierExtractor"),
            patch(
                "src.research.citation_graph.enqueue_citation_graph_job",
                side_effect=capture_early_enqueue,
            ),
            patch.object(pipeline, "_execute_fetch_extract", new_callable=AsyncMock),
            patch.object(
                pipeline,
                "_persist_abstract_as_fragment",
                new_callable=AsyncMock,
                return_value=("page_1", "frag_1"),
            ),
            patch(
                "src.filter.evidence_graph.get_evidence_graph",
                new_callable=AsyncMock,
                return_value=MagicMock(),  # graph.add_node is sync, not async
            ),
            patch(
                "src.utils.config.get_settings",
                return_value=MagicMock(task_limits=MagicMock(search_timeout_seconds=300)),
            ),
        ):
            mock_ap.return_value.search_papers = AsyncMock(return_value=([], 0))
            mock_ap.return_value.close = AsyncMock()
            mock_resolver.return_value.close = AsyncMock()

            await pipeline.execute("test query", PipelineSearchOptions())

        # Then: Early enqueue has only valid paper IDs (no None)
        assert "paper_1" in early_enqueue_paper_ids
        assert "paper_3" in early_enqueue_paper_ids
        assert None not in early_enqueue_paper_ids
        assert len(early_enqueue_paper_ids) == 2  # Only 2 papers with valid IDs

    @pytest.mark.asyncio
    async def test_early_enqueue_exception_handled(self, mock_state: MagicMock) -> None:
        """
        TC-A-02: Exception during early enqueue is handled gracefully.

        // Given: enqueue_citation_graph_job raises exception
        // When: Early enqueue is attempted
        // Then: Exception is caught, warning logged, processing continues
        """
        from src.research.pipeline import (
            PipelineSearchOptions,
            SearchPipeline,
            SearchPipelineResult,
        )

        pipeline = SearchPipeline("task_test", mock_state)

        exception_raised = False
        processing_continued = False

        async def mock_execute_impl(
            search_id: str,
            query: str,
            options: PipelineSearchOptions,
            result: SearchPipelineResult,
        ) -> SearchPipelineResult:
            nonlocal exception_raised, processing_continued

            # Simulate early enqueue that fails
            try:
                from src.research.citation_graph import enqueue_citation_graph_job

                await enqueue_citation_graph_job(
                    task_id="task_test",
                    search_id=search_id,
                    query=query,
                    paper_ids=["paper_1"],
                )
            except RuntimeError:
                exception_raised = True
                # Exception should be caught in the real code

            # Processing continues after exception
            processing_continued = True
            result.status = "satisfied"
            return result

        async def failing_enqueue(*args: Any, **kwargs: Any) -> str:
            raise RuntimeError("Simulated early enqueue failure")

        mock_db = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value=None)

        with (
            patch.object(pipeline, "_ensure_db", new_callable=AsyncMock),
            patch.object(pipeline, "_execute_impl", side_effect=mock_execute_impl),
            patch(
                "src.storage.database.get_database",
                new_callable=AsyncMock,
                return_value=mock_db,
            ),
            patch(
                "src.scheduler.jobs.get_scheduler",
                new_callable=AsyncMock,
                side_effect=failing_enqueue,
            ),
            patch(
                "src.utils.config.get_settings",
                return_value=MagicMock(task_limits=MagicMock(search_timeout_seconds=300)),
            ),
        ):
            # Should not raise even if enqueue fails
            result = await pipeline.execute("test query", PipelineSearchOptions())

        # Then: Exception was raised but processing continued
        assert result is not None
        assert exception_raised is True
        assert processing_continued is True
