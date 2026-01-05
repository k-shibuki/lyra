"""
Tests for citation graph deferred job processing (ADR-0016).

Test Perspectives Table:
| Case ID    | Input / Precondition                     | Perspective              | Expected Result                              | Notes          |
|------------|------------------------------------------|--------------------------|----------------------------------------------|----------------|
| TC-N-01    | Valid task_id with papers                | Normal                   | Job enqueued successfully                    | -              |
| TC-N-02    | process_citation_graph called            | Normal (execution)       | Citations processed, edges created           | -              |
| TC-A-01    | Empty paper_ids list                     | Boundary - empty         | No job enqueued (None returned)              | -              |
| TC-A-02    | Job already exists                       | Boundary - duplicate     | No duplicate job created                     | -              |
| TC-W-01    | JobKind.CITATION_GRAPH in scheduler      | Wiring - registration    | Kind registered with CPU_NLP slot            | -              |
| TC-W-02    | Job handler executes process_citation    | Wiring - handler         | Handler calls process_citation_graph         | -              |
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.storage.database import Database


class TestEnqueueCitationGraphJob:
    """Tests for enqueue_citation_graph_job function."""

    @pytest.mark.asyncio
    async def test_enqueue_with_papers_creates_job(self, test_database: Database) -> None:
        """TC-N-01: Valid task_id with papers enqueues job."""
        # Given: Task exists
        db = test_database
        task_id = "task_cg_01"
        search_id = "sq_cg_01"

        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            (task_id, "Test query", "exploring"),
        )

        # When: Enqueue citation graph job
        with patch("src.scheduler.jobs.JobScheduler") as mock_scheduler_cls:
            mock_scheduler = MagicMock()
            mock_scheduler.submit = AsyncMock(return_value={"job_id": f"cg_{search_id}"})
            mock_scheduler_cls.return_value = mock_scheduler

            from src.research.citation_graph import enqueue_citation_graph_job

            job_id = await enqueue_citation_graph_job(
                task_id=task_id,
                search_id=search_id,
                query="Test query",
                paper_ids=["paper1", "paper2"],
            )

        # Then: Job should be enqueued
        assert job_id is not None
        mock_scheduler.submit.assert_called_once()

    @pytest.mark.asyncio
    async def test_enqueue_empty_papers_returns_none(self, test_database: Database) -> None:
        """TC-A-01: Empty paper_ids list returns None without enqueuing."""
        # Given: Empty paper_ids
        from src.research.citation_graph import enqueue_citation_graph_job

        # When: Enqueue with empty list
        job_id = await enqueue_citation_graph_job(
            task_id="task_cg_02",
            search_id="sq_cg_02",
            query="Test query",
            paper_ids=[],
        )

        # Then: No job enqueued
        assert job_id is None

    @pytest.mark.asyncio
    async def test_enqueue_duplicate_returns_none(self, test_database: Database) -> None:
        """TC-A-02: Duplicate job is not created."""
        import json

        # Given: Job already exists with matching search_id in input_json
        db = test_database
        task_id = "task_cg_03"
        search_id = "sq_cg_03"
        job_id = f"cg_{search_id}"

        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            (task_id, "Test query", "exploring"),
        )

        # Insert existing job with input_json containing the search_id
        input_json = json.dumps(
            {"task_id": task_id, "search_id": search_id, "query": "Test", "paper_ids": []}
        )
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, queued_at, input_json)
            VALUES (?, ?, 'citation_graph', 50, 'cpu_nlp', 'queued', datetime('now'), ?)
            """,
            (job_id, task_id, input_json),
        )

        # When: Try to enqueue again
        with patch("src.scheduler.jobs.JobScheduler") as mock_scheduler_cls:
            mock_scheduler = MagicMock()
            mock_scheduler.submit = AsyncMock(return_value={"job_id": "new_job"})
            mock_scheduler_cls.return_value = mock_scheduler

            from src.research.citation_graph import enqueue_citation_graph_job

            result = await enqueue_citation_graph_job(
                task_id=task_id,
                search_id=search_id,
                query="Test query",
                paper_ids=["paper1"],
            )

        # Then: No new job created
        assert result is None
        mock_scheduler.submit.assert_not_called()


class TestJobKindCitationGraph:
    """Tests for CITATION_GRAPH job kind registration."""

    def test_citation_graph_kind_registered(self) -> None:
        """TC-W-01: CITATION_GRAPH is registered with CPU_NLP slot."""
        from src.scheduler.jobs import KIND_PRIORITY, KIND_TO_SLOT, JobKind, Slot

        # Given/When: Check job kind registration
        # Then: CITATION_GRAPH should be registered
        assert JobKind.CITATION_GRAPH in KIND_TO_SLOT
        assert KIND_TO_SLOT[JobKind.CITATION_GRAPH] == Slot.CPU_NLP
        assert JobKind.CITATION_GRAPH in KIND_PRIORITY
        assert KIND_PRIORITY[JobKind.CITATION_GRAPH] == 50

    @pytest.mark.asyncio
    async def test_job_handler_calls_process(self) -> None:
        """TC-W-02: Job handler calls process_citation_graph."""
        # Given: Job input data
        from src.scheduler.jobs import JobKind, JobScheduler

        scheduler = JobScheduler()
        input_data = {
            "task_id": "task_cg_handler",
            "search_id": "sq_cg_handler",
            "query": "Test query",
            "paper_ids": ["paper1"],
        }

        # When: Execute job
        with patch("src.research.citation_graph.process_citation_graph") as mock_process:
            mock_process.return_value = {"ok": True, "papers_processed": 1}

            result = await scheduler._execute_job(
                kind=JobKind.CITATION_GRAPH,
                input_data=input_data,
                task_id="task_cg_handler",
                cause_id="test_cause",
            )

        # Then: process_citation_graph was called
        mock_process.assert_called_once_with(**input_data)
        assert result["ok"] is True


class TestProcessCitationGraph:
    """Tests for process_citation_graph function."""

    @pytest.mark.asyncio
    async def test_process_returns_stats(self, test_database: Database) -> None:
        """TC-N-02: process_citation_graph returns processing stats."""
        # Given: Task with page data
        db = test_database
        task_id = "task_cg_process"

        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            (task_id, "Test query", "exploring"),
        )

        # When: Process citation graph with no papers (edge case)
        from src.research.citation_graph import process_citation_graph

        # Create a mock that properly handles async context
        mock_provider = MagicMock()
        mock_provider.close = AsyncMock()

        # Patch at the source module since the import is inside the function
        with patch.object(
            __import__("src.search.academic_provider", fromlist=["AcademicSearchProvider"]),
            "AcademicSearchProvider",
            return_value=mock_provider,
        ):
            result = await process_citation_graph(
                task_id=task_id,
                search_id="sq_process",
                query="Test query",
                paper_ids=[],
            )

        # Then: Result has expected structure
        assert result["ok"] is True
        assert "papers_processed" in result
        assert "citations_found" in result
        assert "edges_created" in result
