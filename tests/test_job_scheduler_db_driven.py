"""
Tests for DB-driven JobScheduler (restart reset and atomic claim).

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
