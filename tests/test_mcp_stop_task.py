"""Tests for stop_task MCP tool with mode parameter.

Tests the stop_task tool's graceful/immediate mode per ADR-0010.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-ST-01 | mode=graceful, queued jobs | Equivalence – normal | queued → cancelled | graceful basic |
| TC-ST-02 | mode=immediate, queued jobs | Equivalence – normal | queued → cancelled | immediate basic |
| TC-ST-03 | mode=immediate, running jobs | Equivalence – normal | running → cancelled | immediate cancel |
| TC-ST-04 | mode not specified | Boundary – default | graceful behavior | default value |
| TC-ST-05 | mode=invalid | Boundary – invalid | InvalidParamsError | invalid input |
| TC-ST-06 | empty queue | Boundary – empty | normal completion | no jobs to cancel |
| TC-ST-07 | mode=graceful, running jobs | Equivalence – normal | running NOT cancelled | graceful waits |
| TC-ST-08 | missing task_id | Boundary – NULL | InvalidParamsError | validation |
| TC-ST-09 | nonexistent task_id | Equivalence – error | TaskNotFoundError | validation |
| TC-ST-10 | immediate + running worker | Equivalence – cancel | Worker task cancelled | real cancellation |
| TC-ST-11 | cancel then complete race | Equivalence – race | completed not overwritten | race prevention |
| TC-ST-12 | stop_task with pending auth | Equivalence – normal | Auth items cancelled | Auth queue cancellation |
| TC-ST-13 | stop_task with no auth items | Boundary – empty | No error, 0 cancelled | Empty auth queue |
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from src.storage.database import Database

pytestmark = pytest.mark.integration


class TestStopTaskModeValidation:
    """Tests for stop_task mode parameter validation."""

    @pytest.mark.asyncio
    async def test_missing_task_id_raises_error(self, test_database: Database) -> None:
        """
        TC-ST-08: Missing task_id raises InvalidParamsError.

        // Given: stop_task called without task_id
        // When: Handler is invoked
        // Then: InvalidParamsError is raised
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.tools.task import handle_stop_task as _handle_stop_task

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_stop_task({})

        assert exc_info.value.details.get("param_name") == "task_id"

    @pytest.mark.asyncio
    async def test_nonexistent_task_raises_error(self, test_database: Database) -> None:
        """
        TC-ST-09: Non-existent task_id raises TaskNotFoundError.

        // Given: stop_task with non-existent task
        // When: Handler is invoked
        // Then: TaskNotFoundError is raised
        """
        from src.mcp.errors import TaskNotFoundError
        from src.mcp.tools.task import handle_stop_task as _handle_stop_task

        with pytest.raises(TaskNotFoundError) as exc_info:
            await _handle_stop_task({"task_id": "nonexistent_task"})

        assert "nonexistent_task" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_invalid_mode_raises_error(self, test_database: Database) -> None:
        """
        TC-ST-05: Invalid mode value raises InvalidParamsError.

        // Given: stop_task with invalid mode
        // When: Handler is invoked
        // Then: InvalidParamsError is raised
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.tools.task import handle_stop_task as _handle_stop_task

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_st05", "Test task", "exploring"),
        )

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_stop_task(
                {
                    "task_id": "task_st05",
                    "mode": "invalid_mode",
                }
            )

        assert exc_info.value.details.get("param_name") == "mode"


class TestStopTaskGracefulMode:
    """Tests for stop_task with mode=graceful."""

    @pytest.mark.asyncio
    async def test_graceful_cancels_queued_jobs(self, test_database: Database) -> None:
        """
        TC-ST-01: mode=graceful cancels queued jobs.

        // Given: Task with queued search jobs
        // When: stop_task(mode=graceful)
        // Then: Queued jobs are cancelled
        """
        from src.mcp.tools.task import handle_stop_task as _handle_stop_task

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_st01", "Test task", "exploring"),
        )

        # Queue some jobs
        now = datetime.now(UTC).isoformat()
        for i in range(3):
            await db.execute(
                """
                INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"s_st01_{i}",
                    "task_st01",
                    "search_queue",
                    50,
                    "network_client",
                    "queued",
                    json.dumps({"query": f"query {i}", "options": {}}),
                    now,
                ),
            )

        result = await _handle_stop_task(
            {
                "task_id": "task_st01",
                "mode": "graceful",
            }
        )

        assert result["ok"] is True
        assert result["mode"] == "graceful"

        # Verify all queued jobs are cancelled
        rows = await db.fetch_all(
            "SELECT state FROM jobs WHERE task_id = ? AND kind = 'search_queue'",
            ("task_st01",),
        )
        for row in rows:
            assert row["state"] == "cancelled"

    @pytest.mark.asyncio
    async def test_graceful_does_not_cancel_running_jobs(self, test_database: Database) -> None:
        """
        TC-ST-07: mode=graceful does NOT cancel running jobs.

        // Given: Task with running search job
        // When: stop_task(mode=graceful)
        // Then: Running job state is preserved
        """
        from src.mcp.tools.task import handle_stop_task as _handle_stop_task

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_st07", "Test task", "exploring"),
        )

        # Add a running job
        now = datetime.now(UTC).isoformat()
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at, started_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "s_st07_running",
                "task_st07",
                "search_queue",
                50,
                "network_client",
                "running",
                json.dumps({"query": "running query", "options": {}}),
                now,
                now,
            ),
        )

        await _handle_stop_task(
            {
                "task_id": "task_st07",
                "mode": "graceful",
            }
        )

        # Verify running job is NOT cancelled
        row = await db.fetch_one(
            "SELECT state FROM jobs WHERE id = ?",
            ("s_st07_running",),
        )
        assert row is not None
        assert row["state"] == "running"

    @pytest.mark.asyncio
    async def test_default_mode_is_graceful(self, test_database: Database) -> None:
        """
        TC-ST-04: Default mode is graceful when not specified.

        // Given: Task with queued job
        // When: stop_task without mode
        // Then: Behaves as graceful (queued cancelled, running preserved)
        """
        from src.mcp.tools.task import handle_stop_task as _handle_stop_task

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_st04", "Test task", "exploring"),
        )

        # Add both queued and running jobs
        now = datetime.now(UTC).isoformat()
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "s_st04_queued",
                "task_st04",
                "search_queue",
                50,
                "network_client",
                "queued",
                json.dumps({"query": "queued", "options": {}}),
                now,
            ),
        )
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at, started_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "s_st04_running",
                "task_st04",
                "search_queue",
                50,
                "network_client",
                "running",
                json.dumps({"query": "running", "options": {}}),
                now,
                now,
            ),
        )

        result = await _handle_stop_task(
            {
                "task_id": "task_st04",
                # mode not specified
            }
        )

        assert result["mode"] == "graceful"

        # Queued should be cancelled
        queued_row = await db.fetch_one(
            "SELECT state FROM jobs WHERE id = ?",
            ("s_st04_queued",),
        )
        assert queued_row is not None
        assert queued_row["state"] == "cancelled"

        # Running should be preserved
        running_row = await db.fetch_one(
            "SELECT state FROM jobs WHERE id = ?",
            ("s_st04_running",),
        )
        assert running_row is not None
        assert running_row["state"] == "running"


class TestStopTaskImmediateMode:
    """Tests for stop_task with mode=immediate."""

    @pytest.mark.asyncio
    async def test_immediate_cancels_queued_jobs(self, test_database: Database) -> None:
        """
        TC-ST-02: mode=immediate cancels queued jobs.

        // Given: Task with queued search jobs
        // When: stop_task(mode=immediate)
        // Then: Queued jobs are cancelled
        """
        from src.mcp.tools.task import handle_stop_task as _handle_stop_task

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_st02", "Test task", "exploring"),
        )

        # Queue jobs
        now = datetime.now(UTC).isoformat()
        for i in range(2):
            await db.execute(
                """
                INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"s_st02_{i}",
                    "task_st02",
                    "search_queue",
                    50,
                    "network_client",
                    "queued",
                    json.dumps({"query": f"query {i}", "options": {}}),
                    now,
                ),
            )

        result = await _handle_stop_task(
            {
                "task_id": "task_st02",
                "mode": "immediate",
            }
        )

        assert result["ok"] is True
        assert result["mode"] == "immediate"

        # Verify all jobs are cancelled
        rows = await db.fetch_all(
            "SELECT state FROM jobs WHERE task_id = ? AND kind = 'search_queue'",
            ("task_st02",),
        )
        for row in rows:
            assert row["state"] == "cancelled"

    @pytest.mark.asyncio
    async def test_immediate_cancels_running_jobs(self, test_database: Database) -> None:
        """
        TC-ST-03: mode=immediate cancels running jobs.

        // Given: Task with running search job
        // When: stop_task(mode=immediate)
        // Then: Running job is cancelled, state='cancelled'
        """
        from src.mcp.tools.task import handle_stop_task as _handle_stop_task

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_st03", "Test task", "exploring"),
        )

        # Add a running job
        now = datetime.now(UTC).isoformat()
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at, started_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "s_st03_running",
                "task_st03",
                "search_queue",
                50,
                "network_client",
                "running",
                json.dumps({"query": "running query", "options": {}}),
                now,
                now,
            ),
        )

        result = await _handle_stop_task(
            {
                "task_id": "task_st03",
                "mode": "immediate",
            }
        )

        assert result["ok"] is True
        assert result["mode"] == "immediate"

        # Verify running job is cancelled
        row = await db.fetch_one(
            "SELECT state, finished_at FROM jobs WHERE id = ?",
            ("s_st03_running",),
        )
        assert row is not None
        assert row["state"] == "cancelled"
        assert row["finished_at"] is not None


class TestStopTaskFullMode:
    """Tests for stop_task with mode=full."""

    @pytest.mark.asyncio
    async def test_full_mode_cancels_all_jobs(self, test_database: Database) -> None:
        """
        TC-ST-FULL-01: mode=full cancels both queued and running jobs.

        // Given: Task with both queued and running jobs
        // When: stop_task(mode=full)
        // Then: All jobs are cancelled
        """
        from src.mcp.tools.task import handle_stop_task as _handle_stop_task

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_full_01", "Test task", "exploring"),
        )

        # Add queued and running jobs
        now = datetime.now(UTC).isoformat()
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "s_full_01_queued",
                "task_full_01",
                "search_queue",
                50,
                "network_client",
                "queued",
                json.dumps({"query": "queued query", "options": {}}),
                now,
            ),
        )
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at, started_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "s_full_01_running",
                "task_full_01",
                "search_queue",
                50,
                "network_client",
                "running",
                json.dumps({"query": "running query", "options": {}}),
                now,
                now,
            ),
        )

        result = await _handle_stop_task(
            {
                "task_id": "task_full_01",
                "mode": "full",
            }
        )

        assert result["ok"] is True
        assert result["mode"] == "full"

        # Verify all jobs are cancelled
        rows = await db.fetch_all(
            "SELECT state FROM jobs WHERE task_id = ? AND kind = 'search_queue'",
            ("task_full_01",),
        )
        for row in rows:
            assert row["state"] == "cancelled"


class TestStopTaskEmptyQueue:
    """Tests for stop_task with empty queue."""

    @pytest.mark.asyncio
    async def test_empty_queue_completes_normally(self, test_database: Database) -> None:
        """
        TC-ST-06: Empty queue completes normally.

        // Given: Task with no search jobs
        // When: stop_task is called
        // Then: Completes without error
        """
        from src.mcp.tools.task import handle_stop_task as _handle_stop_task

        db = test_database

        # Create task with no jobs
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_st06", "Test task", "exploring"),
        )

        result = await _handle_stop_task(
            {
                "task_id": "task_st06",
                "mode": "immediate",
            }
        )

        assert result["ok"] is True
        assert result["task_id"] == "task_st06"


class TestStopTaskToolDefinition:
    """Tests for stop_task tool definition."""

    def test_stop_task_has_mode_parameter(self) -> None:
        """
        Test that stop_task tool has mode parameter in schema.

        // Given: TOOLS list
        // When: Looking at stop_task schema
        // Then: mode parameter is defined with enum
        """
        from src.mcp.server import TOOLS

        stop_task_tool = next(t for t in TOOLS if t.name == "stop_task")
        assert "mode" in stop_task_tool.inputSchema["properties"]
        assert stop_task_tool.inputSchema["properties"]["mode"]["enum"] == [
            "graceful",
            "immediate",
            "full",
        ]
        assert stop_task_tool.inputSchema["properties"]["mode"]["default"] == "graceful"


class TestStopTaskRealCancellation:
    """Tests for stop_task with real worker task cancellation.

    These tests verify that mode=immediate actually cancels running asyncio tasks,
    not just updating DB state.
    """

    @pytest.mark.asyncio
    async def test_immediate_cancels_running_search_task(self, test_database: Database) -> None:
        """
        TC-ST-10: mode=immediate cancels running search_action task.

        // Given: Task with a registered search_action task in SearchQueueWorkerManager
        // When: stop_task(mode=immediate)
        // Then: The search_action asyncio.Task is cancelled (worker survives)
        """
        import asyncio

        from src.scheduler.search_worker import SearchQueueWorkerManager

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_st10", "Test task", "exploring"),
        )

        # Create manager
        manager = SearchQueueWorkerManager()
        cancel_flag = {"cancelled": False}
        search_id = "s_st10_running"

        # Create a mock search_action task (not the worker itself)
        # The worker wraps search_action in create_task() and registers that task
        async def mock_search_action() -> None:
            try:
                await asyncio.sleep(60)  # Long sleep
            except asyncio.CancelledError:
                cancel_flag["cancelled"] = True
                raise
            finally:
                # Mimic real worker's finally block
                manager.unregister_job(search_id)

        search_task = asyncio.create_task(mock_search_action())
        manager.register_job(search_id, "task_st10", search_task)

        # Verify job is registered
        assert manager.running_job_count == 1

        # Cancel jobs for task
        cancelled_count = await manager.cancel_jobs_for_task("task_st10")

        # Verify cancellation (wiring check)
        assert cancelled_count == 1
        assert cancel_flag["cancelled"] is True
        assert search_task.cancelled() or search_task.done()
        # Verify unregistration (effect check: worker's finally block calls unregister_job)
        assert manager.running_job_count == 0

    @pytest.mark.asyncio
    async def test_cancel_does_not_affect_other_tasks(self, test_database: Database) -> None:
        """
        TC-ST-10b: Cancellation only affects the specified task's search_action tasks.

        // Given: Multiple tasks with running search_action tasks
        // When: stop_task(mode=immediate) for one task
        // Then: Only that task's search_action tasks are cancelled
        """
        import asyncio

        from src.scheduler.search_worker import SearchQueueWorkerManager

        db = test_database

        # Create tasks
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_st10_a", "Test task A", "exploring"),
        )
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_st10_b", "Test task B", "exploring"),
        )

        # Create manager with search_action tasks for both research tasks
        manager = SearchQueueWorkerManager()

        search_a_cancelled = {"cancelled": False}
        search_b_cancelled = {"cancelled": False}
        search_id_a = "s_task_a"
        search_id_b = "s_task_b"

        # Mock search_action tasks (worker wraps these in create_task)
        async def search_action_a() -> None:
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                search_a_cancelled["cancelled"] = True
                raise
            finally:
                manager.unregister_job(search_id_a)

        async def search_action_b() -> None:
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                search_b_cancelled["cancelled"] = True
                raise
            finally:
                manager.unregister_job(search_id_b)

        search_task_a = asyncio.create_task(search_action_a())
        search_task_b = asyncio.create_task(search_action_b())

        manager.register_job(search_id_a, "task_st10_a", search_task_a)
        manager.register_job(search_id_b, "task_st10_b", search_task_b)

        assert manager.running_job_count == 2

        # Cancel only task A's search
        cancelled_count = await manager.cancel_jobs_for_task("task_st10_a")

        # Verify only task A's search was cancelled (wiring check)
        assert cancelled_count == 1
        assert search_a_cancelled["cancelled"] is True
        assert search_b_cancelled["cancelled"] is False
        assert not search_task_b.done()
        # Verify only task A was unregistered (effect check)
        assert manager.running_job_count == 1

        # Cleanup task B
        search_task_b.cancel()
        try:
            await search_task_b
        except asyncio.CancelledError:
            pass
        assert manager.running_job_count == 0


class TestStopTaskRaceCondition:
    """Tests for stop_task race condition prevention.

    These tests verify that concurrent cancel and complete operations
    don't overwrite each other incorrectly.
    """

    @pytest.mark.asyncio
    async def test_completed_not_overwritten_after_cancel(self, test_database: Database) -> None:
        """
        TC-ST-11: Completed state is not written if job was already cancelled.

        // Given: Job is in 'cancelled' state (simulating race)
        // When: Worker tries to write 'completed'
        // Then: The state remains 'cancelled' (conditional UPDATE prevents overwrite)
        """
        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_st11", "Test task", "exploring"),
        )

        # Create a job that is already cancelled (simulating race condition)
        now = datetime.now(UTC).isoformat()
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "s_st11_cancelled",
                "task_st11",
                "search_queue",
                50,
                "network_client",
                "cancelled",  # Already cancelled
                json.dumps({"query": "test", "options": {}}),
                now,
                now,
            ),
        )

        # Simulate worker trying to complete the job (conditional UPDATE)
        cursor = await db.execute(
            """
            UPDATE jobs
            SET state = 'completed', finished_at = ?, output_json = ?
            WHERE id = ? AND state = 'running'
            """,
            (
                datetime.now(UTC).isoformat(),
                json.dumps({"ok": True}),
                "s_st11_cancelled",
            ),
        )

        # Verify: rowcount should be 0 (no rows updated)
        assert getattr(cursor, "rowcount", 0) == 0

        # Verify state is still 'cancelled'
        row = await db.fetch_one(
            "SELECT state FROM jobs WHERE id = ?",
            ("s_st11_cancelled",),
        )
        assert row is not None
        assert row["state"] == "cancelled"

    @pytest.mark.asyncio
    async def test_failed_not_overwritten_after_cancel(self, test_database: Database) -> None:
        """
        TC-ST-11b: Failed state is not written if job was already cancelled.

        // Given: Job is in 'cancelled' state
        // When: Worker tries to write 'failed'
        // Then: The state remains 'cancelled'
        """
        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_st11b", "Test task", "exploring"),
        )

        # Create a job that is already cancelled
        now = datetime.now(UTC).isoformat()
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "s_st11b_cancelled",
                "task_st11b",
                "search_queue",
                50,
                "network_client",
                "cancelled",
                json.dumps({"query": "test", "options": {}}),
                now,
                now,
            ),
        )

        # Simulate worker trying to mark as failed (conditional UPDATE)
        cursor = await db.execute(
            """
            UPDATE jobs
            SET state = 'failed', finished_at = ?, error_message = ?
            WHERE id = ? AND state = 'running'
            """,
            (
                datetime.now(UTC).isoformat(),
                "Simulated error",
                "s_st11b_cancelled",
            ),
        )

        # Verify: rowcount should be 0
        assert getattr(cursor, "rowcount", 0) == 0

        # Verify state is still 'cancelled'
        row = await db.fetch_one(
            "SELECT state FROM jobs WHERE id = ?",
            ("s_st11b_cancelled",),
        )
        assert row is not None
        assert row["state"] == "cancelled"


class TestStopTaskAuthQueueCancellation:
    """Tests for stop_task auth queue cancellation per ADR-0007."""

    @pytest.mark.asyncio
    async def test_stop_task_cancels_pending_auth_items(self, test_database: Database) -> None:
        """
        TC-ST-12: stop_task cancels pending auth queue items.

        // Given: Task with pending authentication queue items
        // When: stop_task is called
        // Then: Auth queue items are marked as cancelled
        """
        from src.mcp.tools.task import handle_stop_task as _handle_stop_task
        from src.utils.intervention_queue import get_intervention_queue

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_st12", "Test task", "exploring"),
        )

        # Add pending auth queue items
        queue = get_intervention_queue()
        queue._db = db  # Use test database

        queue_id1 = await queue.enqueue(
            task_id="task_st12",
            url="https://example.com/page1",
            domain="example.com",
            auth_type="captcha",
        )
        queue_id2 = await queue.enqueue(
            task_id="task_st12",
            url="https://test.org/page1",
            domain="test.org",
            auth_type="cloudflare",
        )

        # Verify items are pending
        pending = await queue.get_pending(task_id="task_st12")
        assert len(pending) == 2

        # When: stop_task is called
        result = await _handle_stop_task(
            {
                "task_id": "task_st12",
                "mode": "graceful",
            }
        )

        # Then: Auth items should be cancelled
        assert result["ok"] is True

        # Verify items are cancelled
        item1 = await queue.get_item(queue_id1)
        item2 = await queue.get_item(queue_id2)
        assert item1 is not None
        assert item2 is not None
        assert (
            item1["status"] == "cancelled"
        ), f"Item 1 status should be cancelled, got {item1['status']}"
        assert (
            item2["status"] == "cancelled"
        ), f"Item 2 status should be cancelled, got {item2['status']}"

        # Verify no pending items remain
        pending_after = await queue.get_pending(task_id="task_st12")
        assert len(pending_after) == 0

    @pytest.mark.asyncio
    async def test_stop_task_with_no_auth_items(self, test_database: Database) -> None:
        """
        TC-ST-13: stop_task with no auth items completes normally.

        // Given: Task with no auth queue items
        // When: stop_task is called
        // Then: Completes without error
        """
        from src.mcp.tools.task import handle_stop_task as _handle_stop_task

        db = test_database

        # Create task with no auth items
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_st13", "Test task", "exploring"),
        )

        # When: stop_task is called
        result = await _handle_stop_task(
            {
                "task_id": "task_st13",
                "mode": "graceful",
            }
        )

        # Then: Should complete normally
        assert result["ok"] is True
        assert result["task_id"] == "task_st13"

    @pytest.mark.asyncio
    async def test_stop_task_cancels_in_progress_auth_items(self, test_database: Database) -> None:
        """
        Test that stop_task cancels in_progress auth items as well.

        // Given: Task with in_progress auth queue items
        // When: stop_task is called
        // Then: In-progress items are also cancelled
        """
        from src.mcp.tools.task import handle_stop_task as _handle_stop_task
        from src.utils.intervention_queue import get_intervention_queue

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_st12b", "Test task", "exploring"),
        )

        # Add auth queue items and mark as in_progress
        queue = get_intervention_queue()
        queue._db = db

        queue_id = await queue.enqueue(
            task_id="task_st12b",
            url="https://example.com/page",
            domain="example.com",
            auth_type="captcha",
        )

        # Mark as in_progress
        await queue.start_session(task_id="task_st12b")

        # Verify item is in_progress
        item = await queue.get_item(queue_id)
        assert item is not None
        assert item["status"] == "in_progress"

        # When: stop_task is called
        result = await _handle_stop_task(
            {
                "task_id": "task_st12b",
                "mode": "graceful",
            }
        )

        # Then: Item should be cancelled
        assert result["ok"] is True
        item_after = await queue.get_item(queue_id)
        assert item_after is not None
        assert item_after["status"] == "cancelled"
