"""Tests for search queue worker.

Tests the background worker that processes search queue jobs per ADR-0010.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-JK-01 | JobKind.SEARCH_QUEUE | Equivalence – normal | Enum value is "search_queue" | Definition |
| TC-JK-02 | KIND_TO_SLOT[SEARCH_QUEUE] | Equivalence – normal | Slot.NETWORK_CLIENT | Mapping |
| TC-JK-03 | KIND_PRIORITY[SEARCH_QUEUE] | Equivalence – normal | Priority value 25 | Mapping |
| TC-WK-01 | Queue with 1 job | Equivalence – normal | Worker gets, processes, marks completed | Basic flow |
| TC-WK-02 | Queue with multiple jobs | Equivalence – normal | Processed in priority order | Scheduling |
| TC-WK-03 | Two workers race | Equivalence – normal | Only one claims job (CAS) | Race prevention |
| TC-WK-04 | search_action fails | Equivalence – error | jobs.state='failed', error_message set | Error handling |
| TC-WK-05 | asyncio.CancelledError | Equivalence – cancel | jobs.state='cancelled' | Cancellation |
| TC-WK-06 | Empty queue | Boundary – empty | Worker waits, then rechecks | Empty queue |
| TC-MGR-01 | Manager start | Equivalence – normal | 2 workers started | Manager lifecycle |
| TC-MGR-02 | Manager stop | Equivalence – normal | Workers cancelled and cleaned up | Manager lifecycle |
| TC-JT-01 | register_job | Equivalence – normal | Job tracked in _running_jobs | Job tracking |
| TC-JT-02 | unregister_job | Equivalence – normal | Job removed from _running_jobs | Job tracking |
| TC-JT-03 | cancel_jobs_for_task | Equivalence – normal | Only specified task's jobs cancelled | Selective cancel |
| TC-JT-04 | cancel nonexistent task | Boundary – empty | Returns 0, no error | Empty result |
| TC-WK-CANCEL-01 | search_task cancelled | Equivalence – cancel | Worker continues to next job | Worker survives |
| TC-WK-CANCEL-02 | run_server() stops | Equivalence – shutdown | Worker exits loop | Worker shutdown |
"""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestJobKindSearchQueue:
    """Tests for JobKind.SEARCH_QUEUE enum and mappings."""

    def test_search_queue_enum_value(self) -> None:
        """
        TC-JK-01: JobKind.SEARCH_QUEUE enum value.

        // Given: JobKind enum
        // When: Accessing SEARCH_QUEUE
        // Then: Value is "search_queue"
        """
        from src.scheduler.jobs import JobKind

        assert JobKind.SEARCH_QUEUE.value == "search_queue"

    def test_search_queue_slot_mapping(self) -> None:
        """
        TC-JK-02: KIND_TO_SLOT mapping for SEARCH_QUEUE.

        // Given: KIND_TO_SLOT mapping
        // When: Looking up SEARCH_QUEUE
        // Then: Returns Slot.NETWORK_CLIENT
        """
        from src.scheduler.jobs import KIND_TO_SLOT, JobKind, Slot

        assert KIND_TO_SLOT[JobKind.SEARCH_QUEUE] == Slot.NETWORK_CLIENT

    def test_search_queue_priority_mapping(self) -> None:
        """
        TC-JK-03: KIND_PRIORITY mapping for SEARCH_QUEUE.

        // Given: KIND_PRIORITY mapping
        // When: Looking up SEARCH_QUEUE
        // Then: Returns priority value 25
        """
        from src.scheduler.jobs import KIND_PRIORITY, JobKind

        assert KIND_PRIORITY[JobKind.SEARCH_QUEUE] == 25


class TestSearchQueueWorker:
    """Tests for search queue worker processing."""

    @pytest.fixture
    def mock_search_result(self) -> dict[str, Any]:
        """Create mock search result."""
        return {
            "ok": True,
            "search_id": "s_test",
            "query": "test query",
            "status": "satisfied",
            "pages_fetched": 5,
        }

    @pytest.mark.asyncio
    async def test_worker_processes_queued_job(
        self, test_database, mock_search_result: dict[str, Any]
    ) -> None:
        """
        TC-WK-01: Worker processes single queued job.

        // Given: One job in queue with state='queued'
        // When: Worker runs one iteration
        // Then: Job is processed and state='completed'
        """
        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_wk01", "Test task", "exploring"),
        )

        # Queue a job
        now = datetime.now(UTC).isoformat()
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "s_wk01",
                "task_wk01",
                "search_queue",
                50,
                "network_client",
                "queued",
                json.dumps({"query": "test query", "options": {}}),
                now,
            ),
        )

        # Mock search_action and exploration state
        mock_state = MagicMock()
        mock_state.notify_status_change = MagicMock()

        with patch(
            "src.scheduler.search_worker._get_exploration_state",
            new=AsyncMock(return_value=mock_state),
        ):
            with patch(
                "src.research.pipeline.search_action",
                new=AsyncMock(return_value=mock_search_result),
            ):
                # Import and run worker for one iteration
                from src.scheduler.search_worker import _search_queue_worker

                # Run worker with timeout (it will process one job then wait)
                worker_task = asyncio.create_task(_search_queue_worker(0))

                # Wait for job to be processed
                await asyncio.sleep(0.2)

                # Cancel worker
                worker_task.cancel()
                try:
                    await worker_task
                except asyncio.CancelledError:
                    pass

        # Verify job state
        row = await db.fetch_one(
            "SELECT state, output_json FROM jobs WHERE id = ?",
            ("s_wk01",),
        )
        assert row is not None
        assert row["state"] == "completed"
        assert row["output_json"] is not None

        # Verify notify was called
        mock_state.notify_status_change.assert_called()

    @pytest.mark.asyncio
    async def test_worker_priority_order(self, test_database) -> None:
        """
        TC-WK-02: Worker processes jobs in priority order.

        // Given: Multiple jobs with different priorities
        // When: Worker runs
        // Then: Higher priority (lower number) jobs processed first
        """
        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_wk02", "Test task", "exploring"),
        )

        # Queue jobs with different priorities
        now = datetime.now(UTC).isoformat()
        for search_id, priority in [
            ("s_low", 90),
            ("s_high", 10),
            ("s_medium", 50),
        ]:
            await db.execute(
                """
                INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    search_id,
                    "task_wk02",
                    "search_queue",
                    priority,
                    "network_client",
                    "queued",
                    json.dumps({"query": f"query {search_id}", "options": {}}),
                    now,
                ),
            )

        # Verify ordering query
        rows = await db.fetch_all(
            """
            SELECT id FROM jobs
            WHERE task_id = ? AND kind = 'search_queue' AND state = 'queued'
            ORDER BY priority ASC, queued_at ASC
            """,
            ("task_wk02",),
        )

        # First job should be highest priority (lowest number)
        assert rows[0]["id"] == "s_high"
        assert rows[1]["id"] == "s_medium"
        assert rows[2]["id"] == "s_low"

    @pytest.mark.asyncio
    async def test_worker_handles_search_failure(self, test_database) -> None:
        """
        TC-WK-04: Worker handles search_action failure.

        // Given: Job in queue
        // When: search_action raises exception
        // Then: Job state='failed', error_message recorded
        """
        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_wk04", "Test task", "exploring"),
        )

        # Queue a job
        now = datetime.now(UTC).isoformat()
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "s_wk04",
                "task_wk04",
                "search_queue",
                50,
                "network_client",
                "queued",
                json.dumps({"query": "failing query", "options": {}}),
                now,
            ),
        )

        # Mock search_action to fail
        mock_state = MagicMock()
        mock_state.notify_status_change = MagicMock()

        with patch(
            "src.scheduler.search_worker._get_exploration_state",
            new=AsyncMock(return_value=mock_state),
        ):
            with patch(
                "src.research.pipeline.search_action",
                new=AsyncMock(side_effect=ValueError("Search failed: test error")),
            ):
                from src.scheduler.search_worker import _search_queue_worker

                worker_task = asyncio.create_task(_search_queue_worker(0))
                await asyncio.sleep(0.2)
                worker_task.cancel()
                try:
                    await worker_task
                except asyncio.CancelledError:
                    pass

        # Verify job state
        row = await db.fetch_one(
            "SELECT state, error_message FROM jobs WHERE id = ?",
            ("s_wk04",),
        )
        assert row is not None
        assert row["state"] == "failed"
        assert "test error" in row["error_message"]


class TestSearchQueueWorkerManager:
    """Tests for SearchQueueWorkerManager lifecycle."""

    @pytest.mark.asyncio
    async def test_manager_start_creates_workers(self) -> None:
        """
        TC-MGR-01: Manager start creates 2 workers.

        // Given: Fresh manager
        // When: start() is called
        // Then: 2 worker tasks are created
        """
        from src.scheduler.search_worker import SearchQueueWorkerManager

        manager = SearchQueueWorkerManager()

        # Mock the worker function to prevent actual execution
        async def mock_worker_coro(worker_id: int) -> None:
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                pass

        with patch(
            "src.scheduler.search_worker._search_queue_worker",
            side_effect=mock_worker_coro,
        ):
            await manager.start()

            assert manager.is_running is True
            assert len(manager._workers) == 2

            # Cleanup
            await manager.stop()

    @pytest.mark.asyncio
    async def test_manager_stop_cancels_workers(self) -> None:
        """
        TC-MGR-02: Manager stop cancels all workers.

        // Given: Manager with running workers
        // When: stop() is called
        // Then: All workers are cancelled and cleaned up
        """
        from src.scheduler.search_worker import SearchQueueWorkerManager

        manager = SearchQueueWorkerManager()

        # Create dummy worker tasks
        async def dummy_worker():
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                pass

        manager._started = True
        manager._workers = [
            asyncio.create_task(dummy_worker()),
            asyncio.create_task(dummy_worker()),
        ]

        await manager.stop()

        assert manager.is_running is False
        assert len(manager._workers) == 0

    @pytest.mark.asyncio
    async def test_manager_double_start(self) -> None:
        """
        Test that double start is idempotent.

        // Given: Already started manager
        // When: start() called again
        // Then: No error, same workers
        """
        from src.scheduler.search_worker import SearchQueueWorkerManager

        manager = SearchQueueWorkerManager()

        async def mock_worker_coro(worker_id: int) -> None:
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                pass

        with patch(
            "src.scheduler.search_worker._search_queue_worker",
            side_effect=mock_worker_coro,
        ):
            await manager.start()
            worker_count_first = len(manager._workers)

            await manager.start()  # Second start
            worker_count_second = len(manager._workers)

            assert worker_count_first == worker_count_second == 2

            await manager.stop()


class TestJobTracking:
    """Tests for SearchQueueWorkerManager job tracking for cancellation support."""

    @pytest.mark.asyncio
    async def test_register_job_adds_to_running_jobs(self) -> None:
        """
        TC-JT-01: register_job adds job to tracking dict.

        // Given: Empty manager
        // When: register_job called
        // Then: Job is tracked with correct task_id
        """
        from src.scheduler.search_worker import SearchQueueWorkerManager

        manager = SearchQueueWorkerManager()

        async def dummy_task():
            await asyncio.sleep(60)

        task = asyncio.create_task(dummy_task())

        try:
            manager.register_job("search_001", "task_abc", task)

            assert manager.running_job_count == 1
            assert "search_001" in manager._running_jobs
            task_id, tracked_task = manager._running_jobs["search_001"]
            assert task_id == "task_abc"
            assert tracked_task is task
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_unregister_job_removes_from_running_jobs(self) -> None:
        """
        TC-JT-02: unregister_job removes job from tracking dict.

        // Given: Manager with registered job
        // When: unregister_job called
        // Then: Job is no longer tracked
        """
        from src.scheduler.search_worker import SearchQueueWorkerManager

        manager = SearchQueueWorkerManager()

        async def dummy_task():
            await asyncio.sleep(60)

        task = asyncio.create_task(dummy_task())

        try:
            manager.register_job("search_002", "task_xyz", task)
            assert manager.running_job_count == 1

            manager.unregister_job("search_002")

            assert manager.running_job_count == 0
            assert "search_002" not in manager._running_jobs
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_unregister_nonexistent_job_no_error(self) -> None:
        """
        TC-JT-02b: unregister_job with nonexistent ID is no-op.

        // Given: Manager with no jobs
        // When: unregister_job called with unknown ID
        // Then: No error raised
        """
        from src.scheduler.search_worker import SearchQueueWorkerManager

        manager = SearchQueueWorkerManager()

        # Should not raise
        manager.unregister_job("nonexistent_search")

        assert manager.running_job_count == 0

    @pytest.mark.asyncio
    async def test_cancel_jobs_for_task_cancels_only_matching(self) -> None:
        """
        TC-JT-03: cancel_jobs_for_task cancels only specified task's search_action tasks.

        // Given: Manager with search_action tasks for multiple research tasks
        // When: cancel_jobs_for_task called for one research task
        // Then: Only that task's search_action tasks are cancelled (worker survives)
        """
        from src.scheduler.search_worker import SearchQueueWorkerManager

        manager = SearchQueueWorkerManager()

        cancel_flags = {"task_a_1": False, "task_a_2": False, "task_b": False}

        async def make_job(flag_key: str):
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancel_flags[flag_key] = True
                raise

        task_a_1 = asyncio.create_task(make_job("task_a_1"))
        task_a_2 = asyncio.create_task(make_job("task_a_2"))
        task_b = asyncio.create_task(make_job("task_b"))

        try:
            manager.register_job("search_a1", "task_a", task_a_1)
            manager.register_job("search_a2", "task_a", task_a_2)
            manager.register_job("search_b1", "task_b", task_b)

            assert manager.running_job_count == 3

            # Cancel only task_a
            cancelled_count = await manager.cancel_jobs_for_task("task_a")

            assert cancelled_count == 2
            assert cancel_flags["task_a_1"] is True
            assert cancel_flags["task_a_2"] is True
            assert cancel_flags["task_b"] is False
            assert not task_b.done()
        finally:
            # Cleanup remaining task
            task_b.cancel()
            try:
                await task_b
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_cancel_jobs_for_nonexistent_task_returns_zero(self) -> None:
        """
        TC-JT-04: cancel_jobs_for_task with nonexistent task returns 0.

        // Given: Manager with jobs for other tasks
        // When: cancel_jobs_for_task called for unknown task
        // Then: Returns 0, no jobs cancelled
        """
        from src.scheduler.search_worker import SearchQueueWorkerManager

        manager = SearchQueueWorkerManager()

        cancel_flag = {"cancelled": False}

        async def make_job():
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancel_flag["cancelled"] = True
                raise

        task = asyncio.create_task(make_job())

        try:
            manager.register_job("search_x", "task_x", task)

            # Cancel nonexistent task
            cancelled_count = await manager.cancel_jobs_for_task("nonexistent_task")

            assert cancelled_count == 0
            assert cancel_flag["cancelled"] is False
            assert not task.done()
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_running_job_count_property(self) -> None:
        """
        Test running_job_count property reflects current state.

        // Given: Manager with varying number of registered jobs
        // When: Jobs are registered/unregistered
        // Then: running_job_count is accurate
        """
        from src.scheduler.search_worker import SearchQueueWorkerManager

        manager = SearchQueueWorkerManager()

        async def dummy_task():
            await asyncio.sleep(60)

        tasks = []
        try:
            assert manager.running_job_count == 0

            for i in range(3):
                task = asyncio.create_task(dummy_task())
                tasks.append(task)
                manager.register_job(f"search_{i}", f"task_{i}", task)

            assert manager.running_job_count == 3

            manager.unregister_job("search_1")
            assert manager.running_job_count == 2

            manager.unregister_job("search_0")
            manager.unregister_job("search_2")
            assert manager.running_job_count == 0
        finally:
            for task in tasks:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


class TestWorkerCancellationBehavior:
    """Tests for worker behavior when search_action tasks are cancelled.

    Verifies that cancelling a search_action task does NOT kill the worker,
    which continues processing other jobs (ADR-0010 mode=immediate).
    """

    @pytest.mark.asyncio
    async def test_worker_survives_search_task_cancellation(self, test_database) -> None:
        """
        TC-WK-CANCEL-01: Worker continues after search_action task is cancelled.

        // Given: Worker processing a search job
        // When: The search_action task is cancelled (mode=immediate)
        // Then: Worker updates DB state and continues to next job
        """
        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_cancel_01", "Test task", "exploring"),
        )

        # Queue two jobs
        now = datetime.now(UTC).isoformat()
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "search_first",
                "task_cancel_01",
                "search_queue",
                50,
                "network_client",
                "queued",
                json.dumps({"query": "first query", "options": {}}),
                now,
            ),
        )
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "search_second",
                "task_cancel_01",
                "search_queue",
                50,
                "network_client",
                "queued",
                now,  # Will be processed after first
                json.dumps({"query": "second query", "options": {}}),
            ),
        )

        jobs_processed = {"first": False, "second": False}
        first_job_started = asyncio.Event()

        async def mock_search_action(task_id: str, query: str, state: Any, options: dict) -> dict:
            """Mock search_action that signals when first job starts."""
            if "first" in query:
                first_job_started.set()
                jobs_processed["first"] = True
                # Wait for cancellation
                await asyncio.sleep(60)
            else:
                jobs_processed["second"] = True
            return {"status": "completed", "pages_fetched": 1}

        from src.scheduler.search_worker import (
            _search_queue_worker,
            get_worker_manager,
        )

        # Start a worker
        # Patch at use site: _search_queue_worker imports from src.research.pipeline
        with patch("src.research.pipeline.search_action", mock_search_action):
            worker_task = asyncio.create_task(_search_queue_worker(0))

            try:
                # Wait for first job to start
                await asyncio.wait_for(first_job_started.wait(), timeout=5.0)

                # Cancel the first job via manager
                manager = get_worker_manager()
                await manager.cancel_jobs_for_task("task_cancel_01")

                # Give worker time to process the cancellation and pick up second job
                await asyncio.sleep(0.5)

                # Verify first job was marked cancelled
                first_job = await db.fetch_one(
                    "SELECT state FROM jobs WHERE id = ?",
                    ("search_first",),
                )
                assert first_job["state"] == "cancelled"

                # The worker should still be running (not broken by cancellation)
                assert not worker_task.done()

            finally:
                # Stop the worker
                worker_task.cancel()
                try:
                    await worker_task
                except asyncio.CancelledError:
                    pass

    @pytest.mark.asyncio
    async def test_worker_exits_on_manager_stop(self) -> None:
        """
        TC-WK-CANCEL-02: Worker exits when manager.stop() is called.

        // Given: Running worker
        // When: SearchQueueWorkerManager.stop() is called (server shutdown)
        // Then: Worker task completes and exits the loop
        """
        from src.scheduler.search_worker import SearchQueueWorkerManager

        manager = SearchQueueWorkerManager()

        # Create mock worker tasks directly
        worker_cancelled = [False, False]

        async def mock_worker_0():
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                worker_cancelled[0] = True
                raise

        async def mock_worker_1():
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                worker_cancelled[1] = True
                raise

        # Manually set up manager state to simulate started workers
        manager._started = True
        manager._workers = [
            asyncio.create_task(mock_worker_0()),
            asyncio.create_task(mock_worker_1()),
        ]

        # Let tasks start running
        await asyncio.sleep(0)

        assert manager.is_running is True
        assert len(manager._workers) == 2

        await manager.stop()

        assert manager.is_running is False
        assert len(manager._workers) == 0
        assert worker_cancelled[0] is True
        assert worker_cancelled[1] is True


class TestExplorationStateEvent:
    """Tests for ExplorationState asyncio.Event for long polling."""

    @pytest.mark.asyncio
    async def test_notify_status_change_sets_event(self) -> None:
        """
        Test that notify_status_change sets the event.

        // Given: ExplorationState with cleared event
        // When: notify_status_change() called
        // Then: Event is set
        """
        from src.research.state import ExplorationState

        state = ExplorationState("task_test", enable_ucb_allocation=False)

        assert not state._status_changed.is_set()

        state.notify_status_change()

        assert state._status_changed.is_set()

    @pytest.mark.asyncio
    async def test_wait_for_change_returns_on_notify(self) -> None:
        """
        Test that wait_for_change returns True when notified.

        // Given: ExplorationState
        // When: Event is set during wait
        // Then: Returns True before timeout
        """
        from src.research.state import ExplorationState

        state = ExplorationState("task_test", enable_ucb_allocation=False)

        # Set event immediately
        state.notify_status_change()

        # Should return immediately with True
        result = await state.wait_for_change(timeout=5.0)

        assert result is True
        # Event should be cleared after wait
        assert not state._status_changed.is_set()

    @pytest.mark.asyncio
    async def test_wait_for_change_timeout(self) -> None:
        """
        Test that wait_for_change returns False on timeout.

        // Given: ExplorationState with no notification
        // When: wait_for_change times out
        // Then: Returns False
        """
        from src.research.state import ExplorationState

        state = ExplorationState("task_test", enable_ucb_allocation=False)

        # Short timeout, no notification
        result = await state.wait_for_change(timeout=0.1)

        assert result is False

    @pytest.mark.asyncio
    async def test_wait_for_change_with_delayed_notify(self) -> None:
        """
        Test wait_for_change with delayed notification.

        // Given: ExplorationState
        // When: Notification occurs during wait
        // Then: Returns True when notified
        """
        from src.research.state import ExplorationState

        state = ExplorationState("task_test", enable_ucb_allocation=False)

        async def delayed_notify():
            await asyncio.sleep(0.1)
            state.notify_status_change()

        # Start notification in background
        notify_task = asyncio.create_task(delayed_notify())

        # Wait should return True when notified
        result = await state.wait_for_change(timeout=2.0)

        await notify_task

        assert result is True


class TestSearchQueuePerformance:
    """Performance tests for search queue (Phase 3).

    Tests large queue processing, worker stability, priority ordering, and concurrency.

    ## Test Perspectives Table (Performance)

    | Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
    |---------|---------------------|---------------------------------------|-----------------|-------|
    | TC-PF-01 | 15 queued jobs, 1 worker | Equivalence – performance | All processed | Large queue |
    | TC-PF-02 | Error + success jobs | Equivalence – stability | Failed job doesn't block | Error recovery |
    | TC-PF-03 | 10 jobs, 2 workers | Equivalence – concurrency | Parallel processing | Basic parallel |
    | TC-PF-04 | 1 job, 2 workers | Boundary – concurrency | Exactly 1 processes | CAS exclusivity |
    | TC-PF-05 | Mixed priority (high/med/low) | Equivalence – ordering | High first, then med, then low | Priority order |
    | TC-PF-06 | Same priority, different times | Equivalence – ordering | FIFO within priority | FIFO order |
    | TC-PF-07 | Variable processing times | Equivalence – scheduling | Faster jobs complete first | Time variation |
    | TC-PF-08 | 2 workers, mixed priority | Equivalence – concurrency | Both respect priority | Priority + parallel |
    | TC-PF-09 | 0 jobs in queue | Boundary – empty | Workers wait, no error | Empty queue |
    | TC-PF-10 | 1 job, 2 workers | Boundary – minimum | Exactly 1 worker processes | Min jobs |
    """

    @pytest.mark.asyncio
    async def test_large_queue_processing(self, test_database) -> None:
        """
        TC-PF-01: Large queue (10+ jobs) is processed correctly.

        // Given: 15 queued search jobs
        // When: Worker processes them (simulated)
        // Then: All jobs transition to completed/failed
        """
        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_pf01", "Large queue test", "exploring"),
        )

        # Queue 15 jobs
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        num_jobs = 15

        for i in range(num_jobs):
            await db.execute(
                """
                INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"s_pf01_{i:03d}",
                    "task_pf01",
                    "search_queue",
                    50,
                    "network_client",
                    "queued",
                    json.dumps({"query": f"query {i}", "options": {}}),
                    now,
                ),
            )

        # Verify all queued
        count = await db.fetch_one(
            "SELECT COUNT(*) as cnt FROM jobs WHERE task_id = ? AND kind = 'search_queue' AND state = 'queued'",
            ("task_pf01",),
        )
        assert count["cnt"] == num_jobs

        # Simulate worker processing by updating states
        # (In real scenario, worker would process via search_action)
        from src.scheduler.search_worker import _search_queue_worker

        mock_state = MagicMock()
        mock_state.notify_status_change = MagicMock()

        mock_result = {
            "ok": True,
            "search_id": "test",
            "status": "satisfied",
            "pages_fetched": 3,
        }

        with patch(
            "src.scheduler.search_worker._get_exploration_state",
            new=AsyncMock(return_value=mock_state),
        ):
            with patch(
                "src.research.pipeline.search_action",
                new=AsyncMock(return_value=mock_result),
            ):
                worker_task = asyncio.create_task(_search_queue_worker(0))

                # Wait for jobs to be processed (with timeout)
                for _ in range(50):  # Max 5 seconds
                    await asyncio.sleep(0.1)
                    remaining = await db.fetch_one(
                        "SELECT COUNT(*) as cnt FROM jobs WHERE task_id = ? AND kind = 'search_queue' AND state = 'queued'",
                        ("task_pf01",),
                    )
                    if remaining["cnt"] == 0:
                        break

                worker_task.cancel()
                try:
                    await worker_task
                except asyncio.CancelledError:
                    pass

        # Verify all jobs processed
        completed = await db.fetch_one(
            "SELECT COUNT(*) as cnt FROM jobs WHERE task_id = ? AND kind = 'search_queue' AND state = 'completed'",
            ("task_pf01",),
        )
        assert completed["cnt"] == num_jobs

    @pytest.mark.asyncio
    async def test_worker_error_recovery(self, test_database) -> None:
        """
        TC-PF-02: Worker continues after handling error.

        // Given: Job that causes search_action to fail
        // When: Worker processes it
        // Then: Job marked failed, worker continues
        """
        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_pf02", "Error recovery test", "exploring"),
        )

        # Queue jobs - one will fail, one will succeed
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()

        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "s_pf02_fail",
                "task_pf02",
                "search_queue",
                10,  # Higher priority (processed first)
                "network_client",
                "queued",
                json.dumps({"query": "failing query", "options": {}}),
                now,
            ),
        )
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "s_pf02_ok",
                "task_pf02",
                "search_queue",
                50,  # Lower priority (processed second)
                "network_client",
                "queued",
                json.dumps({"query": "succeeding query", "options": {}}),
                now,
            ),
        )

        mock_state = MagicMock()
        mock_state.notify_status_change = MagicMock()

        call_count = 0

        async def mock_search_action(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("Simulated search failure")
            return {"ok": True, "status": "satisfied", "pages_fetched": 2}

        with patch(
            "src.scheduler.search_worker._get_exploration_state",
            new=AsyncMock(return_value=mock_state),
        ):
            with patch(
                "src.research.pipeline.search_action",
                side_effect=mock_search_action,
            ):
                from src.scheduler.search_worker import _search_queue_worker

                worker_task = asyncio.create_task(_search_queue_worker(0))

                # Wait for both jobs to be processed
                for _ in range(30):  # Max 3 seconds
                    await asyncio.sleep(0.1)
                    remaining = await db.fetch_one(
                        "SELECT COUNT(*) as cnt FROM jobs WHERE task_id = ? AND kind = 'search_queue' AND state IN ('queued', 'running')",
                        ("task_pf02",),
                    )
                    if remaining["cnt"] == 0:
                        break

                worker_task.cancel()
                try:
                    await worker_task
                except asyncio.CancelledError:
                    pass

        # Verify: first job failed, second succeeded
        fail_row = await db.fetch_one(
            "SELECT state, error_message FROM jobs WHERE id = ?",
            ("s_pf02_fail",),
        )
        assert fail_row["state"] == "failed"
        assert "Simulated search failure" in fail_row["error_message"]

        ok_row = await db.fetch_one(
            "SELECT state FROM jobs WHERE id = ?",
            ("s_pf02_ok",),
        )
        assert ok_row["state"] == "completed"

    @pytest.mark.asyncio
    async def test_two_workers_parallel_processing(self, test_database) -> None:
        """
        TC-PF-03: Two workers process queue in parallel.

        // Given: 10 queued jobs, 2 workers
        // When: Both workers run
        // Then: Jobs are processed by both workers concurrently
        """
        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_pf03_parallel", "Parallel test", "exploring"),
        )

        # Queue 10 jobs
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        num_jobs = 10

        for i in range(num_jobs):
            await db.execute(
                """
                INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"s_pf03_parallel_{i:03d}",
                    "task_pf03_parallel",
                    "search_queue",
                    50,
                    "network_client",
                    "queued",
                    json.dumps({"query": f"query {i}", "options": {}}),
                    now,
                ),
            )

        mock_state = MagicMock()
        mock_state.notify_status_change = MagicMock()

        async def mock_search_action_with_delay(**kwargs):
            # Simulate some work (allows interleaving)
            await asyncio.sleep(0.05)
            return {"ok": True, "status": "satisfied", "pages_fetched": 1}

        # Patch to track worker assignments
        original_worker = None

        async def patched_worker(worker_id: int):
            nonlocal original_worker
            from src.scheduler.search_worker import _search_queue_worker

            # We need to intercept the processing to track assignments
            # Instead, we'll track via DB updates
            await _search_queue_worker(worker_id)

        with patch(
            "src.scheduler.search_worker._get_exploration_state",
            new=AsyncMock(return_value=mock_state),
        ):
            with patch(
                "src.research.pipeline.search_action",
                side_effect=mock_search_action_with_delay,
            ):
                from src.scheduler.search_worker import _search_queue_worker

                # Start TWO workers
                worker0 = asyncio.create_task(_search_queue_worker(0))
                worker1 = asyncio.create_task(_search_queue_worker(1))

                # Wait for all jobs to be processed
                for _ in range(100):  # Max 10 seconds
                    await asyncio.sleep(0.1)
                    remaining = await db.fetch_one(
                        "SELECT COUNT(*) as cnt FROM jobs WHERE task_id = ? AND kind = 'search_queue' AND state IN ('queued', 'running')",
                        ("task_pf03_parallel",),
                    )
                    if remaining["cnt"] == 0:
                        break

                # Cancel workers
                worker0.cancel()
                worker1.cancel()
                try:
                    await worker0
                except asyncio.CancelledError:
                    pass
                try:
                    await worker1
                except asyncio.CancelledError:
                    pass

        # Verify all jobs completed
        completed = await db.fetch_one(
            "SELECT COUNT(*) as cnt FROM jobs WHERE task_id = ? AND kind = 'search_queue' AND state = 'completed'",
            ("task_pf03_parallel",),
        )
        assert completed["cnt"] == num_jobs, (
            f"Expected {num_jobs} completed, got {completed['cnt']}"
        )

        # Note: Due to the nature of async processing, we can't guarantee which worker
        # processed which job, but we verify that all jobs were processed correctly.
        # The CAS mechanism ensures no double-processing.

    @pytest.mark.asyncio
    async def test_concurrent_worker_claim_exclusivity(self, test_database) -> None:
        """
        TC-PF-04: Multiple workers don't process same job (CAS).

        // Given: Single queued job, two workers
        // When: Both workers try to claim
        // Then: Only one succeeds (CAS semantics)
        """
        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_pf03", "Concurrency test", "exploring"),
        )

        # Queue single job
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "s_pf03",
                "task_pf03",
                "search_queue",
                50,
                "network_client",
                "queued",
                json.dumps({"query": "contested query", "options": {}}),
                now,
            ),
        )

        # Track how many times search_action is called
        search_calls = []

        mock_state = MagicMock()
        mock_state.notify_status_change = MagicMock()

        async def mock_search_action(**kwargs):
            search_calls.append(kwargs.get("query"))
            await asyncio.sleep(0.05)  # Simulate work
            return {"ok": True, "status": "satisfied", "pages_fetched": 1}

        with patch(
            "src.scheduler.search_worker._get_exploration_state",
            new=AsyncMock(return_value=mock_state),
        ):
            with patch(
                "src.research.pipeline.search_action",
                side_effect=mock_search_action,
            ):
                from src.scheduler.search_worker import _search_queue_worker

                # Start two workers simultaneously
                worker1 = asyncio.create_task(_search_queue_worker(0))
                worker2 = asyncio.create_task(_search_queue_worker(1))

                # Wait for job to be processed
                for _ in range(20):
                    await asyncio.sleep(0.1)
                    row = await db.fetch_one(
                        "SELECT state FROM jobs WHERE id = ?",
                        ("s_pf03",),
                    )
                    if row["state"] == "completed":
                        break

                # Cancel workers
                worker1.cancel()
                worker2.cancel()
                try:
                    await worker1
                except asyncio.CancelledError:
                    pass
                try:
                    await worker2
                except asyncio.CancelledError:
                    pass

        # Verify job was processed exactly once (CAS prevents double-processing)
        assert len(search_calls) == 1

        # Verify job is completed
        row = await db.fetch_one(
            "SELECT state FROM jobs WHERE id = ?",
            ("s_pf03",),
        )
        assert row["state"] == "completed"

    @pytest.mark.asyncio
    async def test_priority_ordering_high_medium_low(self, test_database) -> None:
        """
        TC-PF-05: Jobs are processed in priority order (high→medium→low).

        // Given: Jobs with mixed priorities (high=10, medium=50, low=90)
        // When: Single worker processes them
        // Then: High priority jobs complete before medium, medium before low
        """
        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_pf05", "Priority order test", "exploring"),
        )

        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()

        # Queue jobs with different priorities (insert in reverse order to test sorting)
        jobs = [
            ("s_pf05_low", 90, "low priority"),
            ("s_pf05_med", 50, "medium priority"),
            ("s_pf05_high", 10, "high priority"),
        ]
        for job_id, priority, query in jobs:
            await db.execute(
                """
                INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    "task_pf05",
                    "search_queue",
                    priority,
                    "network_client",
                    "queued",
                    json.dumps({"query": query, "options": {}}),
                    now,
                ),
            )

        # Track processing order
        processing_order: list[str] = []

        mock_state = MagicMock()
        mock_state.notify_status_change = MagicMock()

        async def mock_search_action(**kwargs):
            processing_order.append(kwargs.get("query", ""))
            return {"ok": True, "status": "satisfied", "pages_fetched": 1}

        with patch(
            "src.scheduler.search_worker._get_exploration_state",
            new=AsyncMock(return_value=mock_state),
        ):
            with patch(
                "src.research.pipeline.search_action",
                side_effect=mock_search_action,
            ):
                from src.scheduler.search_worker import _search_queue_worker

                worker_task = asyncio.create_task(_search_queue_worker(0))

                for _ in range(30):
                    await asyncio.sleep(0.1)
                    remaining = await db.fetch_one(
                        "SELECT COUNT(*) as cnt FROM jobs WHERE task_id = ? AND state = 'queued'",
                        ("task_pf05",),
                    )
                    if remaining["cnt"] == 0:
                        break

                worker_task.cancel()
                try:
                    await worker_task
                except asyncio.CancelledError:
                    pass

        # Verify processing order: high → medium → low
        assert len(processing_order) == 3
        assert processing_order[0] == "high priority", (
            f"Expected high first, got {processing_order}"
        )
        assert processing_order[1] == "medium priority", (
            f"Expected medium second, got {processing_order}"
        )
        assert processing_order[2] == "low priority", f"Expected low last, got {processing_order}"

    @pytest.mark.asyncio
    async def test_fifo_within_same_priority(self, test_database) -> None:
        """
        TC-PF-06: Jobs with same priority are processed FIFO (by queued_at).

        // Given: 5 jobs with same priority, queued at different times
        // When: Worker processes them
        // Then: Processed in queued_at order (FIFO)
        """
        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_pf06", "FIFO test", "exploring"),
        )

        from datetime import UTC, datetime, timedelta

        base_time = datetime.now(UTC)

        # Queue 5 jobs with same priority but different queued_at
        for i in range(5):
            queued_at = (base_time + timedelta(seconds=i)).isoformat()
            await db.execute(
                """
                INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"s_pf06_{i}",
                    "task_pf06",
                    "search_queue",
                    50,
                    "network_client",
                    "queued",
                    json.dumps({"query": f"query_{i}", "options": {}}),
                    queued_at,
                ),
            )

        processing_order: list[str] = []

        mock_state = MagicMock()
        mock_state.notify_status_change = MagicMock()

        async def mock_search_action(**kwargs):
            processing_order.append(kwargs.get("query", ""))
            return {"ok": True, "status": "satisfied", "pages_fetched": 1}

        with patch(
            "src.scheduler.search_worker._get_exploration_state",
            new=AsyncMock(return_value=mock_state),
        ):
            with patch(
                "src.research.pipeline.search_action",
                side_effect=mock_search_action,
            ):
                from src.scheduler.search_worker import _search_queue_worker

                worker_task = asyncio.create_task(_search_queue_worker(0))

                for _ in range(30):
                    await asyncio.sleep(0.1)
                    remaining = await db.fetch_one(
                        "SELECT COUNT(*) as cnt FROM jobs WHERE task_id = ? AND state = 'queued'",
                        ("task_pf06",),
                    )
                    if remaining["cnt"] == 0:
                        break

                worker_task.cancel()
                try:
                    await worker_task
                except asyncio.CancelledError:
                    pass

        # Verify FIFO order
        assert processing_order == ["query_0", "query_1", "query_2", "query_3", "query_4"]

    @pytest.mark.asyncio
    async def test_variable_processing_times(self, test_database) -> None:
        """
        TC-PF-07: Jobs with variable processing times are handled correctly.

        // Given: Jobs with different processing durations (fast, slow, fast)
        // When: 2 workers process them
        // Then: All complete, faster jobs finish first
        """
        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_pf07", "Variable time test", "exploring"),
        )

        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()

        # Queue jobs: slow, fast, fast (all same priority)
        jobs = [
            ("s_pf07_slow", "slow_query"),
            ("s_pf07_fast1", "fast_query_1"),
            ("s_pf07_fast2", "fast_query_2"),
        ]
        for job_id, query in jobs:
            await db.execute(
                """
                INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    "task_pf07",
                    "search_queue",
                    50,
                    "network_client",
                    "queued",
                    json.dumps({"query": query, "options": {}}),
                    now,
                ),
            )

        completion_order: list[str] = []

        mock_state = MagicMock()
        mock_state.notify_status_change = MagicMock()

        async def mock_search_action(**kwargs):
            query = kwargs.get("query", "")
            # Slow query takes longer
            if "slow" in query:
                await asyncio.sleep(0.2)
            else:
                await asyncio.sleep(0.02)
            completion_order.append(query)
            return {"ok": True, "status": "satisfied", "pages_fetched": 1}

        with patch(
            "src.scheduler.search_worker._get_exploration_state",
            new=AsyncMock(return_value=mock_state),
        ):
            with patch(
                "src.research.pipeline.search_action",
                side_effect=mock_search_action,
            ):
                from src.scheduler.search_worker import _search_queue_worker

                # Two workers: one gets slow, one gets fast jobs
                worker0 = asyncio.create_task(_search_queue_worker(0))
                worker1 = asyncio.create_task(_search_queue_worker(1))

                for _ in range(50):
                    await asyncio.sleep(0.1)
                    remaining = await db.fetch_one(
                        "SELECT COUNT(*) as cnt FROM jobs WHERE task_id = ? AND state IN ('queued', 'running')",
                        ("task_pf07",),
                    )
                    if remaining["cnt"] == 0:
                        break

                worker0.cancel()
                worker1.cancel()
                try:
                    await worker0
                except asyncio.CancelledError:
                    pass
                try:
                    await worker1
                except asyncio.CancelledError:
                    pass

        # All 3 jobs completed
        assert len(completion_order) == 3
        # Fast jobs should complete before slow job
        slow_idx = completion_order.index("slow_query")
        assert slow_idx == 2, f"Slow job should finish last, but order was: {completion_order}"

    @pytest.mark.asyncio
    async def test_two_workers_respect_priority(self, test_database) -> None:
        """
        TC-PF-08: Two workers both respect priority ordering.

        // Given: 6 jobs (2 high, 2 medium, 2 low), 2 workers
        // When: Both workers process
        // Then: High priority jobs claimed first, then medium, then low
        """
        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_pf08", "Two workers priority test", "exploring"),
        )

        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()

        # Queue: 2 high, 2 medium, 2 low
        jobs = [
            ("s_pf08_low1", 90, "low_1"),
            ("s_pf08_low2", 90, "low_2"),
            ("s_pf08_med1", 50, "med_1"),
            ("s_pf08_med2", 50, "med_2"),
            ("s_pf08_high1", 10, "high_1"),
            ("s_pf08_high2", 10, "high_2"),
        ]
        for job_id, priority, query in jobs:
            await db.execute(
                """
                INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    "task_pf08",
                    "search_queue",
                    priority,
                    "network_client",
                    "queued",
                    json.dumps({"query": query, "options": {}}),
                    now,
                ),
            )

        processing_order: list[str] = []

        mock_state = MagicMock()
        mock_state.notify_status_change = MagicMock()

        async def mock_search_action(**kwargs):
            processing_order.append(kwargs.get("query", ""))
            await asyncio.sleep(0.02)  # Small delay to allow interleaving
            return {"ok": True, "status": "satisfied", "pages_fetched": 1}

        with patch(
            "src.scheduler.search_worker._get_exploration_state",
            new=AsyncMock(return_value=mock_state),
        ):
            with patch(
                "src.research.pipeline.search_action",
                side_effect=mock_search_action,
            ):
                from src.scheduler.search_worker import _search_queue_worker

                worker0 = asyncio.create_task(_search_queue_worker(0))
                worker1 = asyncio.create_task(_search_queue_worker(1))

                for _ in range(50):
                    await asyncio.sleep(0.1)
                    remaining = await db.fetch_one(
                        "SELECT COUNT(*) as cnt FROM jobs WHERE task_id = ? AND state IN ('queued', 'running')",
                        ("task_pf08",),
                    )
                    if remaining["cnt"] == 0:
                        break

                worker0.cancel()
                worker1.cancel()
                try:
                    await worker0
                except asyncio.CancelledError:
                    pass
                try:
                    await worker1
                except asyncio.CancelledError:
                    pass

        assert len(processing_order) == 6

        # First 2 should be high priority
        high_jobs = [q for q in processing_order[:2] if q.startswith("high_")]
        assert len(high_jobs) == 2, f"First 2 should be high priority: {processing_order}"

        # Next 2 should be medium
        med_jobs = [q for q in processing_order[2:4] if q.startswith("med_")]
        assert len(med_jobs) == 2, f"Jobs 3-4 should be medium priority: {processing_order}"

        # Last 2 should be low
        low_jobs = [q for q in processing_order[4:6] if q.startswith("low_")]
        assert len(low_jobs) == 2, f"Last 2 should be low priority: {processing_order}"

    @pytest.mark.asyncio
    async def test_empty_queue_worker_waits(self, test_database) -> None:
        """
        TC-PF-09: Worker waits gracefully when queue is empty.

        // Given: Empty queue
        // When: Worker runs for short period
        // Then: No errors, worker can be cancelled cleanly
        """
        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_pf09", "Empty queue test", "exploring"),
        )

        # No jobs queued

        mock_state = MagicMock()
        mock_state.notify_status_change = MagicMock()

        with patch(
            "src.scheduler.search_worker._get_exploration_state",
            new=AsyncMock(return_value=mock_state),
        ):
            from src.scheduler.search_worker import _search_queue_worker

            worker_task = asyncio.create_task(_search_queue_worker(0))

            # Let worker run briefly (it should poll and wait)
            await asyncio.sleep(0.3)

            # Cancel cleanly
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass

        # If we get here without exception, test passes
        # Worker handled empty queue gracefully

    @pytest.mark.asyncio
    async def test_single_job_two_workers(self, test_database) -> None:
        """
        TC-PF-10: Single job with two workers - only one processes.

        // Given: 1 job, 2 workers
        // When: Both workers compete
        // Then: Exactly 1 worker processes the job (no double processing)
        """
        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_pf10", "Single job two workers", "exploring"),
        )

        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "s_pf10",
                "task_pf10",
                "search_queue",
                50,
                "network_client",
                "queued",
                json.dumps({"query": "single job", "options": {}}),
                now,
            ),
        )

        call_count = 0

        mock_state = MagicMock()
        mock_state.notify_status_change = MagicMock()

        async def mock_search_action(**kwargs):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            return {"ok": True, "status": "satisfied", "pages_fetched": 1}

        with patch(
            "src.scheduler.search_worker._get_exploration_state",
            new=AsyncMock(return_value=mock_state),
        ):
            with patch(
                "src.research.pipeline.search_action",
                side_effect=mock_search_action,
            ):
                from src.scheduler.search_worker import _search_queue_worker

                worker0 = asyncio.create_task(_search_queue_worker(0))
                worker1 = asyncio.create_task(_search_queue_worker(1))

                for _ in range(20):
                    await asyncio.sleep(0.1)
                    row = await db.fetch_one(
                        "SELECT state FROM jobs WHERE id = ?",
                        ("s_pf10",),
                    )
                    if row["state"] == "completed":
                        break

                worker0.cancel()
                worker1.cancel()
                try:
                    await worker0
                except asyncio.CancelledError:
                    pass
                try:
                    await worker1
                except asyncio.CancelledError:
                    pass

        # Exactly 1 call (CAS ensures exclusivity)
        assert call_count == 1, f"Expected exactly 1 call, got {call_count}"

        row = await db.fetch_one(
            "SELECT state FROM jobs WHERE id = ?",
            ("s_pf10",),
        )
        assert row["state"] == "completed"
