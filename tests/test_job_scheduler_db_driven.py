"""
Tests for DB-driven JobScheduler (restart reset, atomic claim, TARGET_QUEUE).

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-RS-01 | Startup with no stale jobs | Normal - empty | No jobs reset | baseline |
| TC-RS-02 | Startup with queued jobs | Normal - stale | queued→failed | restart_policy=fail_all |
| TC-RS-03 | Startup with running jobs | Normal - stale | running→failed | crash recovery |
| TC-RS-04 | Startup with completed jobs | Boundary | completed NOT changed | only active states |
| TC-RS-05 | Startup with cancelled jobs | Boundary | cancelled NOT changed | only active states |
| TC-CL-01 | Claim next job with queued | Normal | job claimed, state=running | atomic claim |
| TC-CL-02 | Claim with no queued jobs | Boundary - empty | returns None | no work |
| TC-CL-03 | Priority ordering | Normal | lower priority first | ORDER BY priority |
| TC-CL-04 | Concurrent claims (race) | Boundary - race | only one wins | atomic UPDATE |
| TC-CL-05 | Slot concurrency limit | Boundary - limit | respects SLOT_LIMITS | no over-claim |
| TC-TQ-01 | TARGET_QUEUE kind=query | Wiring | routes to search_action | ADR-0010 |
| TC-TQ-02 | TARGET_QUEUE kind=url | Wiring | routes to ingest_url_action | ADR-0010 |
| TC-TQ-03 | TARGET_QUEUE kind=doi | Wiring | routes to ingest_doi_action | ADR-0010 |
| TC-TQ-04 | Successful target completion | Effect | VERIFY_NLI enqueued | ADR-0005 |
| TC-TQ-05 | Target completion | Effect | queue empty check runs | ADR-0007 |
| TC-TQ-06 | Missing task_id | Boundary - error | ValueError raised | required field |
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from src.storage.database import Database

pytestmark = pytest.mark.integration


class TestJobSchedulerStartupReset:
    """Tests for JobScheduler startup reset (fail_all policy)."""

    @pytest.mark.asyncio
    async def test_startup_with_no_stale_jobs(self, test_database: Database) -> None:
        """
        TC-RS-01: Startup with no stale jobs resets nothing.

        // Given: No queued/running jobs in DB
        // When: JobScheduler._reset_inflight_jobs_on_startup is called
        // Then: No jobs are changed
        """
        from src.scheduler.jobs import JobScheduler

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_rs01", "Test task", "exploring"),
        )

        # Add only completed job
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, queued_at, finished_at)
            VALUES (?, ?, 'target_queue', 25, 'network_client', 'completed', datetime('now'), datetime('now'))
            """,
            ("job_rs01", "task_rs01"),
        )

        # When: Reset is called
        scheduler = JobScheduler()
        await scheduler._reset_inflight_jobs_on_startup()

        # Then: Completed job is unchanged
        row = await db.fetch_one(
            "SELECT state FROM jobs WHERE id = ?",
            ("job_rs01",),
        )
        assert row is not None
        assert row["state"] == "completed"

    @pytest.mark.asyncio
    async def test_startup_resets_queued_to_failed(self, test_database: Database) -> None:
        """
        TC-RS-02: Startup with queued jobs resets them to failed.

        // Given: Queued job in DB
        // When: JobScheduler._reset_inflight_jobs_on_startup is called
        // Then: Job state is 'failed' with error_message='server_restart_reset'
        """
        from src.scheduler.jobs import JobScheduler

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_rs02", "Test task", "exploring"),
        )

        # Add queued job
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, queued_at)
            VALUES (?, ?, 'target_queue', 25, 'network_client', 'queued', datetime('now'))
            """,
            ("job_rs02", "task_rs02"),
        )

        # When: Reset is called
        scheduler = JobScheduler()
        await scheduler._reset_inflight_jobs_on_startup()

        # Then: Job is failed with restart message
        row = await db.fetch_one(
            "SELECT state, error_message, finished_at FROM jobs WHERE id = ?",
            ("job_rs02",),
        )
        assert row is not None
        assert row["state"] == "failed"
        assert row["error_message"] == "server_restart_reset"
        assert row["finished_at"] is not None

    @pytest.mark.asyncio
    async def test_startup_resets_running_to_failed(self, test_database: Database) -> None:
        """
        TC-RS-03: Startup with running jobs resets them to failed.

        // Given: Running job in DB (simulating crash)
        // When: JobScheduler._reset_inflight_jobs_on_startup is called
        // Then: Job state is 'failed' with error_message='server_restart_reset'
        """
        from src.scheduler.jobs import JobScheduler

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_rs03", "Test task", "exploring"),
        )

        # Add running job
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, queued_at, started_at)
            VALUES (?, ?, 'citation_graph', 50, 'cpu_nlp', 'running', datetime('now'), datetime('now'))
            """,
            ("job_rs03", "task_rs03"),
        )

        # When: Reset is called
        scheduler = JobScheduler()
        await scheduler._reset_inflight_jobs_on_startup()

        # Then: Job is failed with restart message
        row = await db.fetch_one(
            "SELECT state, error_message FROM jobs WHERE id = ?",
            ("job_rs03",),
        )
        assert row is not None
        assert row["state"] == "failed"
        assert row["error_message"] == "server_restart_reset"

    @pytest.mark.asyncio
    async def test_startup_does_not_change_completed_jobs(self, test_database: Database) -> None:
        """
        TC-RS-04: Startup does not change completed jobs.

        // Given: Completed job in DB
        // When: JobScheduler._reset_inflight_jobs_on_startup is called
        // Then: Job state remains 'completed'
        """
        from src.scheduler.jobs import JobScheduler

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_rs04", "Test task", "exploring"),
        )

        # Add completed job
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, queued_at, finished_at, output_json)
            VALUES (?, ?, 'verify_nli', 45, 'cpu_nlp', 'completed', datetime('now'), datetime('now'), '{}')
            """,
            ("job_rs04", "task_rs04"),
        )

        # When: Reset is called
        scheduler = JobScheduler()
        await scheduler._reset_inflight_jobs_on_startup()

        # Then: Job remains completed
        row = await db.fetch_one(
            "SELECT state FROM jobs WHERE id = ?",
            ("job_rs04",),
        )
        assert row is not None
        assert row["state"] == "completed"

    @pytest.mark.asyncio
    async def test_startup_does_not_change_cancelled_jobs(self, test_database: Database) -> None:
        """
        TC-RS-05: Startup does not change cancelled jobs.

        // Given: Cancelled job in DB
        // When: JobScheduler._reset_inflight_jobs_on_startup is called
        // Then: Job state remains 'cancelled'
        """
        from src.scheduler.jobs import JobScheduler

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_rs05", "Test task", "exploring"),
        )

        # Add cancelled job
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, queued_at, finished_at)
            VALUES (?, ?, 'target_queue', 25, 'network_client', 'cancelled', datetime('now'), datetime('now'))
            """,
            ("job_rs05", "task_rs05"),
        )

        # When: Reset is called
        scheduler = JobScheduler()
        await scheduler._reset_inflight_jobs_on_startup()

        # Then: Job remains cancelled
        row = await db.fetch_one(
            "SELECT state FROM jobs WHERE id = ?",
            ("job_rs05",),
        )
        assert row is not None
        assert row["state"] == "cancelled"


class TestJobSchedulerClaim:
    """Tests for JobScheduler atomic claim mechanism."""

    @pytest.mark.asyncio
    async def test_claim_next_job_with_queued(self, test_database: Database) -> None:
        """
        TC-CL-01: Claiming next job when queued jobs exist.

        // Given: Queued job for target slot
        // When: _claim_next_job is called
        // Then: Job is claimed (state=running), input_data returned
        """
        from src.scheduler.jobs import JobScheduler, Slot

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_cl01", "Test task", "exploring"),
        )

        # Add queued job
        input_data = {"query": "test query", "options": {}}
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, queued_at, input_json, cause_id)
            VALUES (?, ?, 'target_queue', 25, 'network_client', 'queued', datetime('now'), ?, ?)
            """,
            ("job_cl01", "task_cl01", json.dumps(input_data), "cause_01"),
        )

        # When: Claim next job
        scheduler = JobScheduler()
        claimed = await scheduler._claim_next_job(Slot.NETWORK_CLIENT)

        # Then: Job is claimed
        assert claimed is not None
        job_id, kind, returned_input, task_id, cause_id = claimed
        assert job_id == "job_cl01"
        assert returned_input == input_data
        assert task_id == "task_cl01"
        assert cause_id == "cause_01"

        # Verify DB state is now running
        row = await db.fetch_one(
            "SELECT state, started_at FROM jobs WHERE id = ?",
            ("job_cl01",),
        )
        assert row is not None
        assert row["state"] == "running"
        assert row["started_at"] is not None

    @pytest.mark.asyncio
    async def test_claim_with_no_queued_jobs_returns_none(self, test_database: Database) -> None:
        """
        TC-CL-02: Claiming when no queued jobs exist returns None.

        // Given: No queued jobs for target slot
        // When: _claim_next_job is called
        // Then: Returns None
        """
        from src.scheduler.jobs import JobScheduler, Slot

        db = test_database

        # Create task with only completed job
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_cl02", "Test task", "exploring"),
        )
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, queued_at, finished_at)
            VALUES (?, ?, 'target_queue', 25, 'network_client', 'completed', datetime('now'), datetime('now'))
            """,
            ("job_cl02", "task_cl02"),
        )

        # When: Claim next job
        scheduler = JobScheduler()
        claimed = await scheduler._claim_next_job(Slot.NETWORK_CLIENT)

        # Then: No job claimed
        assert claimed is None

    @pytest.mark.asyncio
    async def test_claim_respects_priority_ordering(self, test_database: Database) -> None:
        """
        TC-CL-03: Claims respect priority ordering (lower priority value first).

        // Given: Multiple queued jobs with different priorities
        // When: _claim_next_job is called
        // Then: Lower priority value job is claimed first
        """
        from src.scheduler.jobs import JobScheduler, Slot

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_cl03", "Test task", "exploring"),
        )

        # Add queued jobs with different priorities
        # Lower priority value = higher priority
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, queued_at, input_json)
            VALUES (?, ?, 'target_queue', 50, 'network_client', 'queued', datetime('now'), '{}')
            """,
            ("job_cl03_low", "task_cl03"),
        )
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, queued_at, input_json)
            VALUES (?, ?, 'target_queue', 10, 'network_client', 'queued', datetime('now'), '{}')
            """,
            ("job_cl03_high", "task_cl03"),
        )

        # When: Claim next job
        scheduler = JobScheduler()
        claimed = await scheduler._claim_next_job(Slot.NETWORK_CLIENT)

        # Then: Higher priority job (lower value) is claimed
        assert claimed is not None
        job_id, *_ = claimed
        assert job_id == "job_cl03_high"

    @pytest.mark.asyncio
    async def test_claim_respects_slot_concurrency_limit(self, test_database: Database) -> None:
        """
        TC-CL-05: Claim respects slot concurrency limits.

        // Given: Slot is at capacity (running jobs = limit)
        // When: _claim_next_job is called
        // Then: Returns None (no over-claim)
        """
        from src.scheduler.jobs import SLOT_LIMITS, JobScheduler, Slot

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_cl05", "Test task", "exploring"),
        )

        # Fill up GPU slot (limit = 1)
        gpu_limit = SLOT_LIMITS[Slot.GPU]
        for i in range(gpu_limit):
            await db.execute(
                """
                INSERT INTO jobs (id, task_id, kind, priority, slot, state, queued_at, started_at, input_json)
                VALUES (?, ?, 'embed', 40, 'gpu', 'running', datetime('now'), datetime('now'), '{}')
                """,
                (f"job_cl05_running_{i}", "task_cl05"),
            )

        # Add queued job for GPU
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, queued_at, input_json)
            VALUES (?, ?, 'embed', 40, 'gpu', 'queued', datetime('now'), '{}')
            """,
            ("job_cl05_queued", "task_cl05"),
        )

        # When: Claim next job
        scheduler = JobScheduler()
        claimed = await scheduler._claim_next_job(Slot.GPU)

        # Then: No job claimed (at capacity)
        assert claimed is None


class TestJobSchedulerCancelRunning:
    """Tests for JobScheduler cancel_running_jobs_for_task."""

    @pytest.mark.asyncio
    async def test_cancel_running_jobs_for_task(self, test_database: Database) -> None:
        """
        Test cancelling running jobs for a specific task.

        // Given: Scheduler with running task registered
        // When: cancel_running_jobs_for_task is called
        // Then: Task is cancelled and count returned
        """
        from src.scheduler.jobs import JobScheduler

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_cancel_01", "Test task", "exploring"),
        )

        # Create a running job in DB
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, queued_at, started_at, input_json)
            VALUES (?, ?, 'citation_graph', 50, 'cpu_nlp', 'running', datetime('now'), datetime('now'), '{}')
            """,
            ("job_cancel_01", "task_cancel_01"),
        )

        scheduler = JobScheduler()
        cancel_flag = {"cancelled": False}

        # Create a mock running task
        async def mock_job() -> None:
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancel_flag["cancelled"] = True
                raise

        task = asyncio.create_task(mock_job())
        scheduler._running_tasks["job_cancel_01"] = task
        scheduler._job_start_times["job_cancel_01"] = 12345.0

        # When: Cancel running jobs
        cancelled_count = await scheduler.cancel_running_jobs_for_task("task_cancel_01")

        # Wait a bit for the cancellation to propagate
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except (asyncio.CancelledError, TimeoutError):
            pass

        # Then: Task was cancelled
        assert cancelled_count == 1
        assert cancel_flag["cancelled"] is True
        assert task.cancelled() or task.done()


class TestJobSchedulerTargetQueueExecution:
    """Tests for JobScheduler TARGET_QUEUE execution (ADR-0010 unified execution).

    Test Perspectives Table:
    | Case ID    | Input / Precondition               | Perspective              | Expected Result                     | Notes      |
    |------------|-------------------------------------|--------------------------|-------------------------------------|------------|
    | TC-TQ-01   | kind=query                          | Wiring - route           | search_action called                | basic      |
    | TC-TQ-02   | kind=url                            | Wiring - route           | ingest_url_action called            | basic      |
    | TC-TQ-03   | kind=doi                            | Wiring - route           | ingest_doi_action called            | basic      |
    | TC-TQ-04   | successful completion               | Effect - NLI enqueue     | _enqueue_verify_nli called          | basic      |
    | TC-TQ-05   | successful completion               | Effect - empty check     | _check_target_queue_empty called    | basic      |
    | TC-TQ-06   | task_id=None                        | Boundary - NULL          | ValueError raised                   | negative   |
    | TC-TQ-07   | slot_worker_id=0, num_workers=2     | Wiring - worker_id       | worker_id=0 in options              | ADR-0014   |
    | TC-TQ-08   | slot_worker_id=1, num_workers=2     | Wiring - worker_id       | worker_id=1 in options              | ADR-0014   |
    | TC-TQ-09   | slot_worker_id=3, num_workers=2     | Boundary - modulo        | worker_id=1 (3%2) in options        | ADR-0014   |
    | TC-TQ-10   | kind=url, slot_worker_id=1          | Wiring - worker_id URL   | worker_id propagated to ingest_url  | ADR-0014   |
    | TC-TQ-11   | kind=doi, slot_worker_id=1          | Wiring - worker_id DOI   | worker_id propagated to ingest_doi  | ADR-0014   |
    """

    @pytest.mark.asyncio
    async def test_execute_target_queue_query_routes_to_search_action(
        self, test_database: Database
    ) -> None:
        """
        TC-TQ-01: TARGET_QUEUE with kind=query routes to search_action.

        // Given: TARGET_QUEUE job with target.kind='query'
        // When: _execute_target_queue_job is called
        // Then: search_action is called with correct parameters (wiring check)
        """
        from unittest.mock import AsyncMock, patch

        from src.scheduler.jobs import JobScheduler

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_tq01", "Test hypothesis", "exploring"),
        )

        scheduler = JobScheduler()
        input_data = {
            "target": {"kind": "query", "query": "test query", "options": {}},
            "options": {"budget_pages": 10},
        }

        # Mock dependencies
        mock_search = AsyncMock(return_value={"ok": True, "status": "completed"})
        mock_state = AsyncMock()
        mock_state.notify_status_change = lambda: None

        with (
            patch("src.mcp.helpers.get_exploration_state", return_value=mock_state),
            patch("src.research.pipeline.search_action", mock_search),
            patch.object(scheduler, "_enqueue_verify_nli_if_needed", new_callable=AsyncMock),
            patch.object(scheduler, "_check_target_queue_empty", new_callable=AsyncMock),
        ):
            await scheduler._execute_target_queue_job(
                input_data=input_data,
                task_id="task_tq01",
                cause_id="cause_01",
            )

        # Then: search_action was called
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args
        assert call_kwargs.kwargs["task_id"] == "task_tq01"
        assert call_kwargs.kwargs["query"] == "test query"
        assert "budget_pages" in call_kwargs.kwargs["options"]

    @pytest.mark.asyncio
    async def test_execute_target_queue_url_routes_to_ingest_url_action(
        self, test_database: Database
    ) -> None:
        """
        TC-TQ-02: TARGET_QUEUE with kind=url routes to ingest_url_action.

        // Given: TARGET_QUEUE job with target.kind='url'
        // When: _execute_target_queue_job is called
        // Then: ingest_url_action is called with correct parameters (wiring check)
        """
        from unittest.mock import AsyncMock, patch

        from src.scheduler.jobs import JobScheduler

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_tq02", "Test hypothesis", "exploring"),
        )

        scheduler = JobScheduler()
        input_data = {
            "target": {
                "kind": "url",
                "url": "https://example.com/paper",
                "depth": 1,
                "reason": "citation_chase",
                "context": {"source_page_id": "page_src"},
                "policy": {},
            },
            "options": {},
        }

        # Mock dependencies
        mock_ingest = AsyncMock(return_value={"ok": True, "status": "completed"})
        mock_state = AsyncMock()
        mock_state.notify_status_change = lambda: None

        with (
            patch("src.mcp.helpers.get_exploration_state", return_value=mock_state),
            patch("src.research.pipeline.ingest_url_action", mock_ingest),
            patch.object(scheduler, "_enqueue_verify_nli_if_needed", new_callable=AsyncMock),
            patch.object(scheduler, "_check_target_queue_empty", new_callable=AsyncMock),
        ):
            await scheduler._execute_target_queue_job(
                input_data=input_data,
                task_id="task_tq02",
                cause_id="cause_02",
            )

        # Then: ingest_url_action was called
        mock_ingest.assert_called_once()
        call_kwargs = mock_ingest.call_args
        assert call_kwargs.kwargs["task_id"] == "task_tq02"
        assert call_kwargs.kwargs["url"] == "https://example.com/paper"
        assert call_kwargs.kwargs["depth"] == 1
        assert call_kwargs.kwargs["reason"] == "citation_chase"

    @pytest.mark.asyncio
    async def test_execute_target_queue_doi_routes_to_ingest_doi_action(
        self, test_database: Database
    ) -> None:
        """
        TC-TQ-03: TARGET_QUEUE with kind=doi routes to ingest_doi_action.

        // Given: TARGET_QUEUE job with target.kind='doi'
        // When: _execute_target_queue_job is called
        // Then: ingest_doi_action is called with correct parameters (wiring check)
        """
        from unittest.mock import AsyncMock, patch

        from src.scheduler.jobs import JobScheduler

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_tq03", "Test hypothesis", "exploring"),
        )

        scheduler = JobScheduler()
        input_data = {
            "target": {
                "kind": "doi",
                "doi": "10.1234/test",
                "reason": "citation_chase",
                "context": {},
            },
            "options": {},
        }

        # Mock dependencies
        mock_ingest_doi = AsyncMock(return_value={"ok": True, "status": "completed"})
        mock_state = AsyncMock()
        mock_state.notify_status_change = lambda: None

        with (
            patch("src.mcp.helpers.get_exploration_state", return_value=mock_state),
            patch("src.research.pipeline.ingest_doi_action", mock_ingest_doi),
            patch.object(scheduler, "_enqueue_verify_nli_if_needed", new_callable=AsyncMock),
            patch.object(scheduler, "_check_target_queue_empty", new_callable=AsyncMock),
        ):
            await scheduler._execute_target_queue_job(
                input_data=input_data,
                task_id="task_tq03",
                cause_id="cause_03",
            )

        # Then: ingest_doi_action was called
        mock_ingest_doi.assert_called_once()
        call_kwargs = mock_ingest_doi.call_args
        assert call_kwargs.kwargs["task_id"] == "task_tq03"
        assert call_kwargs.kwargs["doi"] == "10.1234/test"
        assert call_kwargs.kwargs["reason"] == "citation_chase"

    @pytest.mark.asyncio
    async def test_verify_nli_enqueued_after_successful_target(
        self, test_database: Database
    ) -> None:
        """
        TC-TQ-04: VERIFY_NLI is enqueued after successful target completion.

        // Given: TARGET_QUEUE job that completes successfully
        // When: _execute_target_queue_job completes
        // Then: _enqueue_verify_nli_if_needed is called (effect check)
        """
        from unittest.mock import AsyncMock, patch

        from src.scheduler.jobs import JobScheduler

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_tq04", "Test hypothesis", "exploring"),
        )

        scheduler = JobScheduler()
        input_data = {
            "target": {"kind": "query", "query": "test", "options": {}},
            "options": {},
        }

        mock_state = AsyncMock()
        mock_state.notify_status_change = lambda: None
        mock_enqueue = AsyncMock()

        with (
            patch("src.mcp.helpers.get_exploration_state", return_value=mock_state),
            patch(
                "src.research.pipeline.search_action",
                AsyncMock(return_value={"ok": True, "status": "completed"}),
            ),
            patch.object(scheduler, "_enqueue_verify_nli_if_needed", mock_enqueue),
            patch.object(scheduler, "_check_target_queue_empty", new_callable=AsyncMock),
        ):
            await scheduler._execute_target_queue_job(
                input_data=input_data,
                task_id="task_tq04",
                cause_id="cause_04",
            )

        # Then: VERIFY_NLI was enqueued
        mock_enqueue.assert_called_once_with("task_tq04", {"ok": True, "status": "completed"})

    @pytest.mark.asyncio
    async def test_target_queue_empty_checked_after_completion(
        self, test_database: Database
    ) -> None:
        """
        TC-TQ-05: Target queue empty check runs after job completion.

        // Given: TARGET_QUEUE job
        // When: _execute_target_queue_job completes
        // Then: _check_target_queue_empty is called (effect check)
        """
        from unittest.mock import AsyncMock, patch

        from src.scheduler.jobs import JobScheduler

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_tq05", "Test hypothesis", "exploring"),
        )

        scheduler = JobScheduler()
        input_data = {
            "target": {"kind": "query", "query": "test", "options": {}},
            "options": {},
        }

        mock_state = AsyncMock()
        mock_state.notify_status_change = lambda: None
        mock_check_empty = AsyncMock()

        with (
            patch("src.mcp.helpers.get_exploration_state", return_value=mock_state),
            patch(
                "src.research.pipeline.search_action",
                AsyncMock(return_value={"ok": True, "status": "completed"}),
            ),
            patch.object(scheduler, "_enqueue_verify_nli_if_needed", new_callable=AsyncMock),
            patch.object(scheduler, "_check_target_queue_empty", mock_check_empty),
        ):
            await scheduler._execute_target_queue_job(
                input_data=input_data,
                task_id="task_tq05",
                cause_id="cause_05",
            )

        # Then: Empty check was called
        mock_check_empty.assert_called_once_with("task_tq05")

    @pytest.mark.asyncio
    async def test_missing_task_id_raises_error(self) -> None:
        """
        TC-TQ-06: TARGET_QUEUE without task_id raises ValueError.

        // Given: TARGET_QUEUE job without task_id
        // When: _execute_target_queue_job is called
        // Then: ValueError is raised
        """
        from src.scheduler.jobs import JobScheduler

        scheduler = JobScheduler()
        input_data = {
            "target": {"kind": "query", "query": "test"},
            "options": {},
        }

        with pytest.raises(ValueError, match="task_id is required"):
            await scheduler._execute_target_queue_job(
                input_data=input_data,
                task_id=None,
                cause_id="cause_06",
            )

    @pytest.mark.asyncio
    async def test_worker_id_propagation_query_worker_0(self, test_database: Database) -> None:
        """
        TC-TQ-07: worker_id=0 is propagated to search_action options.

        // Given: TARGET_QUEUE job with slot_worker_id=0, num_workers=2
        // When: _execute_target_queue_job is called
        // Then: options["worker_id"] = 0 (wiring check)
        """
        from unittest.mock import AsyncMock, patch

        from src.scheduler.jobs import JobScheduler

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_tq07", "Test hypothesis", "exploring"),
        )

        scheduler = JobScheduler()
        input_data = {
            "target": {"kind": "query", "query": "test query", "options": {}},
            "options": {},
        }

        mock_search = AsyncMock(return_value={"ok": True})
        mock_state = AsyncMock()
        mock_state.notify_status_change = lambda: None

        with (
            patch("src.mcp.helpers.get_exploration_state", return_value=mock_state),
            patch("src.research.pipeline.search_action", mock_search),
            patch("src.utils.config.get_num_workers", return_value=2),
            patch.object(scheduler, "_enqueue_verify_nli_if_needed", new_callable=AsyncMock),
            patch.object(scheduler, "_check_target_queue_empty", new_callable=AsyncMock),
        ):
            await scheduler._execute_target_queue_job(
                input_data=input_data,
                task_id="task_tq07",
                cause_id="cause_07",
                slot_worker_id=0,
            )

        # Then: worker_id=0 was propagated
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args.kwargs
        assert call_kwargs["options"]["worker_id"] == 0

    @pytest.mark.asyncio
    async def test_worker_id_propagation_query_worker_1(self, test_database: Database) -> None:
        """
        TC-TQ-08: worker_id=1 is propagated to search_action options.

        // Given: TARGET_QUEUE job with slot_worker_id=1, num_workers=2
        // When: _execute_target_queue_job is called
        // Then: options["worker_id"] = 1 (wiring check)
        """
        from unittest.mock import AsyncMock, patch

        from src.scheduler.jobs import JobScheduler

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_tq08", "Test hypothesis", "exploring"),
        )

        scheduler = JobScheduler()
        input_data = {
            "target": {"kind": "query", "query": "test query", "options": {}},
            "options": {},
        }

        mock_search = AsyncMock(return_value={"ok": True})
        mock_state = AsyncMock()
        mock_state.notify_status_change = lambda: None

        with (
            patch("src.mcp.helpers.get_exploration_state", return_value=mock_state),
            patch("src.research.pipeline.search_action", mock_search),
            patch("src.utils.config.get_num_workers", return_value=2),
            patch.object(scheduler, "_enqueue_verify_nli_if_needed", new_callable=AsyncMock),
            patch.object(scheduler, "_check_target_queue_empty", new_callable=AsyncMock),
        ):
            await scheduler._execute_target_queue_job(
                input_data=input_data,
                task_id="task_tq08",
                cause_id="cause_08",
                slot_worker_id=1,
            )

        # Then: worker_id=1 was propagated
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args.kwargs
        assert call_kwargs["options"]["worker_id"] == 1

    @pytest.mark.asyncio
    async def test_worker_id_modulo_calculation(self, test_database: Database) -> None:
        """
        TC-TQ-09: slot_worker_id >= num_workers applies modulo.

        // Given: TARGET_QUEUE job with slot_worker_id=3, num_workers=2
        // When: _execute_target_queue_job is called
        // Then: options["worker_id"] = 1 (3 % 2 = 1, boundary check)
        """
        from unittest.mock import AsyncMock, patch

        from src.scheduler.jobs import JobScheduler

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_tq09", "Test hypothesis", "exploring"),
        )

        scheduler = JobScheduler()
        input_data = {
            "target": {"kind": "query", "query": "test query", "options": {}},
            "options": {},
        }

        mock_search = AsyncMock(return_value={"ok": True})
        mock_state = AsyncMock()
        mock_state.notify_status_change = lambda: None

        with (
            patch("src.mcp.helpers.get_exploration_state", return_value=mock_state),
            patch("src.research.pipeline.search_action", mock_search),
            patch("src.utils.config.get_num_workers", return_value=2),
            patch.object(scheduler, "_enqueue_verify_nli_if_needed", new_callable=AsyncMock),
            patch.object(scheduler, "_check_target_queue_empty", new_callable=AsyncMock),
        ):
            await scheduler._execute_target_queue_job(
                input_data=input_data,
                task_id="task_tq09",
                cause_id="cause_09",
                slot_worker_id=3,  # 3 % 2 = 1
            )

        # Then: worker_id = 3 % 2 = 1
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args.kwargs
        assert call_kwargs["options"]["worker_id"] == 1

    @pytest.mark.asyncio
    async def test_worker_id_propagation_url_target(self, test_database: Database) -> None:
        """
        TC-TQ-10: worker_id is propagated to ingest_url_action options.

        // Given: TARGET_QUEUE job with kind=url, slot_worker_id=1
        // When: _execute_target_queue_job is called
        // Then: options["worker_id"] = 1 (wiring check for URL)
        """
        from unittest.mock import AsyncMock, patch

        from src.scheduler.jobs import JobScheduler

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_tq10", "Test hypothesis", "exploring"),
        )

        scheduler = JobScheduler()
        input_data = {
            "target": {
                "kind": "url",
                "url": "https://example.com/paper",
                "depth": 0,
                "reason": "manual",
                "context": {},
                "policy": {},
            },
            "options": {},
        }

        mock_ingest = AsyncMock(return_value={"ok": True})
        mock_state = AsyncMock()
        mock_state.notify_status_change = lambda: None

        with (
            patch("src.mcp.helpers.get_exploration_state", return_value=mock_state),
            patch("src.research.pipeline.ingest_url_action", mock_ingest),
            patch("src.utils.config.get_num_workers", return_value=2),
            patch.object(scheduler, "_enqueue_verify_nli_if_needed", new_callable=AsyncMock),
            patch.object(scheduler, "_check_target_queue_empty", new_callable=AsyncMock),
        ):
            await scheduler._execute_target_queue_job(
                input_data=input_data,
                task_id="task_tq10",
                cause_id="cause_10",
                slot_worker_id=1,
            )

        # Then: worker_id=1 was propagated to ingest_url_action
        mock_ingest.assert_called_once()
        call_kwargs = mock_ingest.call_args.kwargs
        assert call_kwargs["options"]["worker_id"] == 1

    @pytest.mark.asyncio
    async def test_worker_id_propagation_doi_target(self, test_database: Database) -> None:
        """
        TC-TQ-11: worker_id is propagated to ingest_doi_action options.

        // Given: TARGET_QUEUE job with kind=doi, slot_worker_id=1
        // When: _execute_target_queue_job is called
        // Then: options["worker_id"] = 1 (wiring check for DOI)
        """
        from unittest.mock import AsyncMock, patch

        from src.scheduler.jobs import JobScheduler

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_tq11", "Test hypothesis", "exploring"),
        )

        scheduler = JobScheduler()
        input_data = {
            "target": {
                "kind": "doi",
                "doi": "10.1234/test",
                "reason": "manual",
                "context": {},
            },
            "options": {},
        }

        mock_ingest_doi = AsyncMock(return_value={"ok": True})
        mock_state = AsyncMock()
        mock_state.notify_status_change = lambda: None

        with (
            patch("src.mcp.helpers.get_exploration_state", return_value=mock_state),
            patch("src.research.pipeline.ingest_doi_action", mock_ingest_doi),
            patch("src.utils.config.get_num_workers", return_value=2),
            patch.object(scheduler, "_enqueue_verify_nli_if_needed", new_callable=AsyncMock),
            patch.object(scheduler, "_check_target_queue_empty", new_callable=AsyncMock),
        ):
            await scheduler._execute_target_queue_job(
                input_data=input_data,
                task_id="task_tq11",
                cause_id="cause_11",
                slot_worker_id=1,
            )

        # Then: worker_id=1 was propagated to ingest_doi_action
        mock_ingest_doi.assert_called_once()
        call_kwargs = mock_ingest_doi.call_args.kwargs
        assert call_kwargs["options"]["worker_id"] == 1


class TestJobSchedulerSubmit:
    """Tests for JobScheduler.submit() edge cases.

    Test Perspectives Table (追加分):
    | Case ID    | Input / Precondition          | Perspective              | Expected Result                   | Notes      |
    |------------|-------------------------------|--------------------------|-----------------------------------|------------|
    | TC-SUB-01  | submit with string kind       | Boundary - type conv     | Converts to JobKind               | L249       |
    | TC-SUB-02  | submit with budget exceeded   | Normal - rejection       | accepted=False, reason=budget_*   | L269-281   |
    | TC-SUB-03  | submit exclusive slot busy    | Normal - rejection       | accepted=False, exclusive_slot    | L285-290   |
    """

    @pytest.mark.asyncio
    async def test_submit_with_string_kind(self, test_database: Database) -> None:
        """
        TC-SUB-01: submit() accepts string kind and converts to JobKind.

        // Given: Job submission with string kind
        // When: submit is called
        // Then: Kind is converted to JobKind enum and job is submitted
        """
        from unittest.mock import AsyncMock, patch

        from src.scheduler.jobs import JobScheduler

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_sub01", "Test task", "exploring"),
        )

        scheduler = JobScheduler()
        scheduler._budget_manager = None  # Skip budget check

        # Mock exclusivity check
        with patch.object(scheduler, "_check_exclusivity_db", AsyncMock(return_value=True)):
            # When: Submit with string kind
            result = await scheduler.submit(
                kind="target_queue",  # String, not JobKind
                input_data={"query": "test"},
                task_id="task_sub01",
            )

        # Then: Job was accepted
        assert result["accepted"] is True
        assert result["slot"] == "network_client"

    @pytest.mark.asyncio
    async def test_submit_rejected_by_budget(self, test_database: Database) -> None:
        """
        TC-SUB-02: submit() returns accepted=False when budget is exceeded.

        // Given: Task with exhausted budget
        // When: submit is called
        // Then: accepted=False with budget reason
        """
        from unittest.mock import AsyncMock

        from src.scheduler.budget import BudgetExceededReason
        from src.scheduler.jobs import JobKind, JobScheduler

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_sub02", "Test task", "exploring"),
        )

        scheduler = JobScheduler()

        # Mock budget check to return exceeded
        mock_budget_manager = AsyncMock()
        mock_budget_manager.check_and_update = AsyncMock(
            return_value=(False, BudgetExceededReason.TIME_LIMIT)
        )
        scheduler._budget_manager = mock_budget_manager

        # When: Submit job
        result = await scheduler.submit(
            kind=JobKind.TARGET_QUEUE,
            input_data={"query": "test"},
            task_id="task_sub02",
        )

        # Then: Job rejected with budget reason
        assert result["accepted"] is False
        assert "budget_" in result["reason"]

    @pytest.mark.asyncio
    async def test_submit_rejected_by_exclusive_slot(self, test_database: Database) -> None:
        """
        TC-SUB-03: submit() returns accepted=False when exclusive slot is busy.

        // Given: GPU slot busy (exclusive with BROWSER_HEADFUL)
        // When: submit BROWSER_HEADFUL job
        // Then: accepted=False with exclusive_slot_busy reason
        """
        from unittest.mock import AsyncMock, patch

        from src.scheduler.jobs import JobKind, JobScheduler

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_sub03", "Test task", "exploring"),
        )

        # Add running GPU job
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, queued_at, started_at, input_json)
            VALUES (?, ?, 'embed', 40, 'gpu', 'running', datetime('now'), datetime('now'), '{}')
            """,
            ("job_sub03_gpu", "task_sub03"),
        )

        scheduler = JobScheduler()
        scheduler._budget_manager = None  # Skip budget check

        # When: Submit job to exclusive slot (GPU and BROWSER_HEADFUL are exclusive)
        # Note: We can't directly submit to BROWSER_HEADFUL without mapping, so we check the actual logic
        with patch.object(scheduler, "_check_exclusivity_db", AsyncMock(return_value=False)):
            result = await scheduler.submit(
                kind=JobKind.EMBED,
                input_data={"texts": ["test"]},
                task_id="task_sub03",
            )

        # Then: Job rejected with exclusive slot reason
        assert result["accepted"] is False
        assert result["reason"] == "exclusive_slot_busy"


class TestJobSchedulerBudgetCheck:
    """Tests for JobScheduler._check_budget() branches.

    Test Perspectives Table:
    | Case ID    | Input / Precondition          | Perspective              | Expected Result                   | Notes      |
    |------------|-------------------------------|--------------------------|-----------------------------------|------------|
    | TC-BUD-01  | FETCH at page limit           | Boundary - limit         | returns False, PAGE_LIMIT         | L349-352   |
    | TC-BUD-02  | LLM at ratio limit            | Boundary - limit         | returns False, LLM_RATIO          | L355-360   |
    | TC-BUD-03  | No budget manager             | Boundary - None          | returns True, None                | L340-341   |
    """

    @pytest.mark.asyncio
    async def test_check_budget_fetch_at_page_limit(self, test_database: Database) -> None:
        """
        TC-BUD-01: _check_budget returns False for FETCH when page limit reached.

        // Given: Task at page limit
        // When: _check_budget called for FETCH job
        // Then: Returns (False, 'page_limit')
        """
        from unittest.mock import AsyncMock

        from src.scheduler.jobs import JobKind, JobScheduler

        scheduler = JobScheduler()

        # Mock budget manager
        mock_budget_manager = AsyncMock()
        mock_budget_manager.check_and_update = AsyncMock(return_value=(True, None))
        mock_budget_manager.can_fetch_page = AsyncMock(return_value=False)
        scheduler._budget_manager = mock_budget_manager

        # When: Check budget for FETCH
        can_proceed, reason = await scheduler._check_budget("task_bud01", JobKind.FETCH)

        # Then: Rejected due to page limit
        assert can_proceed is False
        assert reason == "page_limit_exceeded"

    @pytest.mark.asyncio
    async def test_check_budget_llm_at_ratio_limit(self, test_database: Database) -> None:
        """
        TC-BUD-02: _check_budget returns False for LLM when ratio limit reached.

        // Given: Task at LLM ratio limit
        // When: _check_budget called for LLM job
        // Then: Returns (False, 'llm_ratio')
        """
        from unittest.mock import AsyncMock

        from src.scheduler.jobs import JobKind, JobScheduler

        scheduler = JobScheduler()

        # Mock budget manager
        mock_budget_manager = AsyncMock()
        mock_budget_manager.check_and_update = AsyncMock(return_value=(True, None))
        mock_budget_manager.can_run_llm = AsyncMock(return_value=False)
        scheduler._budget_manager = mock_budget_manager

        # When: Check budget for LLM
        can_proceed, reason = await scheduler._check_budget("task_bud02", JobKind.LLM)

        # Then: Rejected due to LLM ratio
        assert can_proceed is False
        assert reason == "llm_ratio_exceeded"

    @pytest.mark.asyncio
    async def test_check_budget_with_no_manager(self) -> None:
        """
        TC-BUD-03: _check_budget returns True when no budget manager.

        // Given: No budget manager initialized
        // When: _check_budget called
        // Then: Returns (True, None) - no restriction
        """
        from src.scheduler.jobs import JobKind, JobScheduler

        scheduler = JobScheduler()
        scheduler._budget_manager = None

        # When: Check budget
        can_proceed, reason = await scheduler._check_budget("task_bud03", JobKind.TARGET_QUEUE)

        # Then: Allowed (no restriction)
        assert can_proceed is True
        assert reason is None


class TestJobSchedulerCancelJob:
    """Tests for JobScheduler.cancel_job().

    Test Perspectives Table:
    | Case ID    | Input / Precondition          | Perspective              | Expected Result                   | Notes      |
    |------------|-------------------------------|--------------------------|-----------------------------------|------------|
    | TC-CAN-01  | cancel_job for queued job     | Normal                   | returns True, state=cancelled     | L873-897   |
    | TC-CAN-02  | cancel_job for running job    | Boundary - invalid state | returns False (not cancelable)    | L890-891   |
    | TC-CAN-03  | cancel_job for nonexistent    | Boundary - not found     | returns False                     | L894       |
    """

    @pytest.mark.asyncio
    async def test_cancel_queued_job_succeeds(self, test_database: Database) -> None:
        """
        TC-CAN-01: cancel_job succeeds for queued job.

        // Given: Queued job exists
        // When: cancel_job is called
        // Then: Returns True, job state is cancelled
        """
        from src.scheduler.jobs import JobScheduler

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_can01", "Test task", "exploring"),
        )

        # Add queued job
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, queued_at, input_json)
            VALUES (?, ?, 'target_queue', 25, 'network_client', 'queued', datetime('now'), '{}')
            """,
            ("job_can01", "task_can01"),
        )

        scheduler = JobScheduler()

        # When: Cancel job
        result = await scheduler.cancel_job("job_can01")

        # Then: Success
        assert result is True

        # Verify state changed
        row = await db.fetch_one("SELECT state, finished_at FROM jobs WHERE id = ?", ("job_can01",))
        assert row is not None
        assert row["state"] == "cancelled"
        assert row["finished_at"] is not None

    @pytest.mark.asyncio
    async def test_cancel_running_job_fails(self, test_database: Database) -> None:
        """
        TC-CAN-02: cancel_job fails for running job (only pending/queued cancelable).

        // Given: Running job exists
        // When: cancel_job is called
        // Then: Returns False (cannot cancel running job via this method)
        """
        from src.scheduler.jobs import JobScheduler

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_can02", "Test task", "exploring"),
        )

        # Add running job
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, queued_at, started_at, input_json)
            VALUES (?, ?, 'citation_graph', 50, 'cpu_nlp', 'running', datetime('now'), datetime('now'), '{}')
            """,
            ("job_can02", "task_can02"),
        )

        scheduler = JobScheduler()

        # When: Cancel running job
        result = await scheduler.cancel_job("job_can02")

        # Then: Fails (running jobs need cancel_running_jobs_for_task)
        assert result is False

        # Verify state unchanged
        row = await db.fetch_one("SELECT state FROM jobs WHERE id = ?", ("job_can02",))
        assert row is not None
        assert row["state"] == "running"

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_job_fails(self, test_database: Database) -> None:
        """
        TC-CAN-03: cancel_job fails for nonexistent job.

        // Given: Job does not exist
        // When: cancel_job is called
        // Then: Returns False
        """
        from src.scheduler.jobs import JobScheduler

        scheduler = JobScheduler()

        # When: Cancel nonexistent job
        result = await scheduler.cancel_job("nonexistent_job_id")

        # Then: Fails
        assert result is False


class TestJobSchedulerClaimEdgeCases:
    """Tests for JobScheduler._claim_next_job() edge cases.

    Test Perspectives Table:
    | Case ID    | Input / Precondition          | Perspective              | Expected Result                   | Notes      |
    |------------|-------------------------------|--------------------------|-----------------------------------|------------|
    | TC-CL-06   | Malformed input_json          | Boundary - parse error   | Falls back to eval/empty dict     | L497-501   |
    | TC-CL-07   | Python dict literal input_json| Boundary - eval fallback | Parses via eval                   | L498-499   |
    """

    @pytest.mark.asyncio
    async def test_claim_with_python_dict_input_json(self, test_database: Database) -> None:
        """
        TC-CL-07: _claim_next_job handles Python dict literal in input_json.

        // Given: Job with Python dict literal (not JSON) in input_json
        // When: _claim_next_job is called
        // Then: Falls back to eval() and parses successfully
        """
        from src.scheduler.jobs import JobScheduler, Slot

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_cl07", "Test task", "exploring"),
        )

        # Add job with Python dict literal (single quotes, not JSON)
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, queued_at, input_json)
            VALUES (?, ?, 'target_queue', 25, 'network_client', 'queued', datetime('now'), ?)
            """,
            ("job_cl07", "task_cl07", "{'key': 'value'}"),  # Python dict, not JSON
        )

        scheduler = JobScheduler()

        # When: Claim job
        claimed = await scheduler._claim_next_job(Slot.NETWORK_CLIENT)

        # Then: Job claimed with parsed input
        assert claimed is not None
        job_id, kind, input_data, task_id, cause_id = claimed
        assert job_id == "job_cl07"
        assert input_data == {"key": "value"}

    @pytest.mark.asyncio
    async def test_claim_with_invalid_input_json(self, test_database: Database) -> None:
        """
        TC-CL-06: _claim_next_job handles completely invalid input_json.

        // Given: Job with unparseable input_json
        // When: _claim_next_job is called
        // Then: Falls back to empty dict
        """
        from src.scheduler.jobs import JobScheduler, Slot

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_cl06", "Test task", "exploring"),
        )

        # Add job with completely invalid input_json
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, queued_at, input_json)
            VALUES (?, ?, 'target_queue', 25, 'network_client', 'queued', datetime('now'), ?)
            """,
            ("job_cl06", "task_cl06", "not valid at all {{{"),
        )

        scheduler = JobScheduler()

        # When: Claim job
        claimed = await scheduler._claim_next_job(Slot.NETWORK_CLIENT)

        # Then: Job claimed with empty dict fallback
        assert claimed is not None
        job_id, kind, input_data, task_id, cause_id = claimed
        assert job_id == "job_cl06"
        assert input_data == {}
