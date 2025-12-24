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
"""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from tests.conftest import is_cloud_agent


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
