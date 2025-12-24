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
"""

import json
from datetime import UTC, datetime

import pytest


class TestStopTaskModeValidation:
    """Tests for stop_task mode parameter validation."""

    @pytest.mark.asyncio
    async def test_missing_task_id_raises_error(self, test_database) -> None:
        """
        TC-ST-08: Missing task_id raises InvalidParamsError.

        // Given: stop_task called without task_id
        // When: Handler is invoked
        // Then: InvalidParamsError is raised
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.server import _handle_stop_task

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_stop_task({})

        assert exc_info.value.details.get("param_name") == "task_id"

    @pytest.mark.asyncio
    async def test_nonexistent_task_raises_error(self, test_database) -> None:
        """
        TC-ST-09: Non-existent task_id raises TaskNotFoundError.

        // Given: stop_task with non-existent task
        // When: Handler is invoked
        // Then: TaskNotFoundError is raised
        """
        from src.mcp.errors import TaskNotFoundError
        from src.mcp.server import _handle_stop_task

        with pytest.raises(TaskNotFoundError) as exc_info:
            await _handle_stop_task({"task_id": "nonexistent_task"})

        assert "nonexistent_task" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_invalid_mode_raises_error(self, test_database) -> None:
        """
        TC-ST-05: Invalid mode value raises InvalidParamsError.

        // Given: stop_task with invalid mode
        // When: Handler is invoked
        // Then: InvalidParamsError is raised
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.server import _handle_stop_task

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_st05", "Test task", "exploring"),
        )

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_stop_task({
                "task_id": "task_st05",
                "mode": "invalid_mode",
            })

        assert exc_info.value.details.get("param_name") == "mode"


class TestStopTaskGracefulMode:
    """Tests for stop_task with mode=graceful."""

    @pytest.mark.asyncio
    async def test_graceful_cancels_queued_jobs(self, test_database) -> None:
        """
        TC-ST-01: mode=graceful cancels queued jobs.

        // Given: Task with queued search jobs
        // When: stop_task(mode=graceful)
        // Then: Queued jobs are cancelled
        """
        from src.mcp.server import _handle_stop_task

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

        result = await _handle_stop_task({
            "task_id": "task_st01",
            "mode": "graceful",
        })

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
    async def test_graceful_does_not_cancel_running_jobs(self, test_database) -> None:
        """
        TC-ST-07: mode=graceful does NOT cancel running jobs.

        // Given: Task with running search job
        // When: stop_task(mode=graceful)
        // Then: Running job state is preserved
        """
        from src.mcp.server import _handle_stop_task

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

        await _handle_stop_task({
            "task_id": "task_st07",
            "mode": "graceful",
        })

        # Verify running job is NOT cancelled
        row = await db.fetch_one(
            "SELECT state FROM jobs WHERE id = ?",
            ("s_st07_running",),
        )
        assert row["state"] == "running"

    @pytest.mark.asyncio
    async def test_default_mode_is_graceful(self, test_database) -> None:
        """
        TC-ST-04: Default mode is graceful when not specified.

        // Given: Task with queued job
        // When: stop_task without mode
        // Then: Behaves as graceful (queued cancelled, running preserved)
        """
        from src.mcp.server import _handle_stop_task

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

        result = await _handle_stop_task({
            "task_id": "task_st04",
            # mode not specified
        })

        assert result["mode"] == "graceful"

        # Queued should be cancelled
        queued_row = await db.fetch_one(
            "SELECT state FROM jobs WHERE id = ?",
            ("s_st04_queued",),
        )
        assert queued_row["state"] == "cancelled"

        # Running should be preserved
        running_row = await db.fetch_one(
            "SELECT state FROM jobs WHERE id = ?",
            ("s_st04_running",),
        )
        assert running_row["state"] == "running"


class TestStopTaskImmediateMode:
    """Tests for stop_task with mode=immediate."""

    @pytest.mark.asyncio
    async def test_immediate_cancels_queued_jobs(self, test_database) -> None:
        """
        TC-ST-02: mode=immediate cancels queued jobs.

        // Given: Task with queued search jobs
        // When: stop_task(mode=immediate)
        // Then: Queued jobs are cancelled
        """
        from src.mcp.server import _handle_stop_task

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

        result = await _handle_stop_task({
            "task_id": "task_st02",
            "mode": "immediate",
        })

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
    async def test_immediate_cancels_running_jobs(self, test_database) -> None:
        """
        TC-ST-03: mode=immediate cancels running jobs.

        // Given: Task with running search job
        // When: stop_task(mode=immediate)
        // Then: Running job is cancelled, state='cancelled'
        """
        from src.mcp.server import _handle_stop_task

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

        result = await _handle_stop_task({
            "task_id": "task_st03",
            "mode": "immediate",
        })

        assert result["ok"] is True
        assert result["mode"] == "immediate"

        # Verify running job is cancelled
        row = await db.fetch_one(
            "SELECT state, finished_at FROM jobs WHERE id = ?",
            ("s_st03_running",),
        )
        assert row["state"] == "cancelled"
        assert row["finished_at"] is not None


class TestStopTaskEmptyQueue:
    """Tests for stop_task with empty queue."""

    @pytest.mark.asyncio
    async def test_empty_queue_completes_normally(self, test_database) -> None:
        """
        TC-ST-06: Empty queue completes normally.

        // Given: Task with no search jobs
        // When: stop_task is called
        // Then: Completes without error
        """
        from src.mcp.server import _handle_stop_task

        db = test_database

        # Create task with no jobs
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_st06", "Test task", "exploring"),
        )

        result = await _handle_stop_task({
            "task_id": "task_st06",
            "mode": "immediate",
        })

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
        ]
        assert stop_task_tool.inputSchema["properties"]["mode"]["default"] == "graceful"

